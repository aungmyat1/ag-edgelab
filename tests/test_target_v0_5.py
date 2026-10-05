"""V0.5 CAUSAL TARGET MODEL DIAGNOSTICS — unit tests (§20).

All tests are synthetic/deterministic; no external dataset required.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.derive import aggregate_bars
from ag_edgelab.data.fx_histdata_2017 import PARTITIONS, bars_closed_at, \
    derive_fx_timeframe
from ag_edgelab.universal.campaign import make_synthetic_fx_bars
from ag_edgelab.universal.direction import Direction
from ag_edgelab.universal.fx_dev_campaign import (CONFIRMATION_WINDOW_BARS,
                                                  OUTCOME_HORIZON_BARS,
                                                  STOP_LOOKBACK_BARS,
                                                  run_fx_symbol_campaign)
from ag_edgelab.universal.targets import EntryGeometry, FIXED_R_TARGETS
from ag_edgelab.universal.trigger_v0_4 import enrich_symbol
from ag_edgelab.universal import target_v0_5 as tv5
from ag_edgelab.universal.target_v0_5 import (
    EntryRecord, FAMILY_CONTRACTS, NATURAL_FAMILIES, SELECTION_REASON,
    _natural_candidates, _pearson, _ranks, _spearman, _target_reachability_impl,
    _time_to_targets, build_entry_records, build_symbol_context,
    candidate_ledger_rows, continuation_chain, coupling_correlations,
    d01_vs_t1_effect, family_report, fit_class_for, fit_classification,
    ladder_rows, multi_objective_delivery, population_target_report,
    root_cause_cases, stop_target_geometry)
from ag_edgelab.universal.target_v0_5 import (CorrelationResult,
                                              pearson_result,
                                              spearman_result)

UTC = timezone.utc
T0 = datetime(2017, 1, 2, tzinfo=UTC)          # Monday


def _bar(ts: datetime, h: float, lo: float) -> MarketBar:
    mid = (h + lo) / 2.0
    return MarketBar(timestamp=ts, open=mid, high=h, low=lo, close=mid)


def _m15bar(i: int, o: float, h: float, lo: float, c: float) -> MarketBar:
    return MarketBar(timestamp=T0 + timedelta(minutes=15 * i),
                     open=o, high=h, low=lo, close=c)


# ---------------------------------------------------------------------------
# hand-built frames: prove per-family causality cuts explicitly
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def manual_frames():
    # H4 (start 2017-01-02 00:00): swing high 1.10 / swing low 0.96 at idx 2
    # (confirmed idx 4 -> created 2017-01-02 20:00); swing high 1.20 / low 0.90
    # at idx 7 (confirmed idx 9 -> created 2017-01-03 16:00).
    h4_hl = [(1.06, 1.02), (1.07, 1.03), (1.10, 0.96), (1.08, 1.03),
             (1.07, 1.04), (1.09, 1.00), (1.11, 0.99), (1.20, 0.90),
             (1.07, 1.01), (1.05, 1.02), (1.04, 1.015), (1.03, 1.01)]
    h4 = tuple(_bar(T0 + timedelta(hours=4 * i), h, lo)
               for i, (h, lo) in enumerate(h4_hl))
    # D1: Jan 2 high 1.12 low 1.00 (closes Jan 3 00:00);
    #     Jan 3 high 1.20 low 0.90 (closes Jan 4 00:00 — FUTURE for our entry)
    d1 = (_bar(T0, 1.12, 1.00), _bar(T0 + timedelta(days=1), 1.20, 0.90))
    # M15 on Jan 3: ASIAN bars 00:00-07:45 (high max 1.08, low min 1.01),
    # LONDON bars 08:00-09:45 (extreme 1.50/0.80 — window NOT completed at
    # the 10:00 entry, must never be selected).
    day2 = T0 + timedelta(days=1)
    m15 = []
    for i in range(32):                                 # ASIAN 00:00-07:45
        hi = 1.08 if i == 10 else 1.05
        lo = 1.01 if i == 20 else 1.02
        m15.append(_bar(day2 + timedelta(minutes=15 * i), hi, lo))
    for i in range(8):                                  # LONDON 08:00-09:45
        m15.append(_bar(day2 + timedelta(hours=8, minutes=15 * i), 1.50, 0.80))
    return {"M15": tuple(m15), "H4": h4, "D1": d1}


class TestCausalityCuts:
    ENTRY = datetime(2017, 1, 3, 10, 0, tzinfo=UTC)

    def _cands(self, frames, direction, entry=None):
        geo = EntryGeometry(direction, 1.05, 1.04 if direction == Direction.BULL
                            else 1.06)
        return _natural_candidates(build_symbol_context(frames), geo,
                                   entry or self.ENTRY)

    def test_future_swing_rejected_long(self, manual_frames):
        c = self._cands(manual_frames, Direction.BULL)
        # 1.20 swing is confirmed only at 2017-01-03 16:00 (future) -> 1.10
        price, created = c["NT01_NEXT_CONFIRMED_STRUCTURAL_SWING"]
        assert price == 1.10
        assert created == datetime(2017, 1, 2, 20, 0, tzinfo=UTC)
        assert created <= self.ENTRY

    def test_swing_visible_after_confirmation(self, manual_frames):
        late = datetime(2017, 1, 3, 22, 0, tzinfo=UTC)
        c = self._cands(manual_frames, Direction.BULL, entry=late)
        # once confirmed (16:00 <= 22:00) the most recent swing is 1.20
        assert c["NT01_NEXT_CONFIRMED_STRUCTURAL_SWING"][0] == 1.20

    def test_future_pdh_rejected_long(self, manual_frames):
        c = self._cands(manual_frames, Direction.BULL)
        # Jan 3's own 1.20 high (closes Jan 4) must NOT be used -> Jan 2 1.12
        price, created = c["NT02_PREVIOUS_DAY_DIRECTIONAL_EXTREME"]
        assert price == 1.12
        assert created == datetime(2017, 1, 3, 0, 0, tzinfo=UTC)

    def test_incomplete_session_rejected_long(self, manual_frames):
        c = self._cands(manual_frames, Direction.BULL)
        # LONDON (running, 1.50 high) is NOT completed at 10:00 -> ASIAN 1.08
        price, created = c["NT03_OPPOSITE_SESSION_LIQUIDITY"]
        assert price == 1.08
        assert created == datetime(2017, 1, 3, 8, 0, tzinfo=UTC)

    def test_short_directional_validity(self, manual_frames):
        c = self._cands(manual_frames, Direction.BEAR)
        assert c["NT01_NEXT_CONFIRMED_STRUCTURAL_SWING"][0] == 0.96   # < entry
        assert c["NT02_PREVIOUS_DAY_DIRECTIONAL_EXTREME"][0] == 1.00  # PDL
        assert c["NT03_OPPOSITE_SESSION_LIQUIDITY"][0] == 1.01        # ASIAN low

    def test_long_candidates_all_beyond_entry(self, manual_frames):
        c = self._cands(manual_frames, Direction.BULL)
        for family, cand in c.items():
            if cand is not None:
                assert cand[0] > 1.05, family

    def test_nt05_order_block_fail_closed(self, manual_frames):
        for direction in (Direction.BULL, Direction.BEAR):
            c = self._cands(manual_frames, direction)
            assert c["NT05_NEXT_VALID_ORDER_BLOCK"] is None
        assert FAMILY_CONTRACTS["NT05_NEXT_VALID_ORDER_BLOCK"]["status"] == \
            "TARGET_FAMILY_CONTRACT_INCOMPLETE"


# ---------------------------------------------------------------------------
# frozen upstream unchanged
# ---------------------------------------------------------------------------

class TestFrozenUpstream:
    def test_stop_and_entry_geometry_constants_unchanged(self):
        assert STOP_LOOKBACK_BARS == 12
        assert CONFIRMATION_WINDOW_BARS == 16
        assert OUTCOME_HORIZON_BARS == 96
        assert tuple(FIXED_R_TARGETS) == (1, 2, 3, 4, 5)

    def test_development_partition_unchanged(self):
        start, end = PARTITIONS["DEVELOPMENT"]
        assert start.isoformat().startswith("2017-01-01")
        assert end.isoformat().startswith("2017-09-01")

    def test_parent_v04_artifacts_unchanged(self):
        fr = json.load(open("data/artifacts/universal_funnel_v0_4_trigger/"
                            "final_report.json"))
        assert fr["directional_n"]["D01"] == 9226
        assert fr["directional_n"]["T1"] == 899
        assert fr["separation_pp"]["D01"] == 2.04
        assert fr["separation_pp"]["T1"] == 7.55


# ---------------------------------------------------------------------------
# fixed/natural 5% tolerance boundaries (§9)
# ---------------------------------------------------------------------------

class TestFitRatioRule:
    def test_bands(self):
        assert fit_class_for(2, 2.0)[0] == "FIXED_TARGET_NEAR_NATURAL"
        assert fit_class_for(2, 2.2)[0] == "FIXED_TARGET_BELOW_NATURAL"
        assert fit_class_for(2, 1.8)[0] == "FIXED_TARGET_ABOVE_NATURAL"

    def test_boundaries_inclusive(self):
        assert fit_class_for(2, 2.0 / 0.95)[0] == "FIXED_TARGET_NEAR_NATURAL"
        assert fit_class_for(2, 2.0 / 1.05)[0] == "FIXED_TARGET_NEAR_NATURAL"

    @pytest.mark.parametrize("bad", [None, 0.0, -1.0, float("inf"), float("nan")])
    def test_invalid_natural_is_null_with_reason(self, bad):
        cls, reason = fit_class_for(2, bad)
        assert cls is None
        assert reason == "INVALID_OR_UNAVAILABLE_NATURAL_TARGET"


# ---------------------------------------------------------------------------
# reached-before-SL semantics / same-bar collision fail-closed (§6, §11)
# ---------------------------------------------------------------------------

class TestStopFirstCollision:
    GEO = EntryGeometry(Direction.BULL, 1.0, 0.99)   # risk = 0.01

    def test_same_bar_stop_and_target_is_invalidated(self):
        bars = [_m15bar(1, 1.0, 1.05, 0.985, 1.0)]
        reached, invalidated, beyond, t, mfe, mae = _target_reachability_impl(
            bars, self.GEO, 1.01)
        assert (reached, invalidated, beyond) == (False, True, False)
        assert t is None and mfe is None and mae is None

    def test_target_reached_with_timing_and_pre_excursions(self):
        bars = [_m15bar(1, 1.0, 1.004, 0.997, 1.0),   # mfe .4R, mae .3R
                _m15bar(2, 1.0, 1.012, 0.995, 1.01)]  # target 1.01 on bar 2
        reached, invalidated, beyond, t, mfe, mae = _target_reachability_impl(
            bars, self.GEO, 1.01)
        assert reached and not invalidated and not beyond
        assert t == 2
        assert mfe == pytest.approx(0.4)
        assert mae == pytest.approx(0.3)

    def test_untouched_target_is_beyond_window(self):
        bars = [_m15bar(i, 1.0, 1.001, 0.999, 1.0) for i in range(1, 10)]
        out = _target_reachability_impl(bars, self.GEO, 1.05)
        assert out[:3] == (False, False, True)

    def test_time_to_mirrors_stop_first(self):
        bars = [_m15bar(1, 1.0, 1.05, 0.985, 1.0)]
        out = _time_to_targets(bars, self.GEO)
        assert all(v is None for v in out.values())


# ---------------------------------------------------------------------------
# fabricated-entry helper
# ---------------------------------------------------------------------------

def mk_entry(nearest_r=0.5, reached=True, fixed=None, symbol="EURUSD",
             direction="BULL", risk=0.001, nearest_distance=None,
             ladder_extra=(), second=None, second_reached=None,
             third=None, third_reached=None, is_t1=False,
             mfe_r=1.0, mae_r=0.5, session="LONDON") -> EntryRecord:
    fixed = fixed or {}
    has = nearest_r is not None
    if nearest_distance is None and has:
        nearest_distance = nearest_r * risk
    ladder = ()
    furthest = (None, None, None)
    if has:
        rows = [("NT01_NEXT_CONFIRMED_STRUCTURAL_SWING",
                 1.0 + nearest_distance, nearest_r, bool(reached))]
        for r, hit in ladder_extra:
            rows.append(("NT02_PREVIOUS_DAY_DIRECTIONAL_EXTREME",
                         1.0 + r * risk, r, bool(hit)))
        ladder = tuple(sorted(rows, key=lambda row: (row[2], row[0])))
        furthest = (ladder[-1][0], ladder[-1][2], ladder[-1][3])
    pip_size, pip_unit = tv5.PIP_OR_POINT.get(symbol, (None, None))
    return EntryRecord(
        symbol=symbol, obs_feed_index=0, entry_index=0, entry_time=T0,
        direction=direction, session=session,
        entry_price=1.0, stop_price=1.0 - risk, risk_distance=risk,
        risk_distance_pips_or_points=(risk / pip_size) if pip_size else None,
        pip_or_point_unit=pip_unit,
        mfe_r=mfe_r, mae_r=mae_r,
        mfe_distance=mfe_r * risk, mae_distance=mae_r * risk,
        fixed_reached={k: bool(fixed.get(k, False)) for k in FIXED_R_TARGETS},
        time_to_r={k: None for k in FIXED_R_TARGETS},
        entry_class="STOP_BEFORE_1R",
        targets={f: None for f in NATURAL_FAMILIES},
        nearest_family=ladder[0][0] if ladder else None,
        nearest_price=(1.0 + nearest_distance) if has else None,
        nearest_distance=nearest_distance if has else None,
        nearest_target_r=nearest_r,
        nearest_reached=bool(reached) if has else None,
        ladder=ladder, multi_objective=len({r[2] for r in ladder}) >= 2,
        furthest_family=furthest[0], furthest_target_r=furthest[1],
        furthest_reached=furthest[2],
        second_target_r=second, second_reached=second_reached,
        third_target_r=third, third_reached=third_reached,
        is_t1=is_t1, is_t2=False)


# ---------------------------------------------------------------------------
# multi-objective ordering / delivery (§12)
# ---------------------------------------------------------------------------

class TestMultiObjective:
    def test_counts_and_conditionals(self):
        rows = []
        for i in range(10):     # multi: first reached, second reached
            rows.append(mk_entry(nearest_r=0.5, reached=True,
                                 ladder_extra=((1.5, True),), second=1.5,
                                 second_reached=True, fixed={1: True, 2: True}))
        for i in range(10):     # multi: first reached, second not
            rows.append(mk_entry(nearest_r=0.5, reached=True,
                                 ladder_extra=((1.5, False),), second=1.5,
                                 second_reached=False, fixed={1: True}))
        for i in range(10):     # single objective, not reached
            rows.append(mk_entry(nearest_r=0.8, reached=False))
        out = multi_objective_delivery(rows)
        assert out["ONE_OBJECTIVE_AVAILABLE_N"] == 10
        assert out["MULTI_OBJECTIVE_AVAILABLE_N"] == 20
        assert out["FIRST_OBJECTIVE_REACHED_PCT"] == pytest.approx(20 / 30)
        assert out["SECOND_OBJECTIVE_REACHED_PCT"] == pytest.approx(0.5)
        assert out["P_SECOND_GIVEN_FIRST"] == pytest.approx(0.5)
        assert out["P_2R_GIVEN_FIRST_OBJECTIVE"] == pytest.approx(0.5)

    def test_unavailable_target_is_null_not_loss(self):
        rows = [mk_entry(nearest_r=None) for _ in range(5)]
        fam = family_report(rows)
        nt1 = fam["NT01_NEXT_CONFIRMED_STRUCTURAL_SWING"]
        assert nt1["AVAILABLE_N"] == 0
        assert nt1["REACHED_BEFORE_SL_PCT"] is None      # NULL, never 0/loss
        mo = multi_objective_delivery(rows)
        assert mo["FIRST_OBJECTIVE_REACHED_PCT"] is None


# ---------------------------------------------------------------------------
# correlations (§14)
# ---------------------------------------------------------------------------

class TestCorrelations:
    def test_pearson_spearman_and_floor(self):
        xs = list(range(40))
        ys = [2.0 * x + 1.0 for x in xs]
        assert _pearson(xs, ys) == pytest.approx(1.0)
        assert _pearson(xs[:10], ys[:10]) is None
        assert _spearman(list(range(1, 41)), [x ** 3 for x in range(1, 41)]) \
            == pytest.approx(1.0)
        assert _ranks([10.0, 20.0, 20.0, 30.0]) == [1.0, 2.5, 2.5, 4.0]

    def test_mechanical_coupling_label(self):
        rows = [mk_entry(nearest_r=0.5 + i * 0.01, risk=0.001 + i * 1e-5)
                for i in range(40)]
        out = coupling_correlations(rows)
        pair = out["RISK_VS_PRIMARY_TARGET_R"]
        assert pair["label"] == "MECHANICALLY_COUPLED_DIAGNOSTIC"
        assert pair["pooled_pearson"] is None
        assert pair["pooled_pearson_reason"] == "CROSS_SYMBOL_PRICE_SCALE_MIX"


class TestStopTargetGeometry:
    def test_yes_when_gradient_and_no_raw_coscaling(self):
        rows = [mk_entry(risk=0.001 * (1 + i / 25.0), nearest_distance=0.002,
                         nearest_r=0.002 / (0.001 * (1 + i / 25.0)))
                for i in range(200)]
        out = stop_target_geometry(rows)
        assert out["q1_over_q4_ratio"] > tv5.SL_INTERACTION_RATIO
        # constant raw target distance: rank correlation is undefined (never
        # numeric zero) and the structured interpretation is NO_RAW_COSCALING
        assert out["risk_vs_target_distance_rank_spearman"] is None
        assert out["correlations"]["RISK_VS_TARGET_DISTANCE"][
            "pooled_within_symbol_rank_spearman_reason"] == "ZERO_VARIANCE"
        assert out["raw_coscaling_interpretation"] == "NO_RAW_COSCALING"
        assert out["SL_TARGET_GEOMETRY_INTERACTION"] == "YES"
        assert out["risk_distance_atr_normalized"] is None   # no ATR authority

    def test_no_when_raw_distances_co_scale(self):
        rows = [mk_entry(risk=0.001 * (1 + i / 25.0),
                         nearest_distance=0.002 * (1 + i / 25.0), nearest_r=2.0)
                for i in range(200)]
        out = stop_target_geometry(rows)
        assert out["SL_TARGET_GEOMETRY_INTERACTION"] == "NO"


class TestZeroVarianceCorrelationContract:
    """Undefined correlation is never coerced to numeric zero."""

    ZERO = CorrelationResult(None, "ZERO_VARIANCE", "NO_RAW_COSCALING")
    XS = [float(i) for i in range(40)]
    CONST = [1.0] * 40

    @pytest.mark.parametrize("fn", [pearson_result, spearman_result])
    def test_x_constant(self, fn):
        assert fn(self.CONST, self.XS) == self.ZERO

    @pytest.mark.parametrize("fn", [pearson_result, spearman_result])
    def test_y_constant(self, fn):
        assert fn(self.XS, self.CONST) == self.ZERO

    @pytest.mark.parametrize("fn", [pearson_result, spearman_result])
    def test_both_constant(self, fn):
        assert fn(self.CONST, [2.0] * 40) == self.ZERO

    @pytest.mark.parametrize("legacy", [_pearson, _spearman])
    def test_legacy_float_api_returns_none_not_zero(self, legacy):
        assert legacy(self.CONST, self.XS) is None
        assert legacy(self.XS, self.CONST) is None
        assert legacy(self.CONST, [2.0] * 40) is None

    def test_insufficient_population(self):
        res = pearson_result(self.XS[:10], self.XS[:10])
        assert res == CorrelationResult(None, "INSUFFICIENT_POPULATION",
                                        "INSUFFICIENT_EVIDENCE")
        assert spearman_result(self.XS[:10], self.XS[:10]).value is None

    def test_nonconstant_positive(self):
        p = pearson_result(self.XS, [2.0 * x + 1.0 for x in self.XS])
        s = spearman_result(self.XS, [x ** 3 for x in self.XS])
        for res in (p, s):
            assert res.value == pytest.approx(1.0)
            assert res.reason is None and res.interpretation == "DEFINED"
        assert _pearson(self.XS, [2.0 * x + 1.0 for x in self.XS])             == pytest.approx(p.value)

    def test_nonconstant_weak(self):
        # y alternates 0/1 over x = 0..39: cov = 10, Sxx = 5330, Syy = 10
        ys = [float(i % 2) for i in range(40)]
        expected = 10.0 / (5330.0 * 10.0) ** 0.5
        for fn, legacy in ((pearson_result, _pearson),
                           (spearman_result, _spearman)):
            res = fn(self.XS, ys)
            assert res.value == pytest.approx(expected)
            assert res.reason is None and res.interpretation == "DEFINED"
            assert abs(res.value) < tv5.RAW_COSCALING_RHO
            assert legacy(self.XS, ys) == pytest.approx(expected)

    def test_stop_target_constant_target_distance(self):
        risks = [0.001 * (1 + i / 25.0) for i in range(200)]
        rows = [mk_entry(risk=r, nearest_distance=0.002, nearest_r=0.002 / r)
                for r in risks]
        targets = [e.nearest_distance for e in rows]
        assert len(set(targets)) == 1            # target variance == 0
        assert len(set(e.risk_distance for e in rows)) > 1   # stop variance > 0
        out = stop_target_geometry(rows)
        pair = out["correlations"]["RISK_VS_TARGET_DISTANCE"]
        assert out["risk_vs_target_distance_rank_spearman"] is None
        assert pair["pooled_within_symbol_rank_spearman"] is None
        assert pair["pooled_within_symbol_rank_spearman_reason"] == "ZERO_VARIANCE"
        assert out["raw_coscaling_interpretation"] == "NO_RAW_COSCALING"
        assert out["SL_TARGET_GEOMETRY_INTERACTION"] == "YES"

    def test_stop_target_nonconstant_coscaling_is_defined(self):
        rows = [mk_entry(risk=0.001 * (1 + i / 25.0),
                         nearest_distance=0.002 * (1 + i / 25.0), nearest_r=2.0)
                for i in range(200)]
        out = stop_target_geometry(rows)
        assert out["risk_vs_target_distance_rank_spearman"] == pytest.approx(1.0)
        assert out["correlations"]["RISK_VS_TARGET_DISTANCE"][
            "pooled_within_symbol_rank_spearman_reason"] is None
        assert out["raw_coscaling_interpretation"] == "DEFINED"


# ---------------------------------------------------------------------------
# root-cause classifier (§17) and T1 effect (§15)
# ---------------------------------------------------------------------------

def _sl(interaction="NO", ratio=1.0):
    return {"SL_TARGET_GEOMETRY_INTERACTION": interaction,
            "q1_over_q4_ratio": ratio,
            "risk_vs_target_distance_rank_spearman": 0.1}


class TestRootCauseClassifier:
    def test_case_a_mismatch(self):
        rows = [mk_entry(nearest_r=0.3, reached=True) for _ in range(150)]
        rc = root_cause_cases(population_target_report(rows), _sl())
        assert rc["PRIMARY_DIAGNOSIS"] == "A_TARGET_MODEL_MISMATCH"
        assert rc["NEXT_FUNNEL_TO_TEST"] == "NATURAL_TARGET_EXPERIMENT"

    def test_case_c_takes_precedence(self):
        rows = [mk_entry(nearest_r=6.0, reached=(i % 5 < 2),
                         fixed={1: True}) for i in range(150)]
        rc = root_cause_cases(population_target_report(rows), _sl())
        assert rc["cases"]["C_FIXED_5R_SUPPORTED"]["true"]
        assert rc["PRIMARY_DIAGNOSIS"] == "C_FIXED_5R_SUPPORTED"
        assert rc["NEXT_FUNNEL_TO_TEST"] == "FIXED_R_TARGET_EXPERIMENT"

    def test_case_b_deep_objectives_fail(self):
        # 3.5R objectives exist for all entries but only 10% delivered; the
        # first objective is commonly NOT reached either (A leg 3 fails)
        rows = [mk_entry(nearest_r=3.5, reached=(i % 10 == 0))
                for i in range(150)]
        rc = root_cause_cases(population_target_report(rows), _sl())
        assert rc["cases"]["B_TARGET_CONTINUATION_WEAKNESS"]["true"]
        assert not rc["cases"]["A_TARGET_MODEL_MISMATCH"]["true"]
        assert rc["PRIMARY_DIAGNOSIS"] == "B_TARGET_CONTINUATION_WEAKNESS"

    def test_case_d_runner_hypothesis_with_a(self):
        rows = [mk_entry(nearest_r=0.5, reached=(i % 10 < 7),
                         ladder_extra=((1.5, i % 10 < 4),), second=1.5,
                         second_reached=(i % 10 < 4)) for i in range(150)]
        rc = root_cause_cases(population_target_report(rows), _sl())
        assert rc["cases"]["A_TARGET_MODEL_MISMATCH"]["true"]
        assert rc["cases"]["D_PARTIAL_TARGET_PLUS_RUNNER_HYPOTHESIS"]["true"]
        assert rc["PRIMARY_DIAGNOSIS"] == "A_TARGET_MODEL_MISMATCH"
        # A + D => runner experiment recommended
        assert rc["NEXT_FUNNEL_TO_TEST"] == "NATURAL_TARGET_PLUS_RUNNER_EXPERIMENT"

    def test_small_population_insufficient(self):
        rows = [mk_entry() for _ in range(50)]
        rc = root_cause_cases(population_target_report(rows), _sl())
        assert rc["PRIMARY_DIAGNOSIS"] == "TARGET_FAMILY_INSUFFICIENT"

    def test_guards_present(self):
        rows = [mk_entry(nearest_r=0.3, reached=True) for _ in range(150)]
        rc = root_cause_cases(population_target_report(rows), _sl())
        assert rc["no_tp_changed"] and rc["no_sl_changed"]
        assert rc["no_partial_exits_implemented"] and rc["no_parameter_search"]


class TestT1Effect:
    def _report(self, p50, f50, first, psec, n=200, one_r=0.5):
        return {"entry_n": n,
                "primary_target_r_quantiles": {"P50": p50},
                "furthest_target_r_quantiles": {"P50": f50},
                "multi_objective_delivery": {
                    "FIRST_OBJECTIVE_REACHED_PCT": first,
                    "SECOND_OBJECTIVE_REACHED_PCT": psec,
                    "P_SECOND_GIVEN_FIRST": psec},
                "fixed_surface": {"reach": {f"{k}R": one_r for k in (2, 3, 4, 5)}}}

    def test_geometry_improved(self):
        eff = d01_vs_t1_effect(self._report(1.0, 3.0, 0.5, 0.5),
                               self._report(1.4, 3.1, 0.5, 0.5))
        assert eff["T1_TARGET_GEOMETRY_EFFECT"] == "IMPROVED"
        assert "A_IMPROVES_TARGET_GEOMETRY" in eff["verdicts"]

    def test_deep_continuation_degraded(self):
        eff = d01_vs_t1_effect(self._report(1.0, 3.0, 0.5, 0.60),
                               self._report(1.0, 3.0, 0.5, 0.50))
        assert eff["T1_DEEP_CONTINUATION_EFFECT"] == "DEGRADED"
        assert "D_DAMAGES_DEEP_CONTINUATION" in eff["verdicts"]

    def test_only_direction_when_nothing_improves(self):
        eff = d01_vs_t1_effect(self._report(1.0, 3.0, 0.5, 0.5),
                               self._report(1.0, 3.0, 0.5, 0.5))
        assert eff["verdicts"] == ["C_ONLY_IMPROVES_INITIAL_DIRECTION"]

    def test_insufficient_when_t1_small(self):
        eff = d01_vs_t1_effect(self._report(1.0, 3.0, 0.5, 0.5),
                               self._report(1.5, 3.5, 0.9, 0.9, n=50))
        assert eff["verdicts"] == ["E_INSUFFICIENT_EVIDENCE"]


class TestContinuationChain:
    def test_earliest_material_deterioration(self):
        rows = [mk_entry(fixed={1: i < 80, 2: i < 40, 3: i < 30})
                for i in range(100)]
        out = continuation_chain(rows)
        assert out["chain"]["P2_GIVEN_1"] == pytest.approx(0.50)
        assert out["earliest_material_deterioration"] == "P2_GIVEN_1"
        assert out["no_trading_rule_derived"] is True


# ---------------------------------------------------------------------------
# end-to-end on synthetic frames: ordering, causality, persistence
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def synth():
    m5 = make_synthetic_fx_bars(days=60, seed=11)
    m15, _ = aggregate_bars(m5, "M5", "M15")
    frames = {"M15": m15}
    for tf in ("H1", "H4", "D1"):
        frames[tf], _ = derive_fx_timeframe(m15, tf, "SYNTH")
    campaign = run_fx_symbol_campaign(frames, "SYNTH",
                                      m15[0].timestamp, m15[-1].timestamp)
    enriched = enrich_symbol(frames, campaign, m15[0].timestamp,
                             m15[-1].timestamp)
    return frames, build_entry_records(frames, campaign, enriched)


class TestBuildInvariants:
    def test_targets_known_at_entry(self, synth):
        _, records = synth
        assert len(records) > 50
        for rec in records:
            for t in rec.targets.values():
                if t is None:
                    continue
                assert t.created_time <= rec.entry_time
                assert t.target_r > 0 and t.distance > 0

    def test_directional_validity_both_sides(self, synth):
        _, records = synth
        seen = {"BULL": 0, "BEAR": 0}
        for rec in records:
            seen[rec.direction] += 1
            for t in rec.targets.values():
                if t is None:
                    continue
                if rec.direction == "BULL":
                    assert t.price > rec.entry_price
                else:
                    assert t.price < rec.entry_price
        assert seen["BULL"] and seen["BEAR"]

    def test_nearest_and_ladder_ordering(self, synth):
        _, records = synth
        for rec in records:
            rs = [row[2] for row in rec.ladder]
            assert rs == sorted(rs)
            if rec.ladder:
                assert rec.nearest_family == rec.ladder[0][0]
                assert rec.nearest_target_r == rec.ladder[0][2]
                assert rec.furthest_target_r == rec.ladder[-1][2]
            if rec.second_target_r is not None:
                assert rec.second_target_r > rec.nearest_target_r
            if rec.third_target_r is not None:
                assert rec.third_target_r > rec.second_target_r

    def test_nt05_never_available(self, synth):
        _, records = synth
        assert all(r.targets["NT05_NEXT_VALID_ORDER_BLOCK"] is None
                   for r in records)

    def test_time_to_consistent_with_fixed_reach(self, synth):
        _, records = synth
        for rec in records:
            for k in FIXED_R_TARGETS:
                assert (rec.time_to_r[k] is not None) == \
                    bool(rec.fixed_reached.get(k, False))

    def test_future_mutation_and_truncation_invariance(self, synth):
        frames, records = synth
        for rec in records[:: max(1, len(records) // 6)]:
            geometry = EntryGeometry(Direction(rec.direction), rec.entry_price,
                                     rec.stop_price)
            expected = {f: (t.price, t.created_time) if t else None
                        for f, t in rec.targets.items()}
            mut, trunc = {}, {}
            for tf, minutes in (("M15", 15), ("H4", 240), ("D1", 1440)):
                span = timedelta(minutes=minutes)
                mut[tf] = tuple(
                    b if b.timestamp + span <= rec.entry_time else
                    MarketBar(timestamp=b.timestamp, open=b.open * 1.1,
                              high=b.high * 1.1, low=b.low * 1.1,
                              close=b.close * 1.1)
                    for b in frames[tf])
                trunc[tf] = bars_closed_at(frames[tf], tf, rec.entry_time)
            for variant in (mut, trunc):
                ctx = build_symbol_context(variant)
                got = _natural_candidates(ctx, geometry, rec.entry_time)
                assert got == expected

    def test_candidate_ledger_contract(self, synth):
        _, records = synth
        rows = candidate_ledger_rows(records[:10])
        assert len(rows) == 10 * len(NATURAL_FAMILIES)
        for row in rows:
            assert row["candidate_id"].count(":") == 2
            if row["target_family"] == "NT05_NEXT_VALID_ORDER_BLOCK":
                assert row["available"] is False
                assert row["reason"] == "TARGET_FAMILY_CONTRACT_INCOMPLETE"
            if row["available"]:
                assert row["causal_at_entry"] is True
                assert row["target_R"] > 0
            else:
                assert row["target_R"] is None       # NULL, never a loss

    def test_ladder_rows_contract(self, synth):
        _, records = synth
        for row in ladder_rows(records[:10]):
            rs = [c["target_R"] for c in row["target_ladder"]]
            assert rs == sorted(rs)
            if row["primary_target_family"] is not None:
                assert row["selection_reason"] == SELECTION_REASON
                assert row["primary_target_R"] == rs[0]
                assert row["furthest_target_R"] == rs[-1]

    def test_deterministic_serialization(self, synth):
        _, records = synth
        a = json.dumps(candidate_ledger_rows(records[:50]), sort_keys=True,
                       default=str)
        b = json.dumps(candidate_ledger_rows(records[:50]), sort_keys=True,
                       default=str)
        assert a == b
