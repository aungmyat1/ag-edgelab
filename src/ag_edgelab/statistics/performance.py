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
        return PerformanceMetrics(0,0,0,None,None,None,0.0,0.0,0)
    wins=[r for r in values if r>0]; losses=[r for r in values if r<0]
    gp=sum(wins); gl=abs(sum(losses))
    pf=gp/gl if gl>0 else (math.inf if gp>0 else None)
    cumulative=peak=0.0; max_dd=0.0; run=max_run=0
    for r in values:
        cumulative += r; peak=max(peak,cumulative); max_dd=min(max_dd,cumulative-peak)
        if r<0: run += 1; max_run=max(max_run,run)
        else: run=0
    return PerformanceMetrics(len(values),len(wins),len(losses),len(wins)/len(values),
                              sum(values)/len(values),pf,sum(values),abs(max_dd),max_run)
