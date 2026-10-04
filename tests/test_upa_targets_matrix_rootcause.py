"""Universal price-action V0.3 — target lab, diagnostic matrix, root cause."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.universal.direction import Direction
from ag_edgelab.universal.matrix import (CAPABILITY_BASIS, IncomparableCapabilityError,
                                         MatrixCandidate, MatrixStage, build_matrix,
                                         compare_capability)
from ag_edgelab.universal.root_cause import (Diagnosis, NextFunnel, RootCauseInputs, diagnose)
from ag_edgelab.universal.targets import (EntryGeometry, classify_target_r, compute_excursions,
                                          natural_target_r, pdh_pdl_target)

Z = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=Z)


def _bar(i: int, o: float, h: float, l: float, c: float) -> MarketBar:
    return MarketBar(timestamp=T0 + timedelta(minutes=5 * i),
                     open=o, high=max(h, o, c), low=min(l, o, c), close=c, volume=1.0)


# ---------------------------------------------------------------------------
# Target lab
# ---------------------------------------------------------------------------

def test_natural_target_r_calculation():
    # TARGET_R = |target - entry| / |entry - stop|
    assert natural_target_r(entry=100.0, stop=98.0, target=106.0) == pytest.approx(3.0)
    assert natural_target_r(entry=1.1000, stop=1.1020, target=1.0950) == pytest.approx(2.5)
    with pytest.raises(ValueError):
        natural_target_r(entry=100.0, stop=100.0, target=103.0)


def test_natural_target_bucket_classification():
    assert classify_target_r(0.4) == "<1R"
    assert classify_target_r(1.0) == "1-2R"
    assert classify_target_r(2.5) == "2-3R"
    assert classify_target_r(3.999) == "3-4R"
    assert classify_target_r(5.0) == "4-5R"
    assert classify_target_r(5.01) == ">5R"


def test_mfe_mae_and_fixed_reachability():
    geometry = EntryGeometry(Direction.BULL, entry=100.0, stop=99.0)  # risk = 1
    forward = (_bar(0, 100, 101.5, 99.8, 101.0),   # MFE 1.5R
               _bar(1, 101, 103.2, 100.5, 103.0),  # MFE 3.2R
               _bar(2, 103, 103.5, 99.0, 99.0))    # stop hit afterwards
    result = compute_excursions(forward, geometry, horizon=10)
    assert result.mfe_r == pytest.approx(3.5)
    assert result.mae_r == pytest.approx(1.0)
    assert result.fixed_target_reached == {1: True, 2: True, 3: True, 4: False, 5: False}
    assert result.stopped_out and result.stop_bar_offset == 2


def test_ambiguous_bar_counts_stop_first_fail_closed():
    geometry = EntryGeometry(Direction.BULL, entry=100.0, stop=99.0)
    forward = (_bar(0, 100, 105.0, 98.5, 100.0),)  # touches 5R AND the stop
    result = compute_excursions(forward, geometry, horizon=10)
    assert result.stopped_out
    assert not any(result.fixed_target_reached.values())


def test_pdh_pdl_fails_closed_for_crypto_without_preregistration():
    geometry = EntryGeometry(Direction.BULL, entry=100.0, stop=99.0)
    d1 = (_bar(0, 95, 104, 94, 100),)
    assert pdh_pdl_target(d1, geometry, is_crypto=True) is None
    fx = pdh_pdl_target(d1, geometry, is_crypto=False)
    assert fx is not None and fx.target_r == pytest.approx(4.0)
    # crypto + explicit preregistration = optional daily-liquidity feature
    assert pdh_pdl_target(d1, geometry, is_crypto=True, preregistered_for_crypto=True) is not None


# ---------------------------------------------------------------------------
# Diagnostic matrix
# ---------------------------------------------------------------------------

def _candidate(cid: str, mfe: float | None, basis: str = CAPABILITY_BASIS, **passes):
    stage_pass = {stage: passes.get(stage.value, False) for stage in MatrixStage}
    return MatrixCandidate(candidate_id=cid, stage_pass=stage_pass, mfe_r=mfe,
                           capability_basis=basis)


def test_matrix_counts_and_uplift():
    candidates = []
    for i in range(30):  # 30 total; 20 pass direction; 10 pass location
        passes = {"TRIGGER_DIRECTION": i < 20, "TRIGGER_LOCATION": i < 10}
        mfe = 3.0 if i < 10 else 0.5  # location-passers reach 2R
        candidates.append(_candidate(f"c{i}", mfe, **passes))
    matrix = build_matrix(candidates)
    rows = {row.stage: row for row in matrix}
    direction = rows[MatrixStage.TRIGGER_DIRECTION]
    assert (direction.input_n, direction.pass_n, direction.fail_n) == (30, 20, 10)
    location = rows[MatrixStage.TRIGGER_LOCATION]
    assert (location.input_n, location.pass_n, location.fail_n) == (20, 10, 10)
    assert location.capability_before == pytest.approx(0.5)
    assert location.capability_after_pass == pytest.approx(1.0)
    assert location.capability_after_fail == pytest.approx(0.0)
    assert location.uplift_pp == pytest.approx(50.0)
    assert location.comparable and location.capability_basis == CAPABILITY_BASIS


def test_matrix_stage_chain_is_monotone():
    matrix = build_matrix([_candidate("x", 1.0, TRIGGER_LOCATION=True)])  # fails direction
    rows = {row.stage: row for row in matrix}
    assert rows[MatrixStage.TRIGGER_LOCATION].input_n == 0  # never reached


def test_incompatible_capability_semantics_never_compared():
    with pytest.raises(IncomparableCapabilityError):
        compare_capability(CAPABILITY_BASIS, "WIN_RATE_FIXED_TP_V9")
    mixed = [_candidate("a", 2.0, TRIGGER_DIRECTION=True),
             _candidate("b", 2.0, basis="OTHER_BASIS", TRIGGER_DIRECTION=True)]
    rows = {row.stage: row for row in build_matrix(mixed)}
    row = rows[MatrixStage.TRIGGER_DIRECTION]
    assert not row.comparable and row.capability_before is None and row.uplift_pp is None


# ---------------------------------------------------------------------------
# Root cause precedence (CASE A > B > C > D, E fail-closed)
# ---------------------------------------------------------------------------

def _inputs(**overrides) -> RootCauseInputs:
    base = dict(trigger_n=100, trigger_capability=0.5, confirmed_n=60,
                confirmed_capability=0.5, desired_target_r=3.0,
                desired_target_reach=0.5, natural_target_median_r=4.0,
                capability_basis=CAPABILITY_BASIS, comparable=True)
    base.update(overrides)
    return RootCauseInputs(**base)


def test_case_a_trigger_weakness_takes_precedence():
    # Even with confirmation destruction AND target mismatch present,
    # a weak trigger dominates and confirmation work is NOT recommended.
    result = diagnose(_inputs(trigger_capability=0.1, confirmed_capability=0.0,
                              desired_target_reach=0.0, natural_target_median_r=1.0),
                      CAPABILITY_BASIS)
    assert result.case == "A" and result.primary == Diagnosis.TRIGGER_FUNNEL_WEAKNESS
    assert result.next_funnel_to_change == NextFunnel.TRIGGER
    assert "confirmation optimization not recommended" in result.rationale
    assert Diagnosis.TARGET_MODEL_MISMATCH in result.secondary


def test_case_b_confirmation_destruction_precedence_over_target():
    result = diagnose(_inputs(trigger_capability=0.5, confirmed_capability=0.3,
                              desired_target_reach=0.0, natural_target_median_r=1.0),
                      CAPABILITY_BASIS)
    assert result.case == "B" and result.primary == Diagnosis.CONFIRMATION_VALUE_DESTRUCTION
    assert result.next_funnel_to_change == NextFunnel.CONFIRMATION


def test_case_c_target_continuation_weakness():
    result = diagnose(_inputs(desired_target_reach=0.1, natural_target_median_r=4.0),
                      CAPABILITY_BASIS)
    assert result.case == "C" and result.primary == Diagnosis.TARGET_CONTINUATION_WEAKNESS
    assert result.next_funnel_to_change == NextFunnel.TARGET


def test_case_d_target_model_mismatch():
    result = diagnose(_inputs(natural_target_median_r=1.5), CAPABILITY_BASIS)
    assert result.case == "D" and result.primary == Diagnosis.TARGET_MODEL_MISMATCH
    assert "NOT replaced" in result.rationale


def test_case_e_insufficient_evidence():
    result = diagnose(_inputs(trigger_n=5), CAPABILITY_BASIS)
    assert result.case == "E" and result.primary == Diagnosis.INSUFFICIENT_EVIDENCE
    assert result.next_funnel_to_change == NextFunnel.NONE
    result = diagnose(_inputs(comparable=False), CAPABILITY_BASIS)
    assert result.primary == Diagnosis.INSUFFICIENT_EVIDENCE


def test_no_dominant_weakness():
    result = diagnose(_inputs(), CAPABILITY_BASIS)
    assert result.case == "NONE" and result.primary == Diagnosis.NO_DOMINANT_WEAKNESS
    assert result.next_funnel_to_change == NextFunnel.NONE


def test_root_cause_refuses_foreign_capability_basis():
    with pytest.raises(IncomparableCapabilityError):
        diagnose(_inputs(capability_basis="SOMETHING_ELSE"), CAPABILITY_BASIS)
