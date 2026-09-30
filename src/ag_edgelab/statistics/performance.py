from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class PerformanceMetrics:
    trades: int
    wins: int
    losses: int
    win_rate: float | None
    expectancy_r: float | None
    profit_factor: float | None
    total_r: float
    max_drawdown_r: float
    max_consecutive_losses: int


def compute_performance(trade_rs: Sequence[float]) -> PerformanceMetrics:
    values = [float(x) for x in trade_rs]
    if not values:
        return PerformanceMetrics(0, 0, 0, None, None, None, 0.0, 0.0, 0)

    wins = [r for r in values if r > 0]
    losses = [r for r in values if r < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else (math.inf if gross_profit > 0 else None)

    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    losing_run = 0
    max_losing_run = 0
    for r in values:
        cumulative += r
        peak = max(peak, cumulative)
        max_dd = min(max_dd, cumulative - peak)
        if r < 0:
            losing_run += 1
            max_losing_run = max(max_losing_run, losing_run)
        else:
            losing_run = 0

    return PerformanceMetrics(
        trades=len(values), wins=len(wins), losses=len(losses), win_rate=len(wins) / len(values),
        expectancy_r=sum(values) / len(values), profit_factor=pf, total_r=sum(values),
        max_drawdown_r=abs(max_dd), max_consecutive_losses=max_losing_run,
    )
