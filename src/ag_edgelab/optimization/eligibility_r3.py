"""Fail-closed Funnel Optimizer R3 parent eligibility.

R3 deliberately lives beside the historical V1/R2 evaluator.  R2 evidence and
its weak ``delta > 0`` rule remain reproducible; this module is the superseding
DEV-only authority.  It has no data loader, broker, OOS, holdout, or child
optimization capability.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import StrEnum
from statistics import mean, median
from typing import Sequence


class R3EligibilityVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED_INSUFFICIENT_REFERENCE_COVERAGE = "BLOCKED_INSUFFICIENT_REFERENCE_COVERAGE"
    BLOCKED_MINIMUM_SAMPLE = "BLOCKED_MINIMUM_SAMPLE"


@dataclass(frozen=True)
class R3EligibilityPolicy:
    """Proposed owner policy; use does not imply owner authorization."""

    min_reference_coverage: float = 0.90
    min_parent_percentile: float = 0.95
    min_parent_n: int = 30
    min_baseline_universe_n: int = 100
    n_bootstrap: int = 2000
    rng_seed: int = 0xF03A2026
    policy_status: str = "PROPOSED_OWNER_POLICY"

    def __post_init__(self) -> None:
        if not 0 < self.min_reference_coverage <= 1:
            raise ValueError("min_reference_coverage must be in (0, 1]")
        if not 0 < self.min_parent_percentile <= 1:
            raise ValueError("min_parent_percentile must be in (0, 1]")
        if min(self.min_parent_n, self.min_baseline_universe_n, self.n_bootstrap) <= 0:
            raise ValueError("sample and bootstrap counts must be positive")
        if self.rng_seed < 0:
            raise ValueError("rng_seed must be non-negative")


@dataclass(frozen=True)
class R3EligibilityResult:
    verdict: R3EligibilityVerdict
    reason_code: str
    reference_coverage: float
    total_eligible_opportunities: int
    evaluable_reference_opportunities: int
    n_parent: int
    n_baseline_universe: int
    baseline_universe_not_subset_of_parent: bool
    parent_expectancy_r: float | None
    baseline_mean_r: float | None
    baseline_median_r: float | None
    baseline_ci95_low_r: float | None
    baseline_ci95_high_r: float | None
    parent_percentile: float | None
    selection_delta_r: float | None
    delta_bootstrap_ci95_low_r: float | None
    delta_bootstrap_ci95_high_r: float | None
    n_bootstrap: int
    rng_seed: int


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    point = (len(ordered) - 1) * probability
    lo, hi = math.floor(point), math.ceil(point)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (point - lo)


def evaluate_parent_r3(
    outcomes_r: Sequence[float | None],
    parent_selected: Sequence[bool],
    *,
    policy: R3EligibilityPolicy = R3EligibilityPolicy(),
) -> R3EligibilityResult:
    """Evaluate a parent against the full opportunity universe.

    ``outcomes_r`` contains one strategy-independent reference outcome per DEV
    opportunity.  The baseline universe is every evaluable item, never a
    resample constructed from the parent's selected rows.  Sampling is used
    only to estimate the parent-size null distribution and confidence bounds.
    """
    if len(outcomes_r) != len(parent_selected):
        raise ValueError("outcomes and parent selection must have equal length")
    if not outcomes_r:
        raise ValueError("eligibility requires at least one opportunity")
    for value in outcomes_r:
        if value is not None and not math.isfinite(float(value)):
            raise ValueError("reference outcomes must be finite")

    evaluable_indices = [i for i, value in enumerate(outcomes_r) if value is not None]
    parent_indices = [i for i in evaluable_indices if parent_selected[i]]
    universe = [float(outcomes_r[i]) for i in evaluable_indices]  # type: ignore[arg-type]
    parent = [float(outcomes_r[i]) for i in parent_indices]  # type: ignore[arg-type]
    coverage = len(evaluable_indices) / len(outcomes_r)
    universe_not_subset = bool(set(evaluable_indices) - set(parent_indices))

    def result(verdict: R3EligibilityVerdict, reason: str, **metrics: object) -> R3EligibilityResult:
        defaults: dict[str, object] = {
            "parent_expectancy_r": mean(parent) if parent else None,
            "baseline_mean_r": mean(universe) if universe else None,
            "baseline_median_r": median(universe) if universe else None,
            "baseline_ci95_low_r": None,
            "baseline_ci95_high_r": None,
            "parent_percentile": None,
            "selection_delta_r": None,
            "delta_bootstrap_ci95_low_r": None,
            "delta_bootstrap_ci95_high_r": None,
        }
        defaults.update(metrics)
        return R3EligibilityResult(
            verdict, reason, coverage, len(outcomes_r), len(evaluable_indices),
            len(parent), len(universe), universe_not_subset,
            defaults["parent_expectancy_r"], defaults["baseline_mean_r"],
            defaults["baseline_median_r"], defaults["baseline_ci95_low_r"],
            defaults["baseline_ci95_high_r"], defaults["parent_percentile"],
            defaults["selection_delta_r"], defaults["delta_bootstrap_ci95_low_r"],
            defaults["delta_bootstrap_ci95_high_r"], policy.n_bootstrap, policy.rng_seed,
        )  # type: ignore[arg-type]

    # Coverage is checked before statistical eligibility.  A 12% fixture can
    # never reach PASS/ELIGIBLE/PROMOTE regardless of its observed expectancy.
    if coverage < policy.min_reference_coverage:
        return result(R3EligibilityVerdict.BLOCKED_INSUFFICIENT_REFERENCE_COVERAGE,
                      "REFERENCE_COVERAGE_BELOW_PROPOSED_OWNER_POLICY")
    if len(parent) < policy.min_parent_n or len(universe) < policy.min_baseline_universe_n:
        return result(R3EligibilityVerdict.BLOCKED_MINIMUM_SAMPLE,
                      "MINIMUM_EFFECTIVE_SAMPLE_NOT_MET")
    if not universe_not_subset:
        return result(R3EligibilityVerdict.FAIL, "BASELINE_UNIVERSE_SELF_COMPARISON")

    parent_mean, baseline_mean = mean(parent), mean(universe)
    delta = parent_mean - baseline_mean
    rng = random.Random(policy.rng_seed)
    null_means: list[float] = []
    baseline_means: list[float] = []
    deltas: list[float] = []
    # Parent-size draws from the full universe estimate the null percentile.
    # Independent with-replacement bootstrap streams estimate uncertainty in
    # parent-minus-universe and the gross universe mean.
    for _ in range(policy.n_bootstrap):
        null_means.append(mean(rng.choices(universe, k=len(parent))))
        boot_baseline = rng.choices(universe, k=len(universe))
        baseline_means.append(mean(boot_baseline))
        deltas.append(mean(rng.choices(parent, k=len(parent))) - mean(boot_baseline))
    percentile = sum(value <= parent_mean for value in null_means) / len(null_means)
    baseline_low, baseline_high = _quantile(baseline_means, .025), _quantile(baseline_means, .975)
    delta_low, delta_high = _quantile(deltas, .025), _quantile(deltas, .975)
    passes = percentile >= policy.min_parent_percentile and delta_low > 0
    return result(
        R3EligibilityVerdict.PASS if passes else R3EligibilityVerdict.FAIL,
        "R3_COVERAGE_PERCENTILE_POSITIVE_CI" if passes else "R3_STATISTICAL_REQUIREMENTS_NOT_MET",
        baseline_ci95_low_r=baseline_low,
        baseline_ci95_high_r=baseline_high,
        parent_percentile=percentile,
        selection_delta_r=delta,
        delta_bootstrap_ci95_low_r=delta_low,
        delta_bootstrap_ci95_high_r=delta_high,
    )
