"""Run state: append-only event log (SQLite), checkpoints, working memory, budgets, stuck detection."""
import hashlib
import json
import os
import pathlib
import sqlite3
import time
import uuid
from typing import Callable, Optional

from .models import Event, Plan, TaskSpec


class RunContext:
    def __init__(self, run_id: Optional[str] = None, root: str = "runs", *, max_steps: int = 80,
                 max_cost_usd: float = 3.0, max_seconds: int | None = None, max_retries_per_step: int = 3):
        if max_seconds is None:   # local models are slow: allow an hour by default, override with OPERATOR_MAX_SECONDS
            max_seconds = int(os.environ.get("OPERATOR_MAX_SECONDS", 3600 if os.environ.get("OPERATOR_PROVIDER") == "ollama" else 900))
        self.run_id = run_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.dir = pathlib.Path(root) / self.run_id
        (self.dir / "screens").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.dir / "events.db", check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS events(ts REAL, type TEXT, payload TEXT)")
        self.scratch: dict = {}            # typed working memory: extracted facts, ids
        self.cost_usd = 0.0
        self.steps_taken = 0
        self.started = time.time()
        self.max_steps, self.max_cost_usd = max_steps, max_cost_usd
        self.max_seconds, self.max_retries_per_step = max_seconds, max_retries_per_step
        # browser-derived view of the current page (set by tools/browser.py)
        self.refs: dict[str, dict] = {}
        self.current_url = ""
        self.last_screenshot: Optional[str] = None
        self.input_files: list[str] = []
        self.history: list[dict] = []      # action/observation signatures for stuck detection
        self.subscribers: list[Callable[[dict], None]] = []   # live UI hooks

    # ----- event log -----
    def log(self, type_: str, payload: dict) -> None:
        ts = time.time()
        body = json.dumps(payload, default=str)
        self.db.execute("INSERT INTO events VALUES (?,?,?)", (ts, type_, body))
        self.db.commit()
        ev = {"ts": ts, "type": type_, "payload": json.loads(body)}
        for fn in list(self.subscribers):
            try:
                fn(ev)
            except Exception:
                pass

    def events(self) -> list[dict]:
        return [dict(ts=r[0], type=r[1], payload=json.loads(r[2]))
                for r in self.db.execute("SELECT * FROM events ORDER BY rowid")]

    def typed_events(self) -> list[Event]:
        return [Event(**e) for e in self.events()]

    # ----- checkpoint / resume -----
    def checkpoint(self, spec: TaskSpec, plan: Plan) -> None:
        (self.dir / "checkpoint.json").write_text(json.dumps({
            "spec": spec.model_dump(), "plan": plan.model_dump(), "scratch": self.scratch,
            "input_files": self.input_files, "cost_usd": self.cost_usd, "steps_taken": self.steps_taken}))

    @classmethod
    def resume(cls, run_id: str, root: str = "runs", **kw):
        """Re-open a run directory. Returns (ctx, spec, plan); pending steps continue where they stopped."""
        ctx = cls(run_id, root, **kw)
        data = json.loads((ctx.dir / "checkpoint.json").read_text())
        ctx.scratch = data["scratch"]
        ctx.input_files = data.get("input_files", [])
        ctx.cost_usd = data.get("cost_usd", 0.0)
        ctx.steps_taken = data.get("steps_taken", 0)
        plan = Plan.model_validate(data["plan"])
        for s in plan.steps:                 # a step interrupted mid-flight is retried from the top
            if s.status == "failed":
                s.status = "pending"
        ctx.log("resume", {"pending": [s.id for s in plan.steps if s.status == "pending"]})
        return ctx, TaskSpec.model_validate(data["spec"]), plan

    # ----- helpers for the policy gate -----
    def element_for_ref(self, ref: str) -> Optional[dict]:
        return self.refs.get(ref)

    def label_for_ref(self, ref: str) -> str:
        el = self.refs.get(ref)
        if not el:
            return ""
        return " ".join(str(el.get(k, "")) for k in ("label", "text", "name", "value")).strip()

    # ----- budgets -----
    def budget_reason(self) -> Optional[str]:
        if self.steps_taken >= self.max_steps:
            return f"step budget exhausted ({self.max_steps})"
        if self.cost_usd >= self.max_cost_usd:
            return f"cost budget exhausted (${self.max_cost_usd:.2f})"
        if time.time() - self.started >= self.max_seconds:
            return f"time budget exhausted ({self.max_seconds}s)"
        return None

    def budget_ok(self) -> bool:
        return self.budget_reason() is None

    # ----- stuck detection (IMPLEMENTATION 3.3) -----
    def record(self, step_id: str, action, obs) -> None:
        sig = hashlib.md5(json.dumps([action.tool, action.args], sort_keys=True, default=str).encode()).hexdigest()
        ohash = hashlib.md5((obs.text or obs.error or "").encode()).hexdigest()
        self.history.append({"step_id": step_id, "tool": action.tool, "sig": sig,
                             "error": obs.error, "ohash": ohash, "args": action.args})

    def stuck_in_step(self, step_id: str) -> bool:
        h = [x for x in self.history if x["step_id"] == step_id]
        last3 = h[-3:]
        if len(last3) == 3 and all(x["error"] for x in last3) and len({(x["sig"], x["error"]) for x in last3}) == 1:
            return True                      # same action, same error, 3 times
        last5 = h[-5:]
        return len(last5) == 5 and len({x["ohash"] for x in last5}) == 1   # no new information in 5 steps

    def stuck(self, step) -> bool:
        return step.attempts > self.max_retries_per_step or self.stuck_in_step(step.id)

    def recent_actions(self, step_id: str, n: int = 5) -> list[str]:
        h = [x for x in self.history if x["step_id"] == step_id][-n:]
        return [f"{x['tool']}({json.dumps(x['args'], default=str)[:120]})" + (f" -> ERROR {x['error'][:100]}" if x["error"] else "") for x in h]
