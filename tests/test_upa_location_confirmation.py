"""Universal price-action V0.3 — location evidence + confirmation primitives."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.universal.confirmation import (ConfirmationPrimitive, SetupAlignment,
                                               classify_alignment, engulfing_event,
                                               evening_star_event, liquidity_sweep_events,
                                               morning_star_event, pin_bar_event,
                                               structure_shift_events)
from ag_edgelab.universal.direction import Direction
from ag_edgelab.universal.location import (LocationFamily, LocationSide, evidence_at_price,
                                           liquidity_levels, premium_discount,
                                           premium_discount_supports, structural_levels,
                                           supply_demand_zones)
from ag_edgelab.universal.parity import synthetic_structural_bars

Z = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=Z)


def _bar(i: int, o: float, h: float, l: float, c: float) -> MarketBar:
    return MarketBar(timestamp=T0 + timedelta(minutes=5 * i),
                     open=o, high=max(h, o, c), low=min(l, o, c), close=c, volume=1.0)


def test_structural_level_location_detected():
    bars = synthetic_structural_bars("BULL", 100.0, 1.0)
    evidences = structural_levels(bars, "H4")
    families = {e.family for e in evidences}
    sides = {e.side for e in evidences}
    assert families == {LocationFamily.STRUCTURAL_LEVEL}
    assert LocationSide.SUPPORT in sides and LocationSide.RESISTANCE in sides
    support = next(e for e in evidences if e.side == LocationSide.SUPPORT)
    assert evidence_at_price(evidences, (support.zone_low + support.zone_high) / 2,
                             Direction.BULL)


def test_supply_demand_location_detected():
    # Quiet tape, then a bearish origin candle followed by a 2x-body bullish
    # displacement => DEMAND zone at the origin candle.
    bars = [_bar(i, 100, 100.6, 99.4, 100.2 if i % 2 else 99.8) for i in range(24)]
    bars.append(_bar(24, 100.0, 100.1, 99.0, 99.1))    # bearish origin
    bars.append(_bar(25, 99.1, 104.3, 99.0, 104.2))    # bullish displacement
    zones = supply_demand_zones(tuple(bars), "H4")
    assert any(z.family == LocationFamily.SUPPLY_DEMAND and z.side == LocationSide.SUPPORT
               for z in zones)
    demand = next(z for z in zones if z.side == LocationSide.SUPPORT)
    assert demand.zone_low <= 99.1 <= demand.zone_high


def test_liquidity_levels_equal_lows_pool():
    bars = synthetic_structural_bars("NEUTRAL", 100.0, 1.0)
    pools = liquidity_levels(bars, "H4")
    assert any(p.detector_id == "LOC_LIQUIDITY_EQUAL_LOWS_V1" for p in pools)
    assert any(p.detector_id == "LOC_LIQUIDITY_EQUAL_HIGHS_V1" for p in pools)


def test_premium_discount_states_support_direction():
    bars = synthetic_structural_bars("BULL", 100.0, 1.0)
    state_low = premium_discount(bars, "H4", price=bars[-1].low - 2.0)
    state_high = premium_discount(bars, "H4", price=state_low.range_high + 2.0)
    assert state_low.state == "DISCOUNT" and state_high.state == "PREMIUM"
    assert premium_discount_supports(state_low, Direction.BULL)
    assert not premium_discount_supports(state_low, Direction.BEAR)
    assert premium_discount_supports(state_high, Direction.BEAR)
    assert not premium_discount_supports(None, Direction.BULL)  # fail-closed


def test_liquidity_sweep_contract():
    bars = (
        _bar(0, 100, 101, 99.5, 100.5),
        _bar(1, 100.5, 101, 98.0, 100.2),   # trades below 99 but closes above => SSL sweep
        _bar(2, 100.2, 103.0, 100.0, 102.0),
    )
    events = liquidity_sweep_events(bars, "M5", level=99.0, side="BELOW")
    assert len(events) == 1
    event = events[0]
    assert event.primitive == ConfirmationPrimitive.LIQUIDITY_SWEEP
    assert event.direction == Direction.BULL and event.index == 1 and event.extreme == 98.0
    assert not liquidity_sweep_events(bars, "M5", level=99.0, side="ABOVE")


def test_mss_and_bos_events():
    from datetime import timedelta as _td
    bear = synthetic_structural_bars("BEAR", 100.0, 1.0, cycles=4, step_minutes=5)
    bull = synthetic_structural_bars("BULL", 100.0, 1.0, cycles=4, step_minutes=5,
                                     start=bear[-1].timestamp + _td(minutes=5))
    events = structure_shift_events(bear + bull, "M5", swing_order=2)
    bearish = [e for e in events if e.direction == Direction.BEAR]
    bullish = [e for e in events if e.direction == Direction.BULL]
    assert bearish and bullish
    # The first bullish break after an established bearish bias is an MSS.
    assert bullish[0].primitive == ConfirmationPrimitive.MSS
    # Continuation breaks keep the BOS label.
    assert all(e.primitive == ConfirmationPrimitive.BOS for e in bullish[1:])


def test_engulfing_contract():
    bars = (_bar(0, 100.0, 100.2, 99.0, 99.2),      # bearish
            _bar(1, 99.1, 100.8, 99.0, 100.5))      # bullish engulfing body
    event = engulfing_event(bars, "M15", 1)
    assert event is not None and event.direction == Direction.BULL
    bearish = (_bar(0, 100.0, 100.6, 99.9, 100.5),   # bullish
               _bar(1, 100.6, 100.7, 99.7, 99.8))    # bearish engulfing body
    assert engulfing_event(bearish, "M15", 1).direction == Direction.BEAR
    # No engulfing when the current body is smaller.
    small = (_bar(0, 100.0, 100.2, 99.0, 99.2), _bar(1, 99.2, 99.5, 99.1, 99.4))
    assert engulfing_event(small, "M15", 1) is None


def test_pin_bar_contract():
    bullish_pin = (_bar(0, 100.0, 100.15, 97.0, 100.1),)
    event = pin_bar_event(bullish_pin, "M15", 0)
    assert event is not None and event.direction == Direction.BULL
    no_pin = (_bar(0, 100.0, 101.0, 99.0, 100.5),)
    assert pin_bar_event(no_pin, "M15", 0) is None


def test_morning_and_evening_star_contracts():
    morning = (_bar(0, 102.0, 102.2, 99.9, 100.0),   # big bearish
               _bar(1, 100.0, 100.3, 99.7, 100.1),   # small body
               _bar(2, 100.1, 102.4, 100.0, 102.2))  # bullish close above midpoint
    event = morning_star_event(morning, "M15", 2)
    assert event is not None and event.direction == Direction.BULL
    evening = (_bar(0, 100.0, 102.1, 99.9, 102.0),
               _bar(1, 102.0, 102.3, 101.8, 101.9),
               _bar(2, 101.9, 102.0, 99.6, 99.8))
    event = evening_star_event(evening, "M15", 2)
    assert event is not None and event.direction == Direction.BEAR
    assert morning_star_event(evening, "M15", 2) is None


def test_direction_precedes_setup_counter_is_recorded_not_rejected():
    # Authority exists BEFORE the setup is judged; a short setup under BULL
    # authority is COUNTER_DIRECTION — a recorded diagnostic class.
    assert classify_alignment(Direction.BULL, Direction.BULL) == SetupAlignment.ALIGNED
    assert classify_alignment(Direction.BULL, Direction.BEAR) == SetupAlignment.COUNTER_DIRECTION
    assert classify_alignment(Direction.NEUTRAL, Direction.BULL) == SetupAlignment.NEUTRAL
    assert classify_alignment(Direction.BEAR, Direction.NEUTRAL) == SetupAlignment.NEUTRAL
    assert SetupAlignment.COUNTER_DIRECTION.value == "COUNTER_DIRECTION"
