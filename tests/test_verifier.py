import sqlite3

import pytest

from ai_operator.context import registry
from ai_operator.core import verifier
from ai_operator.core.models import Plan, Postcondition, Step, SuccessCriterion, TaskSpec


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "t.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE claims(employee TEXT, amount_inr REAL, status TEXT)")
    con.execute("INSERT INTO claims VALUES ('Priya Sharma', 8420, 'pending_approval')")
    con.commit(); con.close()
    pol = {**registry.policy(), "allowed_read_paths": [str(tmp_path)]}
    monkeypatch.setattr(registry, "policy", lambda: pol)
    return str(p)


def sqlpc(db, expect, params=None):
    return Postcondition(kind="sql", description="claim", spec={"db": db, "query": "SELECT * FROM claims WHERE employee=?",
                                                               "params": params or ["Priya Sharma"], "expect": expect})


def test_sql_pass_and_fail(db, ctx):
    assert verifier.check(sqlpc(db, [{"amount_inr": 8420}]), ctx)[0]
    assert not verifier.check(sqlpc(db, [{"amount_inr": 8421}]), ctx)[0]
    assert verifier.check(sqlpc(db, [], ["Nobody"]), ctx)[0]                      # empty result matches empty expect
    assert not verifier.check(sqlpc(db, []), ctx)[0]                              # a row exists, none expected


def test_placeholders_keep_type_and_use_scratch(db, ctx):
    ctx.scratch["claim_total_inr"] = 8420
    pc = sqlpc(db, [{"amount_inr": "{scratch.claim_total_inr}"}], ["{scratch.name}"])
    ctx.scratch["name"] = "Priya Sharma"
    assert verifier.check(pc, ctx)[0]
    ctx.scratch["claim_total_inr"] = 1
    assert not verifier.check(pc, ctx)[0]


def test_check_errors_are_failures_not_crashes(ctx):
    ok, msg = verifier.check(Postcondition(kind="sql", spec={"db": "nope", "query": "SELECT 1", "expect": []}), ctx)
    assert not ok and "check error" in msg


def test_file_checks(tmp_path, ctx, monkeypatch):
    from openpyxl import Workbook
    pol = {**registry.policy(), "allowed_read_paths": [str(tmp_path)]}
    monkeypatch.setattr(registry, "policy", lambda: pol)
    wb = Workbook(); ws = wb.active; ws.append(["invoice_no", "status"]); ws.append(["A1", "matched"]); wb.save(tmp_path / "r.xlsx")
    ok = Postcondition(kind="file", spec={"path": str(tmp_path / "r.xlsx"), "min_rows": 1, "rows_contain": [{"invoice_no": "A1", "status": "matched"}]})
    bad = Postcondition(kind="file", spec={"path": str(tmp_path / "r.xlsx"), "rows_contain": [{"invoice_no": "A1", "status": "amount_mismatch"}]})
    assert verifier.check(ok, ctx)[0] and not verifier.check(bad, ctx)[0]
    assert not verifier.check(Postcondition(kind="file", spec={"path": str(tmp_path / "missing.xlsx")}), ctx)[0]


def test_http_check(ctx, monkeypatch):
    class R:
        text = '{"ok": true}'
        def json(self): return {"ok": True}
    monkeypatch.setattr(verifier.httpx, "get", lambda *a, **k: R())
    assert verifier.check(Postcondition(kind="http", spec={"url": "http://localhost:1/x", "expect": {"ok": True}}), ctx)[0]


def test_llm_kind_uses_judge(ctx, monkeypatch):
    monkeypatch.setattr(verifier, "llm_judge", lambda pc, ev, c: (False, "insufficient evidence"))
    assert not verifier.check(Postcondition(kind="llm", description="x"), ctx)[0]


def test_state_changing_step_without_postcondition_never_passes(ctx):
    assert not verifier.check_step(Step(id="s", goal="g", state_changing=True), ctx)
    assert verifier.check_step(Step(id="s", goal="g"), ctx)


def test_no_success_without_verification(db, ctx):
    plan = Plan(steps=[Step(id="s1", goal="g", status="done")])
    assert verifier.final(TaskSpec(outcome="o"), plan, ctx).outcome == "NOT_VERIFIED"      # no criteria -> cannot verify
    spec = TaskSpec(outcome="o", success_criteria=[SuccessCriterion(description="c", check=sqlpc(db, [{"amount_inr": 1}]))])
    r = verifier.final(spec, plan, ctx)
    assert r.outcome == "NOT_VERIFIED" and "FAILED" in r.reasons[0]
    spec = TaskSpec(outcome="o", success_criteria=[SuccessCriterion(description="c", check=sqlpc(db, [{"amount_inr": 8420}]))])
    assert verifier.final(spec, plan, ctx).outcome == "VERIFIED"


def test_pending_steps_block_verified(db, ctx):
    spec = TaskSpec(outcome="o", success_criteria=[SuccessCriterion(description="c", check=sqlpc(db, [{"amount_inr": 8420}]))])
    plan = Plan(steps=[Step(id="s1", goal="g", status="pending")])
    assert verifier.final(spec, plan, ctx).outcome == "NOT_VERIFIED"


def test_escalation_is_reported_as_escalated(db, ctx):
    r = verifier.final(TaskSpec(outcome="o"), Plan(steps=[]), ctx, escalated_reason="human aborted")
    assert r.outcome == "ESCALATED"
