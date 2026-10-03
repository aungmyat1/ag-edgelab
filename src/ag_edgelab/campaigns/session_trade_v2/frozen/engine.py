from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from .models import Candle, Decision

STRATEGY_ID = "SESSION_TRADE_V2"
STRATEGY_VERSION = "2.0.0"
SUPPORTED_SYMBOLS = {"EURUSD", "GBPUSD", "USDJPY", "XAUUSD"}
SUPPORTED_CYCLES = {"ASIAN_LONDON", "LONDON_NEWYORK"}
R_FRACTION = 0.25


def _no_trade(symbol: str, cycle: str, reason: str, high: float, low: float, mid: float,
              ts: datetime | None = None) -> Decision:
    return Decision(STRATEGY_ID, STRATEGY_VERSION, symbol, cycle, "NO_TRADE", reason,
                    box_high=high, box_low=low, box_mid=mid, signal_timestamp=ts)


def _signal(symbol: str, cycle: str, setup: str, direction: str, order_type: str,
            entry: float, stop: float, high: float, low: float, mid: float,
            ts: datetime, management: str) -> Decision:
    risk = abs(entry - stop)
    if risk <= 0:
        return _no_trade(symbol, cycle, "INVALID_RISK_DISTANCE", high, low, mid, ts)
    sign = 1.0 if direction == "LONG" else -1.0
    return Decision(
        STRATEGY_ID, STRATEGY_VERSION, symbol, cycle, "SIGNAL", "READY",
        setup=setup, direction=direction, entry_order_type=order_type,
        entry=entry, stop_loss=stop, risk_distance=risk,
        target_4r=entry + sign * 4.0 * risk,
        target_5r=entry + sign * 5.0 * risk,
        box_high=high, box_low=low, box_mid=mid, signal_timestamp=ts,
        management=management,
    )


def evaluate(symbol: str, cycle: str, reference_candles: Sequence[Candle],
             trade_candles: Sequence[Candle]) -> Decision:
    """Evaluate closed M15 candles with priority A sweep -> B range rejection -> C expansion.

    The caller owns window slicing. This function is deliberately deterministic and
    side-effect free; it never reads MT5, sizes positions, or submits orders.
    """
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError(f"unsupported symbol: {symbol}")
    if cycle not in SUPPORTED_CYCLES:
        raise ValueError(f"unsupported cycle: {cycle}")
    if not reference_candles:
        raise ValueError("reference_candles must not be empty")
    if not trade_candles:
        high = max(c.high for c in reference_candles)
        low = min(c.low for c in reference_candles)
        return _no_trade(symbol, cycle, "NO_CLOSED_TRADE_CANDLES", high, low, (high + low) / 2.0)

    high = max(c.high for c in reference_candles)
    low = min(c.low for c in reference_candles)
    if high <= low:
        raise ValueError("reference range must be positive")
    mid = (high + low) / 2.0
    r0 = (high - low) * R_FRACTION

    # A — sweep + same-candle reclaim. First qualifying closed candle wins.
    for c in trade_candles:
        swept_high = c.high > high and c.close < high
        swept_low = c.low < low and c.close > low
        if swept_high and swept_low:
            return _no_trade(symbol, cycle, "AMBIGUOUS_DUAL_SIDE_SWEEP", high, low, mid, c.time)
        if swept_low:
            entry = c.close
            stop = entry - r0
            if stop >= c.low:
                return _no_trade(symbol, cycle, "SWEEP_STOP_DOES_NOT_PROTECT_EXTREME", high, low, mid, c.time)
            return _signal(symbol, cycle, "A_SWEEP_REENTRY", "LONG", "MARKET", entry, stop,
                           high, low, mid, c.time, "75% at 4R; move runner to breakeven; 25% to 5R")
        if swept_high:
            entry = c.close
            stop = entry + r0
            if stop <= c.high:
                return _no_trade(symbol, cycle, "SWEEP_STOP_DOES_NOT_PROTECT_EXTREME", high, low, mid, c.time)
            return _signal(symbol, cycle, "A_SWEEP_REENTRY", "SHORT", "MARKET", entry, stop,
                           high, low, mid, c.time, "75% at 4R; move runner to breakeven; 25% to 5R")

    # B — range boundary rejection without an outside close. A boundary-touching candle
    # that closes inward creates a boundary LIMIT entry; dual rejection is ambiguous.
    for c in trade_candles:
        low_reject = c.low <= low and low < c.close < high
        high_reject = c.high >= high and low < c.close < high
        if low_reject and high_reject:
            return _no_trade(symbol, cycle, "AMBIGUOUS_DUAL_BOUNDARY_REJECTION", high, low, mid, c.time)
        if low_reject:
            return _signal(symbol, cycle, "B_RANGE_REJECTION", "LONG", "LIMIT", low, low - r0,
                           high, low, mid, c.time, "75% at 4R; move runner to breakeven; 25% to 5R")
        if high_reject:
            return _signal(symbol, cycle, "B_RANGE_REJECTION", "SHORT", "LIMIT", high, high + r0,
                           high, low, mid, c.time, "75% at 4R; move runner to breakeven; 25% to 5R")

    # C — body close outside the box. Entry is a retrace limit at equilibrium.
    for c in trade_candles:
        if c.body_low > high and c.close > high:
            return _signal(symbol, cycle, "C_TREND_EXPANSION", "LONG", "LIMIT", mid, mid - r0,
                           high, low, mid, c.time, "75% at 4R; trail 25% behind confirmed M15 swings; 5R cap")
        if c.body_high < low and c.close < low:
            return _signal(symbol, cycle, "C_TREND_EXPANSION", "SHORT", "LIMIT", mid, mid + r0,
                           high, low, mid, c.time, "75% at 4R; trail 25% behind confirmed M15 swings; 5R cap")

    return _no_trade(symbol, cycle, "NO_QUALIFYING_SETUP", high, low, mid,
                     trade_candles[-1].time.astimezone(timezone.utc))
