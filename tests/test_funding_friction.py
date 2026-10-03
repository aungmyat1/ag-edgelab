from datetime import datetime, timedelta, timezone

import pytest

from ag_edgelab.friction.model import (
    FundingAuthority,
    FundingEvent,
    FundingSchedule,
    FrictionScenario,
    NetEconomicQualification,
    apply_friction,
    assess_net_economic_qualification,
    funding_cost_r,
)

Z = timezone.utc
T0 = datetime(2026, 6, 1, tzinfo=Z)


def _schedule(rates, authority=FundingAuthority.BYBIT_PUBLIC_HISTORY):
    events = tuple(FundingEvent(timestamp=T0 + timedelta(hours=8 * i), rate=r) for i, r in enumerate(rates))
    return FundingSchedule(authority=authority, events=events, source="test", source_sha256="ab" * 32)


def test_existing_scenario_fields_unchanged_when_funding_absent():
    scenario = FrictionScenario("BASE", spread_r=0.05, commission_r=0.02, slippage_r=0.01)
    assert scenario.funding_r == 0.0
    assert scenario.funding_provenance == "UNDECLARED"
    assert scenario.total_cost_r == pytest.approx(0.08)
    assert apply_friction(0.20, scenario) == pytest.approx(0.12)
    assert scenario.funding_declared is False


def test_funding_component_extends_total_cost():
    scenario = FrictionScenario("PERP", spread_r=0.05, funding_r=0.03, funding_provenance="BYBIT_PUBLIC_HISTORY")
    assert scenario.total_cost_r == pytest.approx(0.08)
    assert scenario.funding_declared is True


def test_funding_charged_per_settlement_crossing_in_r():
    # entry 100 stop 90 -> notional/risk = 10x; one 0.01% long-negative funding
    schedule = _schedule([0.0001])
    cost = funding_cost_r(
        entry_time=T0 - timedelta(hours=1), exit_time=T0 + timedelta(hours=1),
        side="LONG", entry_price=100.0, stop_price=90.0, schedule=schedule,
    )
    assert cost == pytest.approx(0.0001 * 10)


def test_short_sign_flips_funding():
    schedule = _schedule([0.0001])
    long_cost = funding_cost_r(
        entry_time=T0 - timedelta(hours=1), exit_time=T0 + timedelta(hours=1),
        side="LONG", entry_price=100.0, stop_price=90.0, schedule=schedule)
    short_cost = funding_cost_r(
        entry_time=T0 - timedelta(hours=1), exit_time=T0 + timedelta(hours=1),
        side="SHORT", entry_price=100.0, stop_price=110.0, schedule=schedule)
    assert long_cost == pytest.approx(-short_cost)


def test_no_settlement_inside_window_no_cost():
    schedule = _schedule([0.0001])
    cost = funding_cost_r(
        entry_time=T0 + timedelta(hours=1), exit_time=T0 + timedelta(hours=7),
        side="LONG", entry_price=100.0, stop_price=90.0, schedule=schedule)
    assert cost == 0.0


def test_multiple_settlements_accumulate():
    schedule = _schedule([0.0001, 0.0002, 0.0001])
    cost = funding_cost_r(
        entry_time=T0 - timedelta(hours=1), exit_time=T0 + timedelta(hours=17),
        side="LONG", entry_price=100.0, stop_price=99.0, schedule=schedule)
    assert cost == pytest.approx((0.0004) * 100)


def test_settlement_exactly_at_entry_is_not_charged():
    schedule = _schedule([0.0001])
    cost = funding_cost_r(
        entry_time=T0, exit_time=T0 + timedelta(hours=1),
        side="LONG", entry_price=100.0, stop_price=90.0, schedule=schedule)
    assert cost == 0.0


def test_conservative_absolute_never_pays():
    schedule = _schedule([-0.0001])
    economic = funding_cost_r(
        entry_time=T0 - timedelta(hours=1), exit_time=T0 + timedelta(hours=1),
        side="LONG", entry_price=100.0, stop_price=90.0, schedule=schedule)
    conservative = funding_cost_r(
        entry_time=T0 - timedelta(hours=1), exit_time=T0 + timedelta(hours=1),
        side="LONG", entry_price=100.0, stop_price=90.0, schedule=schedule,
        conservative_absolute=True)
    assert economic < 0  # negative funding pays the long economically
    assert conservative > 0


def test_missing_authority_raises_and_disqualifies():
    schedule = FundingSchedule(authority=FundingAuthority.MISSING, events=())
    with pytest.raises(ValueError):
        funding_cost_r(
            entry_time=T0, exit_time=T0 + timedelta(hours=1),
            side="LONG", entry_price=100.0, stop_price=90.0, schedule=schedule)
    assert assess_net_economic_qualification(
        instrument_is_perpetual=True, funding_authority=FundingAuthority.MISSING,
        dataset_is_authoritative=True) == NetEconomicQualification.NOT_ECONOMICALLY_QUALIFIED


def test_qualification_requires_authoritative_dataset_and_funding():
    q = assess_net_economic_qualification
    assert q(instrument_is_perpetual=True, funding_authority=FundingAuthority.BYBIT_PUBLIC_HISTORY,
             dataset_is_authoritative=True) == NetEconomicQualification.PASS
    assert q(instrument_is_perpetual=True, funding_authority=FundingAuthority.BYBIT_PUBLIC_HISTORY,
             dataset_is_authoritative=False) == NetEconomicQualification.NOT_ECONOMICALLY_QUALIFIED
    assert q(instrument_is_perpetual=True, funding_authority=FundingAuthority.SYNTHETIC_FIXTURE,
             dataset_is_authoritative=True) == NetEconomicQualification.NOT_ECONOMICALLY_QUALIFIED
    assert q(instrument_is_perpetual=False, funding_authority=FundingAuthority.UNDECLARED,
             dataset_is_authoritative=True) == NetEconomicQualification.PASS
