import json
import logging
import os
import tempfile
from typing import Annotated

import yt_dlp

from plugin import tool_call
from transcribe import transcribe

max_result_length = 6291556


def result_length(r):
    return len(json.dumps(r, ensure_ascii=False).encode())


def find_audio_files(path, extensions):
    return [f for f in os.listdir(path) if any(f.endswith(ext) for ext in extensions)]


def find_audio_format_id(info):
    size = 0
    format_id = None
    for f in info["formats"]:
        if (
            f["ext"] in ["webm", "m4a", "mp4"]
            and f["vcodec"] == "none"
            and f.get("filesize")
            and size < f["filesize"] < 20971520
        ):
            size = f["filesize"]
            format_id = f["format_id"]
    return format_id


@tool_call("Fetches the title, associated channel, description, and subtitles of a YouTube video.", cache=True)
async def youtube(url: Annotated[str, "URL of the YouTube video."]) -> str:
    logging.debug("youtube: %s", url)

    data = {"url": url}

    sub_preferences_en = ["en", "en-US", "en-GB", "en-AU", "en-CA", "en-IN", "en-IE"]
    sub_preferences_zh = ["zh-CN", "zh-Hans", "zh", "zh-Hant", "zh-TW", "zh-HK", "zh-SG"]
    autosub_preferences = ["en"]

    with yt_dlp.YoutubeDL() as ydl:
        info = ydl.extract_info(url, download=False, process=False)

    if "title" in info:
        data["title"] = info["title"]
        logging.debug("title: %s", info["title"])
    if "channel" in info:
        data["channel"] = info["channel"]
        logging.debug("channel: %s", info["channel"])
    if "uploader" in info:
        data["uploader"] = info["uploader"]
        logging.debug("uploader: %s", info["uploader"])
    if "uploader" in data and "channel" in data:
        if data["uploader"] == data["channel"]:
            del data["uploader"]
            logging.debug("uploader == channel, delete uploader")
    if "description" in info:
        data["description"] = info["description"]

    if "title" in info and len([c for c in info["title"] if ord(c) in range(0x3400, 0xA000)]) >= 5:
        sub_preferences = sub_preferences_zh + sub_preferences_en
        logging.debug("guess_lang: zh")
    else:
        sub_preferences = sub_preferences_en + sub_preferences_zh
        logging.debug("guess_lang: en")

    logging.debug("subtitles: %s", info["subtitles"])
    logging.debug("automatic_captions: %s", info["automatic_captions"])
    subtitle = None
    for lang in sub_preferences:
        if lang in info["subtitles"]:
            subtitle = "sub", lang
            break
    if subtitle is None:
        for lang in info["subtitles"]:
            if lang != "live_chat":
                subtitle = "sub", lang
                break
    if subtitle is None:
        for lang in autosub_preferences:
            if lang in info["automatic_captions"]:
                subtitle = "autosub", lang
                break

    if subtitle is None:  # download audio and transcribe
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_options = {"format": find_audio_format_id(info), "outtmpl": f"{tmpdir}/audio.%(ext)s"}
            with yt_dlp.YoutubeDL(audio_options) as ydl:
                ydl.download([url])
            audio_file = find_audio_files(tmpdir, [".webm", ".m4a", ".mp4"])[0]
            audio_path = f"{tmpdir}/{audio_file}"
            try:
                with open(audio_path, "rb") as audio_file:
                    transcript_response = await transcribe(audio_file)
                transcript = '\n'.join([seg["text"] for seg in transcript_response.segments])
                logging.debug("transcript success")
            except Exception as e:
                logging.error(f"Error in transcribing audio: {e}")
                raise ValueError("Audio transcription failed")
    else:  # download subtitle
        with tempfile.TemporaryDirectory() as tmpdir:
            options = {
                "outtmpl": f"{tmpdir}/output.%(ext)s",
                "skip_download": True,
                "subtitleslangs": [subtitle[1]],
                "subtitlesformat": "json3",
            }
            if subtitle[0] == "sub":
                options["writesubtitles"] = True
            elif subtitle[0] == "autosub":
                options["writeautomaticsub"] = True

            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])

            with open(f"{tmpdir}/output.{subtitle[1]}.json3") as f:
                json3 = json.load(f)
                subtitle_lines = []
                for event in json3["events"]:
                    if "segs" in event:
                        line = "".join([seg["utf8"] for seg in event["segs"]]).strip()
                        if line:
                            subtitle_lines.append(line)
        transcript = "\n".join(subtitle_lines)
        logging.debug("subtitle: %s, %s", subtitle[0], subtitle[1])

    result = {
        "data": data,
        "truncated": False,
        "template": [
            {"field": "url", "name": "URL", "type": "inline"},
            {"field": "title", "name": "Title", "type": "inline"},
            {"field": "channel", "name": "Channel", "type": "inline"},
            {"field": "uploader", "name": "Uploader", "type": "inline"},
            {"field": "description", "name": "Description", "type": "block"},
            {"field": "transcript", "name": "Transcript", "type": "block"},
        ],
    }
    result["data"]["transcript"] = transcript
    if result_length(result) > max_result_length:
        result["truncated"] = True
        result["data"]["transcript"] = ""
        left = 0
        right = len(transcript)
        while left + 1 < right:
            mid = (left + right) // 2
            result["data"]["transcript"] = transcript[:mid]
            if result_length(result["data"]) > max_result_length:
                right = mid
            else:
                left = mid
        result["data"]["transcript"] = transcript[:left]
    return json.dumps(result["data"], ensure_ascii=False)
