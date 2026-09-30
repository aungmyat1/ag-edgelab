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


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    frac = pos - lo
    return values[lo] * (1 - frac) + values[hi] * frac


def shuffle_risk_summary(trade_rs: Sequence[float], *, simulations: int = 2000, seed: int = 0) -> MonteCarloSummary:
    values = [float(x) for x in trade_rs]
    if simulations <= 0:
        raise ValueError("simulations must be positive")
    if not values:
        return MonteCarloSummary(simulations, seed, None, None, None)

    rng = random.Random(seed)
    dds: list[float] = []
    streaks: list[float] = []
    for _ in range(simulations):
        sample = values[:]
        rng.shuffle(sample)
        metrics = compute_performance(sample)
        dds.append(metrics.max_drawdown_r)
        streaks.append(float(metrics.max_consecutive_losses))

    return MonteCarloSummary(
        simulations=simulations,
        seed=seed,
        drawdown_p50_r=_quantile(dds, 0.50),
        drawdown_p95_r=_quantile(dds, 0.95),
        losing_streak_p95=_quantile(streaks, 0.95),
    )
