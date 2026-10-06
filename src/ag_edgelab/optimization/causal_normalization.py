"""Anti-leak normalization policy for R3 causal inference (PHASE B3).

Aggregate transforms fit over a full sample (z-score, rank percentile,
centered rolling windows, whole-dataset volatility normalization) leak future
observations into earlier events when applied retrospectively.  This module
freezes the permitted construction:

* a normalization/model may be fit ONLY on an explicitly authorized prior /
  training partition, and
* it must be FROZEN before any later event is scored, and
* scoring an event whose ``decision_ts`` precedes the fit cutoff is a
  :class:`NormalizationLeak` hard error.

The final aggregate campaign statistic over an expanding sample is explicitly
NOT required to remain identical as future independent events arrive; what is
forbidden is any transform that changes an EARLIER event's inputs using
LATER observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import fmean, pstdev
from typing import Sequence

from ag_edgelab.optimization.causal_time import require_aware_utc


class NormalizationLeak(RuntimeError):
    """A normalization consumed information from after the scored event."""


@dataclass(frozen=True)
class FrozenPartitionNormalizer:
    """Fit once on an authorized prior partition, then frozen forever.

    ``fit_observations`` must all satisfy ``available_at <= fit_cutoff``.
    The frozen parameters are immutable; scoring is only permitted for
    events with ``decision_ts >= fit_cutoff``.
    """

    fit_cutoff: datetime
    mean: float
    sd: float
    name: str = "FROZEN_PARTITION_ZSCORE_V1"

    @classmethod
    def fit(cls, values: Sequence[float], available_at: Sequence[datetime],
            fit_cutoff: datetime) -> "FrozenPartitionNormalizer":
        require_aware_utc(fit_cutoff, "fit_cutoff")
        if len(values) != len(available_at) or not values:
            raise ValueError("fit requires aligned non-empty observations")
        for stamp in available_at:
            require_aware_utc(stamp, "available_at")
            if stamp > fit_cutoff:
                raise NormalizationLeak(
                    f"fit observation available_at {stamp.isoformat()} exceeds "
                    f"fit_cutoff {fit_cutoff.isoformat()}")
        sd = pstdev(values)
        return cls(fit_cutoff, fmean(values), sd if sd > 0 else 0.0)

    def score(self, value: float, decision_ts: datetime) -> float:
        require_aware_utc(decision_ts, "decision_ts")
        if decision_ts < self.fit_cutoff:
            raise NormalizationLeak(
                f"event decision_ts {decision_ts.isoformat()} precedes frozen "
                f"fit cutoff {self.fit_cutoff.isoformat()}: full-sample or "
                "future-fit normalization cannot score past events")
        if self.sd == 0:
            return 0.0
        return (value - self.mean) / self.sd


def assert_no_full_sample_fit(fit_available_at: Sequence[datetime],
                              scored_decision_ts: Sequence[datetime]) -> None:
    """Reject any fit window that extends past a scored event's decision.

    A globally fit transform is admissible only when every fitted
    observation's ``available_at`` is at or before EVERY scored event's
    ``decision_ts`` — i.e. the fit partition is strictly prior.
    """
    if not scored_decision_ts:
        return
    earliest_decision = min(scored_decision_ts)
    for stamp in fit_available_at:
        require_aware_utc(stamp, "available_at")
        if stamp > earliest_decision:
            raise NormalizationLeak(
                f"fit observation available_at {stamp.isoformat()} is after the "
                f"earliest scored decision_ts {earliest_decision.isoformat()}: "
                "full-sample normalization leaks future data into past events")
