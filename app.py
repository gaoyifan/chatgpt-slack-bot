import logging
import os
import asyncio
from slack_bolt.async_app import AsyncApp, AsyncBoltContext, AsyncSay
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.models.metadata import Metadata
from slack_sdk.web.async_slack_response import AsyncSlackResponse
from slack_sdk.web.async_client import AsyncWebClient
from pprint import pprint
from typing import Dict, List, Annotated
from datetime import datetime
from openai_wrapper import OpenAIWrapper

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
slack = AsyncApp(token=os.environ.get("SLACK_BOT_TOKEN"))
openai = OpenAIWrapper()


def generate_prompts(thread_msgs: List[Dict]):
    yield {"role": "system", "content": "You are a helpful assistant."}
    for msg in thread_msgs:
        if "bot_id" in msg:
            additional_prompts = msg.get("metadata", {}).get("event_payload", {}).get("additional_prompts")
            if additional_prompts:  # load tool call context from message metadata
                for m in additional_prompts:
                    yield m
            yield {"role": "assistant", "content": msg["text"]}
        elif "user" in msg:
            yield {"role": "user", "content": msg["text"]}
        else:
            print("Unknown message type")


@slack.event("message")
async def message_handler(context: AsyncBoltContext, event: Dict, say: AsyncSay, client: AsyncWebClient):
    async def update_response():
        nonlocal slack_msg, response, thread_ts, additional_prompts
        metadata = None
        if additional_prompts:  # add tool call context into message metadata
            metadata = Metadata("tool_call", {"additional_prompts": additional_prompts})
        if slack_msg is None:
            slack_msg = await say(response, thread_ts=thread_ts, username="AI Assistant", metadata=metadata)
        else:
            await client.chat_update(channel=slack_msg["channel"], ts=slack_msg["ts"], text=response,
                                     metadata=metadata)

    if "hidden" in event:
        print(context.bot_id)
        return
    thread_ts = event.get("thread_ts") or event["ts"]
    thread_msgs = await client.conversations_replies(channel=event["channel"], ts=thread_ts, include_all_metadata=True)
    prompts = list(generate_prompts(thread_msgs["messages"]))
    slack_msg: AsyncSlackResponse = None
    response = ""
    last_send_time = datetime.now()
    old_prompts_len = len(prompts)
    additional_prompts = []
    try:
        async for delta in openai.generate_reply(prompts):
            response += delta
            if (datetime.now() - last_send_time).total_seconds() > 1:
                await update_response()
                last_send_time = datetime.now()
    except Exception as e:
        response += f"(Exception in function call: {e})"
        logging.error("Exception in function call: %s", e)
    if len(prompts) > old_prompts_len:
        additional_prompts = prompts[old_prompts_len:]
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
    for msg in h["messages"]:
        if msg.get("bot_id"):
            await try_delete(body["channel_id"], msg["ts"])
        else:
            replies = await client.conversations_replies(channel=body["channel_id"], ts=msg["ts"])
            for reply in replies["messages"]:
                await try_delete(body["channel_id"], reply["ts"])


async def main():
    openai.add_function(timer)
    await AsyncSocketModeHandler(slack, os.environ["SLACK_APP_TOKEN"]).start_async()


if __name__ == "__main__":
    asyncio.run(main())
