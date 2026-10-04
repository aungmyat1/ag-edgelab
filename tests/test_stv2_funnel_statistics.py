"""STV2 strategy-funnel statistics and metric semantics.

Covers requirements 34-38 of STV2_STRATEGY_FUNNEL_ANALYZER_V1: profit-factor
edge cases, null (never zero) for undefined metrics, retained-percentage maths,
conditional expectancy semantics, and the prohibition on fabricated 0R.
"""

from __future__ import annotations

from datetime import date

import pytest

from ag_edgelab.campaigns.session_trade_v2 import funnel_analyzer as fa
from ag_edgelab.campaigns.session_trade_v2.funnel_models import FILTER_STAGES, UnitStatus
from ag_edgelab.contracts.funnel import FunnelStage
from tests.stv2_funnel_fixtures import (
    DATASET_SHA,
    body_breakout_up,
    build_session,
    filler,
    sweep_low_reclaim,
)

LOW, HIGH = 1.1000, 1.1100
R0 = (HIGH - LOW) * 0.25
MID = (LOW + HIGH) / 2.0
SESSION = "LONDON_NEWYORK"
SWEEP_DEPTH = R0 * 0.2
ENTRY_A = LOW + 0.0005


# ===========================================================================
# 34. PF no-loss edge case + honest infinity semantics
# ===========================================================================


def test_profit_factor_semantics_are_explicit_and_never_a_sentinel():
    pf, status = fa.profit_factor([])
    assert pf is None and status == "UNDEFINED_NO_CLOSED_TRADES"

    pf, status = fa.profit_factor([2.0, 1.0])
    assert pf is None, "no losses -> PF is infinite, stored as null + reason"
    assert status == "INFINITE_NO_LOSING_TRADES"
    assert pf != 999 and pf != float("inf")

    pf, status = fa.profit_factor([0.0, 0.0])
    assert pf is None and status == "UNDEFINED_NO_GROSS_PROFIT_AND_NO_LOSS"

    pf, status = fa.profit_factor([2.0, -1.0])
    assert pf == pytest.approx(2.0) and status == "DEFINED"

    pf, status = fa.profit_factor([-1.0, -1.0])
    assert pf == pytest.approx(0.0) and status == "DEFINED"


def test_infinite_pf_is_json_serializable_without_nan_or_inf():
    import json

    pf, status = fa.profit_factor([4.25])
    payload = {"conditional_downstream_net_pf": pf, "conditional_downstream_net_pf_status": status}
    # strict RFC JSON: would raise on Infinity/NaN
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload


# ===========================================================================
# 35. undefined metrics remain null
# ===========================================================================


def test_undefined_metrics_are_null_not_zero():
    stats = fa._cohort_stats([])
    assert stats["closed_trades"] == 0
    for key in (
        "win_rate", "win_ci95_low", "win_ci95_high",
        "conditional_downstream_gross_expectancy_r",
        "conditional_downstream_net_expectancy_r",
        "conditional_downstream_gross_pf", "conditional_downstream_net_pf",
        "conditional_downstream_gross_r", "conditional_downstream_net_r",
        "friction_r", "average_cost_r",
    ):
        assert stats[key] is None, key


def test_empty_segment_rows_have_null_economics_and_null_retention_pct():
    rows = fa.stage_rows_for_units([], scope={"segment_id": "X"})
    assert len(rows) == len(FILTER_STAGES)
    for row in rows:
        assert row["stage_input_count"] == 0
        assert row["stage_retained_count"] == 0
        assert row["stage_retained_pct"] is None, "0/0 retention is undefined, not 0%"
        assert row["conditional_downstream_net_expectancy_r"] is None
        assert row["win_rate"] is None


# ===========================================================================
# 36. retained percentage maths + cumulative funnel
# ===========================================================================


def _mixed_units():
    """One A sweep that trades, one C breakout that never fills, one dead session."""
    bars: list = []
    bars += build_session(SESSION, date(2017, 3, 1), ref_low=LOW, ref_high=HIGH,
                          trade_specs=filler(LOW, HIGH, 2)
                          + [sweep_low_reclaim(LOW, HIGH, SWEEP_DEPTH, ENTRY_A)]
                          + [(ENTRY_A, ENTRY_A, ENTRY_A - R0 - 0.0002, ENTRY_A - R0 - 0.0001)]
                          + filler(LOW, HIGH, 8))
    away = (HIGH + 0.0010, HIGH + 0.0015, HIGH + 0.0008, HIGH + 0.0012)
    bars += build_session(SESSION, date(2017, 3, 2), ref_low=LOW, ref_high=HIGH,
                          trade_specs=filler(LOW, HIGH, 3)
                          + [body_breakout_up(HIGH, 0.0005)] + [away] * 8)
    bars += build_session(SESSION, date(2017, 3, 3), ref_low=LOW, ref_high=HIGH,
                          trade_specs=filler(LOW, HIGH, 12))
    build = fa.build_analysis_units("DEVELOPMENT", {"EURUSD": tuple(bars)}, DATASET_SHA)
    return [u for u in build.units
            if u.symbol == "EURUSD" and u.session == SESSION
            and u.trading_date in ("2017-03-01", "2017-03-02", "2017-03-03")]


def test_retained_percentage_is_retained_over_input_at_every_stage():
    units = _mixed_units()
    rows = fa.stage_rows_for_units(units, scope={})
    for row in rows:
        if row["stage_input_count"]:
            assert row["stage_retained_pct"] == pytest.approx(
                row["stage_retained_count"] / row["stage_input_count"] * 100.0, abs=1e-4
            )


def test_funnel_is_cumulative_each_stage_input_equals_previous_retained():
    units = _mixed_units()
    rows = fa.stage_rows_for_units(units, scope={})
    for previous, current in zip(rows, rows[1:]):
        assert current["stage_input_count"] == previous["stage_retained_count"]
    assert rows[0]["stage_input_count"] == len(units)


def test_a_record_failing_an_early_stage_never_reappears_downstream():
    units = _mixed_units()
    for unit in units:
        failed_at = None
        for stage in FILTER_STAGES:
            evaluation = unit.stage(stage)
            if failed_at is not None:
                assert evaluation is None, (
                    f"{unit.branch} has a {stage} result after failing {failed_at}"
                )
                continue
            if evaluation is None or not evaluation.retained:
                failed_at = stage
        if failed_at is not None:
            for stage in FILTER_STAGES[FILTER_STAGES.index(failed_at) + 1:]:
                assert not unit.retained_at(stage)
                assert not unit.reached(stage)


# ===========================================================================
# 37. conditional expectancy semantics
# ===========================================================================


def test_conditional_economics_only_count_closed_trades_of_the_retained_cohort():
    units = _mixed_units()
    rows = fa.stage_rows_for_units(units, scope={})
    closed = [u for u in units if u.closed_trade]
    assert len(closed) == 1
    expected = closed[0].economics.net_r
    for row in rows:
        assert row["closed_trades"] == 1
        assert row["conditional_downstream_net_expectancy_r"] == pytest.approx(expected, abs=1e-6)
        assert row["metric_semantics"]["economics"] == (
            "CONDITIONAL_DOWNSTREAM_CLOSED_TRADES_ONLY"
        )


def test_conditional_shift_is_zero_by_construction_and_declared_as_such():
    """The cohort cannot change across stages, so no decay curve is manufactured."""
    units = _mixed_units()
    rows = fa.stage_rows_for_units(units, scope={})
    assert rows[0]["conditional_net_expectancy_shift_r"] is None  # no previous stage
    for row in rows[1:]:
        assert row["conditional_net_expectancy_shift_r"] == pytest.approx(0.0)
        assert row["win_rate_lift_pp"] == pytest.approx(0.0)

    analysis = fa.build_conditional_expectancy_analysis(units)
    assert analysis["classification"] == "DIAGNOSTIC / NON-CAUSAL"
    assert "NOT causal estimates" in analysis["interpretation_rule"]


# ===========================================================================
# 38. rejected observations are not assigned fake 0R
# ===========================================================================


def test_rejected_and_unfilled_observations_carry_no_economics_at_all():
    units = _mixed_units()
    rejected = [u for u in units if not u.closed_trade]
    assert rejected, "fixture must contain rejected observations"
    for unit in rejected:
        assert unit.economics.net_r is None
        assert unit.economics.gross_r is None
        assert unit.economics.outcome_status in (None, UnitStatus.OPEN_AT_END)

    expired = [u for u in units
               if (s := u.stage(FunnelStage.EXECUTION)) is not None
               and s.status == UnitStatus.EXPIRED]
    assert expired, "fixture must contain an expired limit"
    for unit in expired:
        assert unit.economics.net_r is None


def test_outcome_key_maps_only_closed_trades_so_no_zero_is_imputed():
    bars = build_session(SESSION, date(2017, 3, 2), ref_low=LOW, ref_high=HIGH,
                         trade_specs=filler(LOW, HIGH, 3) + [body_breakout_up(HIGH, 0.0005)]
                         + [(HIGH + 0.0010, HIGH + 0.0015, HIGH + 0.0008, HIGH + 0.0012)] * 8)
    build = fa.build_analysis_units("DEVELOPMENT", {"EURUSD": tuple(bars)}, DATASET_SHA)
    c_units = [u for u in build.units
               if u.branch == "C_TREND_EXPANSION" and u.session == SESSION
               and u.trading_date == "2017-03-02"]
    assert c_units and c_units[0].retained_at(FunnelStage.GEOMETRY)
    assert not c_units[0].retained_at(FunnelStage.EXECUTION)
    # the expired proposal has no key in the outcome maps at all
    assert c_units[0].analysis_unit_id not in build.outcomes_net_r
    assert c_units[0].analysis_unit_id not in build.outcomes_gross_r


def test_friction_analysis_reports_null_not_zero_for_segments_without_trades():
    units = _mixed_units()
    analysis = fa.build_friction_analysis(units)
    empty = [s for s in analysis["segments"] if s["closed_trades"] == 0]
    assert empty
    for segment in empty:
        assert segment["gross_r"] is None
        assert segment["net_r"] is None
        assert segment["friction_r"] is None
        assert segment["gross_positive_net_non_positive"] is None
        assert "not applicable" in segment["note"]


def test_open_at_end_fills_are_censored_from_closed_trade_economics():
    """A filled trade still running at the data edge is never merged into R stats."""
    specs = (filler(LOW, HIGH, 3) + [body_breakout_up(HIGH, 0.0005)]
             + [(HIGH, HIGH + 0.0002, MID - 0.0001, HIGH)] + filler(LOW, HIGH, 7))
    bars = build_session(SESSION, date(2017, 3, 1), ref_low=LOW, ref_high=HIGH,
                         trade_specs=specs)
    build = fa.build_analysis_units("DEVELOPMENT", {"EURUSD": tuple(bars)}, DATASET_SHA)
    unit = next(u for u in build.units
                if u.branch == "C_TREND_EXPANSION" and u.session == SESSION
                and u.trading_date == "2017-03-01")
    assert unit.retained_at(FunnelStage.EXECUTION)
    assert unit.economics.outcome_status == UnitStatus.OPEN_AT_END
    assert unit.economics.gross_r is None and unit.economics.net_r is None
    assert not unit.closed_trade
    rows = fa.stage_rows_for_units([unit], scope={})
    assert rows[4]["stage_retained_count"] == 1
    assert rows[4]["closed_trades"] == 0
    assert rows[4]["conditional_downstream_net_expectancy_r"] is None
    assert rows[4]["open_at_end"] == 1
