"""Human-in-the-loop. A handler (CLI, scripted-for-evals, or web) is installed per thread; the
module-level functions are what the rest of the system calls."""
import json
import threading
from typing import Optional, Protocol

from .models import Action, Decision

_local = threading.local()


class Human(Protocol):
    def approve(self, action: Action, decision: Decision, ctx) -> tuple[bool, Optional[dict]]: ...
    def ask(self, question: str, ctx, options: Optional[list[str]] = None) -> str: ...
    def help(self, summary: str, ctx) -> Optional[str]: ...


def set_handler(h: Human) -> None:
    _local.h = h


def handler() -> Human:
    h = getattr(_local, "h", None)
    if h is None:
        h = _local.h = CLIHuman()
    return h


# ---------------- handlers ----------------
class CLIHuman:
    """rich prompt fallback so the demo never depends on the UI."""

    def __init__(self):
        from rich.console import Console
        self.c = Console()

    def approve(self, action, decision, ctx):
        from rich.prompt import Prompt
        self.c.rule("[bold red]APPROVAL REQUIRED")
        self.c.print(f"[bold]{action.tool}[/] {json.dumps(action.args, default=str)}")
        self.c.print(f"tier={decision.tier}  reason={decision.reason}\nrationale: {action.rationale[:300]}")
        self.c.print(f"known facts: {json.dumps(ctx.scratch, default=str)[:500]}")
        a = Prompt.ask("approve / reject / edit", choices=["approve", "reject", "edit"], default="reject")
        if a == "edit":
            return True, json.loads(Prompt.ask("new args as JSON"))
        return a == "approve", None

    def ask(self, question, ctx, options=None):
        from rich.prompt import Prompt
        self.c.rule("[bold yellow]QUESTION")
        return Prompt.ask(question + (f" {options}" if options else ""))

    def help(self, summary, ctx):
        from rich.prompt import Prompt
        self.c.rule("[bold magenta]OPERATOR NEEDS HELP")
        self.c.print(summary)
        r = Prompt.ask("Guidance (blank to abort the run)", default="")
        return r or None


class ScriptedHuman:
    """Simulated human for evals/tests.
    approvals: {"default": "approve"|"reject", "reject_tools": ["email.send"], "reject_tiers": ["T3"]}
    answers:   {"substring of question (lowercase)": "answer"}
    help:      guidance string, or None to abort (clean escalation)
    """

    def __init__(self, default: str = "approve", reject_tools=(), reject_tiers=(), answers=None, help_text=None):
        self.default, self.reject_tools, self.reject_tiers = default, set(reject_tools), set(reject_tiers)
        self.answers, self.help_text = {k.lower(): v for k, v in (answers or {}).items()}, help_text
        self.log: list[dict] = []

    def approve(self, action, decision, ctx):
        ok = (self.default == "approve" and action.tool not in self.reject_tools
              and decision.tier not in self.reject_tiers)
        self.log.append({"kind": "approval", "tool": action.tool, "approved": ok})
        return ok, None

    def ask(self, question, ctx, options=None):
        self.log.append({"kind": "question", "q": question})
        for k, v in self.answers.items():
            if k in question.lower():
                return v
        return (options or ["unknown"])[0]

    def help(self, summary, ctx):
        self.log.append({"kind": "help"})
        return self.help_text


# ---------------- module API used by the executor / loop ----------------
def request_approval(action: Action, decision: Decision, ctx) -> Decision:
    """Blocks until the human responds. Timeout / no answer = not approved."""
    ctx.log("approval_request", {
        "action": action.model_dump(), "tier": decision.tier, "reason": decision.reason,
        "rationale": action.rationale, "screenshot": ctx.last_screenshot, "facts": ctx.scratch})
    try:
        approved, edited = handler().approve(action, decision, ctx)
    except TimeoutError:
        approved, edited = False, None
    ctx.log("approval_response", {"tool": action.tool, "approved": approved, "edited_args": edited})
    if approved:
        return Decision(verdict="allow", tier=decision.tier, reason="approved by human", by_human=True, edited_args=edited)
    return Decision(verdict="block", tier=decision.tier, reason="rejected by human", by_human=True)


def ask(question: str, ctx, options: Optional[list[str]] = None) -> str:
    ctx.log("question", {"question": question, "options": options, "screenshot": ctx.last_screenshot})
    ans = handler().ask(question, ctx, options)
    ctx.log("answer", {"question": question, "answer": ans})
    return ans


def ask_for_help(step, ctx, summary: str) -> Optional[str]:
    msg = (f"I'm stuck on step {step.id}: {step.goal}\n{summary}\n"
           f"Options: give me a hint/value to continue, do it manually and tell me, or abort the run.")
    ctx.log("help_request", {"step": step.id, "summary": msg, "screenshot": ctx.last_screenshot})
    ans = handler().help(msg, ctx)
    ctx.log("help_response", {"step": step.id, "guidance": ans})
    return ans
