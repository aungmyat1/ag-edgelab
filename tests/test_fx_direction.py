"""Preregistered FX direction hypotheses D01..D10 — contract tests."""

from __future__ import annotations

from dataclasses import fields, replace

import pytest

from ag_edgelab.data.derive import aggregate_bars
from ag_edgelab.universal.campaign import make_synthetic_fx_bars
from ag_edgelab.universal.direction import Direction, structural_direction
from ag_edgelab.universal.fx_direction import (DIRECTION_HYPOTHESES, DirectionContext,
                                               FX_DIRECTION_REGISTRY_SHA256, FlowSeries,
                                               MaSeries, PRIMARY_FUNNEL_HYPOTHESIS,
                                               StructuralSeries,
                                               evaluate_direction_hypotheses)

BULL, BEAR, NEUT = Direction.BULL, Direction.BEAR, Direction.NEUTRAL


def _ctx(**over) -> DirectionContext:
    base = dict(d1=BULL, h4=BULL, h1=BULL, premium_discount="DISCOUNT",
                h1_flow=BULL, liquidity_support_bull=True,
                liquidity_support_bear=False, ma=BULL)
    base.update(over)
    return DirectionContext(**base)


@pytest.fixture(scope="module")
def h1_frame():
    m5 = make_synthetic_fx_bars(days=30, seed=7)
    m15, _ = aggregate_bars(m5, "M5", "M15")
    h1, _ = aggregate_bars(m15, "M15", "H1")
    return h1


class TestStructuralSeries:
    def test_matches_v03_structural_direction_at_every_index(self, h1_frame):
        series = StructuralSeries(h1_frame)
        for i in range(0, len(h1_frame), 7):
            expected = structural_direction(h1_frame, "H1", asof_index=i).direction
            assert series.at(i) == expected, f"divergence at index {i}"

    def test_truncation_invariance(self, h1_frame):
        series = StructuralSeries(h1_frame)
        for cut in (60, 120, 200):
            truncated = StructuralSeries(h1_frame[: cut + 1])
            assert truncated.at(cut) == series.at(cut)
            assert truncated.range_high[cut] == series.range_high[cut]
            assert truncated.range_low[cut] == series.range_low[cut]

    def test_recent_swings_are_prefix_consistent(self, h1_frame):
        series = StructuralSeries(h1_frame)
        mid = len(h1_frame) // 2
        truncated = StructuralSeries(h1_frame[: mid + 1])
        assert truncated.recent_highs(mid) == series.recent_highs(mid)
        assert truncated.recent_lows(mid) == series.recent_lows(mid)


class TestMaFlowSeries:
    def test_ma_neutral_before_200_bars(self, h1_frame):
        series = MaSeries(h1_frame)
        assert series.at(100) == NEUT
        assert series.at(198) == NEUT

    def test_flow_neutral_before_any_event(self, h1_frame):
        series = FlowSeries(h1_frame)
        assert series.at(0) == NEUT


class TestHypothesisContracts:
    def test_registry_is_frozen_ten_hypotheses(self):
        assert list(DIRECTION_HYPOTHESES) == [f"D{i:02d}" for i in range(1, 11)]
        assert PRIMARY_FUNNEL_HYPOTHESIS == "D01"
        assert len(FX_DIRECTION_REGISTRY_SHA256) == 64

    def test_no_session_identity_in_context(self):
        names = {f.name for f in fields(DirectionContext)}
        assert not any("session" in n for n in names)

    def test_d01_is_h4_only(self):
        assert evaluate_direction_hypotheses(_ctx(h4=BEAR, d1=BULL))["D01"] == BEAR

    def test_d02_requires_d1_h4_agreement(self):
        assert evaluate_direction_hypotheses(_ctx())["D02"] == BULL
        assert evaluate_direction_hypotheses(_ctx(d1=BEAR))["D02"] == NEUT
        assert evaluate_direction_hypotheses(_ctx(d1=NEUT))["D02"] == NEUT

    def test_d04_requires_all_three(self):
        assert evaluate_direction_hypotheses(_ctx())["D04"] == BULL
        assert evaluate_direction_hypotheses(_ctx(h1=NEUT))["D04"] == NEUT

    def test_d05_premium_discount_gate(self):
        assert evaluate_direction_hypotheses(_ctx(premium_discount="DISCOUNT"))["D05"] == BULL
        assert evaluate_direction_hypotheses(_ctx(premium_discount="PREMIUM"))["D05"] == NEUT
        bear = _ctx(h4=BEAR, premium_discount="PREMIUM")
        assert evaluate_direction_hypotheses(bear)["D05"] == BEAR
        assert evaluate_direction_hypotheses(_ctx(premium_discount=None))["D05"] == NEUT

    def test_d06_internal_flow_gate(self):
        assert evaluate_direction_hypotheses(_ctx())["D06"] == BULL
        assert evaluate_direction_hypotheses(_ctx(h1_flow=BEAR))["D06"] == NEUT

    def test_d07_liquidity_gate(self):
        assert evaluate_direction_hypotheses(_ctx())["D07"] == BULL
        assert evaluate_direction_hypotheses(_ctx(liquidity_support_bull=False))["D07"] == NEUT
        bear = _ctx(h4=BEAR, liquidity_support_bear=True)
        assert evaluate_direction_hypotheses(bear)["D07"] == BEAR

    def test_d08_requires_pd_and_flow(self):
        assert evaluate_direction_hypotheses(_ctx())["D08"] == BULL
        assert evaluate_direction_hypotheses(_ctx(h1_flow=BEAR))["D08"] == NEUT
        assert evaluate_direction_hypotheses(_ctx(premium_discount="PREMIUM"))["D08"] == NEUT

    def test_d09_is_ma_control_independent_of_structure(self):
        assert evaluate_direction_hypotheses(_ctx(h4=BEAR, d1=BEAR, ma=BULL))["D09"] == BULL

    def test_d10_requires_structure_ma_agreement(self):
        assert evaluate_direction_hypotheses(_ctx())["D10"] == BULL
        assert evaluate_direction_hypotheses(_ctx(ma=BEAR))["D10"] == NEUT

    def test_neutral_structure_gates_everything_structural(self):
        out = evaluate_direction_hypotheses(_ctx(h4=NEUT))
        for hyp in ("D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D10"):
            assert out[hyp] == NEUT, hyp
