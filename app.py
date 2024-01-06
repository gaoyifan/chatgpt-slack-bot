import logging
import os
import asyncio
from slack_bolt.async_app import AsyncApp, AsyncBoltContext, AsyncSay
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_slack_response import AsyncSlackResponse
from slack_sdk.web.async_client import AsyncWebClient
from pprint import pprint
from typing import Dict, List, Annotated
from datetime import datetime
from openai_wrapper import OpenAIWrapper
from pony.orm import *

from plugins.browsing import browser_text, github, pdf, youtube

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
slack = AsyncApp(token=os.environ.get("SLACK_BOT_TOKEN"))
openai = OpenAIWrapper()
db = Database()


class SlackToolCallPrompt(db.Entity):
    ts = PrimaryKey(str)
    channel = Required(str)
    thread_ts = Optional(str)
    prompts = Required(Json)


db.bind(provider="sqlite", filename="db.sqlite", create_db=True)
db.generate_mapping(create_tables=True, check_tables=True)


@db_session
def get_tool_call_prompts(msg_ts):
    prompt = SlackToolCallPrompt.get(ts=msg_ts)
    return prompt.prompts if prompt else []


@db_session
def add_tool_call_prompts(channel, msg_ts, prompts, thread_ts=None):
    SlackToolCallPrompt(channel=channel, ts=msg_ts, thread_ts=thread_ts, prompts=prompts)


def generate_prompts(thread_msgs: List[Dict], channel: str):
    yield {"role": "system", "content": "You are a helpful assistant."}
    for msg in thread_msgs:
        for p in get_tool_call_prompts(msg["ts"]):
            yield p
        if "bot_id" in msg:
            yield {"role": "assistant", "content": msg["text"]}
        elif "user" in msg:
            yield {"role": "user", "content": msg["text"]}
        else:
            print("Unknown message type")


@slack.event("message")
async def message_handler(context: AsyncBoltContext, event: Dict, say: AsyncSay, client: AsyncWebClient):
    logging.debug("event: %s", event)
    if "hidden" in event:
        logging.debug("hidden message")
        return
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    try:
        thread_msgs = await client.conversations_replies(channel=channel, ts=thread_ts)
    except SlackApiError:
        logging.error("Failed to fetch thread messages. channel: %s, ts: %s", channel, thread_ts)
        pprint(event)
    prompts = list(generate_prompts(thread_msgs["messages"], channel))
    response = ""
    last_send_time = datetime.now()
    old_prompts_len = len(prompts)
    response_msg = await say("(Thinking...)", thread_ts=thread_ts, username="AI Assistant")
    try:
        async for delta in openai.generate_reply(prompts):
            response += delta
            if (datetime.now() - last_send_time).total_seconds() > 1:
                await client.chat_update(channel=channel, ts=response_msg["ts"], text=response)
                last_send_time = datetime.now()
    except Exception as e:
        response += f"(Exception when generating reply: {e})"
        logging.error("Exception when generating reply: %s", e)
        traceback.print_exc()
    if len(prompts) > old_prompts_len:  # new tool calls from assistant
        add_tool_call_prompts(channel, response_msg["ts"], prompts[old_prompts_len:], thread_ts)
    await client.chat_update(channel=channel, ts=response_msg["ts"], text=response)


# clear all messages in the IM
@slack.command("/clear")
async def clear_all_history(ack, body, client: AsyncWebClient):
    async def try_delete(channel, ts):
        try:
            await client.chat_delete(channel=channel, ts=ts)
        except Exception as e:
            pprint(e)

    await ack()
    h = await client.conversations_history(channel=body["channel_id"])
    for msg in h["messages"]:
        if msg.get("bot_id"):
            await try_delete(body["channel_id"], msg["ts"])
        else:
            replies = await client.conversations_replies(channel=body["channel_id"], ts=msg["ts"])
            for reply in replies["messages"]:
                await try_delete(body["channel_id"], reply["ts"])


async def main():
    openai.add_function(browser_text)
    openai.add_function(github)
    openai.add_function(pdf)
    openai.add_function(youtube)
    await AsyncSocketModeHandler(slack, os.environ["SLACK_APP_TOKEN"]).start_async()


if __name__ == "__main__":
    asyncio.run(main())
