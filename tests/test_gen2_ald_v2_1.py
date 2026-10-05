"""MISSION 3A PHASE 11 — hardened V2 contract tests.

Synthetic fixtures only. No market data is read, no replay is performed.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import canonical_json
from ag_edgelab.strategies import asian_liquidity_displacement_v2_1 as V
from ag_edgelab.strategies import symbol_metadata as SM

UTC = timezone.utc
T0 = datetime(2016, 3, 1, 7, 0, tzinfo=UTC)


def bar(i: int, o: float, h: float, lo: float, c: float) -> MarketBar:
    return MarketBar(timestamp=T0 + timedelta(minutes=5 * i),
                     open=o, high=h, low=lo, close=c, volume=1.0)


def never(_i: int) -> bool:
    return False


def at(idx: int):
    return lambda i: i == idx


# ===========================================================================
# PHASE 2 — canonical contract identity
# ===========================================================================

def test_serialization_is_deterministic_across_calls():
    assert canonical_json(V.strategy_contract()) == canonical_json(V.strategy_contract())
    assert V.contract_hash() == V.contract_hash() == V.CONTRACT_HASH


def test_serialization_is_insensitive_to_dict_insertion_order():
    c1 = V.strategy_contract()
    c2 = {k: c1[k] for k in reversed(list(c1))}
    assert canonical_json(c1) == canonical_json(c2)


def test_contract_is_json_serialisable_and_has_no_nan():
    json.loads(canonical_json(V.strategy_contract()))


#: (module, attribute, mutated value) for every frozen field.
MUTATIONS = [
    (V, "STRATEGY_ID", "ST_SOMETHING_ELSE"),
    (V, "STRATEGY_VERSION", "9.9.9"),
    (V, "LOOK_INDEX", 1),
    (V, "REFERENCE_WINDOW_UTC", (0, 7)),
    (V, "LONDON_ENTRY_UTC", (7, 11)),
    (V, "NEW_YORK_ENTRY_UTC", (12, 16)),
    (V, "MIN_REFERENCE_M15_BARS", 15),
    (V, "WARMUP_DAYS", 22),
    (V, "OUTCOME_HORIZON_M5_BARS", 289),
    (V, "SWING_ORDER", 3),
    (V, "MIN_SWEEP_TICKS", 2),
    (V, "MAX_SWEEP_RANGE_FRACTION", 0.9),
    (V, "RECLAIM_MAX_BARS", 13),
    (V, "MSS_LOOKBACK_BARS", 13),
    (V, "ACCEPTANCE_CLOSE_COUNT", 3),
    (V, "RETEST_MAX_BARS", 13),
    (V, "RETEST_TOLERANCE", 0.0001),
    (V, "MIN_NATURAL_R", 1.5),
    (V, "HANDOVER_MAX", 2),
    (V, "TARGET_AUTHORITY_ORDER", ("PRIOR_DAY_HIGH_LOW",)),
    (V, "FUNNEL_TAXONOMY_VERSION", "SOMETHING_V3"),
    (V, "FUNNEL_STAGES", ("OPPORTUNITY",)),
    (V, "STATE_MACHINE_A", (("BOUNDARY_UNTOUCHED", "ENTRY_AVAILABLE"),)),
    (V, "STATE_MACHINE_B", (("BOUNDARY_UNTOUCHED", "ENTRY_AVAILABLE"),)),
    (V, "PERMITTED_HANDOVERS", (("A", "B", "ANYTHING"),)),
    (V, "FRICTION_TYPE", "ASSUMED"),
    (V, "ECONOMIC_EDGE", "POSITIVE"),
    (V, "STOP_POLICY", "stop with a buffer"),
    (V, "ENTRY_POLICY", "limit order at the midpoint"),
    (V, "EXPIRY_POLICY", "never expires"),
]


@pytest.mark.parametrize("mod,attr,new", MUTATIONS, ids=[m[1] for m in MUTATIONS])
def test_mutating_any_frozen_field_changes_the_contract_hash(monkeypatch, mod, attr, new):
    before = V.contract_hash()
    assert getattr(mod, attr) != new, f"{attr} mutation is not actually a change"
    monkeypatch.setattr(mod, attr, new)
    assert V.contract_hash() != before, f"{attr} is NOT bound into the contract hash"


def test_mutating_symbol_metadata_changes_the_contract_hash(monkeypatch):
    before = V.contract_hash()
    mutated = dict(SM.SYMBOL_METADATA)
    mutated["USDJPY"] = SM.SymbolMetadata(
        symbol="USDJPY", price_unit="JPY_PER_USD", digits=5,
        tick_size=0.00001, point=0.00001, pip_size=0.0001,
        pip_convention_note="wrong on purpose")
    monkeypatch.setattr(SM, "SYMBOL_METADATA", mutated)
    assert V.contract_hash() != before


def test_every_declared_frozen_field_exists():
    for name in V.FROZEN_FIELDS:
        assert hasattr(V, name) or hasattr(SM, name), f"{name} declared frozen but absent"


def test_every_mutable_rule_magnitude_is_covered_by_a_mutation_test():
    covered = {attr for _, attr, _ in MUTATIONS} | {"SYMBOL_METADATA"}
    missing = set(V.parameter_contract()["values"]) - covered
    assert not missing, f"rule magnitudes with no mutation test: {sorted(missing)}"


def test_every_parameter_has_a_provenance_entry():
    values = set(V.parameter_contract()["values"])
    provenance = set(V.parameter_contract()["provenance"])
    assert values == provenance


def test_contract_declares_no_optimization():
    p = V.parameter_contract()
    assert p["optimization_performed"] is False
    assert p["selected_by_observing_outcome"] is False


# ===========================================================================
# PHASE 3 — symbol normalization
# ===========================================================================

@pytest.mark.parametrize("symbol,tick,pip,digits", [
    ("EURUSD", 0.00001, 0.0001, 5),
    ("GBPUSD", 0.00001, 0.0001, 5),
    ("USDJPY", 0.001, 0.01, 3),
    ("XAUUSD", 0.01, 0.1, 2),
])
def test_symbol_normalization(symbol, tick, pip, digits):
    m = SM.metadata_for(symbol)
    assert (m.tick_size, m.pip_size, m.digits) == (tick, pip, digits)
    assert m.at_least_one_tick(tick)
    assert not m.at_least_one_tick(tick / 10.0)
    assert m.ticks(tick * 7) == pytest.approx(7.0)


def test_universal_pip_constant_is_wrong_for_jpy_and_gold():
    """The exact bug this module exists to kill."""
    universal = 0.0001
    assert SM.metadata_for("USDJPY").pip_size != universal
    assert SM.metadata_for("XAUUSD").pip_size != universal
    assert round(SM.metadata_for("XAUUSD").tick_size
                 / SM.metadata_for("EURUSD").tick_size) == 1000


def test_unknown_symbol_fails_closed_instead_of_defaulting():
    with pytest.raises(SM.UnknownSymbolError):
        SM.metadata_for("BTCUSD")


def test_pip_size_is_forbidden_to_rules():
    assert "pip_size" in SM.RULE_FORBIDDEN_FIELDS
    assert "pip_size" not in SM.RULE_ADMISSIBLE_FIELDS
    source = Path(V.__file__).read_text()
    assert "pip_size" not in source, "a rule module must never consume pip_size"


def test_strategy_module_contains_no_universal_price_constants():
    source = Path(V.__file__).read_text()
    for literal in ("0.0001", "0.0005", "0.00001 *", "0.01 *"):
        assert literal not in source, f"hard-coded price constant {literal!r} in rules"


def test_observed_precision_validation_detects_a_wrong_declaration():
    ok = SM.validate_observed_precision("USDJPY", [101.234, 99.001, 120.500])
    assert ok["consistent"] and ok["violations"] == 0
    bad = SM.validate_observed_precision("USDJPY", [101.23456])
    assert not bad["consistent"]


def test_sweep_floor_scales_with_the_instrument():
    """One tick of gold is 1000x one tick of EURUSD in absolute price."""
    eur, xau = SM.metadata_for("EURUSD"), SM.metadata_for("XAUUSD")
    depth = 0.001
    assert eur.ticks(depth) == pytest.approx(100.0)
    assert xau.ticks(depth) == pytest.approx(0.1)
    assert eur.at_least_one_tick(depth)
    assert not xau.at_least_one_tick(depth)


# ===========================================================================
# PHASE 4 — branch A state machine
# ===========================================================================

JPY = SM.metadata_for("USDJPY")
BOUND_HI, BOUND_LO, REF_RANGE = 101.0, 100.0, 1.0


def branch_a_bars():
    """Sweep at 0, reclaim at 2, MSS available from 4. Distinct bars."""
    return [
        bar(0, 100.9, 101.5, 100.8, 101.2),   # sweep high, closes beyond
        bar(1, 101.2, 101.3, 101.0, 101.1),   # still beyond
        bar(2, 101.1, 101.15, 100.7, 100.8),  # CLOSES back inside -> reclaim
        bar(3, 100.8, 100.9, 100.6, 100.7),
        bar(4, 100.7, 100.75, 100.4, 100.45),  # MSS bar
        bar(5, 100.45, 100.5, 100.2, 100.3),
    ]


def run_a(bars, mss, **kw):
    return V.run_branch_a(bars, boundary=BOUND_HI, boundary_side="HIGH",
                          reference_range=REF_RANGE, meta=JPY,
                          mss_confirmed_at=mss, **kw)


def test_branch_a_full_sequence_uses_three_distinct_increasing_bars():
    r = run_a(branch_a_bars(), at(4))
    assert r.state == V.StateA.ENTRY_AVAILABLE.value
    assert r.indices == {"sweep_index": 0, "reclaim_index": 2, "mss_index": 4}
    assert r.indices["sweep_index"] < r.indices["reclaim_index"] < r.indices["mss_index"]
    assert r.entry_price == 100.45
    assert r.stop_price == 101.5            # sweep extreme, no buffer
    assert r.timestamps["entry_timestamp"] == T0 + timedelta(minutes=5 * 4 + 5)


def test_branch_a_records_every_transition_timestamp():
    r = run_a(branch_a_bars(), at(4))
    for key in ("sweep_timestamp", "reclaim_timestamp", "mss_timestamp", "entry_timestamp"):
        assert key in r.timestamps
    assert (r.timestamps["sweep_timestamp"] < r.timestamps["reclaim_timestamp"]
            < r.timestamps["mss_timestamp"] < r.timestamps["entry_timestamp"])


def test_branch_a_sweep_candle_can_never_be_the_reclaim_candle():
    """Bar 0 both sweeps and closes inside; it must NOT self-reclaim."""
    bars = [bar(0, 100.9, 101.5, 100.5, 100.6)] + branch_a_bars()[1:]
    r = run_a(bars, at(4))
    assert r.indices["sweep_index"] == 0
    assert r.indices.get("reclaim_index", 0) > 0


def test_branch_a_reclaim_candle_can_never_be_the_mss_candle():
    """MSS true exactly on the reclaim bar must not satisfy the MSS step."""
    r = run_a(branch_a_bars(), at(2))
    assert r.state == V.StateA.INVALIDATED.value
    assert r.invalidation_reason == "MSS_TIMEOUT"


def test_branch_a_reclaim_timeout():
    bars = [bar(0, 100.9, 101.5, 100.8, 101.2)]
    bars += [bar(i, 101.2, 101.3, 101.1, 101.25)
             for i in range(1, V.RECLAIM_MAX_BARS + 4)]  # never closes inside
    r = run_a(bars, at(99))
    assert r.state == V.StateA.INVALIDATED.value
    assert r.invalidation_reason == "RECLAIM_TIMEOUT"


def test_branch_a_mss_timeout():
    bars = branch_a_bars() + [bar(i, 100.3, 100.35, 100.2, 100.25)
                              for i in range(6, 6 + V.MSS_LOOKBACK_BARS + 2)]
    r = run_a(bars, never)
    assert r.state == V.StateA.INVALIDATED.value
    assert r.invalidation_reason == "MSS_TIMEOUT"


def test_branch_a_rejects_a_sweep_deeper_than_the_reference_range():
    bars = [bar(0, 100.9, 102.5, 100.8, 102.2)] + branch_a_bars()[1:]
    r = run_a(bars, at(4))
    assert r.invalidation_reason == "SWEEP_GEOMETRY_EXCEEDED"


def test_branch_a_ignores_a_sub_tick_boundary_graze():
    graze = BOUND_HI + JPY.tick_size / 10.0
    bars = [bar(0, 100.9, graze, 100.8, 100.95)] + branch_a_bars()[1:]
    r = run_a(bars, at(4))
    assert r.indices["sweep_index"] == 1 or r.state == V.StateA.INVALIDATED.value


def test_branch_a_stop_tracks_the_deepest_excursion_not_just_the_sweep_bar():
    bars = branch_a_bars()
    bars[1] = bar(1, 101.2, 101.8, 101.0, 101.1)   # deeper after the sweep bar
    r = run_a(bars, at(4))
    assert r.stop_price == 101.8


def test_branch_a_has_no_future_leakage_prefix_invariance():
    """Transitions decided at bar k must not change when later bars vanish."""
    full = run_a(branch_a_bars(), at(4))
    prefix = run_a(branch_a_bars()[:3], at(4))
    assert prefix.indices["sweep_index"] == full.indices["sweep_index"]
    assert prefix.indices["reclaim_index"] == full.indices["reclaim_index"]
    assert "mss_index" not in prefix.indices       # not yet knowable


def test_branch_a_never_queries_structure_beyond_the_confirming_bar():
    seen: list[int] = []

    def recorder(i: int) -> bool:
        seen.append(i)
        return i == 4

    r = run_a(branch_a_bars(), recorder)
    assert max(seen) == r.indices["mss_index"]
    assert min(seen) > r.indices["reclaim_index"]


# ===========================================================================
# PHASE 5 — branch B state machine
# ===========================================================================

def branch_b_bars():
    """Breakout 0, acceptance completes 1, retest 3, continuation 4."""
    return [
        bar(0, 100.9, 101.3, 100.85, 101.2),   # breakout + 1st close beyond
        bar(1, 101.2, 101.4, 101.1, 101.35),   # 2nd close beyond -> accepted
        bar(2, 101.35, 101.5, 101.2, 101.4),
        bar(3, 101.4, 101.45, 100.95, 101.1),  # touches 101.0, closes beyond
        bar(4, 101.1, 101.6, 101.05, 101.55),  # continuation
        bar(5, 101.55, 101.7, 101.4, 101.6),
    ]


def run_b(bars, cont, **kw):
    return V.run_branch_b(bars, boundary=BOUND_HI, boundary_side="HIGH",
                          reference_range=REF_RANGE, meta=JPY,
                          continuation_confirmed_at=cont, **kw)


def test_branch_b_full_sequence_acceptance_precedes_retest():
    r = run_b(branch_b_bars(), at(4))
    assert r.state == V.StateB.ENTRY_AVAILABLE.value
    assert r.indices["breakout_index"] == 0
    assert r.indices["acceptance_index"] == 1
    assert r.indices["retest_index"] == 3
    assert r.indices["continuation_index"] == 4
    assert (r.indices["acceptance_index"] < r.indices["retest_index"]
            < r.indices["continuation_index"])
    assert r.entry_price == 101.55
    assert r.stop_price == 100.95          # retest extreme, no buffer


def test_branch_b_records_every_transition_timestamp():
    r = run_b(branch_b_bars(), at(4))
    for key in ("breakout_timestamp", "acceptance_timestamp", "retest_timestamp",
                "continuation_timestamp", "entry_timestamp"):
        assert key in r.timestamps


def test_branch_b_requires_the_preregistered_number_of_acceptance_closes():
    assert V.ACCEPTANCE_CLOSE_COUNT == 2
    bars = branch_b_bars()
    bars[1] = bar(1, 101.2, 101.4, 100.8, 100.9)   # closes back inside
    r = run_b(bars, at(4))
    assert r.indices.get("acceptance_index") != 1


def test_branch_b_retest_must_be_strictly_after_acceptance():
    """A bar that both completes acceptance and touches cannot be the retest."""
    bars = branch_b_bars()
    bars[1] = bar(1, 101.2, 101.4, 100.95, 101.35)  # accepts AND touches
    r = run_b(bars, at(4))
    assert r.indices["acceptance_index"] == 1
    assert r.indices["retest_index"] > 1


def test_branch_b_retest_timeout():
    bars = branch_b_bars()[:2]
    bars += [bar(i, 101.4, 101.5, 101.3, 101.45)
             for i in range(2, 2 + V.RETEST_MAX_BARS + 2)]   # never returns
    r = run_b(bars, at(99))
    assert r.state == V.StateB.INVALIDATED.value
    assert r.invalidation_reason == "RETEST_TIMEOUT"


def test_branch_b_confirmation_failure():
    bars = branch_b_bars() + [bar(i, 101.1, 101.2, 101.05, 101.15)
                              for i in range(6, 6 + V.MSS_LOOKBACK_BARS + 2)]
    r = run_b(bars, never)
    assert r.state == V.StateB.INVALIDATED.value
    assert r.invalidation_reason == "CONTINUATION_TIMEOUT"


def test_branch_b_close_back_inside_invalidates_the_breakout():
    bars = branch_b_bars()
    bars[2] = bar(2, 101.35, 101.5, 100.5, 100.6)   # closes back inside
    r = run_b(bars, at(4))
    assert r.state == V.StateB.INVALIDATED.value
    assert r.invalidation_reason == "BREAKOUT_REJECTED_CLOSE_BACK_INSIDE"


def test_branch_b_retest_has_no_tolerance_parameter():
    assert V.RETEST_TOLERANCE == 0.0
    bars = branch_b_bars()
    bars[3] = bar(3, 101.4, 101.45, 101.0 + JPY.tick_size, 101.1)  # 1 tick short
    r = run_b(bars, at(4))
    assert r.indices.get("retest_index") != 3


def test_branch_b_has_no_future_leakage_prefix_invariance():
    full = run_b(branch_b_bars(), at(4))
    prefix = run_b(branch_b_bars()[:4], at(4))
    for key in ("breakout_index", "acceptance_index", "retest_index"):
        assert prefix.indices[key] == full.indices[key]
    assert "continuation_index" not in prefix.indices


def test_branch_b_never_queries_structure_beyond_the_confirming_bar():
    seen: list[int] = []

    def recorder(i: int) -> bool:
        seen.append(i)
        return i == 4

    r = run_b(branch_b_bars(), recorder)
    assert max(seen) == r.indices["continuation_index"]
    assert min(seen) > r.indices["retest_index"]


def test_strict_order_assertion_actually_fires():
    res = V.MachineResult(branch="X", state="S")
    res.indices = {"sweep_index": 4, "reclaim_index": 4}
    with pytest.raises(AssertionError):
        V._assert_strict_order(res, V.STRICT_ORDER_A)


# ===========================================================================
# PHASE 6 — natural target authority
# ===========================================================================

ENTRY_T = T0 + timedelta(minutes=30)


def cand(authority: str, level: float, offset_min: int = -5) -> V.TargetCandidate:
    return V.TargetCandidate(authority=authority, level=level,
                             known_at=ENTRY_T + timedelta(minutes=offset_min))


def resolve(cands, entry=100.0, stop=99.0, bull=True):
    return V.resolve_natural_target(cands, entry_price=entry, stop_price=stop,
                                    entry_timestamp=ENTRY_T, direction_is_bull=bull)


def test_natural_target_available_before_entry_resolves():
    out = resolve([cand("OPPOSITE_SESSION_BOUNDARY", 102.0)])
    assert out["status"] == "RESOLVED"
    assert out["authority"] == "OPPOSITE_SESSION_BOUNDARY"
    assert out["natural_r"] == pytest.approx(2.0)


def test_future_target_is_forbidden():
    with pytest.raises(ValueError, match="future leakage"):
        resolve([cand("OPPOSITE_SESSION_BOUNDARY", 102.0, offset_min=+5)])


def test_target_known_exactly_at_entry_is_allowed():
    out = resolve([cand("OPPOSITE_SESSION_BOUNDARY", 102.0, offset_min=0)])
    assert out["status"] == "RESOLVED"


def test_priority_order_wins_over_a_bigger_target():
    """First admissible authority is taken even though a later one is richer."""
    out = resolve([
        cand("CONFIRMED_PRE_ENTRY_SWING_LIQUIDITY", 110.0),
        cand("OPPOSITE_SESSION_BOUNDARY", 102.0),
    ])
    assert out["authority"] == "OPPOSITE_SESSION_BOUNDARY"
    assert out["target"] == 102.0


def test_authority_behind_the_entry_is_skipped_to_the_next():
    out = resolve([
        cand("OPPOSITE_SESSION_BOUNDARY", 99.5),      # behind a bull entry
        cand("PRIOR_DAY_HIGH_LOW", 103.0),
    ])
    assert out["authority"] == "PRIOR_DAY_HIGH_LOW"


def test_no_authority_yields_no_natural_target_and_invalid_geometry():
    out = resolve([cand("OPPOSITE_SESSION_BOUNDARY", 99.5)])
    assert out["status"] == "NO_NATURAL_TARGET"
    assert out["target"] is None and out["natural_r"] is None


def test_target_below_the_r_floor_fails_geometry_rather_than_being_replaced():
    out = resolve([cand("OPPOSITE_SESSION_BOUNDARY", 100.5)])   # 0.5R
    assert out["status"] == "NATURAL_R_BELOW_FLOOR"
    assert out["natural_r"] == pytest.approx(0.5)
    assert out["authority"] == "OPPOSITE_SESSION_BOUNDARY"      # not shopped on


def test_r_floor_is_not_a_selection_criterion():
    """A sub-floor first authority must NOT be bypassed for a richer one."""
    out = resolve([
        cand("OPPOSITE_SESSION_BOUNDARY", 100.5),    # 0.5R, first in order
        cand("PRIOR_DAY_HIGH_LOW", 105.0),           # 5R, would be tempting
    ])
    assert out["status"] == "NATURAL_R_BELOW_FLOOR"
    assert out["target"] == 100.5


def test_bear_direction_mirrors():
    out = resolve([cand("OPPOSITE_SESSION_BOUNDARY", 98.0)],
                  entry=100.0, stop=101.0, bull=False)
    assert out["status"] == "RESOLVED" and out["natural_r"] == pytest.approx(2.0)


def test_non_positive_risk_is_refused():
    out = resolve([cand("OPPOSITE_SESSION_BOUNDARY", 102.0)], entry=100.0, stop=100.0)
    assert out["status"] == "NO_NATURAL_TARGET"
    assert out["reason"] == "GEOMETRY_RISK_NON_POSITIVE"


def test_artificial_fixed_2r_target_is_absent_from_the_contract():
    source = Path(V.__file__).read_text()
    for pattern in ("2 * risk", "2.0 * risk", "risk * 2", "entry + 2", "entry - 2"):
        assert pattern not in source, f"synthetic target arithmetic {pattern!r} present"
    assert "entry +/- 2R" in V.SYNTHETIC_TARGETS_FORBIDDEN
    assert V.target_contract()["fixed_r_targets_are_diagnostic_only"] == [1, 2, 3, 4, 5]


def test_fixed_r_multiples_have_no_target_authority():
    assert "OPPOSITE_SESSION_BOUNDARY" in V.TARGET_AUTHORITY_ORDER
    for authority in V.TARGET_AUTHORITY_ORDER:
        assert "R" != authority and not authority.endswith("R_MULTIPLE")


# ===========================================================================
# PHASE 7 — duplicate event governance
# ===========================================================================

def test_event_id_is_stable_and_discriminating():
    a = V.event_id("EURUSD", "2016-03-01", "ASIAN_LONDON", "HIGH", 0)
    assert a == V.event_id("EURUSD", "2016-03-01", "ASIAN_LONDON", "HIGH", 0)
    assert a != V.event_id("EURUSD", "2016-03-01", "ASIAN_LONDON", "LOW", 0)
    assert a != V.event_id("EURUSD", "2016-03-01", "LONDON_NEWYORK", "HIGH", 0)
    assert a != V.event_id("GBPUSD", "2016-03-01", "ASIAN_LONDON", "HIGH", 0)
    assert a != V.event_id("EURUSD", "2016-03-02", "ASIAN_LONDON", "HIGH", 0)
    assert a != V.event_id("EURUSD", "2016-03-01", "ASIAN_LONDON", "HIGH", 1)


def test_first_valid_signal_locks_the_tuple_and_suppresses_duplicates():
    reg = V.EventRegistry()
    e0 = reg.open_event("EURUSD", "2016-03-01", "ASIAN_LONDON", "HIGH", 0)
    assert reg.accept_signal(e0, V.Branch.A.value) is True
    assert reg.is_locked(e0)
    e1 = reg.open_event("EURUSD", "2016-03-01", "ASIAN_LONDON", "HIGH", 1)
    assert reg.accept_signal(e1, V.Branch.B.value) is False
    assert e1.duplicate_suppressed == 1
    assert reg.accepted_n == 1 and reg.suppressed_n == 1


def test_lock_is_scoped_to_symbol_date_session_boundary():
    reg = V.EventRegistry()
    held = reg.open_event("EURUSD", "2016-03-01", "ASIAN_LONDON", "HIGH", 0)
    reg.accept_signal(held, V.Branch.A.value)
    other = reg.open_event("EURUSD", "2016-03-01", "ASIAN_LONDON", "LOW", 0)
    assert reg.accept_signal(other, V.Branch.A.value) is True


def test_lock_releases_at_expiry():
    reg = V.EventRegistry()
    e = reg.open_event("EURUSD", "2016-03-01", "ASIAN_LONDON", "HIGH", 0)
    reg.accept_signal(e, V.Branch.A.value)
    reg.release(e)
    assert not reg.is_locked(e)


def test_only_preregistered_handovers_are_permitted():
    reg = V.EventRegistry()
    e = reg.open_event("EURUSD", "2016-03-01", "ASIAN_LONDON", "HIGH", 0)
    reg.record_handover(e, V.Branch.A.value, V.Branch.B.value, "RECLAIM_TIMEOUT")
    assert len(e.handovers) == 1
    with pytest.raises(AssertionError):
        reg.record_handover(e, V.Branch.A.value, V.Branch.B.value, "MSS_TIMEOUT")


def test_handover_budget_is_enforced():
    reg = V.EventRegistry()
    e = reg.open_event("EURUSD", "2016-03-01", "ASIAN_LONDON", "HIGH", 0)
    reg.record_handover(e, V.Branch.A.value, V.Branch.B.value, "RECLAIM_TIMEOUT")
    assert V.HANDOVER_MAX == 1
    with pytest.raises(AssertionError):
        reg.record_handover(e, V.Branch.B.value, V.Branch.A.value,
                            "BREAKOUT_REJECTED_CLOSE_BACK_INSIDE")


def test_event_row_reports_every_mandated_field():
    reg = V.EventRegistry()
    e = reg.open_event("EURUSD", "2016-03-01", "ASIAN_LONDON", "HIGH", 0)
    reg.note_detection(e, V.Branch.A.value)
    reg.note_invalidation(e, V.Branch.A.value, "RECLAIM_TIMEOUT")
    reg.record_handover(e, V.Branch.A.value, V.Branch.B.value, "RECLAIM_TIMEOUT")
    reg.accept_signal(e, V.Branch.B.value)
    row = e.as_row()
    for key in ("EVENT_ID", "BRANCH_FIRST_DETECTED", "BRANCH_SELECTED",
                "BRANCH_INVALIDATION_REASON", "DUPLICATE_SUPPRESSED"):
        assert key in row
    assert row["BRANCH_FIRST_DETECTED"] == V.Branch.A.value
    assert row["BRANCH_SELECTED"] == V.Branch.B.value


# ===========================================================================
# PHASE 8 — friction authority boundary
# ===========================================================================

def test_scenario_friction_cannot_verify_edge():
    assert V.can_scenario_friction_verify_edge() is False
    assert V.friction_contract()["scenario_friction_can_verify_edge"] is False


def test_unknown_friction_is_not_zero():
    claim = V.economic_claim()
    for key in ("spread", "slippage", "commission", "swap"):
        assert claim[key] == "UNKNOWN"
        assert claim[key] != 0
    assert claim["ECONOMIC_EDGE"] == "NOT_ESTIMABLE"
    assert claim["EDGE_VERIFIED"] is False


def test_no_substitute_friction_default_appears_in_the_contract():
    blob = canonical_json(V.strategy_contract())
    for forbidden in ("$7", "7/lot", "0.8 pip", "1.2 pip", "industry default"):
        assert forbidden not in blob


def test_edge_verified_is_false_at_module_level():
    assert V.EDGE_VERIFIED is False
    assert V.STRATEGY_STATUS == "RESEARCH_CANDIDATE"


# ===========================================================================
# PHASE 9 — funnel contract
# ===========================================================================

def test_funnel_stages_preserved_exactly():
    assert V.FUNNEL_STAGES == (
        "OPPORTUNITY", "CONTEXT_ELIGIBLE", "LOCATION_ELIGIBLE", "SESSION_EVENT",
        "SWEEP_OR_BREAKOUT", "RECLAIM_OR_RETEST", "STRUCTURE_CONFIRM",
        "ENTRY_AVAILABLE", "GEOMETRY_VALID", "TRADE_COMPLETED")


def test_funnel_reports_three_axes_and_three_metrics():
    f = V.funnel_contract()
    assert f["report_axes"] == ["BRANCH_A", "BRANCH_B", "POOLED"]
    assert f["per_transition_metrics"] == ["N", "PCT_OF_PREVIOUS_STAGE",
                                           "PCT_OF_OPPORTUNITIES"]


# ===========================================================================
# PHASE 1 — exactly two branches
# ===========================================================================

def test_exactly_two_branches_exist():
    assert [b.value for b in V.Branch] == [
        "A_SWEEP_RECLAIM_REVERSAL", "B_BREAKOUT_RETEST_CONTINUATION"]


def test_research_question_is_frozen_in_the_contract():
    assert "structural starvation" in V.RESEARCH_QUESTION
    assert V.identity_contract()["research_question"] == V.RESEARCH_QUESTION


def test_identity_is_not_a_forbidden_reuse():
    assert V.STRATEGY_ID not in V.FORBIDDEN_IDENTITY_REUSE


def test_supersession_of_the_prototype_is_declared():
    assert V.SUPERSEDES.endswith("2.0.0-research")
    assert V.SUPERSEDED_EVIDENCE == "GEN2_ALD_V2_DEV_R1"


def test_second_look_is_disclosed():
    """The contamination hazard must be declared, not buried."""
    assert V.LOOK_INDEX == 2
    assert V.identity_contract()["look_index"] == 2
    assert "CONTAMINATION DISCLOSURE" in (V.__doc__ or "")


# ===========================================================================
# Governance firewalls
# ===========================================================================

GOV = Path("config/governance")


def test_oos_firewall_unchanged():
    log = json.loads((GOV / "oos_access_log.json").read_text())
    blob = json.dumps(log)
    assert "GEN2_ALD_V2" not in blob, "a V2 candidate must not appear in the OOS log"


def test_holdout_firewall_unchanged():
    reg = json.loads((GOV / "candidate_contamination_registry.json").read_text())
    blob = json.dumps(reg)
    assert "SEALED_HOLDOUT_OPENED" not in blob


def test_v1_closed_evidence_is_not_modified_by_this_mission():
    out = subprocess.run(
        ["git", "status", "--porcelain",
         "src/ag_edgelab/strategies/asian_liquidity_displacement_v1.py",
         "src/ag_edgelab/strategies/asian_liquidity_displacement_prereg.py",
         "data/artifacts/gen2_asian_liquidity_displacement_v1_multiyear"],
        capture_output=True, text=True, check=False)
    assert out.stdout.strip() == "", f"V1 evidence touched:\n{out.stdout}"


def test_v2_prototype_evidence_is_not_rewritten():
    out = subprocess.run(
        ["git", "status", "--porcelain",
         "src/ag_edgelab/strategies/asian_liquidity_displacement_v2.py",
         "data/artifacts/gen2_asian_liquidity_displacement_v2"],
        capture_output=True, text=True, check=False)
    assert out.stdout.strip() == "", f"R1 evidence touched:\n{out.stdout}"


def test_no_v2_1_performance_artifact_exists_yet():
    """STOP POINT A: preregistration must precede any replay."""
    results = Path("data/artifacts/gen2_ald_v2_1")
    if results.exists():
        forbidden = {"final_report.json", "funnel_report.json", "v1_vs_v2.json",
                     "pre_oos_gate_result.json", "target_capability.json"}
        present = {p.name for p in results.iterdir()} & forbidden
        assert not present, f"performance results exist before replay: {present}"
