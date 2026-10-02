from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from ag_edgelab.statistics.performance import compute_performance
from ag_edgelab.verification.time import UTCDateTime, utc_datetime


@dataclass(frozen=True)
class ChronologicalFold:
    fold_id: str
    train_start: UTCDateTime
    train_end: UTCDateTime
    test_start: UTCDateTime
    test_end: UTCDateTime

    def __post_init__(self):
        for name in ("train_start", "train_end", "test_start", "test_end"):
            object.__setattr__(self, name, utc_datetime(getattr(self, name)))
        if not (self.train_start < self.train_end <= self.test_start < self.test_end):
            raise ValueError("fold must be chronological and non-overlapping")


@dataclass(frozen=True)
class FoldResult:
    fold_id: str
    trades: int
    expectancy_r: float | None
    profit_factor: float | None
    max_drawdown_r: float


def run_walk_forward(folds: Sequence[ChronologicalFold], evaluator: Callable[[ChronologicalFold], Sequence[float]]) -> tuple[FoldResult, ...]:
    results = []
    previous_test_end = None
    for fold in folds:
        if previous_test_end is not None and fold.test_start < previous_test_end:
            raise ValueError("walk-forward test windows overlap")
        rs = tuple(float(x) for x in evaluator(fold))
        p = compute_performance(rs)
        results.append(FoldResult(fold.fold_id, p.trades, p.expectancy_r, p.profit_factor, p.max_drawdown_r))
        previous_test_end = fold.test_end
    return tuple(results)


@dataclass(frozen=True)
class RegimeSlice:
    name: str
    outcomes_r: tuple[float, ...]


def evaluate_regimes(slices: Sequence[RegimeSlice]):
    return tuple((s.name, compute_performance(s.outcomes_r)) for s in slices)
