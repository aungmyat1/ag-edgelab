"""Acceptance contracts for the development-only Funnel Optimizer V1 slice."""

from __future__ import annotations

from pathlib import Path

import pytest

from ag_edgelab.contracts.dataset import DatasetRole
from ag_edgelab.data.fingerprint import sha256_file
from ag_edgelab.optimization.fx_fixture import (FixtureDataReceipt, FixtureDataStatus,
                                                FixtureFile)
from ag_edgelab.optimization.funnel_optimizer import (
    AblationStatus, CampaignLedger, ChildStatus, EconomicRankingStatus,
    EligibilityVerdict, FastChildEngine, Opportunity, RandomBaselineConfig, RelaxedReplay,
    RuleState, boolean_rule, leave_one_out, rank_child, reference_metrics,
    selected_parent_rows, stage_diagnostics, structural_parent_eligibility)
from ag_edgelab.strategies.asian_liquidity_displacement_v2 import V2Unit
from ag_edgelab.strategies.asian_liquidity_displacement_v2_relaxed import (
    V2_RELAXED_ENGINE_ID, opportunity_from_v2_unit, v2_relaxed_rules)
from ag_edgelab.optimization.governance import OptimizationGovernanceError
from tests.funnel_optimizer_fixtures import (build_fixture_table, fixture_opportunities,
                                             fixture_rules)


FROZEN_ALD_V2_SHA256 = "883e9095977cd25840201f5b2b3d5ce6e67b350c1157f30045654dbd13904920"


def _body_diagnostic(table):
    return next(item for item in stage_diagnostics(table) if item.rule_id == "BODY_RATIO")


def test_relaxed_replay_keeps_reference_outcomes_for_pass_and_fail_cells():
    table = build_fixture_table()
    body = _body_diagnostic(table)

    # The PASS and FAIL populations both use reference outcomes.  Actual trade
    # outcomes are deliberately not used to calculate this selection delta.
    assert body.n_pass == 4
    assert body.n_fail == 2
    assert body.pass_expectancy_r == pytest.approx(-0.85)
    assert body.fail_expectancy_r == pytest.approx(0.8)
    assert body.selection_delta_r == pytest.approx(-1.65)

    failed_body_rows = [row for row in table.rows
                        if row.rule_cells["BODY_RATIO"].state is RuleState.FAIL]
    assert all(row.reference_outcome_r == pytest.approx(0.8) for row in failed_body_rows)
    assert all(not row.actual_trade and row.actual_outcome_r is None for row in failed_body_rows)


def test_tri_state_and_actual_reference_models_remain_separate():
    table = build_fixture_table()
    states = [row.rule_cells["BODY_RATIO"].state for row in table.rows]
    assert RuleState.PASS in states
    assert RuleState.FAIL in states
    assert RuleState.NOT_EVALUABLE in states

    first_parent = next(row for row in table.rows if row.event_id == "SYN-EURUSD-00")
    assert first_parent.actual_trade is True
    assert first_parent.reference_outcome_r == -1.0
    assert first_parent.actual_outcome_r == -0.2
    # A rejected counterfactual may have a reference result but never becomes a
    # fabricated actual trade.
    rejected = next(row for row in table.rows if row.event_id == "SYN-EURUSD-01")
    assert rejected.reference_outcome_r == 0.8
    assert rejected.actual_trade is False
    assert rejected.actual_outcome_r is None


def test_event_table_order_and_hash_are_deterministic_and_cacheable(tmp_path):
    first = build_fixture_table()
    second = RelaxedReplay(fixture_rules(), engine_id="FUNNEL_OPTIMIZER_RELAXED_V1").evaluate(
        fixture_opportunities(), dataset_role=DatasetRole.DEVELOPMENT)
    assert [row.event_id for row in first.rows] == sorted(
        (row.event_id for row in first.rows),
        key=lambda event_id: next(row.sequence_no for row in first.rows if row.event_id == event_id),
    )
    assert first.sha256 == second.sha256
    cache, manifest = first.write_cache(tmp_path / "events.jsonl")
    assert cache.read_text().count("\n") == len(first.rows)
    assert first.sha256 in manifest.read_text()


def test_valid_ablation_reconciles_with_full_replay_fixture_and_structural_fails_closed():
    table = build_fixture_table()
    ablations = {result.rule_id: result for result in leave_one_out(table)}

    body = ablations["BODY_RATIO"]
    assert body.status is AblationStatus.VALID
    assert body.full_parent.reference_expectancy_r == pytest.approx(-0.85)
    assert body.without_rule is not None
    # Equivalent direct full-replay fixture selection: CONTEXT and SWEEP only.
    direct = [row for row in table.rows if row.reference_outcome_r is not None
              and row.rule_cells["CONTEXT"].state is RuleState.PASS
              and row.rule_cells["SWEEP"].state is RuleState.PASS]
    assert body.without_rule == reference_metrics(direct)
    # Removing the filter also admits its previously NOT_EVALUABLE body-ratio
    # row, because the remaining CONTEXT/SWEEP semantics are still defined.
    assert body.without_rule.reference_expectancy_r == pytest.approx(-0.1)
    assert body.expectancy_delta_vs_full_r == pytest.approx(0.75)

    assert ablations["SWEEP"].status is AblationStatus.REQUIRES_FULL_REPLAY
    assert ablations["CONTEXT"].status is AblationStatus.REQUIRES_FULL_REPLAY


def test_fast_children_are_limited_and_campaign_trials_never_reset(tmp_path):
    table = build_fixture_table()
    engine = FastChildEngine(table, parent_id="PARENT-1", campaign_id="CAMPAIGN-1",
                             strategy_funnel_identity="FUNNEL-ID-1")
    ledger = CampaignLedger("CAMPAIGN-1")

    threshold_child = engine.change_threshold(rule_id="BODY_RATIO", old_value=0.6,
                                              new_value=0.8)
    assert threshold_child.status is ChildStatus.EVALUATED
    assert threshold_child.table is not None
    # Newly rejected/accepted rows do not receive reference outcomes as actual
    # outcomes.  This is especially important for a threshold query child.
    assert all(row.actual_outcome_r is None for row in threshold_child.table.rows
               if row.actual_trade and not next(original for original in table.rows
                                                 if original.event_id == row.event_id).actual_trade)
    first = ledger.append(threshold_child)
    assert first.trial_number == 1

    path_dependent = engine.remove_rule(rule_id="SWEEP")
    assert path_dependent.status is ChildStatus.REQUIRES_FULL_REPLAY
    second = ledger.append(path_dependent)
    assert second.trial_number == 2
    assert ledger.trial_count == 2
    ledger_path = ledger.write_jsonl(tmp_path / "campaign.jsonl")
    assert [line for line in ledger_path.read_text().splitlines() if line]


def test_missing_friction_blocks_economic_ranking_instead_of_defaulting_to_zero():
    table = build_fixture_table()
    ranking = rank_child(selected_parent_rows(table))
    assert ranking.economic_ranking is EconomicRankingStatus.BLOCKED
    assert ranking.scenario_net_expectancy_r is None


def test_oos_and_sealed_holdout_cannot_enter_relaxed_optimization():
    replay = RelaxedReplay(fixture_rules(), engine_id="FUNNEL_OPTIMIZER_RELAXED_V1")
    with pytest.raises(OptimizationGovernanceError):
        replay.evaluate(fixture_opportunities(), dataset_role=DatasetRole.OOS)
    with pytest.raises(OptimizationGovernanceError):
        replay.evaluate(fixture_opportunities(), dataset_role=DatasetRole.SEALED_OOS)


def test_data_acquisition_failure_stays_data_blocked_and_has_no_dataset_identity():
    receipt = FixtureDataReceipt.blocked(
        source="TEST_PUBLIC_SOURCE", acquisition_seconds=0.25, reason_code="NETWORK_BLOCKED")
    assert receipt.status is FixtureDataStatus.DATA_BLOCKED
    assert receipt.dataset_sha256 is None
    assert receipt.files == ()


def test_fixture_dataset_identity_does_not_depend_on_local_materialization_path():
    common = dict(symbol="EURUSD", year=2015, sha256="a" * 64, byte_size=123, source="TEST_SOURCE")
    first = FixtureDataReceipt.verified(
        status=FixtureDataStatus.ACQUIRED_VERIFIED,
        source="TEST_SOURCE", acquisition_seconds=1.0,
        files=(FixtureFile(path="/first/materialization.zip", **common),),
    )
    second = FixtureDataReceipt.verified(
        status=FixtureDataStatus.ACQUIRED_VERIFIED,
        source="TEST_SOURCE", acquisition_seconds=2.0,
        files=(FixtureFile(path="/other/materialization.zip", **common),),
    )
    assert first.dataset_sha256 == second.dataset_sha256


def test_negative_noise_fixture_cannot_be_promoted_by_structural_eligibility():
    table = build_fixture_table()
    unresolved = structural_parent_eligibility(table, baseline=None)
    assert unresolved.verdict is EligibilityVerdict.BLOCKED_RANDOM_BASELINE_COUNT

    synthetic_proof = structural_parent_eligibility(
        table,
        baseline=RandomBaselineConfig(count=32, seed=17, synthetic_test_only=True),
        permit_synthetic_test=True,
    )
    assert synthetic_proof.verdict is EligibilityVerdict.FAIL
    assert synthetic_proof.campaign_state.value == "DEV_REJECTED_NO_SIGNAL"
    assert synthetic_proof.selection_delta_r is not None and synthetic_proof.selection_delta_r < 0


def test_independent_rule_remains_evaluable_after_another_rule_fails():
    # A relaxed replay must not inherit a normal first-failure short circuit.
    independent = RelaxedReplay((
        boolean_rule("FIRST", feature="first"),
        boolean_rule("INDEPENDENT", feature="independent"),
    ), engine_id="RELAXED_INDEPENDENCE_TEST")
    row = independent.evaluate((
        Opportunity(
            event_id="INDEPENDENT-1", candidate_id="C", timestamp_utc=fixture_opportunities()[0].timestamp_utc,
            symbol="EURUSD", session="LONDON", dataset_id="SYN", strategy_id="SYN", engine_id="SYN",
            feature_values={"first": False, "independent": True}, reference_outcome_r=0.25),
    ), dataset_role=DatasetRole.DEVELOPMENT).rows[0]
    assert row.rule_cells["FIRST"].state is RuleState.FAIL
    assert row.rule_cells["INDEPENDENT"].state is RuleState.PASS


def test_frozen_v2_adapter_never_turns_absent_downstream_legacy_stages_into_failures():
    unit = V2Unit(symbol="EURUSD", day="2016-03-01", session="ASIAN_LONDON", candidate_id="V2-1")
    unit.stages["S1_CONTEXT_ELIGIBLE"] = False
    unit.reject_node = "S1_CONTEXT_ELIGIBLE"
    unit.reject_reason = "REFERENCE_INSUFFICIENT_BARS"
    opportunity = opportunity_from_v2_unit(
        unit, timestamp_utc=fixture_opportunities()[0].timestamp_utc, dataset_id="SYNTHETIC_DEV")
    row = RelaxedReplay(v2_relaxed_rules(), engine_id=V2_RELAXED_ENGINE_ID).evaluate(
        (opportunity,), dataset_role=DatasetRole.DEVELOPMENT).rows[0]
    assert row.rule_cells["S1_CONTEXT_ELIGIBLE"].state is RuleState.FAIL
    assert row.rule_cells["S2_LOCATION_ELIGIBLE"].state is RuleState.NOT_EVALUABLE
    assert row.rule_cells["S2_LOCATION_ELIGIBLE"].reason_code.startswith("UPSTREAM_NOT_EVALUABLE")


def test_frozen_ald_v2_bytes_are_unchanged():
    source = Path(__file__).parents[1] / "src/ag_edgelab/strategies/asian_liquidity_displacement_v2.py"
    assert sha256_file(source) == FROZEN_ALD_V2_SHA256
