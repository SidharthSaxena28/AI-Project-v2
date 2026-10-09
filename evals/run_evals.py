"""python -m evals.run_evals [--runs 5] [--only fault_modal expense_happy] [--model ...]
For each scenario x N runs: reset company state -> start portals (with faults) -> run operator with a scripted human ->
compare to ground truth independently of the verifier -> results.json + printed table."""
import argparse
import json
import pathlib
import time

import yaml
from rich.console import Console
from rich.table import Table

from ai_operator.core.human import ScriptedHuman
from ai_operator.portals import PortalSet
from ai_operator.runner import execute
from company_env.common import db
from company_env.data import make_data
from evals import metrics

HERE = pathlib.Path(__file__).parent


def load(only):
    sc = [yaml.safe_load(p.read_text()) for p in sorted((HERE / "scenarios").glob("*.yaml"))]
    return [s for s in sc if not only or s["id"] in only]


def human_for(sc) -> ScriptedHuman:
    a = sc.get("approvals", {})
    return ScriptedHuman(default="approve" if a.get("auto", True) else "reject", reject_tools=a.get("reject_tools", []),
                         reject_tiers=a.get("reject_tiers", []), answers=a.get("answers"), help_text=a.get("help"))


def run_one(sc, i) -> dict:
    db.reset_all()
    t0 = time.time()
    with PortalSet(",".join(sc.get("faults", []))):
        human = human_for(sc)
        out = execute(sc["request"], sc.get("files", []), human, run_id=f"{sc['id']}-{i}-{int(t0)}", root="runs/evals")
    j = metrics.judge_run(sc, out["outcome"])
    if sc.get("min_approvals") and not any(h["kind"] == "approval" for h in human.log):
        j["passed"] = False
        j["notes"].append(f"FAIL expected >= {sc['min_approvals']} approval request(s)")
    ev = metrics.event_metrics(out["run_dir"])
    return {"scenario": sc["id"], "run": i, "outcome": out["outcome"], "steps": out["steps"], "seconds": round(out["seconds"], 1),
            "cost_usd": round(out["cost_usd"], 4), "report": out["report_html"], **j, **ev}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    make_data.main()
    results = []
    for sc in load(a.only):
        for i in range(a.runs):
            r = run_one(sc, i)
            results.append(r)
            print(f"{sc['id']:<28} run {i}: {r['outcome']:<12} gt_success={r['gt_success']} passed={r['passed']} false_claim={r['false_claim']}")
            (HERE / "results.json").write_text(json.dumps({"runs": results, **metrics.aggregate(results)}, indent=1, default=str))
    agg = metrics.aggregate(results)
    c = Console()
    t = Table("scenario", "runs", "verified", "gt ok", "pass", "false claims", "interv.", "T3 w/o appr.", "steps", "s", "$")
    for k, v in agg["scenarios"].items():
        t.add_row(k, str(v["runs"]), str(v["verified_rate"]), str(v["gt_success_rate"]), str(v["pass_rate"]), str(v["false_claims"]),
                  str(v["interventions"]), str(v["t3_without_approval"]), str(v["steps"]), str(v["seconds"]), str(v["cost_usd"]))
    c.print(t)
    c.print(agg["overall"])


if __name__ == "__main__":
    main()
