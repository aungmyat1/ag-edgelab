"""STV2 strategy-funnel stage semantics (CONTEXT .. OUTCOME).

Covers requirements 9-32 of STV2_STRATEGY_FUNNEL_ANALYZER_V1: every stage
predicate is asserted against the FROZEN SESSION_TRADE_V2 @ 2.0.0 rules on
deterministic synthetic sessions.  No frozen rule is modified anywhere.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from ag_edgelab.campaigns.session_trade_v2 import funnel_analyzer as fa
from ag_edgelab.campaigns.session_trade_v2.frozen import Candle, evaluate
from ag_edgelab.campaigns.session_trade_v2.funnel_models import UnitStatus
from ag_edgelab.campaigns.session_trade_v2.windows import build_window_slice, session_window
from ag_edgelab.contracts.funnel import FunnelStage
from tests.stv2_funnel_fixtures import (
    DATASET_SHA,
    body_breakout_down,
    body_breakout_up,
    build_session,
    exact_touch_high,
    exact_touch_low,
    filler,
    inside,
    sweep_high_reclaim,
    sweep_low_reclaim,
)

UTC = timezone.utc
LOW, HIGH = 1.1000, 1.1100
RANGE = HIGH - LOW
R0 = RANGE * 0.25
MID = (LOW + HIGH) / 2.0
D = date(2017, 3, 1)
SESSION = "LONDON_NEWYORK"

# A long reclaim close must sit close enough to the boundary that the frozen
# 25%-range stop (entry - R0) lands BELOW the sweep extreme, otherwise the
# frozen engine rejects it with SWEEP_STOP_DOES_NOT_PROTECT_EXTREME.
SWEEP_DEPTH = R0 * 0.2
ENTRY_A_LONG = LOW + 0.0005     # stop = 1.0980 < sweep low 1.0995
ENTRY_A_SHORT = HIGH - 0.0005   # stop = 1.1120 > sweep high 1.1105
STOP_A_LONG = ENTRY_A_LONG - R0


def units_for(trade_specs, symbol="EURUSD", session=SESSION, trading_date=D,
              ref_low=LOW, ref_high=HIGH):
    bars = build_session(session, trading_date, ref_low=ref_low, ref_high=ref_high,
                         trade_specs=trade_specs)
    build = fa.build_analysis_units(
        "DEVELOPMENT", {symbol: tuple(bars)}, DATASET_SHA
    )
    return {
        u.branch: u for u in build.units
        if u.symbol == symbol and u.session == session
        and u.trading_date == trading_date.isoformat()
    }


def box_and_trade(trade_specs, session=SESSION, trading_date=D, ref_low=LOW, ref_high=HIGH):
    bars = build_session(session, trading_date, ref_low=ref_low, ref_high=ref_high,
                         trade_specs=trade_specs)
    slice_ = build_window_slice(session, trading_date, tuple(bars))
    assert slice_.valid, slice_.reason
    to_c = lambda rows: tuple(  # noqa: E731
        Candle(time=b.timestamp, open=b.open, high=b.high, low=b.low, close=b.close) for b in rows
    )
    return fa.reference_box(to_c(slice_.reference_bars)), to_c(slice_.trade_bars)


# ===========================================================================
# 9. CONTEXT valid-session counting
# ===========================================================================


def test_context_counts_a_complete_session_as_valid_for_all_three_branches():
    units = units_for(filler(LOW, HIGH, 12))
    assert set(units) == {"A_SWEEP_REENTRY", "B_RANGE_REJECTION", "C_TREND_EXPANSION"}
    for unit in units.values():
        ctx = unit.stage(FunnelStage.CONTEXT)
        assert ctx.retained and ctx.status == UnitStatus.PASSED
        assert ctx.features["reference_bars_present"] == 20
        assert ctx.features["trade_bars_present"] == 12
        assert ctx.features["positive_reference_range"] is True
        assert ctx.features["reference_box_frozen_before_trade_window"] is True
        assert ctx.features["no_future_leakage"] is True
        assert ctx.features["supported_symbol"] and ctx.features["supported_session"]


def test_context_reference_box_is_frozen_strictly_before_the_trade_window():
    window = session_window(SESSION, D)
    assert window.reference_end == window.trade_start
    assert window.reference_start == datetime(2017, 3, 1, 6, tzinfo=UTC)
    assert window.trade_end == datetime(2017, 3, 1, 14, tzinfo=UTC)
    asian = session_window("ASIAN_LONDON", D)
    assert asian.reference_start == datetime(2017, 2, 28, 22, tzinfo=UTC)
    assert asian.reference_end == asian.trade_start == datetime(2017, 3, 1, 6, tzinfo=UTC)
    assert asian.trade_end == datetime(2017, 3, 1, 9, tzinfo=UTC)


# ===========================================================================
# 10. DATA_INVALID excluded from economic outcomes
# ===========================================================================


def test_incomplete_reference_window_is_data_invalid_and_never_a_loss():
    bars = build_session(SESSION, D, ref_low=LOW, ref_high=HIGH,
                         trade_specs=filler(LOW, HIGH, 12))
    truncated = tuple(b for b in bars if b.timestamp != datetime(2017, 3, 1, 7, tzinfo=UTC))
    build = fa.build_analysis_units("DEVELOPMENT", {"EURUSD": truncated}, DATASET_SHA)
    units = [u for u in build.units
             if u.symbol == "EURUSD" and u.session == SESSION and u.trading_date == D.isoformat()]
    assert len(units) == 3
    for unit in units:
        ctx = unit.stage(FunnelStage.CONTEXT)
        assert ctx.status == UnitStatus.DATA_INVALID
        assert not ctx.retained
        assert "DATA_INVALID_REFERENCE_INCOMPLETE" in ctx.reason
        # no economics at all — not a 0R loss
        assert unit.economics.outcome_status is None
        assert unit.economics.net_r is None and unit.economics.gross_r is None
        assert not unit.closed_trade
    rows = fa.stage_rows_for_units(units, scope={})
    context_row = rows[0]
    assert context_row["data_invalid_count"] == 3
    assert context_row["stage_retained_count"] == 0
    assert context_row["closed_trades"] == 0
    assert context_row["conditional_downstream_net_expectancy_r"] is None


def test_data_invalid_sessions_are_counted_separately_in_context_analysis():
    bars = build_session(SESSION, D, ref_low=LOW, ref_high=HIGH,
                         trade_specs=filler(LOW, HIGH, 12))
    build = fa.build_analysis_units("DEVELOPMENT", {"EURUSD": tuple(bars)}, DATASET_SHA)
    analysis = fa.build_context_analysis(build.units)
    assert analysis["context_valid"] == 1
    assert analysis["data_invalid"] == analysis["session_observations"] - 1
    assert analysis["data_invalid_no_reference_bars_at_all"] > 0


# ===========================================================================
# 11/12/13. LOCATION semantics per branch
# ===========================================================================


def test_location_a_requires_a_strict_boundary_breach():
    box, trade = box_and_trade(filler(LOW, HIGH, 12))
    assert fa.location_evidence("A_SWEEP_REENTRY", box, trade)["low_side_interactions"] == 0

    touch_only = filler(LOW, HIGH, 11) + [exact_touch_low(LOW, HIGH, MID)]
    box, trade = box_and_trade(touch_only)
    evidence = fa.location_evidence("A_SWEEP_REENTRY", box, trade)
    assert evidence["low_side_interactions"] == 0, "an exact touch is NOT a breach for A"

    breach = filler(LOW, HIGH, 11) + [sweep_low_reclaim(LOW, HIGH, 0.0005, MID)]
    box, trade = box_and_trade(breach)
    evidence = fa.location_evidence("A_SWEEP_REENTRY", box, trade)
    assert evidence["low_side_interactions"] == 1
    assert evidence["high_side_interactions"] == 0
    assert evidence["first_interaction_time"] is not None


def test_location_a_measures_both_high_and_low_side_interaction():
    specs = (filler(LOW, HIGH, 10)
             + [sweep_low_reclaim(LOW, HIGH, 0.0005, MID),
                sweep_high_reclaim(LOW, HIGH, 0.0005, MID)])
    box, trade = box_and_trade(specs)
    evidence = fa.location_evidence("A_SWEEP_REENTRY", box, trade)
    assert evidence["low_side_interactions"] == 1
    assert evidence["high_side_interactions"] == 1
    assert evidence["both_sides_interacted"] is True


def test_location_b_accepts_an_exact_boundary_touch_without_rejection_close():
    touch_no_reclaim = filler(LOW, HIGH, 11) + [(LOW, LOW, LOW, LOW)]
    box, trade = box_and_trade(touch_no_reclaim)
    a = fa.location_evidence("A_SWEEP_REENTRY", box, trade)
    b = fa.location_evidence("B_RANGE_REJECTION", box, trade)
    assert a["low_side_interactions"] == 0, "no breach -> no A location"
    assert b["low_side_interactions"] == 1, "a touch IS B location"
    # and B location does not require the final inward-close rejection
    assert fa.raw_trigger_scan("B_RANGE_REJECTION", box, trade).fired is False


def test_location_c_requires_extension_beyond_the_boundary_not_a_full_body_close():
    # high pokes above the box but the body stays inside: C LOCATION yes, C TRIGGER no
    poke = filler(LOW, HIGH, 11) + [(MID, HIGH + 0.0005, MID, MID)]
    box, trade = box_and_trade(poke)
    evidence = fa.location_evidence("C_TREND_EXPANSION", box, trade)
    assert evidence["high_side_interactions"] == 1
    assert fa.raw_trigger_scan("C_TREND_EXPANSION", box, trade).fired is False


def test_every_branch_trigger_implies_its_own_location_cumulativity():
    cases = [
        ("A_SWEEP_REENTRY", filler(LOW, HIGH, 11) + [sweep_low_reclaim(LOW, HIGH, 0.0005, MID)]),
        ("B_RANGE_REJECTION", filler(LOW, HIGH, 11) + [exact_touch_low(LOW, HIGH, MID)]),
        ("C_TREND_EXPANSION", filler(LOW, HIGH, 11) + [body_breakout_up(HIGH, 0.0005)]),
    ]
    for branch, specs in cases:
        box, trade = box_and_trade(specs)
        assert fa.raw_trigger_scan(branch, box, trade).fired
        evidence = fa.location_evidence(branch, box, trade)
        assert evidence["low_side_interactions"] + evidence["high_side_interactions"] > 0


# ===========================================================================
# 14/15/16. branch triggers match the frozen engine exactly
# ===========================================================================


def test_a_trigger_matches_frozen_engine_long_and_short():
    for specs, direction in (
        (filler(LOW, HIGH, 11) + [sweep_low_reclaim(LOW, HIGH, SWEEP_DEPTH, ENTRY_A_LONG)], "LONG"),
        (filler(LOW, HIGH, 11) + [sweep_high_reclaim(LOW, HIGH, SWEEP_DEPTH, ENTRY_A_SHORT)], "SHORT"),
    ):
        box, trade = box_and_trade(specs)
        scan = fa.raw_trigger_scan("A_SWEEP_REENTRY", box, trade)
        assert scan.fired and scan.direction == direction
        decision = evaluate("EURUSD", SESSION, _ref(box), trade)
        assert decision.status == "SIGNAL"
        assert decision.setup == "A_SWEEP_REENTRY"
        assert decision.direction == direction
        units = units_for(specs)
        assert units["A_SWEEP_REENTRY"].retained_at(FunnelStage.TRIGGER)


def test_b_trigger_matches_frozen_engine_and_needs_an_exact_tick_touch():
    specs = filler(LOW, HIGH, 11) + [exact_touch_low(LOW, HIGH, MID)]
    box, trade = box_and_trade(specs)
    assert fa.raw_trigger_scan("B_RANGE_REJECTION", box, trade).direction == "LONG"
    decision = evaluate("EURUSD", SESSION, _ref(box), trade)
    assert decision.setup == "B_RANGE_REJECTION" and decision.direction == "LONG"
    assert decision.entry == pytest.approx(LOW)
    units = units_for(specs)
    assert units["B_RANGE_REJECTION"].retained_at(FunnelStage.TRIGGER)


def test_a_sweep_predicate_subsumes_b_on_any_breached_boundary():
    """Structural reason B is near-unreachable — asserted, not assumed."""
    specs = filler(LOW, HIGH, 11) + [sweep_low_reclaim(LOW, HIGH, 0.0005, MID)]
    box, trade = box_and_trade(specs)
    assert fa.raw_trigger_scan("A_SWEEP_REENTRY", box, trade).fired
    assert fa.raw_trigger_scan("B_RANGE_REJECTION", box, trade).fired  # both predicates match
    units = units_for(specs)
    # ...but the frozen A->B->C precedence gives the session to A
    assert units["A_SWEEP_REENTRY"].retained_at(FunnelStage.TRIGGER)
    b_trigger = units["B_RANGE_REJECTION"].stage(FunnelStage.TRIGGER)
    assert not b_trigger.retained
    assert b_trigger.reason == "TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY"


def test_c_trigger_uses_the_frozen_body_close_rule_only():
    specs = filler(LOW, HIGH, 11) + [body_breakout_up(HIGH, 0.0005)]
    box, trade = box_and_trade(specs)
    scan = fa.raw_trigger_scan("C_TREND_EXPANSION", box, trade)
    assert scan.fired and scan.direction == "LONG"
    decision = evaluate("EURUSD", SESSION, _ref(box), trade)
    assert decision.setup == "C_TREND_EXPANSION"
    assert decision.entry_order_type == "LIMIT"
    assert decision.entry == pytest.approx(MID), "C entry is the reference EQ, not a retest level"
    units = units_for(specs)
    assert units["C_TREND_EXPANSION"].retained_at(FunnelStage.GEOMETRY)

    down = filler(LOW, HIGH, 11) + [body_breakout_down(LOW, 0.0005)]
    box, trade = box_and_trade(down)
    assert fa.raw_trigger_scan("C_TREND_EXPANSION", box, trade).direction == "SHORT"


# ===========================================================================
# 17/18. ambiguity, fail-closed
# ===========================================================================


def test_a_dual_side_sweep_is_ambiguous_and_fails_closed():
    dual = (MID, HIGH + 0.0005, LOW - 0.0005, MID)  # breaches both, closes inside
    specs = filler(LOW, HIGH, 11) + [dual]
    box, trade = box_and_trade(specs)
    scan = fa.raw_trigger_scan("A_SWEEP_REENTRY", box, trade)
    assert scan.ambiguous and scan.direction is None
    decision = evaluate("EURUSD", SESSION, _ref(box), trade)
    assert decision.status == "NO_TRADE"
    assert decision.reason_code == "AMBIGUOUS_DUAL_SIDE_SWEEP"

    units = units_for(specs)
    trigger = units["A_SWEEP_REENTRY"].stage(FunnelStage.TRIGGER)
    assert trigger.status == UnitStatus.AMBIGUOUS
    assert not trigger.retained
    assert trigger.reason == "AMBIGUOUS_DUAL_SIDE_SWEEP"
    assert units["A_SWEEP_REENTRY"].economics.net_r is None
    rows = fa.stage_rows_for_units([units["A_SWEEP_REENTRY"]], scope={})
    assert rows[2]["ambiguity_count"] == 1


def test_b_dual_boundary_rejection_is_ambiguous_and_fails_closed():
    dual_touch = (MID, HIGH, LOW, MID)  # touches both boundaries exactly, closes inside
    specs = filler(LOW, HIGH, 11) + [dual_touch]
    box, trade = box_and_trade(specs)
    scan = fa.raw_trigger_scan("B_RANGE_REJECTION", box, trade)
    assert scan.ambiguous
    decision = evaluate("EURUSD", SESSION, _ref(box), trade)
    assert decision.reason_code == "AMBIGUOUS_DUAL_BOUNDARY_REJECTION"
    units = units_for(specs)
    trigger = units["B_RANGE_REJECTION"].stage(FunnelStage.TRIGGER)
    assert trigger.status == UnitStatus.AMBIGUOUS and not trigger.retained
    assert trigger.reason == "AMBIGUOUS_DUAL_BOUNDARY_REJECTION"


# ===========================================================================
# 19/20/21. geometry
# ===========================================================================


def test_a_sweep_stop_protection_geometry_rejects_shallow_sweeps():
    """Deep wick -> 25% stop sits inside the sweep extreme -> frozen rejection."""
    deep = sweep_low_reclaim(LOW, HIGH, R0 * 1.5, MID)  # wick deeper than R0
    specs = filler(LOW, HIGH, 11) + [deep]
    box, trade = box_and_trade(specs)
    decision = evaluate("EURUSD", SESSION, _ref(box), trade)
    assert decision.status == "NO_TRADE"
    assert decision.reason_code == "SWEEP_STOP_DOES_NOT_PROTECT_EXTREME"

    units = units_for(specs)
    unit = units["A_SWEEP_REENTRY"]
    assert unit.retained_at(FunnelStage.TRIGGER), "it DID trigger"
    geometry = unit.stage(FunnelStage.GEOMETRY)
    assert not geometry.retained
    assert geometry.reason == "SWEEP_STOP_DOES_NOT_PROTECT_EXTREME"
    assert unit.economics.net_r is None  # not repaired, not a 0R loss

    diagnostics = fa.build_geometry_analysis([unit])
    row = next(g for g in diagnostics["segments"]
               if g["branch"] == "A_SWEEP_REENTRY" and g["symbol"] == "EURUSD"
               and g["session"] == SESSION)
    assert row["triggered"] == 1
    assert row["geometry_valid"] == 0
    assert row["sweep_stop_does_not_protect_extreme"] == 1
    assert row["sweep_stop_rejection_pct"] == 100.0
    assert row["other_geometry_rejection_reasons"] == {}


def test_a_shallow_sweep_passes_stop_protection():
    shallow = sweep_low_reclaim(LOW, HIGH, SWEEP_DEPTH, ENTRY_A_LONG)
    units = units_for(filler(LOW, HIGH, 11) + [shallow])
    unit = units["A_SWEEP_REENTRY"]
    geometry = unit.stage(FunnelStage.GEOMETRY)
    assert geometry.retained
    assert geometry.features["sweep_stop_protects_extreme"] is True
    assert geometry.features["stop_loss"] < LOW - SWEEP_DEPTH


def test_quarter_range_geometry_holds_for_every_branch():
    cases = {
        "A_SWEEP_REENTRY": filler(LOW, HIGH, 11) + [sweep_low_reclaim(LOW, HIGH, SWEEP_DEPTH, ENTRY_A_LONG)],
        "B_RANGE_REJECTION": filler(LOW, HIGH, 11) + [exact_touch_low(LOW, HIGH, MID)],
        "C_TREND_EXPANSION": filler(LOW, HIGH, 11) + [body_breakout_up(HIGH, 0.0005)],
    }
    for branch, specs in cases.items():
        unit = units_for(specs)[branch]
        geometry = unit.stage(FunnelStage.GEOMETRY)
        assert geometry.retained, branch
        f = geometry.features
        assert f["quarter_reference_range_stop"] is True
        assert f["risk_distance"] == pytest.approx(R0)
        assert f["quarter_range_r0"] == pytest.approx(R0)
        assert f["positive_risk_distance"] is True
        assert f["stop_on_correct_side_of_entry"] is True
        assert f["target_direction_valid"] is True
        assert f["target_4r_distance_valid"] is True
        assert f["target_5r_distance_valid"] is True
        assert f["branch_entry_geometry_valid"] is True
        assert abs(f["target_4r"] - f["entry"]) == pytest.approx(4 * R0)
        assert abs(f["target_5r"] - f["entry"]) == pytest.approx(5 * R0)


def test_c_eq_geometry_is_unchanged_entry_at_equilibrium():
    unit = units_for(filler(LOW, HIGH, 11) + [body_breakout_up(HIGH, 0.0005)])["C_TREND_EXPANSION"]
    f = unit.stage(FunnelStage.GEOMETRY).features
    assert f["entry"] == pytest.approx(MID), "EQ limit, never a broken-boundary retest"
    assert f["entry_order_type"] == "LIMIT"
    assert f["stop_loss"] == pytest.approx(MID - R0)
    assert f["sweep_stop_protects_extreme"] is None  # not applicable to C


# ===========================================================================
# 22-27. execution semantics
# ===========================================================================


def test_a_next_executable_price_behaviour_unchanged():
    """A is MARKET: it fills at the OPEN of the first bar after the signal close."""
    shallow = sweep_low_reclaim(LOW, HIGH, SWEEP_DEPTH, ENTRY_A_LONG)
    specs = filler(LOW, HIGH, 5) + [shallow] + filler(LOW, HIGH, 6)
    unit = units_for(specs)["A_SWEEP_REENTRY"]
    assert unit.retained_at(FunnelStage.EXECUTION)
    assert unit.economics.order_type == "MARKET"
    signal_bar_open = session_window(SESSION, D).trade_start + timedelta(minutes=15 * 5)
    assert unit.economics.entry_time == signal_bar_open + timedelta(minutes=15)
    assert unit.economics.entry_price == pytest.approx(inside(LOW, HIGH)[0])


def test_b_limit_fill_at_the_boundary_price():
    # the fill bar must only TOUCH the boundary: a breach would make it an A
    # sweep and the frozen A->B->C precedence would reassign the session.
    specs = filler(LOW, HIGH, 3) + [exact_touch_low(LOW, HIGH, MID)] + [
        (MID, MID, LOW, LOW + 0.0002)] + filler(LOW, HIGH, 7)
    unit = units_for(specs)["B_RANGE_REJECTION"]
    assert unit.retained_at(FunnelStage.EXECUTION)
    assert unit.economics.order_type == "LIMIT"
    assert unit.economics.entry_price == pytest.approx(LOW)


def test_c_limit_fill_at_equilibrium():
    specs = filler(LOW, HIGH, 3) + [body_breakout_up(HIGH, 0.0005)] + [
        (HIGH, HIGH + 0.0002, MID - 0.0001, HIGH)] + filler(LOW, HIGH, 7)
    unit = units_for(specs)["C_TREND_EXPANSION"]
    assert unit.retained_at(FunnelStage.EXECUTION)
    assert unit.economics.entry_price == pytest.approx(MID)


def test_unfilled_and_expired_limits_are_tracked_separately_and_never_scored():
    # breakout on bar 3, price never returns to EQ -> the limit expires
    away = (HIGH + 0.0010, HIGH + 0.0015, HIGH + 0.0008, HIGH + 0.0012)
    specs = filler(LOW, HIGH, 3) + [body_breakout_up(HIGH, 0.0005)] + [away] * 8
    unit = units_for(specs)["C_TREND_EXPANSION"]
    execution = unit.stage(FunnelStage.EXECUTION)
    assert not execution.retained
    assert execution.status == UnitStatus.EXPIRED
    assert unit.economics.outcome_status is None
    assert unit.economics.gross_r is None and unit.economics.net_r is None
    assert not unit.closed_trade

    rows = fa.stage_rows_for_units([unit], scope={})
    execution_row = rows[4]
    assert execution_row["stage_input_count"] == 1
    assert execution_row["stage_retained_count"] == 0
    assert execution_row["expired"] == 0  # fate counts describe the RETAINED cohort
    assert execution_row["closed_trades"] == 0
    assert execution_row["conditional_downstream_net_expectancy_r"] is None

    diagnostics = fa.build_execution_analysis([unit])
    row = next(e for e in diagnostics["segments"]
               if e["branch"] == "C_TREND_EXPANSION" and e["symbol"] == "EURUSD"
               and e["session"] == SESSION)
    assert row["geometry_valid_signals"] == 1
    assert row["fills"] == 0 and row["expired"] == 1 and row["unfilled"] == 0
    assert row["fill_rate"] == 0.0


def test_limit_generated_on_the_final_candle_expires_as_never_workable():
    specs = filler(LOW, HIGH, 11) + [body_breakout_up(HIGH, 0.0005)]
    unit = units_for(specs)["C_TREND_EXPANSION"]
    execution = unit.stage(FunnelStage.EXECUTION)
    assert execution.status == UnitStatus.EXPIRED
    assert execution.reason == "LIMIT_NEVER_WORKABLE_IN_TRADE_WINDOW"
    assert execution.features["never_workable"] is True
    diagnostics = fa.build_execution_analysis([unit])
    row = next(e for e in diagnostics["segments"] if e["branch"] == "C_TREND_EXPANSION"
               and e["symbol"] == "EURUSD" and e["session"] == SESSION)
    assert row["expired_never_workable"] == 1


def test_same_bar_ambiguity_is_recorded_not_silently_resolved():
    """A LIMIT whose fill bar also reaches a target records an ambiguity."""
    specs = filler(LOW, HIGH, 3) + [body_breakout_up(HIGH, 0.0005)] + [
        (HIGH, MID + 4 * R0 + 0.0001, MID - 0.0001, HIGH)] + filler(LOW, HIGH, 7)
    unit = units_for(specs)["C_TREND_EXPANSION"]
    assert unit.retained_at(FunnelStage.EXECUTION)
    assert unit.economics.same_bar_ambiguities >= 1
    rows = fa.stage_rows_for_units([unit], scope={})
    assert rows[4]["ambiguity_count"] >= 1


# ===========================================================================
# 28-32. outcome economics
# ===========================================================================


def _a_long_setup(trade_tail):
    """2 quiet bars, a geometry-valid long sweep, then ``trade_tail``.

    The first tail bar must OPEN at ``ENTRY_A_LONG`` so the MARKET
    next-executable-price fill equals the frozen decision entry and R maths is
    exact.
    """
    shallow = sweep_low_reclaim(LOW, HIGH, SWEEP_DEPTH, ENTRY_A_LONG)
    return filler(LOW, HIGH, 2) + [shallow] + trade_tail


def test_friction_is_applied_after_fill_and_gross_net_accounting_is_consistent():
    stop_out = (ENTRY_A_LONG, ENTRY_A_LONG, STOP_A_LONG - 0.0002, STOP_A_LONG - 0.0001)
    unit = units_for(_a_long_setup([stop_out] + filler(LOW, HIGH, 8)))["A_SWEEP_REENTRY"]
    e = unit.economics
    assert e.outcome_status == UnitStatus.CLOSED
    assert e.entry_price == pytest.approx(ENTRY_A_LONG)
    assert e.gross_r == pytest.approx(-1.0)
    assert e.gross_r is not None and e.friction_r is not None
    assert e.friction_r > 0
    assert e.net_r == pytest.approx(e.gross_r - e.friction_r)
    assert e.net_r < e.gross_r


def test_partial_4r_and_runner_5r_accounting_is_weighted_not_relabelled():
    """75 % at 4R + 25 % at 5R = 4.25R gross — never called a '5R result'."""
    runner = (ENTRY_A_LONG, ENTRY_A_LONG + 5 * R0 + 0.0005, ENTRY_A_LONG,
              ENTRY_A_LONG + 5 * R0)
    unit = units_for(_a_long_setup([runner] + filler(LOW, HIGH, 8)))["A_SWEEP_REENTRY"]
    e = unit.economics
    assert e.entry_price == pytest.approx(ENTRY_A_LONG)
    assert e.tp1_4r_hit is True and e.runner_5r_hit is True
    assert e.gross_r == pytest.approx(0.75 * 4.0 + 0.25 * 5.0) == pytest.approx(4.25)
    assert e.gross_r != pytest.approx(5.0)
    assert e.net_r == pytest.approx(4.25 - e.friction_r)


def test_runner_breakeven_accounting():
    """4R hit, stop moves to entry, runner then stops out at breakeven -> 3.0R."""
    tp1 = (ENTRY_A_LONG, ENTRY_A_LONG + 4 * R0 + 0.0001, ENTRY_A_LONG,
           ENTRY_A_LONG + 4 * R0)
    back = (ENTRY_A_LONG, ENTRY_A_LONG, ENTRY_A_LONG - 0.0005, ENTRY_A_LONG - 0.0004)
    unit = units_for(_a_long_setup([tp1, back] + filler(LOW, HIGH, 7)))["A_SWEEP_REENTRY"]
    e = unit.economics
    assert e.tp1_4r_hit is True
    assert e.runner_breakeven is True
    assert e.runner_5r_hit is False
    assert e.gross_r == pytest.approx(0.75 * 4.0)  # runner exits at +0R
    assert e.exit_reason == "STOP"


def test_holding_time_is_preserved():
    # same-bar resolution => 0.0 hours held, 1 bar (recorded, not invented)
    runner = (ENTRY_A_LONG, ENTRY_A_LONG + 5 * R0 + 0.0005, ENTRY_A_LONG,
              ENTRY_A_LONG + 5 * R0)
    quick = units_for(_a_long_setup([runner] + filler(LOW, HIGH, 8)))["A_SWEEP_REENTRY"]
    assert quick.economics.bars_held == 1
    assert quick.economics.holding_hours == pytest.approx(0.0)

    # multi-bar trade => strictly positive holding time
    tp1 = (ENTRY_A_LONG, ENTRY_A_LONG + 4 * R0 + 0.0001, ENTRY_A_LONG,
           ENTRY_A_LONG + 4 * R0)
    back = (ENTRY_A_LONG, ENTRY_A_LONG, ENTRY_A_LONG - 0.0005, ENTRY_A_LONG - 0.0004)
    held = units_for(_a_long_setup([tp1, back] + filler(LOW, HIGH, 7)))["A_SWEEP_REENTRY"]
    assert held.economics.bars_held == 2
    assert held.economics.holding_hours == pytest.approx(0.25)
    assert held.economics.exit_time > held.economics.entry_time


def _ref(box):
    """A minimal reference-candle set reproducing ``box`` for direct engine calls."""
    t0 = datetime(2017, 3, 1, 6, tzinfo=UTC)
    return (Candle(time=t0, open=box.mid, high=box.high, low=box.low, close=box.mid),)
