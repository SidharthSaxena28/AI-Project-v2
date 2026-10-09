"""Shared entry point for CLI, UI and evals."""
from . import tools
from .core import human as human_mod
from .core import loop
from .core.state import RunContext
from .tools.browser import close_browser


def execute(request: str, files, human, *, run_id=None, resume: bool = False, root: str = "runs", subscribers=(), **ctx_kw):
    tools.load_all()
    human_mod.set_handler(human)
    if resume:
        ctx, spec, plan = RunContext.resume(run_id, root, **ctx_kw)
        request = spec.request
    else:
        ctx, spec, plan = RunContext(run_id, root, **ctx_kw), None, None
    ctx.subscribers.extend(subscribers)
    try:
        return loop.run(request, files, ctx, resume=resume, spec=spec, plan=plan)
    finally:
        close_browser()
