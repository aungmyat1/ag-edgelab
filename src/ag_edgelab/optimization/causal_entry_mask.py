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

The historical ``row.all_rules_pass`` funnel flag is NOT this mask: it
requires S9 completion, which is post-entry outcome information.  The
historical S7 stage is also not blindly frozen because its pass state
depends on the existence of forward M5 bars after the confirmation bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from ag_edgelab.optimization.causal_time import (
    CausalFact, LookaheadViolation, assert_available_at_or_before, require_aware_utc,
    t1_direction_available, t2_decision_time,
)

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


def causal_mask_facts_from_v2_unit(unit) -> dict[str, CausalFact]:
    """Build the mask fact set from a frozen ALD V2 ``V2Unit``.

    Only fields whose values are determined by bars closed at or before the
    confirmation bar are read.  Outcome fields (realised_r, mfe_r, mae_r,
    resolution, reached, stopped_out, stopped_same_bar, forward_bars) are
    NEVER read; a unit object that raises on their access still produces a
    mask, which is asserted by the focused test suite.

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

    from datetime import datetime as _dt

    from ag_edgelab.optimization.causal_time import M15_BAR_DURATION, M5_BAR_DURATION

    event_open = _dt.fromisoformat(unit.event_time)
    t1 = t1_direction_available(event_open)
    t2 = t2_decision_time(_dt.fromisoformat(unit.confirm_time))

    # Branch A reclaims on an M15 bar close (+15 min); branch B retests on an
    # M5 bar close (+5 min).  Both bar families stamp OPEN times.
    reclaim_bar_duration = (M15_BAR_DURATION if unit.branch == "A_SWEEP_RECLAIM_REVERSAL"
                            else M5_BAR_DURATION)
    reclaim_available = (t1 if unit.reclaim_or_retest_time is None
                         else _dt.fromisoformat(unit.reclaim_or_retest_time) + reclaim_bar_duration)
    if reclaim_available > t2:
        reclaim_available = t2

    entry_known = unit.entry is not None
    stop_known = unit.stop is not None
    risk_positive = (unit.risk is not None and unit.risk > 0)
    target_known = unit.target is not None
    beyond = False
    if entry_known and target_known and unit.direction in ("BULL", "BEAR"):
        beyond = ((unit.target > unit.entry) if unit.direction == "BULL"
                  else (unit.target < unit.entry))
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


def causal_mask_for_v2_unit(unit) -> CausalMaskResult:
    """Evaluate the frozen causal mask for one ALD V2 unit.

    Units without a confirmation are mask-ineligible with the frozen causal
    reject reason; they remain legitimate baseline opportunities.
    """
    if not unit.passed("S6_STRUCTURE_CONFIRM") or unit.confirm_time is None:
        return CausalMaskResult(
            CAUSAL_MASK_ID, unit.candidate_id, None, False,
            f"NO_CONFIRMATION:{unit.reject_reason or unit.reject_node or 'PRE_S6'}")
    facts = causal_mask_facts_from_v2_unit(unit)
    from datetime import datetime as _dt
    decision = t2_decision_time(_dt.fromisoformat(unit.confirm_time))
    return evaluate_causal_entry_geometry_mask(
        opportunity_id=unit.candidate_id, facts=facts, decision_ts=decision)
