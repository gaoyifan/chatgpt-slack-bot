import asyncio
import json
import logging
import os
import traceback
from pprint import pprint
from typing import Annotated, Any, AsyncGenerator, AsyncIterator, Callable, Dict, List

from openai import AsyncOpenAI

from plugin import add_schema


class OpenAIWrapper:
    def __init__(self):
        self.available_funcs: Dict[str, Callable] = {}
        api_key = os.getenv("OPENAI_API_KEY")
        self.openai = AsyncOpenAI(api_key=api_key)
        self.model = os.getenv("OPENAI_MODEL")
        assert api_key is not None
        assert self.model is not None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.openai.close()

    def add_function(self, func):
        self.available_funcs[func.schema["name"]] = func

    def _get_tools_schema(self):
        if not self.available_funcs:
            # openai.chat.completions.create() will fail with tools={}, so we return None instead
            return None
        return [{"type": "function", "function": func.schema} for func in self.available_funcs.values()]

    async def _execute_function(self, tool_calls: List[Dict[str, Any]]) -> AsyncIterator[Dict[str, Any]]:
        async def execute_tool_call(tool_call):
            id = tool_call["id"]
            func = tool_call["function"]
            func_name = func["name"]
            func_to_call = self.available_funcs[func_name]
            func_args = json.loads(func["arguments"])
            try:
                if asyncio.iscoroutinefunction(func_to_call):
                    func_return = await func_to_call(**func_args)
                else:
                    func_return = func_to_call(**func_args)
            except Exception as e:
                func_return = f"(Exception in function call: {e})"
                logging.error("Exception in function call: %s", e)
                traceback.print_exc()
            return {
                "tool_call_id": id,
                "role": "tool",
                "name": func_name,
                "content": func_return,
            }

        coroutines = [execute_tool_call(tool_call) for tool_call in tool_calls]
        results = await asyncio.gather(*coroutines)
        for result in results:
            yield result

    async def generate_reply(self, msg_history: List[Dict[str, Any]]) -> AsyncGenerator[str, None]:
        logging.debug("msg_history: %s", msg_history)
        msg = msg_history[-1]
        if msg.get("role") in ["user", "tool"]:  # message from user or function return
            stream = await self._raw_chat_complete(msg_history)
            pending_tool_calls = []
            async for chunk in stream:
                choice = chunk.choices[0]
                delta = choice.delta
                assert delta is not None
                if delta.content:
                    yield delta.content
                if delta.tool_calls:
                    for tool_call in delta.tool_calls:  # new tool call
                        if tool_call.index == len(pending_tool_calls):
                            assert tool_call.type == "function"
                            pending_tool_calls.append(tool_call.model_dump())
                        else:  # existing tool call in streaming response
                            pending_tool_calls[tool_call.index]["function"]["arguments"] += tool_call.function.arguments
                match choice.finish_reason:
                    case "length":
                        yield "(Response truncated due to length limit)"
                    case "content_filter":
                        yield "(Request omitted due to content filter)"
                    case "tool_calls":
                        msg_history.append({"role": "assistant", "tool_calls": pending_tool_calls})
                        logging.debug("pending_tool_calls: %s", pending_tool_calls)
                        async for content in self.generate_reply(msg_history):
                            yield content
                    case "stop":  # finished normally
                        pass
                    case None:  # not finished
                        pass
                    case _:
                        yield f"(finish: {choice.finish_reason})"
                        logging.error("Unexpected finish reason: %s", choice.finish_reason)
        elif msg.get("tool_calls"):  # tool calls from assistant
            msg_history += [result async for result in self._execute_function(msg["tool_calls"])]
            async for content in self.generate_reply(msg_history):
                yield content
        else:
            yield f"Unknown message type: {msg}"
            logging.error("Unknown message type: %s", msg)

    def _raw_chat_complete(self, msg_history):
        logging.debug("msg_history: %s", msg_history)
        logging.debug("tools_schema: %s", self._get_tools_schema())
        return self.openai.chat.completions.create(
            model=self.model,
            messages=msg_history,
            tools=self._get_tools_schema(),
            stream=True,
        )


@add_schema("A timer function.")
async def timer(num_seconds: Annotated[int, "Number of seconds in the timer."]) -> str:
    print(f"Timer started for {num_seconds} seconds.")
    await asyncio.sleep(num_seconds)
    print(f"Timer done for {num_seconds} seconds.")
    return "Timer is done!"


async def main():
    async with OpenAIWrapper() as client:
        client.add_function(timer)
        print(f"function schema: {client._get_tools_schema()}")
        prompts = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Set a timer for 3 seconds and 5 seconds in parallel."},
        ]
        async for r in client.generate_reply(prompts):
            print(r, end="", flush=True)
        pprint(prompts)


if __name__ == "__main__":
    asyncio.run(main())
