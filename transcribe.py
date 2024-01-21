import asyncio
import logging
import os
import sys
import time

import openai

API_KEY = os.getenv("WHISPER_API_KEY") or os.getenv("OPENAI_API_KEY") or "sk-placeholder"
client = openai.AsyncOpenAI(base_url=os.getenv("WHISPER_BASE_URL"), api_key=API_KEY)
audio_model = os.getenv("OPENAI_AUDIO_MODEL", "whisper-1")


async def transcribe(audio_file):
    return await client.audio.transcriptions.create(
        model=audio_model,
        file=audio_file
    )


async def main():
    logging.basicConfig(level=logging.DEBUG)
    filename = sys.argv[1] if len(sys.argv) > 1 else "audio.mp4"
    with open(filename, "rb") as f:
        t0 = time.time()
        transcript = await transcribe(f)
        t1 = time.time()
    print(f"Transcribed in {t1 - t0:.2f} seconds")
    print(transcript.text)


if __name__ == "__main__":
    asyncio.run(main())
