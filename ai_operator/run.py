"""CLI:  python -m ai_operator.run "Reimburse Priya's Mumbai trip" --files company_env/data/receipts/mumbai --start-portals"""
import argparse
import os

from rich.console import Console

from .core.human import CLIHuman, ScriptedHuman
from .portals import PortalSet
from .runner import execute


def main():
    ap = argparse.ArgumentParser(description="AI Operator")
    ap.add_argument("request", nargs="?", default="")
    ap.add_argument("--files", nargs="*", default=[])
    ap.add_argument("--start-portals", action="store_true", help="launch the mock portals for this run")
    ap.add_argument("--faults", default=os.environ.get("FAULTS", ""), help="modal,rename_button,session_expiry,validation,flaky_500,slow")
    ap.add_argument("--auto-approve", action="store_true", help="simulate a human that approves everything (demo only)")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    ap.add_argument("--resume", metavar="RUN_ID", help="resume a checkpointed run")
    a = ap.parse_args()
    if a.headed:
        os.environ["OPERATOR_HEADED"] = "1"
    human = ScriptedHuman() if a.auto_approve else CLIHuman()
    portals = PortalSet(a.faults) if a.start_portals else None
    if portals:
        portals.start()
    try:
        out = execute(a.request, a.files, human, run_id=a.resume, resume=bool(a.resume))
    finally:
        if portals:
            portals.stop()
    c = Console()
    badge = {"VERIFIED": "[bold green]VERIFIED", "NOT_VERIFIED": "[bold yellow]NOT VERIFIED", "ESCALATED": "[bold red]ESCALATED"}[out["outcome"]]
    c.rule(badge)
    for ch in out["result"].checks:
        c.print(("[green]PASS" if ch.passed else "[red]FAIL"), ch.description, f"[dim]{ch.actual[:120]}")
    for r in out["result"].reasons:
        c.print("  -", r)
    c.print(f"report: {out['report_html']}  cost=${out['cost_usd']:.3f} steps={out['steps']} time={out['seconds']:.0f}s")


if __name__ == "__main__":
    main()
