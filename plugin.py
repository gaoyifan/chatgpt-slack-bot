import asyncio
import functools
from inspect import signature
from typing import Annotated, Callable

from autogen.function_utils import get_function_schema
from pony.orm import *

from database import db


class ToolCallCache(db.Entity):
    """Database model for storing the tool call cache"""

    key = Required(Json, index=True)  # Serialized function name and parameters
    value = Required(str)  # the function's result as a string


def tool_call(description: str, cache: bool = False):
    def decorator(func: Callable):
        schema = get_function_schema(func, description=description)
        setattr(func, "schema", schema)
        if not cache:
            return func

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            key = generate_cache_index(func, *args, **kwargs)

            with db_session:
                entry = ToolCallCache.select(lambda e: e.key == key).first()
                if entry:
                    return entry.value

            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            with db_session:
                ToolCallCache(key=key, value=result)
            return result

        return wrapper

    return decorator


def generate_cache_index(func, *args, **kwargs):
    """
    Convert *args and **kwargs to a key-value (KV) format.
    Args for the function are indexed based on the function's signature.
    """

    param_names = list(signature(func).parameters.keys())

    kv = {"func_name": func.__name__}

    # Add *args to the kv dictionary
    for i, arg in enumerate(args):
        param_name = param_names[i] if i < len(param_names) else f"arg{i}"
        kv[param_name] = arg

    # Add **kwargs to the kv dictionary
    kv.update(kwargs)

    return kv


async def main():
    db.generate_mapping(create_tables=True, check_tables=True)

    # Example usage of the combined decorator
    @tool_call(description="This is a test function", cache=True)
    def example_function(x: Annotated[int, "parameter x"], y: Annotated[int, "parameter y"]) -> str:
        return str(x + y)

    print(await example_function(1, 2))
    print(await example_function(1, 2))  # The second call will fetch the result from the cache

    @tool_call(description="This is a test function", cache=True)
    async def example_function2(x: Annotated[int, "parameter x"], y: Annotated[int, "parameter y"]) -> str:
        return str(x + y)

    print(await example_function2(1, 2))
    print(await example_function2(1, 2))  # The second call will fetch the result from the cache


if __name__ == "__main__":
    asyncio.run(main())
