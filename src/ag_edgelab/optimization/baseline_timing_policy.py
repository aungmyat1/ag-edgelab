"""Frozen baseline T2 timing policies for the causal R3 estimand (PHASE B6).

The owner must choose how non-parent baseline opportunities' reference
entries are timed (decision R3_OD_05).  This module implements the three
compared policies as pure deterministic functions so the sensitivity
analysis — and any future owner selection — uses exactly one audited
implementation:

* ``EMPIRICAL_MATCHED_DELAY`` — deterministic hash slot into the sorted
  parent T2−T0 lag distribution (the R3.2 adversarial-diagnostic
  semantics).
* ``STRATIFIED_EMPIRICAL_MATCHED_DELAY`` — by symbol + session, and by
  year where the (symbol, session, year) parent stratum has at least
  ``min_stratum_parent_n`` parents.  Sub-threshold years fall back to the
  (symbol, session) pool; the year decision is made PER YEAR, never
  collapsed across sibling years.
* ``FIXED_CAUSAL_DELAY_FROM_T1`` — one preregistered clock that does not
  depend on whether the opportunity later qualifies.

Every assignment is deterministic in its inputs; no outcome information
enters any of these functions.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Mapping, Sequence

EMPIRICAL_MATCHED_DELAY = "EMPIRICAL_MATCHED_DELAY"
STRATIFIED_EMPIRICAL_MATCHED_DELAY = "STRATIFIED_EMPIRICAL_MATCHED_DELAY"
FIXED_CAUSAL_DELAY_FROM_T1 = "FIXED_CAUSAL_DELAY_FROM_T1"

BASELINE_TIMING_POLICIES: tuple[str, ...] = (
    EMPIRICAL_MATCHED_DELAY,
    STRATIFIED_EMPIRICAL_MATCHED_DELAY,
    FIXED_CAUSAL_DELAY_FROM_T1,
)

DEFAULT_MIN_STRATUM_PARENT_N = 30
DEFAULT_FIXED_DELAY_FROM_T1_MINUTES = 120


def deterministic_slot(key: str, modulo: int) -> int:
    """Stable hash slot; identical inputs always select the identical slot."""
    if modulo <= 0:
        raise ValueError("modulo must be positive")
    return int(hashlib.sha256(key.encode()).hexdigest()[:16], 16) % modulo


def empirical_matched_delay(event_id: str, t0: datetime,
                            parent_t2_lags: Sequence[timedelta]) -> datetime:
    """Policy A: T0 + a parent lag chosen by deterministic event slot."""
    if not parent_t2_lags:
        raise ValueError("EMPIRICAL_MATCHED_DELAY requires parent lags")
    ordered = sorted(parent_t2_lags)
    return t0 + ordered[deterministic_slot(event_id, len(ordered))]


@dataclass(frozen=True)
class StratifiedDelayPools:
    """Parent T2−T0 lag pools for stratified baseline timing.

    ``year_pools`` is keyed by (symbol, session, year) and exists only for
    strata with at least ``min_stratum_parent_n`` parents;
    ``session_pools`` is keyed by (symbol, session) over ALL parents of
    that session stratum.  Year eligibility is evaluated per individual
    (symbol, session, year) stratum — never collapsed across sibling
    years.
    """

    min_stratum_parent_n: int
    session_pools: Mapping[tuple[str, str], tuple[timedelta, ...]]
    year_pools: Mapping[tuple[str, str, int], tuple[timedelta, ...]]
    year_counts: Mapping[tuple[str, str, int], int] = field(default_factory=dict)

    @classmethod
    def build(cls, parent_rows: Sequence[tuple[str, str, str, int, timedelta]],
              *, min_stratum_parent_n: int = DEFAULT_MIN_STRATUM_PARENT_N) -> "StratifiedDelayPools":
        """Build from (event_id, symbol, session, year, t2_minus_t0_lag)."""
        if min_stratum_parent_n <= 0:
            raise ValueError("min_stratum_parent_n must be positive")
        by_year: dict[tuple[str, str, int], list[timedelta]] = {}
        by_session: dict[tuple[str, str], list[timedelta]] = {}
        for _event_id, symbol, session, year, lag in parent_rows:
            by_year.setdefault((symbol, session, year), []).append(lag)
            by_session.setdefault((symbol, session), []).append(lag)
        year_pools = {key: tuple(sorted(lags)) for key, lags in by_year.items()
                      if len(lags) >= min_stratum_parent_n}
        session_pools = {key: tuple(sorted(lags)) for key, lags in by_session.items()}
        return cls(min_stratum_parent_n, session_pools, year_pools,
                   {key: len(lags) for key, lags in by_year.items()})

    def delay(self, event_id: str, t0: datetime, symbol: str, session: str,
              year: int) -> datetime:
        """Policy B: year pool when that year stratum is adequate, else the
        (symbol, session) pool.  The fallback pool always exists because a
        parent populated the session stratum."""
        year_key = (symbol, session, year)
        pool = self.year_pools.get(year_key)
        if pool is None:
            pool = self.session_pools.get((symbol, session))
        if not pool:
            raise ValueError(f"no delay pool for {symbol}/{session}")
        return t0 + pool[deterministic_slot(f"{event_id}|{year_key}", len(pool))]


def fixed_causal_delay_from_t1(t1: datetime, *, minutes: int = DEFAULT_FIXED_DELAY_FROM_T1_MINUTES) -> datetime:
    """Policy C: T1 + one preregistered constant clock."""
    if minutes <= 0:
        raise ValueError("fixed delay must be positive")
    return t1 + timedelta(minutes=minutes)
