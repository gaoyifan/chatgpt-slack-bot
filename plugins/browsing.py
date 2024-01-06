import asyncio
import json
import os
from json import JSONDecodeError
from typing import Annotated

from httpx import AsyncClient, ReadTimeout

from plugin import add_schema


# using API from @SmartHypercube
# https://github.com/SmartHypercube/browse-api-serverless


async def _api_request(api_url, url):
    try:
        async with AsyncClient(http2=True, timeout=20) as client:
            response = await client.post(api_url, json={"url": url})
            try:
                json_response = response.json()
            except JSONDecodeError:
                json_response = {}
            data = json_response.get("data")
            if data:
                return json.dumps(data)
            else:
                return response.content
    except ReadTimeout:
        return "(tool call timeout)"
    except Exception as e:
        return f"(Exception in tool call: {e})"


@add_schema("Open a webpage using headless Chromium and extracts the title and all displayed text from the page.")
async def browser_text(url: Annotated[str, "URL of the webpage."]) -> str:
    return await _api_request(os.environ["BROWSER_TEXT_API_URL"], url)


@add_schema("Retrieves metadata and the README file of a GitHub repository.")
async def github(url: Annotated[str, "URL of the GitHub repository."]) -> str:
    return await _api_request(os.environ["GITHUB_API_URL"], url)


@add_schema("Downloads a PDF file and extracts text from it.")
async def pdf(url: Annotated[str, "URL of the PDF file"]) -> str:
    return await _api_request(os.environ["PDF_API_URL"], url)


@add_schema("Fetches the title, associated channel, description, and subtitles of a YouTube video.")
async def youtube(url: Annotated[str, "URL of the YouTube video."]) -> str:
    return await _api_request(os.environ["YOUTUBE_API_URL"], url)


async def main():
    print(await browser_text("https://www.openai.com/blog/"))
    print(await github("https://github.com/torvalds/linux"))
    print(await pdf("https://arxiv.org/pdf/2104.08691.pdf"))
    print(await youtube("https://www.youtube.com/watch?v=QdBZY2fkU-0"))


if __name__ == "__main__":
    asyncio.run(main())
