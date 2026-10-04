from __future__ import annotations

"""Identity and record model for the STV2 **strategy funnel** analyzer.

This module implements the identity layer required by
``STV2_STRATEGY_FUNNEL_ANALYZER_V1``.  It is deliberately separate from the
*verification lifecycle* funnel (CONTRACT -> DATA_QUALITY -> DEV_SCREEN ->
FREEZE -> OOS_VERIFICATION -> ...) which the economic-matrix campaign already
implements.  The strategy funnel answers a different question:

    CONTEXT -> LOCATION -> TRIGGER -> GEOMETRY -> EXECUTION -> OUTCOME

Three identity concepts must stay distinguishable:

``candidate_id``
    The frozen strategy candidate, *identical for every observation*:
    ``SESSION_TRADE_V2_v2.0.0_e1ffe9f1e5cc``.

``segment_id``
    branch x symbol x session.  Exactly ``EXPECTED_SEGMENTS == 24`` of them.

``analysis_unit_id``
    One individual opportunity / session event.  This is the ONLY key that may
    be used for unit-level economic lookups.  ``candidate_id`` cannot be used:
    thousands of observations share it, so indexing outcomes by it collapses
    the whole DEV dataset onto a single value (the outcome-identity collision
    bug this analyzer had to fix).  Neither may the strategy commit sha be used
    as an "instance hash" — it is constant across every observation and
    therefore solves nothing.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Mapping

from ag_edgelab.campaigns.session_trade_v2.identity import (
    SOURCE_COMMIT,
    STRATEGY_ID,
    STRATEGY_VERSION,
)
from ag_edgelab.campaigns.session_trade_v2.windows import BRANCHES, SESSIONS, SYMBOLS
from ag_edgelab.contracts.funnel import FunnelStage
from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.ledger.candidate import CandidateRecord

#: The canonical, immutable strategy candidate identity.  Never fan this out.
CANONICAL_CANDIDATE_ID = f"{STRATEGY_ID}_v{STRATEGY_VERSION}_{SOURCE_COMMIT[:12]}"

#: The five cumulative FILTERING/EXECUTION stages of the strategy funnel.
#: OUTCOME is reported as a summary, not as a filtering stage.
FILTER_STAGES: tuple[FunnelStage, ...] = (
    FunnelStage.CONTEXT,
    FunnelStage.LOCATION,
    FunnelStage.TRIGGER,
    FunnelStage.GEOMETRY,
    FunnelStage.EXECUTION,
)
OUTCOME_STAGE = "OUTCOME"

EXPECTED_SEGMENTS = 24
EXPECTED_FILTER_STAGE_ROWS = EXPECTED_SEGMENTS * len(FILTER_STAGES)  # 120

#: Frozen A -> B -> C evaluation priority of the upstream engine.  A session is
#: "owned" by the first branch whose scan terminates the engine.
BRANCH_PRIORITY: dict[str, int] = {b: i for i, b in enumerate(BRANCHES)}


class UnitStatus(StrEnum):
    """Per-stage status vocabulary (never collapsed into a single value)."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    DATA_INVALID = "DATA_INVALID"
    AMBIGUOUS = "AMBIGUOUS"
    UNFILLED = "UNFILLED"
    EXPIRED = "EXPIRED"
    OPEN_AT_END = "OPEN_AT_END"
    CLOSED = "CLOSED"
    NOT_REACHED = "NOT_REACHED"


# ---------------------------------------------------------------------------
# segment identity
# ---------------------------------------------------------------------------


def segment_id(symbol: str, session: str, branch: str) -> str:
    """Immutable segment key, e.g. ``SESSION_TRADE_V2|EURUSD|LONDON_NEWYORK|A_SWEEP_REENTRY``."""
    if symbol not in SYMBOLS:
        raise ValueError(f"unsupported symbol: {symbol}")
    if session not in SESSIONS:
        raise ValueError(f"unsupported session: {session}")
    if branch not in BRANCHES:
        raise ValueError(f"unsupported branch: {branch}")
    return f"{STRATEGY_ID}|{symbol}|{session}|{branch}"


def all_segment_ids() -> tuple[str, ...]:
    """The exactly-24 segment identities, in a deterministic order."""
    return tuple(
        segment_id(symbol, session, branch)
        for branch in BRANCHES
        for symbol in SYMBOLS
        for session in SESSIONS
    )


@dataclass(frozen=True)
class SegmentKey:
    branch: str
    symbol: str
    session: str

    @property
    def segment_id(self) -> str:
        return segment_id(self.symbol, self.session, self.branch)


def all_segment_keys() -> tuple[SegmentKey, ...]:
    return tuple(
        SegmentKey(branch=branch, symbol=symbol, session=session)
        for branch in BRANCHES
        for symbol in SYMBOLS
        for session in SESSIONS
    )


# ---------------------------------------------------------------------------
# analysis-unit identity
# ---------------------------------------------------------------------------


def analysis_unit_identity_payload(
    *,
    candidate_id: str,
    symbol: str,
    session: str,
    branch: str,
    trading_date: str,
    event_identity: str,
    dataset_sha256: str,
    strategy_id: str = STRATEGY_ID,
    strategy_version: str = STRATEGY_VERSION,
) -> dict[str, str]:
    """The canonical identity payload hashed into an ``analysis_unit_id``."""
    return {
        "candidate_id": candidate_id,
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "symbol": symbol,
        "session": session,
        "branch": branch,
        "trading_date": trading_date,
        "event_identity": event_identity,
        "dataset_sha256": dataset_sha256,
    }


def compute_analysis_unit_id(
    *,
    candidate_id: str,
    symbol: str,
    session: str,
    branch: str,
    trading_date: str,
    event_identity: str,
    dataset_sha256: str,
    strategy_id: str = STRATEGY_ID,
    strategy_version: str = STRATEGY_VERSION,
) -> str:
    """sha256 of the canonical identity representation of one opportunity.

    Deterministic and collision-free across symbol, session, branch and
    trading date / event.  Uses EdgeLab's canonical-JSON hashing so the digest
    is stable regardless of key insertion order.
    """
    return sha256_json(
        analysis_unit_identity_payload(
            candidate_id=candidate_id,
            symbol=symbol,
            session=session,
            branch=branch,
            trading_date=trading_date,
            event_identity=event_identity,
            dataset_sha256=dataset_sha256,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
        )
    )


# ---------------------------------------------------------------------------
# stage + unit records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageEvaluation:
    """One strategy-funnel stage evaluation for one analysis unit."""

    stage: FunnelStage
    status: UnitStatus
    retained: bool
    reason: str | None = None
    features: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "stage": self.stage.value,
            "status": self.status.value,
            "retained": self.retained,
            "reason": self.reason,
            "features": dict(self.features),
        }


@dataclass(frozen=True)
class UnitEconomics:
    """Realized economics of ONE analysis unit.

    Every field is ``None`` unless the unit actually produced that evidence.
    A rejected, unfilled or expired observation is NEVER given a fabricated
    ``0R`` outcome — it simply has no economics.
    """

    outcome_status: UnitStatus | None = None
    order_type: str | None = None
    direction: str | None = None
    entry_time: datetime | None = None
    entry_price: float | None = None
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    risk_distance: float | None = None
    gross_r: float | None = None
    friction_r: float | None = None
    net_r: float | None = None
    tp1_4r_hit: bool | None = None
    runner_5r_hit: bool | None = None
    runner_breakeven: bool | None = None
    runner_open_at_end: bool | None = None
    same_bar_ambiguities: int = 0
    bars_held: int | None = None
    holding_hours: float | None = None

    def as_dict(self) -> dict:
        return {
            "outcome_status": self.outcome_status.value if self.outcome_status else None,
            "order_type": self.order_type,
            "direction": self.direction,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "entry_price": self.entry_price,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "risk_distance": self.risk_distance,
            "gross_r": self.gross_r,
            "friction_r": self.friction_r,
            "net_r": self.net_r,
            "tp1_4r_hit": self.tp1_4r_hit,
            "runner_5r_hit": self.runner_5r_hit,
            "runner_breakeven": self.runner_breakeven,
            "runner_open_at_end": self.runner_open_at_end,
            "same_bar_ambiguities": self.same_bar_ambiguities,
            "bars_held": self.bars_held,
            "holding_hours": self.holding_hours,
        }


@dataclass(frozen=True)
class AnalysisUnit:
    """One individual opportunity / session event in the strategy funnel.

    ``candidate_id`` is the canonical (shared) strategy identity;
    ``analysis_unit_id`` is this observation's own immutable identity.
    """

    analysis_unit_id: str
    candidate_id: str
    strategy_id: str
    strategy_version: str
    symbol: str
    session: str
    branch: str
    segment: str
    trading_date: str
    opportunity_timestamp: str
    event_sequence: int
    event_identity: str
    dataset_sha256: str
    stages: tuple[StageEvaluation, ...]
    economics: UnitEconomics = field(default_factory=UnitEconomics)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    # -- cumulative helpers -------------------------------------------------

    def stage(self, stage: FunnelStage) -> StageEvaluation | None:
        return next((s for s in self.stages if s.stage == stage), None)

    def retained_at(self, stage: FunnelStage) -> bool:
        """Cumulative retention: every stage up to and including ``stage`` passed."""
        for candidate in FILTER_STAGES:
            evaluation = self.stage(candidate)
            if evaluation is None or not evaluation.retained:
                return False
            if candidate == stage:
                return True
        return False

    def reached(self, stage: FunnelStage) -> bool:
        """The unit was an INPUT to ``stage`` (i.e. it survived every prior stage)."""
        index = FILTER_STAGES.index(stage)
        if index == 0:
            return True
        return self.retained_at(FILTER_STAGES[index - 1])

    @property
    def terminal_stage(self) -> str:
        """The stage at which this unit left the funnel (or EXECUTION if it survived)."""
        for stage in FILTER_STAGES:
            evaluation = self.stage(stage)
            if evaluation is None:
                return stage.value
            if not evaluation.retained:
                return stage.value
        return FILTER_STAGES[-1].value

    @property
    def closed_trade(self) -> bool:
        return self.economics.outcome_status == UnitStatus.CLOSED

    def as_dict(self) -> dict:
        return {
            "analysis_unit_id": self.analysis_unit_id,
            "candidate_id": self.candidate_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "symbol": self.symbol,
            "session": self.session,
            "branch": self.branch,
            "segment_id": self.segment,
            "trading_date": self.trading_date,
            "opportunity_timestamp": self.opportunity_timestamp,
            "event_sequence": self.event_sequence,
            "event_identity": self.event_identity,
            "dataset_sha256": self.dataset_sha256,
            "terminal_stage": self.terminal_stage,
            "stages": [s.as_dict() for s in self.stages],
            "economics": self.economics.as_dict(),
            "diagnostics": dict(self.diagnostics),
        }


class Stv2AnalysisUnitRecord(CandidateRecord):
    """A :class:`CandidateRecord` carrying its own unit-level identity.

    The inherited ``candidate_id`` stays the canonical strategy identity (so
    the ledger view of the candidate is unchanged); ``analysis_unit_id`` is the
    collision-free key that unit-level economics must be indexed by.
    """

    analysis_unit_id: str
    segment_id: str


def analysis_unit_key(record: CandidateRecord) -> str:
    """``key_fn`` for :func:`ag_edgelab.analytics.funnel.compute_funnel_stats`.

    STV2 records are keyed by ``analysis_unit_id``; anything else would reuse
    the shared ``candidate_id`` and collide.
    """
    unit_id = getattr(record, "analysis_unit_id", None)
    if not unit_id:
        raise ValueError(
            "record carries no analysis_unit_id; STV2 unit-level economics must "
            "never be keyed by the shared candidate_id"
        )
    return unit_id


def event_identity_for_session(session: str, trading_date: date, trade_start: datetime, sequence: int = 0) -> str:
    """Deterministic event identity of one session opportunity.

    Under the frozen STV2 semantics each (symbol, session, trading date,
    branch) yields at most one opportunity, so the event identity is the trade
    window's opening instant plus an explicit sequence ordinal (reserved for
    future multi-opportunity stage constructions).
    """
    return f"{session}@{trade_start.isoformat()}#{sequence}"
