from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

from ag_edgelab.statistics.performance import compute_performance


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--expected-report", required=True)
    ap.add_argument("--out", default="artifacts/fx_ssc_gen001_verification.json")
    args=ap.parse_args()

    with open(args.ledger, newline="", encoding="utf-8") as fh:
        rows=[r for r in csv.DictReader(fh) if r["policy"]=="CONTROL"]
    net=[float(r["net_R"]) for r in rows]
    gross=sum(float(r["gross_R"]) for r in rows)
    friction=sum(float(r["friction_R"]) for r in rows)
    metrics=compute_performance(net)

    expected=json.loads(Path(args.expected_report).read_text(encoding="utf-8"))
    control=next(x for x in expected["policy_metrics"] if x["policy"]=="CONTROL")
    parity=expected["parity"]

    checks={
        "trade_count": metrics.trades == control["trade_count"] == parity["canonical_trade_count"],
        "net_r": abs(metrics.total_r-control["net_R"]) < 1e-12,
        "gross_r": abs(gross-control["gross_R"]) < 1e-12,
        "friction_r": abs(friction-control["friction_R"]) < 1e-12,
        "expectancy_r": abs((metrics.expectancy_r or 0)-control["average_R"]) < 1e-12,
        "profit_factor": abs((metrics.profit_factor or 0)-control["profit_factor"]) < 1e-12,
        "max_drawdown_r": abs(metrics.max_drawdown_r-control["max_drawdown_R"]) < 1e-12,
        "population_hash_match": parity["population_hash_match"] is True,
        "dataset_hash_match": parity["dataset_hash_match"] is True,
        "control_parity": parity["CONTROL_PARITY"] == "PASS",
    }
    verdict="NO_EDGE" if all(checks.values()) and (metrics.expectancy_r or 0) <= 0 else (
        "EDGE_SUPPORTED" if all(checks.values()) else "INTEGRITY_FAIL"
    )
    payload={
        "strategy_id":"ST_SESSION_SWEEP_CONTINUATION_V1",
        "strategy_version":"1.0.1",
        "instrument":"EURUSD",
        "experiment":"GEN_001",
        "verification_method":"EdgeLab independent recomputation from donor per-trade CONTROL ledger",
        "checks":checks,
        "metrics":asdict(metrics),
        "gross_r":gross,
        "friction_r":friction,
        "verdict":verdict,
    }
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(payload,indent=2,sort_keys=True))
    if verdict=="INTEGRITY_FAIL":
        raise SystemExit(2)


if __name__=="__main__":
    main()
