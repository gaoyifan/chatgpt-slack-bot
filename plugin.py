from typing import Callable

from autogen.function_utils import get_function_schema


def add_schema(description: str):
    def decorator(func: Callable):
        schema = get_function_schema(func, description=description)
        setattr(func, "schema", schema)
        return func

    return decorator
