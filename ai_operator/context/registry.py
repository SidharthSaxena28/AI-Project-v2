"""Loaders for systems.yaml / policy.yaml / prompts. Credentials never reach the model."""
import functools
import os
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV_DIR = pathlib.Path(os.environ.get("OPERATOR_COMPANY_ENV", ROOT / "company_env"))
PROMPTS = ROOT / "ai_operator" / "prompts"


@functools.lru_cache(maxsize=None)
def systems() -> dict:
    return yaml.safe_load((ENV_DIR / "systems.yaml").read_text())


@functools.lru_cache(maxsize=None)
def policy() -> dict:
    return yaml.safe_load((ENV_DIR / "policy.yaml").read_text())


def reload() -> None:
    systems.cache_clear()
    policy.cache_clear()


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text()


def abspath(p: str) -> pathlib.Path:
    p = pathlib.Path(p)
    return (p if p.is_absolute() else ROOT / p).resolve()


def under(path: str, allowed: list[str]) -> bool:
    """True if `path` resolves inside one of the allowed directories (blocks ../ tricks and symlinks)."""
    target = abspath(path)
    for a in allowed:
        base = abspath(a)
        if target == base or base in target.parents:
            return True
    return False


def resolve_db(name_or_path: str) -> pathlib.Path:
    dbs = systems().get("databases", {})
    if name_or_path in dbs:
        return abspath(dbs[name_or_path])
    p = abspath(name_or_path)
    if not under(str(p), policy()["allowed_read_paths"]):
        raise PermissionError(f"database path not allowed: {name_or_path}")
    return p


def schema_summary() -> str:
    """Table definitions of every read-only database alias, so SQL is written against real column names."""
    import sqlite3
    out = []
    for alias, path in systems().get("databases", {}).items():
        stmts = []
        p = abspath(path)
        if p.exists():
            try:
                con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
                stmts = [r[0] for r in con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")]
                con.close()
            except sqlite3.Error:
                stmts = []
        if not stmts:
            try:
                from company_env.common.db import SCHEMAS
                stmts = [x.strip() for x in SCHEMAS.get(alias, "").split(";") if x.strip()]
            except Exception:
                pass
        out.append(f"database '{alias}' tables (use EXACTLY these column names):\n" + "\n".join(" ".join(x.split()) for x in stmts))
    return "\n".join(out)


def systems_summary() -> str:
    """What the model may see: names, URLs, DB aliases and schemas. No credentials."""
    out = []
    for name, s in systems()["systems"].items():
        api = ", ".join(f"{k}={v}" for k, v in (s.get("api") or {}).items())
        out.append(f"- {name}: {s['description']} | url={s['base_url']} | login via browser.login(system='{name}') "
                   f"| sql db alias='{s.get('db')}' | api: {api}")
    return "\n".join(out) + "\n\nDATABASE SCHEMAS (read-only SQL):\n" + schema_summary()


def policy_summary() -> str:
    p = policy()
    return (f"- T0 read-only and T1 reversible edits run automatically.\n"
            f"- T2 commits (submit/create/confirm) run automatically only within limits "
            f"(expense claims up to INR {p['auto_approve']['expense_claim_max_inr']}); above that a human must approve.\n"
            f"- T3 external/irreversible actions (email, delete, pay, unknown) always need human approval.\n"
            f"- Only hosts {p['allowed_hosts']} and paths {p['allowed_read_paths']} may be touched.")


def credentials(system: str) -> tuple[str, str]:
    login = systems()["systems"][system]["login"]
    return (os.environ.get(login["user_env"], "operator"), os.environ.get(login["password_env"], "operator123"))
