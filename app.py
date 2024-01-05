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

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
slack = AsyncApp(token=os.environ.get("SLACK_BOT_TOKEN"))
openai = OpenAIWrapper()


def gen_prompts(thread_msgs: List[Dict]):
    yield {"role": "system", "content": "You are a helpful assistant."}
    for message in thread_msgs:
        if "bot_id" in message:
            yield {"role": "assistant", "content": message["text"]}
        elif "user" in message:
            yield {"role": "user", "content": message["text"]}
        else:
            print("Unknown message type")


@slack.event("message")
async def reply_with_gpt(context: AsyncBoltContext, event: Dict, say: AsyncSay, client: AsyncWebClient):
    async def update_response():
        nonlocal slack_message, response, thread_ts
        if slack_message is None:
            slack_message = await say(response, thread_ts=thread_ts, username="AI Assistant")
        else:
            await client.chat_update(channel=slack_message["channel"], ts=slack_message["ts"], text=response)

    if "hidden" in event:
        print(context.bot_id)
        return
    thread_ts = event.get("thread_ts") or event["ts"]
    thread_msgs = await client.conversations_replies(channel=event["channel"], ts=thread_ts)
    prompts = list(gen_prompts(thread_msgs["messages"]))
    slack_message: AsyncSlackResponse = None
    response = ""
    last_send_time = datetime.now()
    async for delta in openai.generate_reply(prompts):
        response += delta
        if (datetime.now() - last_send_time).total_seconds() > 1:
            await update_response()
            last_send_time = datetime.now()
    await update_response()


@OpenAIWrapper.add_schema("A timer function.")
async def timer(num_seconds: Annotated[int, "Number of seconds in the timer."]) -> str:
    await asyncio.sleep(num_seconds)
    return "Timer is done!"


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
    for message in h["messages"]:
        if message.get("bot_id"):
            await try_delete(body["channel_id"], message["ts"])
        else:
            replies = await client.conversations_replies(channel=body["channel_id"], ts=message["ts"])
            for reply in replies["messages"]:
                await try_delete(body["channel_id"], reply["ts"])


async def main():
    openai.add_function(timer)
    await AsyncSocketModeHandler(slack, os.environ["SLACK_APP_TOKEN"]).start_async()


if __name__ == "__main__":
    asyncio.run(main())
