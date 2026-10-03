from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Sequence

from .models import Candle, Decision
from .structure import (
    classify_false_shift,
    control_shift_zones,
    latest_fresh_zone,
    structural_target,
    structure_bias,
    validate_series,
    zone_touched,
    zones,
)

STRATEGY_ID = "ST_MTF_CONTROL_SHIFT_V1"
STRATEGY_VERSION = "1.0.0"
SUPPORTED_SYMBOLS = {"EURUSD", "GBPUSD", "USDJPY", "XAUUSD"}
SESSION_WINDOWS = {
    "ASIAN_LONDON": (time(6, 0), time(9, 0)),
    "LONDON_NEWYORK": (time(11, 0), time(14, 0)),
}
STOP_BUFFER_FRACTION = 0.10
H1_SHIFT_MAX_AGE_BARS = 4


def _decision(symbol: str, cycle: str, status: str, reason: str, **kwargs) -> Decision:
    return Decision(STRATEGY_ID, STRATEGY_VERSION, symbol, cycle, status, reason, **kwargs)


def _in_window(ts: datetime, cycle: str) -> bool:
    if ts.tzinfo is None:
        raise ValueError("candle timestamps must be timezone-aware")
    t = ts.astimezone(timezone.utc).time().replace(tzinfo=None)
    start, end = SESSION_WINDOWS[cycle]
    return start <= t < end


def _expiry(ts: datetime, cycle: str) -> datetime:
    _, end = SESSION_WINDOWS[cycle]
    utc = ts.astimezone(timezone.utc)
    return datetime.combine(utc.date(), end, tzinfo=timezone.utc)


def evaluate(
    symbol: str,
    cycle: str,
    d1: Sequence[Candle],
    h4: Sequence[Candle],
    h1: Sequence[Candle],
    m15: Sequence[Candle],
) -> Decision:
    """Evaluate one frozen MTF control-shift candidate using closed candles only.

    This function is side-effect free and has no broker/execution imports. Callers own
    candle acquisition and must pass only information available at the evaluation time.
    """
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError(f"unsupported symbol: {symbol}")
    if cycle not in SESSION_WINDOWS:
        raise ValueError(f"unsupported cycle: {cycle}")
    for series in (d1, h4, h1, m15):
        validate_series(series)
        if any(c.time.tzinfo is None for c in series):
            raise ValueError("all timestamps must be timezone-aware")

    d1_bias = structure_bias(d1)
    h4_bias = structure_bias(h4)
    if d1_bias == "NEUTRAL" or h4_bias == "NEUTRAL" or d1_bias != h4_bias:
        return _decision(symbol, cycle, "NO_TRADE", "HTF_BIAS_NOT_ALIGNED")
    bias = d1_bias
    direction = "LONG" if bias == "BULLISH" else "SHORT"

    h4_kind = "DEMAND" if bias == "BULLISH" else "SUPPLY"
    h4_zone = latest_fresh_zone(h4, h4_kind)
    if h4_zone is None:
        return _decision(symbol, cycle, "NO_TRADE", "NO_FRESH_H4_POI", bias=bias, direction=direction)
    if not zone_touched(h1, h4_zone, lookback=4):
        return _decision(symbol, cycle, "NO_TRADE", "HTF_POI_NOT_REACHED", bias=bias,
                         direction=direction, h4_zone=h4_zone)

    shifts = control_shift_zones(h1, bias)
    cutoff = h1[max(0, len(h1) - H1_SHIFT_MAX_AGE_BARS)].time
    shifts = tuple(z for z in shifts if z.created_time >= cutoff)
    if not shifts:
        false_class = classify_false_shift(h1, bias)
        reason = "FALSE_CHOCH_" + false_class if false_class else "NO_VALID_H1_CONTROL_SHIFT"
        return _decision(symbol, cycle, "NO_TRADE", reason, bias=bias,
                         false_shift_class=false_class, h4_zone=h4_zone, direction=direction)
    h1_shift = shifts[-1]

    entry_kind = "DEMAND" if bias == "BULLISH" else "SUPPLY"
    refinements = [z for z in zones(m15)
                   if z.kind == entry_kind and z.created_time >= h1_shift.created_time and _in_window(z.created_time, cycle)]
    if not refinements:
        return _decision(symbol, cycle, "NO_TRADE", "NO_M15_ENTRY_REFINEMENT", bias=bias,
                         h4_zone=h4_zone, h1_shift_zone=h1_shift, direction=direction)
    entry_zone = refinements[-1]
    entry = entry_zone.midpoint
    buffer = entry_zone.height * STOP_BUFFER_FRACTION
    if entry_zone.height <= 0:
        return _decision(symbol, cycle, "DATA_INVALID", "NON_POSITIVE_ENTRY_ZONE", bias=bias,
                         h4_zone=h4_zone, h1_shift_zone=h1_shift, direction=direction)

    if direction == "LONG":
        stop = entry_zone.low - buffer
        risk = entry - stop
        tp1 = entry + 2.0 * risk
    else:
        stop = entry_zone.high + buffer
        risk = stop - entry
        tp1 = entry - 2.0 * risk
    if risk <= 0:
        return _decision(symbol, cycle, "DATA_INVALID", "NON_POSITIVE_RISK", bias=bias,
                         h4_zone=h4_zone, h1_shift_zone=h1_shift, m15_entry_zone=entry_zone,
                         direction=direction)

    tp2 = structural_target(h4, direction, entry, tp1)
    if tp2 is None:
        return _decision(symbol, cycle, "NO_TRADE", "NO_VALID_HTF_FINAL_TARGET", bias=bias,
                         h4_zone=h4_zone, h1_shift_zone=h1_shift, m15_entry_zone=entry_zone,
                         direction=direction)

    signal_time = entry_zone.created_time
    expiry = _expiry(signal_time, cycle)
    return _decision(
        symbol, cycle, "SIGNAL", "READY_RESEARCH_SHADOW",
        bias=bias, h4_zone=h4_zone, h1_shift_zone=h1_shift, m15_entry_zone=entry_zone,
        direction=direction, entry_order_type="LIMIT", entry=entry, stop_loss=stop,
        risk_distance=risk, tp1=tp1, tp2=tp2, signal_timestamp=signal_time,
        expiry_timestamp=expiry,
    )
