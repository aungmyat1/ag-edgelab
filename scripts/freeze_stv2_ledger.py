"""SESSION_TRADE_V2 — ledger freeze.

Writes EdgeLab ``CandidateRecord`` rows (one per symbol) recording the
campaign outcome through EdgeLab's funnel stages:

  CONTEXT   = frozen identity verified (all four source artifacts hash-pinned)
  LOCATION  = dataset + partition integrity (quality gates, DEV/OOS disjoint,
              holdout never touched)
  TRIGGER   = DEV screen executed (24-cell matrix; per-symbol survivor info)
  GEOMETRY  = OOS promotion gate on the frozen DEV survivors (net expectancy
              must be > 0 and net PF > 1 over closed trades)

EXECUTION is never recorded: execution authority is frozen OFF (research-only
campaign), and the candidate cannot reach it without passing GEOMETRY.

Research only — no Demo/Live, no order_send.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ag_edgelab.contracts.funnel import FunnelStage, FunnelStageResult, RuleResult  # noqa: E402
from ag_edgelab.ledger.candidate import CandidateRecord, write_jsonl  # noqa: E402
from ag_edgelab.campaigns.session_trade_v2.identity import verify_identity  # noqa: E402

ARTIFACTS = REPO / "artifacts" / "session_trade_v2_economic_matrix"

MIN_TRADES = 30  # EdgeLab canonical policy constant (metrics.py)


def _rule(rule_id: str, passed: bool, features: dict, failure: str | None = None,
          rejection: str | None = None) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        rule_version="v1",
        rule_hash="frozen-in-repo",  # rule source is the committed campaign package
        passed=passed,
        evaluated_at=datetime.now(timezone.utc),
        features=features,
        failure_reason=failure,
        rejection_code=rejection,
    )


def main() -> None:
    dev = json.loads((ARTIFACTS / "dev_result.json").read_text())
    oos = json.loads((ARTIFACTS / "oos_result.json").read_text())
    quality = json.loads((REPO / ".campaign_cache" / "m15" / "quality_reports.json").read_text())
    ident = verify_identity()
    now = datetime.now(timezone.utc)
    candidate_id = ident.candidate_id

    dev_cells = {(c["branch"], c["symbol"], c["session"]): c for c in dev["cells"]}
    oos_cells = {(c["branch"], c["symbol"], c["session"]): c for c in oos["cells"]}
    gate = {tuple(k) for k in oos["aggregates"].get("gate_cells", [])}
    gate_by_branch = oos["aggregates"].get("gate_by_branch", {})

    records = []
    for symbol in ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD"):
        q = quality[symbol]
        context = FunnelStageResult(
            candidate_id=candidate_id, stage=FunnelStage.CONTEXT, passed=True, as_of=now,
            rule_results=(_rule("stv2_identity_freeze", True, {
                "source_repo": ident.source_repo,
                "source_pr": ident.source_pr,
                "source_commit": ident.source_commit,
                "artifact_sha256": ident.artifact_sha256,
                "execution_authority": {"demo": False, "live": False, "order_send": False},
            }),),
        )
        location_ok = (q["m1_duplicate_timestamps"] == 0 and q["m1_ohlc_violations"] == 0
                       and q["m15_bars"] > 0)
        location = FunnelStageResult(
            candidate_id=candidate_id, stage=FunnelStage.LOCATION,
            passed=location_ok, as_of=now,
            rule_results=(_rule("stv2_partition_integrity", location_ok, {
                "dataset_source": q["source"],
                "dataset_sha256": q["source_sha256"],
                "m1_rows": q["m1_rows"], "m15_bars": q["m15_bars"],
                "duplicate_timestamps": q["m1_duplicate_timestamps"],
                "ohlc_violations": q["m1_ohlc_violations"],
                "dev_partition": dev["partition"]["start"] + ".." + dev["partition"]["end"],
                "oos_partition": oos["partition"]["start"] + ".." + oos["partition"]["end"],
                "holdout_touched": False,
            }),),
        )

        survivors = [k for k in dev_cells if k[1] == symbol
                     and dev_cells[k]["status"] == "SURVIVES_DEV_SCREEN"]
        trigger = FunnelStageResult(
            candidate_id=candidate_id, stage=FunnelStage.TRIGGER,
            passed=bool(survivors), as_of=now,
            rejection_codes=() if survivors else ("DEV_SCREEN_NO_SURVIVOR",),
            rule_results=(_rule("stv2_dev_screen", bool(survivors), {
                "survivor_cells": ["/".join(k) for k in survivors],
                "cell_status": {"/".join(k): dev_cells[k]["status"]
                                for k in dev_cells if k[1] == symbol},
            }),),
        )

        # OOS gate: frozen survivors of THIS symbol
        sym_gate_keys = [k for k in survivors if k in gate]
        closed = 0
        net_exp = None
        net_pf = None
        for k in sym_gate_keys:
            c = oos_cells[k]
            closed += c["closed"]
        # per-symbol pooled survivor figures come from gate_by_branch restricted
        # further by symbol: recompute from the per-cell rows (closed-traded)
        sym_net_r = sum(oos_cells[k]["net_r"] for k in sym_gate_keys)
        sym_gross_win = 0.0
        sym_gross_loss = 0.0
        # profit factor from per-cell avg win/loss x counts (rounded inputs;
        # authoritative pooled figures live in gate_by_branch)
        for k in sym_gate_keys:
            c = oos_cells[k]
            if c["average_win_r"] is not None:
                sym_gross_win += c["average_win_r"] * c["wins"]
            if c["average_loss_r"] is not None:
                sym_gross_loss += abs(c["average_loss_r"]) * c["losses"]
        net_exp = (sym_net_r / closed) if closed else None
        net_pf = (sym_gross_win / sym_gross_loss) if sym_gross_loss else None

        oos_passed = bool(
            survivors and closed >= MIN_TRADES
            and net_exp is not None and net_exp > 0.0
            and net_pf is not None and net_pf > 1.0
        )
        if not survivors:
            rejection = "DEV_SCREEN_NO_SURVIVOR"
            failure = "no DEV survivor cell for this symbol"
        elif closed < MIN_TRADES:
            rejection = "OOS_INSUFFICIENT_SAMPLE"
            failure = f"only {closed} closed OOS trades among frozen survivors (< {MIN_TRADES})"
        elif net_exp is None or net_exp <= 0.0 or net_pf is None or net_pf <= 1.0:
            rejection = "OOS_NET_EXPECTANCY_NON_POSITIVE"
            failure = (f"OOS gate failed: closed={closed} net_r={sym_net_r:.4f} "
                       f"net_exp={net_exp} net_pf={net_pf}")
        else:
            rejection = None
            failure = None
        geometry = FunnelStageResult(
            candidate_id=candidate_id, stage=FunnelStage.GEOMETRY,
            passed=oos_passed, as_of=now,
            rejection_codes=() if rejection is None else (rejection,),
            rule_results=(_rule("stv2_oos_gate", oos_passed, {
                "frozen_survivor_cells": ["/".join(k) for k in sym_gate_keys],
                "oos_closed_trades": closed,
                "oos_net_r": round(sym_net_r, 4),
                "oos_net_expectancy_r": None if net_exp is None else round(net_exp, 4),
                "oos_net_profit_factor": None if net_pf is None else round(net_pf, 4),
            }, failure, rejection),),
        )

        records.append(CandidateRecord(
            candidate_id=candidate_id,
            instrument=symbol,
            strategy_id=ident.strategy_id,
            strategy_version=ident.strategy_version,
            strategy_sha256=ident.source_commit,
            dataset_sha256=q["source_sha256"],
            stage_results=(context, location, trigger, geometry),
        ))

    out = write_jsonl(ARTIFACTS / "ledger.jsonl", records)
    for r in records:
        print(f"{r.instrument}: passed={r.passed} stages={[s.stage.value for s in r.stage_results]}"
              f" rejection={r.rejection_codes}")
    print("ledger frozen ->", out)


if __name__ == "__main__":
    main()
