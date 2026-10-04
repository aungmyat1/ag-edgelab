"""Universal price-action V0.3 — Funnel 1 direction engine + MA family."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.universal.direction import (Direction, DirectionMode, MA_FAST, MA_SLOW,
                                            assert_no_future_bars, combined_direction,
                                            ma_direction, mtf_direction, structural_direction)
from ag_edgelab.universal.parity import synthetic_structural_bars

Z = timezone.utc


def test_bullish_structure_confirmed_hh_hl():
    bars = synthetic_structural_bars("BULL", 100.0, 1.0)
    state = structural_direction(bars, "H4")
    assert state.direction == Direction.BULL
    assert state.reason == "CONFIRMED_HH_HL"
    assert state.last_high > state.prior_high and state.last_low > state.prior_low


def test_bearish_structure_confirmed_lh_ll():
    state = structural_direction(synthetic_structural_bars("BEAR", 100.0, 1.0), "H4")
    assert state.direction == Direction.BEAR
    assert state.reason == "CONFIRMED_LH_LL"


def test_neutral_structure_unresolved():
    state = structural_direction(synthetic_structural_bars("NEUTRAL", 100.0, 1.0), "H4")
    assert state.direction == Direction.NEUTRAL


def test_neutral_on_insufficient_swings():
    bars = synthetic_structural_bars("BULL", 100.0, 1.0)[:4]
    state = structural_direction(bars, "H4")
    assert state.direction == Direction.NEUTRAL
    assert state.reason == "INSUFFICIENT_CONFIRMED_SWINGS"


def test_mtf_composite_conflict_is_neutral():
    frames = {
        "D1": synthetic_structural_bars("BULL", 100.0, 1.0),
        "H4": synthetic_structural_bars("BEAR", 100.0, 1.0),
        "H1": synthetic_structural_bars("BULL", 100.0, 1.0),
    }
    assert mtf_direction(frames).composite == Direction.NEUTRAL


def test_mtf_composite_consensus_bull():
    frames = {
        "D1": synthetic_structural_bars("BULL", 100.0, 1.0),
        "H4": synthetic_structural_bars("BULL", 100.0, 1.0),
        "H1": synthetic_structural_bars("NEUTRAL", 100.0, 1.0),
    }
    assert mtf_direction(frames).composite == Direction.BULL


def test_ma_bull_when_ma50_above_ma200():
    closes = [100.0] * 150 + [200.0] * 50  # fast window dominated by 200s
    state = ma_direction(closes)
    assert state.direction == Direction.BULL and state.ma_fast > state.ma_slow


def test_ma_bear_when_ma50_below_ma200():
    closes = [200.0] * 150 + [100.0] * 50
    state = ma_direction(closes)
    assert state.direction == Direction.BEAR and state.ma_fast < state.ma_slow


def test_ma_insufficient_bars_fails_closed_neutral():
    state = ma_direction([100.0] * (MA_SLOW - 1))
    assert state.direction == Direction.NEUTRAL
    assert state.reason == "INSUFFICIENT_BARS_FOR_MA200"


def test_ma_family_is_preregistered_no_optimization():
    with pytest.raises(ValueError, match="preregistered"):
        ma_direction([100.0] * 300, fast=20, slow=100)
    assert (MA_FAST, MA_SLOW) == (50, 200)


def test_combined_direction_modes():
    assert combined_direction(Direction.BULL, Direction.BEAR, DirectionMode.STRUCTURE_ONLY) == Direction.BULL
    assert combined_direction(Direction.BULL, Direction.BEAR, DirectionMode.MA_ONLY) == Direction.BEAR
    assert combined_direction(Direction.BULL, Direction.BEAR, DirectionMode.STRUCTURE_PLUS_MA) == Direction.NEUTRAL
    assert combined_direction(Direction.BULL, Direction.BULL, DirectionMode.STRUCTURE_PLUS_MA) == Direction.BULL
    assert combined_direction(Direction.NEUTRAL, Direction.NEUTRAL, DirectionMode.STRUCTURE_PLUS_MA) == Direction.NEUTRAL


def test_no_future_bars_guard():
    start = datetime(2026, 1, 1, tzinfo=Z)
    bars = tuple(MarketBar(timestamp=start + timedelta(hours=i), open=1, high=2, low=0.5, close=1.5)
                 for i in range(3))
    assert_no_future_bars(bars, start + timedelta(hours=2))  # ok
    with pytest.raises(ValueError, match="future bar"):
        assert_no_future_bars(bars, start + timedelta(hours=1))


def test_structural_direction_asof_uses_only_confirmed_swings():
    bars = synthetic_structural_bars("BULL", 100.0, 1.0)
    early = structural_direction(bars, "H4", asof_index=3)
    assert early.direction == Direction.NEUTRAL  # pivots not confirmed yet
    late = structural_direction(bars, "H4", asof_index=len(bars) - 1)
    assert late.direction == Direction.BULL
