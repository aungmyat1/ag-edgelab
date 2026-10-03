"""ST_CRYPTO_MTF_SMC_V1 — ONE baseline dev run on the synthetic BTCUSDT fixture.

This is a STRUCTURAL_GROSS_REPLAY on SYNTHETIC data (provider=SYNTHETIC_FIXTURE,
dataset_is_authoritative=false). It is a machinery/ plumbing proof only:
NO grid search, NO parameter optimization, NO optimization-tuned inputs, and
absolutely NOT an economic backtest. Because the dataset is synthetic and the
funding schedule is synthetic (not BYBIT_PUBLIC_HISTORY), the run's net
qualification is NOT_ECONOMICALLY_QUALIFIED by construction; NET_R is not
reported as a number with any economic claim.

REPRODUCTION:
    PYTHONPATH=src .venv/bin/python scripts/make_synthetic_btcusdt_fixture.py
    PYTHONPATH=src .venv/bin/python scripts/run_st_crypto_mtf_smc_dev.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from ag_edgelab.contracts.instrument import InstrumentType
from ag_edgelab.contracts.trade import ExecutionStatus
from ag_edgelab.data.bars import read_bars_csv
from ag_edgelab.data.derive import aggregate_bars, TIMEFRAME_MINUTES
from ag_edgelab.data.quality import audit_bars
from ag_edgelab.engines.reference.replay import ReferenceReplayEngine
from ag_edgelab.friction.model import (
    FundingAuthority,
    FundingEvent,
    FundingSchedule,
    NetEconomicQualification,
    assess_net_economic_qualification,
    funding_cost_r,
)
from ag_edgelab.strategies.crypto_mtf_smc import MtfSmcScanner

SCRIPT_NAME = "run_st_crypto_mtf_smc_dev.py"

# One baseline execution-friction scenario (unit-R), matching the repo's BASE
# convention used by the funding/friction tests. Funding is NOT folded in here;
# it is accrued per trade from the declared funding schedule instead.
SPREAD_R = 0.05
COMMISSION_R = 0.02
SLIPPAGE_R = 0.01
EXECUTION_FRICTION_R = SPREAD_R + COMMISSION_R + SLIPPAGE_R


def read_funding_schedule(path: Path) -> FundingSchedule:
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    events = []
    for row in csv.DictReader(data.decode("utf-8").splitlines()):
        ts_raw = row["timestamp"].strip()
        ts = datetime.fromisoformat(ts_raw)
        events.append(FundingEvent(timestamp=ts, rate=float(row["funding_rate"])))
    events.sort(key=lambda e: e.timestamp)
    return FundingSchedule(
        authority=FundingAuthority.SYNTHETIC_FIXTURE,
        events=tuple(events),
        source="BTCUSDT_FUNDING_SYNTHETIC.csv (deterministic synthetic companion; NOT real funding)",
        source_sha256=sha,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Single baseline dev run of ST_CRYPTO_MTF_SMC_V1 on the synthetic fixture.")
    parser.add_argument("--bars", type=Path, default=Path("data/artifacts/synthetic_btcusdt/BTCUSDT_M5_SYNTHETIC.csv"))
    parser.add_argument("--funding", type=Path, default=Path("data/artifacts/synthetic_btcusdt/BTCUSDT_FUNDING_SYNTHETIC.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports/st_crypto_mtf_smc_v1_dev"))
    args = parser.parse_args()

    # ---- dataset identity + quality gate (fixture; no real-market authority)
    bars, bars_sha = read_bars_csv(str(args.bars))
    if not bars:
        print("ERROR: no bars loaded", file=sys.stderr)
        return 2
    quality = audit_bars(bars, "M5", symbol="BTCUSDT", venue="SYNTHETIC_FIXTURE",
                         expected_start=bars[0].timestamp,
                         expected_end=bars[-1].timestamp)

    # ---- deterministic higher-timeframe derivation with lineage
    from ag_edgelab.data.derive import derive_timeframe

    frames = {}
    lineage = {}
    for tf in ("M15", "H1", "H4", "D1"):
        derived, lin, bucket_audit = derive_timeframe(bars, "M5", tf, bars_sha)
        frames[tf] = derived
        lineage[tf] = (lin, bucket_audit)

    # ---- strategy scan (baseline parameters; no tuning input accepted)
    scanner = MtfSmcScanner(bars, frames)
    intents, candidates, rejection_tally = scanner.scan()

    # ---- conservative OHLC replay (same-bar stop-wins policy)
    engine = ReferenceReplayEngine({"BTCUSDT": bars})
    results = engine.execute(intents)
    closed = [r for r in results if r.status == ExecutionStatus.CLOSED]
    non_closed = [r for r in results if r.status != ExecutionStatus.CLOSED]

    # ---- synthetic funding accrual (NOT authoritative)
    schedule = read_funding_schedule(args.funding)
    trade_rows = []
    funding_rs = []
    intent_by_id = {i.candidate_id: i for i in intents}
    for r in closed:
        side = r.side.value
        entry_idx = intent_by_id[r.candidate_id]
        f_r = funding_cost_r(
            entry_time=r.entry_time, exit_time=r.exit_time, side=side,
            entry_price=r.entry_price, stop_price=entry_idx.stop_price,
            schedule=schedule,
        )
        funding_rs.append(f_r)
        risk = abs(r.entry_price - entry_idx.stop_price)
        trade_rows.append({
            "candidate_id": r.candidate_id,
            "side": side,
            "entry_time": r.entry_time.isoformat(),
            "entry_price": r.entry_price,
            "stop_price": entry_idx.stop_price,
            "target_price": entry_idx.targets[0].price,
            "exit_time": r.exit_time.isoformat(),
            "exit_price": r.exit_price,
            "exit_reason": r.exit_reason.value,
            "risk": risk,
            "gross_r": r.gross_r,
            "execution_friction_r": EXECUTION_FRICTION_R,
            "funding_r": f_r,
            "friction_plus_funding_r": EXECUTION_FRICTION_R + f_r,
            "structural_net_r_if_qualification_were_available": r.gross_r - EXECUTION_FRICTION_R - f_r,
        })

    gross_rs = [r.gross_r for r in closed]
    net_rs_structural = [t["structural_net_r_if_qualification_were_available"] for t in trade_rows]

    # ---- net economic qualification gate (cannot pass: synthetic data + synthetic funding)
    instrument_is_perpetual = True  # InstrumentType.LINEAR_PERPETUAL target domain
    assert InstrumentType.LINEAR_PERPETUAL.value == "LINEAR_PERPETUAL"
    qualification = assess_net_economic_qualification(
        instrument_is_perpetual=instrument_is_perpetual,
        funding_authority=schedule.authority,
        dataset_is_authoritative=False,
    )
    assert qualification == NetEconomicQualification.NOT_ECONOMICALLY_QUALIFIED

    # ---- metrics
    trade_count = len(closed)
    longs = sum(1 for r in closed if r.side.value == "LONG")
    shorts = trade_count - longs
    wins = [g for g in gross_rs if g > 0]
    losses = [g for g in gross_rs if g < 0]
    breakeven = [g for g in gross_rs if g == 0]
    gross_total = sum(gross_rs)
    pf_denom = abs(sum(losses))
    profit_factor_gross = (sum(wins) / pf_denom) if pf_denom else (float("inf") if wins else None)
    # running max drawdown in R over closed-trade equity curve (chronological)
    chrono = sorted(zip((r.exit_time for r in closed), net_rs_structural), key=lambda z: z[0])
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for _, nn in chrono:
        equity += nn
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    top_rejections = Counter(rejection_tally).most_common(12)

    metrics = {
        "RUN_KIND": "STRUCTURAL_GROSS_REPLAY",
        "DATASET_AUTHORITY": "SYNTHETIC_FIXTURE (no real-market authority, never evidence for BTCUSDT perp economics)",
        "TRADE_COUNT": trade_count,
        "LONGS": longs,
        "SHORTS": shorts,
        "WINS": len(wins),
        "LOSSES": len(losses),
        "BREAKEVEN": len(breakeven),
        "NON_CLOSED_INTENTS_OPEN_OR_UNFILLED": len(non_closed),
        "WIN_RATE": (len(wins) / trade_count) if trade_count else None,
        "GROSS_R": gross_total,
        "FRICTION_R": EXECUTION_FRICTION_R * trade_count,
        "FUNDING_R": sum(funding_rs),
        "NET_R": "NOT_ECONOMICALLY_QUALIFIED",
        "EXPECTANCY_GROSS_R": (gross_total / trade_count) if trade_count else None,
        "EXPECTANCY_NET_R": "NOT_ECONOMICALLY_QUALIFIED",
        "PROFIT_FACTOR_NET": "NOT_ECONOMICALLY_QUALIFIED",
        "PROFIT_FACTOR_GROSS": profit_factor_gross,
        "MAX_DRAWDOWN_R": max_dd,
        "AVG_WIN_R": (sum(wins) / len(wins)) if wins else None,
        "AVG_LOSS_R": (sum(losses) / len(losses)) if losses else None,
        "TOP_REJECTION_REASONS": top_rejections,
        "NET_ECONOMIC_QUALIFICATION": qualification.value,
        "STRUCTURAL_ONLY_NET_R_REFERENCE": sum(net_rs_structural),
        "CANDIDATE_COUNT": len(candidates),
        "INTENT_COUNT": len(intents),
    }

    # ---- artifacts
    args.out_dir.mkdir(parents=True, exist_ok=True)
    ledger_json = {
        "run": {
            "script": SCRIPT_NAME,
            "run_kind": "STRUCTURAL_GROSS_REPLAY",
            "instrument_domain": "BTCUSDT_LINEAR_PERPETUAL (structural target; dataset is synthetic)",
            "dataset_is_authoritative": False,
            "m5_bars": len(bars),
            "m5_sha256": bars_sha,
            "m5_span": [bars[0].timestamp.isoformat(), bars[-1].timestamp.isoformat()],
            "funding_authority": schedule.authority.value,
            "funding_sha256": schedule.source_sha256,
            "funding_events": len(schedule.events),
            "derived_timeframes": {tf: {"bars": len(frames[tf]),
                                        "lineage_source_dataset_hash": line.source_dataset_hash,
                                        "lineage_output_hash": line.output_hash,
                                        "aggregation_rule": line.aggregation_rule,
                                        "timezone": line.timezone,
                                        "boundary_convention": line.boundary_convention,
                                        "rows": line.rows,
                                        "buckets_emitted": sum(1 for a in bucket_audit if a.complete),
                                        "buckets_dropped_incomplete": sum(1 for a in bucket_audit if not a.complete)}
                                   for tf, (line, bucket_audit) in lineage.items()},
            "data_quality": {"verdict": quality.verdict.value, "gap_audit": quality.gap_audit,
                             "rows": quality.rows, "expected_slots": quality.expected_slots,
                             "missing_slots": quality.missing_slots, "forward_filled": quality.forward_filled,
                             "issues": [{"code": i.code, "detail": i.detail} for i in quality.issues]},
            "execution_friction_r_per_trade": {"spread_r": SPREAD_R, "commission_r": COMMISSION_R,
                                               "slippage_r": SLIPPAGE_R, "total": EXECUTION_FRICTION_R},
            "metrics": metrics,
        },
        "trades": trade_rows,
        "candidates": [
            {
                "machine_id": c.machine_id, "direction": c.direction, "status": c.status,
                "rejection_code": c.rejection_code,
                "transitions": [{"stage_id": t.stage_id, "driving_bar_index": t.driving_bar_index,
                                 "observed_at": t.observed_at.isoformat()} for t in c.transitions],
            }
            for c in candidates
        ],
    }
    (args.out_dir / "ledger.json").write_text(json.dumps(ledger_json, indent=2, default=str))
    with (args.out_dir / "trades.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(trade_rows[0].keys()) if trade_rows else ["empty"])
        writer.writeheader()
        writer.writerows(trade_rows)

    # ---- console report (exact mission metric names)
    print(f"REPO RUN: {SCRIPT_NAME} — STRUCTURAL_GROSS_REPLAY on SYNTHETIC_FIXTURE (no economic claim)")
    print(f"dataset: {len(bars)} M5 bars sha256={bars_sha[:16]} span={bars[0].timestamp:%Y-%m-%d}..{bars[-1].timestamp:%Y-%m-%d}")
    print(f"quality: verdict={quality.verdict.value} gap_audit={quality.gap_audit} rows={quality.rows}/{quality.expected_slots}")
    for k in ("TRADE_COUNT", "LONGS", "SHORTS", "WINS", "LOSSES", "WIN_RATE", "GROSS_R", "FRICTION_R",
              "FUNDING_R", "NET_R",  "EXPECTANCY_GROSS_R", "EXPECTANCY_NET_R", "PROFIT_FACTOR_NET",
              "PROFIT_FACTOR_GROSS", "MAX_DRAWDOWN_R", "AVG_WIN_R", "AVG_LOSS_R",
              "NET_ECONOMIC_QUALIFICATION", "STRUCTURAL_ONLY_NET_R_REFERENCE"):
        v = metrics[k]
        print(f"  {k}: {round(v, 4) if isinstance(v, float) else v}")
    print(f"  TOP_REJECTION_REASONS: {top_rejections}")
    print(f"  CANDIDATES/INTENTS: {metrics['CANDIDATE_COUNT']}/{metrics['INTENT_COUNT']}")
    print(f"artifacts: {args.out_dir/'ledger.json'}, {args.out_dir/'trades.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
