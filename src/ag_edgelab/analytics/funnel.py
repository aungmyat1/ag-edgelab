from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from ag_edgelab.contracts.funnel import FunnelStage
from ag_edgelab.ledger.candidate import CandidateRecord


@dataclass(frozen=True)
class FunnelStat:
    stage: str
    candidates: int
    retained_pct: float
    wins: int
    win_rate: float | None
    win_ci95_low: float | None
    win_ci95_high: float | None
    expectancy_r: float | None
    profit_factor: float | None
    win_rate_lift_pp: float | None
    expectancy_lift_r: float | None


def _wilson(wins: int, n: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def _economic(rs: Sequence[float]) -> tuple[float | None, float | None]:
    if not rs:
        return None, None
    expectancy = sum(rs) / len(rs)
    gains = sum(r for r in rs if r > 0)
    losses = abs(sum(r for r in rs if r < 0))
    pf = gains / losses if losses > 0 else (math.inf if gains > 0 else None)
    return expectancy, pf


def compute_funnel_stats(records: Sequence[CandidateRecord], outcomes_r: Mapping[str, float]) -> tuple[FunnelStat, ...]:
    stages = [
        FunnelStage.CONTEXT, FunnelStage.LOCATION, FunnelStage.TRIGGER,
        FunnelStage.GEOMETRY, FunnelStage.EXECUTION,
    ]
    prior_count = len(records)
    prior_wr = None
    prior_exp = None
    output: list[FunnelStat] = []

    for stage in stages:
        eligible: list[CandidateRecord] = []
        for record in records:
            result = next((x for x in record.stage_results if x.stage == stage), None)
            if result is not None and result.passed:
                eligible.append(record)

        values = [float(outcomes_r[r.candidate_id]) for r in eligible if r.candidate_id in outcomes_r]
        wins = sum(1 for value in values if value > 0)
        wr = wins / len(values) if values else None
        low, high = _wilson(wins, len(values))
        exp, pf = _economic(values)
        retained = (len(eligible) / prior_count * 100.0) if prior_count else 0.0
        output.append(FunnelStat(
            stage=stage.value, candidates=len(eligible), retained_pct=retained, wins=wins,
            win_rate=wr, win_ci95_low=low, win_ci95_high=high,
            expectancy_r=exp, profit_factor=pf,
            win_rate_lift_pp=None if wr is None or prior_wr is None else (wr - prior_wr) * 100.0,
            expectancy_lift_r=None if exp is None or prior_exp is None else exp - prior_exp,
        ))
        prior_count = len(eligible)
        if wr is not None:
            prior_wr = wr
        if exp is not None:
            prior_exp = exp

    return tuple(output)
