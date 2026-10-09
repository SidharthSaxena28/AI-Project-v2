"""DOM-first browser tool. Interactive elements get stable refs; the model sees a compact list, not raw HTML."""
import os
import pathlib
import threading

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from ..context import registry
from ..core.models import Observation
from .base import FunctionTool, register

SNAPSHOT_JS = """
() => {
  document.querySelectorAll('[data-op-ref]').forEach(e => e.removeAttribute('data-op-ref'));
  const els = [...document.querySelectorAll('a,button,input,select,textarea,[role=button],[onclick]')];
  let i = 0; const out = [];
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || getComputedStyle(el).visibility === 'hidden') continue;
    const ref = 'e' + (++i); el.setAttribute('data-op-ref', ref);
    out.push({ref, tag: el.tagName.toLowerCase(), type: el.type || '', name: el.name || '',
              label: (el.labels && el.labels[0]?.innerText) || el.getAttribute('aria-label') || '',
              text: (el.innerText || el.value || '').trim().slice(0, 80),
              value: (el.tagName === 'INPUT' && el.type !== 'file' && el.type !== 'password') ? (el.value || '').slice(0, 60) : '',
              disabled: el.disabled || false});
  }
  return {url: location.href, title: document.title,
          text: document.body.innerText.slice(0, 2500), elements: out};
}
"""


class Browser:
    def __init__(self, headless: bool = True):
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=headless)
        self.page = self.browser.new_page()
        self.last_status = None
        self.page.on("response", self._on_response)

    def _on_response(self, resp):
        try:
            if resp.request.is_navigation_request() and resp.frame == self.page.main_frame:
                self.last_status = resp.status
        except Exception:
            pass

    def snapshot(self, ctx, shot: bool = True):
        snap = self.page.evaluate(SNAPSHOT_JS)
        snap["status"] = self.last_status
        path = None
        if shot:
            path = str(ctx.dir / "screens" / f"{ctx.steps_taken:03d}.png")
            self.page.screenshot(path=path)
        return snap, path

    def close(self):
        try:
            self.browser.close()
            self.pw.stop()
        except Exception:
            pass


_local = threading.local()


def get_browser() -> Browser:
    """One browser per thread (Playwright's sync API is thread-bound)."""
    if getattr(_local, "b", None) is None:
        _local.b = Browser(headless=os.environ.get("OPERATOR_HEADED", "") == "")
    return _local.b


def close_browser():
    b = getattr(_local, "b", None)
    if b:
        b.close()
        _local.b = None


def format_snapshot(snap: dict) -> str:
    lines = [f"SNAPSHOT url={snap['url']} title={snap['title']!r} status={snap.get('status')}",
             "--- page text ---", snap["text"], "--- interactive elements ---"]
    for e in snap["elements"]:
        bits = [f"[{e['ref']}] {e['tag']}"]
        if e["type"]:
            bits.append(f"type={e['type']}")
        if e["name"]:
            bits.append(f"name={e['name']}")
        if e["label"]:
            bits.append(f"label={e['label'].strip()!r}")
        if e["text"] and e["tag"] in ("a", "button"):
            bits.append(f"text={e['text']!r}")
        if e.get("value"):
            bits.append(f"value={e['value']!r}")
        if e["disabled"]:
            bits.append("DISABLED")
        lines.append(" ".join(bits))
    return "\n".join(lines)


def _obs(ctx, ok=True, error=None, prefix="") -> Observation:
    snap, path = get_browser().snapshot(ctx)
    ctx.refs = {e["ref"]: e for e in snap["elements"]}
    ctx.current_url = snap["url"]
    ctx.last_screenshot = path
    text = (prefix + "\n" if prefix else "") + format_snapshot(snap)
    return Observation(ok=ok, error=error, text=text, data=snap, screenshot=path)


def _settle(page):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except PWTimeout:
        pass


def _loc(ref):
    page = get_browser().page
    loc = page.locator(f'[data-op-ref="{ref}"]')
    return loc if loc.count() else None


STALE = "stale ref; re-snapshot"


def goto(args, ctx):
    try:
        get_browser().page.goto(args["url"], wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        return _obs(ctx, ok=False, error=f"navigation failed: {type(e).__name__}: {str(e)[:200]}")
    return _obs(ctx)


def snapshot(args, ctx):
    return _obs(ctx)


def click(args, ctx):
    loc = _loc(args["ref"])
    if not loc:
        return Observation(ok=False, error=STALE)
    try:
        loc.first.click(timeout=3000)
    except PWTimeout as e:
        return _obs(ctx, ok=False, error="click failed - element may be covered by an overlay/modal or disabled: "
                    + str(e).splitlines()[0][:160])
    _settle(get_browser().page)
    return _obs(ctx)


def fill(args, ctx):
    loc = _loc(args["ref"])
    if not loc:
        return Observation(ok=False, error=STALE)
    try:
        loc.first.fill(str(args["text"]), timeout=3000)
    except PWTimeout as e:
        return _obs(ctx, ok=False, error="fill failed (covered or not editable): " + str(e).splitlines()[0][:160])
    return _obs(ctx)


def select(args, ctx):
    loc = _loc(args["ref"])
    if not loc:
        return Observation(ok=False, error=STALE)
    try:
        try:
            loc.first.select_option(value=args["value"], timeout=3000)
        except Exception:
            loc.first.select_option(label=args["value"], timeout=3000)
    except PWTimeout as e:
        return _obs(ctx, ok=False, error="select failed: " + str(e).splitlines()[0][:160])
    return _obs(ctx)


def upload(args, ctx):
    loc = _loc(args["ref"])
    if not loc:
        return Observation(ok=False, error=STALE)
    paths = args.get("paths") or [args.get("path")]
    abs_paths = [str(registry.abspath(p)) for p in paths if p]
    missing = [p for p in abs_paths if not pathlib.Path(p).exists()]
    if missing:
        return Observation(ok=False, error=f"file(s) not found: {missing}")
    loc.first.set_input_files(abs_paths)
    return _obs(ctx, prefix=f"attached {len(abs_paths)} file(s)")


def press(args, ctx):
    get_browser().page.keyboard.press(args["key"])
    _settle(get_browser().page)
    return _obs(ctx)


def wait(args, ctx):
    get_browser().page.wait_for_timeout(min(int(args.get("ms", 1000)), 10000))
    return _obs(ctx)


def login(args, ctx):
    """Log in using the systems registry. Credentials are read here and never exposed to the model."""
    name = args["system"]
    systems = registry.systems()["systems"]
    if name not in systems:
        return Observation(ok=False, error=f"unknown system {name}; known: {list(systems)}")
    s = systems[name]
    user, pw = registry.credentials(name)
    page = get_browser().page
    page.goto(s["base_url"] + s["login"]["path"], wait_until="domcontentloaded", timeout=30000)
    page.fill("input[name=username]", user)
    page.fill("input[name=password]", pw)
    page.click("button[type=submit]", timeout=5000)
    _settle(page)
    ok = "/login" not in page.url
    return _obs(ctx, ok=ok, error=None if ok else "login failed", prefix=f"logged in to {name}" if ok else "")


def register_all():
    ref = {"ref": {"type": "string", "description": "element ref like e3 from the latest snapshot"}}
    register(FunctionTool("browser.goto", "Open a URL (allow-listed hosts only). Returns a snapshot.",
                          {"url": {"type": "string"}}, ["url"], goto))
    register(FunctionTool("browser.snapshot", "Re-read the current page: text + numbered interactive elements.", {}, [], snapshot))
    register(FunctionTool("browser.click", "Click an element by ref.", ref, ["ref"], click))
    register(FunctionTool("browser.fill", "Type text into an input/textarea by ref.",
                          {**ref, "text": {"type": "string"}}, ["ref", "text"], fill))
    register(FunctionTool("browser.select", "Choose an option in a <select> by value or visible label.",
                          {**ref, "value": {"type": "string"}}, ["ref", "value"], select))
    register(FunctionTool("browser.upload", "Attach one or more local files to a file input.",
                          {**ref, "paths": {"type": "array", "items": {"type": "string"}}}, ["ref", "paths"], upload))
    register(FunctionTool("browser.press", "Press a keyboard key (e.g. Escape).", {"key": {"type": "string"}}, ["key"], press))
    register(FunctionTool("browser.wait", "Wait N milliseconds (max 10000), then snapshot. Use for backoff.",
                          {"ms": {"type": "integer"}}, ["ms"], wait))
    register(FunctionTool("browser.login", "Log in to a registered system (credentials handled securely).",
                          {"system": {"type": "string"}}, ["system"], login))
