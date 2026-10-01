from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ag_edgelab.verification.production import (
    CANONICAL_POLICY_V1, EdgeValidationArtifact, EdgeValidationEvidence, EdgeVerdict,
    FrictionPoint, FrictionStressResult, MetricSet, ParityResult, RegimeResult,
    StabilityEvidence, WalkForwardResult, validate_artifact, verify_edge,
)
from ag_edgelab.verification.walk_forward import ChronologicalFold, run_walk_forward


def good_evidence():
    p = CANONICAL_POLICY_V1
    return EdgeValidationEvidence(
        strategy_id="S", strategy_version="1", strategy_sha256="a"*64,
        funnel_sha256="b"*64, parameters_sha256="c"*64, oos_dataset_sha256="d"*64,
        cost_model_sha256="e"*64, verification_policy_id=p.policy_id,
        verification_policy_sha256=p.sha256, frozen_variant_sha256="f"*64,
        exposure_ledger_proof_sha256="1"*64, holdout_was_unseen=True, candidate_was_frozen=True,
        oos=MetricSet(trades=80, expectancy_r=.2, profit_factor=1.4, max_drawdown_r=8),
        friction=FrictionStressResult(points=(FrictionPoint(multiplier=1.0,expectancy_r=.2),FrictionPoint(multiplier=1.25,expectancy_r=.15),FrictionPoint(multiplier=1.5,expectancy_r=.1))),
        stability=StabilityEvidence(result_sha256="2"*64, stable=True),
        walk_forward=WalkForwardResult(fold_expectancy_r=(.1,.2,-.02,.15)),
        regimes=(RegimeResult(name="TREND", trades=40, expectancy_r=.3), RegimeResult(name="RANGE", trades=40, expectancy_r=.1)),
        parity=ParityResult(reference_engine_id="reference", independent_engine_id="independent", reference_code_sha256="3"*64, independent_code_sha256="4"*64, reference_trade_list_sha256="5"*64, independent_trade_list_sha256="6"*64, reference_trades=80, independent_trades=80, reference_expectancy_r=.2, independent_expectancy_r=.195),
        bootstrap_ci_low_r=.04, bootstrap_ci_high_r=.35, evidence_hashes=("7"*64,),
    )


def test_all_gates_can_issue_edge_verified():
    a=verify_edge(good_evidence())
    assert a.verdict == EdgeVerdict.EDGE_VERIFIED
    assert all(v for _,v in a.gate_results)
    assert validate_artifact(a)


def test_missing_parity_fails_closed():
    e=good_evidence().model_copy(update={"parity":None})
    assert verify_edge(e).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_bad_oos_economics_is_no_edge():
    e=good_evidence().model_copy(update={"oos":MetricSet(trades=80,expectancy_r=-.1,profit_factor=.8,max_drawdown_r=8)})
    assert verify_edge(e).verdict == EdgeVerdict.NO_EDGE


def test_policy_mismatch_blocks_verification():
    e=good_evidence().model_copy(update={"verification_policy_sha256":"0"*64})
    assert verify_edge(e).verdict == EdgeVerdict.VERIFICATION_BLOCKED


def test_holdout_not_unseen_blocks_verification():
    e=good_evidence().model_copy(update={"holdout_was_unseen":False})
    assert verify_edge(e).verdict == EdgeVerdict.VERIFICATION_BLOCKED


def test_bad_bootstrap_interval_rejected():
    with pytest.raises(ValidationError):
        EdgeValidationEvidence.model_validate({**good_evidence().model_dump(),"bootstrap_ci_low_r":.4,"bootstrap_ci_high_r":.3})


def test_friction_requires_full_monotone_grid_and_oos_match():
    e=good_evidence().model_copy(update={"friction":FrictionStressResult(points=(FrictionPoint(multiplier=1.0,expectancy_r=-.1),FrictionPoint(multiplier=1.25,expectancy_r=-.05),FrictionPoint(multiplier=1.5,expectancy_r=.1)))})
    assert verify_edge(e).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_single_walk_forward_fold_cannot_pass():
    e=good_evidence().model_copy(update={"walk_forward":WalkForwardResult(fold_expectancy_r=(.001,))})
    assert verify_edge(e).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_negative_well_sampled_regime_cannot_pass():
    e=good_evidence().model_copy(update={"regimes":(RegimeResult(name="TREND",trades=40,expectancy_r=.3),RegimeResult(name="RANGE",trades=40,expectancy_r=-2.0))})
    assert verify_edge(e).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_parity_must_match_oos_population():
    p=good_evidence().parity.model_copy(update={"reference_trades":3,"independent_trades":3})
    e=good_evidence().model_copy(update={"parity":p})
    assert verify_edge(e).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_empty_or_junk_evidence_hashes_rejected():
    with pytest.raises(ValidationError):
        EdgeValidationEvidence.model_validate({**good_evidence().model_dump(),"evidence_hashes":()})
    with pytest.raises(ValidationError):
        EdgeValidationEvidence.model_validate({**good_evidence().model_dump(),"evidence_hashes":("junk",)})


def test_infinite_metrics_rejected():
    with pytest.raises(ValidationError):
        MetricSet(trades=80,expectancy_r=float("inf"),profit_factor=1.4,max_drawdown_r=8)
    with pytest.raises(ValidationError):
        WalkForwardResult(fold_expectancy_r=(.1,float("inf"),.2))


def test_forged_artifact_does_not_validate():
    good=verify_edge(good_evidence())
    forged=good.model_copy(update={"verdict":EdgeVerdict.NO_EDGE})
    assert not validate_artifact(forged)


def test_walk_forward_requires_chronology():
    z=timezone.utc
    fold=ChronologicalFold("F1",datetime(2024,1,1,tzinfo=z),datetime(2024,6,1,tzinfo=z),datetime(2024,6,1,tzinfo=z),datetime(2024,7,1,tzinfo=z))
    r=run_walk_forward((fold,),lambda _: (1,-1,1))
    assert r[0].trades==3
