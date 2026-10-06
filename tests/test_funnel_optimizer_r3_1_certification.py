"""Permanent clustered-directional certification tests for R3.1."""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ag_edgelab.optimization.eligibility_r3 import R3EligibilityPolicy, R3EligibilityVerdict
from ag_edgelab.optimization.eligibility_r3_1 import (
    DirectionalOpportunity, evaluate_parent_r3_1, sample_opportunity_clusters,
)
from ag_edgelab.optimization.statistical_controls_r3_1 import run_r3_1_controls

UTC = timezone.utc
ROOT = Path(__file__).parents[1]
POLICY = R3EligibilityPolicy(n_bootstrap=200, rng_seed=3117)


def _row(index: int, long_r: float | None, short_r: float | None, *,
         selected: bool = False, direction: str | None = None) -> DirectionalOpportunity:
    timestamp = datetime(2016, 2, 1, tzinfo=UTC) + timedelta(hours=index)
    return DirectionalOpportunity(
        f"OPP_{index}", timestamp, "EURUSD", timestamp.year, "TEST",
        long_r, short_r, selected, direction,
    )


def test_parent_outcome_uses_declared_direction_not_symmetric_average():
    rows = [_row(i, 2.0, -1.0, selected=i < 30,
                 direction="LONG" if i < 30 else None) for i in range(100)]
    result = evaluate_parent_r3_1(rows, policy=POLICY)
    assert result.parent_outcome_uses_declared_direction is True
    assert result.parent_expectancy_r == 2.0
    assert result.baseline_mean_r == 0.5


def test_short_parent_uses_short_leg():
    rows = [_row(i, 2.0, -1.0, selected=i < 30,
                 direction="SHORT" if i < 30 else None) for i in range(100)]
    assert evaluate_parent_r3_1(rows, policy=POLICY).parent_expectancy_r == -1.0


def test_directional_legs_are_stored_separately_in_one_cluster():
    row = _row(0, 2.0, -1.0)
    assert row.long_outcome_r == 2.0
    assert row.short_outcome_r == -1.0
    assert not hasattr(row, "symmetric_outcome_r")


def test_cluster_sampler_can_only_sample_whole_opportunities():
    rows = [_row(i, float(i), -float(i)) for i in range(5)]
    sample = sample_opportunity_clusters(rows, rng=random.Random(9), count=50)
    assert all(isinstance(cluster, DirectionalOpportunity) for cluster in sample)
    assert all(cluster.long_outcome_r == -cluster.short_outcome_r for cluster in sample)


def test_cluster_bootstrap_counts_two_legs_per_evaluable_opportunity():
    rows = [_row(i, random.Random(i).gauss(0, 1), random.Random(i + 100).gauss(0, 1),
                 selected=i < 30, direction="LONG" if i < 30 else None)
            for i in range(120)]
    result = evaluate_parent_r3_1(rows, policy=POLICY)
    assert result.bootstrap_method == "CLUSTER_BOOTSTRAP"
    assert result.bootstrap_cluster_unit == "OPPORTUNITY"
    assert result.n_baseline_direction_legs == 2 * result.n_baseline_opportunities


def test_coverage_gate_still_fails_closed_with_directional_legs():
    rows = [_row(i, 0.0 if i < 12 else None, 0.0 if i < 12 else None,
                 selected=i < 12, direction="LONG" if i < 12 else None)
            for i in range(100)]
    result = evaluate_parent_r3_1(rows, policy=POLICY)
    assert result.verdict is R3EligibilityVerdict.BLOCKED_INSUFFICIENT_REFERENCE_COVERAGE


def test_permanent_200_random_null_and_planted_power_certification():
    controls = run_r3_1_controls(bootstrap_replicates=80)
    assert controls.random_parent_replicates == 200
    assert controls.random_parent_pass_count <= 17
    assert controls.planted_signal_replicates == 100
    assert controls.planted_signal_estimated_power >= .80
    assert controls.subsample_null_result == "FAIL"
    assert controls.low_coverage_result == "BLOCKED_INSUFFICIENT_REFERENCE_COVERAGE"
    assert controls.certification == "PASS"


def test_r3_1_evidence_preserves_lineage_and_stops_on_unexpected_parent_pass():
    path = ROOT / "artifacts/funnel_optimizer_v1_r3_1_statistical_certification/acceptance_evidence.json"
    evidence = json.loads(path.read_text())
    assert evidence["lineage"]["original_pr23_head"] == "458b8fb13b21134ce26c247759e3544454fb712b"
    assert evidence["lineage"]["R3_original_gate_status"] == "PARTIAL_PROVISIONAL_NOT_CERTIFIED"
    assert evidence["lineage"]["supersedes"] == "R3 eligibility statistical certification only"
    assert evidence["r3_1_eligibility"]["verdict"] == "PASS"
    assert evidence["certification"]["unexpected_ald_v2_pass"] is True
    assert evidence["certification"]["r3_gate_trustworthy"] is False
    assert evidence["certification"]["real_campaign_authorized"] is False


def test_persisted_directional_table_has_two_legs_and_declared_parent_outcomes():
    path = ROOT / "artifacts/funnel_optimizer_v1_r3_1_statistical_certification/directional_reference_legs.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 2656
    selected = [row for row in rows if row["parent_selected"]]
    assert len(selected) == 294
    for row in rows:
        assert "REFERENCE_LEG_LONG" in row and "REFERENCE_LEG_SHORT" in row
    for row in selected:
        key = "REFERENCE_LEG_LONG" if row["parent_direction"] == "LONG" else "REFERENCE_LEG_SHORT"
        assert row["parent_outcome_r"] == row[key]
