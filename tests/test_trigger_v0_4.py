"""V0.4 trigger research (MTF_DIRECTION_TRIGGER_V1) — contract tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ag_edgelab.data.derive import TIMEFRAME_MINUTES, aggregate_bars
from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.data.fx_histdata_2017 import bars_closed_at, derive_fx_timeframe
from ag_edgelab.universal.campaign import make_synthetic_fx_bars
from ag_edgelab.universal.direction import Direction
from ag_edgelab.universal.fx_dev_campaign import (INCOMPARABLE_REASON, build_series,
                                                  context_at, run_fx_symbol_campaign)
from ag_edgelab.universal.matrix import CAPABILITY_BASIS
from ag_edgelab.universal.trigger_v0_4 import (MIN_POLICY_DIRECTIONAL_N,
                                               MIN_POLICY_ENTERED_N, PHASES,
                                               RESEARCH_DIAGNOSTIC_THRESHOLD_PP,
                                               TRIGGER_POLICY_REGISTRY_SHA256,
                                               attrition, capability_deltas,
                                               confirmation_stability, enrich_symbol,
                                               interpret_policy, join_symbol,
                                               location_label, location_stability,
                                               ma_ablation, overall_interpretation,
                                               phase_distribution, phase_of,
                                               policy_metrics,
                                               pullback_realignment_report,
                                               session_label, t1_direction,
                                               t2_direction, t2ma_direction,
                                               target_distribution_shift)

BULL, BEAR, NEUT = Direction.BULL, Direction.BEAR, Direction.NEUTRAL
UTC = timezone.utc


# ---------------------------------------------------------------------------
# synthetic end-to-end fixture (frozen V0.3 engine + enrichment)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pipeline():
    m5 = make_synthetic_fx_bars(days=60, seed=11)
    m15, _ = aggregate_bars(m5, "M5", "M15")
    frames = {"M15": m15}
    for tf in ("H1", "H4", "D1"):
        frames[tf], _ = derive_fx_timeframe(m15, tf, "SYNTH")
    campaign = run_fx_symbol_campaign(frames, "SYNTH", m15[0].timestamp, m15[-1].timestamp)
    enriched = enrich_symbol(frames, campaign, m15[0].timestamp, m15[-1].timestamp)
    joined = join_symbol(campaign, enriched)
    return frames, campaign, enriched, joined


class TestPhaseModel:
    def test_all_five_phases(self):
        assert phase_of(BULL, BULL) == "BULL_CONTINUATION"
        assert phase_of(BULL, BEAR) == "BULL_PULLBACK"
        assert phase_of(BEAR, BEAR) == "BEAR_CONTINUATION"
        assert phase_of(BEAR, BULL) == "BEAR_PULLBACK"
        assert phase_of(NEUT, BULL) == "NEUTRAL"
        assert phase_of(NEUT, BEAR) == "NEUTRAL"

    def test_undecided_flow_is_no_phase_commitment(self):
        assert phase_of(BULL, NEUT) == "NEUTRAL"
        assert phase_of(BEAR, NEUT) == "NEUTRAL"

    def test_location_never_erases_phase(self):
        # mission section 5: H4 BULL + H1 BEAR + PREMIUM stays a BULL_PULLBACK
        phase = phase_of(BULL, BEAR)
        location = location_label("PREMIUM")
        assert phase == "BULL_PULLBACK" and location == "PREMIUM"
        # and phase ignores location entirely (no location argument exists)
        assert phase_of(BULL, BEAR) == phase_of(BULL, BEAR)

    def test_location_labels_are_frozen_eq_relabel(self):
        assert location_label("DISCOUNT") == "DISCOUNT"
        assert location_label("PREMIUM") == "PREMIUM"
        assert location_label("EQUILIBRIUM") == "MIDRANGE"
        assert location_label(None) == "UNAVAILABLE"

    def test_phase_x_location_cross_table_has_pullbacks_at_premium(self, pipeline):
        _, _, enriched, _ = pipeline
        dist = phase_distribution(enriched)
        assert set(dist["counts"]) == set(PHASES)
        cross = dist["phase_x_location"]
        # pullbacks exist and are recorded across locations, not zeroed by location
        assert sum(cross["BULL_PULLBACK"].values()) == dist["counts"]["BULL_PULLBACK"]


class TestPolicies:
    def test_t1_strict_requires_all_three_conditions(self):
        assert t1_direction(BULL, BULL, "DISCOUNT") == BULL
        assert t1_direction(BEAR, BEAR, "PREMIUM") == BEAR
        assert t1_direction(BULL, BULL, "PREMIUM") == NEUT
        assert t1_direction(BULL, BEAR, "DISCOUNT") == NEUT
        assert t1_direction(NEUT, BULL, "DISCOUNT") == NEUT
        assert t1_direction(BULL, BULL, None) == NEUT

    def test_t2_phase_aware_trades_continuation_only(self):
        assert t2_direction("BULL_CONTINUATION") == BULL
        assert t2_direction("BEAR_CONTINUATION") == BEAR
        assert t2_direction("BULL_PULLBACK") == NEUT      # explicit state, not a trade
        assert t2_direction("BEAR_PULLBACK") == NEUT
        assert t2_direction("NEUTRAL") == NEUT

    def test_ma_filters_but_never_overrides_structure(self):
        # MA agreement keeps the structural direction
        assert t2ma_direction(BULL, BULL) == BULL
        # MA disagreement only neutralizes — it can never flip direction
        assert t2ma_direction(BULL, BEAR) == NEUT
        # MA can never create a direction structure did not produce
        assert t2ma_direction(NEUT, BULL) == NEUT
        assert t2ma_direction(NEUT, BEAR) == NEUT

    def test_policy_directions_subset_of_d01(self, pipeline):
        _, _, _, joined = pipeline
        for j in joined:
            for policy in ("T1", "T2", "T2_MA"):
                d = j.direction(policy)
                if d != "NEUTRAL":
                    assert d == j.v3.primary_direction

    def test_registry_hash_is_stable(self):
        assert len(TRIGGER_POLICY_REGISTRY_SHA256) == 64


class TestPullbackRealignment:
    def test_only_pullbacks_are_measured(self, pipeline):
        _, _, enriched, _ = pipeline
        for en in enriched:
            if en.phase in ("BULL_PULLBACK", "BEAR_PULLBACK"):
                assert en.realign_measured
            else:
                assert not en.realign_measured and en.realigned is None

    def test_realignment_fields_consistent(self, pipeline):
        _, _, enriched, _ = pipeline
        realigned = [en for en in enriched if en.realigned]
        assert realigned, "fixture should contain realigned pullbacks"
        for en in realigned:
            assert en.realign_delay_h1 >= 1
            macro = "BULL" if en.phase == "BULL_PULLBACK" else "BEAR"
            assert en.realign_direction == macro

    def test_report_counts_and_delay_quantiles(self, pipeline):
        _, _, enriched, _ = pipeline
        report = pullback_realignment_report(enriched)
        assert report["PULLBACK_REALIGN_N"] <= report["PULLBACK_N"]
        rate = report["PULLBACK_REALIGN_RATE"]
        assert rate is None or 0.0 <= rate <= 1.0
        d = report["REALIGN_DELAY_H1_BARS"]
        if report["PULLBACK_REALIGN_N"]:
            assert d["min"] <= d["P25"] <= d["P50"] <= d["P75"] <= d["P90"] <= d["max"]
        assert report["diagnostic_only"] is True
        assert "NOT a maximum-wait" in report["window_note"]


class TestCausality:
    def test_truncation_and_future_mutation_invariance(self, pipeline):
        frames, _, enriched, _ = pipeline
        from ag_edgelab.contracts.market import MarketBar
        samples = enriched[150::300]
        for en in samples:
            price = frames["M15"][en.feed_index].close
            for variant in ("truncated", "mutated"):
                vframes = {}
                for tf in ("H1", "H4", "D1"):
                    if variant == "truncated":
                        vframes[tf] = bars_closed_at(frames[tf], tf, en.observed_at)
                    else:
                        span = timedelta(minutes=TIMEFRAME_MINUTES[tf])
                        vframes[tf] = tuple(
                            b if b.timestamp + span <= en.observed_at else
                            MarketBar(timestamp=b.timestamp, open=b.open * 1.1,
                                      high=b.high * 1.1, low=b.low * 1.1,
                                      close=b.close * 1.1)
                            for b in frames[tf])
                bundle = build_series(vframes)
                cuts = {}
                for tf in ("H1", "H4", "D1"):
                    span = timedelta(minutes=TIMEFRAME_MINUTES[tf])
                    cuts[tf] = max(i for i, b in enumerate(vframes[tf])
                                   if b.timestamp + span <= en.observed_at)
                ctx, extras = context_at(bundle, cuts["D1"], cuts["H4"], cuts["H1"], price)
                assert ctx.h4.value == en.h4, variant
                assert ctx.h1_flow.value == en.h1_flow, variant
                assert phase_of(ctx.h4, ctx.h1_flow) == en.phase, variant
                assert location_label(extras["pd_state"]) == en.location, variant
                assert ctx.ma.value == en.ma, variant
                assert t1_direction(ctx.h4, ctx.h1_flow, extras["pd_state"]).value == en.t1
                assert t2_direction(phase_of(ctx.h4, ctx.h1_flow)).value == en.t2


class TestMetricsAndComparability:
    def test_sample_attrition_math(self, pipeline):
        _, _, _, joined = pipeline
        d01 = policy_metrics(joined, "D01")
        t1 = policy_metrics(joined, "T1")
        a = attrition(t1, d01)
        assert a == pytest.approx(
            (1 - t1["directional_n"] / d01["directional_n"]) * 100, abs=0.01)
        assert t1["directional_n"] <= d01["directional_n"]

    def test_capability_semantics_comparable_and_null_rules(self, pipeline):
        _, _, _, joined = pipeline
        for policy in ("D01", "T1", "T2"):
            m = policy_metrics(joined, policy)
            assert m["capability_basis"] == CAPABILITY_BASIS
            conf = m["confirmation"]
            assert conf["entry_conditioned_uplift_vs_opportunity"] is None
            assert conf["entry_conditioned_uplift_reason"] == INCOMPARABLE_REASON

    def test_empty_population_yields_null_not_zero(self):
        m = policy_metrics((), "T1")
        assert m["directional_n"] == 0
        assert m["separation_pp"] is None
        assert m["fixed_reach"]["2R"] is None
        assert m["natural_target_r"]["P50"] is None
        assert m["mfe_r_median"] is None

    def test_deterministic_hashes(self, pipeline):
        _, _, _, joined = pipeline
        a = sha256_json(policy_metrics(joined, "T2"))
        b = sha256_json(policy_metrics(joined, "T2"))
        assert a == b and len(a) == 64

    def test_target_distribution_shift_bands(self):
        assert target_distribution_shift({"DELTA_2R_vs_D01_pp": 5.0}) == "IMPROVED"
        assert target_distribution_shift({"DELTA_2R_vs_D01_pp": -5.0}) == "DEGRADED"
        assert target_distribution_shift({"DELTA_2R_vs_D01_pp": 1.0}) == "UNCHANGED"
        assert target_distribution_shift({"DELTA_2R_vs_D01_pp": None}) == "NOT_MEASURABLE"


def _metrics(policy="T1", n=1000, sep=7.0, entered=300, r=None, p50=3.0):
    # default reach profile is deliberately NON-material vs the D01 fixture
    r = r or {"1R": 0.50, "2R": 0.31, "3R": 0.20, "4R": 0.13, "5R": 0.09}
    return {"policy": policy, "directional_n": n, "separation_pp": sep,
            "entered_n": entered, "fixed_reach": r,
            "natural_target_r": {"P25": 1.0, "P50": p50, "P75": 4.0, "P90": 6.0}}


class TestAcceptanceInterpretation:
    D01 = _metrics("D01", n=9000, sep=2.0, entered=3000,
                   r={"1R": 0.49, "2R": 0.30, "3R": 0.20, "4R": 0.14, "5R": 0.10},
                   p50=2.3)

    def test_type_a_requires_separation_and_material_targets(self):
        m = _metrics(sep=8.0, r={"1R": 0.60, "2R": 0.38, "3R": 0.25, "4R": 0.16, "5R": 0.11})
        v = interpret_policy(m, self.D01)
        assert v["result_type"] == "A"
        assert v["interpretation"] == "TRIGGER_HYPOTHESIS_SUPPORTED_ON_DEV"

    def test_type_b_separation_without_target_propagation(self):
        m = _metrics(sep=8.0, r={"1R": 0.50, "2R": 0.31, "3R": 0.20, "4R": 0.13, "5R": 0.09})
        v = interpret_policy(m, self.D01)
        assert v["result_type"] == "B"
        assert v["interpretation"] == "TRIGGER_DIRECTION_IMPROVED_TARGET_NOT_IMPROVED"

    def test_type_c_no_separation_improvement(self):
        v = interpret_policy(_metrics(sep=1.0), self.D01)
        assert v["result_type"] == "C"
        assert v["interpretation"] == "TRIGGER_HYPOTHESIS_NOT_SUPPORTED"

    def test_type_d_population_floors(self):
        v = interpret_policy(_metrics(n=MIN_POLICY_DIRECTIONAL_N - 1), self.D01)
        assert v["result_type"] == "D"
        v = interpret_policy(_metrics(sep=9.0, entered=MIN_POLICY_ENTERED_N - 1), self.D01)
        assert v["result_type"] == "D"
        assert v["interpretation"] == "INSUFFICIENT_EVIDENCE"

    def test_threshold_is_labelled_research_diagnostic(self):
        v = interpret_policy(_metrics(), self.D01)
        assert v["research_diagnostic_threshold_pp"] == RESEARCH_DIAGNOSTIC_THRESHOLD_PP
        assert "RESEARCH_DIAGNOSTIC_THRESHOLD" in v["threshold_label"]

    def test_overall_precedence_and_next_funnel(self):
        va = interpret_policy(_metrics("T1", sep=8.0,
                                       r={"1R": 0.6, "2R": 0.38, "3R": 0.25,
                                          "4R": 0.16, "5R": 0.11}), self.D01)
        vb = interpret_policy(_metrics("T2", sep=8.0), self.D01)
        vc = interpret_policy(_metrics("T2", sep=1.0), self.D01)
        out = overall_interpretation({"T1": va, "T2": vc})
        assert out["best_policy"] == "T1" and out["next_funnel_to_test"] == "NONE"
        out = overall_interpretation({"T1": vb, "T2": vc})
        assert out["best_result_type"] == "B" and out["next_funnel_to_test"] == "TARGET"
        assert out["direction_improvement_propagates_downstream"] == "NO"
        out = overall_interpretation({"T1": vc, "T2": vc})
        assert out["next_funnel_to_test"] == "TRIGGER"

    def test_separation_alone_never_wins(self):
        # type B with huge separation must not outrank type A with smaller one
        va = interpret_policy(_metrics("T2", sep=6.0,
                                       r={"1R": 0.6, "2R": 0.38, "3R": 0.25,
                                          "4R": 0.16, "5R": 0.11}), self.D01)
        vb = interpret_policy(_metrics("T1", sep=20.0), self.D01)
        out = overall_interpretation({"T1": vb, "T2": va})
        assert out["best_policy"] == "T2" and out["best_result_type"] == "A"


class TestStabilityAndAblation:
    def test_location_stability_verdict(self, pipeline):
        _, _, _, joined = pipeline
        per = {p: policy_metrics(joined, p) for p in ("D01", "T1", "T2")}
        out = location_stability(per)
        assert out["LOCATION_VALUE_STABLE"] in ("YES", "NO", "INSUFFICIENT_EVIDENCE")
        assert "no location optimization" in out["note"]

    def test_confirmation_stability_states(self, pipeline):
        _, _, _, joined = pipeline
        per = {p: policy_metrics(joined, p) for p in ("D01", "T1", "T2")}
        out = confirmation_stability(per)
        for state in out["per_policy_state"].values():
            assert state in ("IMPROVES", "DEGRADES", "UNCLEAR", "INSUFFICIENT_EVIDENCE")

    def test_ma_ablation_verdict_rules(self):
        t2 = _metrics("T2", n=4000, sep=3.0, entered=500)
        good = _metrics("T2_MA", n=3000, sep=6.0, entered=400)
        assert ma_ablation(t2, good)["MA_ADDS_VALUE_BEYOND_STRUCTURE"] == "YES"
        weak = _metrics("T2_MA", n=3000, sep=3.5, entered=400)
        assert ma_ablation(t2, weak)["MA_ADDS_VALUE_BEYOND_STRUCTURE"] == "NO"
        tiny = _metrics("T2_MA", n=50, sep=9.0, entered=10)
        assert ma_ablation(t2, tiny)["MA_ADDS_VALUE_BEYOND_STRUCTURE"] == "INSUFFICIENT_EVIDENCE"


class TestSessions:
    def test_session_labels_from_frozen_windows(self):
        day = datetime(2017, 3, 1, tzinfo=UTC)
        assert session_label(day.replace(hour=3)) == "ASIAN"
        assert session_label(day.replace(hour=9)) == "LONDON"
        assert session_label(day.replace(hour=14)) == "LONDON_NEWYORK_OVERLAP"
        assert session_label(day.replace(hour=17)) == "NEW_YORK"
        assert session_label(day.replace(hour=22)) == "OFF_SESSION"

    def test_sessions_are_strata_not_requirements(self, pipeline):
        # directional totals are unchanged by stratification (no session gate)
        _, _, _, joined = pipeline
        from ag_edgelab.universal.trigger_v0_4 import session_stratification
        strat = session_stratification(joined)
        d01_total = sum(v["directional_n"] for v in strat["D01"].values())
        assert d01_total == policy_metrics(joined, "D01")["directional_n"]
