from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

from ag_edgelab.statistics.performance import compute_performance


@dataclass(frozen=True)
class MonteCarloSummary:
    simulations: int
    seed: int
    drawdown_p50_r: float | None
    drawdown_p95_r: float | None
    losing_streak_p95: float | None


def _quantile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered_values = sorted(values)
    position = (len(ordered_values) - 1) * quantile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered_values) - 1)
    fraction = position - lower_index
    return (
        ordered_values[lower_index] * (1 - fraction)
        + ordered_values[upper_index] * fraction
    )


def shuffle_risk_summary(
    trade_rs: Sequence[float], *, simulations: int = 2000, seed: int = 0
) -> MonteCarloSummary:
    trade_values = [float(trade_r) for trade_r in trade_rs]
    if simulations <= 0:
        raise ValueError("simulations must be positive")
    if not trade_values:
        return MonteCarloSummary(simulations, seed, None, None, None)

    random_generator = random.Random(seed)
    drawdown_values: list[float] = []
    losing_streak_values: list[float] = []
    for simulation_index in range(simulations):
        shuffled_values = trade_values[:]
        random_generator.shuffle(shuffled_values)
        metrics = compute_performance(shuffled_values)
        drawdown_values.append(metrics.max_drawdown_r)
        losing_streak_values.append(float(metrics.max_consecutive_losses))

    return MonteCarloSummary(
        simulations=simulations,
        seed=seed,
        drawdown_p50_r=_quantile(drawdown_values, 0.50),
        drawdown_p95_r=_quantile(drawdown_values, 0.95),
        losing_streak_p95=_quantile(losing_streak_values, 0.95),
    )