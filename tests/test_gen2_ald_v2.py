"""MISSION 3 — ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2.

Mechanics are proven on SYNTHETIC bars only. Nothing in this file reads the
DEVELOPMENT corpus, so the rules could be frozen and preregistered without
anyone having seen a single real V2 result.
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.strategies import asian_liquidity_displacement_v2 as V2
from ag_edgelab.strategies.asian_liquidity_displacement_v1 import (
    STRATEGY_HASH as V1_HASH,
)

UTC = timezone.utc
ART = Path("data/artifacts/gen2_asian_liquidity_displacement_v2")
DAY = datetime(2012, 3, 15, tzinfo=UTC)


# ---------------------------------------------------------------------------
# synthetic bar helpers
# ---------------------------------------------------------------------------

def bar(ts: datetime, o: float, h: float, l: float, c: float) -> MarketBar:
    return MarketBar(timestamp=ts, open=o, high=h, low=l, close=c, volume=1.0)


def tf(bars: list[MarketBar], timeframe: str) -> tuple[MarketBar, ...]:
    """MarketBar carries no timeframe field; the tuple itself is the frame."""
    return tuple(bars)


def _ramp(start: datetime, step: timedelta, prices: list[float],
          pad: float = 0.05) -> list[MarketBar]:
    """One bar per price, each bar's wick padded symmetrically."""
    out = []
    for i, p in enumerate(prices):
        prev = prices[i - 1] if i else p
        out.append(bar(start + i * step, prev, max(prev, p) + pad,
                       min(prev, p) - pad, p))
    return out


def _context_frames(anchor: datetime) -> dict[str, tuple[MarketBar, ...]]:
    """H1/H4/D1 history with real swings, ending before the trading day."""
    h1_prices, v = [], 100.0
    for i in range(24 * 40):
        v += (1.0 if (i // 6) % 2 == 0 else -1.0) * 0.5
        h1_prices.append(round(v, 4))
    h1 = _ramp(anchor - timedelta(hours=24 * 40), timedelta(hours=1), h1_prices, pad=0.15)
    h4 = _ramp(anchor - timedelta(hours=4 * 120), timedelta(hours=4),
               [round(100 + 0.4 * ((i // 5) % 2 * 2 - 1) * (i % 9), 4) for i in range(120)],
               pad=0.3)
    d1 = _ramp(anchor - timedelta(days=60), timedelta(days=1),
               [round(100 + ((i // 4) % 2 * 2 - 1) * (i % 7) * 0.5, 4) for i in range(60)],
               pad=0.6)
    return {"H1": tf(h1, "H1"), "H4": tf(h4, "H4"), "D1": tf(d1, "D1")}


def _reference_m15() -> list[MarketBar]:
    """24 M15 bars 00:00-06:00 UTC oscillating inside [100.0, 101.0]."""
    # the first bar defines the range extremes exactly: [100.0, 101.0]
    out = [bar(DAY, 100.5, 101.0, 100.0, 100.5)]
    prev = 100.5
    for i in range(1, 24):
        ts = DAY + timedelta(minutes=15 * i)
        close = 100.5 + (0.3 if i % 2 else -0.3)
        hi = min(101.0, max(prev, close) + 0.1)
        lo = max(100.0, min(prev, close) - 0.1)
        out.append(bar(ts, prev, hi, lo, close))
        prev = close
    return out


def _bearish_shift_m5(start: datetime, entry_close: float) -> list[MarketBar]:
    """M5 bars that build a confirmed swing low then close below it (BEAR BOS)."""
    # rise, pivot low at index 3, rise again, then break below the pivot low
    prices = [100.70, 100.80, 100.60, 100.40, 100.55, 100.75, 100.85, 100.65, entry_close]
    out = _ramp(start, timedelta(minutes=5), prices, pad=0.02)
    return out


def build_case(kind: str) -> tuple[dict[str, tuple[MarketBar, ...]], datetime, datetime]:
    """Assemble a full frame set containing exactly one engineered session."""
    frames = _context_frames(DAY)
    m15 = _reference_m15()
    w = DAY + timedelta(hours=7)          # London entry window 07:00-10:00

    if kind == "A":
        # interaction bar pierces 101.0 and closes back inside -> SWEEP (BEAR)
        m15.append(bar(w, 100.8, 101.50, 100.70, 100.90))
        m5 = _bearish_shift_m5(w + timedelta(minutes=15), 100.30)
        # forward bars drive price to the opposite boundary (100.0)
        m5 += _ramp(m5[-1].timestamp + timedelta(minutes=5), timedelta(minutes=5),
                    [100.20, 100.10, 99.95, 99.90], pad=0.02)
    elif kind == "B":
        # interaction bar CLOSES beyond 101.0 -> BREAKOUT (BULL)
        m15.append(bar(w, 100.9, 101.40, 100.85, 101.30))
        # retest bar: wicks to 100.95 (below the broken 101.0) but CLOSES above it
        m5 = [bar(w + timedelta(minutes=15), 101.20, 101.28, 100.95, 101.05)]
        m5 += _ramp(m5[-1].timestamp + timedelta(minutes=5), timedelta(minutes=5),
                    [101.10, 101.25, 101.45, 101.60, 101.80], pad=0.02)
        m5 += _ramp(m5[-1].timestamp + timedelta(minutes=5), timedelta(minutes=5),
                    [102.0, 102.4, 102.8, 103.2], pad=0.02)
    elif kind == "NO_EVENT":
        m15.append(bar(w, 100.5, 100.80, 100.30, 100.60))   # never leaves the range
        m5 = _ramp(w + timedelta(minutes=15), timedelta(minutes=5),
                   [100.5, 100.6, 100.4], pad=0.02)
    elif kind == "BOTH_SIDES":
        m15.append(bar(w, 100.5, 101.40, 99.60, 100.50))    # pierces both boundaries
        m5 = _ramp(w + timedelta(minutes=15), timedelta(minutes=5),
                   [100.5, 100.6], pad=0.02)
    else:  # pragma: no cover
        raise ValueError(kind)

    # pad the M5 series so the warm-up and window indices behave
    pre = _ramp(DAY, timedelta(minutes=5), [100.5] * 84, pad=0.05)
    frames["M15"] = tf(m15, "M15")
    frames["M5"] = tf(pre + m5, "M5")
    return frames, DAY, DAY + timedelta(days=1)


def _one_unit(kind: str, session: str = "ASIAN_LONDON") -> V2.V2Unit:
    frames, start, end = build_case(kind)
    unit = V2.V2Unit(symbol="TESTFX", day=DAY.date().isoformat(), session=session,
                     candidate_id="synthetic")
    from ag_edgelab.universal.confirmation import structure_shift_events
    shifts = structure_shift_events(frames["M5"], "M5", swing_order=V2.SWING_ORDER)
    by_index: dict[int, list] = {}
    for ev in shifts:
        by_index.setdefault(ev.index, []).append(ev)
    entry_from, entry_to = V2.SESSION_PAIRS[session]
    V2._evaluate_unit(unit, frames["M15"], frames["M5"], frames["H1"], frames["H4"],
                      frames["D1"], by_index, DAY, entry_from, entry_to)
    return unit


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

def test_v2_identity_is_new_and_never_reuses_a_historical_candidate():
    assert V2.STRATEGY_ID == "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2"
    assert V2.STRATEGY_VERSION == "2.0.0-research"
    assert V2.EDGE_VERIFIED is False
    assert V2.STRATEGY_ID not in V2.FORBIDDEN_IDENTITY_REUSE
    for forbidden in ("ST_ASIAN_SWEEP_5R_V1", "SESSION_TRADE_V2", "TARGET_POLICY_C3_V1",
                      "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1"):
        assert forbidden in V2.FORBIDDEN_IDENTITY_REUSE


def test_v2_hash_is_distinct_from_v1_and_deterministic():
    assert V2.STRATEGY_HASH != V1_HASH
    assert V2.STRATEGY_HASH == V2.contract_hashes()["strategy_contract_hash"]
    assert V2.STRATEGY_HASH == __import__(
        "ag_edgelab.data.fingerprint", fromlist=["sha256_json"]
    ).sha256_json(V2.strategy_contract())


def test_v2_does_not_import_or_mutate_v1():
    tree = ast.parse(Path(V2.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "asian_liquidity_displacement_v1" not in (node.module or ""), \
                "V2 must not import V1 — V1 is closed evidence"


def test_v2_carries_no_free_parameter_and_no_v1_tuning():
    contract = V2.parameter_contract()
    assert contract["free_parameters_n"] == 0
    assert V2.PARAMETER_VECTOR == ()
    # the three V1 magnitudes must be absent from the module entirely
    source = Path(V2.__file__).read_text()
    tree = ast.parse(source)
    assigned = {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)}
    assigned |= {n.target.id for n in ast.walk(tree)
                 if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
    for banned in ("DISPLACEMENT_BODY_RANGE_MIN", "FVG_MAX_AGE_M5_BARS",
                   "RETRACE_MAX_AGE_M5_BARS"):
        assert banned not in assigned, f"V2 re-introduced V1 tuning: {banned}"
    # and no numeric literal may masquerade as a body-ratio threshold
    assert 0.70 not in [n.value for n in ast.walk(tree)
                        if isinstance(n, ast.Constant) and isinstance(n.value, float)]


def test_displacement_body_ratio_is_recorded_but_never_gates():
    """The V1 magnitude survives as information, not as authority."""
    source = Path(V2.__file__).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            blob = ast.unparse(node)
            assert "body_range_ratio" not in blob and "displacement_body_ratio" not in blob, \
                f"body ratio used as a gate: {blob}"
    unit = _one_unit("A")
    assert unit.displacement_body_ratio is not None


def test_five_r_has_no_authority_anywhere_in_the_contract():
    target = V2.target_contract()
    assert target["five_r_required"] is False
    assert "DIAGNOSTIC_ONLY" in target["fixed_r_role"]
    assert target["selection_by_future_excursion"].startswith("FORBIDDEN")


# ---------------------------------------------------------------------------
# architecture
# ---------------------------------------------------------------------------

def test_exactly_two_branches_are_preregistered_and_one_was_rejected_by_mechanism():
    arch = V2.architecture_contract()
    states = {a["id"]: a["state"] for a in arch["architectures_considered"]}
    assert len([s for s in states.values() if s == "PREREGISTERED_BRANCH"]) == 2
    rejected = [a for a in arch["architectures_considered"]
                if a["state"] == "REJECTED_AT_DESIGN_TIME"]
    assert len(rejected) == 1
    assert "parameter" in rejected[0]["rejection_reason"].lower()
    assert arch["selection_authority"].startswith("MECHANISM_ONLY")
    assert len(arch["architectures_considered"]) <= 3


def test_branches_partition_the_event_space_and_cannot_overlap():
    a_unit, b_unit = _one_unit("A"), _one_unit("B")
    assert a_unit.branch == "A_SWEEP_RECLAIM_REVERSAL"
    assert b_unit.branch == "B_BREAKOUT_RETEST_CONTINUATION"
    assert a_unit.branch != b_unit.branch
    assert set(V2.BRANCHES) == {a_unit.branch, b_unit.branch}


def test_direction_is_endogenous_to_the_event_not_an_mtf_filter():
    a_unit = _one_unit("A")          # upper boundary rejected -> fade it
    assert a_unit.boundary_side == "UPPER" and a_unit.direction == "BEAR"
    b_unit = _one_unit("B")          # upper boundary accepted -> follow it
    assert b_unit.boundary_side == "UPPER" and b_unit.direction == "BULL"
    # higher-timeframe structure is recorded, and is NOT required to agree
    assert a_unit.mtf_agreement != "UNAVAILABLE"
    assert a_unit.passed("S4_SWEEP_OR_BREAKOUT")


def test_mtf_context_is_a_stratum_and_never_a_gate():
    """No rejection reason may be attributable to higher-timeframe context."""
    for reason, node in V2.REASON_NODE.items():
        assert "DIRECTION_NEUTRAL" not in reason
        assert "MTF" not in reason
    # Structural check: no context field may guard a branch that rejects a unit.
    # Labelling a stratum with a comparison is fine; failing a unit on one is not.
    fields = ("d1_structure", "h4_structure", "h1_structure", "mtf_agreement",
              "premium_discount_state", "regime")
    tree = ast.parse(Path(V2.__file__).read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test_src = ast.unparse(node.test)
        if not any(f in test_src for f in fields):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and getattr(inner.func, "id", "") == "_fail":
                pytest.fail(f"context gates a rejection: if {test_src}")


# ---------------------------------------------------------------------------
# funnel mechanics (synthetic)
# ---------------------------------------------------------------------------

def test_branch_a_runs_the_whole_funnel_to_a_completed_trade():
    unit = _one_unit("A")
    for node in V2.STAGE_NODES:
        assert unit.passed(node), f"branch A stalled at {node}: {unit.reject_reason}"
    assert unit.reject_reason == "PASS"
    assert unit.target == 100.0                      # opposite reference boundary
    assert unit.target_authority == "OPPOSITE_REFERENCE_BOUNDARY"
    assert unit.stop == pytest.approx(101.50)        # sweep extreme, no buffer
    assert unit.risk == pytest.approx(abs(unit.entry - 101.50))
    assert unit.natural_target_r and unit.natural_target_r > 0
    assert unit.resolution in {"TARGET_REACHED", "STOPPED_OUT", "HORIZON"}


def test_branch_b_runs_the_whole_funnel_to_a_completed_trade():
    unit = _one_unit("B")
    for node in V2.STAGE_NODES:
        assert unit.passed(node), f"branch B stalled at {node}: {unit.reject_reason}"
    assert unit.target_authority == "NEXT_CLOSED_H1_LIQUIDITY_POOL"
    assert unit.direction == "BULL"
    assert unit.stop is not None and unit.stop < unit.entry


def test_stage_order_is_strictly_sequential_no_stage_skipped():
    for kind in ("A", "B", "NO_EVENT", "BOTH_SIDES"):
        unit = _one_unit(kind)
        passed = [n for n in V2.STAGE_NODES if unit.passed(n)]
        assert passed == list(V2.STAGE_NODES[:len(passed)]), (kind, passed)
        if unit.reject_node is not None:
            assert not unit.passed(unit.reject_node)
            assert V2.REASON_NODE[unit.reject_reason] == unit.reject_node


def test_no_boundary_interaction_fails_at_the_session_event_stage():
    unit = _one_unit("NO_EVENT")
    assert unit.reject_node == "S3_SESSION_EVENT"
    assert unit.reject_reason == "NO_BOUNDARY_INTERACTION"
    assert unit.branch is None


def test_a_bar_piercing_both_boundaries_is_undecidable_never_guessed():
    unit = _one_unit("BOTH_SIDES")
    assert unit.boundary_side == "BOTH"
    assert unit.reject_reason == "ON_BOUNDARY_UNDECIDABLE"
    assert unit.direction == "NEUTRAL" and unit.branch is None


def test_every_reject_reason_maps_to_exactly_one_declared_node():
    assert set(V2.REASON_NODE) == set(V2.REJECT_REASONS) - {"PASS"}
    assert set(V2.REASON_NODE.values()) <= set(V2.STAGE_NODES)
    assert len(V2.REJECT_REASONS) == len(set(V2.REJECT_REASONS))


def test_causality_entry_never_precedes_its_own_evidence():
    for kind in ("A", "B"):
        unit = _one_unit(kind)
        stamps = [unit.event_time, unit.reclaim_or_retest_time, unit.confirm_time]
        assert all(s is not None for s in stamps)
        assert stamps == sorted(stamps), (kind, stamps)


def test_entry_fill_is_the_confirmation_close_and_needs_no_second_event():
    unit = _one_unit("A")
    assert "MARKET_ON_CONFIRMATION_CLOSE" in V2.entry_contract()["policy"]
    assert unit.entry is not None
    # no FVG / retrace machinery may exist in V2 at all
    src = Path(V2.__file__).read_text().lower()
    tree = ast.parse(Path(V2.__file__).read_text())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not {"detect_fvg", "fvgs_by_index"} & names


def test_one_unit_per_symbol_day_session_no_duplicate_signals():
    frames, start, end = build_case("A")
    warmup = _ramp(DAY - timedelta(days=V2.WARMUP_DAYS + 2), timedelta(minutes=15),
                   [100.5] * ((V2.WARMUP_DAYS + 2) * 96), pad=0.05)
    frames = {**frames, "M15": tuple(warmup) + frames["M15"]}
    units = V2.replay_symbol(frames, "TESTFX", start, end)
    keys = [(u.symbol, u.day, u.session) for u in units]
    assert len(keys) == len(set(keys)), "a session produced two units"
    assert set(u.session for u in units) == set(V2.SESSION_PAIRS)
    assert "ONE unit per" in V2.DUPLICATE_SIGNAL_POLICY


def test_searches_are_bounded_by_session_expiry_not_by_a_tuned_age():
    assert "expiry is the session clock itself" in V2.EXPIRY_POLICY
    src = Path(V2.__file__).read_text()
    tree = ast.parse(src)
    # the only horizon constant may be the shared measurement horizon
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id.endswith("_MAX_AGE_M5_BARS"):
            pytest.fail(f"V2 reintroduced an age bound: {node.id}")


def test_stop_is_structural_with_no_buffer():
    assert V2.sl_contract()["buffers"] == "NONE"
    unit = _one_unit("A")
    assert unit.stop == pytest.approx(101.50)   # exactly the sweep wick


def test_right_censoring_fails_trade_completed_and_is_never_imputed():
    frames, start, end = build_case("A")
    # amputate the forward series so the trade cannot resolve
    m5 = frames["M5"]
    cut = {**frames, "M5": m5[:-6]}
    from ag_edgelab.universal.confirmation import structure_shift_events
    shifts = structure_shift_events(cut["M5"], "M5", swing_order=V2.SWING_ORDER)
    by_index: dict[int, list] = {}
    for ev in shifts:
        by_index.setdefault(ev.index, []).append(ev)
    unit = V2.V2Unit(symbol="TESTFX", day=DAY.date().isoformat(), session="ASIAN_LONDON",
                     candidate_id="censor")
    V2._evaluate_unit(unit, cut["M15"], cut["M5"], cut["H1"], cut["H4"], cut["D1"],
                      by_index, DAY, 7, 10)
    if unit.passed("S8_GEOMETRY_VALID") and not unit.passed("S9_TRADE_COMPLETED"):
        assert unit.reject_reason == "RIGHT_CENSORED_DATA_BOUNDARY"
        assert unit.reached == {}
        assert unit.realised_r is None


def test_outcome_stop_wins_a_same_bar_collision():
    assert V2.SAME_BAR_COLLISION_POLICY == "STOP_FIRST_FAIL_CLOSED_V0_3"
    forward = (bar(DAY, 100.0, 101.0, 99.0, 100.0),)   # touches stop and target
    hit, stop_first = V2._resolve_target(forward, V2.Direction.BULL, 99.5, 100.8)
    assert hit is False and stop_first is True


# ---------------------------------------------------------------------------
# prohibitions
# ---------------------------------------------------------------------------

def test_no_execution_or_broker_imports():
    tree = ast.parse(Path(V2.__file__).read_text())
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    blob = " ".join(imported).lower()
    for token in ("nautilus", "metatrader", "mt5", "broker", "order_send", "place_order"):
        assert token not in blob


def test_no_economic_claim_is_possible():
    friction = V2.friction_contract()
    assert friction["ECONOMIC_EDGE"] == "NOT_ESTIMABLE"
    for key in ("spread_model", "commission_model", "slippage_model"):
        assert friction[key] == "NONE"


def test_the_module_never_requests_a_non_development_partition():
    src = Path(V2.__file__).read_text()
    tree = ast.parse(src)
    strings = {n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "OOS" not in strings
    assert not [s for s in strings if "SEALED_HOLDOUT" in s]


@pytest.mark.skipif(not (ART / "phase0_governance_verification.json").exists(),
                    reason="phase 0 not yet run")
def test_phase0_governance_passed_before_any_v2_design():
    report = json.loads((ART / "phase0_governance_verification.json").read_text())
    assert report["state"] == "PASS"
    assert not report["failures"]
    names = {c["check"] for c in report["checks"]}
    for required in ("v1_frozen_rule_hash_unchanged",
                     "zero_oos_access_events_under_the_r2_authority",
                     "sealed_holdout_untouched",
                     "no_contamination_record_extends_past_september"):
        assert required in names
        assert next(c for c in report["checks"] if c["check"] == required)["state"] == "PASS"
