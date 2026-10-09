"""Tool protocol, registry and router.

Anthropic tool names must match ^[a-zA-Z0-9_-]{1,64}$ - dots are rejected - so internal names
like `browser.click` are exposed to the model as `browser__click` and mapped back here.
"""
from typing import Callable, Protocol

from ..core.models import Observation


class Tool(Protocol):
    name: str                    # "browser.click"
    schema: dict                 # Anthropic tool JSON schema (api-safe name)

    def run(self, args: dict, ctx) -> Observation: ...


class FunctionTool:
    def __init__(self, name: str, description: str, properties: dict, required: list[str], fn: Callable):
        self.name = name
        self.fn = fn
        self.description = description
        self.schema = {"name": to_api_name(name), "description": description,
                       "input_schema": {"type": "object", "properties": properties, "required": required}}

    def run(self, args: dict, ctx) -> Observation:
        return self.fn(args, ctx)


REGISTRY: dict[str, Tool] = {}


def to_api_name(name: str) -> str:
    return name.replace(".", "__")


def from_api_name(name: str) -> str:
    return name.replace("__", ".")


def register(tool) -> None:
    REGISTRY[tool.name] = tool


def schema() -> list[dict]:
    return [t.schema for t in REGISTRY.values()]


def describe_registry() -> str:
    """Compact list for the planner prompt."""
    return "\n".join(f"- {t.name}: {getattr(t, 'description', '')}" for t in REGISTRY.values())


def run_tool(name: str, args: dict, ctx) -> Observation:
    tool = REGISTRY.get(name)
    if not tool:
        return Observation(ok=False, error=f"unknown tool {name}")
    try:
        return tool.run(args, ctx)
    except Exception as e:                  # never raise into the loop
        return Observation(ok=False, error=f"{type(e).__name__}: {e}")
