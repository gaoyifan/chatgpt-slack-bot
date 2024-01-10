import asyncio
import json
import os
import sys
from typing import Annotated

import aiohttp

from plugin import tool_call

# The original version is from: https://github.com/zzh1996/chatgpt-telegram-bot

# google
key = os.environ["GOOGLE_SEARCH_KEY"]
cx = os.environ["GOOGLE_SEARCH_CX"]

# bing
subscription_key = os.environ["BING_SEARCH_V7_SUBSCRIPTION_KEY"]
endpoint = os.environ["BING_SEARCH_V7_ENDPOINT"] + "/v7.0/search"


@tool_call("Search on Google and Bing and get the search results. Use concise keywords as query.", cache=True)
async def search(query: Annotated[str, "The search query, English only."]) -> str:
    query = query.strip()
    if not query:
        return {"error": "query is empty"}
    api_url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": key,
        "cx": cx,
        "q": query,
    }
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        async with session.get(api_url, params=params) as response:
            response.raise_for_status()
            results = await response.json()
            # print(json.dumps(results, ensure_ascii=False, indent=2))
            google_results = []
            if "items" in results:
                for item in results["items"]:
                    obj = {}
                    if "title" in item:
                        obj["title"] = item["title"]
                    if "link" in item:
                        obj["link"] = item["link"]
                    if "snippet" in item:
                        obj["snippet"] = item["snippet"]
                    if len(obj):
                        google_results.append(obj)

    params = {"q": query}
    headers = {"Ocp-Apim-Subscription-Key": subscription_key}

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        async with session.get(endpoint, headers=headers, params=params) as response:
            response.raise_for_status()
            results = await response.json()
            # print(json.dumps(results, ensure_ascii=False, indent=2))
            bing_results = []
            if "webPages" in results and "value" in results["webPages"]:
                for item in results["webPages"]["value"]:
                    obj = {}
                    if "name" in item:
                        obj["title"] = item["name"]
                    if "url" in item:
                        obj["link"] = item["url"]
                    if "snippet" in item:
                        obj["snippet"] = item["snippet"]
                    if len(obj):
                        bing_results.append(obj)

    return json.dumps({"google_results": google_results, "bing_results": bing_results}, ensure_ascii=False)


async def main():
    from database import db

    db.generate_mapping(create_tables=True, check_tables=True)
    keyword = "ChatGPT"
    if len(sys.argv) > 1:
        keyword = sys.argv[1]
    print(await search(keyword))


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
