import asyncio
import json
import logging
import os
import traceback
from datetime import datetime
from pprint import pprint
from typing import Dict, List

import aiohttp
from pony.orm import *
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp, AsyncSay
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from database import db
from openai_wrapper import OpenAIWrapper
from plugins.browsing import browser_text, github, pdf
from plugins.search import search
from plugins.youtube import youtube
from transcribe import transcribe

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
slack = AsyncApp(token=os.environ.get("SLACK_BOT_TOKEN"))
openai = OpenAIWrapper()


async def download_file(url):
    logging.debug("Downloading file: %s", url)
    async with aiohttp.ClientSession() as aiohttp_session:
        async with aiohttp_session.get(url, headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"}) as r:
            if not r.ok:
                logging.error("Failed to download file: %s", url)
                return
            return await r.content.read()


class SlackExtraPrompt(db.Entity):
    _table_ = "SlackToolCallPrompt"  # historical reasons
    ts = PrimaryKey(str)
    channel = Required(str)
    thread_ts = Optional(str)
    prompts = Required(Json)


@db_session
def get_extra_prompts(msg_ts):
    prompt = SlackExtraPrompt.get(ts=msg_ts)
    return prompt.prompts if prompt else []


@db_session
def add_extra_prompts(channel, msg_ts, prompts, thread_ts=None):
    if SlackExtraPrompt.exists(ts=msg_ts):
        prompt = SlackExtraPrompt.get(ts=msg_ts)
        prompt.prompts += prompts
    else:
        SlackExtraPrompt(ts=msg_ts, channel=channel, thread_ts=thread_ts, prompts=prompts)


def generate_prompts(thread_msgs: List[Dict]):
    yield {"role": "system", "content": "You are a helpful assistant."}
    for msg in thread_msgs:
        for p in get_extra_prompts(msg["ts"]):
            yield p
        if not msg["text"]:  # skip empty messages, e.g. audio prompts
            continue
        if "bot_id" in msg:
            yield {"role": "assistant", "content": msg["text"]}
        elif "user" in msg:
            yield {"role": "user", "content": msg["text"]}
        else:
            print("Unknown message type")


@slack.event("message")
async def message_handler(event: Dict, say: AsyncSay, client: AsyncWebClient):
    async def update_response():
        nonlocal slack_response, response, channel
        await client.chat_update(channel=channel, ts=slack_response["ts"], text=response)

    async def new_response(msg):
        nonlocal thread_ts
        return await say(msg, thread_ts=thread_ts, username="AI Assistant")

    logging.debug("event: %s", event)
    if "hidden" in event:
        logging.debug("hidden message")
        return
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]

    # transcribe audio files
    for file in event.get("files", []):
        if file.get("subtype") == "slack_audio":
            logging.debug("transcribing audio file")
            url = file["url_private"]
            transcript = await transcribe(await download_file(url))
            await client.chat_postEphemeral(
                channel=channel,
                user=event["user"],
                username="AI Assistant",
                text=f"You: {transcript.text}",
                thread_ts=thread_ts,
            )
            add_extra_prompts(channel, event["ts"], [{"role": "user", "content": transcript.text}], thread_ts)

    try:
        thread_msgs = await client.conversations_replies(channel=channel, ts=thread_ts)
    except SlackApiError:
        logging.error("Failed to fetch thread messages. channel: %s, ts: %s", channel, thread_ts)
        return
    prompts = list(generate_prompts(thread_msgs["messages"]))
    logging.debug("prompts: %s", prompts)
    response = ""
    last_send_time = datetime.now()
    old_prompts_len = len(prompts)
    slack_response = await new_response("(Thinking...)")
    try:
        async for delta in openai.generate_reply(prompts):
            if len(response.encode("utf-8")) + len(delta.encode("utf-8")) > 3000:  # slack message length limit
                await update_response()
                response = delta
                slack_response = await new_response(response)
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
        add_extra_prompts(channel, slack_response["ts"], prompts[old_prompts_len:], thread_ts)
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


# set OpenAI key by slash command
@slack.command("/set-openai-key")
async def set_openai_key(ack, body, client: AsyncWebClient):
    await ack()
    if os.environ.get("ALLOW_SET_OPENAI_KEY") != "true":
        await client.chat_postEphemeral(
            channel=body["channel_id"], user=body["user_id"], text="This command is disabled"
        )
        return
    key = body["text"]
    logging.info("Setting OpenAI key: %s", key)
    openai.set_openai_key(key)
    await client.chat_postEphemeral(channel=body["channel_id"], user=body["user_id"], text="OpenAI key set")


# dump all messages to json
@slack.command("/dump-conversations")
async def dump_conversation(ack, body, client: AsyncWebClient):
    await ack()

    await client.chat_postEphemeral(
        channel=body["channel_id"],
        user=body["user_id"],
        text="Dumping conversations to JSON file, this may take up to an hour according to your conversation size, "
        "please wait...",
    )

    try:
        h = await client.conversations_history(channel=body["channel_id"], limit=999)
        assert h["ok"]
        msg_history = h["messages"]

        while h["has_more"]:
            await asyncio.sleep(1)  # need to wait 1 sec before next call due to rate limits
            h = await client.conversations_history(
                channel=body["channel_id"], limit=999, cursor=h["response_metadata"]["next_cursor"]
            )
            assert h["ok"]
            messages = h["messages"]
            msg_history += messages

        # receive all threads
        msg_replies = []
        for msg in msg_history:
            if "thread_ts" in msg:
                await asyncio.sleep(1)
                thread = await client.conversations_replies(channel=body["channel_id"], ts=msg["ts"])
                msg_replies.extend(thread["messages"])

        msg_all = msg_history + msg_replies
        msg_all.sort(key=lambda x: float(x["ts"]))
        msg_json = json.dumps(msg_all, ensure_ascii=False)

        await client.files_upload(
            channels=body["channel_id"],
            content=msg_json,
            title="conversations of user {} before {}".format(body["user_id"], datetime.now().strftime("%Y-%m-%d")),
            filename="conversation.json",
            initial_comment="Fetched a total of {} messages.".format(len(msg_all)),
            filetype="json",
        )
    except Exception as e:
        logging.error("Failed to dump conversations to JSON file: %s", e)
        print(traceback.format_exc())
        await client.chat_postEphemeral(
            channel=body["channel_id"],
            user=body["user_id"],
            text=f"Failed to dump conversation to JSON file: {e}",
        )


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
