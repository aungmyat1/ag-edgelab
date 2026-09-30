from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ag_edgelab.contracts.intent import OrderIntent, OrderType, Side, Target
from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.contracts.trade import ExecutionStatus
from ag_edgelab.engines.reference.replay import ReferenceReplayEngine
from ag_edgelab.statistics.performance import compute_performance

POINT = 0.00001
COMMISSION_POINTS_ROUND_TRIP = 6.0
SLIPPAGE_POINTS_ROUND_TRIP = 2.0


def parse_time(raw: str) -> datetime:
    return datetime.fromisoformat(raw.strip()).replace(tzinfo=timezone.utc)


def load_csv(path: str) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append({
                "time": parse_time(r["timestamp_utc"]),
                "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]),
                "close": float(r["close"]), "spread": float(r.get("spread") or 0.0),
                "volume": float(r.get("tick_volume") or 0.0),
            })
    return rows


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    alpha = 2.0 / (period + 1.0)
    current = None
    for i, value in enumerate(values):
        current = value if current is None else alpha * value + (1.0 - alpha) * current
        out.append(current if i + 1 >= period else None)
    return out


def atr(rows: list[dict], period: int = 14) -> list[float | None]:
    tr = []
    for i, row in enumerate(rows):
        prev_close = rows[i - 1]["close"] if i else row["close"]
        tr.append(max(row["high"] - row["low"], abs(row["high"] - prev_close), abs(row["low"] - prev_close)))
    out = []
    rolling = 0.0
    for i, value in enumerate(tr):
        rolling += value
        if i >= period:
            rolling -= tr[i - period]
        out.append(rolling / period if i + 1 >= period else None)
    return out


def latest_closed_h1_index(h1: list[dict], at: datetime, cursor: int) -> int:
    while cursor + 1 < len(h1) and h1[cursor + 1]["time"] + timedelta(hours=1) <= at:
        cursor += 1
    return cursor


def evaluate(h1: list[dict], m15: list[dict], *, atr_mult: float, rr: float, body_atr_min: float,
             session_start: int, session_end: int) -> dict:
    h1_fast = ema([r["close"] for r in h1], 20)
    h1_slow = ema([r["close"] for r in h1], 50)
    m15_fast = ema([r["close"] for r in m15], 20)
    m15_atr = atr(m15, 14)

    bars = tuple(MarketBar(
        timestamp=r["time"], open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r["volume"]
    ) for r in m15)
    engine = ReferenceReplayEngine({"EURUSD": bars})

    trade_rs: list[float] = []
    trades = []
    h1_cursor = -1
    blocked_until: datetime | None = None

    for i in range(1, len(m15) - 1):
        row = m15[i]
        if blocked_until is not None and row["time"] <= blocked_until:
            continue
        if not (session_start <= row["time"].hour < session_end):
            continue
        if m15_fast[i] is None or m15_fast[i - 1] is None or m15_atr[i] is None:
            continue

        h1_cursor = latest_closed_h1_index(h1, row["time"], h1_cursor)
        if h1_cursor < 49 or h1_fast[h1_cursor] is None or h1_slow[h1_cursor] is None:
            continue

        if h1_fast[h1_cursor] > h1_slow[h1_cursor]:
            side = Side.LONG
            crossed = m15[i - 1]["close"] <= m15_fast[i - 1] and row["close"] > m15_fast[i]
            body_ok = (row["close"] - row["open"]) >= body_atr_min * m15_atr[i]
        elif h1_fast[h1_cursor] < h1_slow[h1_cursor]:
            side = Side.SHORT
            crossed = m15[i - 1]["close"] >= m15_fast[i - 1] and row["close"] < m15_fast[i]
            body_ok = (row["open"] - row["close"]) >= body_atr_min * m15_atr[i]
        else:
            continue
        if not crossed or not body_ok:
            continue

        entry_row = m15[i + 1]
        entry = entry_row["open"]
        risk = atr_mult * m15_atr[i]
        if risk <= 0:
            continue
        stop = entry - risk if side == Side.LONG else entry + risk
        target = entry + rr * risk if side == Side.LONG else entry - rr * risk
        intent = OrderIntent(
            candidate_id=f"FX-{i}", instrument="EURUSD", created_at=entry_row["time"], side=side,
            order_type=OrderType.MARKET, entry_price=entry, stop_price=stop,
            targets=(Target(price=target, allocation=1.0),),
        )
        result = engine.execute_one(intent)
        if result.status != ExecutionStatus.CLOSED or result.exit_time is None or result.gross_r is None:
            continue

        friction_points = entry_row["spread"] + COMMISSION_POINTS_ROUND_TRIP + SLIPPAGE_POINTS_ROUND_TRIP
        friction_r = (friction_points * POINT) / risk
        net_r = result.gross_r - friction_r
        trade_rs.append(net_r)
        trades.append({
            "signal_time": row["time"].isoformat(), "entry_time": entry_row["time"].isoformat(),
            "exit_time": result.exit_time.isoformat(), "side": side.value, "gross_r": result.gross_r,
            "friction_r": friction_r, "net_r": net_r, "spread_points": entry_row["spread"],
        })
        blocked_until = result.exit_time

    metrics = compute_performance(trade_rs)
    return {"metrics": asdict(metrics), "trades": trades}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--h1", required=True)
    ap.add_argument("--m15", required=True)
    ap.add_argument("--out", default="artifacts/fx_dev_screen.json")
    args = ap.parse_args()

    h1, m15 = load_csv(args.h1), load_csv(args.m15)
    grid = []
    for atr_mult in (1.0, 1.5, 2.0):
        for rr in (1.5, 2.0, 2.5):
            for body_atr_min in (0.0, 0.2, 0.4):
                result = evaluate(
                    h1, m15, atr_mult=atr_mult, rr=rr, body_atr_min=body_atr_min,
                    session_start=6, session_end=16,
                )
                m = result["metrics"]
                qualifies = (
                    m["trades"] >= 30 and
                    m["expectancy_r"] is not None and m["expectancy_r"] > 0 and
                    m["profit_factor"] is not None and m["profit_factor"] > 1.0
                )
                grid.append({
                    "parameters": {"atr_mult": atr_mult, "rr": rr, "body_atr_min": body_atr_min,
                                   "session_start": 6, "session_end": 16},
                    "metrics": m, "qualifies_development_floor": qualifies,
                    "trades": result["trades"],
                })

    # Selection is deterministic and development-only: highest expectancy among
    # candidates that clear N/PF/expectancy floors; ties prefer simpler/lower RR.
    eligible = [x for x in grid if x["qualifies_development_floor"]]
    eligible.sort(key=lambda x: (
        -(x["metrics"]["expectancy_r"] or -999),
        -(x["metrics"]["profit_factor"] or -999),
        x["parameters"]["body_atr_min"],
        x["parameters"]["atr_mult"],
        x["parameters"]["rr"],
    ))
    selected = eligible[0] if eligible else None

    payload = {
        "strategy_id": "FX_TREND_PULLBACK_FUNNEL_V1",
        "dataset_role": "DEVELOPMENT_CONSUMED",
        "search_space_frozen": {
            "atr_mult": [1.0, 1.5, 2.0],
            "rr": [1.5, 2.0, 2.5],
            "body_atr_min": [0.0, 0.2, 0.4],
            "session": [6, 16],
            "h1_ema": [20, 50],
            "m15_ema": 20,
            "atr_period": 14,
        },
        "friction": {
            "recorded_entry_spread": True,
            "commission_points_round_trip": COMMISSION_POINTS_ROUND_TRIP,
            "slippage_points_round_trip": SLIPPAGE_POINTS_ROUND_TRIP,
        },
        "candidate_count": len(grid),
        "selected_candidate": selected,
        "oos_accessed": False,
        "all_candidates": [
            {"parameters": x["parameters"], "metrics": x["metrics"],
             "qualifies_development_floor": x["qualifies_development_floor"]}
            for x in grid
        ],
    }
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "candidate_count": len(grid),
        "eligible_count": len(eligible),
        "selected": None if selected is None else {
            "parameters": selected["parameters"], "metrics": selected["metrics"]
        },
        "oos_accessed": False,
    }, indent=2))


if __name__ == "__main__":
    main()
