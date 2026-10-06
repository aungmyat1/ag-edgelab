"""Deterministic permanent null and power controls for the R3.1 gate."""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from ag_edgelab.optimization.eligibility_r3 import R3EligibilityPolicy, R3EligibilityVerdict
from ag_edgelab.optimization.eligibility_r3_1 import DirectionalOpportunity, evaluate_parent_r3_1

UTC = timezone.utc


@dataclass(frozen=True)
class R31ControlResults:
    subsample_null_result: str
    random_parent_replicates: int
    random_parent_pass_count: int
    random_parent_pass_rate: float
    planted_effect_r: float
    planted_signal_replicates: int
    planted_signal_pass_count: int
    planted_signal_estimated_power: float
    low_coverage_result: str
    certification: str


def _record(index: int, long_r: float | None, short_r: float | None, *,
            selected: bool = False, direction: str | None = None) -> DirectionalOpportunity:
    timestamp = datetime(2016, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    return DirectionalOpportunity(
        opportunity_id=f"CONTROL_{index:04d}", timestamp_utc=timestamp,
        symbol="EURUSD" if index % 2 == 0 else "GBPUSD", year=timestamp.year,
        session="CONTROL", long_outcome_r=long_r, short_outcome_r=short_r,
        parent_selected=selected, parent_direction=direction,
    )


def _base_universe(size: int, seed: int) -> list[DirectionalOpportunity]:
    rng = random.Random(seed)
    return [_record(i, rng.gauss(0, 1), rng.gauss(0, 1)) for i in range(size)]


def run_r3_1_controls(*, bootstrap_replicates: int = 300) -> R31ControlResults:
    """Run preregistered 200-null and 100-power deterministic controls."""
    universe_size, parent_n = 800, 294
    control_policy = R3EligibilityPolicy(
        min_reference_coverage=.90, min_parent_percentile=.95,
        min_parent_n=30, min_baseline_universe_n=100,
        n_bootstrap=bootstrap_replicates, rng_seed=913700,
    )
    base = _base_universe(universe_size, 44017)

    selected_null = set(random.Random(811).sample(range(universe_size), int(.9 * universe_size)))
    subsample_rows = [replace(row, parent_selected=i in selected_null,
                              parent_direction="LONG" if i in selected_null else None)
                      for i, row in enumerate(base)]
    subsample = evaluate_parent_r3_1(subsample_rows, policy=control_policy)

    random_replicates, random_passes = 200, 0
    for replicate in range(random_replicates):
        rng = random.Random(f"R3.1_RANDOM_RULE:{replicate}")
        selected = set(rng.sample(range(universe_size), parent_n))
        rows = [replace(row, parent_selected=i in selected,
                        parent_direction=(rng.choice(("LONG", "SHORT")) if i in selected else None))
                for i, row in enumerate(base)]
        policy = replace(control_policy, rng_seed=920000 + replicate)
        random_passes += evaluate_parent_r3_1(rows, policy=policy).verdict is R3EligibilityVerdict.PASS

    planted_effect, planted_replicates, planted_passes = .30, 100, 0
    for replicate in range(planted_replicates):
        rng = random.Random(f"R3.1_PLANTED_SIGNAL:{replicate}")
        raw = _base_universe(universe_size, 55000 + replicate)
        selected = set(rng.sample(range(universe_size), parent_n))
        rows = []
        for i, row in enumerate(raw):
            if i in selected:
                # Plant approximately +0.30R in a randomly declared direction;
                # the opposite leg remains untouched and the selected leg still
                # carries realistic unit-scale noise.
                direction = rng.choice(("LONG", "SHORT"))
                row = replace(
                    row,
                    long_outcome_r=(row.long_outcome_r + planted_effect if direction == "LONG" else row.long_outcome_r),
                    short_outcome_r=(row.short_outcome_r + planted_effect if direction == "SHORT" else row.short_outcome_r),
                    parent_selected=True,
                    parent_direction=direction,
                )
            rows.append(row)
        policy = replace(control_policy, rng_seed=930000 + replicate)
        planted_passes += evaluate_parent_r3_1(rows, policy=policy).verdict is R3EligibilityVerdict.PASS

    low_rows = [_record(i, 0.0 if i < 12 else None, 0.0 if i < 12 else None,
                        selected=i < 12, direction="LONG" if i < 12 else None)
                for i in range(100)]
    low = evaluate_parent_r3_1(low_rows, policy=control_policy)
    power = planted_passes / planted_replicates
    certified = (
        subsample.verdict is R3EligibilityVerdict.FAIL
        and random_passes <= 17
        and power >= .80
        and low.verdict is R3EligibilityVerdict.BLOCKED_INSUFFICIENT_REFERENCE_COVERAGE
    )
    return R31ControlResults(
        subsample_null_result=subsample.verdict.value,
        random_parent_replicates=random_replicates,
        random_parent_pass_count=random_passes,
        random_parent_pass_rate=random_passes / random_replicates,
        planted_effect_r=planted_effect,
        planted_signal_replicates=planted_replicates,
        planted_signal_pass_count=planted_passes,
        planted_signal_estimated_power=power,
        low_coverage_result=low.verdict.value,
        certification="PASS" if certified else "FAIL",
    )
