"""Optional computer-use fallback (first thing on the cut list). Read-only: describes the latest screenshot
so the model can recover when the DOM snapshot is uninformative (canvas widgets, odd overlays)."""
import base64

from ..core import llm
from ..core.models import Observation
from .base import FunctionTool, register


def describe(args, ctx):
    if llm.PROVIDER == "ollama":
        return Observation(ok=False, error="vision.describe is not available with the local text model")
    if not ctx.last_screenshot:
        return Observation(ok=False, error="no screenshot yet; call browser.snapshot first")
    img = base64.b64encode(open(ctx.last_screenshot, "rb").read()).decode()
    r = llm.call("Describe what is visible on this web page and any blocking overlay. Be concise and literal.",
                 [{"role": "user", "content": [
                     {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img}},
                     {"type": "text", "text": args.get("question", "What is on screen?")}]}],
                 ctx, model=llm.JUDGE, max_tokens=500)
    return Observation(ok=True, text=llm.text_of(r))


def register_all():
    register(FunctionTool("vision.describe", "Describe the latest screenshot (fallback when DOM refs are unhelpful).",
                          {"question": {"type": "string"}}, [], describe))
