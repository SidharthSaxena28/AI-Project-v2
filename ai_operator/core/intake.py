"""request -> TaskSpec"""
import json
import pathlib

from ..context import registry
from ..context.retriever import load_sops, sops_index
from . import llm
from .models import TaskSpec


def expand_files(files) -> list[str]:
    out = []
    for f in files or []:
        p = registry.abspath(f)
        if p.is_dir():
            out += [str(x.relative_to(registry.ROOT)) for x in sorted(p.rglob("*")) if x.is_file()]
        else:
            out.append(str(p.relative_to(registry.ROOT)) if registry.ROOT in p.parents else str(p))
    return out


def intake(request: str, files, ctx) -> TaskSpec:
    expanded = expand_files(files)
    ctx.input_files = expanded
    user = json.dumps({"request": request, "input_files": expanded,
                       "systems": registry.systems_summary(), "sops_available": sops_index(load_sops())}, indent=1)
    spec = llm.call_json(registry.prompt("intake"), user, TaskSpec, ctx)
    spec.request, spec.files = request, expanded
    ctx.log("intake", spec.model_dump())
    return spec
