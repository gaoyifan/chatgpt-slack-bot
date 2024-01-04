import os
import asyncio
from slack_bolt.async_app import AsyncApp, AsyncBoltContext, AsyncSay
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_slack_response import AsyncSlackResponse
from slack_sdk.web.async_client import AsyncWebClient
from openai import AsyncOpenAI
from pprint import pprint
from typing import Dict, List
from datetime import datetime

openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
slack = AsyncApp(token=os.environ.get("SLACK_BOT_TOKEN"))


async def fetch_gpt_response(prompts: List[Dict]):
    try:
        stream = await openai.chat.completions.create(
            model="gpt-4-1106-preview",
            stream=True,
            messages=prompts)
        async for response in stream:
            choice = response.choices[0]
            if choice.finish_reason is not None:
                print("Finished:", choice.finish_reason)
                return
            if choice.delta.content:
                yield choice.delta.content
    except Exception as e:
        yield str(e)
        return


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
    async for delta in fetch_gpt_response(prompts):
        response += delta
        if (datetime.now() - last_send_time).total_seconds() > 1:
            await update_response()
            last_send_time = datetime.now()
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
    for message in h["messages"]:
        if message.get("bot_id"):
            await try_delete(body["channel_id"], message["ts"])
        else:
            replies = await client.conversations_replies(channel=body["channel_id"], ts=message["ts"])
            for reply in replies["messages"]:
                await try_delete(body["channel_id"], reply["ts"])


async def main():
    await AsyncSocketModeHandler(slack, os.environ["SLACK_APP_TOKEN"]).start_async()


if __name__ == "__main__":
    asyncio.run(main())
