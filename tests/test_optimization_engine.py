import pytest

from ag_edgelab.contracts.dataset import DatasetRole
from ag_edgelab.optimization.ablation import run_leave_one_out_ablation, stage_value_map
from ag_edgelab.optimization.contracts import DatasetExposure, FunnelVariant, MutationType, ResearchMutation, StageContribution
from ag_edgelab.optimization.governance import OptimizationGovernanceError, assert_holdout_open_allowed, assert_optimization_allowed, next_exposure
from ag_edgelab.optimization.stability import assess_parameter_stability


def test_stage_contribution_rejects_impossible_counts():
    with pytest.raises(ValueError):
        StageContribution(stage_id="SWEEP", input_count=10, pass_count=11, pass_rate=1, wins=0, losses=0, population_retained=1)


def test_ablation_reports_incremental_stage_value():
    outcomes = {
        frozenset({"TREND", "SWEEP"}): [1, 1, -1, 1],
        frozenset({"SWEEP"}): [1, -1, -1, -1],
        frozenset({"TREND"}): [1, -1, -1, -1],
    }
    results = run_leave_one_out_ablation(["TREND", "SWEEP"], lambda enabled: outcomes[enabled])
    values = stage_value_map(results)
    assert values["TREND"] > 0
    assert values["SWEEP"] > 0


def test_optimizer_is_development_only():
    assert_optimization_allowed(DatasetRole.DEVELOPMENT, DatasetExposure.DEVELOPMENT)
    for role in (DatasetRole.OOS, DatasetRole.SEALED_OOS, DatasetRole.FORWARD):
        with pytest.raises(OptimizationGovernanceError):
            assert_optimization_allowed(role, DatasetExposure.UNSEEN)


def test_inspected_oos_is_burned_irreversibly_by_transition():
    assert next_exposure(DatasetExposure.UNSEEN, True, DatasetRole.SEALED_OOS) == DatasetExposure.BURNED_HOLDOUT


def test_holdout_requires_frozen_candidate_and_unseen_data():
    variant = FunnelVariant(strategy_id="S", strategy_version="1", strategy_sha256="a" * 64, development_dataset_sha256="b" * 64, frozen=False)
    with pytest.raises(OptimizationGovernanceError):
        assert_holdout_open_allowed(variant, DatasetRole.SEALED_OOS, DatasetExposure.UNSEEN)
    frozen = variant.model_copy(update={"frozen": True})
    assert_holdout_open_allowed(frozen, DatasetRole.SEALED_OOS, DatasetExposure.UNSEEN)
    with pytest.raises(OptimizationGovernanceError):
        assert_holdout_open_allowed(frozen, DatasetRole.SEALED_OOS, DatasetExposure.BURNED_HOLDOUT)


def test_mutation_lineage_requires_parent():
    mutation = ResearchMutation(mutation_id="m1", mutation_type=MutationType.REMOVE_STAGE, stage_id="RETEST", rationale="negative DEV contribution")
    with pytest.raises(ValueError):
        FunnelVariant(strategy_id="S", strategy_version="2", strategy_sha256="a" * 64, mutations=(mutation,), development_dataset_sha256="b" * 64)


def test_parameter_plateau_passes_and_spike_fails():
    plateau = assess_parameter_stability({1.0: .20, 1.2: .25, 1.4: .24}, 1.2)
    assert plateau.stable
    spike = assess_parameter_stability({1.0: -.02, 1.2: .49, 1.4: -.08}, 1.2)
    assert not spike.stable
