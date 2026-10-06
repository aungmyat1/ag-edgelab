"""Adversarial directional-null tools for the R3.2 causality audit."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from statistics import mean, median, stdev
from typing import Sequence

from ag_edgelab.optimization.eligibility_r3_1 import DirectionalOpportunity


def m15_direction_available_time(event_bar_open_time: datetime) -> datetime:
    """ALD V2 S4 consumes the interaction M15 close, not its open."""
    if event_bar_open_time.tzinfo is None:
        raise ValueError("event time must be timezone aware")
    return event_bar_open_time + timedelta(minutes=15)


def assert_causal_reference_entry(direction_available_time: datetime,
                                  reference_entry_time: datetime) -> None:
    if reference_entry_time < direction_available_time:
        raise ValueError("reference entry precedes direction availability")


class DirectionalNullMode(StrEnum):
    OLD_SYMMETRIC_TWO_LEG_AVERAGE = "OLD_SYMMETRIC_TWO_LEG_AVERAGE"
    RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY = "RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY"
    MATCHED_DIRECTION_FREQUENCY_NULL = "MATCHED_DIRECTION_FREQUENCY_NULL"


@dataclass(frozen=True)
class NullSummary:
    mode: DirectionalNullMode
    mean_r: float
    sd_r: float
    ci95_low_r: float
    ci95_high_r: float
    parent_percentile: float


@dataclass(frozen=True)
class DirectionalExperimentResult:
    n: int
    reference_coverage: float
    parent_expectancy_r: float
    null_mean_r: float
    parent_percentile: float
    selection_delta_r: float
    delta_cluster_ci95_low_r: float
    delta_cluster_ci95_high_r: float
    verdict: str
    null_summaries: tuple[NullSummary, ...]


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    point = (len(ordered) - 1) * probability
    lo, hi = math.floor(point), math.ceil(point)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (point - lo)


def _leg(row: DirectionalOpportunity, direction: str) -> float:
    value = row.long_outcome_r if direction == "LONG" else row.short_outcome_r
    if value is None:
        raise ValueError("directional null requires evaluable legs")
    return float(value)


def directional_null_draw(
    population: Sequence[DirectionalOpportunity], *, sample_n: int,
    long_count: int, mode: DirectionalNullMode, rng: random.Random,
) -> tuple[float, tuple[tuple[str, str], ...]]:
    """Draw opportunity clusters and return the exact leg membership audit."""
    if sample_n <= 0 or not population or not 0 <= long_count <= sample_n:
        raise ValueError("invalid directional null sample")
    sampled = [rng.choice(population) for _ in range(sample_n)]
    membership: list[tuple[str, str]] = []
    values: list[float] = []
    if mode is DirectionalNullMode.OLD_SYMMETRIC_TWO_LEG_AVERAGE:
        for row in sampled:
            values.extend((_leg(row, "LONG"), _leg(row, "SHORT")))
            membership.extend(((row.opportunity_id, "LONG"), (row.opportunity_id, "SHORT")))
    else:
        if mode is DirectionalNullMode.RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY:
            directions = ["LONG" if rng.getrandbits(1) else "SHORT" for _ in sampled]
        else:
            directions = ["LONG"] * long_count + ["SHORT"] * (sample_n - long_count)
            rng.shuffle(directions)
        for row, direction in zip(sampled, directions, strict=True):
            values.append(_leg(row, direction))
            membership.append((row.opportunity_id, direction))
    return mean(values), tuple(membership)


def _distribution(population: Sequence[DirectionalOpportunity], *, sample_n: int,
                  long_count: int, mode: DirectionalNullMode,
                  replicates: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    return [directional_null_draw(population, sample_n=sample_n, long_count=long_count,
                                  mode=mode, rng=rng)[0]
            for _ in range(replicates)]


def evaluate_directional_experiment(
    records: Sequence[DirectionalOpportunity], *, replicates: int, seed: int,
    min_percentile: float = .95,
) -> DirectionalExperimentResult:
    baseline = [row for row in records if row.both_legs_evaluable]
    parent = [row for row in baseline if row.parent_selected and row.parent_outcome_r is not None]
    if not parent or not baseline:
        raise ValueError("experiment requires baseline and parent records")
    parent_values = [float(row.parent_outcome_r) for row in parent]  # type: ignore[arg-type]
    parent_mean = mean(parent_values)
    long_count = sum(row.parent_direction == "LONG" for row in parent)
    summaries: list[NullSummary] = []
    distributions: dict[DirectionalNullMode, list[float]] = {}
    for offset, mode in enumerate(DirectionalNullMode):
        values = _distribution(baseline, sample_n=len(parent), long_count=long_count,
                               mode=mode, replicates=replicates, seed=seed + offset * 100003)
        distributions[mode] = values
        summaries.append(NullSummary(
            mode, mean(values), stdev(values), _quantile(values, .025), _quantile(values, .975),
            sum(value <= parent_mean for value in values) / len(values),
        ))

    # Primary R3.2 null: one deterministic random direction per sampled
    # opportunity. Full-universe cluster draws estimate baseline uncertainty;
    # parent clusters are separately sampled for the delta CI.
    rng = random.Random(seed + 700009)
    delta_draws: list[float] = []
    full_baseline_draws: list[float] = []
    for _ in range(replicates):
        boot_parent = mean(rng.choice(parent_values) for _ in parent_values)
        boot_baseline, membership = directional_null_draw(
            baseline, sample_n=len(baseline), long_count=len(baseline) // 2,
            mode=DirectionalNullMode.RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY, rng=rng)
        if len(membership) != len(baseline):
            raise AssertionError("one-leg null violated opportunity clustering")
        full_baseline_draws.append(boot_baseline)
        delta_draws.append(boot_parent - boot_baseline)
    primary = next(item for item in summaries
                   if item.mode is DirectionalNullMode.RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY)
    delta_low, delta_high = _quantile(delta_draws, .025), _quantile(delta_draws, .975)
    passes = primary.parent_percentile >= min_percentile and delta_low > 0
    return DirectionalExperimentResult(
        n=len(parent),
        reference_coverage=len(baseline) / len(records),
        parent_expectancy_r=parent_mean,
        null_mean_r=mean(full_baseline_draws),
        parent_percentile=primary.parent_percentile,
        selection_delta_r=parent_mean - mean(full_baseline_draws),
        delta_cluster_ci95_low_r=delta_low,
        delta_cluster_ci95_high_r=delta_high,
        verdict="PASS" if passes else "FAIL",
        null_summaries=tuple(summaries),
    )


def median_value(values: Sequence[float]) -> float:
    return median(values)
