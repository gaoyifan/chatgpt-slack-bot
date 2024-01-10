import asyncio
import logging
import os
import traceback
from datetime import datetime
from pprint import pprint
from typing import Dict, List

from pony.orm import *
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp, AsyncSay
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from database import db
from openai_wrapper import OpenAIWrapper
from plugins.browsing import browser_text, github, pdf
from plugins.youtube import youtube
from plugins.search import search

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
slack = AsyncApp(token=os.environ.get("SLACK_BOT_TOKEN"))
openai = OpenAIWrapper()


class SlackToolCallPrompt(db.Entity):
    ts = PrimaryKey(str)
    channel = Required(str)
    thread_ts = Optional(str)
    prompts = Required(Json)


@db_session
def get_tool_call_prompts(msg_ts):
    prompt = SlackToolCallPrompt.get(ts=msg_ts)
    return prompt.prompts if prompt else []


@db_session
def add_tool_call_prompts(channel, msg_ts, prompts, thread_ts=None):
    SlackToolCallPrompt(channel=channel, ts=msg_ts, thread_ts=thread_ts, prompts=prompts)


def generate_prompts(thread_msgs: List[Dict]):
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
async def message_handler(event: Dict, say: AsyncSay, client: AsyncWebClient):
    async def update_response():
        nonlocal response_msg, response, channel
        await client.chat_update(channel=channel, ts=response_msg["ts"], text=response)

    async def new_response(msg):
        nonlocal thread_ts
        return await say(msg, thread_ts=thread_ts, username="AI Assistant")

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
    prompts = list(generate_prompts(thread_msgs["messages"]))
    response = ""
    last_send_time = datetime.now()
    old_prompts_len = len(prompts)
    response_msg = await new_response("(Thinking...)")
    try:
        async for delta in openai.generate_reply(prompts):
            if len(response.encode("utf-8")) + len(delta.encode("utf-8")) > 3000:  # slack message length limit
                await update_response()
                response = delta
                response_msg = await new_response(response)
                last_send_time = datetime.now()
            else:
                response += delta
            if (datetime.now() - last_send_time).total_seconds() > 1:
                await update_response()
                last_send_time = datetime.now()
    except Exception as e:
        response += f"(Exception when generating reply: {e})"
        logging.error("Exception when generating reply: %s", e)
        traceback.print_exc()
    if len(prompts) > old_prompts_len:  # new tool calls from assistant
        add_tool_call_prompts(channel, response_msg["ts"], prompts[old_prompts_len:], thread_ts)
    await update_response()


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
    db.generate_mapping(create_tables=True, check_tables=True)
    openai.add_function(browser_text)
    openai.add_function(github)
    openai.add_function(pdf)
    openai.add_function(youtube)
    openai.add_function(search)
    await AsyncSocketModeHandler(slack, os.environ["SLACK_APP_TOKEN"]).start_async()


if __name__ == "__main__":
    asyncio.run(main())
