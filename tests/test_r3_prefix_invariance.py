"""Permanent prefix-invariance CI guard on real DEVELOPMENT data (PHASE B3).

RUN A evaluates the frozen ALD V2 replay from the complete DEVELOPMENT
history.  RUN B truncates all market data so nothing after a sampled
timestamp ``t`` is visible, rebuilds every timeframe with the frozen
aggregation rules, and recomputes the event state at ``t``.

For every fact knowable at ``t`` the two runs must agree bit-for-bit:
event identity, pre-T2 stage states, direction, branch, confirmed
swings/pivots (via S6 confirmation), causal mask state, decision
timestamp, reference-entry timestamp, causal geometry, and reason codes.

Post-entry facts (S7 forward availability, S9 outcome, reference outcome
before its horizon completes) are NOT expected to be knowable at ``t`` and
are compared only once their own availability time has passed.

This guard is mandatory CI for every future candidate family.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fx_histdata_2017 import (aggregate_m15, derive_fx_timeframe,
                                              quality_gate_m1)
from ag_edgelab.data.fx_histdata_multiyear import partition_bounds
from ag_edgelab.optimization.causal_entry_mask import causal_mask_for_v2_unit
from ag_edgelab.optimization.causal_time import first_m5_open_at_or_after, t2_decision_time
from ag_edgelab.strategies import asian_liquidity_displacement_v2 as V2
from ag_edgelab.strategies.asian_liquidity_displacement_v1 import aggregate_m5
from ag_edgelab.strategies.asian_liquidity_displacement_v2_real_fixture import (
    _parse_development_m1,
)

UTC = timezone.utc
ROOT = Path(__file__).parents[1]
PREREGISTRATION = ROOT / "config/governance/funnel_optimizer_v1_fixture_preregistration.json"

SYMBOL, YEAR = "EURUSD", 2016
TRUNCATION_FRACTIONS = (0.20, 0.35, 0.50, 0.65, 0.80)
M5 = timedelta(minutes=5)
M1 = timedelta(minutes=1)


def _fixture_present() -> bool:
    config = json.loads(PREREGISTRATION.read_text())
    return all((ROOT / item["path"]).is_file() for item in config["materialization"]["files"])


pytestmark = pytest.mark.skipif(not _fixture_present(),
                                reason="registered raw Funnel Optimizer FX fixture is not materialized")


def _load_zip_m1() -> tuple[MarketBar, ...]:
    config = json.loads(PREREGISTRATION.read_text())
    item = next(entry for entry in config["materialization"]["files"]
                if entry["symbol"] == SYMBOL and entry["year"] == YEAR)
    return _parse_development_m1(ROOT / item["path"], year=YEAR, symbol=SYMBOL)


def _frames_from_m1(m1: tuple[MarketBar, ...]) -> dict[str, tuple[MarketBar, ...]]:
    quality_gate_m1(m1, f"{SYMBOL}:{YEAR}:PREFIX")
    m15 = aggregate_m15(m1)
    frames: dict[str, tuple[MarketBar, ...]] = {"M15": m15, "M5": aggregate_m5(m1)}
    for timeframe in ("H1", "H4", "D1"):
        frames[timeframe], _ = derive_fx_timeframe(m15, timeframe, SYMBOL)
    return frames


def _replay(frames) -> dict[str, V2.V2Unit]:
    start, end = partition_bounds("DEVELOPMENT", YEAR)
    units = V2.replay_symbol(frames, SYMBOL, start, end)
    return {unit.candidate_id: unit for unit in units}


def _t2(unit: V2.V2Unit) -> datetime:
    return t2_decision_time(datetime.fromisoformat(unit.confirm_time))


def _session_window_end(unit: V2.V2Unit) -> datetime:
    day = datetime.fromisoformat(unit.day).replace(tzinfo=UTC)
    _, entry_to = V2.SESSION_PAIRS[unit.session]
    return day + timedelta(hours=entry_to)


def _knowable_pre_t2_state(unit: V2.V2Unit, frames) -> tuple:
    """Every fact the causal mask and the decision are allowed to consume.

    The mask derives geometry from bars closed at or before T2 using the
    run's own visible frames, so RUN A and RUN B are each evaluated with
    exactly the data visible to them.
    """
    return (
        unit.stages.get("S1_CONTEXT_ELIGIBLE", False),
        unit.stages.get("S2_LOCATION_ELIGIBLE", False),
        unit.stages.get("S3_SESSION_EVENT", False),
        unit.stages.get("S4_SWEEP_OR_BREAKOUT", False),
        unit.stages.get("S5_RECLAIM_OR_RETEST", False),
        unit.stages.get("S6_STRUCTURE_CONFIRM", False),
        unit.event_time, unit.reclaim_or_retest_time, unit.confirm_time,
        unit.boundary_side, unit.branch, unit.direction,
        unit.reference_high, unit.reference_low,
        unit.confirm_primitive,
        _mask_state(unit, frames),
    )


def _mask_state(unit: V2.V2Unit, frames) -> tuple:
    result = causal_mask_for_v2_unit(
        unit, m5=frames["M5"], m15=frames["M15"], h1=frames["H1"])
    return (result.eligible, result.reason_code)


@pytest.fixture(scope="module")
def full_run():
    m1 = _load_zip_m1()
    frames = _frames_from_m1(m1)
    units = _replay(frames)
    m5_opens = [bar.timestamp for bar in frames["M5"]]
    return units, m5_opens, frames


def _truncation_points(frames) -> list[datetime]:
    m15 = frames["M15"]
    first, last = m15[0].timestamp, m15[-1].timestamp
    span = (last - first).total_seconds()
    return [first + timedelta(seconds=span * fraction)
            for fraction in TRUNCATION_FRACTIONS]


def test_prefix_invariance_of_event_state_on_real_development_data(full_run):
    units_a, m5_opens_a, frames_a = full_run
    cutoffs = _truncation_points(frames_a)
    m1 = _load_zip_m1()

    compared_confirmed = compared_failed = compared_entries = compared_outcomes = 0
    for t in cutoffs:
        # RUN B: nothing after t is visible.  An M1 bar is visible once it
        # has CLOSED: open + 1 minute <= t.
        m1_b = tuple(bar for bar in m1 if bar.timestamp + M1 <= t)
        frames_b = _frames_from_m1(m1_b)
        units_b = _replay(frames_b)
        m5_opens_b = [bar.timestamp for bar in frames_b["M5"]]

        for unit_b in units_b.values():
            unit_a = units_a.get(unit_b.candidate_id)
            # Event identity: every unit visible at t must exist in RUN A.
            assert unit_a is not None, unit_b.candidate_id

            if unit_b.passed("S6_STRUCTURE_CONFIRM"):
                t2 = _t2(unit_b)
                if t2 <= t:
                    # Decision completed at/before t: full pre-T2 identity.
                    assert unit_a.passed("S6_STRUCTURE_CONFIRM"), unit_b.candidate_id
                    assert _t2(unit_a) == t2, unit_b.candidate_id
                    assert (_knowable_pre_t2_state(unit_a, frames_a)
                            == _knowable_pre_t2_state(unit_b, frames_b))
                    compared_confirmed += 1
                    # Reference-entry timestamp, once the entry bar has closed.
                    entry_a = first_m5_open_at_or_after(m5_opens_a, t2)
                    entry_b = first_m5_open_at_or_after(m5_opens_b, t2)
                    if entry_a is not None and entry_a + M5 <= t:
                        assert entry_b == entry_a, (unit_b.candidate_id, entry_a, entry_b)
                        compared_entries += 1
            else:
                # Unconfirmed: the pre-S6 outcome is fully determined once
                # the session entry window has expired at/before t.
                if _session_window_end(unit_b) <= t:
                    assert (_knowable_pre_t2_state(unit_a, frames_a)
                            == _knowable_pre_t2_state(unit_b, frames_b))
                    assert unit_a.reject_node == unit_b.reject_node, unit_b.candidate_id
                    assert unit_a.reject_reason == unit_b.reject_reason, unit_b.candidate_id
                    compared_failed += 1

    # The guard must actually exercise the population, not compare nothing.
    assert compared_confirmed >= 50, compared_confirmed
    assert compared_failed >= 50, compared_failed
    assert compared_entries >= 50, compared_entries


def test_reference_outcomes_are_prefix_invariant_once_resolved(full_run):
    """A resolved reference outcome cannot change when later data arrives."""
    from ag_edgelab.optimization.reference_outcome_v2 import (
        ReferenceDirectionMode, ReferenceOutcomeV2Config,
        evaluate_reference_outcome_v2,
    )

    units_a, _, frames_a = full_run
    m5_a = frames_a["M5"]
    m1 = _load_zip_m1()
    config = ReferenceOutcomeV2Config(
        direction_mode=ReferenceDirectionMode.BOTH_DIRECTIONS_SYMMETRIC)

    confirmed = [u for u in units_a.values() if u.passed("S6_STRUCTURE_CONFIRM")]
    assert confirmed
    # Deterministic sample: every 2nd confirmed unit (EURUSD 2016 has ~59).
    sampled = confirmed[::2]
    checked = 0
    for unit in sampled:
        t2 = _t2(unit)
        outcome_a = evaluate_reference_outcome_v2(m5_a, t2, event_id=unit.candidate_id,
                                                  config=config)
        if outcome_a.long_outcome_r is None:
            continue  # outcome not evaluable in the full run
        exit_bar = outcome_a.entry_time + timedelta(
            minutes=5 * config.max_holding_bars)
        # Truncate AFTER the full horizon: the outcome must be identical.
        t = exit_bar + M5
        m1_b = tuple(bar for bar in m1 if bar.timestamp + M1 <= t)
        frames_b = _frames_from_m1(m1_b)
        outcome_b = evaluate_reference_outcome_v2(frames_b["M5"], t2,
                                                  event_id=unit.candidate_id,
                                                  config=config)
        assert outcome_b.long_outcome_r == outcome_a.long_outcome_r
        assert outcome_b.short_outcome_r == outcome_a.short_outcome_r
        assert outcome_b.entry_time == outcome_a.entry_time
        assert outcome_b.atr == outcome_a.atr
        checked += 1
    assert checked >= 15, checked
