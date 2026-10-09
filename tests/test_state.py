from ai_operator.core.models import Action, Observation, Plan, Postcondition, Step, TaskSpec
from ai_operator.core.state import RunContext


def mk_plan():
    return Plan(steps=[Step(id="s1", goal="read", status="done"), Step(id="s2", goal="fill"), Step(id="s3", goal="submit", state_changing=True,
                postconditions=[Postcondition(kind="sql", spec={})])])


def test_events_roundtrip(ctx):
    ctx.log("a", {"x": 1})
    ctx.log("b", {"y": [1, 2]})
    assert [(e["type"], e["payload"]) for e in ctx.events()] == [("a", {"x": 1}), ("b", {"y": [1, 2]})]


def test_resume_from_checkpoint_continues_at_right_step(tmp_path):
    ctx = RunContext("r1", root=str(tmp_path))
    ctx.scratch["claim_total_inr"] = 8420
    ctx.steps_taken = 7
    ctx.checkpoint(TaskSpec(request="req", outcome="o"), mk_plan())
    ctx2, spec, plan = RunContext.resume("r1", root=str(tmp_path))
    assert spec.request == "req" and ctx2.scratch["claim_total_inr"] == 8420 and ctx2.steps_taken == 7
    assert plan.next().id == "s2"                       # s1 stays done
    assert any(e["type"] == "resume" for e in ctx2.events())


def test_plan_revise_freezes_completed_steps():
    p = mk_plan()
    q = p.revise([Step(id="s2", goal="retry fill"), Step(id="s3", goal="submit")])
    assert q.version == 2 and q.steps[0].id == "s1" and q.steps[0].status == "done"
    assert len({s.id for s in q.steps}) == len(q.steps)


def test_stuck_same_action_same_error(ctx):
    a = Action(tool="browser.click", args={"ref": "e1"})
    for _ in range(3):
        ctx.record("s1", a, Observation(ok=False, error="stale ref"))
    assert ctx.stuck_in_step("s1")


def test_not_stuck_when_errors_differ(ctx):
    for i in range(3):
        ctx.record("s1", Action(tool="browser.click", args={"ref": f"e{i}"}), Observation(ok=False, error="stale ref"))
    assert not ctx.stuck_in_step("s1")


def test_stuck_when_no_new_information(ctx):
    for i in range(5):
        ctx.record("s1", Action(tool="browser.snapshot", args={"i": i}), Observation(ok=True, text="same page"))
    assert ctx.stuck_in_step("s1")


def test_retry_budget_marks_stuck(ctx):
    s = Step(id="s1", goal="x", attempts=4)
    assert ctx.stuck(s)


def test_budgets(ctx):
    assert ctx.budget_ok()
    ctx.cost_usd = 99
    assert "cost" in ctx.budget_reason()
