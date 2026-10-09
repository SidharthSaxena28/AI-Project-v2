"""Deterministic policy gate. No LLM in this file: every verdict is reproducible and unit-tested.

Tiers: T0 read-only | T1 reversible edit | T2 commit (limits apply) | T3 external/irreversible/unknown.
"""
import re
from urllib.parse import urlparse

from ..context import registry
from .models import Action, Decision

READ_TOOLS = {"browser.snapshot", "browser.goto", "browser.wait", "browser.login", "files.read_pdf", "files.list_dir",
              "files.read_sheet", "sql.query", "memory.set", "memory.get", "human.ask", "vision.describe", "http.get"}
WRITE_T1 = {"browser.fill", "browser.select", "browser.upload", "files.write_sheet", "files.write_docx"}
PATH_ARGS = {"files.read_pdf": ("path",), "files.list_dir": ("path",), "files.read_sheet": ("path",),
             "files.write_docx": ("path", "template"), "files.write_sheet": ("path",), "browser.upload": ("paths", "path")}
WRITE_PATH_TOOLS = {"files.write_sheet", "files.write_docx"}


def _matches(patterns, label: str) -> bool:
    return any(re.search(p, label) for p in patterns)


def commit_decision(action: Action, ctx, label: str) -> Decision:
    """T2: depends on which system the page belongs to and on limits read from working memory."""
    pol = registry.policy()
    url = getattr(ctx, "current_url", "") or ""
    rule = next((r["rule"] for r in pol.get("commit_rules", []) if r["url_contains"] in url), "ask")
    if rule == "allow":
        return Decision(verdict="allow", tier="T2", reason=f"commit '{label}' permitted by system rule")
    if rule == "limit_expense":
        limit = pol["auto_approve"]["expense_claim_max_inr"]
        total = ctx.scratch.get("claim_total_inr")
        try:
            total = float(str(total).replace(",", ""))
        except (TypeError, ValueError):
            return Decision(verdict="ask", tier="T2", reason="commit with unknown claim total (claim_total_inr not recorded)")
        if total <= limit:
            return Decision(verdict="allow", tier="T2", reason=f"claim INR {total:g} within auto-approve limit {limit}")
        return Decision(verdict="ask", tier="T2", reason=f"claim INR {total:g} exceeds auto-approve limit {limit}")
    return Decision(verdict="ask", tier="T2", reason=f"commit '{label}' on unclassified system ({url})")


def _paths(action: Action) -> list[str]:
    out = []
    for k in PATH_ARGS.get(action.tool, ()):
        v = action.args.get(k)
        out += v if isinstance(v, list) else ([v] if v else [])
    return out


def check(action: Action, ctx) -> Decision:
    pol = registry.policy()
    t = action.tool

    # ---- hard blocks: hosts and paths outside the allow-lists ----
    if t in ("browser.goto", "http.get"):
        host = urlparse(action.args.get("url", "")).hostname
        if host not in pol["allowed_hosts"]:
            return Decision(verdict="block", tier="T3", reason=f"host {host} not allowed")
    for p in _paths(action):
        allowed = pol["allowed_write_paths"] if (t in WRITE_PATH_TOOLS and p == action.args.get("path")) else pol["allowed_read_paths"]
        if not registry.under(p, allowed):
            return Decision(verdict="block", tier="T3", reason=f"path {p} outside allowed paths")

    # ---- clicks: commit detection is structural (type=submit) as well as label-based ----
    if t == "browser.click":
        el = ctx.element_for_ref(action.args.get("ref", "")) or {}
        label = ctx.label_for_ref(action.args.get("ref", "")).lower()
        if _matches(pol.get("non_commit_labels", []), label):
            return Decision(verdict="allow", tier="T1", reason="navigation/dismiss control")
        if _matches(pol.get("destructive_labels", []), label):
            return Decision(verdict="ask", tier="T3", reason=f"destructive action '{label}'")
        if el.get("type") == "submit" or _matches(pol.get("commit_labels", []), label):
            return commit_decision(action, ctx, label)
        return Decision(verdict="allow", tier="T1", reason="reversible click")

    # Enter in a form field submits it - treat as a commit, not a keystroke
    if t == "browser.press":
        if str(action.args.get("key", "")).lower() in ("enter", "return"):
            return commit_decision(action, ctx, "enter (form submit)")
        return Decision(verdict="allow", tier="T1", reason="reversible keypress")

    if t in READ_TOOLS:
        return Decision(verdict="allow", tier="T0", reason="read-only")
    if t in WRITE_T1:
        return Decision(verdict="allow", tier="T1", reason="reversible")
    if t.startswith("email.") or t.startswith("http.post_external"):
        return Decision(verdict="ask", tier="T3", reason="external/irreversible")
    return Decision(verdict="ask", tier="T3", reason="unclassified action")   # default-deny-ish
