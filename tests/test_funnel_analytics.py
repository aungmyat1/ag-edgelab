from datetime import datetime, timezone

from ag_edgelab.analytics.funnel import compute_funnel_stats
from ag_edgelab.contracts.funnel import FunnelStage, FunnelStageResult
from ag_edgelab.ledger.candidate import CandidateRecord


def record(cid, passed_stages):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    results = tuple(
        FunnelStageResult(candidate_id=cid, stage=stage, passed=True, as_of=now, rule_results=())
        for stage in passed_stages
    )
    return CandidateRecord(
        candidate_id=cid, instrument="EURUSD", strategy_id="S", strategy_version="1",
        strategy_sha256="a" * 64, dataset_sha256="b" * 64, stage_results=results,
    )


def test_funnel_stats_compute_conditional_win_rate_and_lift():
    records = [
        record("A", [FunnelStage.CONTEXT, FunnelStage.LOCATION]),
        record("B", [FunnelStage.CONTEXT, FunnelStage.LOCATION]),
        record("C", [FunnelStage.CONTEXT]),
        record("D", []),
    ]
    stats = compute_funnel_stats(records, {"A": 1.0, "B": -1.0, "C": -1.0})
    context, location = stats[0], stats[1]
    assert context.candidates == 3
    assert round(context.win_rate or 0, 6) == round(1 / 3, 6)
    assert location.candidates == 2
    assert location.win_rate == 0.5
    assert round(location.win_rate_lift_pp or 0, 6) == round((0.5 - 1 / 3) * 100, 6)
    assert context.win_ci95_low is not None and context.win_ci95_high is not None
