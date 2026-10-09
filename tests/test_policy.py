import pytest

from ai_operator.core import policy
from ai_operator.core.models import Action


def A(tool, **args):
    return Action(tool=tool, args=args)


def with_el(ctx, ref, url, **el):
    ctx.refs = {ref: {"ref": ref, "tag": "button", "type": "", "name": "", "label": "", "text": "", "value": "", **el}}
    ctx.current_url = url


EXP = "http://localhost:8001/claims/new"


@pytest.mark.parametrize("tool", ["browser.snapshot", "files.read_pdf", "sql.query", "memory.set", "http.get"])
def test_reads_are_t0(ctx, tool):
    d = policy.check(A(tool, path="company_env/data/receipts/mumbai/x.pdf", url="http://localhost:8001/api/claims"), ctx)
    assert (d.verdict, d.tier) == ("allow", "T0")


def test_fill_is_t1(ctx):
    assert policy.check(A("browser.fill", ref="e1", text="x"), ctx).tier == "T1"


def test_unknown_tool_asks(ctx):
    d = policy.check(A("shell.exec", cmd="rm -rf /"), ctx)
    assert (d.verdict, d.tier) == ("ask", "T3")


def test_email_is_t3_ask(ctx):
    assert policy.check(A("email.send", to="a@b.c", subject="s", body="b"), ctx).verdict == "ask"


def test_disallowed_host_blocked(ctx):
    d = policy.check(A("browser.goto", url="https://evil.example/steal"), ctx)
    assert d.verdict == "block"


def test_path_outside_allowed_blocked(ctx):
    assert policy.check(A("files.read_pdf", path="/etc/passwd"), ctx).verdict == "block"
    assert policy.check(A("files.read_pdf", path="company_env/data/../../../etc/passwd"), ctx).verdict == "block"
    assert policy.check(A("files.write_sheet", path="company_env/data/expense.db", rows=[]), ctx).verdict == "block"


def test_plain_click_allowed(ctx):
    with_el(ctx, "e1", EXP, tag="a", text="Claims")
    assert policy.check(A("browser.click", ref="e1"), ctx).tier == "T1"


def test_signin_is_not_a_commit(ctx):
    with_el(ctx, "e1", "http://localhost:8001/login", type="submit", text="Sign in")
    assert policy.check(A("browser.click", ref="e1"), ctx).verdict == "allow"


def test_modal_dismiss_not_a_commit(ctx):
    with_el(ctx, "e1", EXP, type="button", text="Accept and continue")
    assert policy.check(A("browser.click", ref="e1"), ctx).verdict == "allow"


def test_commit_within_limit_allowed(ctx):
    with_el(ctx, "e1", EXP, type="submit", text="Submit claim")
    ctx.scratch["claim_total_inr"] = 8420
    d = policy.check(A("browser.click", ref="e1"), ctx)
    assert (d.verdict, d.tier) == ("allow", "T2")


def test_commit_over_limit_asks(ctx):
    with_el(ctx, "e1", EXP, type="submit", text="Submit claim")
    ctx.scratch["claim_total_inr"] = "48,920"
    d = policy.check(A("browser.click", ref="e1"), ctx)
    assert (d.verdict, d.tier) == ("ask", "T2") and "exceeds" in d.reason


def test_commit_with_unknown_total_asks(ctx):
    with_el(ctx, "e1", EXP, type="submit", text="Submit claim")
    assert policy.check(A("browser.click", ref="e1"), ctx).verdict == "ask"


def test_renamed_submit_button_is_still_gated(ctx):
    with_el(ctx, "e1", EXP, type="submit", text="File reimbursement")
    ctx.scratch["claim_total_inr"] = 99999
    assert policy.check(A("browser.click", ref="e1"), ctx).verdict == "ask"


def test_enter_key_is_treated_as_commit(ctx):
    ctx.current_url = EXP
    ctx.scratch["claim_total_inr"] = 99999
    assert policy.check(A("browser.press", key="Enter"), ctx).verdict == "ask"
    assert policy.check(A("browser.press", key="Escape"), ctx).verdict == "allow"


def test_hr_commit_allowed_by_system_rule(ctx):
    with_el(ctx, "e1", "http://localhost:8002/employees/new", type="submit", text="Create employee")
    assert policy.check(A("browser.click", ref="e1"), ctx).tier == "T2"


def test_unclassified_system_commit_asks(ctx):
    with_el(ctx, "e1", "http://localhost:9999/x", type="submit", text="Go")
    assert policy.check(A("browser.click", ref="e1"), ctx).verdict == "ask"


def test_destructive_click_is_t3(ctx):
    with_el(ctx, "e1", "http://localhost:8002/", text="Delete employee")
    d = policy.check(A("browser.click", ref="e1"), ctx)
    assert (d.verdict, d.tier) == ("ask", "T3")
