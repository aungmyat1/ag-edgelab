"""Funnel 1 (part A) — deterministic MTF structural direction + MA family.

Scale-invariant by construction (pure price inequalities), so the SAME rule
produces the SAME structural state for EURUSD and BTCUSDT given structurally
identical bars (cross-asset parity, mission section 20).

Research timeframes: D1 / H4 / H1 required, W1 optional context.
MA family preregistered as MA50 / MA200 only — no optimization.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.strategies.crypto_mtf_smc import SwingPoint, confirmed_swing_points

REQUIRED_DIRECTION_TIMEFRAMES: tuple[str, ...] = ("D1", "H4", "H1")
OPTIONAL_DIRECTION_TIMEFRAMES: tuple[str, ...] = ("W1",)

# Preregistered MA family (mission section 7). Frozen; never tuned.
MA_FAST = 50
MA_SLOW = 200


class Direction(StrEnum):
    BULL = "BULL"
    BEAR = "BEAR"
    NEUTRAL = "NEUTRAL"


class DirectionMode(StrEnum):
    STRUCTURE_ONLY = "STRUCTURE_ONLY"
    MA_ONLY = "MA_ONLY"
    STRUCTURE_PLUS_MA = "STRUCTURE_PLUS_MA"


def assert_no_future_bars(bars: Sequence[MarketBar], as_of: datetime) -> None:
    """Anti-lookahead guard: every bar must have CLOSED at or before as_of.

    Callers pass the bar's open timestamp + timeframe span implicitly by
    pre-cutting; this guard rejects any bar whose open is after as_of.
    """
    as_of = as_of.astimezone(timezone.utc)
    for bar in bars:
        if bar.timestamp.astimezone(timezone.utc) > as_of:
            raise ValueError(f"future bar at {bar.timestamp.isoformat()} > as_of {as_of.isoformat()}")


class TimeframeDirection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    timeframe: str
    direction: Direction
    prior_high: float | None = None
    last_high: float | None = None
    prior_low: float | None = None
    last_low: float | None = None
    reason: str


def structural_direction(
    bars: tuple[MarketBar, ...],
    timeframe: str,
    swing_order: int = 2,
    asof_index: int | None = None,
) -> TimeframeDirection:
    """HH/HL -> BULL, LH/LL -> BEAR, anything unresolved/conflicting -> NEUTRAL.

    Uses only swings CONFIRMED at or before `asof_index` (default: last bar).
    A pivot confirms only after `swing_order` right-side bars close, so this
    is anti-lookahead-safe by construction.
    """
    idx = len(bars) - 1 if asof_index is None else asof_index
    swings = confirmed_swing_points(bars, swing_order)
    highs = [s for s in swings if s.kind == "HIGH" and s.confirmed_index <= idx]
    lows = [s for s in swings if s.kind == "LOW" and s.confirmed_index <= idx]
    if len(highs) < 2 or len(lows) < 2:
        return TimeframeDirection(timeframe=timeframe, direction=Direction.NEUTRAL,
                                  reason="INSUFFICIENT_CONFIRMED_SWINGS")
    h1, h2 = highs[-2], highs[-1]
    l1, l2 = lows[-2], lows[-1]
    hh, hl = h2.price > h1.price, l2.price > l1.price
    lh, ll = h2.price < h1.price, l2.price < l1.price
    if hh and hl:
        direction, reason = Direction.BULL, "CONFIRMED_HH_HL"
    elif lh and ll:
        direction, reason = Direction.BEAR, "CONFIRMED_LH_LL"
    else:
        direction, reason = Direction.NEUTRAL, "UNRESOLVED_OR_CONFLICTING_STRUCTURE"
    return TimeframeDirection(timeframe=timeframe, direction=direction,
                              prior_high=h1.price, last_high=h2.price,
                              prior_low=l1.price, last_low=l2.price, reason=reason)


class MtfDirectionState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    composite: Direction
    by_timeframe: tuple[TimeframeDirection, ...] = Field(min_length=1)
    rule_id: str = "DIR_STRUCT_MTF_V1"


def mtf_direction(
    frames: Mapping[str, tuple[MarketBar, ...]],
    swing_order: int = 2,
    required: tuple[str, ...] = REQUIRED_DIRECTION_TIMEFRAMES,
) -> MtfDirectionState:
    """Composite MTF direction: conflicting required TFs -> NEUTRAL.

    Preregistered composite rule DIR_STRUCT_MTF_V1: if any required TF is
    BULL and any is BEAR the composite is NEUTRAL; otherwise it takes the
    non-neutral consensus; all-neutral stays NEUTRAL.
    """
    states = tuple(structural_direction(frames[tf], tf, swing_order) for tf in required if tf in frames)
    if not states:
        raise ValueError("no required direction timeframe present")
    values = {s.direction for s in states}
    if Direction.BULL in values and Direction.BEAR in values:
        composite = Direction.NEUTRAL
    elif Direction.BULL in values:
        composite = Direction.BULL
    elif Direction.BEAR in values:
        composite = Direction.BEAR
    else:
        composite = Direction.NEUTRAL
    return MtfDirectionState(composite=composite, by_timeframe=states)


# ---------------------------------------------------------------------------
# MA50/MA200 family — preregistered, no optimization, no assumed improvement
# ---------------------------------------------------------------------------

class MaState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    direction: Direction
    ma_fast: float | None = None
    ma_slow: float | None = None
    fast_period: int = MA_FAST
    slow_period: int = MA_SLOW
    reason: str
    rule_id: str = "DIR_MA_50_200_V1"


def ma_direction(closes: Sequence[float], fast: int = MA_FAST, slow: int = MA_SLOW) -> MaState:
    """MA_BULL: MA50 > MA200; MA_BEAR: MA50 < MA200; else NEUTRAL (fail-closed)."""
    if (fast, slow) != (MA_FAST, MA_SLOW):
        raise ValueError("MA family is preregistered as 50/200 only (no optimization)")
    if len(closes) < slow:
        return MaState(direction=Direction.NEUTRAL, reason="INSUFFICIENT_BARS_FOR_MA200")
    ma_fast = sum(closes[-fast:]) / fast
    ma_slow = sum(closes[-slow:]) / slow
    if ma_fast > ma_slow:
        return MaState(direction=Direction.BULL, ma_fast=ma_fast, ma_slow=ma_slow, reason="MA50_ABOVE_MA200")
    if ma_fast < ma_slow:
        return MaState(direction=Direction.BEAR, ma_fast=ma_fast, ma_slow=ma_slow, reason="MA50_BELOW_MA200")
    return MaState(direction=Direction.NEUTRAL, ma_fast=ma_fast, ma_slow=ma_slow, reason="MA50_EQUALS_MA200")


def combined_direction(structure: Direction, ma: Direction, mode: DirectionMode) -> Direction:
    """Compare structure-only / MA-only / structure+MA without assuming MA helps."""
    if mode == DirectionMode.STRUCTURE_ONLY:
        return structure
    if mode == DirectionMode.MA_ONLY:
        return ma
    # STRUCTURE_PLUS_MA: both authorities must agree on a non-neutral side.
    if structure == ma and structure != Direction.NEUTRAL:
        return structure
    return Direction.NEUTRAL
