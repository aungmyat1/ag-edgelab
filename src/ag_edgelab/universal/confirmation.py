"""Funnel 2 — lower-timeframe confirmation primitives (M15/M5 layer).

Only deterministic contracts are implemented; every primitive below has an
exact numeric definition. Direction authority exists BEFORE setup
evaluation; a setup against authority is recorded as COUNTER_DIRECTION in
the diagnostic population, never silently dropped (mission section 11).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.strategies.crypto_mtf_smc import IncrementalStructure
from ag_edgelab.universal.direction import Direction

# Preregistered candle-pattern geometry (frozen; not searched).
PIN_WICK_BODY_MULT = 2.0      # dominant wick >= 2x body
PIN_WICK_RANGE_FRACTION = 0.66  # dominant wick >= 66% of full range
STAR_SMALL_BODY_FRACTION = 0.30  # middle candle body <= 30% of first body


class ConfirmationPrimitive(StrEnum):
    LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"
    MSS = "MSS"
    BOS = "BOS"
    ENGULFING = "ENGULFING"
    PIN_BAR = "PIN_BAR"
    MORNING_STAR = "MORNING_STAR"
    EVENING_STAR = "EVENING_STAR"


class SetupAlignment(StrEnum):
    ALIGNED = "ALIGNED"
    COUNTER_DIRECTION = "COUNTER_DIRECTION"
    NEUTRAL = "NEUTRAL"


class ConfirmationEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    primitive: ConfirmationPrimitive
    timeframe: str
    index: int = Field(ge=0)          # bar index on which the event CLOSED
    timestamp: datetime
    direction: Direction              # BULL / BEAR side of the event
    level: float | None = None        # reference level where applicable
    extreme: float | None = None      # sweep extreme where applicable


def classify_alignment(authority: Direction, event_direction: Direction) -> SetupAlignment:
    """Direction precedes setup: authority is fixed before the event is judged."""
    if authority == Direction.NEUTRAL or event_direction == Direction.NEUTRAL:
        return SetupAlignment.NEUTRAL
    return SetupAlignment.ALIGNED if authority == event_direction else SetupAlignment.COUNTER_DIRECTION


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def liquidity_sweep_events(
    bars: tuple[MarketBar, ...], timeframe: str, level: float, side: str,
    start: int = 0, end: int | None = None,
) -> tuple[ConfirmationEvent, ...]:
    """Sweep contract: bar trades beyond `level` but CLOSES back on the origin side.

    side="BELOW" (sell-side liquidity): low < level and close > level -> BULL event.
    side="ABOVE" (buy-side liquidity): high > level and close < level -> BEAR event.
    """
    if side not in ("BELOW", "ABOVE"):
        raise ValueError("side must be BELOW or ABOVE")
    stop = len(bars) if end is None else min(end, len(bars))
    out: list[ConfirmationEvent] = []
    for i in range(start, stop):
        bar = bars[i]
        if side == "BELOW" and bar.low < level and bar.close > level:
            out.append(ConfirmationEvent(primitive=ConfirmationPrimitive.LIQUIDITY_SWEEP,
                                         timeframe=timeframe, index=i, timestamp=bar.timestamp,
                                         direction=Direction.BULL, level=level, extreme=bar.low))
        elif side == "ABOVE" and bar.high > level and bar.close < level:
            out.append(ConfirmationEvent(primitive=ConfirmationPrimitive.LIQUIDITY_SWEEP,
                                         timeframe=timeframe, index=i, timestamp=bar.timestamp,
                                         direction=Direction.BEAR, level=level, extreme=bar.high))
    return tuple(out)


def structure_shift_events(
    bars: tuple[MarketBar, ...], timeframe: str, swing_order: int = 2,
) -> tuple[ConfirmationEvent, ...]:
    """BOS/MSS contract via the shared IncrementalStructure core.

    A close beyond the last confirmed opposing swing while bias is OPPOSITE
    is an MSS (structure shift); while bias is already same-side or neutral
    it is a BOS (break of structure/continuation). Closed bars only.
    """
    tracker = IncrementalStructure(bars, swing_order)
    out: list[ConfirmationEvent] = []
    prev_bias = "NEUTRAL"
    prev_bull_bos = -1
    prev_bear_bos = -1
    for j in range(len(bars)):
        state = tracker.update(j)
        if state.last_bullish_bos_index == j and j > prev_bull_bos:
            primitive = (ConfirmationPrimitive.MSS if prev_bias == "BEARISH"
                         else ConfirmationPrimitive.BOS)
            out.append(ConfirmationEvent(primitive=primitive, timeframe=timeframe, index=j,
                                         timestamp=bars[j].timestamp, direction=Direction.BULL,
                                         level=state.swing_high))
        if state.last_bearish_bos_index == j and j > prev_bear_bos:
            primitive = (ConfirmationPrimitive.MSS if prev_bias == "BULLISH"
                         else ConfirmationPrimitive.BOS)
            out.append(ConfirmationEvent(primitive=primitive, timeframe=timeframe, index=j,
                                         timestamp=bars[j].timestamp, direction=Direction.BEAR,
                                         level=state.swing_low))
        prev_bias = state.bias
        prev_bull_bos = state.last_bullish_bos_index
        prev_bear_bos = state.last_bearish_bos_index
    return tuple(out)


def engulfing_event(bars: tuple[MarketBar, ...], timeframe: str, i: int) -> ConfirmationEvent | None:
    """Engulfing contract: bar i body strictly engulfs bar i-1 body, opposite colour."""
    if i < 1 or i >= len(bars):
        return None
    prev, cur = bars[i - 1], bars[i]
    prev_body = abs(prev.close - prev.open)
    cur_body = abs(cur.close - cur.open)
    if cur_body <= prev_body or prev_body <= 0:
        return None
    if cur.close > cur.open and prev.close < prev.open \
            and cur.open <= prev.close and cur.close >= prev.open:
        return ConfirmationEvent(primitive=ConfirmationPrimitive.ENGULFING, timeframe=timeframe,
                                 index=i, timestamp=cur.timestamp, direction=Direction.BULL)
    if cur.close < cur.open and prev.close > prev.open \
            and cur.open >= prev.close and cur.close <= prev.open:
        return ConfirmationEvent(primitive=ConfirmationPrimitive.ENGULFING, timeframe=timeframe,
                                 index=i, timestamp=cur.timestamp, direction=Direction.BEAR)
    return None


def pin_bar_event(bars: tuple[MarketBar, ...], timeframe: str, i: int) -> ConfirmationEvent | None:
    """Pin bar contract: dominant wick >= 2x body AND >= 66% of the bar range."""
    if i < 0 or i >= len(bars):
        return None
    bar = bars[i]
    rng = bar.high - bar.low
    body = abs(bar.close - bar.open)
    if rng <= 0:
        return None
    lower = min(bar.open, bar.close) - bar.low
    upper = bar.high - max(bar.open, bar.close)
    if lower >= PIN_WICK_BODY_MULT * body and lower >= PIN_WICK_RANGE_FRACTION * rng:
        return ConfirmationEvent(primitive=ConfirmationPrimitive.PIN_BAR, timeframe=timeframe,
                                 index=i, timestamp=bar.timestamp, direction=Direction.BULL)
    if upper >= PIN_WICK_BODY_MULT * body and upper >= PIN_WICK_RANGE_FRACTION * rng:
        return ConfirmationEvent(primitive=ConfirmationPrimitive.PIN_BAR, timeframe=timeframe,
                                 index=i, timestamp=bar.timestamp, direction=Direction.BEAR)
    return None


def morning_star_event(bars: tuple[MarketBar, ...], timeframe: str, i: int) -> ConfirmationEvent | None:
    """Morning star contract (3 closed bars ending at i):

    bar i-2 bearish; bar i-1 body <= 30% of bar i-2 body; bar i bullish with
    close above the midpoint of bar i-2's body.
    """
    if i < 2 or i >= len(bars):
        return None
    a, b, c = bars[i - 2], bars[i - 1], bars[i]
    body_a = abs(a.close - a.open)
    if body_a <= 0 or a.close >= a.open:
        return None
    if abs(b.close - b.open) > STAR_SMALL_BODY_FRACTION * body_a:
        return None
    if c.close <= c.open or c.close <= (a.open + a.close) / 2.0:
        return None
    return ConfirmationEvent(primitive=ConfirmationPrimitive.MORNING_STAR, timeframe=timeframe,
                             index=i, timestamp=c.timestamp, direction=Direction.BULL)


def evening_star_event(bars: tuple[MarketBar, ...], timeframe: str, i: int) -> ConfirmationEvent | None:
    """Evening star contract — exact mirror of the morning star."""
    if i < 2 or i >= len(bars):
        return None
    a, b, c = bars[i - 2], bars[i - 1], bars[i]
    body_a = abs(a.close - a.open)
    if body_a <= 0 or a.close <= a.open:
        return None
    if abs(b.close - b.open) > STAR_SMALL_BODY_FRACTION * body_a:
        return None
    if c.close >= c.open or c.close >= (a.open + a.close) / 2.0:
        return None
    return ConfirmationEvent(primitive=ConfirmationPrimitive.EVENING_STAR, timeframe=timeframe,
                             index=i, timestamp=c.timestamp, direction=Direction.BEAR)
