"""TaskSpec + context -> Plan ; replan() revises only the remaining steps."""
import json
import re

from ..context import registry
from ..tools import base as tools_base
from . import llm
from .models import Plan, ReplanOut, Step, TaskSpec


class PlanError(RuntimeError):
    pass


def validate_steps(steps: list[Step], known_tools: set[str]) -> list[str]:
    problems = []
    if len(steps) > 12:
        problems.append(f"{len(steps)} steps; maximum is 12")
    ids = [s.id for s in steps]
    if len(ids) != len(set(ids)):
        problems.append("duplicate step ids")
    for s in steps:
        if s.kind == "tool":
            for tok in re.findall(r"[a-z_]+\.[a-z_]+", s.tool_hint):
                if tok not in known_tools:
                    problems.append(f"{s.id}: tool_hint '{tok}' is not in the tool registry")
            if s.state_changing and not s.postconditions:
                problems.append(f"{s.id}: state-changing step has no machine-checkable postcondition")
    return problems


def validate_plan(plan: Plan) -> list[str]:
    known = set(tools_base.REGISTRY)
    problems = validate_steps(plan.steps, known)
    if not plan.final_postconditions:
        problems.append("final_postconditions is empty")
    if not plan.steps:
        problems.append("no steps")
    return problems


def _context_blob(spec: TaskSpec, sops, ctx) -> str:
    return json.dumps({
        "task_spec": spec.model_dump(),
        "sops": [{"id": s["id"], "title": s["title"], "body": s["body"]} for s in sops],
        "systems": registry.systems_summary(),
        "policy": registry.policy_summary(),
        "tools": tools_base.describe_registry(),
        "input_files": ctx.input_files,
        "human_answers": ctx.scratch.get("human_answers", []),
    }, indent=1)


def make_plan(spec: TaskSpec, sops, ctx) -> Plan:
    system, user = registry.prompt("planner"), _context_blob(spec, sops, ctx)
    problems = []
    for _ in range(3):
        plan = llm.call_json(system, user, Plan, ctx, max_tokens=6000)
        problems = validate_plan(plan)
        if not problems:
            plan.version = 1
            plan.sop_refs = plan.sop_refs or [s["id"] for s in sops]
            ctx.log("plan", plan.model_dump())
            return plan
        user += f"\n\nYour previous plan was invalid: {problems}. Return a corrected plan."
    raise PlanError(f"could not produce a valid plan: {problems}")


def replan(spec: TaskSpec, plan: Plan, failed: Step, res, ctx) -> Plan:
    """Completed steps are frozen. Falls back to retrying the failed step if the LLM cannot help."""
    last_obs = [e["payload"] for e in ctx.events() if e["type"] == "observation"][-4:]
    user = json.dumps({
        "task_spec": spec.model_dump(), "plan": plan.model_dump(), "failed_step": failed.model_dump(),
        "step_result": res.model_dump(), "recent_actions": ctx.recent_actions(failed.id, 8),
        "last_observations": [{k: (str(v)[:600]) for k, v in o.items() if k in ("tool", "ok", "error", "text")} for o in last_obs],
        "facts": ctx.scratch, "tools": tools_base.describe_registry(), "policy": registry.policy_summary(),
    }, indent=1)
    try:
        out = llm.call_json(registry.prompt("replan"), user, ReplanOut, ctx, max_tokens=5000)
        remaining = out.steps
        done = [s for s in plan.steps if s.status == "done"]
        problems = validate_steps(done + remaining, set(tools_base.REGISTRY))
        if problems or not remaining:
            raise ValueError(problems or "empty replan")
        new = plan.revise(remaining)
    except Exception as e:                       # noqa: BLE001
        ctx.log("replan_failed", {"error": str(e)})
        failed.status = "pending"
        return plan
    ctx.log("replan", {"from": plan.version, "to": new.version, "note": out.note, "steps": [s.model_dump() for s in remaining]})
    return new
