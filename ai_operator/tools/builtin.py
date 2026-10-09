"""Working-memory and human-question tools."""
import json

from ..core import human
from ..core.models import Observation
from .base import FunctionTool, register


def _mem_set(args, ctx):
    ctx.scratch[args["key"]] = args["value"]
    ctx.log("memory", {"op": "set", "key": args["key"], "value": args["value"]})
    return Observation(ok=True, text=f"stored {args['key']}={json.dumps(args['value'], default=str)}")


def _mem_get(args, ctx):
    if args["key"] not in ctx.scratch:
        return Observation(ok=False, error=f"no value stored for '{args['key']}'; known keys: {sorted(ctx.scratch)}")
    return Observation(ok=True, text=json.dumps(ctx.scratch[args["key"]], default=str))


def _ask(args, ctx):
    ans = human.ask(args["question"], ctx, args.get("options"))
    ctx.scratch.setdefault("human_answers", []).append({"q": args["question"], "a": ans})
    return Observation(ok=True, text=f"Human answered: {ans}")


def register_all():
    register(FunctionTool("memory.set", "Record an extracted fact (amount, id, name) so it survives context trimming.",
                          {"key": {"type": "string"}, "value": {}}, ["key", "value"], _mem_set))
    register(FunctionTool("memory.get", "Read a previously recorded fact.", {"key": {"type": "string"}}, ["key"], _mem_get))
    register(FunctionTool("human.ask", "Ask the human a clarifying question when a value cannot be read from sources.",
                          {"question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}}},
                          ["question"], _ask))
