"""ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2 — GENERATION 2 SESSION HYPOTHESIS.

STATUS: RESEARCH_CANDIDATE / DEVELOPMENT_ONLY / EDGE_VERIFIED = False.

This is a NEW hypothesis, not a retune of V1. V1 is closed evidence and is
neither imported nor modified here.

WHY V2 EXISTS
-------------
V1's multi-year DEV replay (63 symbol-years, 26,814 opportunities) produced
35 entries against a floor of 100 and was classified
STRATEGY_STRUCTURAL_STARVATION with three diagnoses. Each diagnosis is
answered here by a MECHANISM change, never by moving a number:

1. TRIGGER_FUNNEL_WEAKNESS. V1 lost 89% of decidable sessions to
   DIRECTION_NEUTRAL (12,577 -> 1,382) because it demanded an EXOGENOUS
   multi-timeframe trend agreement (D1 and H4 and H1) *before* it would look
   at the session at all, and then additionally required the sweep to occur
   on the side that trend implied.
   V2 claim: in a session-liquidity model the direction is ENDOGENOUS to the
   event. Which boundary gets raided, and whether price is rejected by it or
   accepted beyond it, IS the directional information. Higher-timeframe
   context is still computed and recorded as a stratum, but it is never a
   gate. This is an architectural change, not a loosened threshold.

2. CONFIRMATION_FUNNEL_WEAKNESS. V1 lost 88% of triggers (441 -> 51) across
   four sequential sub-conditions: a body-ratio displacement gate, then
   MSS/BOS, then a fresh FVG, then a causal retrace into that FVG.
   V2 claim: exactly ONE causal confirmation is entailed by the hypothesis —
   that market structure actually shifted in the event's direction. The
   body-ratio gate is a strength proxy, not a causal requirement, and the
   FVG-retrace requirement is an entry-pricing luxury that makes the trade
   conditional on a second event the thesis never claimed. Both are removed
   as GATES and the displacement body ratio is retained as a DIAGNOSTIC so
   no information is lost.
   V1's 0.70 is NOT lowered here. It is not used at all, and V2 introduces
   no replacement magnitude threshold to tune.

3. TARGET_MODEL_MISMATCH. V1's median natural target was ~1.004R and 5R was
   never reached in 35 entries, yet its fixed-R ladder treated 5R as a
   target authority.
   V2 claim: the target is the next opposing liquidity objective that is
   causally known at entry. 1R..5R are computed for every trade as
   DIAGNOSTICS ONLY and have no authority over entry, exit or selection.

PARAMETER VECTOR
----------------
EMPTY BY CONSTRUCTION. V2 adds no tunable magnitude, no ratio, no lookback
and no "max age" bound. Every search in V2 is bounded by the session expiry
itself. The only numbers present are (a) exogenous session clocks, (b)
inherited data-sufficiency and measurement contracts shared by every EdgeLab
campaign. There is therefore nothing in V2 that a later agent could "tune"
without changing the architecture, which is the point.

ARCHITECTURE: PREREGISTERED A/B BRANCH MODEL
--------------------------------------------
A single mechanism — price reaching a session reference boundary inside the
entry window — has exactly two causal resolutions, and they partition the
event space:

  BRANCH A  SWEEP_RECLAIM_REVERSAL
            the boundary REJECTS price: traded beyond, closed back inside.
  BRANCH B  BREAKOUT_RETEST_CONTINUATION
            price ACCEPTS beyond the boundary: closed beyond, then retested
            the broken level and held.

Both branches are preregistered and BOTH are reported. Neither is selected
on results; they are disjoint by construction (the same interaction bar
cannot both close inside and close beyond), so pooled = A + B with no double
counting and no cherry-picking.

A third architecture (TIME_OF_DAY_MOMENTUM_IGNITION) was considered and
REJECTED at design time: it has no location or liquidity mechanism, so it
degenerates into a search over clock times, which this mission forbids.

OPPORTUNITY BASIS
-----------------
Deliberately IDENTICAL to V1: one unit per (symbol, trading day, session
pair), at most one signal per unit. This keeps OPPORTUNITY_N comparable
between V1 and V2 so the Phase 5 comparison measures architecture rather
than a change of denominator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Sequence

from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.data.fx_histdata_2017 import bars_closed_at
from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.universal.confirmation import structure_shift_events
from ag_edgelab.universal.direction import Direction, structural_direction
from ag_edgelab.universal.location import (
    LocationSide,
    liquidity_levels,
    premium_discount,
)
from ag_edgelab.universal.targets import EntryGeometry, compute_excursions
from ag_edgelab.verification.regimes import classify_market_state

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Identity — NEW. Never reuse a historical candidate identity.
# ---------------------------------------------------------------------------

CANDIDATE_FAMILY_ID = "ASIAN_LIQUIDITY_DISPLACEMENT"
STRATEGY_ID = "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2"
STRATEGY_VERSION = "2.0.0-research"
STRATEGY_STATUS = "RESEARCH_CANDIDATE"
EDGE_VERIFIED = False
VERIFIER_VERSION = "EDGELAB_SYSTEM_READINESS_V1"

#: Identities that may never be reused or silently continued.
FORBIDDEN_IDENTITY_REUSE: tuple[str, ...] = (
    "ST_ASIAN_SWEEP_5R_V1",
    "SESSION_TRADE_V2",
    "ST_MTF_CONTROL_SHIFT_V1",
    "ST_MTF_CONTROL_SHIFT_V2",
    "TARGET_POLICY_C3_V1",
    "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1",
)

SYMBOL_UNIVERSE: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")
TIMEFRAMES: tuple[str, ...] = ("D1", "H4", "H1", "M15", "M5")

# ---------------------------------------------------------------------------
# Session contract — exogenous institutional clocks, NOT fitted parameters.
# Identical to the V1 contract so the Phase 5 comparison is apples-to-apples.
# ---------------------------------------------------------------------------

REFERENCE_WINDOW_UTC: tuple[int, int] = (0, 6)      # 00:00 <= UTC < 06:00
LONDON_ENTRY_UTC: tuple[int, int] = (7, 10)         # 07:00 <= UTC < 10:00
NEW_YORK_ENTRY_UTC: tuple[int, int] = (12, 15)      # 12:00 <= UTC < 15:00

SESSION_PAIRS: dict[str, tuple[int, int]] = {
    "ASIAN_LONDON": LONDON_ENTRY_UTC,
    "LONDON_NEWYORK": NEW_YORK_ENTRY_UTC,
}

SESSION_CONTRACT_NOTE = (
    "The Asian range (00:00-06:00 UTC) is the liquidity reference for both "
    "entry windows. Session windows are exogenous institutional boundaries, "
    "frozen before replay, and are NEVER widened, shifted or searched in "
    "response to observed results."
)

# ---------------------------------------------------------------------------
# Inherited contracts — data sufficiency and MEASUREMENT only.
# None of these is a strategy magnitude, and none was chosen by looking at a
# V2 result. They are held identical to V1 so the comparison is fair.
# ---------------------------------------------------------------------------

MIN_REFERENCE_M15_BARS = 16          # of 24 possible 00:00-06:00 M15 buckets
WARMUP_DAYS = 21                     # context warm-up inside the DEV partition
OUTCOME_HORIZON_M5_BARS = 288        # 24 traded hours, measured on M5
SWING_ORDER = 2                      # universal library default, not tuned
FIXED_R_TARGETS: tuple[int, ...] = (1, 2, 3, 4, 5)   # DIAGNOSTIC ONLY

#: V2 introduces no free numeric parameter. Asserted by the test-suite.
PARAMETER_VECTOR: tuple[str, ...] = ()

#: V1 magnitudes deliberately absent from V2 (not lowered — not present).
EXCLUDED_V1_TUNING: tuple[str, ...] = (
    "DISPLACEMENT_BODY_RANGE_MIN",   # 0.70 body-ratio gate — removed, not relaxed
    "FVG_MAX_AGE_M5_BARS",           # fresh-FVG age bound — mechanism removed
    "RETRACE_MAX_AGE_M5_BARS",       # retrace age bound — mechanism removed
    "MTF_DIRECTION_GATE",            # D1/H4/H1 agreement — demoted to a stratum
)

SAME_BAR_COLLISION_POLICY = "STOP_FIRST_FAIL_CLOSED_V0_3"
CENSORING_POLICY = (
    "RIGHT_CENSORED_DATA_BOUNDARY_EXPLICIT — a trade whose 288-M5-bar outcome "
    "window is truncated by the DEVELOPMENT partition end and that has not "
    "already resolved is RIGHT_CENSORED: it fails TRADE_COMPLETED, is excluded "
    "from capability denominators, is counted in the population and is never "
    "imputed. The OOS partition is NEVER read to complete an outcome window."
)
ENTRY_FILL_POLICY = (
    "MARKET_ON_CONFIRMATION_CLOSE — the fill price is the CLOSE of the M5 bar "
    "on which the structure shift confirms. That price is causally available "
    "at the decision instant and requires no second event. Outcome measurement "
    "starts at the NEXT M5 bar; if the confirmation bar itself already trades "
    "through the structural stop the trade is recorded STOPPED_SAME_BAR = -1R "
    "(fail-closed)."
)
STOP_CONTRACT_NOTE = (
    "Structural stop ONLY, taken from the event that defines the thesis: "
    "branch A uses the SWEEP EXTREME (the wick that raided the boundary), "
    "branch B uses the RETEST EXTREME (the deepest point of the pullback that "
    "held). No pip/point buffer is ever added; execution buffering belongs to "
    "the friction layer, which has no authority in this mission."
)
TARGET_CONTRACT_NOTE = (
    "TARGET AUTHORITY = the next opposing liquidity objective causally known "
    "at the entry instant. Branch A: the OPPOSITE reference boundary (the "
    "liquidity resting on the far side of the raided range). Branch B: the "
    "nearest CLOSED-H1 liquidity pool beyond entry in the direction of travel. "
    "No fixed R multiple has any authority. 1R..5R are diagnostics."
)
DUPLICATE_SIGNAL_POLICY = (
    "ONE unit per (symbol, trading day, session pair) and at most ONE signal "
    "per unit. The FIRST boundary interaction inside the entry window is the "
    "only one evaluated; its close decides the branch. If a unit fails at any "
    "stage no later interaction is re-examined, so a session can never "
    "contribute two correlated observations."
)
EXPIRY_POLICY = (
    "Every search — reclaim, retest, structure confirmation — is bounded by "
    "the END OF THE ENTRY WINDOW and by nothing else. V2 has no 'max age' "
    "parameter; expiry is the session clock itself."
)

# ---------------------------------------------------------------------------
# Funnel vocabulary (mission Phase 4, in order)
# ---------------------------------------------------------------------------

STAGE_NODES: tuple[str, ...] = (
    "S1_CONTEXT_ELIGIBLE",
    "S2_LOCATION_ELIGIBLE",
    "S3_SESSION_EVENT",
    "S4_SWEEP_OR_BREAKOUT",
    "S5_RECLAIM_OR_RETEST",
    "S6_STRUCTURE_CONFIRM",
    "S7_ENTRY_AVAILABLE",
    "S8_GEOMETRY_VALID",
    "S9_TRADE_COMPLETED",
)
OUTCOME_NODES: tuple[str, ...] = ("O1_1R", "O2_2R", "O3_3R", "O4_4R", "O5_5R")
ALL_NODES: tuple[str, ...] = STAGE_NODES + OUTCOME_NODES

BRANCHES: tuple[str, ...] = ("A_SWEEP_RECLAIM_REVERSAL", "B_BREAKOUT_RETEST_CONTINUATION")

REJECT_REASONS: tuple[str, ...] = (
    "PASS",
    # S1
    "REFERENCE_INSUFFICIENT_BARS",
    "ENTRY_WINDOW_NO_BARS",
    # S2
    "REFERENCE_RANGE_DEGENERATE",
    "LOCATION_STATE_UNAVAILABLE",
    # S3
    "NO_BOUNDARY_INTERACTION",
    # S4
    "ON_BOUNDARY_UNDECIDABLE",
    # S5
    "NO_RECLAIM_BEFORE_EXPIRY",
    "NO_RETEST_BEFORE_EXPIRY",
    "INVALIDATED_BEFORE_RETEST",
    # S6
    "NO_STRUCTURE_SHIFT_BEFORE_EXPIRY",
    "INVALIDATED_BEFORE_CONFIRM",
    # S7
    "NO_FORWARD_BARS",
    # S8
    "GEOMETRY_RISK_NON_POSITIVE",
    "GEOMETRY_TARGET_NOT_BEYOND_ENTRY",
    "GEOMETRY_TEMPORAL_ORDER_INVALID",
    "NO_TARGET_OBJECTIVE",
    # S9
    "RIGHT_CENSORED_DATA_BOUNDARY",
)

#: Which node each reason belongs to — asserted complete by the test-suite.
REASON_NODE: dict[str, str] = {
    "REFERENCE_INSUFFICIENT_BARS": "S1_CONTEXT_ELIGIBLE",
    "ENTRY_WINDOW_NO_BARS": "S1_CONTEXT_ELIGIBLE",
    "REFERENCE_RANGE_DEGENERATE": "S2_LOCATION_ELIGIBLE",
    "LOCATION_STATE_UNAVAILABLE": "S2_LOCATION_ELIGIBLE",
    "NO_BOUNDARY_INTERACTION": "S3_SESSION_EVENT",
    "ON_BOUNDARY_UNDECIDABLE": "S4_SWEEP_OR_BREAKOUT",
    "NO_RECLAIM_BEFORE_EXPIRY": "S5_RECLAIM_OR_RETEST",
    "NO_RETEST_BEFORE_EXPIRY": "S5_RECLAIM_OR_RETEST",
    "INVALIDATED_BEFORE_RETEST": "S5_RECLAIM_OR_RETEST",
    "NO_STRUCTURE_SHIFT_BEFORE_EXPIRY": "S6_STRUCTURE_CONFIRM",
    "INVALIDATED_BEFORE_CONFIRM": "S6_STRUCTURE_CONFIRM",
    "NO_FORWARD_BARS": "S7_ENTRY_AVAILABLE",
    "GEOMETRY_RISK_NON_POSITIVE": "S8_GEOMETRY_VALID",
    "GEOMETRY_TARGET_NOT_BEYOND_ENTRY": "S8_GEOMETRY_VALID",
    "GEOMETRY_TEMPORAL_ORDER_INVALID": "S8_GEOMETRY_VALID",
    "NO_TARGET_OBJECTIVE": "S8_GEOMETRY_VALID",
    "RIGHT_CENSORED_DATA_BOUNDARY": "S9_TRADE_COMPLETED",
}


# ---------------------------------------------------------------------------
# Candidate record
# ---------------------------------------------------------------------------

@dataclass
class V2Unit:
    symbol: str
    day: str
    session: str
    candidate_id: str

    # context strata — RECORDED, never gates
    d1_structure: str = "UNAVAILABLE"
    h4_structure: str = "UNAVAILABLE"
    h1_structure: str = "UNAVAILABLE"
    mtf_agreement: str = "UNAVAILABLE"
    premium_discount_state: str = "UNAVAILABLE"
    regime: str = "UNAVAILABLE"
    quarter: str = ""

    reference_high: float | None = None
    reference_low: float | None = None
    reference_bars: int = 0
    entry_window_m5_bars: int = 0

    # event evidence
    branch: str | None = None
    direction: str = "NEUTRAL"
    boundary_side: str | None = None
    event_time: str | None = None
    reclaim_or_retest_time: str | None = None
    confirm_time: str | None = None
    confirm_primitive: str | None = None
    displacement_body_ratio: float | None = None   # DIAGNOSTIC ONLY

    stages: dict[str, bool] = field(default_factory=dict)
    reject_reason: str = "PASS"
    reject_node: str | None = None

    entry: float | None = None
    stop: float | None = None
    risk: float | None = None
    target: float | None = None
    target_authority: str | None = None
    natural_target_r: float | None = None

    # outcome
    mfe_r: float | None = None
    mae_r: float | None = None
    reached: dict[str, bool] = field(default_factory=dict)
    stopped_out: bool | None = None
    stopped_same_bar: bool = False
    forward_bars: int = 0
    resolution: str | None = None
    target_reached: bool | None = None
    realised_r: float | None = None

    def passed(self, node: str) -> bool:
        return bool(self.stages.get(node))


def _fail(unit: V2Unit, node: str, reason: str) -> None:
    unit.stages[node] = False
    unit.reject_node = node
    unit.reject_reason = reason


def _window_indices(bars: Sequence[MarketBar], start: datetime, end: datetime) -> tuple[int, ...]:
    return tuple(i for i, b in enumerate(bars) if start <= b.timestamp < end)


def body_range_ratio(bar: MarketBar) -> float | None:
    """Diagnostic only. V2 never gates on this value."""
    span = bar.high - bar.low
    if span <= 0:
        return None
    return abs(bar.close - bar.open) / span


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def replay_symbol(frames: dict[str, tuple[MarketBar, ...]], symbol: str,
                  dev_start: datetime, dev_end: datetime) -> list[V2Unit]:
    """Causal replay of one symbol over one DEVELOPMENT partition.

    `dev_end` bounds the data that exists; it is never consulted as a rule.
    """
    m15 = frames["M15"]
    m5 = frames["M5"]
    h1 = frames["H1"]
    h4 = frames["H4"]
    d1 = frames["D1"]
    if not m15 or not m5:
        return []

    shifts = structure_shift_events(m5, "M5", swing_order=SWING_ORDER)
    shifts_by_index: dict[int, list] = {}
    for ev in shifts:
        shifts_by_index.setdefault(ev.index, []).append(ev)

    first_day = (m15[0].timestamp + timedelta(days=WARMUP_DAYS)).date()
    last_day = m15[-1].timestamp.date()

    units: list[V2Unit] = []
    day = first_day
    while day <= last_day:
        day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        for session, (entry_from, entry_to) in SESSION_PAIRS.items():
            unit = V2Unit(symbol=symbol, day=day.isoformat(), session=session,
                          candidate_id=f"{symbol}|{day.isoformat()}|{session}|V2")
            _evaluate_unit(unit, m15, m5, h1, h4, d1, shifts_by_index,
                           day_start, entry_from, entry_to)
            units.append(unit)
        day += timedelta(days=1)
    return units


def _evaluate_unit(
    unit: V2Unit,
    m15: tuple[MarketBar, ...], m5: tuple[MarketBar, ...],
    h1: tuple[MarketBar, ...], h4: tuple[MarketBar, ...], d1: tuple[MarketBar, ...],
    shifts_by_index: dict[int, list],
    day_start: datetime, entry_from: int, entry_to: int,
) -> None:
    ref_start = day_start + timedelta(hours=REFERENCE_WINDOW_UTC[0])
    ref_end = day_start + timedelta(hours=REFERENCE_WINDOW_UTC[1])
    w_start = day_start + timedelta(hours=entry_from)
    w_end = day_start + timedelta(hours=entry_to)

    # ---------------- S1 CONTEXT_ELIGIBLE --------------------------------
    ref_idx = _window_indices(m15, ref_start, ref_end)
    unit.reference_bars = len(ref_idx)
    if len(ref_idx) < MIN_REFERENCE_M15_BARS:
        _fail(unit, "S1_CONTEXT_ELIGIBLE", "REFERENCE_INSUFFICIENT_BARS")
        return
    m5_idx = _window_indices(m5, w_start, w_end)
    unit.entry_window_m5_bars = len(m5_idx)
    if not m5_idx:
        _fail(unit, "S1_CONTEXT_ELIGIBLE", "ENTRY_WINDOW_NO_BARS")
        return
    unit.stages["S1_CONTEXT_ELIGIBLE"] = True

    # ---------------- S2 LOCATION_ELIGIBLE -------------------------------
    ref_bars = [m15[i] for i in ref_idx]
    ref_high = max(b.high for b in ref_bars)
    ref_low = min(b.low for b in ref_bars)
    unit.reference_high, unit.reference_low = ref_high, ref_low
    if not ref_high > ref_low:
        _fail(unit, "S2_LOCATION_ELIGIBLE", "REFERENCE_RANGE_DEGENERATE")
        return

    # context strata: computed from CLOSED bars only, recorded, never a gate
    h1_closed = bars_closed_at(h1, "H1", w_start)
    h4_closed = bars_closed_at(h4, "H4", w_start)
    d1_closed = bars_closed_at(d1, "D1", w_start)
    unit.d1_structure = structural_direction(d1_closed, "D1", SWING_ORDER).direction.value \
        if d1_closed else "UNAVAILABLE"
    unit.h4_structure = structural_direction(h4_closed, "H4", SWING_ORDER).direction.value \
        if h4_closed else "UNAVAILABLE"
    unit.h1_structure = structural_direction(h1_closed, "H1", SWING_ORDER).direction.value \
        if h1_closed else "UNAVAILABLE"
    agree = {unit.d1_structure, unit.h4_structure, unit.h1_structure}
    unit.mtf_agreement = ("ALIGNED_" + unit.d1_structure
                          if len(agree) == 1 and unit.d1_structure in ("BULL", "BEAR")
                          else "MIXED")
    pd_state = premium_discount(h1_closed, "H1", m15[ref_idx[-1]].close, SWING_ORDER) \
        if h1_closed else None
    if pd_state is None:
        _fail(unit, "S2_LOCATION_ELIGIBLE", "LOCATION_STATE_UNAVAILABLE")
        return
    unit.premium_discount_state = pd_state.state
    unit.regime = classify_market_state(h1_closed[-1]) if h1_closed else "UNAVAILABLE"
    unit.quarter = f"{day_start.year}Q{(day_start.month - 1) // 3 + 1}"
    unit.stages["S2_LOCATION_ELIGIBLE"] = True

    # ---------------- S3 SESSION_EVENT -----------------------------------
    # The FIRST M15 bar of the entry window that trades beyond a boundary.
    win_idx = _window_indices(m15, w_start, w_end)
    event_i: int | None = None
    side: str | None = None
    for i in win_idx:
        above = m15[i].high > ref_high
        below = m15[i].low < ref_low
        if above or below:
            event_i = i
            # If one bar pierces both boundaries the raid is undecidable at
            # M15 resolution; recorded, never guessed.
            side = "BOTH" if (above and below) else ("UPPER" if above else "LOWER")
            break
    if event_i is None:
        _fail(unit, "S3_SESSION_EVENT", "NO_BOUNDARY_INTERACTION")
        return
    unit.stages["S3_SESSION_EVENT"] = True
    unit.event_time = m15[event_i].timestamp.isoformat()
    unit.boundary_side = side

    # ---------------- S4 SWEEP_OR_BREAKOUT -------------------------------
    bar = m15[event_i]
    unit.displacement_body_ratio = body_range_ratio(bar)   # diagnostic only
    if side == "BOTH":
        _fail(unit, "S4_SWEEP_OR_BREAKOUT", "ON_BOUNDARY_UNDECIDABLE")
        return
    boundary = ref_high if side == "UPPER" else ref_low
    if bar.close == boundary:
        _fail(unit, "S4_SWEEP_OR_BREAKOUT", "ON_BOUNDARY_UNDECIDABLE")
        return

    accepted_beyond = (bar.close > ref_high) if side == "UPPER" else (bar.close < ref_low)
    if accepted_beyond:
        unit.branch = "B_BREAKOUT_RETEST_CONTINUATION"
        unit.direction = (Direction.BULL if side == "UPPER" else Direction.BEAR).value
    else:
        unit.branch = "A_SWEEP_RECLAIM_REVERSAL"
        # the boundary rejected price: trade AGAINST the raid
        unit.direction = (Direction.BEAR if side == "UPPER" else Direction.BULL).value
    unit.stages["S4_SWEEP_OR_BREAKOUT"] = True

    direction = Direction.BULL if unit.direction == "BULL" else Direction.BEAR
    if unit.branch == "A_SWEEP_RECLAIM_REVERSAL":
        _branch_a(unit, m15, m5, h1, shifts_by_index, event_i, side,
                  ref_high, ref_low, w_end, direction)
    else:
        _branch_b(unit, m15, m5, h1, shifts_by_index, event_i, side,
                  ref_high, ref_low, w_end, direction)


def _branch_a(unit: V2Unit, m15, m5, h1, shifts_by_index, event_i: int, side: str,
              ref_high: float, ref_low: float, w_end: datetime,
              direction: Direction) -> None:
    """Boundary rejected price: sweep -> reclaim -> structure shift -> entry."""
    # ---------------- S5 RECLAIM (close back inside the range) -----------
    # By construction of S4 the interaction bar closed back inside, so the
    # reclaim instant is that bar's close. Expiry-bounded, no age parameter.
    reclaim_i = event_i
    inside = ref_low < m15[reclaim_i].close < ref_high
    if not inside:
        # closed beyond the OPPOSITE boundary — not a reclaim of this range
        _fail(unit, "S5_RECLAIM_OR_RETEST", "NO_RECLAIM_BEFORE_EXPIRY")
        return
    unit.stages["S5_RECLAIM_OR_RETEST"] = True
    unit.reclaim_or_retest_time = m15[reclaim_i].timestamp.isoformat()

    sweep_extreme = m15[event_i].high if side == "UPPER" else m15[event_i].low
    reclaim_close_time = m15[reclaim_i].timestamp + timedelta(minutes=15)
    target = ref_low if direction == Direction.BEAR else ref_high
    _confirm_and_measure(unit, m5, h1, shifts_by_index, reclaim_close_time, w_end,
                         direction, protective_extreme=sweep_extreme,
                         target=target, target_authority="OPPOSITE_REFERENCE_BOUNDARY")


def _branch_b(unit: V2Unit, m15, m5, h1, shifts_by_index, event_i: int, side: str,
              ref_high: float, ref_low: float, w_end: datetime,
              direction: Direction) -> None:
    """Price accepted beyond: breakout -> retest holds -> structure shift."""
    broken_level = ref_high if side == "UPPER" else ref_low
    search_from = m15[event_i].timestamp + timedelta(minutes=15)

    # ---------------- S5 RETEST (returns to the level and holds) ---------
    retest_i: int | None = None
    retest_extreme: float | None = None
    invalidated = False
    for j in _window_indices(m5, search_from, w_end):
        b = m5[j]
        if direction == Direction.BULL:
            if b.close < broken_level:        # acceptance lost before the retest
                invalidated = True
                break
            if b.low <= broken_level:         # returned to the level and held
                retest_i, retest_extreme = j, b.low
                break
        else:
            if b.close > broken_level:
                invalidated = True
                break
            if b.high >= broken_level:
                retest_i, retest_extreme = j, b.high
                break
    if retest_i is None or retest_extreme is None:
        _fail(unit, "S5_RECLAIM_OR_RETEST",
              "INVALIDATED_BEFORE_RETEST" if invalidated else "NO_RETEST_BEFORE_EXPIRY")
        return
    unit.stages["S5_RECLAIM_OR_RETEST"] = True
    unit.reclaim_or_retest_time = m5[retest_i].timestamp.isoformat()

    confirm_from = m5[retest_i].timestamp + timedelta(minutes=5)
    _confirm_and_measure(unit, m5, h1, shifts_by_index, confirm_from, w_end,
                         direction, protective_extreme=retest_extreme,
                         target=None, target_authority="NEXT_CLOSED_H1_LIQUIDITY_POOL")


def _confirm_and_measure(unit: V2Unit, m5, h1, shifts_by_index,
                         search_from: datetime, w_end: datetime,
                         direction: Direction, protective_extreme: float,
                         target: float | None, target_authority: str) -> None:
    # ---------------- S6 STRUCTURE_CONFIRM -------------------------------
    confirm_i: int | None = None
    primitive: str | None = None
    invalidated = False
    for j in _window_indices(m5, search_from, w_end):
        b = m5[j]
        # the thesis dies if price violates the protective extreme first
        if direction == Direction.BULL and b.low <= protective_extreme:
            invalidated = True
            break
        if direction == Direction.BEAR and b.high >= protective_extreme:
            invalidated = True
            break
        for ev in shifts_by_index.get(j, ()):
            if ev.direction == direction:
                confirm_i, primitive = j, ev.primitive.value
                break
        if confirm_i is not None:
            break
    if confirm_i is None:
        _fail(unit, "S6_STRUCTURE_CONFIRM",
              "INVALIDATED_BEFORE_CONFIRM" if invalidated
              else "NO_STRUCTURE_SHIFT_BEFORE_EXPIRY")
        return
    unit.stages["S6_STRUCTURE_CONFIRM"] = True
    unit.confirm_time = m5[confirm_i].timestamp.isoformat()
    unit.confirm_primitive = primitive

    # ---------------- S7 ENTRY_AVAILABLE ---------------------------------
    entry_price = m5[confirm_i].close
    forward = m5[confirm_i + 1: confirm_i + 1 + OUTCOME_HORIZON_M5_BARS]
    unit.forward_bars = len(forward)
    entry_bar = m5[confirm_i]
    same_bar_stop = (entry_bar.low <= protective_extreme) if direction == Direction.BULL \
        else (entry_bar.high >= protective_extreme)
    if not forward and not same_bar_stop:
        _fail(unit, "S7_ENTRY_AVAILABLE", "NO_FORWARD_BARS")
        return
    unit.stages["S7_ENTRY_AVAILABLE"] = True
    unit.entry, unit.stop = entry_price, protective_extreme
    unit.stopped_same_bar = bool(same_bar_stop)

    # ---------------- S8 GEOMETRY_VALID ----------------------------------
    risk = abs(entry_price - protective_extreme)
    if risk <= 0:
        _fail(unit, "S8_GEOMETRY_VALID", "GEOMETRY_RISK_NON_POSITIVE")
        return
    unit.risk = risk

    if target is None:
        # branch B: nearest CLOSED-H1 liquidity pool beyond entry
        h1_at_entry = bars_closed_at(h1, "H1", m5[confirm_i].timestamp + timedelta(minutes=5))
        if h1_at_entry:
            zones = liquidity_levels(h1_at_entry, "H1", SWING_ORDER)
            if direction == Direction.BULL:
                cand = [z.zone_low for z in zones
                        if z.side == LocationSide.RESISTANCE and z.zone_low > entry_price]
                target = min(cand) if cand else None
            else:
                cand = [z.zone_high for z in zones
                        if z.side == LocationSide.SUPPORT and z.zone_high < entry_price]
                target = max(cand) if cand else None
        if target is None:
            _fail(unit, "S8_GEOMETRY_VALID", "NO_TARGET_OBJECTIVE")
            return

    beyond = (target > entry_price) if direction == Direction.BULL else (target < entry_price)
    if not beyond:
        _fail(unit, "S8_GEOMETRY_VALID", "GEOMETRY_TARGET_NOT_BEYOND_ENTRY")
        return
    times = [unit.event_time, unit.reclaim_or_retest_time, unit.confirm_time]
    if any(times[k] > times[k + 1] for k in range(len(times) - 1)):  # type: ignore[operator]
        _fail(unit, "S8_GEOMETRY_VALID", "GEOMETRY_TEMPORAL_ORDER_INVALID")
        return
    unit.stages["S8_GEOMETRY_VALID"] = True
    unit.target, unit.target_authority = target, target_authority
    unit.natural_target_r = abs(target - entry_price) / risk

    # ---------------- S9 TRADE_COMPLETED + outcome -----------------------
    geo = EntryGeometry(direction=direction, entry=entry_price, stop=protective_extreme)
    if same_bar_stop:
        unit.mfe_r, unit.mae_r = 0.0, 1.0
        unit.reached = {f"{k}R": False for k in FIXED_R_TARGETS}
        unit.stopped_out, unit.target_reached = True, False
        unit.resolution, unit.realised_r = "STOPPED_SAME_BAR", -1.0
        unit.stages["S9_TRADE_COMPLETED"] = True
        unit.reject_reason = "PASS"
        return

    exc = compute_excursions(tuple(forward), geo, OUTCOME_HORIZON_M5_BARS)
    target_hit, stop_first = _resolve_target(forward, direction, protective_extreme, target)
    resolved = exc.stopped_out or target_hit
    if not resolved and len(forward) < OUTCOME_HORIZON_M5_BARS:
        unit.mfe_r, unit.mae_r = exc.mfe_r, exc.mae_r
        _fail(unit, "S9_TRADE_COMPLETED", "RIGHT_CENSORED_DATA_BOUNDARY")
        return

    unit.stages["S9_TRADE_COMPLETED"] = True
    unit.reject_reason = "PASS"
    unit.mfe_r, unit.mae_r = exc.mfe_r, exc.mae_r
    unit.reached = {f"{k}R": bool(v) for k, v in sorted(exc.fixed_target_reached.items())}
    unit.stopped_out = exc.stopped_out
    unit.target_reached = bool(target_hit)
    if target_hit and not stop_first:
        unit.resolution = "TARGET_REACHED"
        unit.realised_r = unit.natural_target_r
    elif exc.stopped_out:
        unit.resolution = "STOPPED_OUT"
        unit.realised_r = -1.0
    else:
        unit.resolution = "HORIZON"
        last = forward[-1].close
        unit.realised_r = ((last - entry_price) / unit.risk if direction == Direction.BULL
                           else (entry_price - last) / unit.risk)

    for k in FIXED_R_TARGETS:
        node = f"O{k}_{k}R"
        unit.stages[node] = bool(unit.reached.get(f"{k}R"))
        if not unit.stages[node]:
            break


def _resolve_target(forward: Sequence[MarketBar], direction: Direction,
                    stop: float, target: float) -> tuple[bool, bool]:
    """Did the structural target print before the stop? Stop wins same-bar."""
    for b in forward:
        if direction == Direction.BULL:
            hit_stop, hit_tp = b.low <= stop, b.high >= target
        else:
            hit_stop, hit_tp = b.high >= stop, b.low <= target
        if hit_stop:
            return (False, True) if hit_tp else (False, False)
        if hit_tp:
            return True, False
    return False, False


# ---------------------------------------------------------------------------
# Frozen contracts
# ---------------------------------------------------------------------------

def architecture_contract() -> dict:
    return {
        "architectures_considered": [
            {"id": "A_SWEEP_RECLAIM_REVERSAL", "state": "PREREGISTERED_BRANCH",
             "mechanism": "A session reference boundary is raided for resting liquidity and "
                          "REJECTS price (trades beyond, closes back inside). The raid itself "
                          "names the direction: trade away from the swept side.",
             "causal_information_at_decision_time": [
                 "closed reference-window M15 bars (00:00-06:00 UTC)",
                 "the closed M15 interaction bar inside the entry window",
                 "closed M5 bars up to and including the confirming bar",
                 "closed H1/H4/D1 context bars (recorded as strata only)"]},
            {"id": "B_BREAKOUT_RETEST_CONTINUATION", "state": "PREREGISTERED_BRANCH",
             "mechanism": "Price ACCEPTS beyond the boundary (closes beyond), returns to the "
                          "broken level and holds it. Acceptance plus a held retest names the "
                          "direction: trade with the breakout.",
             "causal_information_at_decision_time": [
                 "closed reference-window M15 bars",
                 "the closed M15 breakout bar",
                 "closed M5 bars through the retest and the confirming bar",
                 "closed H1 liquidity pools for the target"]},
            {"id": "C_TIME_OF_DAY_MOMENTUM_IGNITION", "state": "REJECTED_AT_DESIGN_TIME",
             "rejection_reason": "No location or liquidity mechanism. Without a structural "
                                 "reference the hypothesis reduces to a search over clock "
                                 "times and momentum thresholds, which is parameter "
                                 "optimization and is forbidden by this mission."},
        ],
        "selection_rule": (
            "A PREREGISTERED A/B BRANCH MODEL, selected before replay on mechanism grounds: A "
            "and B are the only two causal resolutions of one event (a boundary interaction) "
            "and they PARTITION the event space, so running both measures the whole mechanism "
            "instead of a chosen half. Branches are disjoint by construction — the interaction "
            "bar either closes back inside (A) or beyond (B), never both."),
        "selection_authority": "MECHANISM_ONLY — no branch may be dropped, ranked or "
                               "preferred on the basis of its replayed results.",
        "branches": list(BRANCHES),
    }


def session_contract() -> dict:
    return {
        "reference_window_utc": {"start_hour": REFERENCE_WINDOW_UTC[0],
                                 "end_hour": REFERENCE_WINDOW_UTC[1]},
        "session_pairs": {k: {"start_hour": v[0], "end_hour": v[1]}
                          for k, v in SESSION_PAIRS.items()},
        "note": SESSION_CONTRACT_NOTE,
        "widening_allowed": False,
        "clock": "UTC, derived from the frozen PR#10 timezone normalization",
    }


def trigger_contract() -> dict:
    return {
        "opportunity_basis": "one unit per (symbol, trading day, session pair)",
        "context_eligible": {
            "reference_bars_required": MIN_REFERENCE_M15_BARS,
            "entry_window_bars_required": 1,
            "note": "data-sufficiency only; NOT a directional filter",
        },
        "location_eligible": {
            "rule": "reference range non-degenerate (high > low) AND a causally computable "
                    "premium/discount state from CLOSED H1 bars",
            "note": "availability of a location frame, not a view on it",
        },
        "session_event": "the FIRST M15 bar of the entry window whose high exceeds the "
                         "reference high or whose low breaks the reference low",
        "sweep_definition": "branch A: the interaction bar trades beyond the boundary and "
                            "CLOSES BACK INSIDE the reference range",
        "breakout_acceptance": "branch B: the interaction bar CLOSES BEYOND the boundary "
                               "(body acceptance; no magnitude threshold exists)",
        "reclaim_definition": "branch A: the close of the interaction bar is strictly inside "
                              "(reference_low, reference_high)",
        "retest_definition": "branch B: the first M5 bar after the breakout bar that trades "
                             "back to the broken level (low <= level for BULL, high >= level "
                             "for BEAR) while still CLOSING on the breakout side",
        "undecidable": "an interaction bar that pierces BOTH boundaries, or closes exactly on "
                       "the boundary, is ON_BOUNDARY_UNDECIDABLE and is never guessed",
        "direction_rule": "ENDOGENOUS to the event. A: trade away from the swept boundary. "
                          "B: trade with the accepted breakout. Higher-timeframe structure is "
                          "recorded as a stratum and NEVER gates a unit.",
        "duplicate_signal_policy": DUPLICATE_SIGNAL_POLICY,
        "expiry": EXPIRY_POLICY,
    }


def confirmation_contract() -> dict:
    return {
        "rule": "the FIRST closed-M5 structure shift (MSS/BOS) in the event direction, strictly "
                "after the reclaim/retest instant and strictly before session expiry",
        "detector": "ag_edgelab.universal.confirmation.structure_shift_events (shared library, "
                    f"swing_order={SWING_ORDER} library default)",
        "invalidation": "the unit dies if price violates the protective extreme (branch A: the "
                        "sweep extreme; branch B: the retest extreme) BEFORE a structure shift "
                        "confirms",
        "single_condition_rationale": (
            "V1 chained four confirmation conditions and lost 88% of its triggers. V2 keeps the "
            "one condition the hypothesis actually entails — that structure shifted — and "
            "records the V1 body-ratio as a diagnostic instead of a gate."),
        "removed_from_v1_not_relaxed": list(EXCLUDED_V1_TUNING),
    }


def entry_contract() -> dict:
    return {"policy": ENTRY_FILL_POLICY,
            "fill_price": "close of the confirming M5 bar",
            "same_bar_collision": SAME_BAR_COLLISION_POLICY}


def sl_contract() -> dict:
    return {"policy": STOP_CONTRACT_NOTE,
            "branch_A": "sweep extreme (high for SHORT, low for LONG)",
            "branch_B": "retest extreme (deepest point of the pullback that held)",
            "buffers": "NONE"}


def target_contract() -> dict:
    return {
        "authority": TARGET_CONTRACT_NOTE,
        "branch_A_target": "OPPOSITE_REFERENCE_BOUNDARY",
        "branch_B_target": "NEXT_CLOSED_H1_LIQUIDITY_POOL",
        "fixed_r_role": "DIAGNOSTIC_ONLY — 1R..5R are measured for every completed trade and "
                        "have no authority over entry, exit, selection or the verdict",
        "five_r_required": False,
        "selection_by_future_excursion": "FORBIDDEN — the target is fixed at the entry instant "
                                         "from causally known levels",
    }


def parameter_contract() -> dict:
    return {
        "parameter_vector": list(PARAMETER_VECTOR),
        "free_parameters_n": len(PARAMETER_VECTOR),
        "claim": "V2 has NO tunable strategy magnitude. Every search bound is the session "
                 "expiry; every numeric constant below is either an exogenous session clock or "
                 "an inherited data-sufficiency / measurement contract shared with V1 so that "
                 "the comparison is fair.",
        "exogenous_session_clocks": {"reference": REFERENCE_WINDOW_UTC,
                                     "london_entry": LONDON_ENTRY_UTC,
                                     "new_york_entry": NEW_YORK_ENTRY_UTC},
        "inherited_measurement_contracts": {
            "MIN_REFERENCE_M15_BARS": MIN_REFERENCE_M15_BARS,
            "WARMUP_DAYS": WARMUP_DAYS,
            "OUTCOME_HORIZON_M5_BARS": OUTCOME_HORIZON_M5_BARS,
            "SWING_ORDER": SWING_ORDER,
            "SAME_BAR_COLLISION_POLICY": SAME_BAR_COLLISION_POLICY,
            "CENSORING_POLICY": CENSORING_POLICY,
        },
        "v1_tuning_deliberately_absent": list(EXCLUDED_V1_TUNING),
        "optimization": "NONE. No grid, no Optuna, no threshold search, no session search, no "
                        "RR search, no post-hoc symbol or branch selection.",
    }


def friction_contract() -> dict:
    return {
        "measured_friction_available": "NO",
        "spread_model": "NONE",
        "commission_model": "NONE",
        "slippage_model": "NONE",
        "ECONOMIC_EDGE": "NOT_ESTIMABLE",
        "note": "Structural R only. No generic spread, per-lot commission or invented slippage "
                "may be substituted, so no economic claim is made anywhere in this campaign.",
    }


def strategy_contract() -> dict:
    return {
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "candidate_family_id": CANDIDATE_FAMILY_ID,
        "status": STRATEGY_STATUS,
        "edge_verified": EDGE_VERIFIED,
        "verifier_version": VERIFIER_VERSION,
        "symbol_universe": list(SYMBOL_UNIVERSE),
        "timeframes": list(TIMEFRAMES),
        "architecture": architecture_contract(),
        "session": session_contract(),
        "trigger": trigger_contract(),
        "confirmation": confirmation_contract(),
        "entry": entry_contract(),
        "stop_loss": sl_contract(),
        "target": target_contract(),
        "parameters": parameter_contract(),
        "friction": friction_contract(),
        "funnel_nodes": list(STAGE_NODES),
        "outcome_nodes": list(OUTCOME_NODES),
        "reject_reasons": list(REJECT_REASONS),
        "censoring": CENSORING_POLICY,
        "forbidden_identity_reuse": list(FORBIDDEN_IDENTITY_REUSE),
    }


def contract_hashes() -> dict[str, str]:
    return {
        "architecture_contract_hash": sha256_json(architecture_contract()),
        "session_contract_hash": sha256_json(session_contract()),
        "trigger_contract_hash": sha256_json(trigger_contract()),
        "confirmation_contract_hash": sha256_json(confirmation_contract()),
        "entry_contract_hash": sha256_json(entry_contract()),
        "sl_contract_hash": sha256_json(sl_contract()),
        "target_contract_hash": sha256_json(target_contract()),
        "parameter_contract_hash": sha256_json(parameter_contract()),
        "friction_contract_hash": sha256_json(friction_contract()),
        "strategy_contract_hash": sha256_json(strategy_contract()),
    }


STRATEGY_HASH = sha256_json(strategy_contract())
