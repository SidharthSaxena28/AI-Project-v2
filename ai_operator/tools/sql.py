"""Read-only SQL on systems of record (mode=ro URI + SELECT-only guard)."""
import json
import re
import sqlite3

from ..context import registry
from ..core.models import Observation
from .base import FunctionTool, register

_SELECT = re.compile(r"^\s*(select|with)\b", re.I)


def sql_ro(db: str, query: str, params=()) -> list[dict]:
    if not _SELECT.match(query) or ";" in query.strip().rstrip(";"):
        raise ValueError("only a single SELECT statement is allowed")
    path = registry.resolve_db(db)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(query, list(params)).fetchmany(200)]
    finally:
        con.close()


def query(args, ctx):
    rows = sql_ro(args["db"], args["query"], args.get("params", []))
    return Observation(ok=True, text=json.dumps(rows, default=str), data={"rows": rows})


def register_all():
    register(FunctionTool("sql.query", "Run a read-only SELECT against a system database alias (expense, hr, ticketing).",
                          {"db": {"type": "string"}, "query": {"type": "string"},
                           "params": {"type": "array", "items": {}}}, ["db", "query"], query))
