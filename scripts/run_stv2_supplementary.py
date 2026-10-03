"""SESSION_TRADE_V2 — supplementary walk-forward + regime views (diagnostic).

These stages are SUPPLEMENTARY to the partition gates: the promotion gates are
DEV screen -> OOS (already frozen). They reuse EdgeLab's frozen verification
modules (``run_walk_forward``, ``evaluate_regimes``) and the campaign's single
``evaluate_window`` core, so their statistics cannot diverge from the
partition runs.

Walk-forward folds use an expanding NOMINAL train (the candidate is frozen —
no fitting ever occurs; the single frozen parameter point is used everywhere)
with non-overlapping forward test windows. The evaluator returns the frozen
DEV-survivor cells' closed-trade net R (gross R minus frozen friction).

The sealed holdout is never touched: all windows end before 2017-12-01
(``evaluate_window`` enforces this structurally).

Usage: python scripts/run_stv2_supplementary.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ag_edgelab.campaigns.session_trade_v2.campaign import evaluate_window  # noqa: E402
from ag_edgelab.verification.walk_forward import (  # noqa: E402
    ChronologicalFold,
    run_walk_forward,
)
from ag_edgelab.verification.walk_forward import RegimeSlice, evaluate_regimes  # noqa: E402

ARTIFACTS = REPO / "artifacts" / "session_trade_v2_economic_matrix"
UTC = timezone.utc

FOLDS = (
    ("WF1", "2017-01-01", "2017-04-01", "2017-04-01", "2017-06-01"),
    ("WF2", "2017-01-01", "2017-06-01", "2017-06-01", "2017-08-01"),
    ("WF3", "2017-01-01", "2017-08-01", "2017-08-01", "2017-10-01"),
    ("WF4", "2017-01-01", "2017-10-01", "2017-10-01", "2017-12-01"),
)

#: Walk-forward pass rule (stated here, applied mechanically): the pooled
#: fold expectancy must be positive AND a majority of folds positive.
WF_RULE = ("PASS iff pooled forward-test net expectancy > 0 and a majority of "
           "folds have net expectancy > 0")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def load_m15_cache():
    from ag_edgelab.contracts.market import MarketBar
    bars = {}
    for sym in ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD"):
        rows = []
        with open(REPO / ".campaign_cache" / "m15" / f"{sym}_M15_2017.csv") as fh:
            next(fh)
            for line in fh:
                ts, o, h, l, c = line.strip().split(",")
                rows.append(MarketBar(timestamp=datetime.fromisoformat(ts),
                                      open=float(o), high=float(h), low=float(l),
                                      close=float(c)))
        bars[sym] = tuple(rows)
    return bars


def gate_cells() -> tuple[tuple[str, str, str], ...]:
    dev = json.loads((ARTIFACTS / "dev_result.json").read_text())
    return tuple(
        (c["branch"], c["symbol"], c["session"])
        for c in dev["cells"] if c["status"] == "SURVIVES_DEV_SCREEN"
    )


def survivor_net_rs(bars, start: datetime, end: datetime, gate):
    """Frozen-survivor closed-trade net R inside [start, end)."""
    _, trades, friction = evaluate_window(start, end, bars)
    rs = []
    for t in trades:
        if (t.setup, t.instrument, t.session) in gate and t.closed:
            rs.append(t.gross_r - friction.get(t.trade_id, 0.0))
    return rs


def main() -> None:
    bars = load_m15_cache()
    gate = gate_cells()
    print(f"frozen DEV-survivor cells: {gate}")

    # ---- walk-forward (EdgeLab frozen module) ----
    folds = tuple(
        ChronologicalFold(fid, _dt(tr_s), _dt(tr_e), _dt(te_s), _dt(te_e))
        for fid, tr_s, tr_e, te_s, te_e in FOLDS
    )
    fold_results = run_walk_forward(
        folds,
        lambda fold: survivor_net_rs(bars, fold.test_start, fold.test_end, gate),
    )
    fold_rows = [
        {"fold_id": f.fold_id, "test_window": f"{f.test_start.date()}..{f.test_end.date()}",
         "trades": r.trades, "net_expectancy_r": r.expectancy_r,
         "net_profit_factor": r.profit_factor, "max_drawdown_r": r.max_drawdown_r}
        for f, r in zip(folds, fold_results)
    ]
    pooled = [r for row in fold_rows for r in []]  # placeholder, pooled below
    all_rs = []
    for f in folds:
        all_rs.extend(survivor_net_rs(bars, f.test_start, f.test_end, gate))
    pooled_exp = (sum(all_rs) / len(all_rs)) if all_rs else None
    positive_folds = sum(1 for r in fold_results if (r.expectancy_r or 0.0) > 0)
    wf_pass = (
        pooled_exp is not None and pooled_exp > 0
        and positive_folds * 2 > len(fold_results)
    )
    print("\nwalk-forward folds (frozen survivors, net R):")
    for row in fold_rows:
        print("  ", row)
    print(f"pooled forward-test expectancy: {pooled_exp}  -> walk_forward="
          f"{'PASS' if wf_pass else 'FAIL'}")

    # ---- regime slices (EdgeLab frozen module, descriptive) ----
    _, trades, friction = evaluate_window(
        datetime(2017, 1, 1, tzinfo=UTC), datetime(2017, 12, 1, tzinfo=UTC), bars
    )
    surv = [t for t in trades
            if (t.setup, t.instrument, t.session) in gate and t.closed]
    net = {t.trade_id: t.gross_r - friction.get(t.trade_id, 0.0) for t in surv}

    def slice_by(name, keyfn):
        groups: dict[str, list[float]] = {}
        for t in surv:
            groups.setdefault(keyfn(t), []).append(net[t.trade_id])
        return groups

    slices: dict[str, dict[str, list[float]]] = {
        "by_symbol": slice_by("symbol", lambda t: t.instrument),
        "by_direction": slice_by("direction", lambda t: t.direction),
    }
    # volatility terciles of the session reference range (A = 4 * risk R0)
    risks = sorted(t.risk_distance for t in surv if t.risk_distance)
    if len(risks) >= 3:
        q1, q2 = risks[len(risks) // 3], risks[2 * len(risks) // 3]

        def vol_bucket(t):
            if t.risk_distance is None:
                return "UNKNOWN"
            return "LOW" if t.risk_distance <= q1 else ("MID" if t.risk_distance <= q2 else "HIGH")
        slices["by_reference_volatility_tercile"] = slice_by("vol", vol_bucket)
    slices["by_quarter"] = slice_by(
        "quarter",
        lambda t: f"Q{(datetime.fromisoformat(t.trading_date).month - 1) // 3 + 1}",
    )

    regime_out = {}
    print("\nregime slices (frozen survivors, net R):")
    for group, buckets in slices.items():
        regime_out[group] = {}
        results = evaluate_regimes(
            tuple(RegimeSlice(f"{group}:{name}", tuple(rs))
                  for name, rs in sorted(buckets.items()))
        )
        for name, perf in results:
            regime_out[group][name] = {
                "trades": perf.trades,
                "net_r": round(perf.total_r, 4),
                "net_expectancy_r": None if perf.expectancy_r is None
                else round(perf.expectancy_r, 4),
                "net_profit_factor": None if perf.profit_factor is None
                else round(perf.profit_factor, 4),
                "max_drawdown_r": round(perf.max_drawdown_r, 4),
            }
            print(f"  {name}: {regime_out[group][name]}")

    detail = {
        "walk_forward_rule": WF_RULE,
        "walk_forward_pass": wf_pass,
        "pooled_forward_expectancy_r": None if pooled_exp is None else round(pooled_exp, 4),
        "positive_folds": f"{positive_folds}/{len(fold_results)}",
        "folds": fold_rows,
        "regime_slices": regime_out,
        "regime_note": (
            "Descriptive only: EdgeLab's canonical policy defines no regime "
            "gate thresholds; slices expose where the pooled survivor edge "
            "concentrates. No promotion decision is taken from this table."
        ),
    }
    (ARTIFACTS / "supplementary_detail.json").write_text(json.dumps(detail, indent=2))
    (ARTIFACTS / "supplementary.json").write_text(json.dumps({
        "walk_forward": "PASS" if wf_pass else "FAIL",
        "regime": "REPORTED",
    }, indent=2))
    print("\nsupplementary written:",
          ARTIFACTS / "supplementary.json",
          ARTIFACTS / "supplementary_detail.json")


if __name__ == "__main__":
    main()
