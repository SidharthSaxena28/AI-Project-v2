"""Free, local LLM backend via Ollama's OpenAI-compatible API. Translates the Anthropic-style messages/tools the
rest of the project uses into OpenAI chat format and back, so no other module has to change."""
import json
import os
import types
import uuid

URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


def _g(b, k, default=None):
    return b.get(k, default) if isinstance(b, dict) else getattr(b, k, default)


def to_openai_messages(system, messages):
    out = [{"role": "system", "content": system}] if system else []
    for m in messages:
        c = m["content"]
        if isinstance(c, str):
            out.append({"role": m["role"], "content": c})
            continue
        if m["role"] == "assistant":
            text = "".join(_g(b, "text", "") for b in c if _g(b, "type") == "text")
            calls = [{"id": _g(b, "id"), "type": "function",
                      "function": {"name": _g(b, "name"), "arguments": json.dumps(_g(b, "input", {}))}}
                     for b in c if _g(b, "type") == "tool_use"]
            msg = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:
            texts = []
            for b in c:
                if _g(b, "type") == "tool_result":
                    out.append({"role": "tool", "tool_call_id": _g(b, "tool_use_id"), "content": str(_g(b, "content", ""))})
                elif _g(b, "type") == "text":
                    texts.append(_g(b, "text", ""))
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
    return out


def to_openai_tools(tools):
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": t["input_schema"]}} for t in tools]


def from_openai(data):
    msg = data["choices"][0]["message"]
    blocks = []
    if msg.get("content"):
        blocks.append(types.SimpleNamespace(type="text", text=msg["content"]))
    for tc in msg.get("tool_calls") or []:
        args = tc["function"].get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except json.JSONDecodeError:
                args = {}
        blocks.append(types.SimpleNamespace(type="tool_use", id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                                            name=tc["function"]["name"], input=args))
    u = data.get("usage", {})
    return types.SimpleNamespace(content=blocks, stop_reason=data["choices"][0].get("finish_reason"),
                                 usage=types.SimpleNamespace(input_tokens=u.get("prompt_tokens", 0), output_tokens=u.get("completion_tokens", 0)))


def chat(system, messages, model, tools=None, max_tokens=2000):
    import httpx
    body = {"model": model, "messages": to_openai_messages(system, messages), "max_tokens": max_tokens, "temperature": 0}
    if tools:
        body["tools"] = to_openai_tools(tools)
    r = httpx.post(f"{URL}/v1/chat/completions", json=body, timeout=600)
    r.raise_for_status()
    return from_openai(r.json())
