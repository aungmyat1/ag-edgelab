from datetime import datetime, timezone

from ag_edgelab.verification.production import (
    EdgeValidationEvidence, EdgeVerdict, FrictionStressResult, MetricSet,
    ParityResult, RegimeResult, VerificationPolicy, WalkForwardResult, verify_edge,
)
from ag_edgelab.verification.walk_forward import ChronologicalFold, run_walk_forward


def good_evidence(policy):
    return EdgeValidationEvidence(
        strategy_id="S", strategy_version="1", strategy_sha256="a"*64,
        funnel_sha256="b"*64, parameters_sha256="c"*64, oos_dataset_sha256="d"*64,
        cost_model_sha256="e"*64, verification_policy_sha256=policy.sha256,
        holdout_was_unseen=True, candidate_was_frozen=True,
        oos=MetricSet(trades=80, expectancy_r=.2, profit_factor=1.4, max_drawdown_r=8),
        friction=FrictionStressResult(expectancy_by_multiplier={1.0:.2,1.5:.1,2.0:.02}),
        parameter_stable=True,
        walk_forward=WalkForwardResult(fold_expectancy_r=(.1,.2,-.02,.15)),
        regimes=(RegimeResult(name="TREND", trades=40, expectancy_r=.3), RegimeResult(name="RANGE", trades=40, expectancy_r=.1)),
        parity=ParityResult(reference_trades=80, independent_trades=80, reference_expectancy_r=.2, independent_expectancy_r=.195),
        bootstrap_ci_low_r=.04, bootstrap_ci_high_r=.35,
    )


def test_all_gates_can_issue_edge_verified():
    p=VerificationPolicy()
    a=verify_edge(good_evidence(p),p)
    assert a.verdict == EdgeVerdict.EDGE_VERIFIED
    assert all(a.gate_results.values())


def test_missing_parity_fails_closed():
    p=VerificationPolicy(); e=good_evidence(p).model_copy(update={"parity":None})
    assert verify_edge(e,p).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_bad_oos_economics_is_no_edge_not_verified():
    p=VerificationPolicy(); e=good_evidence(p).model_copy(update={"oos":MetricSet(trades=80,expectancy_r=-.1,profit_factor=.8,max_drawdown_r=8)})
    assert verify_edge(e,p).verdict == EdgeVerdict.NO_EDGE


def test_policy_mismatch_blocks_verification():
    p=VerificationPolicy(); e=good_evidence(p).model_copy(update={"verification_policy_sha256":"0"*64})
    assert verify_edge(e,p).verdict == EdgeVerdict.VERIFICATION_BLOCKED


def test_holdout_not_unseen_blocks_verification():
    p=VerificationPolicy(); e=good_evidence(p).model_copy(update={"holdout_was_unseen":False})
    assert verify_edge(e,p).verdict == EdgeVerdict.VERIFICATION_BLOCKED


def test_walk_forward_requires_chronology():
    z=timezone.utc
    fold=ChronologicalFold("F1",datetime(2024,1,1,tzinfo=z),datetime(2024,6,1,tzinfo=z),datetime(2024,6,1,tzinfo=z),datetime(2024,7,1,tzinfo=z))
    r=run_walk_forward((fold,),lambda _: (1,-1,1))
    assert r[0].trades==3
