"""R3.1 clustered directional statistical certification.

This module supersedes only the statistical interpretation of the historical
R3 artifact.  It keeps long and short reference legs attached to one opportunity
cluster and evaluates selected parents in their declared direction.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, median
from typing import Mapping, Sequence

from ag_edgelab.optimization.eligibility_r3 import R3EligibilityPolicy, R3EligibilityVerdict

UTC = timezone.utc


@dataclass(frozen=True)
class DirectionalOpportunity:
    opportunity_id: str
    timestamp_utc: datetime
    symbol: str
    year: int
    session: str
    long_outcome_r: float | None
    short_outcome_r: float | None
    parent_selected: bool = False
    parent_direction: str | None = None

    def __post_init__(self) -> None:
        if not all((self.opportunity_id, self.symbol, self.session)):
            raise ValueError("opportunity cluster identity fields are required")
        if self.timestamp_utc.tzinfo is None or self.timestamp_utc.utcoffset() != timezone.utc.utcoffset(self.timestamp_utc):
            raise ValueError("timestamp_utc must be aware UTC")
        if self.year != self.timestamp_utc.year:
            raise ValueError("year must match opportunity timestamp")
        for value in (self.long_outcome_r, self.short_outcome_r):
            if value is not None and not math.isfinite(float(value)):
                raise ValueError("directional outcomes must be finite")
        if self.parent_selected and self.parent_direction not in {"LONG", "SHORT"}:
            raise ValueError("selected parent opportunity requires LONG or SHORT direction")
        if not self.parent_selected and self.parent_direction is not None:
            raise ValueError("unselected opportunity cannot claim a parent direction")

    @property
    def both_legs_evaluable(self) -> bool:
        return self.long_outcome_r is not None and self.short_outcome_r is not None

    @property
    def parent_outcome_r(self) -> float | None:
        if not self.parent_selected:
            return None
        return self.long_outcome_r if self.parent_direction == "LONG" else self.short_outcome_r

    @property
    def trading_day(self) -> str:
        return self.timestamp_utc.astimezone(UTC).date().isoformat()


@dataclass(frozen=True)
class R31EligibilityResult:
    verdict: R3EligibilityVerdict
    reason_code: str
    reference_coverage: float
    total_eligible_opportunities: int
    evaluable_reference_opportunities: int
    n_baseline_opportunities: int
    n_baseline_direction_legs: int
    n_parent: int
    baseline_universe_not_subset_of_parent: bool
    parent_outcome_uses_declared_direction: bool
    direction_legs_stored_separately: bool
    bootstrap_method: str
    bootstrap_cluster_unit: str
    bootstrap_replicates: int
    bootstrap_seed: int
    parent_expectancy_r: float | None
    baseline_mean_r: float | None
    baseline_median_r: float | None
    baseline_ci95_low_r: float | None
    baseline_ci95_high_r: float | None
    parent_percentile: float | None
    selection_delta_r: float | None
    delta_cluster_ci95_low_r: float | None
    delta_cluster_ci95_high_r: float | None
    stratum_diagnostics: Mapping[str, Mapping[str, float | int]]


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    point = (len(ordered) - 1) * probability
    lo, hi = math.floor(point), math.ceil(point)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (point - lo)


def sample_opportunity_clusters(
    population: Sequence[DirectionalOpportunity], *, rng: random.Random, count: int,
) -> tuple[DirectionalOpportunity, ...]:
    """Sample whole opportunity records; directional legs are never sampled."""
    if not population or count <= 0:
        raise ValueError("cluster sample requires a population and positive count")
    return tuple(rng.choice(population) for _ in range(count))


def _baseline_statistic(clusters: Sequence[DirectionalOpportunity]) -> float:
    # Every sampled cluster contributes exactly its long and short leg.  The
    # implementation intentionally does not expose either leg as a sampling
    # unit even though the final statistic is the arithmetic mean of all legs.
    legs = [leg for cluster in clusters
            for leg in (cluster.long_outcome_r, cluster.short_outcome_r)]
    if any(leg is None for leg in legs):
        raise ValueError("baseline statistic requires both legs per cluster")
    return mean(float(leg) for leg in legs)


def _strata(records: Sequence[DirectionalOpportunity]) -> dict[str, dict[str, float | int]]:
    groups: dict[str, list[DirectionalOpportunity]] = {}
    for record in records:
        groups.setdefault(record.symbol, []).append(record)
        groups.setdefault(f"{record.symbol}_{record.year}", []).append(record)
    out: dict[str, dict[str, float | int]] = {}
    for name, group in sorted(groups.items()):
        legs = [float(leg) for row in group for leg in (row.long_outcome_r, row.short_outcome_r)]
        out[name] = {
            "n_opportunities": len(group),
            "n_direction_legs": len(legs),
            "baseline_mean_r": mean(legs),
            "baseline_median_r": median(legs),
        }
    return out


def evaluate_parent_r3_1(
    opportunities: Sequence[DirectionalOpportunity],
    *,
    policy: R3EligibilityPolicy = R3EligibilityPolicy(),
) -> R31EligibilityResult:
    """Evaluate directional parent value with opportunity-cluster bootstrap."""
    if not opportunities:
        raise ValueError("eligibility requires opportunities")
    if len({row.opportunity_id for row in opportunities}) != len(opportunities):
        raise ValueError("opportunity cluster ids must be unique")
    baseline = [row for row in opportunities if row.both_legs_evaluable]
    parent_records = [row for row in baseline if row.parent_selected and row.parent_outcome_r is not None]
    coverage = len(baseline) / len(opportunities)
    parent_values = [float(row.parent_outcome_r) for row in parent_records]  # type: ignore[arg-type]
    baseline_legs = [float(leg) for row in baseline for leg in (row.long_outcome_r, row.short_outcome_r)]
    not_subset = bool({row.opportunity_id for row in baseline} - {row.opportunity_id for row in parent_records})

    metrics: dict[str, float | None] = {
        "parent_expectancy_r": mean(parent_values) if parent_values else None,
        "baseline_mean_r": mean(baseline_legs) if baseline_legs else None,
        "baseline_median_r": median(baseline_legs) if baseline_legs else None,
        "baseline_ci95_low_r": None,
        "baseline_ci95_high_r": None,
        "parent_percentile": None,
        "selection_delta_r": None,
        "delta_cluster_ci95_low_r": None,
        "delta_cluster_ci95_high_r": None,
    }

    def finish(verdict: R3EligibilityVerdict, reason: str) -> R31EligibilityResult:
        return R31EligibilityResult(
            verdict=verdict,
            reason_code=reason,
            reference_coverage=coverage,
            total_eligible_opportunities=len(opportunities),
            evaluable_reference_opportunities=len(baseline),
            n_baseline_opportunities=len(baseline),
            n_baseline_direction_legs=len(baseline_legs),
            n_parent=len(parent_records),
            baseline_universe_not_subset_of_parent=not_subset,
            parent_outcome_uses_declared_direction=True,
            direction_legs_stored_separately=True,
            bootstrap_method="CLUSTER_BOOTSTRAP",
            bootstrap_cluster_unit="OPPORTUNITY",
            bootstrap_replicates=policy.n_bootstrap,
            bootstrap_seed=policy.rng_seed,
            stratum_diagnostics=_strata(baseline) if baseline else {},
            **metrics,
        )

    if coverage < policy.min_reference_coverage:
        return finish(R3EligibilityVerdict.BLOCKED_INSUFFICIENT_REFERENCE_COVERAGE,
                      "REFERENCE_COVERAGE_BELOW_PROPOSED_OWNER_POLICY")
    if len(parent_records) < policy.min_parent_n or len(baseline) < policy.min_baseline_universe_n:
        return finish(R3EligibilityVerdict.BLOCKED_MINIMUM_SAMPLE,
                      "MINIMUM_EFFECTIVE_SAMPLE_NOT_MET")
    if not not_subset:
        return finish(R3EligibilityVerdict.FAIL, "BASELINE_UNIVERSE_SELF_COMPARISON")

    parent_mean = mean(parent_values)
    baseline_mean = mean(baseline_legs)
    metrics["selection_delta_r"] = parent_mean - baseline_mean
    rng = random.Random(policy.rng_seed)
    null_means: list[float] = []
    baseline_means: list[float] = []
    deltas: list[float] = []
    for _ in range(policy.n_bootstrap):
        null_clusters = sample_opportunity_clusters(baseline, rng=rng, count=len(parent_records))
        null_means.append(_baseline_statistic(null_clusters))
        baseline_clusters = sample_opportunity_clusters(baseline, rng=rng, count=len(baseline))
        boot_baseline = _baseline_statistic(baseline_clusters)
        parent_clusters = sample_opportunity_clusters(parent_records, rng=rng, count=len(parent_records))
        boot_parent = mean(float(row.parent_outcome_r) for row in parent_clusters)  # type: ignore[arg-type]
        baseline_means.append(boot_baseline)
        deltas.append(boot_parent - boot_baseline)
    metrics["baseline_ci95_low_r"] = _quantile(baseline_means, .025)
    metrics["baseline_ci95_high_r"] = _quantile(baseline_means, .975)
    metrics["parent_percentile"] = sum(value <= parent_mean for value in null_means) / len(null_means)
    metrics["delta_cluster_ci95_low_r"] = _quantile(deltas, .025)
    metrics["delta_cluster_ci95_high_r"] = _quantile(deltas, .975)
    passes = (metrics["parent_percentile"] >= policy.min_parent_percentile and
              metrics["delta_cluster_ci95_low_r"] > 0)
    return finish(
        R3EligibilityVerdict.PASS if passes else R3EligibilityVerdict.FAIL,
        "R3_1_CLUSTERED_DIRECTIONAL_CERTIFICATION_PASS" if passes
        else "R3_1_CLUSTERED_DIRECTIONAL_REQUIREMENTS_NOT_MET",
    )
