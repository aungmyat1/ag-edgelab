"""ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2 — HARDENED CONTRACT (version 2.1.0-research).

MISSION 3A. This module supersedes the 2.0.0-research prototype
(``asian_liquidity_displacement_v2.py``), which remains in the tree untouched
as closed evidence for the GEN2_ALD_V2_DEV_R1 run.

RESEARCH QUESTION (frozen, Phase 1)
-----------------------------------
"Does a dual session-liquidity mechanism solve the structural starvation of V1
without post-result threshold tuning?"

Exactly two branches. No third branch may be added.
  A = SWEEP_RECLAIM_REVERSAL
  B = BREAKOUT_RETEST_CONTINUATION

WHAT THE PROTOTYPE GOT WRONG, AND WHAT IS FIXED HERE
-----------------------------------------------------
1. CONTRACT IDENTITY WAS INCOMPLETE. The 2.0.0 hash covered a prose summary
   of the architecture, so several operative magnitudes could be edited
   without moving the hash. 2.1.0 binds every frozen field and is protected by
   mutation tests: change any frozen field, the hash MUST change.

2. NO INSTRUMENT NORMALIZATION. Distances were absolute price. That makes one
   named rule behave as four different rules across EURUSD/GBPUSD/USDJPY/
   XAUUSD. All magnitudes are now either TICK_SIZE multiples (precision
   floors) or REFERENCE-RANGE FRACTIONS (dimensionless), resolved through
   ``symbol_metadata``.

3. NO EXPLICIT TEMPORAL SEQUENCE. The prototype could satisfy sweep, reclaim
   and confirmation in ways that did not force distinct, strictly ordered
   bars. 2.1.0 runs an explicit state machine per branch; the sweep bar can
   never be the reclaim bar, and the reclaim bar can never be the MSS bar.

4. NO EVENT-LEVEL DUPLICATE GOVERNANCE. Suppression was implicit in the
   one-unit-per-session construction. 2.1.0 issues an EVENT_ID and locks it.

DESIGN CONTAMINATION DISCLOSURE — READ THIS BEFORE TRUSTING THE RESULT
-----------------------------------------------------------------------
This contract is written AFTER the GEN2_ALD_V2_DEV_R1 development replay was
observed (pooled expectancy -0.0042R, CI95 [-0.0619, +0.0550], 9/10 robustness
axes failed). That ordering is a real contamination hazard: a designer who has
seen an outcome can unconsciously select magnitudes that flatter it.

Three mitigations, all falsifiable by reading the code:

  (a) The 2.0.0 prototype had an EMPTY parameter vector. Hardening necessarily
      INTRODUCES magnitudes (``reclaim_max_bars`` and friends are mandated by
      the mission). Every one of them is derived in PARAMETER_PROVENANCE from
      a mechanism, a clock already in the contract, or a minimality argument —
      never from an outcome.
  (b) No R1 artifact was read, re-parsed, or scanned while choosing any value
      here, and no value was varied to observe its effect.
  (c) The honest consequence: results produced under this contract are a
      SECOND look at the same development data by the same researcher. They
      cannot carry the evidential weight of a first look. This is recorded in
      the preregistration as LOOK_INDEX = 2 and must be reported alongside any
      outcome.

NOT IN SCOPE: V1 optimization, threshold rescue, parameter search, OOS
validation, economic verification.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Sequence

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import canonical_json
from ag_edgelab.strategies.symbol_metadata import (
    METADATA_AUTHORITY_ID,
    SymbolMetadata,
    metadata_contract,
    metadata_for,
)

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

CANDIDATE_FAMILY_ID = "ASIAN_LIQUIDITY_DISPLACEMENT"
STRATEGY_ID = "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2"
STRATEGY_VERSION = "2.1.0-research"
STRATEGY_STATUS = "RESEARCH_CANDIDATE"
EDGE_VERIFIED = False
SUPERSEDES = "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2@2.0.0-research"
SUPERSEDED_EVIDENCE = "GEN2_ALD_V2_DEV_R1"
LOOK_INDEX = 2  # second look at the same DEV partition — see disclosure above

FORBIDDEN_IDENTITY_REUSE: tuple[str, ...] = (
    "ST_ASIAN_SWEEP_5R_V1",
    "SESSION_TRADE_V2",
    "ST_MTF_CONTROL_SHIFT_V1",
    "ST_MTF_CONTROL_SHIFT_V2",
    "TARGET_POLICY_C3_V1",
    "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1",
)

RESEARCH_QUESTION = (
    "Does a dual session-liquidity mechanism solve the structural starvation "
    "of V1 without post-result threshold tuning?"
)

# ---------------------------------------------------------------------------
# Session clocks — exogenous institutional boundaries, identical to V1 and to
# the 2.0.0 prototype so the funnel comparison keeps a common denominator.
# ---------------------------------------------------------------------------

REFERENCE_WINDOW_UTC: tuple[int, int] = (0, 6)      # Asian reference range
LONDON_ENTRY_UTC: tuple[int, int] = (7, 10)
NEW_YORK_ENTRY_UTC: tuple[int, int] = (12, 15)

SESSION_PAIRS: dict[str, tuple[int, int]] = {
    "ASIAN_LONDON": LONDON_ENTRY_UTC,
    "LONDON_NEWYORK": NEW_YORK_ENTRY_UTC,
}

M5_BARS_PER_HOUR = 12
H1_IN_M5_BARS = M5_BARS_PER_HOUR  # the clock unit all timeouts are quoted in

# ---------------------------------------------------------------------------
# Measurement contracts — inherited UNCHANGED from V1/2.0.0. Not magnitudes of
# the hypothesis; they define what is measurable, not what is traded.
# ---------------------------------------------------------------------------

MIN_REFERENCE_M15_BARS = 16
WARMUP_DAYS = 21
OUTCOME_HORIZON_M5_BARS = 288
SWING_ORDER = 2
FIXED_R_TARGETS: tuple[int, ...] = (1, 2, 3, 4, 5)   # DIAGNOSTIC ONLY

# ---------------------------------------------------------------------------
# FROZEN RULE MAGNITUDES
# Every value below is bound into CONTRACT_HASH. See PARAMETER_PROVENANCE for
# the derivation of each. None was selected by observing an outcome.
# ---------------------------------------------------------------------------

# -- Branch A: sweep / reclaim / MSS
MIN_SWEEP_TICKS = 1
MAX_SWEEP_RANGE_FRACTION = 1.0
RECLAIM_MAX_BARS = H1_IN_M5_BARS          # 12 M5 bars = 1 hour
MSS_LOOKBACK_BARS = H1_IN_M5_BARS         # 12 M5 bars = 1 hour

# -- Branch B: breakout / acceptance / retest / continuation
ACCEPTANCE_CLOSE_COUNT = 2
RETEST_MAX_BARS = H1_IN_M5_BARS           # 12 M5 bars = 1 hour
RETEST_TOLERANCE = 0.0                    # EXACT touch. No tolerance parameter.

# -- Shared geometry
MIN_NATURAL_R = 1.0
HANDOVER_MAX = 1

PARAMETER_PROVENANCE: dict[str, str] = {
    "MIN_SWEEP_TICKS": (
        "DEFINITIONAL, NOT TUNED. 1 tick is the smallest increment at which "
        "'strictly beyond the boundary' is representable in the feed. Zero "
        "would admit float noise; anything above 1 would be a magnitude "
        "choice. The minimum non-degenerate integer is the only value that "
        "encodes the definition rather than a preference."
    ),
    "MAX_SWEEP_RANGE_FRACTION": (
        "STRUCTURAL BOUNDARY, NOT TUNED. An excursion beyond the reference "
        "boundary that exceeds the ENTIRE reference range is, mechanically, "
        "no longer an interaction with that range — it is the establishment "
        "of a new one, and the reversal mechanism this branch claims does not "
        "apply. 1.0 is the natural changeover point of that argument. "
        "Dimensionless, so it is identical across all four instruments."
    ),
    "RECLAIM_MAX_BARS": (
        "CLOCK-DERIVED, NOT TUNED. Quoted as exactly one H1 (12 M5 bars). H1 "
        "is already an exogenous unit of this contract (it is the structural "
        "timeframe the target authority reads). A reclaim that takes longer "
        "than the governing structural bar is not a reclaim of the sweep, it "
        "is a separate later event."
    ),
    "MSS_LOOKBACK_BARS": (
        "CLOCK-DERIVED, NOT TUNED. One H1, same argument as RECLAIM_MAX_BARS: "
        "confirmation must belong to the same structural bar as the event it "
        "confirms."
    ),
    "ACCEPTANCE_CLOSE_COUNT": (
        "MINIMALITY, NOT TUNED. 1 close cannot distinguish acceptance from a "
        "single-print artifact, so it fails to express the concept. 2 is the "
        "smallest integer that does express it. Larger values would be "
        "preferences about conviction."
    ),
    "RETEST_MAX_BARS": (
        "CLOCK-DERIVED, NOT TUNED. One H1, same argument as above."
    ),
    "RETEST_TOLERANCE": (
        "ELIMINATED, NOT TUNED. The prototype's absolute price tolerance is "
        "removed outright: a retest is an EXACT touch of the broken level "
        "(the bar trades to or through it) while still closing on the "
        "breakout side. Zero is not a chosen magnitude — it is the absence of "
        "a parameter, which is why no instrument normalization is needed here."
    ),
    "MIN_NATURAL_R": (
        "ARITHMETIC FLOOR, NOT TUNED. A target closer than the stop cannot "
        "repay its own risk even at a 100% hit rate once any positive friction "
        "exists. 1.0 is where that arithmetic changes sign; it is not a "
        "preference about reward."
    ),
    "HANDOVER_MAX": (
        "ANTI-PING-PONG, NOT TUNED. One handover permits the single "
        "mechanically meaningful transition (a failed sweep that becomes an "
        "accepted breakout, or the reverse). Allowing more would let one "
        "boundary event generate an unbounded search for any working branch, "
        "which is selection disguised as a state machine."
    ),
}

#: The genuinely discretionary values, named explicitly so a reviewer does not
#: have to find them. Both are defended above, both are frozen, and neither may
#: be adjusted after a result is seen.
DISCRETIONARY_MAGNITUDES: tuple[str, ...] = (
    "RECLAIM_MAX_BARS / MSS_LOOKBACK_BARS / RETEST_MAX_BARS (all = 1 H1)",
    "ACCEPTANCE_CLOSE_COUNT (= 2)",
)

# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

STOP_POLICY = (
    "Branch A: the SWEEP EXTREME (the furthest price reached beyond the "
    "boundary during the sweep). Branch B: the RETEST EXTREME (the deepest "
    "point of the pullback that held). NO pip/point/ATR buffer is added, in "
    "either branch, under any circumstance. Execution buffering is a broker "
    "concern and is out of research scope."
)
ENTRY_POLICY = (
    "Entry is the CLOSE of the confirming M5 bar (branch A: the MSS bar; "
    "branch B: the continuation bar). entry_timestamp is that bar's close "
    "instant. No intrabar fill, no limit order, no improvement is modelled."
)
EXPIRY_POLICY = (
    "Every pending state is bounded by BOTH (a) its preregistered bar budget "
    "and (b) the end of the entry window, whichever comes FIRST. A state that "
    "times out is INVALIDATED with a recorded reason; it is never carried."
)
SAME_BAR_COLLISION_POLICY = "STOP_FIRST_FAIL_CLOSED_V0_3"
CENSORING_POLICY = (
    "A trade unresolved at the data boundary is RIGHT_CENSORED and reported "
    "as such. Outcomes are never imputed."
)

# ---------------------------------------------------------------------------
# FRICTION AUTHORITY BOUNDARY (Phase 8)
# ---------------------------------------------------------------------------

FRICTION_TYPE = "UNAVAILABLE"
ECONOMIC_EDGE = "NOT_ESTIMABLE"
FRICTION_POLICY = (
    "No measured broker friction authority exists for this corpus. Spread, "
    "slippage, commission and swap are UNKNOWN — and UNKNOWN IS NOT ZERO. "
    "No default, generic, broker-typical or per-lot-commission substitute "
    "may appear anywhere in the evidence bundle. Structural geometry is "
    "computed "
    "cost-independently so that it remains valid when an authority arrives. "
    "A SCENARIO friction overlay is permitted for sensitivity reporting but "
    "can NEVER establish EDGE_VERIFIED."
)
SCENARIO_FRICTION_CAN_VERIFY_EDGE = False

# ---------------------------------------------------------------------------
# FUNNEL CONTRACT (Phase 9) — ten stages, preserved exactly.
# ---------------------------------------------------------------------------

FUNNEL_TAXONOMY_VERSION = "GEN2_ALD_V2_FUNNEL_V2"
FUNNEL_STAGES: tuple[str, ...] = (
    "OPPORTUNITY",
    "CONTEXT_ELIGIBLE",
    "LOCATION_ELIGIBLE",
    "SESSION_EVENT",
    "SWEEP_OR_BREAKOUT",
    "RECLAIM_OR_RETEST",
    "STRUCTURE_CONFIRM",
    "ENTRY_AVAILABLE",
    "GEOMETRY_VALID",
    "TRADE_COMPLETED",
)
FUNNEL_REPORT_AXES: tuple[str, ...] = ("BRANCH_A", "BRANCH_B", "POOLED")


class Branch(str, Enum):
    A = "A_SWEEP_RECLAIM_REVERSAL"
    B = "B_BREAKOUT_RETEST_CONTINUATION"


class StateA(str, Enum):
    """Branch A temporal sequence. Terminal: ENTRY_AVAILABLE | INVALIDATED."""

    BOUNDARY_UNTOUCHED = "BOUNDARY_UNTOUCHED"
    SWEEP_DETECTED = "SWEEP_DETECTED"
    RECLAIM_PENDING = "RECLAIM_PENDING"
    RECLAIM_CONFIRMED = "RECLAIM_CONFIRMED"
    MSS_PENDING = "MSS_PENDING"
    MSS_CONFIRMED = "MSS_CONFIRMED"
    ENTRY_AVAILABLE = "ENTRY_AVAILABLE"
    INVALIDATED = "INVALIDATED"


class StateB(str, Enum):
    """Branch B temporal sequence. Terminal: ENTRY_AVAILABLE | INVALIDATED."""

    BOUNDARY_UNTOUCHED = "BOUNDARY_UNTOUCHED"
    BREAKOUT_DETECTED = "BREAKOUT_DETECTED"
    ACCEPTANCE_PENDING = "ACCEPTANCE_PENDING"
    ACCEPTED_BREAKOUT = "ACCEPTED_BREAKOUT"
    RETEST_PENDING = "RETEST_PENDING"
    RETEST_CONFIRMED = "RETEST_CONFIRMED"
    CONTINUATION_CONFIRMED = "CONTINUATION_CONFIRMED"
    ENTRY_AVAILABLE = "ENTRY_AVAILABLE"
    INVALIDATED = "INVALIDATED"


STATE_MACHINE_A: tuple[tuple[str, str], ...] = (
    ("BOUNDARY_UNTOUCHED", "SWEEP_DETECTED"),
    ("SWEEP_DETECTED", "RECLAIM_PENDING"),
    ("RECLAIM_PENDING", "RECLAIM_CONFIRMED"),
    ("RECLAIM_PENDING", "INVALIDATED"),
    ("RECLAIM_CONFIRMED", "MSS_PENDING"),
    ("MSS_PENDING", "MSS_CONFIRMED"),
    ("MSS_PENDING", "INVALIDATED"),
    ("MSS_CONFIRMED", "ENTRY_AVAILABLE"),
)

STATE_MACHINE_B: tuple[tuple[str, str], ...] = (
    ("BOUNDARY_UNTOUCHED", "BREAKOUT_DETECTED"),
    ("BREAKOUT_DETECTED", "ACCEPTANCE_PENDING"),
    ("ACCEPTANCE_PENDING", "ACCEPTED_BREAKOUT"),
    ("ACCEPTANCE_PENDING", "INVALIDATED"),
    ("ACCEPTED_BREAKOUT", "RETEST_PENDING"),
    ("RETEST_PENDING", "RETEST_CONFIRMED"),
    ("RETEST_PENDING", "INVALIDATED"),
    ("RETEST_CONFIRMED", "CONTINUATION_CONFIRMED"),
    ("RETEST_CONFIRMED", "INVALIDATED"),
    ("CONTINUATION_CONFIRMED", "ENTRY_AVAILABLE"),
)

#: Strict-ordering requirements. Each pair MUST occupy distinct, increasing
#: bar indices — this is what makes the sequence temporal rather than
#: coincidental, and it is asserted at runtime, not merely documented.
STRICT_ORDER_A: tuple[tuple[str, str], ...] = (
    ("sweep_index", "reclaim_index"),
    ("reclaim_index", "mss_index"),
)
STRICT_ORDER_B: tuple[tuple[str, str], ...] = (
    ("breakout_index", "acceptance_index"),
    ("acceptance_index", "retest_index"),
    ("retest_index", "continuation_index"),
)

# ---------------------------------------------------------------------------
# DUPLICATE EVENT GOVERNANCE (Phase 7)
# ---------------------------------------------------------------------------

DUPLICATE_EVENT_POLICY = (
    "One underlying session-boundary event may produce AT MOST ONE accepted "
    "trade. EVENT_ID = sha256(symbol, date, session, boundary, "
    "event_sequence). A branch handover (A invalidated -> B pending, or the "
    "reverse) is permitted at most HANDOVER_MAX times and only via the "
    "preregistered transitions. The instant a FIRST_VALID_SIGNAL exists the "
    "tuple (symbol, date, session, boundary) is LOCKED until window expiry; "
    "every later signal on that tuple is recorded as DUPLICATE_SUPPRESSED and "
    "contributes no observation."
)

PERMITTED_HANDOVERS: tuple[tuple[str, str, str], ...] = (
    ("A", "B", "RECLAIM_TIMEOUT"),
    ("A", "B", "SWEEP_GEOMETRY_EXCEEDED"),
    ("B", "A", "BREAKOUT_REJECTED_CLOSE_BACK_INSIDE"),
    ("B", "A", "ACCEPTANCE_TIMEOUT"),
)


def event_id(symbol: str, date: str, session: str, boundary: str,
             event_sequence: int) -> str:
    """Stable identity of one underlying session-boundary event."""
    payload = canonical_json({
        "symbol": symbol,
        "date": date,
        "session": session,
        "boundary": boundary,
        "event_sequence": event_sequence,
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# NATURAL TARGET AUTHORITY (Phase 6)
# ---------------------------------------------------------------------------

TARGET_AUTHORITY_ORDER: tuple[str, ...] = (
    "OPPOSITE_SESSION_BOUNDARY",
    "PRIOR_DAY_HIGH_LOW",
    "CONFIRMED_PRE_ENTRY_SWING_LIQUIDITY",
)

TARGET_POLICY = (
    "DETERMINISTIC PRIORITY, CAUSALLY CLOSED. Authorities are consulted in "
    "TARGET_AUTHORITY_ORDER and the FIRST one that yields a level strictly "
    "beyond the entry in the direction of travel wins. Selection stops there: "
    "later authorities are never consulted, so a larger target can never be "
    "shopped for. Every authority is computed from information closed at or "
    "before entry_timestamp. If no authority yields a level, "
    "TARGET_STATUS = NO_NATURAL_TARGET and GEOMETRY_VALID = FALSE — an R "
    "multiple is NEVER manufactured. NATURAL_R = |target-entry| / "
    "|entry-stop|; if NATURAL_R < MIN_NATURAL_R the unit fails geometry with "
    "NATURAL_R_BELOW_FLOOR. Note the floor is applied AFTER the authority is "
    "selected, never as a selection criterion. 1R..5R are capability "
    "diagnostics with no authority over any decision."
)

SYNTHETIC_TARGETS_FORBIDDEN = (
    "No fixed R multiple may act as a target. The 2.0.0 prototype's branch-B "
    "fallback of entry +/- 2R is abolished; absence of a natural target is an "
    "outcome (NO_NATURAL_TARGET), not a case to be filled in."
)


class TargetStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NO_NATURAL_TARGET = "NO_NATURAL_TARGET"
    BELOW_FLOOR = "NATURAL_R_BELOW_FLOOR"


@dataclass(frozen=True)
class TargetCandidate:
    """A level offered by one authority, with its causal cutoff."""

    authority: str
    level: float
    known_at: datetime


def resolve_natural_target(
    candidates: Sequence[TargetCandidate],
    *,
    entry_price: float,
    stop_price: float,
    entry_timestamp: datetime,
    direction_is_bull: bool,
) -> dict:
    """Apply the frozen target authority.

    Fails closed on any candidate that is not causally available at
    ``entry_timestamp`` — a future-derived level is a bug, not a target.
    """
    for cand in candidates:
        if cand.known_at > entry_timestamp:
            raise ValueError(
                f"target authority {cand.authority} used information known at "
                f"{cand.known_at.isoformat()}, after entry "
                f"{entry_timestamp.isoformat()} — future leakage"
            )

    by_authority = {c.authority: c for c in candidates}
    risk = abs(entry_price - stop_price)
    if risk <= 0:
        return {"status": TargetStatus.NO_NATURAL_TARGET.value,
                "reason": "GEOMETRY_RISK_NON_POSITIVE",
                "authority": None, "target": None, "natural_r": None}

    for authority in TARGET_AUTHORITY_ORDER:
        cand = by_authority.get(authority)
        if cand is None:
            continue
        beyond = (cand.level > entry_price) if direction_is_bull else (cand.level < entry_price)
        if not beyond:
            continue
        natural_r = abs(cand.level - entry_price) / risk
        if natural_r < MIN_NATURAL_R:
            return {"status": TargetStatus.BELOW_FLOOR.value,
                    "reason": "NATURAL_R_BELOW_FLOOR",
                    "authority": authority, "target": cand.level,
                    "natural_r": natural_r,
                    "min_natural_r": MIN_NATURAL_R}
        return {"status": TargetStatus.RESOLVED.value, "reason": None,
                "authority": authority, "target": cand.level,
                "natural_r": natural_r}

    return {"status": TargetStatus.NO_NATURAL_TARGET.value,
            "reason": "NO_NATURAL_TARGET", "authority": None,
            "target": None, "natural_r": None}


# ---------------------------------------------------------------------------
# Branch A state machine
# ---------------------------------------------------------------------------

@dataclass
class MachineResult:
    """Outcome of driving one branch over the entry window."""

    branch: str
    state: str
    invalidation_reason: str | None = None
    transitions: list[dict] = field(default_factory=list)
    indices: dict[str, int] = field(default_factory=dict)
    timestamps: dict[str, datetime] = field(default_factory=dict)
    entry_price: float | None = None
    stop_price: float | None = None
    direction_is_bull: bool | None = None

    def record(self, frm: str, to: str, index: int, bar: MarketBar,
               note: str | None = None) -> None:
        self.transitions.append({
            "from": frm, "to": to, "bar_index": index,
            "timestamp": bar.timestamp.isoformat(),
            "note": note,
        })
        self.state = to

    @property
    def reached_entry(self) -> bool:
        return self.state in (StateA.ENTRY_AVAILABLE.value,
                              StateB.ENTRY_AVAILABLE.value)


def _close_instant(bar: MarketBar) -> datetime:
    """M5 bars are stamped at OPEN; the decision instant is the close."""
    return bar.timestamp + timedelta(minutes=5)


def run_branch_a(
    bars: Sequence[MarketBar],
    *,
    boundary: float,
    boundary_side: str,
    reference_range: float,
    meta: SymbolMetadata,
    mss_confirmed_at,
    start_index: int = 0,
) -> MachineResult:
    """Drive BOUNDARY_UNTOUCHED -> ... -> ENTRY_AVAILABLE for branch A.

    ``boundary_side`` is "HIGH" (swept upward, expect bearish reversal) or
    "LOW" (swept downward, expect bullish reversal).
    ``mss_confirmed_at(index) -> bool`` reports whether a closed-M5 MSS/BOS in
    the reversal direction is confirmed AT that bar, using only bars closed at
    or before it. It is injected so the state machine owns sequencing and the
    frozen universal library owns structure detection.
    """
    bull = boundary_side == "LOW"
    res = MachineResult(branch=Branch.A.value, state=StateA.BOUNDARY_UNTOUCHED.value,
                        direction_is_bull=bull)

    # --- transition 1: BOUNDARY_UNTOUCHED -> SWEEP_DETECTED ---------------
    sweep_i: int | None = None
    for i in range(start_index, len(bars)):
        bar = bars[i]
        breached = bar.low < boundary if bull else bar.high > boundary
        if not breached:
            continue
        depth = (boundary - bar.low) if bull else (bar.high - boundary)
        if depth < MIN_SWEEP_TICKS * meta.tick_size:
            continue  # not beyond the boundary at machine precision
        if reference_range > 0 and depth > MAX_SWEEP_RANGE_FRACTION * reference_range:
            res.record(StateA.BOUNDARY_UNTOUCHED.value, StateA.INVALIDATED.value,
                       i, bar, "sweep deeper than the whole reference range")
            res.invalidation_reason = "SWEEP_GEOMETRY_EXCEEDED"
            return res
        sweep_i = i
        res.record(StateA.BOUNDARY_UNTOUCHED.value, StateA.SWEEP_DETECTED.value, i, bar)
        break
    if sweep_i is None:
        res.invalidation_reason = "NO_SWEEP"
        res.state = StateA.INVALIDATED.value
        return res

    sweep_bar = bars[sweep_i]
    sweep_extreme = sweep_bar.low if bull else sweep_bar.high
    res.indices["sweep_index"] = sweep_i
    res.timestamps["sweep_timestamp"] = sweep_bar.timestamp
    res.record(StateA.SWEEP_DETECTED.value, StateA.RECLAIM_PENDING.value, sweep_i, sweep_bar)

    # --- transition 2: RECLAIM_PENDING -> RECLAIM_CONFIRMED ---------------
    # STRICTLY LATER BAR: the sweep candle can never be the reclaim candle.
    reclaim_i: int | None = None
    budget_end = min(len(bars), sweep_i + 1 + RECLAIM_MAX_BARS)
    for i in range(sweep_i + 1, budget_end):
        bar = bars[i]
        # track the extreme while we wait; the stop is the furthest excursion
        sweep_extreme = min(sweep_extreme, bar.low) if bull else max(sweep_extreme, bar.high)
        depth = (boundary - sweep_extreme) if bull else (sweep_extreme - boundary)
        if reference_range > 0 and depth > MAX_SWEEP_RANGE_FRACTION * reference_range:
            res.record(StateA.RECLAIM_PENDING.value, StateA.INVALIDATED.value, i, bar)
            res.invalidation_reason = "SWEEP_GEOMETRY_EXCEEDED"
            return res
        reclaimed = bar.close > boundary if bull else bar.close < boundary
        if reclaimed:
            reclaim_i = i
            res.record(StateA.RECLAIM_PENDING.value, StateA.RECLAIM_CONFIRMED.value, i, bar)
            break
    if reclaim_i is None:
        res.state = StateA.INVALIDATED.value
        res.invalidation_reason = "RECLAIM_TIMEOUT"
        return res

    res.indices["reclaim_index"] = reclaim_i
    res.timestamps["reclaim_timestamp"] = bars[reclaim_i].timestamp
    res.record(StateA.RECLAIM_CONFIRMED.value, StateA.MSS_PENDING.value,
               reclaim_i, bars[reclaim_i])

    # --- transition 3: MSS_PENDING -> MSS_CONFIRMED -----------------------
    # STRICTLY LATER BAR: the reclaim candle can never be the MSS candle.
    mss_i: int | None = None
    budget_end = min(len(bars), reclaim_i + 1 + MSS_LOOKBACK_BARS)
    for i in range(reclaim_i + 1, budget_end):
        if mss_confirmed_at(i):
            mss_i = i
            res.record(StateA.MSS_PENDING.value, StateA.MSS_CONFIRMED.value, i, bars[i])
            break
    if mss_i is None:
        res.state = StateA.INVALIDATED.value
        res.invalidation_reason = "MSS_TIMEOUT"
        return res

    res.indices["mss_index"] = mss_i
    res.timestamps["mss_timestamp"] = bars[mss_i].timestamp
    res.timestamps["entry_timestamp"] = _close_instant(bars[mss_i])
    res.entry_price = bars[mss_i].close
    res.stop_price = sweep_extreme
    res.record(StateA.MSS_CONFIRMED.value, StateA.ENTRY_AVAILABLE.value, mss_i, bars[mss_i])
    _assert_strict_order(res, STRICT_ORDER_A)
    return res


def run_branch_b(
    bars: Sequence[MarketBar],
    *,
    boundary: float,
    boundary_side: str,
    reference_range: float,
    meta: SymbolMetadata,
    continuation_confirmed_at,
    start_index: int = 0,
) -> MachineResult:
    """Drive BOUNDARY_UNTOUCHED -> ... -> ENTRY_AVAILABLE for branch B.

    ``boundary_side`` is "HIGH" (broken upward, expect bullish continuation)
    or "LOW" (broken downward, expect bearish continuation).
    """
    bull = boundary_side == "HIGH"
    res = MachineResult(branch=Branch.B.value, state=StateB.BOUNDARY_UNTOUCHED.value,
                        direction_is_bull=bull)

    # --- transition 1: BOUNDARY_UNTOUCHED -> BREAKOUT_DETECTED ------------
    brk_i: int | None = None
    for i in range(start_index, len(bars)):
        bar = bars[i]
        beyond = bar.high > boundary if bull else bar.low < boundary
        if not beyond:
            continue
        depth = (bar.high - boundary) if bull else (boundary - bar.low)
        if depth < MIN_SWEEP_TICKS * meta.tick_size:
            continue
        brk_i = i
        res.record(StateB.BOUNDARY_UNTOUCHED.value, StateB.BREAKOUT_DETECTED.value, i, bar)
        break
    if brk_i is None:
        res.invalidation_reason = "NO_BREAKOUT"
        res.state = StateB.INVALIDATED.value
        return res

    res.indices["breakout_index"] = brk_i
    res.timestamps["breakout_timestamp"] = bars[brk_i].timestamp
    res.record(StateB.BREAKOUT_DETECTED.value, StateB.ACCEPTANCE_PENDING.value,
               brk_i, bars[brk_i])

    # --- transition 2: ACCEPTANCE_PENDING -> ACCEPTED_BREAKOUT ------------
    # ACCEPTANCE_CLOSE_COUNT consecutive closes beyond the broken level.
    # Acceptance must complete BEFORE any retest is considered.
    accept_i: int | None = None
    streak = 0
    budget_end = min(len(bars), brk_i + 1 + RETEST_MAX_BARS)
    for i in range(brk_i, budget_end):
        bar = bars[i]
        closed_beyond = bar.close > boundary if bull else bar.close < boundary
        if closed_beyond:
            streak += 1
            if streak >= ACCEPTANCE_CLOSE_COUNT:
                accept_i = i
                res.record(StateB.ACCEPTANCE_PENDING.value,
                           StateB.ACCEPTED_BREAKOUT.value, i, bar,
                           f"{streak} consecutive closes beyond")
                break
        else:
            streak = 0
    if accept_i is None:
        res.state = StateB.INVALIDATED.value
        res.invalidation_reason = "ACCEPTANCE_TIMEOUT"
        return res

    res.indices["acceptance_index"] = accept_i
    res.timestamps["acceptance_timestamp"] = bars[accept_i].timestamp
    res.record(StateB.ACCEPTED_BREAKOUT.value, StateB.RETEST_PENDING.value,
               accept_i, bars[accept_i])

    # --- transition 3: RETEST_PENDING -> RETEST_CONFIRMED -----------------
    # STRICTLY AFTER ACCEPTANCE. Exact touch of the broken level, with the
    # bar still closing on the breakout side. No tolerance parameter exists.
    retest_i: int | None = None
    retest_extreme: float | None = None
    budget_end = min(len(bars), accept_i + 1 + RETEST_MAX_BARS)
    for i in range(accept_i + 1, budget_end):
        bar = bars[i]
        closed_back_inside = bar.close < boundary if bull else bar.close > boundary
        if closed_back_inside:
            res.record(StateB.RETEST_PENDING.value, StateB.INVALIDATED.value, i, bar)
            res.invalidation_reason = "BREAKOUT_REJECTED_CLOSE_BACK_INSIDE"
            return res
        touched = bar.low <= boundary + RETEST_TOLERANCE if bull else \
            bar.high >= boundary - RETEST_TOLERANCE
        if touched:
            retest_i = i
            retest_extreme = bar.low if bull else bar.high
            res.record(StateB.RETEST_PENDING.value, StateB.RETEST_CONFIRMED.value, i, bar)
            break
    if retest_i is None:
        res.state = StateB.INVALIDATED.value
        res.invalidation_reason = "RETEST_TIMEOUT"
        return res

    res.indices["retest_index"] = retest_i
    res.timestamps["retest_timestamp"] = bars[retest_i].timestamp

    # --- transition 4: RETEST_CONFIRMED -> CONTINUATION_CONFIRMED ---------
    cont_i: int | None = None
    budget_end = min(len(bars), retest_i + 1 + MSS_LOOKBACK_BARS)
    for i in range(retest_i + 1, budget_end):
        bar = bars[i]
        retest_extreme = min(retest_extreme, bar.low) if bull else max(retest_extreme, bar.high)
        if continuation_confirmed_at(i):
            cont_i = i
            res.record(StateB.RETEST_CONFIRMED.value,
                       StateB.CONTINUATION_CONFIRMED.value, i, bar)
            break
    if cont_i is None:
        res.state = StateB.INVALIDATED.value
        res.invalidation_reason = "CONTINUATION_TIMEOUT"
        return res

    res.indices["continuation_index"] = cont_i
    res.timestamps["continuation_timestamp"] = bars[cont_i].timestamp
    res.timestamps["entry_timestamp"] = _close_instant(bars[cont_i])
    res.entry_price = bars[cont_i].close
    res.stop_price = retest_extreme
    res.record(StateB.CONTINUATION_CONFIRMED.value, StateB.ENTRY_AVAILABLE.value,
               cont_i, bars[cont_i])
    _assert_strict_order(res, STRICT_ORDER_B)
    return res


def _assert_strict_order(res: MachineResult,
                         pairs: Sequence[tuple[str, str]]) -> None:
    """Fail closed if any mandated pair shares a bar or runs backwards."""
    for earlier, later in pairs:
        a, b = res.indices.get(earlier), res.indices.get(later)
        if a is None or b is None:
            continue
        if not a < b:
            raise AssertionError(
                f"{res.branch}: {earlier}={a} must be STRICTLY before "
                f"{later}={b} — the same bar cannot satisfy two transitions"
            )


# ---------------------------------------------------------------------------
# CANONICAL CONTRACT IDENTITY (Phase 2)
# ---------------------------------------------------------------------------

def identity_contract() -> dict:
    return {
        "candidate_family_id": CANDIDATE_FAMILY_ID,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "strategy_status": STRATEGY_STATUS,
        "edge_verified": EDGE_VERIFIED,
        "supersedes": SUPERSEDES,
        "superseded_evidence": SUPERSEDED_EVIDENCE,
        "look_index": LOOK_INDEX,
        "research_question": RESEARCH_QUESTION,
        "forbidden_identity_reuse": list(FORBIDDEN_IDENTITY_REUSE),
    }


def session_contract() -> dict:
    return {
        "reference_window_utc": list(REFERENCE_WINDOW_UTC),
        "london_entry_utc": list(LONDON_ENTRY_UTC),
        "new_york_entry_utc": list(NEW_YORK_ENTRY_UTC),
        "session_pairs": {k: list(v) for k, v in sorted(SESSION_PAIRS.items())},
        "min_reference_m15_bars": MIN_REFERENCE_M15_BARS,
        "warmup_days": WARMUP_DAYS,
        "outcome_horizon_m5_bars": OUTCOME_HORIZON_M5_BARS,
        "swing_order": SWING_ORDER,
        "clock_note": (
            "Exogenous institutional boundaries. Never widened, shifted or "
            "searched in response to an observed result."
        ),
    }


def branch_a_contract() -> dict:
    return {
        "branch_id": Branch.A.value,
        "mechanism": (
            "A boundary of the reference range is swept — liquidity resting "
            "beyond it is taken — and price then CLOSES back inside the "
            "range, evidencing a failed auction. The reversal is traded "
            "against the sweep, confirmed by a market-structure shift."
        ),
        "sweep_definition": (
            "An M5 bar trades beyond the reference boundary by at least "
            "MIN_SWEEP_TICKS ticks. Wick-only penetration qualifies: the "
            "sweep is about liquidity taken, not about the close."
        ),
        "min_sweep_geometry": {"ticks": MIN_SWEEP_TICKS,
                               "unit": "instrument TICK_SIZE"},
        "max_sweep_geometry": {"reference_range_fraction": MAX_SWEEP_RANGE_FRACTION,
                               "unit": "dimensionless fraction of the reference range"},
        "reclaim_definition": (
            "A STRICTLY LATER M5 bar CLOSES back inside the reference range "
            "(beyond the boundary in the returning direction)."
        ),
        "reclaim_max_bars": RECLAIM_MAX_BARS,
        "mss_definition": (
            "The first closed-M5 market-structure shift / break of structure "
            "in the reversal direction, detected by the frozen universal "
            "confirmation library using only bars closed at or before it."
        ),
        "mss_lookback_bars": MSS_LOOKBACK_BARS,
        "entry_definition": "Close of the confirming MSS bar.",
        "stop_definition": "Sweep extreme — furthest excursion beyond the boundary. No buffer.",
        "expiration": (
            "min(bar budget of the pending state, end of the entry window). "
            "Timeout is INVALIDATION with a recorded reason."
        ),
        "state_machine": [list(t) for t in STATE_MACHINE_A],
        "strict_order": [list(p) for p in STRICT_ORDER_A],
    }


def branch_b_contract() -> dict:
    return {
        "branch_id": Branch.B.value,
        "mechanism": (
            "A boundary of the reference range is broken and ACCEPTED — "
            "consecutive closes beyond it evidence that the level has flipped "
            "polarity. A pullback retests the broken level, holds, and the "
            "move continues."
        ),
        "breakout_definition": (
            "An M5 bar trades beyond the reference boundary by at least "
            "MIN_SWEEP_TICKS ticks."
        ),
        "acceptance_close_count": ACCEPTANCE_CLOSE_COUNT,
        "acceptance_definition": (
            f"{ACCEPTANCE_CLOSE_COUNT} CONSECUTIVE M5 closes beyond the broken "
            "level. Acceptance must COMPLETE before any retest is considered."
        ),
        "retest_definition": (
            "A STRICTLY LATER bar than acceptance whose extreme touches or "
            "crosses the broken level (EXACT touch — there is no tolerance "
            "parameter) while the bar still CLOSES on the breakout side."
        ),
        "retest_tolerance": RETEST_TOLERANCE,
        "retest_tolerance_note": (
            "Zero by construction: the absolute price tolerance of the 2.0.0 "
            "prototype is removed, not re-scaled."
        ),
        "retest_max_bars": RETEST_MAX_BARS,
        "continuation_confirmation": (
            "The first closed-M5 market-structure shift / break of structure "
            "in the breakout direction after the retest."
        ),
        "continuation_lookback_bars": MSS_LOOKBACK_BARS,
        "entry_definition": "Close of the confirming continuation bar.",
        "stop_definition": "Retest extreme — deepest point of the pullback that held. No buffer.",
        "invalidation": (
            "A close back inside the range at any point after acceptance "
            "invalidates the branch (BREAKOUT_REJECTED_CLOSE_BACK_INSIDE)."
        ),
        "expiration": (
            "min(bar budget of the pending state, end of the entry window)."
        ),
        "state_machine": [list(t) for t in STATE_MACHINE_B],
        "strict_order": [list(p) for p in STRICT_ORDER_B],
    }


def target_contract() -> dict:
    return {
        "authority_order": list(TARGET_AUTHORITY_ORDER),
        "policy": TARGET_POLICY,
        "min_natural_r": MIN_NATURAL_R,
        "natural_r_definition": "abs(target - entry) / abs(entry - stop)",
        "synthetic_targets_forbidden": SYNTHETIC_TARGETS_FORBIDDEN,
        "fixed_r_targets_are_diagnostic_only": list(FIXED_R_TARGETS),
        "causality_rule": (
            "Every candidate level carries the instant it became known; a "
            "level known after entry_timestamp raises rather than resolves."
        ),
    }


def governance_contract() -> dict:
    return {
        "duplicate_event_policy": DUPLICATE_EVENT_POLICY,
        "event_id_inputs": ["symbol", "date", "session", "boundary", "event_sequence"],
        "permitted_handovers": [list(h) for h in PERMITTED_HANDOVERS],
        "handover_max": HANDOVER_MAX,
        "stop_policy": STOP_POLICY,
        "entry_policy": ENTRY_POLICY,
        "expiry_policy": EXPIRY_POLICY,
        "same_bar_collision_policy": SAME_BAR_COLLISION_POLICY,
        "censoring_policy": CENSORING_POLICY,
    }


def friction_contract() -> dict:
    return {
        "friction_type": FRICTION_TYPE,
        "economic_edge": ECONOMIC_EDGE,
        "policy": FRICTION_POLICY,
        "scenario_friction_can_verify_edge": SCENARIO_FRICTION_CAN_VERIFY_EDGE,
        "unknown_is_not_zero": True,
    }


def funnel_contract() -> dict:
    return {
        "taxonomy_version": FUNNEL_TAXONOMY_VERSION,
        "stages": list(FUNNEL_STAGES),
        "report_axes": list(FUNNEL_REPORT_AXES),
        "per_transition_metrics": ["N", "PCT_OF_PREVIOUS_STAGE", "PCT_OF_OPPORTUNITIES"],
    }


def parameter_contract() -> dict:
    """Every frozen rule magnitude, with its derivation."""
    return {
        "values": {
            "MIN_SWEEP_TICKS": MIN_SWEEP_TICKS,
            "MAX_SWEEP_RANGE_FRACTION": MAX_SWEEP_RANGE_FRACTION,
            "RECLAIM_MAX_BARS": RECLAIM_MAX_BARS,
            "MSS_LOOKBACK_BARS": MSS_LOOKBACK_BARS,
            "ACCEPTANCE_CLOSE_COUNT": ACCEPTANCE_CLOSE_COUNT,
            "RETEST_MAX_BARS": RETEST_MAX_BARS,
            "RETEST_TOLERANCE": RETEST_TOLERANCE,
            "MIN_NATURAL_R": MIN_NATURAL_R,
            "HANDOVER_MAX": HANDOVER_MAX,
        },
        "provenance": dict(sorted(PARAMETER_PROVENANCE.items())),
        "discretionary_magnitudes": list(DISCRETIONARY_MAGNITUDES),
        "optimization_performed": False,
        "selected_by_observing_outcome": False,
    }


def strategy_contract() -> dict:
    """THE frozen contract. Everything that defines the hypothesis."""
    return {
        "identity": identity_contract(),
        "session": session_contract(),
        "branch_a": branch_a_contract(),
        "branch_b": branch_b_contract(),
        "target": target_contract(),
        "governance": governance_contract(),
        "friction": friction_contract(),
        "funnel": funnel_contract(),
        "parameters": parameter_contract(),
        "symbol_metadata": metadata_contract(),
        "symbol_metadata_authority": METADATA_AUTHORITY_ID,
    }


def contract_hash() -> str:
    """Deterministic canonical identity of the frozen contract."""
    return hashlib.sha256(
        canonical_json(strategy_contract()).encode("utf-8")
    ).hexdigest()


def contract_hashes() -> dict[str, str]:
    """Per-section hashes, so a diff localises what moved."""
    c = strategy_contract()
    out = {
        f"{section}_hash": hashlib.sha256(
            canonical_json(body).encode("utf-8")).hexdigest()
        for section, body in sorted(c.items())
        if isinstance(body, dict)
    }
    out["contract_hash"] = contract_hash()
    return out


#: The frozen fields a mutation test must cover. Changing ANY of these MUST
#: move CONTRACT_HASH; ``tests/test_gen2_ald_v2_1.py`` proves it field by field.
FROZEN_FIELDS: tuple[str, ...] = (
    "STRATEGY_ID", "STRATEGY_VERSION", "LOOK_INDEX",
    "REFERENCE_WINDOW_UTC", "LONDON_ENTRY_UTC", "NEW_YORK_ENTRY_UTC",
    "MIN_REFERENCE_M15_BARS", "WARMUP_DAYS", "OUTCOME_HORIZON_M5_BARS",
    "SWING_ORDER",
    "MIN_SWEEP_TICKS", "MAX_SWEEP_RANGE_FRACTION", "RECLAIM_MAX_BARS",
    "MSS_LOOKBACK_BARS", "ACCEPTANCE_CLOSE_COUNT", "RETEST_MAX_BARS",
    "RETEST_TOLERANCE", "MIN_NATURAL_R", "HANDOVER_MAX",
    "TARGET_AUTHORITY_ORDER", "FUNNEL_STAGES", "FUNNEL_TAXONOMY_VERSION",
    "STATE_MACHINE_A", "STATE_MACHINE_B", "PERMITTED_HANDOVERS",
    "FRICTION_TYPE", "ECONOMIC_EDGE",
    "STOP_POLICY", "ENTRY_POLICY", "EXPIRY_POLICY",
    "SYMBOL_METADATA",
)

CONTRACT_HASH = contract_hash()


# ---------------------------------------------------------------------------
# EVENT REGISTRY — the executable half of DUPLICATE_EVENT_POLICY
# ---------------------------------------------------------------------------

@dataclass
class EventRecord:
    """Everything the funnel must be able to say about one boundary event."""

    event_id: str
    symbol: str
    date: str
    session: str
    boundary: str
    event_sequence: int
    branch_first_detected: str | None = None
    branch_selected: str | None = None
    branch_invalidation_reason: dict[str, str] = field(default_factory=dict)
    handovers: list[dict] = field(default_factory=list)
    duplicate_suppressed: int = 0
    locked: bool = False

    def as_row(self) -> dict:
        return {
            "EVENT_ID": self.event_id,
            "symbol": self.symbol,
            "date": self.date,
            "session": self.session,
            "boundary": self.boundary,
            "event_sequence": self.event_sequence,
            "BRANCH_FIRST_DETECTED": self.branch_first_detected,
            "BRANCH_SELECTED": self.branch_selected,
            "BRANCH_INVALIDATION_REASON": dict(sorted(
                self.branch_invalidation_reason.items())),
            "HANDOVERS": list(self.handovers),
            "DUPLICATE_SUPPRESSED": self.duplicate_suppressed,
            "LOCKED": self.locked,
        }


class EventRegistry:
    """Enforces: one underlying boundary event -> at most one accepted trade."""

    def __init__(self) -> None:
        self._events: dict[str, EventRecord] = {}
        #: (symbol, date, session, boundary) -> event_id holding the lock
        self._locks: dict[tuple[str, str, str, str], str] = {}

    # -- lifecycle --------------------------------------------------------
    def open_event(self, symbol: str, date: str, session: str, boundary: str,
                   event_sequence: int) -> EventRecord:
        eid = event_id(symbol, date, session, boundary, event_sequence)
        rec = self._events.get(eid)
        if rec is None:
            rec = EventRecord(event_id=eid, symbol=symbol, date=date,
                              session=session, boundary=boundary,
                              event_sequence=event_sequence)
            self._events[eid] = rec
        return rec

    def lock_key(self, rec: EventRecord) -> tuple[str, str, str, str]:
        return (rec.symbol, rec.date, rec.session, rec.boundary)

    def is_locked(self, rec: EventRecord) -> bool:
        return self.lock_key(rec) in self._locks

    # -- branch bookkeeping -----------------------------------------------
    def note_detection(self, rec: EventRecord, branch: str) -> None:
        if rec.branch_first_detected is None:
            rec.branch_first_detected = branch

    def note_invalidation(self, rec: EventRecord, branch: str, reason: str) -> None:
        rec.branch_invalidation_reason[branch] = reason

    def may_hand_over(self, rec: EventRecord, frm: str, to: str,
                      reason: str) -> bool:
        """Is this A<->B handover one of the preregistered transitions?"""
        if len(rec.handovers) >= HANDOVER_MAX:
            return False
        short = {Branch.A.value: "A", Branch.B.value: "B"}
        key = (short.get(frm, frm), short.get(to, to), reason)
        return key in PERMITTED_HANDOVERS

    def record_handover(self, rec: EventRecord, frm: str, to: str,
                        reason: str) -> None:
        if not self.may_hand_over(rec, frm, to, reason):
            raise AssertionError(
                f"handover {frm}->{to} on {reason} is not preregistered "
                f"(or HANDOVER_MAX={HANDOVER_MAX} already spent)"
            )
        rec.handovers.append({"from": frm, "to": to, "reason": reason})

    # -- the gate ---------------------------------------------------------
    def accept_signal(self, rec: EventRecord, branch: str) -> bool:
        """Register a valid signal. False means DUPLICATE_SUPPRESSED.

        The first valid signal on a (symbol, date, session, boundary) tuple
        locks it; every later signal on that tuple is suppressed and counted.
        """
        key = self.lock_key(rec)
        if key in self._locks:
            rec.duplicate_suppressed += 1
            return False
        self._locks[key] = rec.event_id
        rec.locked = True
        rec.branch_selected = branch
        return True

    def release(self, rec: EventRecord) -> None:
        """Window expiry / daily reset."""
        self._locks.pop(self.lock_key(rec), None)
        rec.locked = False

    # -- reporting --------------------------------------------------------
    def rows(self) -> list[dict]:
        return [r.as_row() for _, r in sorted(self._events.items())]

    @property
    def accepted_n(self) -> int:
        return sum(1 for r in self._events.values() if r.branch_selected)

    @property
    def suppressed_n(self) -> int:
        return sum(r.duplicate_suppressed for r in self._events.values())


def can_scenario_friction_verify_edge() -> bool:
    """Structural answer to 'may a SCENARIO overlay establish EDGE_VERIFIED?'"""
    return SCENARIO_FRICTION_CAN_VERIFY_EDGE  # frozen False


def economic_claim() -> dict:
    """The only economic statement this contract is permitted to make."""
    return {
        "FRICTION_TYPE": FRICTION_TYPE,
        "ECONOMIC_EDGE": ECONOMIC_EDGE,
        "EDGE_VERIFIED": EDGE_VERIFIED,
        "spread": "UNKNOWN",
        "slippage": "UNKNOWN",
        "commission": "UNKNOWN",
        "swap": "UNKNOWN",
        "note": "UNKNOWN is not zero; no substitute default is permitted.",
    }
