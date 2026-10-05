"""V2.1 REPLAY ENGINE — deterministic execution of the frozen 2.1.0 contract.

Mission 3B-A. Infrastructure only: this module is capable of running a replay
but no real-corpus replay is performed by it during the preparation mission.

DESIGN RULE THAT GOVERNS THIS FILE
-----------------------------------
The engine implements ONLY what contract ``2c5cfa8c`` actually freezes. Where
the contract is silent, the engine does NOT invent a reading. It exposes a
REQUIRED, UN-DEFAULTED policy hook and refuses to construct until the hook is
supplied, naming the open question. Choosing an interpretation here would
silently turn an unfrozen degree of freedom into a research result.

Four such silences were found while implementing, recorded in
``CONTRACT_AMBIGUITIES``. They are reported upward as CONTRACT_AMBIGUITY_FOUND
and are for the contract owner / auditor to resolve, not for this agent.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Iterable, Sequence

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import canonical_json
from ag_edgelab.strategies import asian_liquidity_displacement_v2_1 as V
from ag_edgelab.strategies.symbol_metadata import SymbolMetadata, metadata_for

ENGINE_ID = "GEN2_ALD_V2_1_REPLAY_ENGINE_V1"

# ---------------------------------------------------------------------------
# CONTRACT AMBIGUITIES — found while implementing, NOT resolved here.
# ---------------------------------------------------------------------------

CONTRACT_AMBIGUITIES: tuple[dict, ...] = (
    {
        "id": "AMB_1_OPPORTUNITY_UNIT",
        "contract_field": "funnel.stages[OPPORTUNITY]",
        "finding": (
            "OPPORTUNITY appears in the funnel taxonomy as a stage name and "
            "nowhere else in the contract. The denominator of every funnel "
            "percentage is therefore unfrozen."
        ),
        "why_it_matters": (
            "EVENT_ID and the duplicate lock are keyed on (symbol, date, "
            "session, BOUNDARY), which admits one accepted trade PER "
            "BOUNDARY — up to two per symbol-day-session. The 2.0.0 "
            "prototype instead counted ONE unit per (symbol, day, session). "
            "The two readings give different OPPORTUNITY_N on identical "
            "data, so entry yield and every funnel percentage change "
            "meaning. This also determines whether the 2.1.0 funnel is "
            "comparable to V1's 26,814 denominator."
        ),
        "question_for_owner": (
            "Is an OPPORTUNITY one (symbol, trading_date, session) or one "
            "(symbol, trading_date, session, boundary)?"
        ),
        "hook": "policy.enumerate_opportunities",
    },
    {
        "id": "AMB_2_CONTEXT_AND_LOCATION_ELIGIBILITY",
        "contract_field": "funnel.stages[CONTEXT_ELIGIBLE, LOCATION_ELIGIBLE]",
        "finding": (
            "Both stages appear only as names. The contract freezes "
            "MIN_REFERENCE_M15_BARS and WARMUP_DAYS, which plausibly "
            "constitute CONTEXT eligibility, but never says so, and gives "
            "LOCATION eligibility no definition at all."
        ),
        "why_it_matters": (
            "These are the first two attrition stages. In the V1 evidence the "
            "equivalent stage absorbed 53% of all opportunities, so an "
            "unfrozen definition here dominates the funnel."
        ),
        "question_for_owner": (
            "What predicate defines CONTEXT_ELIGIBLE, and what defines "
            "LOCATION_ELIGIBLE?"
        ),
        "hook": "policy.context_eligible / policy.location_eligible",
    },
    {
        "id": "AMB_3_INITIAL_BRANCH_SELECTION",
        "contract_field": "governance.permitted_handovers",
        "finding": (
            "PERMITTED_HANDOVERS presupposes that one branch is attempted "
            "FIRST, but no rule selects it. The contract defines A and B "
            "mechanisms and the transitions between them, never the entry "
            "point into that graph."
        ),
        "why_it_matters": (
            "With HANDOVER_MAX = 1, the branch tried first gets first claim "
            "on the event lock. Branch mix, and therefore the branch "
            "stability axis, depends entirely on this unfrozen choice."
        ),
        "question_for_owner": (
            "Which branch is attempted first on a boundary interaction — is "
            "it decided by the interaction bar's close (prototype behaviour), "
            "by a fixed precedence, or are both run and the earlier "
            "ENTRY_AVAILABLE taken?"
        ),
        "hook": "policy.select_initial_branch",
    },
    {
        "id": "AMB_4_SECOND_AND_THIRD_TARGET_AUTHORITIES",
        "contract_field": "target.authority_order[1], [2]",
        "finding": (
            "PRIOR_DAY_HIGH_LOW and CONFIRMED_PRE_ENTRY_SWING_LIQUIDITY are "
            "named and ordered but never operationally defined. No timeframe, "
            "no session-day convention, no swing derivation is frozen for "
            "either. (OPPOSITE_SESSION_BOUNDARY is unambiguous.)"
        ),
        "why_it_matters": (
            "These two authorities set NATURAL_TARGET_R for every unit the "
            "first authority does not serve — which is most of branch B, "
            "since the opposite boundary lies behind a continuation entry. "
            "NATURAL_TARGET_R is the primary outcome metric."
        ),
        "question_for_owner": (
            "Define 'prior day' (previous calendar day vs previous trading "
            "day; UTC vs session day) and define the swing-liquidity "
            "derivation (timeframe and whether SWING_ORDER = 2 applies)."
        ),
        "hook": "policy.prior_day_levels / policy.swing_liquidity_levels",
    },
)


class ContractAmbiguityError(RuntimeError):
    """Raised instead of guessing when an unfrozen degree of freedom is hit."""


class PolicyProvenanceError(RuntimeError):
    """Raised when a synthetic policy is pointed at a real dataset."""


# ---------------------------------------------------------------------------
# Policy injection — every hook is REQUIRED and has NO default.
# ---------------------------------------------------------------------------

SYNTHETIC_PROVENANCE = "SYNTHETIC_FIXTURE_ONLY"
OWNER_RESOLVED_PROVENANCE = "OWNER_RESOLVED_CONTRACT_AMENDMENT"


@dataclass(frozen=True)
class ReplayPolicy:
    """The unfrozen decisions, supplied from outside and labelled.

    ``provenance`` must be OWNER_RESOLVED_PROVENANCE before this policy may be
    used against a real dataset. A SYNTHETIC_FIXTURE_ONLY policy is accepted
    for tests and determinism proofs and refused everywhere else.
    """

    provenance: str
    enumerate_opportunities: Callable[..., Iterable["Opportunity"]]
    context_eligible: Callable[["Opportunity"], tuple[bool, str]]
    location_eligible: Callable[["Opportunity"], tuple[bool, str]]
    select_initial_branch: Callable[..., str]
    prior_day_levels: Callable[..., Sequence[V.TargetCandidate]]
    swing_liquidity_levels: Callable[..., Sequence[V.TargetCandidate]]
    resolves_ambiguities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        unresolved = {a["id"] for a in CONTRACT_AMBIGUITIES} - set(self.resolves_ambiguities)
        if unresolved:
            raise ContractAmbiguityError(
                "policy does not declare a resolution for: "
                f"{sorted(unresolved)}. The engine will not invent one."
            )
        if self.provenance not in (SYNTHETIC_PROVENANCE, OWNER_RESOLVED_PROVENANCE):
            raise PolicyProvenanceError(f"unknown policy provenance {self.provenance!r}")

    @property
    def is_synthetic(self) -> bool:
        return self.provenance == SYNTHETIC_PROVENANCE


# ---------------------------------------------------------------------------
# Units of work
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Opportunity:
    """One candidate occasion, as defined by the (unfrozen) policy."""

    symbol: str
    trading_date: str
    session: str
    boundary: str                 # "HIGH" | "LOW"
    boundary_price: float
    reference_high: float
    reference_low: float
    event_sequence: int
    bars: tuple[MarketBar, ...]   # entry-window M5 bars
    forward_bars: tuple[MarketBar, ...] = ()

    @property
    def reference_range(self) -> float:
        return self.reference_high - self.reference_low

    @property
    def opposite_boundary_price(self) -> float:
        return self.reference_low if self.boundary == "HIGH" else self.reference_high


@dataclass
class Transition:
    """A single state-machine transition, fully attributed (Phase 2)."""

    event_id: str
    symbol: str
    trading_date: str
    session: str
    branch: str
    boundary: str
    from_state: str
    to_state: str
    decision_timestamp: str
    source_bar_timestamp: str
    reason_code: str

    def as_row(self) -> dict:
        return {
            "event_id": self.event_id, "symbol": self.symbol,
            "trading_date": self.trading_date, "session": self.session,
            "branch": self.branch, "boundary": self.boundary,
            "from_state": self.from_state, "to_state": self.to_state,
            "decision_timestamp": self.decision_timestamp,
            "source_bar_timestamp": self.source_bar_timestamp,
            "reason_code": self.reason_code,
        }


@dataclass
class TradeRecord:
    """One evaluated candidate: funnel position, geometry and outcome."""

    event_id: str
    symbol: str
    trading_date: str
    session: str
    boundary: str
    branch: str | None = None
    stages: dict[str, bool] = field(default_factory=dict)
    reject_reason: str | None = None
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    target_authority: str | None = None
    risk_distance: float | None = None
    reward_distance: float | None = None
    natural_target_r: float | None = None
    entry_timestamp: str | None = None
    outcome: str | None = None
    realised_r: float | None = None
    reached: dict[str, bool] = field(default_factory=dict)

    def as_row(self) -> dict:
        return {
            "event_id": self.event_id, "symbol": self.symbol,
            "trading_date": self.trading_date, "session": self.session,
            "boundary": self.boundary, "branch": self.branch,
            "stages": dict(sorted(self.stages.items())),
            "reject_reason": self.reject_reason,
            "entry_price": self.entry_price, "stop_price": self.stop_price,
            "target_price": self.target_price,
            "target_authority": self.target_authority,
            "risk_distance": self.risk_distance,
            "reward_distance": self.reward_distance,
            "natural_target_r": self.natural_target_r,
            "entry_timestamp": self.entry_timestamp,
            "outcome": self.outcome, "realised_r": self.realised_r,
            "reached": dict(sorted(self.reached.items())),
        }


# ---------------------------------------------------------------------------
# PHASE 8 — outcome engine. Same-bar collision = frozen STOP_FIRST policy.
# ---------------------------------------------------------------------------

OUTCOME_NATURAL_TARGET = "NATURAL_TARGET_REACHED"
OUTCOME_STOP = "STOP_REACHED"
OUTCOME_SESSION_EXPIRED = "SESSION_EXPIRED"
OUTCOME_UNRESOLVED = "UNRESOLVED"


def evaluate_outcome(forward: Sequence[MarketBar], *, bull: bool,
                     entry: float, stop: float, target: float) -> dict:
    """Walk forward bar by bar. Stop wins any same-bar collision.

    The optimistic reading (target first when both print on one bar) is
    deliberately NOT available: SAME_BAR_COLLISION_POLICY is frozen to
    STOP_FIRST_FAIL_CLOSED_V0_3.
    """
    risk = abs(entry - stop)
    horizon = forward[:V.OUTCOME_HORIZON_M5_BARS]
    best_r = 0.0
    reached = {f"{k}R": False for k in V.FIXED_R_TARGETS}

    for b in horizon:
        if bull:
            hit_stop, hit_tp = b.low <= stop, b.high >= target
            excursion = (b.high - entry) / risk if risk > 0 else 0.0
        else:
            hit_stop, hit_tp = b.high >= stop, b.low <= target
            excursion = (entry - b.low) / risk if risk > 0 else 0.0

        if hit_stop:
            # Fail closed: the stop is assumed first even if the target also
            # printed on this bar. Record excursion only up to what is safe.
            for k in V.FIXED_R_TARGETS:
                if reached[f"{k}R"]:
                    continue
            return {"outcome": OUTCOME_STOP, "realised_r": -1.0,
                    "reached": reached, "bars_held": horizon.index(b) + 1,
                    "same_bar_collision": bool(hit_tp)}

        best_r = max(best_r, excursion)
        for k in V.FIXED_R_TARGETS:
            if best_r >= k:
                reached[f"{k}R"] = True

        if hit_tp:
            natural_r = abs(target - entry) / risk if risk > 0 else 0.0
            return {"outcome": OUTCOME_NATURAL_TARGET, "realised_r": natural_r,
                    "reached": reached, "bars_held": horizon.index(b) + 1,
                    "same_bar_collision": False}

    if not horizon:
        return {"outcome": OUTCOME_UNRESOLVED, "realised_r": None,
                "reached": reached, "bars_held": 0, "same_bar_collision": False}

    last = horizon[-1]
    mark = (last.close - entry) / risk if bull else (entry - last.close) / risk
    outcome = (OUTCOME_SESSION_EXPIRED if len(forward) > len(horizon)
               else OUTCOME_UNRESOLVED)
    return {"outcome": outcome, "realised_r": round(mark, 6),
            "reached": reached, "bars_held": len(horizon),
            "same_bar_collision": False}


# ---------------------------------------------------------------------------
# PHASE 5/6 — target + geometry engine
# ---------------------------------------------------------------------------

def build_target_candidates(opp: Opportunity, policy: ReplayPolicy, *,
                            entry_timestamp: datetime,
                            bull: bool) -> list[V.TargetCandidate]:
    """Assemble candidates in contract order. Authority 1 is frozen; 2 and 3
    come from the policy because the contract never defines them (AMB_4)."""
    cands: list[V.TargetCandidate] = []
    # Authority 1 — OPPOSITE_SESSION_BOUNDARY. Known from the reference
    # session, which closed before the entry window opened.
    cands.append(V.TargetCandidate(
        authority="OPPOSITE_SESSION_BOUNDARY",
        level=opp.opposite_boundary_price,
        known_at=opp.bars[0].timestamp if opp.bars else entry_timestamp,
    ))
    cands.extend(policy.prior_day_levels(opp, entry_timestamp=entry_timestamp, bull=bull))
    cands.extend(policy.swing_liquidity_levels(opp, entry_timestamp=entry_timestamp, bull=bull))
    return cands


def compute_geometry(opp: Opportunity, policy: ReplayPolicy, *, entry: float,
                     stop: float, entry_timestamp: datetime,
                     bull: bool, meta: SymbolMetadata) -> dict:
    """Phase 6. Returns a geometry record or a failure reason."""
    risk = abs(entry - stop)
    if risk <= 0 or not meta.at_least_one_tick(risk):
        return {"ok": False, "reason": "GEOMETRY_RISK_NON_POSITIVE"}
    directional = (stop < entry) if bull else (stop > entry)
    if not directional:
        return {"ok": False, "reason": "GEOMETRY_STOP_WRONG_SIDE"}

    cands = build_target_candidates(opp, policy, entry_timestamp=entry_timestamp, bull=bull)
    res = V.resolve_natural_target(cands, entry_price=entry, stop_price=stop,
                                   entry_timestamp=entry_timestamp,
                                   direction_is_bull=bull)
    if res["status"] != V.TargetStatus.RESOLVED.value:
        return {"ok": False, "reason": res["reason"] or res["status"],
                "target_authority": res["authority"],
                "natural_target_r": res["natural_r"]}

    reward = abs(res["target"] - entry)
    if reward <= 0 or not meta.at_least_one_tick(reward):
        return {"ok": False, "reason": "GEOMETRY_REWARD_NON_POSITIVE"}
    return {"ok": True, "target": res["target"], "target_authority": res["authority"],
            "risk_distance": risk, "reward_distance": reward,
            "natural_target_r": res["natural_r"]}


# ---------------------------------------------------------------------------
# PHASE 2/3 — the driver
# ---------------------------------------------------------------------------

_A_REASONS = {
    "SWEEP_DETECTED": "SWEEP_MIN_TICKS_MET",
    "RECLAIM_PENDING": "AWAITING_RECLAIM",
    "RECLAIM_CONFIRMED": "CLOSED_BACK_INSIDE_RANGE",
    "MSS_PENDING": "AWAITING_STRUCTURE_SHIFT",
    "MSS_CONFIRMED": "STRUCTURE_SHIFT_IN_REVERSAL_DIRECTION",
    "ENTRY_AVAILABLE": "ENTRY_AT_CONFIRMING_BAR_CLOSE",
}
_B_REASONS = {
    "BREAKOUT_DETECTED": "BREAKOUT_MIN_TICKS_MET",
    "ACCEPTANCE_PENDING": "AWAITING_ACCEPTANCE_CLOSES",
    "ACCEPTED_BREAKOUT": "ACCEPTANCE_CLOSE_COUNT_MET",
    "RETEST_PENDING": "AWAITING_RETEST",
    "RETEST_CONFIRMED": "EXACT_TOUCH_HELD_ON_BREAKOUT_SIDE",
    "CONTINUATION_CONFIRMED": "STRUCTURE_SHIFT_IN_BREAKOUT_DIRECTION",
    "ENTRY_AVAILABLE": "ENTRY_AT_CONFIRMING_BAR_CLOSE",
}


def _attribute(result: V.MachineResult, opp: Opportunity, eid: str,
               bars: Sequence[MarketBar]) -> list[Transition]:
    """Turn frozen-module transitions into fully attributed ledger rows."""
    table = _A_REASONS if result.branch == V.Branch.A.value else _B_REASONS
    rows: list[Transition] = []
    for t in result.transitions:
        bar_ts = t["timestamp"]
        src = datetime.fromisoformat(bar_ts)
        reason = (result.invalidation_reason if t["to"] == "INVALIDATED"
                  else table.get(t["to"], t["to"]))
        rows.append(Transition(
            event_id=eid, symbol=opp.symbol, trading_date=opp.trading_date,
            session=opp.session, branch=result.branch, boundary=opp.boundary,
            from_state=t["from"], to_state=t["to"],
            decision_timestamp=(src + timedelta(minutes=5)).isoformat(),
            source_bar_timestamp=bar_ts, reason_code=reason or "UNSPECIFIED",
        ))
    return rows


class V21Engine:
    """Deterministic driver for one frozen-contract replay."""

    def __init__(self, policy: ReplayPolicy, *, allow_synthetic: bool = False):
        if policy.is_synthetic and not allow_synthetic:
            raise PolicyProvenanceError(
                "a SYNTHETIC_FIXTURE_ONLY policy may not drive a real replay"
            )
        self.policy = policy
        self.registry = V.EventRegistry()
        self.transitions: list[Transition] = []
        self.trades: list[TradeRecord] = []

    # -- per-opportunity --------------------------------------------------
    def evaluate(self, opp: Opportunity, *, mss_confirmed_at,
                 continuation_confirmed_at) -> TradeRecord:
        meta = metadata_for(opp.symbol)
        rec = self.registry.open_event(opp.symbol, opp.trading_date, opp.session,
                                       opp.boundary, opp.event_sequence)
        tr = TradeRecord(event_id=rec.event_id, symbol=opp.symbol,
                         trading_date=opp.trading_date, session=opp.session,
                         boundary=opp.boundary)
        tr.stages["OPPORTUNITY"] = True

        ok, reason = self.policy.context_eligible(opp)
        tr.stages["CONTEXT_ELIGIBLE"] = ok
        if not ok:
            tr.reject_reason = reason
            self.trades.append(tr)
            return tr

        ok, reason = self.policy.location_eligible(opp)
        tr.stages["LOCATION_ELIGIBLE"] = ok
        if not ok:
            tr.reject_reason = reason
            self.trades.append(tr)
            return tr

        if self.registry.is_locked(rec):
            self.registry.accept_signal(rec, "LOCKED")
            tr.reject_reason = "DUPLICATE_SUPPRESSED"
            self.trades.append(tr)
            return tr

        first = self.policy.select_initial_branch(opp)
        order = [first] + [b.value for b in V.Branch if b.value != first]

        result = None
        for attempt, branch in enumerate(order):
            if attempt and not self.registry.may_hand_over(
                    rec, order[attempt - 1], branch,
                    result.invalidation_reason or ""):
                break
            if attempt:
                self.registry.record_handover(rec, order[attempt - 1], branch,
                                              result.invalidation_reason or "")
            self.registry.note_detection(rec, branch)
            result = self._drive(branch, opp, meta, mss_confirmed_at,
                                 continuation_confirmed_at)
            self.transitions.extend(_attribute(result, opp, rec.event_id, opp.bars))
            if result.reached_entry:
                break
            self.registry.note_invalidation(rec, branch,
                                            result.invalidation_reason or "UNKNOWN")

        tr.branch = result.branch if result else None
        tr.stages["SESSION_EVENT"] = bool(result and result.indices)
        tr.stages["STRUCTURE_CONFIRM"] = bool(result and result.reached_entry)

        if result is None or not result.reached_entry:
            tr.reject_reason = (result.invalidation_reason if result else "NO_EVENT")
            tr.stages["ENTRY_AVAILABLE"] = False
            self.trades.append(tr)
            return tr

        if not self.registry.accept_signal(rec, result.branch):
            tr.reject_reason = "DUPLICATE_SUPPRESSED"
            tr.stages["ENTRY_AVAILABLE"] = False
            self.trades.append(tr)
            return tr

        tr.stages["ENTRY_AVAILABLE"] = True
        entry_ts = result.timestamps["entry_timestamp"]
        tr.entry_timestamp = entry_ts.isoformat()
        tr.entry_price = result.entry_price
        tr.stop_price = result.stop_price
        bull = bool(result.direction_is_bull)

        geom = compute_geometry(opp, self.policy, entry=result.entry_price,
                                stop=result.stop_price, entry_timestamp=entry_ts,
                                bull=bull, meta=meta)
        tr.stages["GEOMETRY_VALID"] = geom["ok"]
        if not geom["ok"]:
            tr.reject_reason = geom["reason"]
            tr.target_authority = geom.get("target_authority")
            tr.natural_target_r = geom.get("natural_target_r")
            self.trades.append(tr)
            return tr

        tr.target_price = geom["target"]
        tr.target_authority = geom["target_authority"]
        tr.risk_distance = geom["risk_distance"]
        tr.reward_distance = geom["reward_distance"]
        tr.natural_target_r = geom["natural_target_r"]

        out = evaluate_outcome(opp.forward_bars, bull=bull, entry=tr.entry_price,
                               stop=tr.stop_price, target=tr.target_price)
        tr.outcome = out["outcome"]
        tr.realised_r = out["realised_r"]
        tr.reached = out["reached"]
        tr.stages["TRADE_COMPLETED"] = out["outcome"] in (
            OUTCOME_NATURAL_TARGET, OUTCOME_STOP)
        self.trades.append(tr)
        return tr

    def _drive(self, branch: str, opp: Opportunity, meta: SymbolMetadata,
               mss_confirmed_at, continuation_confirmed_at) -> V.MachineResult:
        if branch == V.Branch.A.value:
            return V.run_branch_a(
                opp.bars, boundary=opp.boundary_price, boundary_side=opp.boundary,
                reference_range=opp.reference_range, meta=meta,
                mss_confirmed_at=mss_confirmed_at)
        return V.run_branch_b(
            opp.bars, boundary=opp.boundary_price, boundary_side=opp.boundary,
            reference_range=opp.reference_range, meta=meta,
            continuation_confirmed_at=continuation_confirmed_at)

    # -- ledgers ----------------------------------------------------------
    def event_ledger(self) -> list[dict]:
        return self.registry.rows()

    def transition_ledger(self) -> list[dict]:
        return [t.as_row() for t in self.transitions]

    def trade_ledger(self) -> list[dict]:
        return [t.as_row() for t in self.trades]

    def ledger_hash(self) -> str:
        payload = {
            "engine_id": ENGINE_ID,
            "contract_hash": V.contract_hash(),
            "events": self.event_ledger(),
            "transitions": self.transition_ledger(),
            "trades": self.trade_ledger(),
        }
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
