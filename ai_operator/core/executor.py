"""step -> Actions via a tool-use loop. Every action passes the deterministic policy gate first."""
import json

from ..context import registry
from ..context.retriever import load_sops
from ..tools import base as tools
from . import human, llm, policy
from .models import Action, Decision, Observation, Plan, Step, StepResult, TaskSpec


def compress(obs: Observation) -> str:
    if not obs.ok:
        return f"ERROR: {obs.error}" + (("\n" + obs.text[:3000]) if obs.text else "")
    return obs.text[:6000] or "ok"


def prune_snapshots(msgs: list, keep_last: int = 1) -> None:
    """Older page snapshots are replaced by a one-line summary to control context size."""
    spots = [(i, j) for i, m in enumerate(msgs) if m["role"] == "user" and isinstance(m["content"], list)
             for j, c in enumerate(m["content"])
             if isinstance(c, dict) and c.get("type") == "tool_result" and "SNAPSHOT url=" in str(c.get("content", ""))[:200]]
    for i, j in spots[:-keep_last] if keep_last else spots:
        first = str(msgs[i]["content"][j]["content"]).splitlines()[0]
        msgs[i]["content"][j]["content"] = f"[older snapshot elided] {first}"


def render_step_prompt(step: Step, spec: TaskSpec, plan: Plan, ctx) -> str:
    sop = next((s for s in load_sops() if s["id"] == step.sop_ref), None)
    plan_lines = "\n".join(f"- [{s.status}] {s.id}: {s.goal}" for s in plan.steps)
    return (f"OUTCOME: {spec.outcome}\n\nPLAN v{plan.version}:\n{plan_lines}\n\n"
            f"CURRENT STEP {step.id}: {step.goal}\nTool hint: {step.tool_hint or 'any'}\n"
            f"This step is complete when: {[p.description for p in step.postconditions] or 'its goal is achieved'}\n\n"
            f"SOP ({step.sop_ref}):\n{sop['body'] if sop else 'n/a'}\n\n"
            f"KNOWN FACTS: {json.dumps(ctx.scratch, default=str)}\n"
            f"INPUT FILES: {ctx.input_files}\nSYSTEMS:\n{registry.systems_summary()}\n"
            f"POLICY:\n{registry.policy_summary()}\n")


def run_step(step: Step, spec: TaskSpec, plan: Plan, ctx, tools_schema, observe_budget: int = 10) -> StepResult:
    msgs = [{"role": "user", "content": render_step_prompt(step, spec, plan, ctx)}]
    system = registry.prompt("executor")
    blocked = rejected = False
    for _ in range(observe_budget):
        r = llm.call(system, msgs, ctx, tools=tools_schema, max_tokens=1500)
        msgs.append({"role": "assistant", "content": r.content})
        calls = [b for b in r.content if b.type == "tool_use"]
        if not calls:                              # model says step is complete
            return StepResult(done=True, summary=llm.text_of(r), blocked=blocked, rejected_by_human=rejected)
        results = []
        for c in calls:
            action = Action(tool=tools.from_api_name(c.name), args=dict(c.input), rationale=llm.text_of(r), step_id=step.id)
            decision = policy.check(action, ctx)       # deterministic
            ctx.log("decision", {"action": action.model_dump(), "decision": decision.model_dump()})
            if decision.verdict == "ask":
                decision = human.request_approval(action, decision, ctx)     # blocks
                if decision.edited_args is not None:
                    action.args = decision.edited_args
            if decision.verdict == "block":
                obs = Observation(ok=False, error=f"blocked by policy: {decision.reason}")
                blocked = True
                rejected = rejected or decision.by_human
            else:
                obs = tools.run_tool(action.tool, action.args, ctx)
            ctx.steps_taken += 1
            ctx.record(step.id, action, obs)
            ctx.log("observation", {**obs.model_dump(exclude={"data"}), "tool": action.tool, "step_id": step.id,
                                    "tier": decision.tier, "args": action.args, "verdict": decision.verdict})
            results.append({"type": "tool_result", "tool_use_id": c.id, "content": compress(obs), "is_error": not obs.ok})
        msgs.append({"role": "user", "content": results})
        prune_snapshots(msgs)
        if rejected:
            return StepResult(done=False, summary="a human rejected a requested action", blocked=True, rejected_by_human=True)
        if ctx.stuck_in_step(step.id):
            return StepResult(done=False, summary="stuck: repeating actions without progress", blocked=blocked, stuck=True)
        if not ctx.budget_ok():
            return StepResult(done=False, summary=ctx.budget_reason() or "budget", blocked=blocked)
    return StepResult(done=False, summary="observe budget exhausted", blocked=blocked)
