"""FastAPI + SSE console.  python -m ai_operator.ui.server [--faults modal] [--port 8000]
POST /runs · GET /runs/{id}/stream · POST /runs/{id}/approve · POST /runs/{id}/answer"""
import argparse
import asyncio
import json
import os
import re
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..portals import PortalSet
from ..runner import execute

STATIC = os.path.join(os.path.dirname(__file__), "static")
app = FastAPI(title="AI Operator console")
RUNS: dict[str, "RunState"] = {}


def _get(rid):
    if rid not in RUNS:
        raise HTTPException(404)
    return RUNS[rid]
APPROVAL_TIMEOUT = int(os.environ.get("OPERATOR_APPROVAL_TIMEOUT", "600"))


class WebHuman:
    """Blocks the run thread until the browser UI answers (timeout = not approved)."""

    def __init__(self):
        self._ev, self._resp = threading.Event(), None

    def _wait(self):
        self._ev.clear()
        if not self._ev.wait(APPROVAL_TIMEOUT):
            raise TimeoutError("no human response")
        return self._resp

    def respond(self, resp):
        self._resp = resp
        self._ev.set()

    def approve(self, action, decision, ctx):
        r = self._wait()
        return r.get("decision") in ("approve", "edit"), (r.get("args") if r.get("decision") == "edit" else None)

    def ask(self, question, ctx, options=None):
        return str(self._wait().get("answer", ""))

    def help(self, summary, ctx):
        return self._wait().get("answer") or None


class RunState:
    def __init__(self, run_id):
        self.run_id, self.events, self.human = run_id, [], WebHuman()
        self.done, self.report = False, None

    def push(self, ev):
        self.events.append(ev)


class StartBody(BaseModel):
    request: str
    files: list[str] = []


class ApproveBody(BaseModel):
    decision: str                 # approve | reject | edit
    args: dict | None = None


class AnswerBody(BaseModel):
    answer: str = ""


def _worker(st: RunState, body: StartBody):
    try:
        out = execute(body.request, body.files, st.human, run_id=st.run_id, subscribers=[st.push])
        st.report = {"outcome": out["outcome"], "cost_usd": out["cost_usd"], "steps": out["steps"],
                     "reasons": out["result"].reasons}
    except Exception as e:                                   # noqa: BLE001
        st.report = {"outcome": "ESCALATED", "reasons": [f"{type(e).__name__}: {e}"]}
    st.done = True


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.post("/runs")
def start(body: StartBody):
    rid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    st = RUNS[rid] = RunState(rid)
    threading.Thread(target=_worker, args=(st, body), daemon=True).start()
    return {"run_id": rid}


@app.get("/runs/{rid}/stream")
async def stream(rid: str):
    st = _get(rid)

    async def gen():
        i = 0
        while True:
            while i < len(st.events):
                yield {"data": json.dumps(st.events[i])}
                i += 1
            if st.done and i >= len(st.events):
                yield {"event": "done", "data": json.dumps(st.report)}
                return
            await asyncio.sleep(0.25)
    return EventSourceResponse(gen())


@app.post("/runs/{rid}/approve")
def approve(rid: str, body: ApproveBody):
    (_get(rid)).human.respond(body.model_dump())
    return {"ok": True}


@app.post("/runs/{rid}/answer")
def answer(rid: str, body: AnswerBody):
    (_get(rid)).human.respond(body.model_dump())
    return {"ok": True}


@app.get("/runs/{rid}/screens/{name}")
def screen(rid: str, name: str):
    if not re.fullmatch(r"[\w\-]+\.png", name) or not re.fullmatch(r"[\w\-]+", rid):
        raise HTTPException(400)
    p = os.path.join("runs", rid, "screens", name)
    if not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/runs/{rid}/report")
def report(rid: str):
    if not re.fullmatch(r"[\w\-]+", rid):
        raise HTTPException(400)
    p = os.path.join("runs", rid, "report.html")
    if not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p)


if __name__ == "__main__":
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--faults", default=os.environ.get("FAULTS", ""))
    ap.add_argument("--no-portals", action="store_true")
    a = ap.parse_args()
    portals = None if a.no_portals else PortalSet(a.faults)
    if portals:
        portals.start()
    try:
        uvicorn.run(app, port=a.port)
    finally:
        if portals:
            portals.stop()
