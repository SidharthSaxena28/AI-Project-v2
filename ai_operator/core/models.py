"""Pydantic contracts shared by every module (CONTEXT.md section 7)."""
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

Verdict = Literal["allow", "ask", "block"]
Tier = Literal["T0", "T1", "T2", "T3"]
Outcome = Literal["VERIFIED", "NOT_VERIFIED", "ESCALATED"]


class Lenient(BaseModel):
    """Base for models filled in by an LLM. Small models often emit null / lists / ints where we expect
    strings or lists: drop nulls (so defaults apply) and coerce the common slips instead of failing the run."""

    @model_validator(mode="before")
    @classmethod
    def _drop_nulls(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


def _as_str(v):
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return str(v)


class Event(BaseModel):
    ts: float
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------- verification ----------
class Postcondition(Lenient):
    """A machine-checkable claim about the world.

    kind=sql  spec: {db, query, params?, expect: [ {col: val}, ... ]}
    kind=file spec: {path, exists?, contains?, min_rows?, rows_contain?: [ {col: val} ]}
    kind=http spec: {url, expect: {key: val}}
    kind=ui   spec: {contains: "text"}
    kind=llm  spec: {evidence_sql?: [ {db, query, params?} ]}   (fuzzy criteria only)
    String values may hold {scratch.key}, {entities.key} or {files.count} placeholders.
    """
    kind: Literal["sql", "file", "http", "ui", "llm"]
    description: str = ""
    spec: dict[str, Any] = Field(default_factory=dict)

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v):
        v = str(v).strip().lower()
        return {"database": "sql", "db": "sql", "query": "sql", "web": "ui", "page": "ui", "browser": "ui", "api": "http"}.get(v, v)

    @field_validator("description", mode="before")
    @classmethod
    def _desc(cls, v):
        return _as_str(v)


class CheckResult(BaseModel):
    description: str
    kind: str = ""
    expected: str = ""
    actual: str = ""
    passed: bool = False
    authority: Literal["criterion", "helper"] = "criterion"


class VerificationResult(BaseModel):
    outcome: Outcome
    checks: list[CheckResult] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


# ---------- intake ----------
class Ambiguity(Lenient):
    question: str
    blocking: bool = False
    resolvable_from: str = ""      # e.g. "receipts" / "hr.employees" - planner turns this into a step


class SuccessCriterion(Lenient):
    description: str
    check: Optional[Postcondition] = None


class TaskSpec(Lenient):
    request: str = ""
    outcome: str
    entities: dict[str, Any] = Field(default_factory=dict)
    success_criteria: list[SuccessCriterion] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)


# ---------- planning ----------
class Step(Lenient):
    id: str
    goal: str
    kind: Literal["tool", "human"] = "tool"
    tool_hint: str = ""
    sop_ref: Optional[str] = None
    state_changing: bool = False
    postconditions: list[Postcondition] = Field(default_factory=list)
    status: Literal["pending", "done", "failed", "skipped"] = "pending"
    attempts: int = 0

    @field_validator("id", "goal", "tool_hint", mode="before")
    @classmethod
    def _strs(cls, v):
        return _as_str(v)

    @field_validator("sop_ref", mode="before")
    @classmethod
    def _sop(cls, v):
        if isinstance(v, (list, tuple)):
            v = v[0] if v else None
        return None if v in (None, "", "null", "none", "None") else str(v)

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v):
        return "human" if str(v).strip().lower() in ("human", "approval", "ask") else "tool"

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, v):
        return v if v in ("pending", "done", "failed", "skipped") else "pending"


class Plan(Lenient):
    version: int = 1
    steps: list[Step]
    final_postconditions: list[Postcondition] = Field(default_factory=list)
    sop_refs: list[str] = Field(default_factory=list)

    @field_validator("sop_refs", mode="before")
    @classmethod
    def _refs(cls, v):
        return [v] if isinstance(v, str) else [str(x) for x in v]

    def has_pending(self) -> bool:
        return any(s.status == "pending" for s in self.steps)

    def next(self) -> Optional[Step]:
        return next((s for s in self.steps if s.status == "pending"), None)

    def revise(self, remaining: list[Step]) -> "Plan":
        """Completed steps are frozen; only the remaining steps are replaced."""
        done = [s for s in self.steps if s.status == "done"]
        taken = {s.id for s in done}
        fresh = []
        for s in remaining:
            if s.id in taken:
                s = s.model_copy(update={"id": f"{s.id}-v{self.version + 1}"})
            s.status = "pending"
            fresh.append(s)
            taken.add(s.id)
        return Plan(version=self.version + 1, steps=done + fresh,
                    final_postconditions=self.final_postconditions, sop_refs=self.sop_refs)


class ReplanOut(Lenient):
    steps: list[Step]
    note: str = ""


# ---------- execution ----------
class Action(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    step_id: str = ""


class Decision(BaseModel):
    verdict: Verdict
    tier: Tier = "T3"
    reason: str = ""
    by_human: bool = False
    edited_args: Optional[dict[str, Any]] = None


class Observation(BaseModel):
    ok: bool = True
    error: Optional[str] = None
    text: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    screenshot: Optional[str] = None


class StepResult(BaseModel):
    done: bool
    summary: str = ""
    blocked: bool = False              # a policy block happened in this step
    rejected_by_human: bool = False    # a human said no
    stuck: bool = False