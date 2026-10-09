"""The orchestrator: intake -> plan -> (execute -> verify -> replan)* -> independent final verification -> report."""
from ..context import registry
from ..context.retriever import load_sops, retrieve
from ..report import evidence
from .. import tools as tools_pkg
from ..tools import base as tools
from . import executor, human, intake as intake_mod, planner, verifier
from .models import Plan, Step, StepResult, TaskSpec
from .state import RunContext


def resolve_blocking_questions(spec: TaskSpec, ctx) -> TaskSpec:
    for amb in [a for a in spec.ambiguities if a.blocking]:
        ans = human.ask(amb.question, ctx)
        spec.entities.setdefault("clarifications", []).append({"q": amb.question, "a": ans})
        ctx.scratch.setdefault("human_answers", []).append({"q": amb.question, "a": ans})
        amb.blocking = False
    return spec


def _human_step(step: Step, ctx) -> StepResult:
    ans = human.ask(step.goal, ctx, ["approve", "reject"])
    ctx.scratch[f"human_{step.id}"] = ans
    ok = str(ans).strip().lower() in ("approve", "approved", "yes", "y", "ok")
    return StepResult(done=ok, summary=f"human answered: {ans}", rejected_by_human=not ok)


def _help_summary(step: Step, res: StepResult, ctx) -> str:
    tried = "\n".join(f"  - {a}" for a in ctx.recent_actions(step.id)) or "  (nothing yet)"
    return f"What I tried:\n{tried}\nWhat is blocking: {res.summary}"


def run(request: str, files, ctx: RunContext, resume: bool = False, spec=None, plan=None):
    tools_pkg.load_all()
    escalated: str | None = None
    try:
        if not resume:
            ctx.log("start", {"request": request, "files": list(files or [])})
            spec = intake_mod.intake(request, files, ctx)
            spec = resolve_blocking_questions(spec, ctx)
            sops = retrieve(request, load_sops())
            plan = planner.make_plan(spec, sops, ctx)
            ctx.checkpoint(spec, plan)
        while plan.has_pending() and ctx.budget_ok() and not escalated:
            step = plan.next()
            step.attempts += 1
            ctx.log("step_start", {"step": step.model_dump()})
            res = _human_step(step, ctx) if step.kind == "human" else executor.run_step(step, spec, plan, ctx, tools.schema())
            ok = res.done and verifier.check_step(step, ctx, spec)         # postconditions
            ctx.log("step_end", {"step": step.id, "done": res.done, "verified": ok, "summary": res.summary})
            if ok:
                step.status = "done"
            elif res.rejected_by_human:
                escalated = f"human rejected: {res.summary}"
            elif res.blocked or ctx.stuck(step):
                # never plan around a policy block; never loop forever - ask a human
                guidance = human.ask_for_help(step, ctx, _help_summary(step, res, ctx))
                if guidance is None:
                    escalated = f"stuck on {step.id} ({res.summary}); human aborted"
                else:
                    ctx.scratch.setdefault("human_hints", []).append({"step": step.id, "hint": guidance})
                    step.attempts = 0
            else:
                plan = planner.replan(spec, plan, step, res, ctx)           # adapt
            ctx.checkpoint(spec, plan)
        if not escalated and plan.has_pending() and not ctx.budget_ok():
            escalated = ctx.budget_reason()
    except planner.PlanError as e:
        escalated = f"planning failed: {e}"
        spec = spec or TaskSpec(request=request, outcome="(intake incomplete)")
        plan = plan or Plan(steps=[])
    except Exception as e:                      # noqa: BLE001  never crash without a report
        escalated = f"unexpected error: {type(e).__name__}: {e}"
        ctx.log("error", {"error": escalated})
        spec = spec or TaskSpec(request=request, outcome="(intake incomplete)")
        plan = plan or Plan(steps=[])
    result = verifier.final(spec, plan, ctx, escalated)                  # independent check
    ctx.log("final", result.model_dump())
    return evidence.build(spec, plan, result, ctx)
