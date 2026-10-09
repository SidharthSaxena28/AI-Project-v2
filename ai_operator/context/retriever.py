"""SOP retrieval. Start simple: keyword/trigger scoring; embeddings can be layered on with this as fallback."""
import pathlib
import re

import yaml

from .registry import ENV_DIR


def load_sops(dir=None):
    dir = pathlib.Path(dir) if dir else ENV_DIR / "sops"
    sops = []
    for p in sorted(dir.glob("*.md")):
        raw = p.read_text()
        _, fm, body = raw.split("---", 2)
        meta = yaml.safe_load(fm)
        sops.append({**meta, "body": body.strip(), "path": str(p)})
    return sops


def _words(s: str) -> set[str]:
    return set(re.findall(r"\w+", s.lower()))


def _stem(w: str) -> str:
    return w[:-2] if w.endswith("'s") else w


def retrieve(request: str, sops, k=2):
    words = {_stem(w) for w in _words(request)}

    def score(s):
        trig = {w for t in s.get("triggers", []) for w in _words(str(t))}
        return len(words & trig) * 3 + len(words & _words(s["title"]))

    ranked = sorted(sops, key=score, reverse=True)
    return [s for s in ranked[:k] if score(s) > 0]


def sops_index(sops) -> str:
    return "\n".join(f"- {s['id']}: {s['title']} (triggers: {', '.join(map(str, s.get('triggers', [])))})" for s in sops)
