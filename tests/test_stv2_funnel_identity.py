"""STV2 strategy-funnel identity model.

Covers requirements 1-8, 35-36 and 45 of STV2_STRATEGY_FUNNEL_ANALYZER_V1.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ag_edgelab.analytics.funnel import compute_funnel_stats, default_outcome_key, wilson_interval
from ag_edgelab.campaigns.session_trade_v2.funnel_models import (
    CANONICAL_CANDIDATE_ID,
    EXPECTED_FILTER_STAGE_ROWS,
    EXPECTED_SEGMENTS,
    FILTER_STAGES,
    Stv2AnalysisUnitRecord,
    all_segment_ids,
    analysis_unit_key,
    compute_analysis_unit_id,
    segment_id,
)
from ag_edgelab.campaigns.session_trade_v2.identity import SOURCE_COMMIT, verify_identity
from ag_edgelab.contracts.funnel import FunnelStage, FunnelStageResult
from ag_edgelab.ledger.candidate import CandidateRecord

BASE = {
    "candidate_id": CANONICAL_CANDIDATE_ID,
    "symbol": "EURUSD",
    "session": "LONDON_NEWYORK",
    "branch": "A_SWEEP_REENTRY",
    "trading_date": "2017-03-01",
    "event_identity": "LONDON_NEWYORK@2017-03-01T11:00:00+00:00#0",
    "dataset_sha256": "a" * 64,
}


def uid(**overrides) -> str:
    return compute_analysis_unit_id(**{**BASE, **overrides})


# -- 1. canonical candidate identity preserved ------------------------------


def test_canonical_candidate_identity_preserved():
    identity = verify_identity()
    assert identity.candidate_id == CANONICAL_CANDIDATE_ID
    assert CANONICAL_CANDIDATE_ID == "SESSION_TRADE_V2_v2.0.0_e1ffe9f1e5cc"
    assert identity.source_commit == SOURCE_COMMIT == "e1ffe9f1e5ccfb9a336f1b4ae4289d41901ec5d2"


# -- 2. unique analysis_unit_id ---------------------------------------------


def test_analysis_unit_id_is_a_sha256_hex_digest():
    value = uid()
    assert len(value) == 64
    assert int(value, 16) >= 0


def test_analysis_unit_ids_are_unique_across_the_identity_payload():
    ids = {
        uid(),
        uid(symbol="GBPUSD"),
        uid(session="ASIAN_LONDON"),
        uid(branch="B_RANGE_REJECTION"),
        uid(trading_date="2017-03-02"),
        uid(event_identity="LONDON_NEWYORK@2017-03-01T11:00:00+00:00#1"),
        uid(dataset_sha256="b" * 64),
    }
    assert len(ids) == 7


# -- 3/4/5/6. no collisions across each dimension ---------------------------


def test_same_candidate_across_symbols_does_not_collide():
    assert uid(symbol="EURUSD") != uid(symbol="GBPUSD")
    assert len({uid(symbol=s) for s in ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")}) == 4


def test_same_candidate_and_symbol_across_sessions_does_not_collide():
    assert uid(session="ASIAN_LONDON") != uid(session="LONDON_NEWYORK")


def test_same_candidate_symbol_session_across_branches_does_not_collide():
    branches = ("A_SWEEP_REENTRY", "B_RANGE_REJECTION", "C_TREND_EXPANSION")
    assert len({uid(branch=b) for b in branches}) == 3


def test_separate_trading_dates_and_events_do_not_collide():
    assert uid(trading_date="2017-03-01") != uid(trading_date="2017-03-02")
    assert uid(event_identity="X#0") != uid(event_identity="X#1")


def test_strategy_commit_hash_alone_is_not_the_instance_hash():
    """The commit sha is constant across observations and cannot disambiguate."""
    assert uid(symbol="EURUSD") != SOURCE_COMMIT
    assert uid(symbol="EURUSD") != uid(symbol="GBPUSD")  # commit identical in both


# -- 7. deterministic ID reproduction ---------------------------------------


def test_analysis_unit_id_is_deterministic_and_key_order_independent():
    assert uid() == uid()
    reordered = compute_analysis_unit_id(
        dataset_sha256=BASE["dataset_sha256"],
        event_identity=BASE["event_identity"],
        trading_date=BASE["trading_date"],
        branch=BASE["branch"],
        session=BASE["session"],
        symbol=BASE["symbol"],
        candidate_id=BASE["candidate_id"],
    )
    assert reordered == uid()


# -- 8. exactly 24 segment identities ---------------------------------------


def test_exactly_24_segment_identities():
    segments = all_segment_ids()
    assert len(segments) == EXPECTED_SEGMENTS == 24
    assert len(set(segments)) == 24
    assert EXPECTED_FILTER_STAGE_ROWS == 24 * len(FILTER_STAGES) == 120


def test_segment_id_format_and_validation():
    assert segment_id("EURUSD", "LONDON_NEWYORK", "A_SWEEP_REENTRY") == (
        "SESSION_TRADE_V2|EURUSD|LONDON_NEWYORK|A_SWEEP_REENTRY"
    )
    for bad in (("XXXXXX", "LONDON_NEWYORK", "A_SWEEP_REENTRY"),
                ("EURUSD", "TOKYO", "A_SWEEP_REENTRY"),
                ("EURUSD", "LONDON_NEWYORK", "D_UNKNOWN")):
        with pytest.raises(ValueError):
            segment_id(*bad)


def test_segment_and_analysis_unit_and_candidate_are_three_distinct_concepts():
    seg = segment_id("EURUSD", "LONDON_NEWYORK", "A_SWEEP_REENTRY")
    assert seg != CANONICAL_CANDIDATE_ID
    assert uid() != seg
    assert uid() != CANONICAL_CANDIDATE_ID


# -- 45. generic analyzer backward compatibility ----------------------------


def _record(cid: str, stages, unit_id: str | None = None, segment: str = "S"):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    results = tuple(
        FunnelStageResult(candidate_id=cid, stage=s, passed=True, as_of=now, rule_results=())
        for s in stages
    )
    common = dict(
        candidate_id=cid, instrument="EURUSD", strategy_id="S", strategy_version="1",
        strategy_sha256="a" * 64, dataset_sha256="b" * 64, stage_results=results,
    )
    if unit_id is None:
        return CandidateRecord(**common)
    return Stv2AnalysisUnitRecord(**common, analysis_unit_id=unit_id, segment_id=segment)


def test_compute_funnel_stats_default_key_is_unchanged():
    records = [
        _record("A", [FunnelStage.CONTEXT, FunnelStage.LOCATION]),
        _record("B", [FunnelStage.CONTEXT, FunnelStage.LOCATION]),
        _record("C", [FunnelStage.CONTEXT]),
    ]
    stats = compute_funnel_stats(records, {"A": 1.0, "B": -1.0, "C": -1.0})
    assert stats[0].candidates == 3
    assert stats[1].candidates == 2
    assert stats[1].win_rate == 0.5
    assert default_outcome_key(records[0]) == "A"


def test_candidate_id_keying_collides_but_analysis_unit_keying_does_not():
    """The exact bug being fixed: shared candidate_id collapses every outcome."""
    shared = CANONICAL_CANDIDATE_ID
    records = [
        _record(shared, [FunnelStage.CONTEXT], unit_id=uid(symbol="EURUSD")),
        _record(shared, [FunnelStage.CONTEXT], unit_id=uid(symbol="GBPUSD")),
        _record(shared, [FunnelStage.CONTEXT], unit_id=uid(symbol="USDJPY")),
    ]
    outcomes = {
        uid(symbol="EURUSD"): 2.0,
        uid(symbol="GBPUSD"): -1.0,
        uid(symbol="USDJPY"): -1.0,
    }
    # Legacy keying finds nothing (candidate_id is not a key in outcomes) and,
    # if it did, every record would map to the SAME value.
    legacy = compute_funnel_stats(records, {shared: 2.0})
    assert legacy[0].candidates == 3
    assert legacy[0].expectancy_r == 2.0  # all three collapsed onto one outcome

    fixed = compute_funnel_stats(records, outcomes, key_fn=analysis_unit_key)
    assert fixed[0].candidates == 3
    assert fixed[0].expectancy_r == pytest.approx(0.0)
    assert fixed[0].wins == 1


def test_analysis_unit_key_rejects_records_without_unit_identity():
    with pytest.raises(ValueError, match="analysis_unit_id"):
        analysis_unit_key(_record("A", [FunnelStage.CONTEXT]))


def test_stv2_record_preserves_canonical_candidate_id_alongside_unit_id():
    record = _record(CANONICAL_CANDIDATE_ID, [FunnelStage.CONTEXT], unit_id=uid(), segment="SEG")
    assert record.candidate_id == CANONICAL_CANDIDATE_ID
    assert record.analysis_unit_id == uid()
    assert record.segment_id == "SEG"
    assert isinstance(record, CandidateRecord)


# -- 33. Wilson interval behaviour ------------------------------------------


def test_wilson_interval_reused_and_undefined_at_zero_samples():
    assert wilson_interval(0, 0) == (None, None)
    low, high = wilson_interval(5, 10)
    assert 0.0 < low < 0.5 < high < 1.0
    # degenerate proportions stay inside [0, 1] and never collapse to a point
    low0, high0 = wilson_interval(0, 10)
    assert low0 == 0.0 and 0.0 < high0 < 1.0
    low1, high1 = wilson_interval(10, 10)
    assert high1 == pytest.approx(1.0) and 0.0 < low1 < 1.0
    # wider interval for smaller n at the same proportion
    narrow = wilson_interval(50, 100)
    wide = wilson_interval(5, 10)
    assert (wide[1] - wide[0]) > (narrow[1] - narrow[0])


def test_no_scipy_dependency_introduced():
    import ag_edgelab.analytics.funnel as mod
    import ag_edgelab.campaigns.session_trade_v2.funnel_analyzer as analyzer

    for source in (mod, analyzer):
        text = open(source.__file__).read()
        assert "scipy" not in text
