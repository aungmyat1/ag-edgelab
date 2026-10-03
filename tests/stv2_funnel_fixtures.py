"""Deterministic synthetic session fixtures for the STV2 strategy-funnel tests.

These build *exactly* complete session windows under the frozen STV2 contract
(32/20 reference M15 bars, 12 trade M15 bars) so that stage semantics can be
asserted without touching real market data or the frozen rules.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from ag_edgelab.campaigns.session_trade_v2.windows import (
    REFERENCE_BAR_COUNT,
    TRADE_BAR_COUNT,
    session_window,
)
from ag_edgelab.contracts.market import MarketBar

UTC = timezone.utc
M15 = timedelta(minutes=15)

DATASET_SHA = {
    "EURUSD": "a" * 64,
    "GBPUSD": "b" * 64,
    "USDJPY": "c" * 64,
    "XAUUSD": "d" * 64,
}


def bar(ts: datetime, o: float, h: float, low: float, c: float) -> MarketBar:
    return MarketBar(timestamp=ts, open=o, high=h, low=low, close=c)


def flat_bars(start: datetime, count: int, lo: float, hi: float) -> list[MarketBar]:
    """``count`` M15 bars from ``start`` oscillating strictly inside ``[lo, hi]``."""
    mid = (lo + hi) / 2.0
    out = []
    for i in range(count):
        ts = start + i * M15
        if i == 0:
            out.append(bar(ts, mid, hi, lo, mid))  # establishes the box exactly
        else:
            out.append(bar(ts, mid, mid + (hi - lo) * 0.1, mid - (hi - lo) * 0.1, mid))
    return out


def build_session(
    session: str,
    trading_date: date,
    *,
    ref_low: float,
    ref_high: float,
    trade_specs: list[tuple[float, float, float, float]],
) -> list[MarketBar]:
    """Build one complete session: exact reference box + exactly 12 trade bars.

    ``trade_specs`` is a list of ``(open, high, low, close)`` of length 12.
    """
    window = session_window(session, trading_date)
    ref = flat_bars(window.reference_start, REFERENCE_BAR_COUNT[session], ref_low, ref_high)
    assert len(trade_specs) == TRADE_BAR_COUNT, "need exactly 12 trade bars"
    trade = [
        bar(window.trade_start + i * M15, *spec) for i, spec in enumerate(trade_specs)
    ]
    return ref + trade


def inside(ref_low: float, ref_high: float) -> tuple[float, float, float, float]:
    """A quiet trade bar fully inside the box (triggers nothing)."""
    mid = (ref_low + ref_high) / 2.0
    pad = (ref_high - ref_low) * 0.05
    return (mid, mid + pad, mid - pad, mid)


def filler(ref_low: float, ref_high: float, n: int) -> list[tuple[float, float, float, float]]:
    return [inside(ref_low, ref_high)] * n


def sweep_low_reclaim(ref_low: float, ref_high: float, depth: float, close: float):
    """A long sweep: ``low < ref_low`` and ``close > ref_low``."""
    return (ref_low, max(close, ref_low), ref_low - depth, close)


def sweep_high_reclaim(ref_low: float, ref_high: float, depth: float, close: float):
    """A short sweep: ``high > ref_high`` and ``close < ref_high``."""
    return (ref_high, ref_high + depth, min(close, ref_high), close)


def exact_touch_low(ref_low: float, ref_high: float, close: float):
    """B long rejection: ``low == ref_low`` exactly, inward close."""
    return (close, close, ref_low, close)


def exact_touch_high(ref_low: float, ref_high: float, close: float):
    """B short rejection: ``high == ref_high`` exactly, inward close."""
    return (close, ref_high, close, close)


def body_breakout_up(ref_high: float, lift: float):
    """C long expansion: whole body above the box."""
    o = ref_high + lift
    c = ref_high + lift * 2
    return (o, c, o, c)


def body_breakout_down(ref_low: float, drop: float):
    """C short expansion: whole body below the box."""
    o = ref_low - drop
    c = ref_low - drop * 2
    return (o, o, c, c)
