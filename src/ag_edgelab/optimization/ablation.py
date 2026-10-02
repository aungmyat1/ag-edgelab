from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from ag_edgelab.statistics.performance import compute_performance


@dataclass(frozen=True)
class AblationResult:
    removed_stage: str | None
    trades: int
    expectancy_r: float | None
    profit_factor: float | None
    total_r: float
    expectancy_delta_vs_full_r: float | None


def run_leave_one_out_ablation(
    stage_ids: Sequence[str],
    evaluator: Callable[[frozenset[str]], Sequence[float]],
) -> tuple[AblationResult, ...]:
    """Evaluate full funnel and one-stage removals on DEVELOPMENT data only.

    evaluator receives the enabled stage-id set and returns net R outcomes. This
    module deliberately has no dataset loader so OOS access cannot be smuggled
    into the optimization primitive.
    """
    full_enabled = frozenset(stage_ids)
    full_rs = tuple(float(x) for x in evaluator(full_enabled))
    full = compute_performance(full_rs)
    results = [AblationResult(None, full.trades, full.expectancy_r, full.profit_factor, full.total_r, 0.0)]

    for removed in stage_ids:
        rs = tuple(float(x) for x in evaluator(full_enabled - {removed}))
        perf = compute_performance(rs)
        delta = None
        if perf.expectancy_r is not None and full.expectancy_r is not None:
            delta = perf.expectancy_r - full.expectancy_r
        results.append(AblationResult(removed, perf.trades, perf.expectancy_r, perf.profit_factor, perf.total_r, delta))
    return tuple(results)


def stage_value_map(results: Sequence[AblationResult]) -> Mapping[str, float | None]:
    """Positive value means removing the stage hurt expectancy, so it added value."""
    return {
        r.removed_stage: None if r.expectancy_delta_vs_full_r is None else -r.expectancy_delta_vs_full_r
        for r in results
        if r.removed_stage is not None
    }
