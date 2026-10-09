"""Evidence Report (report.md + report.html): what was asked, what was done, what was *observed* to be true."""
import html
import json
import os
import time

from ..core import llm
from ..context import registry

BADGE = {"VERIFIED": "✅ VERIFIED", "NOT_VERIFIED": "⚠️ NOT VERIFIED", "ESCALATED": "🛑 ESCALATED"}


def _timeline(ctx) -> list[dict]:
    """Pair each decision with its observation (same order in the log)."""
    rows, pending = [], None
    for e in ctx.events():
        if e["type"] == "decision":
            pending = e["payload"]
        elif e["type"] == "observation":
            p = e["payload"]
            d = (pending or {}).get("decision", {})
            a = (pending or {}).get("action", {})
            shot = p.get("screenshot")
            rows.append({"step": p.get("step_id", ""), "tool": p.get("tool", ""), "tier": d.get("tier", p.get("tier", "")),
                         "verdict": d.get("verdict", ""), "args": json.dumps(a.get("args", p.get("args", {})), default=str)[:140],
                         "result": ("OK" if p.get("ok") else "ERR: " + str(p.get("error"))[:120]), "shot": shot})
            pending = None
    return rows


def _humans(ctx) -> dict:
    ev = ctx.events()
    pick = lambda t: [e["payload"] for e in ev if e["type"] == t]       # noqa: E731
    blocked = [e["payload"] for e in ev if e["type"] == "decision" and e["payload"]["decision"]["verdict"] == "block"]
    return {"approvals": list(zip(pick("approval_request"), pick("approval_response"))), "questions": list(zip(pick("question"), pick("answer"))),
            "help": pick("help_request"), "blocked": blocked}


def _summary(spec, result, ctx) -> str:
    if os.environ.get("OPERATOR_NO_LLM_SUMMARY"):
        return ""
    try:
        r = llm.call(registry.prompt("report"), [{"role": "user", "content": json.dumps({
            "request": spec.request, "outcome": result.outcome, "reasons": result.reasons,
            "checks": [(c.description, c.passed) for c in result.checks]})}], ctx, model=llm.JUDGE, max_tokens=300)
        return llm.text_of(r)
    except Exception:                                                  # noqa: BLE001
        return ""


def _rel(path, ctx):
    if not path:
        return ""
    try:
        return os.path.relpath(path, ctx.dir)
    except ValueError:
        return path


def _thumb(shot, ctx) -> str:
    if not shot:
        return ""
    src = html.escape(_rel(shot, ctx))
    return f'<a href="{src}"><img src="{src}" width="140"></a>'


def build(spec, plan, result, ctx) -> dict:
    elapsed = time.time() - ctx.started
    tl, hu = _timeline(ctx), _humans(ctx)
    summary = _summary(spec, result, ctx)
    cost = f"${ctx.cost_usd:.3f}"
    md = [f"# Evidence Report - {BADGE[result.outcome]}", f"Run `{ctx.run_id}`", ""]
    if summary:
        md += [summary, ""]
    md += ["## 1. Request and TaskSpec", f"**Request:** {spec.request}", f"**Outcome sought:** {spec.outcome}",
           f"**Entities:** `{json.dumps(spec.entities, default=str)}`", "**Success criteria:**"]
    md += [f"- {c.description}" for c in spec.success_criteria] or ["- (none)"]
    md += ["", "## 2. SOP and plan", f"SOP cited: {', '.join(plan.sop_refs) or 'none'} - plan version {plan.version}"]
    md += [f"{i}. [{s.status}] **{s.id}** {s.goal} _(tool: {s.tool_hint or '-'}, sop: {s.sop_ref or '-'})_" for i, s in enumerate(plan.steps, 1)]
    versions = [e["payload"] for e in ctx.events() if e["type"] == "replan"]
    md += [f"- replan v{v['from']}→v{v['to']}: {v.get('note', '')}" for v in versions]
    md += ["", "## 3. Timeline", "| # | step | tool | tier | verdict | args | result | screenshot |", "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(tl, 1):
        shot = f"![]({_rel(r['shot'], ctx)})" if r["shot"] else ""
        md.append(f"| {i} | {r['step']} | {r['tool']} | {r['tier']} | {r['verdict']} | `{r['args']}` | {r['result']} | {shot} |")
    md += ["", "## 4. Verification (observed state)", "| check | authority | expected | actual observed | result |", "|---|---|---|---|---|"]
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")      # noqa: E731
    for c in result.checks:
        md.append(f"| {esc(c.description)} | {c.authority} | `{esc(c.expected[:200])}` | `{esc(c.actual[:300])}` | {'PASS' if c.passed else 'FAIL'} |")
    if result.reasons:
        md += ["", "**Reasons:**"] + [f"- {r}" for r in result.reasons]
    md += ["", "## 5. Human interactions"]
    md += [f"- approval requested for `{rq['action']['tool']}` ({rq['tier']}: {rq['reason']}) → {'approved' if rs['approved'] else 'rejected'}" for rq, rs in hu["approvals"]]
    md += [f"- question: {q['question']} → {a['answer']}" for q, a in hu["questions"]]
    md += [f"- help requested on {h['step']}" for h in hu["help"]]
    md += [f"- BLOCKED: `{b['action']['tool']}` - {b['decision']['reason']}" for b in hu["blocked"]]
    if not (hu["approvals"] or hu["questions"] or hu["help"] or hu["blocked"]):
        md.append("- none")
    md += ["", "## 6. Cost, time, steps", f"- cost {cost} · wall time {elapsed:.0f}s · tool calls {ctx.steps_taken}"]
    text = "\n".join(md)
    (ctx.dir / "report.md").write_text(text)
    (ctx.dir / "report.html").write_text(_html(text, tl, result, ctx, spec, plan, hu, summary, cost, elapsed))
    return {"outcome": result.outcome, "result": result, "report_md": str(ctx.dir / "report.md"),
            "report_html": str(ctx.dir / "report.html"), "run_dir": str(ctx.dir), "cost_usd": ctx.cost_usd,
            "steps": ctx.steps_taken, "seconds": elapsed}


def _html(md_text, tl, result, ctx, spec, plan, hu, summary, cost, elapsed) -> str:
    e = html.escape
    colour = {"VERIFIED": "#0f7b4a", "NOT_VERIFIED": "#b26a00", "ESCALATED": "#b3261e"}[result.outcome]
    rows = "".join(
        f"<tr><td>{i}</td><td>{e(r['step'])}</td><td>{e(r['tool'])}</td><td class=t{e(r['tier'])}>{e(r['tier'])}</td>"
        f"<td>{e(r['verdict'])}</td><td><code>{e(r['args'])}</code></td><td>{e(r['result'])}</td>"
        f"<td>{_thumb(r['shot'], ctx)}</td></tr>"
        for i, r in enumerate(tl, 1))
    checks = "".join(
        f"<tr class={'ok' if c.passed else 'bad'}><td>{e(c.description)}</td><td>{c.authority}</td><td><code>{e(c.expected[:200])}</code></td>"
        f"<td><code>{e(c.actual[:300])}</code></td><td>{'PASS' if c.passed else 'FAIL'}</td></tr>" for c in result.checks)
    steps = "".join(f"<li>[{s.status}] <b>{e(s.id)}</b> {e(s.goal)}</li>" for s in plan.steps)
    reasons = "".join(f"<li>{e(r)}</li>" for r in result.reasons)
    human = "".join(f"<li>approval: {e(rq['action']['tool'])} ({rq['tier']}) → {'approved' if rs['approved'] else 'rejected'}</li>" for rq, rs in hu["approvals"])
    human += "".join(f"<li>question: {e(q['question'])} → {e(str(a['answer']))}</li>" for q, a in hu["questions"])
    human += "".join(f"<li>BLOCKED {e(b['action']['tool'])}: {e(b['decision']['reason'])}</li>" for b in hu["blocked"])
    return f"""<!doctype html><meta charset=utf-8><title>Evidence report {e(ctx.run_id)}</title>
<style>body{{font:15px/1.5 system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#14201c}}
h1{{border-left:8px solid {colour};padding-left:12px}}table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border:1px solid #ccd;padding:4px 6px;vertical-align:top;text-align:left}}tr.bad td{{background:#fdecea}}tr.ok td:last-child{{color:#0f7b4a}}
.tT0{{color:#667}}.tT1{{color:#0a7a74}}.tT2{{color:#b26a00}}.tT3{{color:#b3261e;font-weight:600}}code{{word-break:break-all}}</style>
<h1>{BADGE[result.outcome]}</h1><p>Run <code>{e(ctx.run_id)}</code> · {cost} · {elapsed:.0f}s · {ctx.steps_taken} tool calls</p>
<p>{e(summary)}</p>
<h2>1. Request</h2><p>{e(spec.request)}</p><p><b>Outcome sought:</b> {e(spec.outcome)}</p>
<h2>2. SOP and plan (v{plan.version})</h2><p>SOP: {e(', '.join(plan.sop_refs) or 'none')}</p><ol>{steps}</ol>
<h2>3. Timeline</h2><table><tr><th>#<th>step<th>tool<th>tier<th>verdict<th>args<th>result<th>screen</tr>{rows}</table>
<h2>4. Verification - observed state</h2><table><tr><th>check<th>authority<th>expected<th>actual<th>result</tr>{checks}</table><ul>{reasons}</ul>
<h2>5. Human interactions</h2><ul>{human or '<li>none</li>'}</ul>"""
