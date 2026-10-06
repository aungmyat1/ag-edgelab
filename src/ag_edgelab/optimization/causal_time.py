"""Frozen causal time semantics for R3 policy (PHASE B1).

Vocabulary
----------
BAR_TIMESTAMP_SEMANTICS = BAR_OPEN_TIME
    Every ``MarketBar.timestamp`` in this repository is the bar's OPEN time.
DATA_AVAILABLE_TIME = BAR_OPEN_TIME + BAR_DURATION
    A bar's OHLC values become knowable only when the bar CLOSES.
T1_DIRECTION_AVAILABLE = EVENT_M15_OPEN + 15 minutes
    ALD V2 S4 branch/direction consumes the interaction M15 bar's CLOSE.
T2_DECISION_TIME = CONFIRMATION_M5_CLOSE
    The final parent decision is the close of the confirming M5 bar
    (confirmation bar open + 5 minutes).
REFERENCE_EXECUTABLE_ENTRY = FIRST_M5_OPEN_AT_OR_AFTER_T2
    The executable reference entry is the first M5 bar whose OPEN time is
    at or after T2.  Never the confirmation bar itself.

Every causally sensitive derived fact consumed by an eligibility mask must
carry an ``available_at`` timestamp and satisfy ``available_at <= decision_ts``.
This module provides that schema (:class:`CausalFact`), the enforcement guard
(:func:`assert_available_at_or_before`), and a strictly backward as-of lookup
(:func:`asof_last_at_or_before`) that can never select a future observation.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from ag_edgelab.optimization.direction_causality_audit import (
    m15_direction_available_time as _m15_direction_available_time,
)

UTC = timezone.utc

BAR_TIMESTAMP_SEMANTICS = "BAR_OPEN_TIME"
DATA_AVAILABLE_TIME_RULE = "BAR_OPEN_TIME + BAR_DURATION"

M15_BAR_DURATION = timedelta(minutes=15)
M5_BAR_DURATION = timedelta(minutes=5)
M1_BAR_DURATION = timedelta(minutes=1)


class LookaheadViolation(RuntimeError):
    """A derived fact was consumed before its AVAILABLE_AT timestamp."""


def require_aware_utc(value: datetime, name: str = "timestamp") -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be an aware UTC datetime")
    return value


def data_available_time(bar_open_time: datetime, bar_duration: timedelta) -> datetime:
    """DATA_AVAILABLE_TIME: a bar's values exist only at its close."""
    require_aware_utc(bar_open_time, "bar_open_time")
    if bar_duration <= timedelta(0):
        raise ValueError("bar_duration must be positive")
    return bar_open_time + bar_duration


def m15_data_available_time(m15_bar_open: datetime) -> datetime:
    return data_available_time(m15_bar_open, M15_BAR_DURATION)


def m5_data_available_time(m5_bar_open: datetime) -> datetime:
    return data_available_time(m5_bar_open, M5_BAR_DURATION)


def t1_direction_available(event_m15_open: datetime) -> datetime:
    """T1_DIRECTION_AVAILABLE = EVENT_M15_OPEN + 15 minutes (bar close)."""
    return _m15_direction_available_time(event_m15_open)


def t2_decision_time(confirmation_m5_open: datetime) -> datetime:
    """T2_DECISION_TIME = CONFIRMATION_M5_CLOSE = confirmation open + 5 minutes."""
    require_aware_utc(confirmation_m5_open, "confirmation_m5_open")
    return confirmation_m5_open + M5_BAR_DURATION


def first_m5_open_at_or_after(m5_opens: Sequence[datetime], t2: datetime) -> datetime | None:
    """REFERENCE_EXECUTABLE_ENTRY = FIRST_M5_OPEN_AT_OR_AFTER_T2.

    ``m5_opens`` must be sorted bar OPEN timestamps.  Returns the first open
    at or after ``t2``, or ``None`` when no such bar exists.  This is a pure
    schedule query over supplied bars; it never inspects bar values.
    """
    require_aware_utc(t2, "t2")
    if any(open_time.tzinfo is None or open_time.utcoffset() != timedelta(0)
           for open_time in m5_opens):
        raise ValueError("m5_opens must be aware UTC datetimes")
    index = bisect_left(m5_opens, t2)
    if index >= len(m5_opens):
        return None
    return m5_opens[index]


@dataclass(frozen=True)
class CausalFact:
    """A derived fact plus the earliest time it can be consumed.

    ``available_at`` is the time at which the fact's value became knowable
    from completed bars only.  A fact whose ``available_at`` exceeds the
    consumer's ``decision_ts`` is future information and may never enter an
    eligibility mask, feature, or normalization.
    """

    name: str
    value: object
    available_at: datetime

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("causal fact requires a name")
        require_aware_utc(self.available_at, f"available_at[{self.name}]")


def assert_available_at_or_before(fact: CausalFact, decision_ts: datetime) -> None:
    """Enforce available_at <= decision_ts for every mask input fact."""
    require_aware_utc(decision_ts, "decision_ts")
    if fact.available_at > decision_ts:
        raise LookaheadViolation(
            f"fact {fact.name!r} available_at {fact.available_at.isoformat()} "
            f"exceeds decision_ts {decision_ts.isoformat()}")


def asof_last_at_or_before(facts: Sequence[CausalFact], ts: datetime) -> CausalFact:
    """Strictly BACKWARD as-of lookup: the last fact with available_at <= ts.

    Never a nearest lookup: if only future observations exist, this raises
    :class:`LookaheadViolation` instead of silently selecting a future fact.
    """
    require_aware_utc(ts, "ts")
    eligible = [fact for fact in facts if fact.available_at <= ts]
    if not eligible:
        raise LookaheadViolation(
            f"no observation available at or before {ts.isoformat()}; "
            "a forward lookup is forbidden")
    return max(eligible, key=lambda fact: fact.available_at)
