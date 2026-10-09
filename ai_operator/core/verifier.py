"""Independent verification: postconditions are checked against observed system state, never against
what the executor claims. 'VERIFIED' is only emitted when every check passes."""
import json
import pathlib
import re

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ..context import registry
from ..tools import files as files_tool
from ..tools.sql import sql_ro
from . import llm
from .models import CheckResult, Plan, Postcondition, TaskSpec, VerificationResult

_PH = re.compile(r"\{(scratch|entities|files)\.([\w\-]+)\}")


# ---------- placeholder resolution ----------
def resolve(obj, ctx, spec: TaskSpec | None = None):
    """Substitute {scratch.k}, {entities.k}, {files.count}. An exact-match string keeps the value's type."""
    if isinstance(obj, dict):
        return {k: resolve(v, ctx, spec) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve(v, ctx, spec) for v in obj]
    if not isinstance(obj, str):
        return obj

    def lookup(scope, key):
        if scope == "scratch":
            return ctx.scratch.get(key)
        if scope == "entities":
            return (spec.entities if spec else {}).get(key)
        return len(ctx.input_files) if key == "count" else None

    m = _PH.fullmatch(obj)
    if m:
        return lookup(*m.groups())
    return _PH.sub(lambda mm: str(lookup(*mm.groups())), obj)


# ---------- matching ----------
def _eq(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 0.01
    except (TypeError, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()


def subset_match(row: dict, expect: dict) -> bool:
    return all(k in row and _eq(row[k], v) for k, v in expect.items())


def match(rows: list[dict], expect) -> bool:
    """Ordered, exact row count; each expected dict is a subset-match for its row."""
    if isinstance(expect, dict):
        expect = [expect]
    return len(rows) == len(expect) and all(subset_match(r, e) for r, e in zip(rows, expect))


def jmatch(data, expect) -> bool:
    if isinstance(expect, dict) and isinstance(data, dict):
        return all(k in data and jmatch(data[k], v) for k, v in expect.items())
    if isinstance(expect, list) and isinstance(data, list):
        return len(data) == len(expect) and all(jmatch(d, e) for d, e in zip(data, expect))
    return _eq(data, expect)


def file_check(spec: dict) -> tuple[bool, str]:
    p = registry.abspath(spec["path"])
    exists = p.exists()
    if spec.get("exists", True) is False:
        return (not exists), f"exists={exists}"
    if not exists:
        return False, "file does not exist"
    notes = [f"size={p.stat().st_size}"]
    ok = True
    suffix = p.suffix.lower()
    if "contains" in spec:
        if suffix == ".docx":
            from docx import Document
            text = "\n".join(x.text for x in Document(str(p)).paragraphs)
        elif suffix == ".pdf":
            text = files_tool.pdf_text(p)[0]
        else:
            text = p.read_text(errors="ignore")
        hit = str(spec["contains"]).lower() in text.lower()
        ok &= hit
        notes.append(f"contains({spec['contains']!r})={hit}")
    if suffix == ".xlsx" and ("min_rows" in spec or "rows_contain" in spec):
        rows = files_tool.sheet_rows(p)
        notes.append(f"rows={len(rows)}")
        if "min_rows" in spec:
            ok &= len(rows) >= int(spec["min_rows"])
        for exp in spec.get("rows_contain", []):
            hit = any(subset_match(r, exp) for r in rows)
            ok &= hit
            notes.append(f"row {exp} present={hit}")
        notes.append("sample=" + json.dumps(rows[:10], default=str)[:600])
    return ok, "; ".join(notes)


# ---------- LLM judge (fuzzy criteria only) ----------
class Judgement(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    pass_: bool = Field(alias="pass")
    reason: str = ""
    evidence_quote: str = ""


def evidence_for(pc: Postcondition, ctx, spec: TaskSpec | None = None) -> str:
    parts = []
    for q in resolve(pc.spec.get("evidence_sql", []), ctx, spec):
        try:
            parts.append(f"SQL {q['query']} {q.get('params', [])} => {json.dumps(sql_ro(q['db'], q['query'], q.get('params', [])), default=str)}")
        except Exception as e:                  # noqa: BLE001
            parts.append(f"SQL failed: {e}")
    for f in ctx.input_files[:8]:               # independent re-read of source documents
        try:
            p = registry.abspath(f)
            if p.suffix.lower() == ".pdf":
                parts.append(files_tool.wrap(f, files_tool.pdf_text(p)[0][:1500]))
        except Exception:
            parts.append(f"(could not re-read {f})")
    obs = [e["payload"] for e in ctx.events() if e["type"] == "observation"][-6:]
    parts.append("RECENT OBSERVATIONS:\n" + "\n".join(f"{o.get('tool')}: {(o.get('error') or o.get('text') or '')[:300]}" for o in obs))
    return "\n\n".join(parts)


def llm_judge(pc: Postcondition, evidence: str, ctx) -> tuple[bool, str]:
    user = f"SUCCESS CRITERION: {pc.description}\n\nEVIDENCE:\n{evidence}"
    j = llm.call_json(registry.prompt("verifier"), user, Judgement, ctx, model=llm.JUDGE, max_tokens=600)
    return j.pass_, f"{j.reason} | quote: {j.evidence_quote}"


# ---------- single check ----------
def check(pc: Postcondition, ctx, spec: TaskSpec | None = None) -> tuple[bool, str]:
    s = resolve(pc.spec, ctx, spec)
    try:
        if pc.kind == "sql":
            rows = sql_ro(s["db"], s["query"], s.get("params", []))
            return match(rows, s["expect"]), f"rows={json.dumps(rows, default=str)[:700]}"
        if pc.kind == "file":
            return file_check(s)
        if pc.kind == "http":
            r = httpx.get(s["url"], timeout=10)
            return jmatch(r.json(), s["expect"]), r.text[:300]
        if pc.kind == "ui":
            from ..tools.browser import get_browser
            snap, _ = get_browser().snapshot(ctx, shot=False)
            return s["contains"] in snap["text"], snap["url"]
        if pc.kind == "llm":
            return llm_judge(pc, evidence_for(pc, ctx, spec), ctx)
    except Exception as e:                      # noqa: BLE001  a check that errors is a failed check
        return False, f"check error: {type(e).__name__}: {e}"
    return False, f"unknown postcondition kind {pc.kind}"


def _run(pc: Postcondition, ctx, spec, authority) -> CheckResult:
    ok, actual = check(pc, ctx, spec)
    res = CheckResult(description=pc.description or pc.kind, kind=pc.kind, authority=authority,
                      expected=json.dumps(resolve(pc.spec, ctx, spec), default=str)[:500], actual=actual[:800], passed=ok)
    ctx.log("verify", res.model_dump())
    return res


# ---------- per-step and final ----------
def check_step(step, ctx, spec=None) -> bool:
    if not step.postconditions:
        return not step.state_changing        # state-changing steps without a postcondition can never pass
    return all(_run(pc, ctx, spec, "helper").passed for pc in step.postconditions)


def final(spec: TaskSpec, plan: Plan, ctx, escalated_reason: str | None = None) -> VerificationResult:
    """Authority = TaskSpec success criteria. Planner postconditions are helpers; any failure -> NOT_VERIFIED."""
    checks: list[CheckResult] = []
    for crit in spec.success_criteria:
        pc = crit.check or Postcondition(kind="llm", description=crit.description)
        if not pc.description:
            pc = pc.model_copy(update={"description": crit.description})
        checks.append(_run(pc, ctx, spec, "criterion"))
    for pc in plan.final_postconditions:
        checks.append(_run(pc, ctx, spec, "helper"))
    reasons = [f"FAILED: {c.description} -> {c.actual[:200]}" for c in checks if not c.passed]
    if plan.has_pending():
        reasons.append("plan has steps that never completed")
    if not any(c.authority == "criterion" for c in checks):
        reasons.append("TaskSpec defines no success criteria; cannot verify")
    if escalated_reason:
        return VerificationResult(outcome="ESCALATED", checks=checks, reasons=[escalated_reason] + reasons)
    outcome = "VERIFIED" if not reasons else "NOT_VERIFIED"
    return VerificationResult(outcome=outcome, checks=checks, reasons=reasons)
