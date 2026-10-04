"""V0.5 TARGET MODEL DIAGNOSTICS — unit tests (A-J governance hardening).

All tests are synthetic/deterministic; no dataset required.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.derive import aggregate_bars
from ag_edgelab.data.fx_histdata_2017 import bars_closed_at, derive_fx_timeframe
from ag_edgelab.universal.campaign import make_synthetic_fx_bars
from ag_edgelab.universal.direction import Direction
from ag_edgelab.universal.fx_dev_campaign import run_fx_symbol_campaign
from ag_edgelab.universal.targets import EntryGeometry, FIXED_R_TARGETS
from ag_edgelab.universal.trigger_v0_4 import enrich_symbol
from ag_edgelab.universal import target_v0_5 as tv5
from ag_edgelab.universal.target_v0_5 import (
    EntryRecord, MIN_CORR_N, NATURAL_FAMILIES, SELECTION_REASON,
    _natural_candidates, _pearson, _ranks, _spearman, _target_reachability_impl,
    _time_to_targets, build_entry_records, build_symbol_context,
    continuation_chain, coupling_correlations, direction_asymmetry,
    entry_ledger_rows, fit_class_for, fit_classification, level_verdict,
    objective_ladder_report, root_cause, sl_target_interaction,
    stratum_diagnosis)

UTC = timezone.utc
T0 = datetime(2017, 1, 2, tzinfo=UTC)


def _bar(i: int, o: float, h: float, lo: float, c: float) -> MarketBar:
    return MarketBar(timestamp=T0 + timedelta(minutes=15 * i),
                     open=o, high=h, low=lo, close=c)


def mk_entry(nearest_r=0.5, reached=True, fixed=None, symbol="EURUSD",
             direction="BULL", risk=0.001, nearest_distance=None,
             second=None, second_reached=None, extended=None,
             extended_reached=None, max_r=None, max_reached=None,
             multi=False, is_t1=False, mfe_r=1.0, mae_r=0.5,
             session="LONDON") -> EntryRecord:
    fixed = fixed or {}
    has_nearest = nearest_r is not None
    if nearest_distance is None and has_nearest:
        nearest_distance = nearest_r * risk
    pip = tv5.PIP_SIZE.get(symbol)
    return EntryRecord(
        symbol=symbol, obs_feed_index=0, entry_index=0, entry_time=T0,
        direction=direction, session=session,
        entry_price=1.0, stop_price=1.0 - risk, risk_distance=risk,
        risk_distance_pips=(risk / pip) if pip else None,
        mfe_r=mfe_r, mae_r=mae_r,
        mfe_distance=mfe_r * risk, mae_distance=mae_r * risk,
        fixed_reached={k: bool(fixed.get(k, False)) for k in FIXED_R_TARGETS},
        time_to_r={k: None for k in FIXED_R_TARGETS},
        entry_class="STOP_BEFORE_1R",
        targets={f: None for f in NATURAL_FAMILIES},
        nearest_family="NT01_NEXT_SWING" if has_nearest else None,
        nearest_price=(1.0 + nearest_distance) if has_nearest else None,
        nearest_distance=nearest_distance if has_nearest else None,
        nearest_target_r=nearest_r,
        nearest_reached=reached if has_nearest else None,
        ladder=(), multi_objective=multi,
        max_family="NT02_PDH_PDL" if max_r is not None else None,
        max_target_r=max_r, max_reached=max_reached,
        second_target_r=second, second_reached=second_reached,
        extended_target_r=extended, extended_reached=extended_reached,
        is_t1=is_t1, is_t2=False)


# ---------------------------------------------------------------------------
# A. preregistered ratio fit tolerance (5%)
# ---------------------------------------------------------------------------

class TestFitRatioRule:
    def test_near_at_exact_match(self):
        assert fit_class_for(2, 2.0) == ("FIXED_TARGET_NEAR_NATURAL", None)

    def test_below_when_ratio_under_095(self):
        # ratio = 2 / 2.2 = 0.909 < 0.95
        assert fit_class_for(2, 2.2)[0] == "FIXED_TARGET_BELOW_NATURAL"

    def test_above_when_ratio_over_105(self):
        # ratio = 2 / 1.8 = 1.111 > 1.05
        assert fit_class_for(2, 1.8)[0] == "FIXED_TARGET_ABOVE_NATURAL"

    def test_boundaries_inclusive(self):
        # ratio exactly 0.95 and 1.05 are NEAR (inclusive band)
        assert fit_class_for(2, 2.0 / 0.95)[0] == "FIXED_TARGET_NEAR_NATURAL"
        assert fit_class_for(2, 2.0 / 1.05)[0] == "FIXED_TARGET_NEAR_NATURAL"

    @pytest.mark.parametrize("bad", [None, 0.0, -1.0, float("inf"), float("nan")])
    def test_invalid_natural_is_null_with_reason(self, bad):
        cls, reason = fit_class_for(2, bad)
        assert cls is None
        assert reason == "INVALID_OR_UNAVAILABLE_NATURAL_TARGET"

    def test_classification_counts_null_separately(self):
        entries = [mk_entry(nearest_r=2.0), mk_entry(nearest_r=None),
                   mk_entry(nearest_r=0.5)]
        out = fit_classification(entries, 2)
        assert out["NULL_N"] == 1
        assert out["FIXED_TARGET_NEAR_NATURAL_N"] == 1
        assert out["FIXED_TARGET_ABOVE_NATURAL_N"] == 1
        assert out["null_reason"] == "INVALID_OR_UNAVAILABLE_NATURAL_TARGET"
        assert out["tolerance_pct"] == 5.0


# ---------------------------------------------------------------------------
# stop-first collision semantics
# ---------------------------------------------------------------------------

class TestStopFirstCollision:
    GEO = EntryGeometry(Direction.BULL, 1.0, 0.99)   # risk = 0.01

    def test_stop_and_target_same_bar_is_invalidated(self):
        bars = [_bar(1, 1.0, 1.05, 0.985, 1.0)]      # both touched
        reached, invalidated, beyond = _target_reachability_impl(
            bars, self.GEO, 1.01)
        assert (reached, invalidated, beyond) == (False, True, False)

    def test_target_before_stop_bar_is_reached(self):
        bars = [_bar(1, 1.0, 1.012, 0.995, 1.01), _bar(2, 1.01, 1.02, 0.98, 0.99)]
        reached, invalidated, beyond = _target_reachability_impl(
            bars, self.GEO, 1.01)
        assert (reached, invalidated, beyond) == (True, False, False)

    def test_untouched_target_is_beyond_window(self):
        bars = [_bar(i, 1.0, 1.001, 0.999, 1.0) for i in range(1, 10)]
        reached, invalidated, beyond = _target_reachability_impl(
            bars, self.GEO, 1.05)
        assert (reached, invalidated, beyond) == (False, False, True)

    def test_time_to_mirrors_stop_first(self):
        # 1R (1.01) and the stop are both touched on bar 1 -> no credit at all
        bars = [_bar(1, 1.0, 1.05, 0.985, 1.0)]
        out = _time_to_targets(bars, self.GEO)
        assert all(v is None for v in out.values())

    def test_time_to_offsets_are_one_based(self):
        bars = [_bar(1, 1.0, 1.005, 0.995, 1.0),     # nothing
                _bar(2, 1.0, 1.012, 0.995, 1.01)]    # 1R on 2nd forward bar
        out = _time_to_targets(bars, self.GEO)
        assert out[1] == 2 and out[2] is None


# ---------------------------------------------------------------------------
# G. correlation machinery
# ---------------------------------------------------------------------------

class TestCorrelations:
    def test_pearson_perfect_and_floor(self):
        xs = list(range(40))
        ys = [2.0 * x + 1.0 for x in xs]
        assert _pearson(xs, ys) == pytest.approx(1.0)
        assert _pearson(xs[:10], ys[:10]) is None          # below MIN_CORR_N

    def test_spearman_monotone_nonlinear(self):
        xs = list(range(1, 41))
        ys = [x ** 3 for x in xs]
        assert _spearman(xs, ys) == pytest.approx(1.0)

    def test_ranks_average_ties(self):
        assert _ranks([10.0, 20.0, 20.0, 30.0]) == [1.0, 2.5, 2.5, 4.0]

    def test_constant_series_returns_none(self):
        xs = [1.0] * 40
        ys = list(range(40))
        assert _pearson(xs, ys) is None

    def test_mechanical_coupling_label_present(self):
        entries = [mk_entry(nearest_r=0.5 + i * 0.01, risk=0.001 + i * 1e-5)
                   for i in range(MIN_CORR_N + 5)]
        out = coupling_correlations(entries)
        assert out["RISK_VS_TARGET_R"]["label"] == "MECHANICALLY_COUPLED_DIAGNOSTIC"
        assert out["RISK_VS_TARGET_R"]["pooled_pearson"] is None
        assert out["RISK_VS_TARGET_R"]["pooled_pearson_reason"] == \
            "CROSS_SYMBOL_PRICE_SCALE_MIX"


# ---------------------------------------------------------------------------
# level verdict + evidence floor
# ---------------------------------------------------------------------------

def _diag(support, realize, n_sup):
    return {"SUPPORT_pct": support, "REALIZE_when_supported_pct": realize,
            "natural_ge_level_n": n_sup}


class TestLevelVerdict:
    def test_both_when_geometry_and_continuation(self):
        assert level_verdict(_diag(0.10, 0.10, 50)) == "BOTH"

    def test_geometry_only(self):
        assert level_verdict(_diag(0.10, 0.60, 50)) == "TARGET_GEOMETRY_MISMATCH"

    def test_continuation_only(self):
        assert level_verdict(_diag(0.60, 0.10, 50)) == "CONTINUATION_FAILURE"

    def test_neither(self):
        assert level_verdict(_diag(0.60, 0.60, 50)) == "NEITHER"

    def test_realize_floor_blocks_continuation_assertion(self):
        # only 2 supported entries: continuation leg UNMEASURABLE, geometry
        # still decisive — never BOTH from n=2
        assert level_verdict(_diag(0.001, 0.0, 2)) == "TARGET_GEOMETRY_MISMATCH"
        assert level_verdict(_diag(0.001, 0.0, 2), apply_realize_floor=False) \
            == "BOTH"

    def test_floor_without_geometry_is_insufficient(self):
        assert level_verdict(_diag(0.60, 0.0, 2)) == "INSUFFICIENT_EVIDENCE"


# ---------------------------------------------------------------------------
# I. refined stratum diagnosis (three-leg mismatch rule)
# ---------------------------------------------------------------------------

class TestStratumDiagnosis:
    def test_small_stratum_is_insufficient(self):
        out = stratum_diagnosis([mk_entry() for _ in range(99)])
        assert out["diagnosis"] == "INSUFFICIENT_EVIDENCE"

    def test_family_insufficient_when_objectives_rare(self):
        rows = [mk_entry(nearest_r=None) for _ in range(80)] + \
               [mk_entry(nearest_r=0.5) for _ in range(40)]
        out = stratum_diagnosis(rows)
        assert out["diagnosis"] == "TARGET_FAMILY_INSUFFICIENT"

    def test_mismatch_requires_all_three_legs(self):
        # objectives exist, fixed 2R far beyond (natural 0.3R), objective
        # reachable (reached=True) -> clean mismatch
        rows = [mk_entry(nearest_r=0.3, reached=True) for _ in range(150)]
        out = stratum_diagnosis(rows)
        assert out["diagnosis"] == "TARGET_MODEL_MISMATCH"
        assert all(out["mismatch_evidence"][k] for k in (
            "leg1_objectives_frequently_exist", "leg2_fixed_frequently_beyond",
            "leg3_natural_objective_reachable"))

    def test_low_median_alone_is_never_mismatch(self):
        # natural median low BUT the objective itself is rarely reached:
        # leg 3 fails -> not a target-model mismatch; commonly-unreached
        # nearest objective is continuation evidence instead
        rows = [mk_entry(nearest_r=0.3, reached=(i % 10 == 0))
                for i in range(150)]
        out = stratum_diagnosis(rows)
        assert out["diagnosis"] == "TARGET_CONTINUATION_WEAKNESS"
        assert not out["mismatch_evidence"]["leg3_natural_objective_reachable"]

    def test_none_detected_when_geometry_supports_and_realizes(self):
        rows = [mk_entry(nearest_r=3.0, reached=True,
                         fixed={1: True, 2: True, 3: True})
                for _ in range(150)]
        out = stratum_diagnosis(rows)
        assert out["diagnosis"] == "NONE_DETECTED"


# ---------------------------------------------------------------------------
# chain deterioration (diagnostic only)
# ---------------------------------------------------------------------------

class TestContinuationChain:
    def test_earliest_material_deterioration(self):
        rows = []
        for i in range(100):
            rows.append(mk_entry(fixed={1: i < 80, 2: i < 40, 3: i < 30}))
        out = continuation_chain(rows)
        assert out["chain"]["P1"] == pytest.approx(0.80)
        assert out["chain"]["P2_GIVEN_1"] == pytest.approx(0.50)
        assert out["earliest_material_deterioration"] == "P2_GIVEN_1"
        assert out["no_trading_rule_derived"] is True


# ---------------------------------------------------------------------------
# H + G. SL/target interaction decision rule
# ---------------------------------------------------------------------------

class TestSlTargetInteraction:
    def test_yes_when_gradient_and_no_raw_coscaling(self):
        # constant raw target distance, widely varying risk: normalized R
        # gradient is pure denominator coupling -> interaction YES
        rows = [mk_entry(risk=0.001 * (1 + i / 25.0), nearest_distance=0.002,
                         nearest_r=0.002 / (0.001 * (1 + i / 25.0)))
                for i in range(200)]
        out = sl_target_interaction(rows)
        assert out["q1_over_q4_ratio"] > tv5.SL_INTERACTION_RATIO
        assert out["risk_vs_target_distance_rank_spearman"] < tv5.RAW_COSCALING_RHO
        assert out["SL_TARGET_GEOMETRY_INTERACTION"] == "YES"

    def test_no_when_raw_distances_co_scale(self):
        # raw target distance proportional to risk: R is flat, raw co-scaling
        # strong -> NO interaction
        rows = [mk_entry(risk=0.001 * (1 + i / 25.0),
                         nearest_distance=0.002 * (1 + i / 25.0), nearest_r=2.0)
                for i in range(200)]
        out = sl_target_interaction(rows)
        assert out["risk_vs_target_distance_rank_spearman"] > tv5.RAW_COSCALING_RHO
        assert out["SL_TARGET_GEOMETRY_INTERACTION"] == "NO"

    def test_quartile_table_fields(self):
        rows = [mk_entry(risk=0.001 + i * 1e-5, nearest_r=0.5,
                         fixed={1: True, 2: i % 2 == 0})
                for i in range(200)]
        out = sl_target_interaction(rows)
        for q in ("Q1", "Q2", "Q3", "Q4"):
            t = out["risk_quartile_target_analysis"][q]
            assert t["entry_n"] > 0
            for key in ("median_target_distance_price", "median_natural_target_r",
                        "median_mfe_r", "median_mae_r"):
                assert t[key] is not None
            assert set(t["fixed_reach"]) == {f"{k}R" for k in FIXED_R_TARGETS}


# ---------------------------------------------------------------------------
# direction asymmetry + root cause mapping
# ---------------------------------------------------------------------------

class TestVerdicts:
    def test_direction_asymmetry_thresholds(self):
        sym = direction_asymmetry({"nearest_p50_r": 1.0, "reach_2r": 0.30},
                                  {"nearest_p50_r": 1.2, "reach_2r": 0.31})
        assert sym["TARGET_GEOMETRY_DIRECTION_DEPENDENT"] is False
        asym = direction_asymmetry({"nearest_p50_r": 1.0, "reach_2r": 0.30},
                                   {"nearest_p50_r": 1.6, "reach_2r": 0.31})
        assert asym["TARGET_GEOMETRY_DIRECTION_DEPENDENT"] is True

    def _sl(self, interaction, ratio):
        return {"SL_TARGET_GEOMETRY_INTERACTION": interaction,
                "q1_over_q4_ratio": ratio,
                "risk_vs_target_distance_rank_spearman": 0.1,
                "decision_rule": "test"}

    def _pooled(self, diagnosis):
        return {"diagnosis": diagnosis, "mismatch_evidence": {},
                "continuation_evidence": {"levels_with_continuation_failure": [],
                                          "level_detail": {}}}

    def test_mismatch_maps_to_natural_target_policy(self):
        rc = root_cause(self._pooled("TARGET_MODEL_MISMATCH"), {},
                        {"TARGET_GEOMETRY_DIRECTION_DEPENDENT": False},
                        self._sl("NO", 1.0), 1000)
        assert rc["next_recommended_research"] == "PREREGISTER_NATURAL_TARGET_POLICY"

    def test_sl_override_requires_ratio_3(self):
        rc = root_cause(self._pooled("TARGET_MODEL_MISMATCH"), {},
                        {"TARGET_GEOMETRY_DIRECTION_DEPENDENT": False},
                        self._sl("YES", 2.8), 1000)
        assert rc["next_recommended_research"] == "PREREGISTER_NATURAL_TARGET_POLICY"
        assert "SL_TARGET_GEOMETRY_INTERACTION" in rc["secondary"]
        rc2 = root_cause(self._pooled("TARGET_MODEL_MISMATCH"), {},
                         {"TARGET_GEOMETRY_DIRECTION_DEPENDENT": False},
                         self._sl("YES", 3.5), 1000)
        assert rc2["next_recommended_research"] == "TEST_SL_TARGET_INTERACTION"

    def test_symbol_dependence_secondary(self):
        rc = root_cause(self._pooled("TARGET_MODEL_MISMATCH"),
                        {"EURUSD": {"diagnosis": "NONE_DETECTED"}},
                        {"TARGET_GEOMETRY_DIRECTION_DEPENDENT": False},
                        self._sl("NO", 1.0), 1000)
        assert "TARGET_GEOMETRY_SYMBOL_DEPENDENT" in rc["secondary"]

    def test_guards_always_present(self):
        rc = root_cause(self._pooled("NONE_DETECTED"), {},
                        {"TARGET_GEOMETRY_DIRECTION_DEPENDENT": False},
                        self._sl("NO", 1.0), 1000)
        assert rc["no_tp_changed"] and rc["no_sl_changed"] \
            and rc["no_parameter_search"]


# ---------------------------------------------------------------------------
# D/E. objective ladder + reach sequence
# ---------------------------------------------------------------------------

class TestObjectiveLadder:
    def test_report_fields(self):
        rows = [mk_entry(nearest_r=0.5, reached=True, second=1.5,
                         second_reached=True, extended=3.0,
                         extended_reached=False, max_r=3.0, max_reached=False,
                         multi=True) for _ in range(10)]
        rows += [mk_entry(nearest_r=0.8, reached=False, multi=False)
                 for _ in range(10)]
        out = objective_ladder_report(rows)
        assert out["MULTI_OBJECTIVE_ENTRY_PCT"] == pytest.approx(0.5)
        assert out["FIRST_OBJECTIVE_REACHED_PCT"] == pytest.approx(0.5)
        assert out["SECOND_OBJECTIVE_REACHED_PCT"] == pytest.approx(1.0)
        assert out["EXTENDED_OBJECTIVE_REACHED_PCT"] == pytest.approx(0.0)
        assert out["P_SECOND_REACHED_GIVEN_FIRST_REACHED"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# end-to-end on synthetic frames: build invariants, causality, persistence
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
    records = build_entry_records(frames, campaign, enriched)
    return frames, records


class TestBuildInvariants:
    def test_entries_exist(self, synth):
        _, records = synth
        assert len(records) > 50

    def test_targets_are_causal_and_eligible(self, synth):
        _, records = synth
        for rec in records:
            for t in rec.targets.values():
                if t is None:
                    continue
                assert t.created_time <= rec.entry_time
                assert t.target_r > 0 and t.distance > 0
                if rec.direction == "BULL":
                    assert t.price > rec.entry_price
                else:
                    assert t.price < rec.entry_price

    def test_ladder_sorted_and_nearest_is_first(self, synth):
        _, records = synth
        for rec in records:
            rs = [row[2] for row in rec.ladder]
            assert rs == sorted(rs)
            if rec.ladder:
                assert rec.nearest_family == rec.ladder[0][0]
                assert rec.nearest_target_r == rec.ladder[0][2]
                assert rec.max_target_r == rec.ladder[-1][2]
                assert rec.nearest_target_r <= rec.max_target_r
            if rec.second_target_r is not None:
                assert rec.second_target_r > rec.nearest_target_r
            if rec.extended_target_r is not None:
                assert rec.second_target_r is not None
                assert rec.extended_target_r >= rec.second_target_r

    def test_time_to_consistent_with_fixed_reach(self, synth):
        _, records = synth
        for rec in records:
            for k in FIXED_R_TARGETS:
                assert (rec.time_to_r[k] is not None) == \
                    bool(rec.fixed_reached.get(k, False))

    def test_pip_authority_fail_closed(self, synth):
        _, records = synth
        # SYNTH has no pip authority -> NULL, never zero
        assert all(rec.risk_distance_pips is None for rec in records)

    def test_future_mutation_and_truncation_invariance(self, synth):
        frames, records = synth
        for rec in records[:: max(1, len(records) // 6)]:
            geometry = EntryGeometry(Direction(rec.direction), rec.entry_price,
                                     rec.stop_price)
            expected = {f: (t.price, t.created_time) if t else None
                        for f, t in rec.targets.items()}
            mut = {"M15": frames["M15"]}
            trunc = {"M15": frames["M15"]}
            for tf, minutes in (("H4", 240), ("D1", 1440)):
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

    def test_entry_ledger_persists_each_family_separately(self, synth):
        _, records = synth
        rows = entry_ledger_rows(records[:25])
        assert len(rows) == 25
        for row in rows:
            assert set(row["targets"]) == set(NATURAL_FAMILIES)
            for family, cell in row["targets"].items():
                assert cell["target_family"] == family
                if cell["target_available"]:
                    assert cell["target_created_time"] is not None
                    assert cell["target_R"] > 0
                    assert cell["target_reached_before_SL"] in (True, False)
                else:
                    assert cell["target_R"] is None
                    assert cell["null_reason"] == \
                        "NO_CAUSALLY_VALID_TARGET_AT_ENTRY"
            assert row["RISK_DISTANCE_PIPS"] is None          # no pip authority
            if row["primary_target_family"] is not None:
                assert row["selection_reason"] == SELECTION_REASON
                ladder_rs = [c["target_R"] for c in row["objective_ladder"]]
                assert ladder_rs == sorted(ladder_rs)
                assert row["primary_target_R"] == ladder_rs[0]
                assert row["MAX_CAUSAL_OBJECTIVE_R"] == ladder_rs[-1]
