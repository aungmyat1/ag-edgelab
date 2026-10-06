"""Strategy-independent DEVELOPMENT reference outcomes for the R3 gate."""

from __future__ import annotations

import math
import random
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from statistics import mean
from typing import Sequence

from ag_edgelab.contracts.market import MarketBar

UTC = timezone.utc
REFERENCE_MODEL_ID = "REFERENCE_OUTCOME_MODEL_V2"


class ReferenceDirectionMode(StrEnum):
    RANDOM_DIRECTION = "RANDOM_DIRECTION"
    BOTH_DIRECTIONS_SYMMETRIC = "BOTH_DIRECTIONS_SYMMETRIC"
    SIMPLE_TREND_DIRECTION = "SIMPLE_TREND_DIRECTION"


@dataclass(frozen=True)
class ReferenceOutcomeV2Config:
    direction_mode: ReferenceDirectionMode = ReferenceDirectionMode.BOTH_DIRECTIONS_SYMMETRIC
    atr_period: int = 14
    stop_atr_multiple: float = 1.0
    target_r: float = 2.0
    max_holding_bars: int = 72
    rng_seed: int = 0xF03A2026
    direction_authorized: bool = False
    friction_status: str = "UNKNOWN_SEPARATE_NOT_APPLIED"

    def __post_init__(self) -> None:
        if min(self.atr_period, self.max_holding_bars) <= 0:
            raise ValueError("ATR period and horizon must be positive")
        if self.stop_atr_multiple <= 0 or self.target_r <= 0:
            raise ValueError("stop and target geometry must be positive")
        if self.rng_seed < 0:
            raise ValueError("rng_seed must be non-negative")


@dataclass(frozen=True)
class ReferenceOutcomeV2:
    outcome_r: float | None
    entry_time: datetime | None
    entry_price: float | None
    atr: float | None
    long_outcome_r: float | None
    short_outcome_r: float | None
    exit_reason: str
    direction_mode: ReferenceDirectionMode


def _atr_before(bars: Sequence[MarketBar], entry_index: int, period: int) -> float | None:
    # Every true range ends strictly before the entry bar.  No entry/future
    # high or low contributes to the stop distance.
    if entry_index < period + 1:
        return None
    ranges = []
    for index in range(entry_index - period, entry_index):
        bar, previous = bars[index], bars[index - 1]
        ranges.append(max(bar.high - bar.low, abs(bar.high - previous.close), abs(bar.low - previous.close)))
    value = mean(ranges)
    return value if value > 0 and math.isfinite(value) else None


def _one_direction(entry: float, distance: float, target_r: float,
                   forward: Sequence[MarketBar], *, long: bool) -> tuple[float, str]:
    stop = entry - distance if long else entry + distance
    target = entry + target_r * distance if long else entry - target_r * distance
    for bar in forward:
        hit_stop = bar.low <= stop if long else bar.high >= stop
        hit_target = bar.high >= target if long else bar.low <= target
        # With OHLC data no within-bar ordering authority exists.  The frozen
        # conservative contract resolves a tie stop-first rather than choosing
        # the favorable path or dropping coverage selectively.
        if hit_stop:
            return -1.0, "STOP_FIRST" if hit_target else "STOP"
        if hit_target:
            return target_r, "TARGET"
    close = forward[-1].close
    return ((close - entry) / distance if long else (entry - close) / distance), "TIMEOUT"


def evaluate_reference_outcome_v2(
    bars: Sequence[MarketBar],
    opportunity_time: datetime,
    *,
    event_id: str,
    config: ReferenceOutcomeV2Config = ReferenceOutcomeV2Config(),
) -> ReferenceOutcomeV2:
    """Evaluate from the opportunity timestamp without strategy-stage facts."""
    if opportunity_time.tzinfo is None or opportunity_time.utcoffset() != timedelta(0):
        raise ValueError("opportunity_time must be aware UTC")
    entry_index = bisect_left(bars, opportunity_time, key=lambda bar: bar.timestamp)
    if entry_index >= len(bars):
        return ReferenceOutcomeV2(None, None, None, None, None, None, "NO_ENTRY_BAR", config.direction_mode)
    atr = _atr_before(bars, entry_index, config.atr_period)
    forward = bars[entry_index:entry_index + config.max_holding_bars]
    if atr is None or len(forward) < config.max_holding_bars:
        return ReferenceOutcomeV2(None, bars[entry_index].timestamp, bars[entry_index].open,
                                  atr, None, None, "INSUFFICIENT_CAUSAL_HISTORY", config.direction_mode)
    entry = bars[entry_index].open
    distance = atr * config.stop_atr_multiple
    long_r, long_reason = _one_direction(entry, distance, config.target_r, forward, long=True)
    short_r, short_reason = _one_direction(entry, distance, config.target_r, forward, long=False)
    if config.direction_mode is ReferenceDirectionMode.BOTH_DIRECTIONS_SYMMETRIC:
        # R3.1 retains both directional legs as one opportunity cluster.  A
        # scalar symmetric average would erase the parent's directional value
        # and invite accidental leg-level resampling, so no scalar is emitted.
        outcome = None
        reason = f"SYMMETRIC_LEGS:{long_reason}+{short_reason}"
    elif config.direction_mode is ReferenceDirectionMode.RANDOM_DIRECTION:
        choose_long = random.Random(f"REFERENCE_V2:{config.rng_seed}:{event_id}").getrandbits(1) == 1
        outcome, reason = (long_r, f"RANDOM_LONG:{long_reason}") if choose_long else (short_r, f"RANDOM_SHORT:{short_reason}")
    else:
        # A deliberately simple causal trend rule, supported but never the
        # neutral default: compare the last two completed closes.
        choose_long = bars[entry_index - 1].close >= bars[entry_index - 2].close
        outcome, reason = (long_r, f"TREND_LONG:{long_reason}") if choose_long else (short_r, f"TREND_SHORT:{short_reason}")
    return ReferenceOutcomeV2(outcome, bars[entry_index].timestamp, entry, atr,
                              long_r, short_r, reason, config.direction_mode)
