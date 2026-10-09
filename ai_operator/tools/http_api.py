"""Allow-listed HTTP GET (host check enforced by the policy gate and again here)."""
import httpx
from urllib.parse import urlparse

from ..context import registry
from ..core.models import Observation
from .base import FunctionTool, register


def get(args, ctx):
    host = urlparse(args["url"]).hostname
    if host not in registry.policy()["allowed_hosts"]:
        return Observation(ok=False, error=f"host {host} not allowed")
    r = httpx.get(args["url"], timeout=10)
    return Observation(ok=r.status_code < 400, error=None if r.status_code < 400 else f"HTTP {r.status_code}",
                       text=r.text[:4000], data={"status": r.status_code})


def register_all():
    register(FunctionTool("http.get", "GET a URL on an allow-listed internal host (e.g. a portal /api/ endpoint).",
                          {"url": {"type": "string"}}, ["url"], get))
