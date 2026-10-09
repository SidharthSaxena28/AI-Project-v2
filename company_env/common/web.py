"""Shared plumbing for the mock portals: layout, login/session, health, and fault injection (CONTEXT section 10).

FAULTS env (comma separated, read per request so tests can toggle it):
  modal           privacy-policy overlay covers every page until dismissed
  rename_button   commit buttons get different wording
  session_expiry  the session is invalidated after N requests
  validation      a hidden required field (project code) appears after the first rejected submit
  flaky_500       the first POST (other than /login) fails with HTTP 500
  slow            every page takes FAULT_SLOW_SECONDS to respond
"""
import asyncio
import os
import secrets
import urllib.parse

import jinja2
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

SESSIONS: set[str] = set()
STATE = {"posts": 0, "requests": 0, "expired": False, "validation_shown": False}
RENAMES = {"Submit claim": "File reimbursement", "Create employee": "Register hire",
           "Create account": "Provision access", "Open ticket": "Raise request"}
EXEMPT = ("/login", "/health", "/api/", "/static")

BASE = """<!doctype html><html><head><meta charset=utf-8><title>{{ title }}</title>
<style>body{font:15px system-ui;margin:0;color:#1b2430}header{background:#1b2d45;color:#fff;padding:10px 24px;display:flex;gap:20px;align-items:center}
header a{color:#cfe3ff;text-decoration:none}main{max-width:820px;margin:24px auto;padding:0 16px}table{border-collapse:collapse;width:100%}
td,th{border-bottom:1px solid #dde;padding:6px 8px;text-align:left}label{display:block;margin:12px 0 3px;font-weight:600}
input,select,textarea{padding:6px;width:100%;box-sizing:border-box}button{margin-top:16px;padding:8px 18px;background:#1b2d45;color:#fff;border:0;border-radius:4px}
.err{background:#fde8e8;border:1px solid #e0a0a0;padding:8px;margin:12px 0}.ok{background:#e6f5ea;padding:8px}</style></head>
<body><header><b>{{ brand }}</b>{% for href,text in nav %}<a href="{{ href }}">{{ text }}</a>{% endfor %}</header>
<main>{% block body %}{% endblock %}</main></body></html>"""

_env = jinja2.Environment(autoescape=True, loader=jinja2.DictLoader({"base.html": BASE}))


def page(request: Request, brand: str, nav: list, body: str, status: int = 200, **ctx) -> HTMLResponse:
    """Render `body` (a jinja snippet) inside the shared layout."""
    tpl = _env.from_string('{% extends "base.html" %}{% block body %}' + body + "{% endblock %}")
    return HTMLResponse(tpl.render(title=brand, brand=brand, nav=nav, request=request, **ctx), status_code=status)


def faults() -> set[str]:
    return {f.strip() for f in os.environ.get("FAULTS", "").split(",") if f.strip()}


def reset_fault_state() -> None:
    SESSIONS.clear()
    STATE.update(posts=0, requests=0, expired=False, validation_shown=False)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path.startswith(EXEMPT) or request.cookies.get("op_session") in SESSIONS:
            return await call_next(request)
        return RedirectResponse(f"/login?next={urllib.parse.quote(path)}", status_code=303)


class FaultMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        f, path = faults(), request.url.path
        page_req = not path.startswith(EXEMPT)
        if page_req:
            STATE["requests"] += 1
            if "slow" in f:
                await asyncio.sleep(float(os.environ.get("FAULT_SLOW_SECONDS", "3")))
            if "session_expiry" in f and not STATE["expired"] and STATE["requests"] >= int(os.environ.get("FAULT_SESSION_REQS", "8")):
                STATE["expired"] = True
                SESSIONS.clear()                         # server forgets every session; next request -> /login
            if "flaky_500" in f and request.method == "POST" and path != "/login":
                STATE["posts"] += 1
                if STATE["posts"] == 1:
                    return HTMLResponse("<h1>Internal Server Error</h1><p>upstream timeout</p>", status_code=500)
        response = await call_next(request)
        if page_req and response.headers.get("content-type", "").startswith("text/html") and not (300 <= response.status_code < 400) \
                and ({"modal", "rename_button"} & f):
            body = b"".join([c async for c in response.body_iterator]).decode()
            if "rename_button" in f:
                for a, b in RENAMES.items():
                    body = body.replace(a, b)
            if "modal" in f:
                body = body.replace("</body>", MODAL + "</body>")
            headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "content-type")}
            return Response(body, status_code=response.status_code, headers=headers, media_type="text/html")
        return response


MODAL = """<div id="op-modal" style="position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:flex;align-items:center;justify-content:center">
<div style="background:#fff;padding:24px;max-width:360px"><p>We have updated our privacy policy. Please review and continue.</p>
<button type="button" onclick="sessionStorage.setItem('op-modal','1');document.getElementById('op-modal').remove()">Accept and continue</button></div></div>
<script>if(sessionStorage.getItem('op-modal')){document.getElementById('op-modal').remove()}</script>"""


def make_app(brand: str, init_fn) -> FastAPI:
    app = FastAPI(title=brand)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(FaultMiddleware)       # outermost: sees every request

    init_fn()                                 # create/seed the SQLite file as soon as the app is imported

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next: str = "/", error: str = ""):
        return page(request, brand, [], """<h2>Sign in</h2>{% if error %}<div class=err>{{ error }}</div>{% endif %}
            <form method=post action="/login"><input type=hidden name=next value="{{ next }}">
            <label for=u>Username</label><input id=u name=username><label for=p>Password</label><input id=p name=password type=password>
            <button type=submit>Sign in</button></form>""", next=next, error=error)

    @app.post("/login")
    def login(username: str = Form(""), password: str = Form(""), next: str = Form("/")):
        ok = username == os.environ.get("PORTAL_USER", "operator") and password == os.environ.get("PORTAL_PASSWORD", "operator123")
        if not ok:
            return RedirectResponse("/login?error=Invalid+credentials", status_code=303)
        token = secrets.token_hex(16)
        SESSIONS.add(token)
        r = RedirectResponse(next if next.startswith("/") else "/", status_code=303)
        r.set_cookie("op_session", token, httponly=True)
        return r

    return app
