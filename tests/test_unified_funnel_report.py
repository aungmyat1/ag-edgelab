from datetime import datetime, timedelta, timezone

from ag_edgelab.analytics.unified import build_funnel_diagnostic_report, classify_root_cause
from ag_edgelab.contracts.funnel import FunnelStage, FunnelStageResult, RuleResult
from ag_edgelab.ledger.candidate import CandidateRecord

UTC = timezone.utc


def _record(cid="C", stages=()):
    out = []
    for stage, at, passed, features, reason in stages:
        rule = RuleResult(rule_id=f"{stage}-R", rule_version="1", rule_hash="a" * 64, passed=passed, evaluated_at=at, features=features, failure_reason=reason, rejection_code=reason)
        out.append(FunnelStageResult(candidate_id=cid, stage=stage, passed=passed, as_of=at, rule_results=(rule,), failure_reason=reason, rejection_codes=(reason,) if reason else ()))
    return CandidateRecord(candidate_id=cid, instrument="EURUSD", strategy_id="S", strategy_version="1", strategy_sha256="b" * 64, dataset_sha256="c" * 64, stage_results=tuple(out))


def _flow(trigger, confirmation):
    return ({"rule": "TRIGGER", "pass_n": trigger}, {"rule": "CONFIRMATION", "pass_n": confirmation})


def test_complete_funnel_and_deterministic_report_hash():
    t = datetime(2026, 1, 1, 6, tzinfo=UTC)
    features = {"cycle_id": "D|S"}
    r = _record(stages=[
        (FunnelStage.CONTEXT, t, True, features, None),
        (FunnelStage.LOCATION, t + timedelta(minutes=1), True, features, None),
        (FunnelStage.TRIGGER, t + timedelta(minutes=2), True, features, None),
        (FunnelStage.GEOMETRY, t + timedelta(minutes=3), True, {**features, "logical_stage": "CONFIRMATION"}, None),
        (FunnelStage.EXECUTION, t + timedelta(minutes=4), True, features, None),
    ])
    kwargs = dict(strategy_identity={"id": "S"}, dataset_identity={"id": "D"}, dataset_role="DEV")
    a = build_funnel_diagnostic_report([r], **kwargs)
    b = build_funnel_diagnostic_report([r], **kwargs)
    assert a.report_hash == b.report_hash
    assert a.primary_diagnosis is None
    assert a.temporal["same_cycle_n"] == 1


def test_root_cause_precedence_hides_downstream_starvation():
    primary, secondary = classify_root_cause(
        flow=_flow(18, 0),
        temporal={"diagnostic_counts": {"TEMPORAL_FUNNEL_INCOMPATIBILITY": 18, "CROSS_SESSION_TRIGGER": 18}},
        target_capability={"1R": {"reach_after_pass": None}}, economics={"closed": 0},
    )
    assert primary == "TEMPORAL_FUNNEL_INCOMPATIBILITY"
    assert "STARVED_CONFIRMATION" in secondary


def test_starved_trigger_diagnostic():
    primary, _ = classify_root_cause(flow=_flow(0, 0), temporal={"diagnostic_counts": {}}, target_capability={}, economics=None)
    assert primary == "STARVED_TRIGGER"


def test_starved_confirmation_diagnostic():
    primary, _ = classify_root_cause(flow=_flow(2, 0), temporal={"diagnostic_counts": {}}, target_capability={}, economics=None)
    assert primary == "STARVED_CONFIRMATION"


def test_capability_friction_and_sample_diagnostics():
    primary, secondary = classify_root_cause(
        flow=_flow(2, 2), temporal={"diagnostic_counts": {}},
        target_capability={"1R": {"reach_after_pass": 0.5, "uplift_pp": 0.0}},
        economics={"closed": 2, "gross_R": 1.0, "net_R": -0.2},
    )
    assert primary is None
    assert "CONFIRMATION_NO_UPLIFT" in secondary
    assert "FRICTION_DESTROYS_EDGE" in secondary


def test_real_v2_report_is_generic_temporal_conclusion():
    import json
    from pathlib import Path
    report = json.loads((Path(__file__).parents[1] / "artifacts/mtf_control_shift_v1/universal_funnel_report_v2.json").read_text())
    assert report["schema_version"] == "FunnelDiagnosticReportV2"
    assert report["flow"][2]["pass_n"] == 18
    assert report["flow"][3]["pass_n"] == 0
    assert report["temporal"]["cross_cycle_n"] == 18
    assert report["primary_diagnosis"] == "TEMPORAL_FUNNEL_INCOMPATIBILITY"
