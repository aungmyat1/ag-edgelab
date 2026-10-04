from datetime import datetime, timedelta, timezone

from ag_edgelab.analytics.funnel import analyze_temporal_funnel
from ag_edgelab.analytics.temporal import TemporalDiagnostic
from ag_edgelab.contracts.funnel import FunnelStage, FunnelStageResult, RuleResult
from ag_edgelab.ledger.candidate import CandidateRecord

UTC = timezone.utc


def _record(cid, entries):
    results = []
    for stage, at, passed, features in entries:
        rule = RuleResult(
            rule_id=f"{stage.lower()}-rule", rule_version="1", rule_hash="a" * 64,
            passed=passed, evaluated_at=at, features=features,
        )
        results.append(FunnelStageResult(
            candidate_id=cid, stage=stage, passed=passed, as_of=at,
            rule_results=(rule,),
        ))
    return CandidateRecord(
        candidate_id=cid, instrument="EURUSD", strategy_id="S", strategy_version="1",
        strategy_sha256="b" * 64, dataset_sha256="c" * 64,
        stage_results=tuple(results),
    )


def test_valid_same_cycle_temporal_funnel_and_delays():
    t = datetime(2026, 1, 5, 6, tzinfo=UTC)
    cycle = {"cycle_id": "2026-01-05|ASIAN_LONDON"}
    record = _record("VALID", [
        (FunnelStage.CONTEXT, t, True, cycle),
        (FunnelStage.LOCATION, t + timedelta(minutes=15), True, cycle),
        (FunnelStage.TRIGGER, t + timedelta(minutes=30), True, cycle),
        (FunnelStage.GEOMETRY, t + timedelta(minutes=45), True, {**cycle, "logical_stage": "CONFIRMATION"}),
        (FunnelStage.EXECUTION, t + timedelta(minutes=60), True, cycle),
    ])
    report = analyze_temporal_funnel([record])
    audit = report.candidates[0]
    assert audit.stage_order_valid is True
    assert audit.same_cycle is True
    assert audit.diagnostics == ()
    assert audit.inter_stage_delays_minutes["LOCATION->TRIGGER"] == 15.0
    assert report.diagnostic_counts[TemporalDiagnostic.TEMPORAL_FUNNEL_INCOMPATIBILITY] == 0


def test_invalid_temporal_funnel_flags_order_and_cross_cycle():
    t = datetime(2026, 1, 5, 6, tzinfo=UTC)
    record = _record("INVALID", [
        (FunnelStage.TRIGGER, t, True, {"cycle_id": "prior"}),
        (FunnelStage.LOCATION, t + timedelta(minutes=30), True, {"cycle_id": "current"}),
        (FunnelStage.GEOMETRY, t - timedelta(minutes=15), True, {"logical_stage": "CONFIRMATION", "cycle_id": "prior"}),
    ])
    report = analyze_temporal_funnel([record])
    audit = report.candidates[0]
    assert audit.stage_order_valid is False
    assert audit.same_cycle is False
    assert TemporalDiagnostic.TRIGGER_PRECEDES_LOCATION in audit.diagnostics
    assert TemporalDiagnostic.CONFIRMATION_PRECEDES_LOCATION in audit.diagnostics
    assert TemporalDiagnostic.CROSS_SESSION_TRIGGER in audit.diagnostics
    assert report.diagnostic_counts[TemporalDiagnostic.TEMPORAL_FUNNEL_INCOMPATIBILITY] >= 1


def test_missing_downstream_stage_is_not_a_temporal_violation():
    t = datetime(2026, 1, 5, 6, tzinfo=UTC)
    record = _record("ATTRITION", [
        (FunnelStage.CONTEXT, t, True, {}),
        (FunnelStage.LOCATION, t + timedelta(minutes=10), False, {}),
    ])
    audit = analyze_temporal_funnel([record]).candidates[0]
    assert audit.stage_order_valid is True
    assert audit.diagnostics == ()
