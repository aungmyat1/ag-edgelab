"""CAUSAL_ENTRY_GEOMETRY_MASK_V1 — the frozen causal parent mask (PHASE B2).

Semantics
---------
The mask may use only information available at or before ``decision_ts``
(T2 = confirmation M5 close).

Conceptually permitted inputs (each must carry ``available_at <= T2``):

* S1 context (reference window bars/range)
* S2 location (premium/discount, multi-timeframe structure strata)
* S3 session event (boundary interaction bar)
* S4 branch / direction (M15 interaction bar close)
* S5 reclaim / retest
* S6 confirmation (confirming M5 bar close)
* entry time and price known at T2 (confirmation close)
* stop geometry known at T2 (protective extreme from bars closed <= T2)
* target / reference geometry causally known at T2 (e.g. liquidity levels
  from H1 bars closed at or before T2)

Forbidden inputs — supplying them raises :class:`MaskInputForbidden`:

* future-bar existence checks (S7 ``NO_FORWARD_BARS`` forward availability)
* right-censor status (S9 ``RIGHT_CENSORED_DATA_BOUNDARY``)
* S9 completion
* MFE / MAE / realized outcome
* future fill knowledge
* any post-entry outcome availability

Implementation note (review finding, PR #24): the frozen ALD V2 replay
assigns ``unit.entry/stop/risk/target`` only AFTER the S7 forward-bar
availability gate, so those stored fields are absent for a confirmed unit
at a data boundary and their presence otherwise encodes that forward bars
existed.  This mask therefore NEVER reads those fields: geometry is
re-derived from genuinely pre-T2 inputs — the confirmation bar close, the
branch's protective extreme bar, the opposite reference boundary, and H1
liquidity pools closed at or before T2 — using the frozen strategy's own
helper functions.  For units that did pass S8 the derived values must
equal the stored ones; the freeze audit asserts that equivalence.

The historical ``row.all_rules_pass`` funnel flag is NOT this mask: it
requires S9 completion, which is post-entry outcome information.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Mapping, Sequence

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fx_histdata_2017 import bars_closed_at
from ag_edgelab.optimization.causal_time import (
    CausalFact, LookaheadViolation, M15_BAR_DURATION, M5_BAR_DURATION,
    assert_available_at_or_before, require_aware_utc, t1_direction_available,
    t2_decision_time,
)
from ag_edgelab.strategies.asian_liquidity_displacement_v2 import (
    SWING_ORDER, liquidity_levels,
)
from ag_edgelab.universal.location import LocationSide

CAUSAL_MASK_ID = "CAUSAL_ENTRY_GEOMETRY_MASK_V1"
MASK_SCHEMA_VERSION = "CAUSAL_ENTRY_GEOMETRY_MASK_V1_SCHEMA"

# Stage facts the mask consumes.  S7 (entry forward availability) and S9
# (trade completion / outcome) are deliberately absent.
MASK_STAGE_FACTS: tuple[str, ...] = (
    "S1_CONTEXT_ELIGIBLE",
    "S2_LOCATION_ELIGIBLE",
    "S3_SESSION_EVENT",
    "S4_SWEEP_OR_BREAKOUT",
    "S5_RECLAIM_OR_RETEST",
    "S6_STRUCTURE_CONFIRM",
)

MASK_GEOMETRY_FACTS: tuple[str, ...] = (
    "ENTRY_PRICE_KNOWN",
    "STOP_PRICE_KNOWN",
    "TARGET_PRICE_KNOWN",
    "RISK_POSITIVE",
    "TARGET_BEYOND_ENTRY",
    "TEMPORAL_ORDER_VALID",
)

# Substrings that identify forbidden (post-entry / future availability) fact
# names.  Supplying any fact whose name matches is a hard error.
FORBIDDEN_FACT_NAME_PATTERNS: tuple[str, ...] = (
    "S9",
    "OUTCOME",
    "REALISED",
    "REALIZED",
    "MFE",
    "MAE",
    "FORWARD_BARS",
    "FORWARD_AVAILABILITY",
    "RIGHT_CENSOR",
    "RESOLUTION",
    "STOPPED",
    "REACHED",
    "FILL",
)


class MaskInputForbidden(RuntimeError):
    """The mask was offered a forbidden future/outcome input."""


class CausalGeometryUnavailable(RuntimeError):
    """The bars needed to derive causal geometry at T2 were not supplied."""


@dataclass(frozen=True)
class CausalGeometry:
    """Entry geometry derived strictly from bars closed at or before T2."""

    entry: float | None
    stop: float | None
    target: float | None
    decision_ts: datetime


def _bar_at(bars: Sequence[MarketBar], open_time: datetime) -> MarketBar | None:
    index = bisect_left(bars, open_time, key=lambda bar: bar.timestamp)
    if index < len(bars) and bars[index].timestamp == open_time:
        return bars[index]
    return None


def derive_causal_geometry(unit, *, m5: Sequence[MarketBar],
                           m15: Sequence[MarketBar],
                           h1: Sequence[MarketBar]) -> CausalGeometry:
    """Re-derive ALD V2 entry geometry from pre-T2 inputs only.

    * entry   = close of the confirming M5 bar (known at T2);
    * stop    = branch A: the interaction M15 bar's raid-side extreme;
                branch B: the retest M5 bar's held-side extreme;
    * target  = branch A: the opposite reference boundary; branch B: the
                nearest closed-H1 liquidity pool beyond entry (H1 bars
                closed at or before T2, exactly the frozen S8 rule).
    """
    if not unit.passed("S6_STRUCTURE_CONFIRM") or unit.confirm_time is None:
        raise ValueError("causal geometry requires a confirmed unit")
    confirm_open = datetime.fromisoformat(unit.confirm_time)
    t2 = t2_decision_time(confirm_open)
    confirm_bar = _bar_at(m5, confirm_open)
    if confirm_bar is None:
        return CausalGeometry(None, None, None, t2)
    entry = confirm_bar.close

    stop: float | None
    if unit.branch == "A_SWEEP_RECLAIM_REVERSAL":
        event_bar = _bar_at(m15, datetime.fromisoformat(unit.event_time)) \
            if unit.event_time else None
        if event_bar is None or unit.boundary_side not in ("UPPER", "LOWER"):
            return CausalGeometry(entry, None, None, t2)
        stop = event_bar.high if unit.boundary_side == "UPPER" else event_bar.low
        target = (unit.reference_low if unit.direction == "BEAR"
                  else unit.reference_high) if unit.reference_high is not None \
            and unit.reference_low is not None else None
    elif unit.branch == "B_BREAKOUT_RETEST_CONTINUATION":
        retest_bar = _bar_at(m5, datetime.fromisoformat(unit.reclaim_or_retest_time)) \
            if unit.reclaim_or_retest_time else None
        if retest_bar is None or unit.direction not in ("BULL", "BEAR"):
            return CausalGeometry(entry, None, None, t2)
        stop = retest_bar.low if unit.direction == "BULL" else retest_bar.high
        # Frozen S8 branch-B rule: pools from H1 bars CLOSED at or before T2.
        h1_at_entry = bars_closed_at(tuple(h1), "H1", t2)
        target = None
        if h1_at_entry:
            zones = liquidity_levels(h1_at_entry, "H1", SWING_ORDER)
            if unit.direction == "BULL":
                candidates = [zone.zone_low for zone in zones
                              if zone.side is LocationSide.RESISTANCE
                              and zone.zone_low > entry]
                target = min(candidates) if candidates else None
            else:
                candidates = [zone.zone_high for zone in zones
                              if zone.side is LocationSide.SUPPORT
                              and zone.zone_high < entry]
                target = max(candidates) if candidates else None
    else:
        return CausalGeometry(entry, None, None, t2)
    return CausalGeometry(entry, stop, target, t2)


@dataclass(frozen=True)
class CausalMaskResult:
    mask_id: str
    opportunity_id: str
    decision_ts: datetime | None
    eligible: bool
    reason_code: str
    fact_audit: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def mask_uses_post_entry_data(self) -> bool:
        return False

    @property
    def mask_uses_s9(self) -> bool:
        return False


def _validate_fact_names(facts: Mapping[str, CausalFact]) -> None:
    for name in facts:
        for pattern in FORBIDDEN_FACT_NAME_PATTERNS:
            if pattern in name:
                raise MaskInputForbidden(
                    f"fact {name!r} is forbidden: {CAUSAL_MASK_ID} may not "
                    "consume post-entry or future-availability information")


def evaluate_causal_entry_geometry_mask(
    *,
    opportunity_id: str,
    facts: Mapping[str, CausalFact],
    decision_ts: datetime,
) -> CausalMaskResult:
    """Evaluate CAUSAL_ENTRY_GEOMETRY_MASK_V1 from causal facts only.

    ``decision_ts`` is T2 (confirmation M5 close).  Every stage and geometry
    fact must be present, PASS, and satisfy ``available_at <= decision_ts``.
    Any missing stage fact, failed stage, failed geometry predicate, or
    lookahead violation makes the opportunity mask-ineligible with an exact
    reason code.
    """
    require_aware_utc(decision_ts, "decision_ts")
    _validate_fact_names(facts)
    # EVERY fact offered to the mask — required or supplementary — must be
    # available at or before the decision timestamp.  A supplementary fact
    # with future availability is just as much lookahead as a stage fact.
    for name, fact in facts.items():
        assert_available_at_or_before(fact, decision_ts)
    audit: list[tuple[str, str]] = []

    def fail(reason: str) -> CausalMaskResult:
        return CausalMaskResult(CAUSAL_MASK_ID, opportunity_id, decision_ts,
                                False, reason, tuple(audit))

    for name in MASK_STAGE_FACTS:
        fact = facts.get(name)
        if fact is None:
            audit.append((name, "MISSING"))
            return fail(f"MASK_MISSING_FACT:{name}")
        try:
            assert_available_at_or_before(fact, decision_ts)
        except LookaheadViolation:
            audit.append((name, "LOOKAHEAD"))
            raise
        passed = fact.value is True
        audit.append((name, "PASS" if passed else "FAIL"))
        if not passed:
            return fail(f"MASK_STAGE_FAILED:{name}")

    for name in MASK_GEOMETRY_FACTS:
        fact = facts.get(name)
        if fact is None:
            audit.append((name, "MISSING"))
            return fail(f"MASK_MISSING_FACT:{name}")
        try:
            assert_available_at_or_before(fact, decision_ts)
        except LookaheadViolation:
            audit.append((name, "LOOKAHEAD"))
            raise
        passed = fact.value is True
        audit.append((name, "PASS" if passed else "FAIL"))
        if not passed:
            return fail(f"MASK_GEOMETRY_FAILED:{name}")

    return CausalMaskResult(CAUSAL_MASK_ID, opportunity_id, decision_ts,
                            True, "CAUSAL_ENTRY_GEOMETRY_PASS", tuple(audit))


def causal_mask_facts_from_v2_unit(unit, *, m5: Sequence[MarketBar],
                                   m15: Sequence[MarketBar],
                                   h1: Sequence[MarketBar]) -> dict[str, CausalFact]:
    """Build the mask fact set from a frozen ALD V2 ``V2Unit`` plus bars.

    Stage facts come from the unit's recorded pre-T2 stage outcomes.
    Geometry facts are DERIVED from bars closed at or before T2 (see
    :func:`derive_causal_geometry`); the S7-populated ``entry/stop/risk/
    target`` fields are never read, so a confirmed unit at a data boundary
    (no forward M5 bars) is judged exactly like any other confirmed unit.
    Outcome fields are likewise never read.

    Availability times (conservative upper bounds of true knowability):

    * S1/S2 reference-window facts: T0 (event M15 bar open).  The reference
      window closes at 06:00 UTC, before the entry window opens.
    * S3 event / S4 branch+direction: T1 (event M15 bar close).
    * S5 reclaim/retest: the reclaim/retest bar close.
    * S6 confirmation, entry, stop, target, risk: T2 (confirmation close).
    """
    if not unit.passed("S6_STRUCTURE_CONFIRM") or unit.confirm_time is None:
        # No confirmation: no decision timestamp exists.  The mask is not
        # evaluable; the caller records the unit as a non-parent baseline
        # opportunity carrying the frozen causal reject reason.
        raise ValueError("mask facts require a confirmed unit")

    event_open = datetime.fromisoformat(unit.event_time)
    t1 = t1_direction_available(event_open)
    confirm_open = datetime.fromisoformat(unit.confirm_time)
    t2 = t2_decision_time(confirm_open)

    # Branch A reclaims on an M15 bar close (+15 min); branch B retests on
    # an M5 bar close (+5 min).  Both bar families stamp OPEN times.
    reclaim_bar_duration = (M15_BAR_DURATION if unit.branch == "A_SWEEP_RECLAIM_REVERSAL"
                            else M5_BAR_DURATION)
    reclaim_available = (t1 if unit.reclaim_or_retest_time is None
                         else datetime.fromisoformat(unit.reclaim_or_retest_time) + reclaim_bar_duration)
    if reclaim_available > t2:
        reclaim_available = t2

    geometry = derive_causal_geometry(unit, m5=m5, m15=m15, h1=h1)
    entry_known = geometry.entry is not None
    stop_known = geometry.stop is not None
    risk_positive = (entry_known and stop_known
                     and abs(geometry.entry - geometry.stop) > 0)  # type: ignore[operator]
    target_known = geometry.target is not None
    beyond = False
    if entry_known and target_known and unit.direction in ("BULL", "BEAR"):
        beyond = ((geometry.target > geometry.entry) if unit.direction == "BULL"
                  else (geometry.target < geometry.entry))
    order_ok = bool(unit.event_time and unit.reclaim_or_retest_time and unit.confirm_time
                    and unit.event_time <= unit.reclaim_or_retest_time <= unit.confirm_time)

    return {
        "S1_CONTEXT_ELIGIBLE": CausalFact("S1_CONTEXT_ELIGIBLE", unit.passed("S1_CONTEXT_ELIGIBLE"), event_open),
        "S2_LOCATION_ELIGIBLE": CausalFact("S2_LOCATION_ELIGIBLE", unit.passed("S2_LOCATION_ELIGIBLE"), event_open),
        "S3_SESSION_EVENT": CausalFact("S3_SESSION_EVENT", unit.passed("S3_SESSION_EVENT"), t1),
        "S4_SWEEP_OR_BREAKOUT": CausalFact("S4_SWEEP_OR_BREAKOUT", unit.passed("S4_SWEEP_OR_BREAKOUT"), t1),
        "S5_RECLAIM_OR_RETEST": CausalFact("S5_RECLAIM_OR_RETEST", unit.passed("S5_RECLAIM_OR_RETEST"), reclaim_available),
        "S6_STRUCTURE_CONFIRM": CausalFact("S6_STRUCTURE_CONFIRM", unit.passed("S6_STRUCTURE_CONFIRM"), t2),
        "ENTRY_PRICE_KNOWN": CausalFact("ENTRY_PRICE_KNOWN", entry_known, t2),
        "STOP_PRICE_KNOWN": CausalFact("STOP_PRICE_KNOWN", stop_known, t2),
        "TARGET_PRICE_KNOWN": CausalFact("TARGET_PRICE_KNOWN", target_known, t2),
        "RISK_POSITIVE": CausalFact("RISK_POSITIVE", risk_positive, t2),
        "TARGET_BEYOND_ENTRY": CausalFact("TARGET_BEYOND_ENTRY", beyond, t2),
        "TEMPORAL_ORDER_VALID": CausalFact("TEMPORAL_ORDER_VALID", order_ok, t2),
    }


def causal_mask_for_v2_unit(unit, *, m5: Sequence[MarketBar],
                            m15: Sequence[MarketBar],
                            h1: Sequence[MarketBar]) -> CausalMaskResult:
    """Evaluate the frozen causal mask for one ALD V2 unit.

    Units without a confirmation are mask-ineligible with the frozen causal
    reject reason; they remain legitimate baseline opportunities.
    """
    if not unit.passed("S6_STRUCTURE_CONFIRM") or unit.confirm_time is None:
        return CausalMaskResult(
            CAUSAL_MASK_ID, unit.candidate_id, None, False,
            f"NO_CONFIRMATION:{unit.reject_reason or unit.reject_node or 'PRE_S6'}")
    facts = causal_mask_facts_from_v2_unit(unit, m5=m5, m15=m15, h1=h1)
    decision = t2_decision_time(datetime.fromisoformat(unit.confirm_time))
    return evaluate_causal_entry_geometry_mask(
        opportunity_id=unit.candidate_id, facts=facts, decision_ts=decision)
