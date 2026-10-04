"""FX DEV campaign orchestration — synthetic fixture tests (always run)."""

from __future__ import annotations

import pytest

from ag_edgelab.data.derive import aggregate_bars
from ag_edgelab.data.fx_histdata_2017 import derive_fx_timeframe
from ag_edgelab.universal.campaign import make_synthetic_fx_bars
from ag_edgelab.universal.fx_dev_campaign import (FUNNEL_STAGES, INCOMPARABLE_REASON,
                                                  MIN_DIRECTIONAL_N, build_funnel,
                                                  confirmation_value,
                                                  decisions_from_truncated_frames,
                                                  fx_root_cause, hypothesis_comparison,
                                                  reach_share, required_comparisons,
                                                  run_fx_symbol_campaign, target_lab)
from ag_edgelab.universal.matrix import CAPABILITY_BASIS


@pytest.fixture(scope="module")
def frames():
    m5 = make_synthetic_fx_bars(days=60, seed=11)
    m15, _ = aggregate_bars(m5, "M5", "M15")
    out = {"M15": m15}
    for tf in ("H1", "H4", "D1"):
        out[tf], _ = derive_fx_timeframe(m15, tf, "SYNTH")
    return out


@pytest.fixture(scope="module")
def campaign(frames):
    m15 = frames["M15"]
    return run_fx_symbol_campaign(frames, "SYNTH", m15[0].timestamp, m15[-1].timestamp)


class TestFunnelShape:
    def test_stage_names_and_order(self, campaign):
        assert tuple(r["stage"] for r in campaign.funnel) == FUNNEL_STAGES

    def test_counts_monotone_non_increasing(self, campaign):
        counts = [r["n"] for r in campaign.funnel]
        assert all(a >= b for a, b in zip(counts, counts[1:]))

    def test_percentages_relative_to_previous_stage(self, campaign):
        rows = campaign.funnel
        assert rows[0]["pct_of_previous"] is None
        for prev, row in zip(rows, rows[1:]):
            if prev["n"]:
                assert row["pct_of_previous"] == pytest.approx(
                    row["n"] / prev["n"] * 100.0, abs=0.01)

    def test_raw_observations_counted(self, campaign):
        assert campaign.raw_observations >= len(campaign.observations) > 0


class TestObservationInvariants:
    def test_entry_requires_aligned_location_and_confirmation(self, campaign):
        for obs in campaign.observations:
            if obs.entered:
                assert obs.location_state == "ALIGNED"
                assert obs.confirmation_alignment == "ALIGNED"
                assert obs.entry_mfe_r is not None

    def test_fixed_reach_is_monotone_per_entry(self, campaign):
        for obs in campaign.observations:
            if obs.entered:
                for k in (2, 3, 4, 5):
                    if obs.fixed_reached.get(k):
                        assert obs.fixed_reached.get(k - 1), "reach must be nested"

    def test_midrange_mismatch_recorded_not_dropped(self, campaign):
        states = {o.location_state for o in campaign.observations
                  if o.primary_direction != "NEUTRAL"}
        assert states <= {"ALIGNED", "MISMATCH_RECORDED", "UNAVAILABLE"}
        # directional observations outside any zone must still be present
        assert any(o.location_state == "MISMATCH_RECORDED"
                   for o in campaign.observations)

    def test_neutral_observations_not_location_evaluated(self, campaign):
        for obs in campaign.observations:
            if obs.primary_direction == "NEUTRAL":
                assert obs.location_state == "NOT_EVALUATED"
                assert not obs.entered

    def test_all_ten_hypotheses_decided_per_observation(self, campaign):
        for obs in campaign.observations[:50]:
            assert set(obs.directions) == {f"D{i:02d}" for i in range(1, 11)}
            assert set(obs.directions.values()) <= {"BULL", "BEAR", "NEUTRAL"}


class TestAntiLookahead:
    def test_truncated_recomputation_matches_streaming_decisions(self, frames, campaign):
        obs_list = campaign.observations
        for obs in obs_list[100::200]:
            recomputed = decisions_from_truncated_frames(frames, obs.observed_at, obs.price)
            assert recomputed == obs.directions

    def test_observation_horizon_fits_inside_feed(self, frames, campaign):
        last = max(o.feed_index for o in campaign.observations)
        assert last + 96 + 16 < len(frames["M15"])


class TestAggregations:
    def test_hypothesis_comparison_counts_consistent(self, campaign):
        comp = hypothesis_comparison(campaign.observations)
        n = len(campaign.observations)
        for hyp, row in comp.items():
            assert row["n_bull"] + row["n_bear"] + row["n_neutral"] == n
            assert row["capability_basis"] == CAPABILITY_BASIS

    def test_survival_chain_matches_counts(self, campaign):
        entered = [o for o in campaign.observations if o.entered]
        tl = target_lab(campaign.observations)
        counts = {k: sum(1 for o in entered if o.fixed_reached.get(k)) for k in range(1, 6)}
        if counts[1]:
            assert tl["continuation_survival"]["P2_GIVEN_1"] == pytest.approx(
                counts[2] / counts[1])
        assert tl["entered_n"] == len(entered)
        assert tl["fixed_targets_changed"] is False

    def test_comparison_populations_are_disjoint_partitions(self, campaign):
        cmp = required_comparisons(campaign.observations)
        directional = [o for o in campaign.observations if o.primary_direction != "NEUTRAL"]
        bb = cmp["bull_vs_bear"]
        assert bb["bull_n"] + bb["bear_n"] == len(directional)
        loc = cmp["location_aligned_vs_mismatch"]
        unavailable = sum(1 for o in directional if o.location_state == "UNAVAILABLE")
        assert loc["aligned_n"] + loc["mismatch_n"] + unavailable == len(directional)

    def test_reach_share_handles_empty_and_none(self):
        assert reach_share([]) is None
        assert reach_share([None, None]) is None
        assert reach_share([1.0, 3.0, None]) == 0.5


class TestComparabilityGuard:
    def test_entry_conditioned_uplift_is_never_cross_basis(self, campaign):
        cv = confirmation_value(campaign.observations)
        assert cv["entry_conditioned_uplift_vs_opportunity"] is None
        assert cv["entry_conditioned_uplift_reason"] == INCOMPARABLE_REASON
        assert cv["opportunity_basis"] == CAPABILITY_BASIS
        assert cv["entry_conditioned_basis"] != CAPABILITY_BASIS

    def test_same_basis_uplift_is_within_opportunity_basis(self, campaign):
        cv = confirmation_value(campaign.observations)
        if cv["uplift_pp_same_basis"] is not None:
            assert cv["confirmed_subset_capability_same_basis"] is not None
            assert cv["opportunity_capability_location_aligned"] is not None


def _comparison(separation, cap=0.40, n=300):
    return {"D01": {"n_bull": n // 2, "n_bear": n - n // 2, "n_neutral": 0,
                    "capability_decided_direction": cap,
                    "capability_opposite_direction": cap - separation / 100.0,
                    "separation_pp": separation, "sample_sufficient": n >= MIN_DIRECTIONAL_N}}


def _conf_value(loc_cap=0.40, uplift=5.0, entry_cap=0.5):
    return {"opportunity_capability_location_aligned": loc_cap,
            "uplift_pp_same_basis": uplift,
            "entry_conditioned_capability": entry_cap}


def _targets(entered=100, r1=0.6, r3=0.4, nat_median=4.0):
    return {"entered_n": entered,
            "fixed_reach": {"1R": r1, "2R": (r1 + r3) / 2, "3R": r3, "4R": r3 / 2, "5R": r3 / 4},
            "natural_target_median_r": nat_median}


class TestRootCausePrecedence:
    def test_case_a_direction_no_separation(self):
        out = fx_root_cause((), _comparison(2.0), _conf_value(), _targets())
        assert (out["case"], out["primary"], out["next_funnel_to_change"]) == \
            ("A", "TRIGGER_FUNNEL_WEAKNESS", "TRIGGER")

    def test_case_b_location_destroys(self):
        out = fx_root_cause((), _comparison(10.0, cap=0.40),
                            _conf_value(loc_cap=0.30), _targets())
        assert (out["case"], out["primary"], out["next_funnel_to_change"]) == \
            ("B", "DIRECTION_LOCATION_MISMATCH", "LOCATION")

    def test_case_c_confirmation_destroys(self):
        out = fx_root_cause((), _comparison(10.0, cap=0.40),
                            _conf_value(loc_cap=0.40, uplift=-15.0), _targets())
        assert (out["case"], out["primary"], out["next_funnel_to_change"]) == \
            ("C", "CONFIRMATION_VALUE_DESTRUCTION", "CONFIRMATION")

    def test_case_d_continuation_collapse(self):
        out = fx_root_cause((), _comparison(10.0), _conf_value(),
                            _targets(r1=0.6, r3=0.1))
        assert (out["case"], out["primary"], out["next_funnel_to_change"]) == \
            ("D", "TARGET_CONTINUATION_WEAKNESS", "TARGET")

    def test_case_d_secondary_mismatch_when_natural_also_short(self):
        out = fx_root_cause((), _comparison(10.0), _conf_value(),
                            _targets(r1=0.6, r3=0.1, nat_median=2.0))
        assert out["case"] == "D"
        assert "TARGET_MODEL_MISMATCH" in out["secondary"]

    def test_case_e_natural_geometry_below_fixed(self):
        out = fx_root_cause((), _comparison(10.0), _conf_value(),
                            _targets(nat_median=2.0))
        assert (out["case"], out["primary"], out["next_funnel_to_change"]) == \
            ("E", "TARGET_MODEL_MISMATCH", "TARGET")

    def test_low_5r_reach_alone_does_not_trip_target(self):
        # healthy 1R/3R, natural median >= desired -> NONE even with tiny 5R reach
        targets = _targets(r1=0.6, r3=0.4, nat_median=4.0)
        targets["fixed_reach"]["5R"] = 0.01
        out = fx_root_cause((), _comparison(10.0), _conf_value(), targets)
        assert out["case"] == "NONE" and out["next_funnel_to_change"] == "NONE"

    def test_insufficient_directional_population(self):
        out = fx_root_cause((), _comparison(10.0, n=50), _conf_value(), _targets())
        assert out["primary"] == "INSUFFICIENT_EVIDENCE"

    def test_insufficient_entries_before_target_cases(self):
        out = fx_root_cause((), _comparison(10.0), _conf_value(),
                            _targets(entered=5, nat_median=1.0))
        assert out["primary"] == "INSUFFICIENT_EVIDENCE"

    def test_precedence_a_wins_over_later_cases(self):
        out = fx_root_cause((), _comparison(1.0), _conf_value(uplift=-50.0),
                            _targets(nat_median=1.0))
        assert out["case"] == "A"


class TestBuildFunnel:
    def test_empty_population(self):
        rows = build_funnel((), 0)
        assert [r["n"] for r in rows] == [0] * len(FUNNEL_STAGES)
        assert all(r["pct_of_previous"] is None for r in rows)
