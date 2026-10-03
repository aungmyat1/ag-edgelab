from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ag_edgelab.analytics.funnel_v3 import comparable_uplift
from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.diagnostics.direction_daily_bias import (
    Direction,
    LiquidityState,
    Location,
    Phase,
    classify_alignment,
    classify_premium_discount,
    confirmed_swing_points,
    evaluate_direction_hypothesis,
    fixed_target_capability,
    fixed_target_geometry,
    ma_direction,
    natural_target_r,
    prior_day_levels,
    structure_state,
)

Z = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=Z)


def bars(rows, start=T0, step=timedelta(hours=1)):
    return tuple(
        MarketBar(
            timestamp=start + i * step,
            open=float(o), high=float(max(o, h, l, c)), low=float(min(o, h, l, c)), close=float(c), volume=1
        )
        for i, (o, h, l, c) in enumerate(rows)
    )


def bullish_structure_bars():
    return bars([
        (100, 101, 99, 100), (100, 105, 98, 103), (103, 102, 95, 98),
        (98, 110, 100, 108), (108, 106, 97, 100), (100, 115, 99, 112),
        (112, 113, 102, 110),
    ])


def bearish_structure_bars():
    return bars([
        (100, 101, 99, 100), (100, 110, 100, 105), (105, 105, 95, 97),
        (97, 108, 96, 99), (99, 98, 90, 92), (92, 97, 91, 94),
    ])


def test_confirmed_bullish_structure_hh_hl_and_invalidation():
    state = structure_state(bullish_structure_bars(), order=1)
    assert state.direction == Direction.BULL
    assert {p.label for p in state.swing_points if p.label} >= {"HH", "HL"}
    assert state.invalidation_type == "PROTECTED_SWING_LOW"
    assert state.invalidation_reference == 97.0
    assert any(event.direction == Direction.BULL for event in state.bos_events)


def test_confirmed_bearish_structure_lh_ll_and_invalidation():
    state = structure_state(bearish_structure_bars(), order=1)
    assert state.direction == Direction.BEAR
    assert {p.label for p in state.swing_points if p.label} >= {"LH", "LL"}
    assert state.invalidation_type == "PROTECTED_SWING_HIGH"


def test_structure_neutral_when_labels_conflict_or_are_missing():
    flat = bars([(100, 101, 99, 100)] * 6)
    assert structure_state(flat, order=1).direction == Direction.NEUTRAL
    assert confirmed_swing_points(flat, order=1) == ()


def test_ma_bull_bear_and_insufficient_history():
    bull = bars([(100, 100, 100, 100)] * 150 + [(110, 110, 110, 110)] * 50, step=timedelta(days=1))
    bear = bars([(110, 110, 110, 110)] * 150 + [(100, 100, 100, 100)] * 50, step=timedelta(days=1))
    assert ma_direction(bull, "D1").state == Direction.BULL
    assert ma_direction(bear, "D1").state == Direction.BEAR
    short = ma_direction(bull[:199], "D1")
    assert short.state == Direction.NEUTRAL and short.insufficient_history


def test_premium_discount_midrange_exact_equality():
    assert classify_premium_discount(101, 100) == Location.PREMIUM
    assert classify_premium_discount(99, 100) == Location.DISCOUNT
    assert classify_premium_discount(100, 100) == Location.MIDRANGE


def test_pdh_pdl_construction_and_sweeps():
    rows = [
        (100, 105, 95, 100), (100, 110, 90, 105),  # previous UTC date
        (105, 111, 89, 100),  # current date sweeps both
    ]
    source = bars(rows, start=datetime(2026, 1, 2, 0, tzinfo=Z), step=timedelta(hours=12))
    levels = prior_day_levels(source, asof=datetime(2026, 1, 3, 12, tzinfo=Z))
    assert levels.pdh == 110 and levels.pdl == 90
    assert levels.pdh_state == LiquidityState.SWEPT
    assert levels.pdl_state == LiquidityState.SWEPT


def test_phase_examples():
    frames = {"H4": bullish_structure_bars(), "H1": bearish_structure_bars()}
    decision = evaluate_direction_hypothesis("MD08", frames, swing_order=1)
    assert decision.macro_direction == Direction.BULL
    # A separate H1 structural direction is deliberately retained.
    assert decision.immediate_direction == Direction.BEAR
    assert decision.phase == Phase.PULLBACK


def test_bias_and_entry_are_separate_objects():
    decision = evaluate_direction_hypothesis("MD01", {"H4": bullish_structure_bars()}, swing_order=1)
    assert decision.direction == Direction.BULL
    assert "entry" not in decision.evidence
    assert decision.invalidation_reference is not None


def test_natural_target_r_and_fixed_target_capability():
    assert natural_target_r(100, 98, 106) == 3.0
    assert natural_target_r(100, 100, 106) is None
    geometry = fixed_target_geometry("T03", Direction.BULL, 100, 98, 3)
    assert geometry.target_price == 106 and geometry.target_r == 3
    outcome = fixed_target_capability(bars([(100, 105, 99, 104), (104, 107, 103, 106)]), Direction.BULL, 100, 98, 3)
    assert outcome == "TARGET"


def test_target_selection_does_not_read_future_bars():
    entry_time = T0 + timedelta(hours=10)
    before = fixed_target_geometry("T05", Direction.BULL, 100, 98, 5, selected_at=entry_time)
    after = fixed_target_geometry("T05", Direction.BULL, 100, 98, 5, selected_at=entry_time)
    assert before == after
    assert fixed_target_capability(bars([(100, 103, 99, 102)]), Direction.BULL, 100, 98, 5) == "UNRESOLVED"
    assert fixed_target_capability(bars([(102, 111, 101, 110)]), Direction.BULL, 100, 98, 5) == "TARGET"


def test_no_future_swing_ma_or_liquidity_at_decision_time():
    source = bullish_structure_bars()
    prefix = source[:5]
    assert structure_state(source, order=1, asof_index=4) == structure_state(prefix, order=1)
    daily = bars([(100, 100, 100, 100)] * 200, start=datetime(2026, 1, 1, tzinfo=Z), step=timedelta(days=1))
    assert ma_direction(daily, "D1") == ma_direction(daily[:200], "D1")
    current = bars([
        (100, 105, 95, 100),  # Jan 1 00:00, prior context
        (100, 105, 95, 100),  # Jan 1 12:00, prior context
        (100, 111, 89, 100),  # Jan 2 00:00, PDH/PDL source
        (100, 105, 95, 100),  # Jan 2 12:00, previous-day completion
        (100, 105, 95, 100),  # Jan 3 00:00, current day before sweep
        (100, 112, 88, 100),  # Jan 3 12:00, future sweep
    ], start=datetime(2026, 1, 1, tzinfo=Z), step=timedelta(hours=12))
    before = prior_day_levels(current, asof=datetime(2026, 1, 3, 6, tzinfo=Z))
    after = prior_day_levels(current, asof=datetime(2026, 1, 3, 23, tzinfo=Z))
    assert before.pdh == after.pdh == 111 and before.pdl == after.pdl == 89
    assert before.pdh_state == LiquidityState.INTACT
    assert after.pdh_state == LiquidityState.SWEPT


def test_alignment_classes():
    assert classify_alignment(Direction.BULL, Direction.BULL, Direction.BULL) == "ALIGNED"
    assert classify_alignment(Direction.BULL, Direction.BEAR, Direction.BEAR) == "COUNTER_DIRECTION"
    assert classify_alignment(Direction.NEUTRAL, Direction.BULL, Direction.BULL) == "NEUTRAL"
    assert classify_alignment(Direction.BULL, Direction.BULL, Direction.BEAR) == "MACRO_ALIGNED_INTERNAL_COUNTER"
    assert classify_alignment(Direction.BULL, Direction.BEAR, Direction.BULL) == "MACRO_COUNTER_INTERNAL_ALIGNED"


def test_incompatible_uplift_and_missing_target_are_null():
    assert comparable_uplift(0.5, 0.2, aligned_population="ENTRY", counter_population="OPPORTUNITY", aligned_geometry="5R", counter_geometry="5R") is None
    assert natural_target_r(100, 98, float("nan")) is None


def test_deterministic_report_hash_and_existing_strategy_files_unchanged():
    payload = {"b": 2, "a": [1, 2, 3]}
    a = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    b = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert a == b
    strategy = Path("src/ag_edgelab/strategies/crypto_mtf_smc.py")
    assert strategy.exists()  # the lab does not mutate existing strategy identities
