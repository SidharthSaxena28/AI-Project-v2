"""email.send - simulated: writes to an outbox directory. Always T3 (needs human approval)."""
import json
import time

from ..context import registry
from ..core.models import Observation
from .base import FunctionTool, register


def send(args, ctx):
    d = registry.abspath("company_env/data/out/outbox")
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{int(time.time() * 1000)}.json"
    p.write_text(json.dumps({"to": args["to"], "subject": args["subject"], "body": args["body"], "run": ctx.run_id}, indent=1))
    return Observation(ok=True, text=f"email queued to {args['to']} ({p.name})")


def register_all():
    register(FunctionTool("email.send", "Send an email (external; requires human approval).",
                          {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
                          ["to", "subject", "body"], send))
