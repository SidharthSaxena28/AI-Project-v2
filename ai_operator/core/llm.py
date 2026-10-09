"""Single LLM wrapper: retries, cost accounting, JSON validation."""
import json
import os
import re
import time

try:
    import anthropic
except ImportError:                      # not needed when OPERATOR_PROVIDER=ollama
    anthropic = None

from . import ollama

PROVIDER = os.environ.get("OPERATOR_PROVIDER", "anthropic")      # "anthropic" or "ollama" (free, local)
MODEL = os.environ.get("OPERATOR_MODEL", "qwen2.5:14b" if PROVIDER == "ollama" else "claude-sonnet-5-5")
JUDGE = os.environ.get("OPERATOR_JUDGE_MODEL", MODEL if PROVIDER == "ollama" else "claude-haiku-5-5")
_client = None

# $ per million tokens (input, output) - approximate; order matters (first substring match wins)
_PRICES = [("haiku", (1.0, 5.0)), ("opus", (5.0, 25.0)), ("sonnet", (3.0, 15.0))]
_RETRYABLE = (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) if anthropic else ()


def get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _cost(usage, model: str) -> float:
    pin, pout = next((p for k, p in _PRICES if k in model), (3.0, 15.0))
    return (getattr(usage, "input_tokens", 0) * pin + getattr(usage, "output_tokens", 0) * pout) / 1e6


def call(system, messages, ctx=None, model=None, tools=None, max_tokens=2000, retries=3):
    model = model or MODEL
    if PROVIDER == "ollama":
        last = None
        for i in range(retries):
            try:
                return ollama.chat(system, messages, model, tools, max_tokens)     # free: no cost accounting
            except Exception as e:                                                 # noqa: BLE001
                last = e
                time.sleep(2 ** i)
        raise RuntimeError(f"Ollama unavailable at {ollama.URL} (is `ollama serve` running and the model pulled?): {last}")
    kwargs = dict(model=model, system=system, messages=messages, max_tokens=max_tokens)
    if tools:
        kwargs["tools"] = tools
    last = None
    for i in range(retries):
        try:
            r = get_client().messages.create(**kwargs)
            if ctx:
                ctx.cost_usd += _cost(r.usage, model)
            return r
        except _RETRYABLE as e:            # 4xx errors (bad request, auth) are not retried
            last = e
            time.sleep(2 ** i)
    raise RuntimeError(f"LLM unavailable: {last}")


def text_of(r) -> str:
    return "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()


def extract_json(text: str) -> str:
    """Tolerate code fences / stray prose around a JSON object."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


def call_json(system, user, schema, ctx=None, model=None, max_tokens=4000):
    """Ask for JSON only; validate with Pydantic; one repair retry."""
    msg = [{"role": "user", "content": user + "\n\nReturn ONLY valid JSON. No prose, no fences."}]
    err = None
    for _ in range(2):
        r = call(system, msg, ctx, model, max_tokens=max_tokens)
        text = text_of(r)
        try:
            return schema.model_validate_json(extract_json(text))
        except Exception as e:             # noqa: BLE001
            err = e
            msg += [{"role": "assistant", "content": text or "{}"},
                    {"role": "user", "content": f"Invalid: {e}. Return corrected JSON only."}]
    raise ValueError(f"Could not obtain valid JSON: {err}")
