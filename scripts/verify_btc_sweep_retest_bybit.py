from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import requests
import types

# The donor strategy imports mt5.symbol_resolver for the SymbolMeta dataclass.
# This verification never calls MT5; provide a module shell so the Windows-only
# package is not required on the Linux research runner.
if "MetaTrader5" not in sys.modules:
    mt5_stub = types.ModuleType("MetaTrader5")
    # Import-time constants only. The verifier never calls any MT5 function.
    for _name, _value in {
        "TIMEFRAME_M1": 1,
        "TIMEFRAME_M5": 5,
        "TIMEFRAME_M15": 15,
        "TIMEFRAME_M30": 30,
        "TIMEFRAME_H1": 60,
        "TIMEFRAME_H4": 240,
        "TIMEFRAME_D1": 1440,
        "TIMEFRAME_W1": 10080,
    }.items():
        setattr(mt5_stub, _name, _value)
    sys.modules["MetaTrader5"] = mt5_stub

ROOT = Path(__file__).resolve().parents[1]
DONOR = Path(os.environ.get("AG_DONOR_REPO", ROOT.parent / "AG-profit-trading-assit")).resolve()
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(DONOR / "src"))

from ag_edgelab.contracts.intent import OrderIntent, OrderType, Side, Target
from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.contracts.trade import ExecutionStatus
from ag_edgelab.engines.reference.replay import ReferenceReplayEngine
from ag_edgelab.statistics.bootstrap import bootstrap_expectancy_ci
from ag_edgelab.statistics.performance import compute_performance

from btc_sweep_research.pipeline import run_research_cycle
from execution_runtime.bybit_linear_perp_feed import default_symbol_meta, to_symbol_meta
from strategy_engine.session import Candle

API = "https://api.bybit.com"
SYMBOL = "BTCUSDT"
CATEGORY = "linear"
TAKER_FEE_RATE = 0.00055
SLIPPAGE_TICKS_PER_LEG = 2.0
TICK_SIZE = 0.1


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def fetch_klines(interval: str, start: datetime, end: datetime) -> list[Candle]:
    out: dict[int, Candle] = {}
    cursor_end = ms(end)
    start_ms = ms(start)
    while cursor_end >= start_ms:
        resp = requests.get(
            f"{API}/v5/market/kline",
            params={"category": CATEGORY, "symbol": SYMBOL, "interval": interval,
                    "start": start_ms, "end": cursor_end, "limit": 1000},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("retCode") != 0:
            raise RuntimeError(f"Bybit kline error: {payload}")
        rows = payload.get("result", {}).get("list", [])
        if not rows:
            break
        oldest = None
        for row in rows:
            ts = int(row[0])
            if ts < start_ms or ts > ms(end):
                continue
            out[ts] = Candle(
                time=datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                open=float(row[1]), high=float(row[2]), low=float(row[3]), close=float(row[4]),
                volume=float(row[5]),
            )
            oldest = ts if oldest is None else min(oldest, ts)
        if oldest is None or oldest <= start_ms:
            break
        cursor_end = oldest - 1
    return [out[k] for k in sorted(out)]


def fetch_funding(start: datetime, end: datetime) -> list[tuple[datetime, float]]:
    resp = requests.get(
        f"{API}/v5/market/funding/history",
        params={"category": CATEGORY, "symbol": SYMBOL, "startTime": ms(start),
                "endTime": ms(end), "limit": 200},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("retCode") != 0:
        raise RuntimeError(f"Bybit funding error: {payload}")
    rows = []
    for item in payload.get("result", {}).get("list", []):
        rows.append((
            datetime.fromtimestamp(int(item["fundingRateTimestamp"]) / 1000, tz=timezone.utc),
            float(item["fundingRate"]),
        ))
    return sorted(rows)


class HistoricalFeed:
    def __init__(self, h1: list[Candle], m5: list[Candle]) -> None:
        self.h1 = h1
        self.m5 = m5
        self.now: datetime | None = None

    def get_latest_candles(self, symbol: str, timeframe: str, count: int):
        if symbol != SYMBOL or self.now is None:
            raise ValueError("historical feed identity/time not configured")
        source = self.h1 if timeframe == "H1" else self.m5 if timeframe == "M5" else None
        if source is None:
            raise ValueError(f"unsupported timeframe {timeframe}")
        rows = [c for c in source if c.time <= self.now]
        return rows[-count:]


class NullLedger:
    def record(self, proposal) -> bool:
        return True


def retest_time(state, m5: list[Candle]) -> datetime | None:
    if state.mss_time is None or state.entry is None:
        return None
    rows = [c for c in m5 if c.time > state.mss_time][:3]
    for candle in rows:
        touched = candle.low <= state.entry if state.direction == "LONG" else candle.high >= state.entry
        if touched:
            return candle.time
    return None


def funding_cost_r(entry_time: datetime, exit_time: datetime, side: str, notional: float,
                   risk_amount: float, funding: list[tuple[datetime, float]]) -> float:
    if risk_amount <= 0:
        return 0.0
    cost = 0.0
    for ts, rate in funding:
        if entry_time < ts <= exit_time:
            # Conservative validation: count absolute funding magnitude as cost,
            # never as a benefit, so favorable funding cannot manufacture an edge.
            cost += abs(rate) * notional
    return cost / risk_amount


def friction_r(entry_price: float, volume: float, risk_amount: float) -> float:
    if risk_amount <= 0:
        return 0.0
    fee = (entry_price * volume * 2.0) * TAKER_FEE_RATE
    slippage = (SLIPPAGE_TICKS_PER_LEG * TICK_SIZE * volume) * 2.0
    return (fee + slippage) / risk_amount


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-09-01")
    ap.add_argument("--end", default="2026-09-25")
    ap.add_argument("--data-end", default="2026-10-01")
    ap.add_argument("--out", default="artifacts/crypto_btc_verification.json")
    args = ap.parse_args()
    out_path = Path(args.out).resolve()

    # Donor strategy/config loaders intentionally use repository-relative paths.
    os.chdir(DONOR)

    start_day = date.fromisoformat(args.start)
    end_day = date.fromisoformat(args.end)
    data_end_day = date.fromisoformat(args.data_end)
    acquisition_start = datetime.combine(start_day - timedelta(days=10), time.min, tzinfo=timezone.utc)
    acquisition_end = datetime.combine(data_end_day, time.min, tzinfo=timezone.utc)

    h1 = fetch_klines("60", acquisition_start, acquisition_end)
    m5 = fetch_klines("5", acquisition_start, acquisition_end)
    funding = fetch_funding(acquisition_start, acquisition_end)
    if not h1 or not m5:
        raise RuntimeError("empty Bybit historical dataset")

    feed = HistoricalFeed(h1, m5)
    meta = to_symbol_meta(default_symbol_meta())
    rows = []
    day = start_day
    while day <= end_day:
        now = datetime.combine(day, time(16, 5), tzinfo=timezone.utc)
        feed.now = now
        report = run_research_cycle(
            feed,
            now=now,
            ledger=NullLedger(),
            exchange_id="BYBIT_LINEAR_PERP",
            symbol_meta=meta,
            symbol=SYMBOL,
        )
        for occurrence in report.qualified_occurrences:
            state = occurrence.setup_state
            entry_time = retest_time(state, m5)
            if entry_time is None or None in (state.entry, state.stop_loss, state.tp1, state.tp2, state.volume, state.risk_amount):
                rows.append({"setup_id": state.setup_id, "status": "INVALID_EVIDENCE", "reason": "missing entry/geometry"})
                continue
            bars = tuple(
                MarketBar(timestamp=c.time, open=c.open, high=c.high, low=c.low, close=c.close, volume=c.volume)
                for c in m5 if c.time >= entry_time
            )
            intent = OrderIntent(
                candidate_id=state.setup_id,
                instrument=SYMBOL,
                created_at=entry_time,
                side=Side(state.direction),
                order_type=OrderType.LIMIT,
                entry_price=state.entry,
                stop_price=state.stop_loss,
                targets=(
                    Target(price=state.tp1, allocation=0.5, move_stop_to_entry=True),
                    Target(price=state.tp2, allocation=0.5),
                ),
            )
            result = ReferenceReplayEngine({SYMBOL: bars}).execute_one(intent)
            if result.status != ExecutionStatus.CLOSED or result.entry_time is None or result.exit_time is None:
                rows.append({
                    "setup_id": state.setup_id,
                    "status": result.status.value,
                    "gross_r": result.gross_r,
                    "entry_time": str(result.entry_time),
                    "exit_time": str(result.exit_time),
                })
                continue
            base_cost_r = friction_r(state.entry, state.volume, state.risk_amount)
            funding_r = funding_cost_r(
                result.entry_time, result.exit_time, state.direction,
                state.entry * state.volume, state.risk_amount, funding,
            )
            net_r = float(result.gross_r or 0.0) - base_cost_r - funding_r
            rows.append({
                "setup_id": state.setup_id,
                "status": "CLOSED",
                "direction": state.direction,
                "entry_time": result.entry_time.isoformat(),
                "exit_time": result.exit_time.isoformat(),
                "gross_r": result.gross_r,
                "base_friction_r": base_cost_r,
                "funding_r_conservative": funding_r,
                "net_r": net_r,
            })
        day += timedelta(days=1)

    closed = [r["net_r"] for r in rows if r.get("status") == "CLOSED"]
    unresolved = [r for r in rows if r.get("status") not in {"CLOSED"}]
    metrics = compute_performance(closed)
    ci = bootstrap_expectancy_ci(closed, samples=5000, seed=42) if closed else None

    if len(closed) < 30 or unresolved:
        verdict = "INSUFFICIENT_EVIDENCE"
    elif metrics.expectancy_r is not None and metrics.expectancy_r <= 0:
        verdict = "NO_EDGE"
    elif ci is not None and ci.low is not None and ci.low > 0:
        verdict = "EDGE_CANDIDATE_POST_REGISTRATION"
    else:
        verdict = "INSUFFICIENT_EVIDENCE"

    payload = {
        "strategy_id": "ST_LIQUIDITY_SWEEP_RETEST_V1",
        "strategy_version": "2.0.0",
        "instrument": SYMBOL,
        "source": "BYBIT_PUBLIC_V5",
        "evaluation_window": {"start": args.start, "end": args.end, "data_end": args.data_end},
        "cost_model": {
            "taker_fee_rate": TAKER_FEE_RATE,
            "slippage_ticks_per_leg": SLIPPAGE_TICKS_PER_LEG,
            "funding": "historical Bybit public rates; absolute magnitude charged conservatively",
        },
        "closed_trades": len(closed),
        "unresolved_or_invalid": len(unresolved),
        "metrics": asdict(metrics),
        "bootstrap_expectancy_ci95": None if ci is None else asdict(ci),
        "verdict": verdict,
        "rows": rows,
        "notes": [
            "Research-only; no authenticated/private/order endpoints.",
            "Positive result is only an edge candidate until contamination/OOS review passes.",
            "No strategy parameters are changed after observing this run.",
        ],
    }
    out = out_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("closed_trades", "unresolved_or_invalid", "verdict")}, indent=2))


if __name__ == "__main__":
    main()
