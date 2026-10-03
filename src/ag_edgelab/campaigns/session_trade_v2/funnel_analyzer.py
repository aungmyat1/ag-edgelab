from __future__ import annotations

"""STV2 strategy-funnel analyzer (``STV2_STRATEGY_FUNNEL_ANALYZER_V1``).

Diagnostic research only.  This module NEVER modifies the frozen
``SESSION_TRADE_V2 @ 2.0.0`` rules, never optimizes parameters, never touches
the sealed holdout, and never reaches an execution API.

Funnel (cumulative)::

    CONTEXT -> LOCATION -> TRIGGER -> GEOMETRY -> EXECUTION -> OUTCOME

Unit of observation: one ``(trading_date, symbol, session, branch)`` tuple.
Observations aggregate into the 24 ``branch x symbol x session`` segments.

Authority of each stage
-----------------------

``CONTEXT``
    The campaign's own frozen completeness gate (``build_window_slice``) plus
    the frozen engine's own preconditions (supported symbol/session, positive
    reference range, reference box closed strictly before the trade window).

``LOCATION``
    A *structural relaxation* of each branch's own frozen trigger: the trigger
    predicate with its final confirmation clause removed.  Nothing is invented
    — see :func:`location_evidence`.

``TRIGGER``
    The **frozen engine's authoritative decision**.  The upstream engine
    evaluates one session with a hard A -> B -> C priority and returns a single
    decision, so a branch is TRIGGER-retained only when the frozen engine
    itself attributed the session to that branch.  Branch rule predicates are
    *also* replayed verbatim as a diagnostic (``branch_rule_fired``) so that
    "the rule never fires" can be distinguished from "a higher-priority branch
    owned the session" — but the diagnostic never overrides the engine.

``GEOMETRY``
    The frozen entry/stop/target geometry emitted by the engine, re-validated
    explicitly (positive risk, 25 % reference-range stop, stop side, target
    direction, 4R/5R distances, branch entry geometry, and for A the frozen
    ``SWEEP_STOP_DOES_NOT_PROTECT_EXTREME`` protection rule).  Nothing is
    repaired.

``EXECUTION`` / ``OUTCOME``
    The campaign's frozen adapter + replay + friction semantics, reused
    unchanged via :func:`ag_edgelab.campaigns.session_trade_v2.campaign.evaluate_window`,
    which guarantees the funnel reconciles exactly to the economic campaign's
    trade records.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from ag_edgelab.analytics.funnel import wilson_interval
from ag_edgelab.campaigns.session_trade_v2.campaign import SessionRecord, evaluate_window
from ag_edgelab.campaigns.session_trade_v2.dataset import (
    PARTITIONS,
    HoldoutAccessError,
    partition_bounds,
)
from ag_edgelab.campaigns.session_trade_v2.frozen import Candle
from ag_edgelab.campaigns.session_trade_v2.funnel_models import (
    BRANCH_PRIORITY,
    CANONICAL_CANDIDATE_ID,
    EXPECTED_FILTER_STAGE_ROWS,
    EXPECTED_SEGMENTS,
    FILTER_STAGES,
    AnalysisUnit,
    SegmentKey,
    StageEvaluation,
    Stv2AnalysisUnitRecord,
    UnitEconomics,
    UnitStatus,
    all_segment_keys,
    compute_analysis_unit_id,
    event_identity_for_session,
    segment_id,
)
from ag_edgelab.campaigns.session_trade_v2.identity import STRATEGY_ID, STRATEGY_VERSION
from ag_edgelab.campaigns.session_trade_v2.replay import CampaignTrade
from ag_edgelab.campaigns.session_trade_v2.windows import (
    BRANCHES,
    SESSIONS,
    SYMBOLS,
    build_window_slice,
    session_window,
)
from ag_edgelab.contracts.funnel import FunnelStage, FunnelStageResult, RuleResult
from ag_edgelab.contracts.market import MarketBar

A, B, C = BRANCHES  # A_SWEEP_REENTRY, B_RANGE_REJECTION, C_TREND_EXPANSION

R_FRACTION = 0.25  # frozen STV2 constant, mirrored for explicit geometry checks
GEOMETRY_REL_TOL = 1e-9
BE_TOLERANCE = 1e-9

#: Reasons emitted by the frozen engine that still mean "this branch triggered".
A_OWNED_NO_TRADE_REASONS = (
    "SWEEP_STOP_DOES_NOT_PROTECT_EXTREME",
    "AMBIGUOUS_DUAL_SIDE_SWEEP",
)
B_OWNED_NO_TRADE_REASONS = ("AMBIGUOUS_DUAL_BOUNDARY_REJECTION",)

AMBIGUOUS_TRIGGER_REASONS = {
    A: "AMBIGUOUS_DUAL_SIDE_SWEEP",
    B: "AMBIGUOUS_DUAL_BOUNDARY_REJECTION",
}


class FunnelReconciliationError(RuntimeError):
    """Raised when funnel results cannot be reconciled to campaign trades."""


# ---------------------------------------------------------------------------
# branch structural predicates (verbatim relaxations / replicas of V2 rules)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceBox:
    high: float
    low: float

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2.0

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def r0(self) -> float:
        return self.range * R_FRACTION


def reference_box(reference: Sequence[Candle]) -> ReferenceBox:
    return ReferenceBox(high=max(c.high for c in reference), low=min(c.low for c in reference))


def location_evidence(branch: str, box: ReferenceBox, trade: Sequence[Candle]) -> dict[str, Any]:
    """Structural-area evidence for one branch.

    Each predicate is the branch's own frozen trigger with the *final*
    confirmation clause dropped — no new filters, no reclaim/rejection/body
    requirement:

    * ``A`` trigger is ``low < ref_low AND close > ref_low`` (or the high-side
      mirror); dropping the reclaim clause leaves a strict boundary BREACH.
    * ``B`` trigger is ``low <= ref_low AND inside close`` (or the mirror);
      dropping the inward-close clause leaves a boundary TOUCH-or-beyond.
    * ``C`` trigger is ``body_low > ref_high AND close > ref_high`` (or the
      mirror); dropping the body-close clause leaves an EXTENSION beyond the
      boundary.
    """
    if branch == A:
        low_side = [c for c in trade if c.low < box.low]
        high_side = [c for c in trade if c.high > box.high]
    elif branch == B:
        low_side = [c for c in trade if c.low <= box.low]
        high_side = [c for c in trade if c.high >= box.high]
    elif branch == C:
        # expansion direction: below the low (short) or above the high (long)
        low_side = [c for c in trade if c.low < box.low]
        high_side = [c for c in trade if c.high > box.high]
    else:  # pragma: no cover - guarded by BRANCHES
        raise ValueError(f"unsupported branch: {branch}")

    first = None
    candidates = [c for c in trade if c in low_side or c in high_side]
    if candidates:
        first = min(c.time for c in candidates)
    return {
        "low_side_interactions": len(low_side),
        "high_side_interactions": len(high_side),
        "both_sides_interacted": bool(low_side) and bool(high_side),
        "first_interaction_time": first.isoformat() if first else None,
        "reference_high": box.high,
        "reference_low": box.low,
        "reference_range": box.range,
    }


@dataclass(frozen=True)
class RawTriggerScan:
    """Verbatim replay of one branch's frozen trigger predicate.

    Diagnostic ONLY — it ignores the engine's A -> B -> C priority so that
    "the rule never fires" can be told apart from "a higher-priority branch
    consumed the session".  Retention is always decided by the engine.
    """

    fired: bool
    ambiguous: bool
    direction: str | None
    candle_time: datetime | None


def raw_trigger_scan(branch: str, box: ReferenceBox, trade: Sequence[Candle]) -> RawTriggerScan:
    high, low = box.high, box.low
    if branch == A:
        for c in trade:
            swept_high = c.high > high and c.close < high
            swept_low = c.low < low and c.close > low
            if swept_high and swept_low:
                return RawTriggerScan(True, True, None, c.time)
            if swept_low:
                return RawTriggerScan(True, False, "LONG", c.time)
            if swept_high:
                return RawTriggerScan(True, False, "SHORT", c.time)
        return RawTriggerScan(False, False, None, None)
    if branch == B:
        for c in trade:
            low_reject = c.low <= low and low < c.close < high
            high_reject = c.high >= high and low < c.close < high
            if low_reject and high_reject:
                return RawTriggerScan(True, True, None, c.time)
            if low_reject:
                return RawTriggerScan(True, False, "LONG", c.time)
            if high_reject:
                return RawTriggerScan(True, False, "SHORT", c.time)
        return RawTriggerScan(False, False, None, None)
    if branch == C:
        for c in trade:
            if c.body_low > high and c.close > high:
                return RawTriggerScan(True, False, "LONG", c.time)
            if c.body_high < low and c.close < low:
                return RawTriggerScan(True, False, "SHORT", c.time)
        return RawTriggerScan(False, False, None, None)
    raise ValueError(f"unsupported branch: {branch}")  # pragma: no cover


def owning_branch(record: SessionRecord) -> str | None:
    """Which branch the frozen engine attributed this session to (if any)."""
    if record.outcome == "SIGNAL":
        return record.setup
    if record.outcome == "NO_TRADE":
        if record.reason in A_OWNED_NO_TRADE_REASONS:
            return A
        if record.reason in B_OWNED_NO_TRADE_REASONS:
            return B
    return None


# ---------------------------------------------------------------------------
# geometry validation (explicit, non-repairing)
# ---------------------------------------------------------------------------


def _close_to(a: float, b: float, scale: float) -> bool:
    return abs(a - b) <= max(GEOMETRY_REL_TOL * max(1.0, abs(scale)), 1e-12)


def geometry_checks(
    branch: str,
    decision,
    box: ReferenceBox,
    trigger_candle: Candle | None,
) -> dict[str, bool | None]:
    """Explicit evaluation of the frozen STV2 entry/stop/target geometry."""
    entry = decision.entry
    stop = decision.stop_loss
    risk = decision.risk_distance
    long_side = decision.direction == "LONG"
    scale = max(abs(entry), 1.0)

    checks: dict[str, bool | None] = {
        "positive_risk_distance": risk is not None and risk > 0,
        "quarter_reference_range_stop": risk is not None and _close_to(risk, box.r0, scale),
        "stop_on_correct_side_of_entry": (stop < entry) if long_side else (stop > entry),
        "target_direction_valid": (
            (decision.target_4r > entry and decision.target_5r > decision.target_4r)
            if long_side
            else (decision.target_4r < entry and decision.target_5r < decision.target_4r)
        ),
        "target_4r_distance_valid": _close_to(abs(decision.target_4r - entry), 4.0 * risk, scale),
        "target_5r_distance_valid": _close_to(abs(decision.target_5r - entry), 5.0 * risk, scale),
    }

    if branch == A:
        checks["branch_entry_geometry_valid"] = (
            trigger_candle is not None and _close_to(entry, trigger_candle.close, scale)
        )
        if trigger_candle is None:
            checks["sweep_stop_protects_extreme"] = None
        elif long_side:
            checks["sweep_stop_protects_extreme"] = stop < trigger_candle.low
        else:
            checks["sweep_stop_protects_extreme"] = stop > trigger_candle.high
    elif branch == B:
        boundary = box.low if long_side else box.high
        checks["branch_entry_geometry_valid"] = _close_to(entry, boundary, scale)
        checks["sweep_stop_protects_extreme"] = None
    else:  # C — entry is the reference equilibrium (EQ / mid)
        checks["branch_entry_geometry_valid"] = _close_to(entry, box.mid, scale)
        checks["sweep_stop_protects_extreme"] = None
    return checks


# ---------------------------------------------------------------------------
# analysis-unit construction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FunnelBuild:
    units: tuple[AnalysisUnit, ...]
    records: tuple[Stv2AnalysisUnitRecord, ...]
    outcomes_net_r: dict[str, float]
    outcomes_gross_r: dict[str, float]
    partition: dict
    reconciliation: dict


def build_analysis_units(
    role: str,
    bars_by_symbol: Mapping[str, tuple[MarketBar, ...]],
    dataset_sha256_by_symbol: Mapping[str, str],
) -> FunnelBuild:
    """Construct every analysis unit of ``role`` and run the strategy funnel.

    The sealed holdout fails closed before anything else happens.
    """
    if role == "SEALED_HOLDOUT":
        raise HoldoutAccessError(
            "STV2 strategy-funnel analysis may never read the sealed holdout partition"
        )
    bounds = partition_bounds(role)
    holdout_start, holdout_end = PARTITIONS["SEALED_HOLDOUT"]
    if bounds[0] < holdout_end and bounds[1] > holdout_start:
        raise HoldoutAccessError("requested partition intersects the sealed holdout")

    missing = [s for s in SYMBOLS if s not in dataset_sha256_by_symbol]
    if missing:
        raise ValueError(f"missing frozen dataset sha256 for: {missing}")

    # Reuse the campaign's single evaluation implementation => identical
    # decisions, fills, friction and trade records as the economic campaign.
    session_records, trades, friction_by_trade = evaluate_window(
        bounds[0], bounds[1], bars_by_symbol
    )
    trades_by_id: dict[str, CampaignTrade] = {t.trade_id: t for t in trades}
    records_by_key = {(r.symbol, r.session, r.trading_date): r for r in session_records}

    partition_bars = {
        symbol: tuple(b for b in bars if bounds[0] <= b.timestamp < bounds[1])
        for symbol, bars in bars_by_symbol.items()
    }

    units: list[AnalysisUnit] = []
    for (symbol, session, trading_date_s), record in sorted(records_by_key.items()):
        bars = partition_bars.get(symbol, ())
        trading_date = datetime.fromisoformat(trading_date_s).date()
        window = session_window(session, trading_date)
        slice_ = build_window_slice(session, trading_date, bars)
        units.extend(
            _units_for_session(
                symbol=symbol,
                session=session,
                trading_date_s=trading_date_s,
                window=window,
                slice_=slice_,
                record=record,
                trades_by_id=trades_by_id,
                friction_by_trade=friction_by_trade,
                dataset_sha256=dataset_sha256_by_symbol[symbol],
            )
        )

    units_t = tuple(units)
    _assert_identity_integrity(units_t)
    ledger = tuple(_to_record(u) for u in units_t)
    outcomes_net = {
        u.analysis_unit_id: u.economics.net_r
        for u in units_t
        if u.closed_trade and u.economics.net_r is not None
    }
    outcomes_gross = {
        u.analysis_unit_id: u.economics.gross_r
        for u in units_t
        if u.closed_trade and u.economics.gross_r is not None
    }
    reconciliation = _reconcile(units_t, trades, friction_by_trade)

    return FunnelBuild(
        units=units_t,
        records=ledger,
        outcomes_net_r=outcomes_net,
        outcomes_gross_r=outcomes_gross,
        partition={
            "role": role,
            "start": bounds[0].isoformat(),
            "end": bounds[1].isoformat(),
            "session_observations": len(session_records),
            "analysis_units": len(units_t),
            "holdout_touched": False,
        },
        reconciliation=reconciliation,
    )


def _units_for_session(
    *,
    symbol: str,
    session: str,
    trading_date_s: str,
    window,
    slice_,
    record: SessionRecord,
    trades_by_id: Mapping[str, CampaignTrade],
    friction_by_trade: Mapping[str, float],
    dataset_sha256: str,
) -> list[AnalysisUnit]:
    trading_date = datetime.fromisoformat(trading_date_s).date()
    event_identity = event_identity_for_session(session, trading_date, window.trade_start)

    def identity(branch: str) -> dict:
        return {
            "analysis_unit_id": compute_analysis_unit_id(
                candidate_id=CANONICAL_CANDIDATE_ID,
                symbol=symbol,
                session=session,
                branch=branch,
                trading_date=trading_date_s,
                event_identity=event_identity,
                dataset_sha256=dataset_sha256,
            ),
            "candidate_id": CANONICAL_CANDIDATE_ID,
            "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "symbol": symbol,
            "session": session,
            "branch": branch,
            "segment": segment_id(symbol, session, branch),
            "trading_date": trading_date_s,
            "opportunity_timestamp": window.trade_start.isoformat(),
            "event_sequence": 0,
            "event_identity": event_identity,
            "dataset_sha256": dataset_sha256,
        }

    # ---------------- CONTEXT -------------------------------------------
    context_features = {
        "supported_symbol": symbol in SYMBOLS,
        "supported_session": session in SESSIONS,
        "reference_window": [window.reference_start.isoformat(), window.reference_end.isoformat()],
        "trade_window": [window.trade_start.isoformat(), window.trade_end.isoformat()],
        "reference_bars_present": slice_.reference_count,
        "reference_bars_expected": window.reference_bars_expected,
        "trade_bars_present": slice_.trade_count,
        "reference_box_frozen_before_trade_window": window.reference_end <= window.trade_start,
    }

    if not slice_.valid:
        ctx = StageEvaluation(
            FunnelStage.CONTEXT, UnitStatus.DATA_INVALID, False,
            reason=slice_.reason, features=context_features,
        )
        return [
            AnalysisUnit(**identity(branch), stages=(ctx,), economics=UnitEconomics(),
                         diagnostics={"engine_outcome": record.outcome, "engine_reason": record.reason})
            for branch in BRANCHES
        ]

    reference = _to_candles(slice_.reference_bars)
    trade = _to_candles(slice_.trade_bars)
    box = reference_box(reference)
    context_features.update(
        {
            "reference_high": box.high,
            "reference_low": box.low,
            "reference_range": box.range,
            "positive_reference_range": box.range > 0,
            "no_future_leakage": max(c.time for c in reference) < window.trade_start,
        }
    )

    if box.range <= 0 or record.outcome == "DATA_INVALID":
        ctx = StageEvaluation(
            FunnelStage.CONTEXT, UnitStatus.DATA_INVALID, False,
            reason=record.reason or "DATA_INVALID_NON_POSITIVE_REFERENCE_RANGE",
            features=context_features,
        )
        return [
            AnalysisUnit(**identity(branch), stages=(ctx,), economics=UnitEconomics(),
                         diagnostics={"engine_outcome": record.outcome, "engine_reason": record.reason})
            for branch in BRANCHES
        ]

    ctx = StageEvaluation(FunnelStage.CONTEXT, UnitStatus.PASSED, True, features=context_features)
    owner = owning_branch(record)
    evaluation = record.evaluation
    decision = evaluation.decision if evaluation else None

    out: list[AnalysisUnit] = []
    for branch in BRANCHES:
        stages: list[StageEvaluation] = [ctx]
        diagnostics: dict[str, Any] = {
            "engine_outcome": record.outcome,
            "engine_reason": record.reason,
            "engine_owning_branch": owner,
        }

        # ------------- LOCATION ----------------------------------------
        loc_features = location_evidence(branch, box, trade)
        loc_reached = loc_features["low_side_interactions"] > 0 or loc_features["high_side_interactions"] > 0
        stages.append(
            StageEvaluation(
                FunnelStage.LOCATION,
                UnitStatus.PASSED if loc_reached else UnitStatus.FAILED,
                loc_reached,
                reason=None if loc_reached else "LOCATION_STRUCTURAL_AREA_NOT_REACHED",
                features=loc_features,
            )
        )
        if not loc_reached:
            out.append(_unit(identity(branch), stages, UnitEconomics(), diagnostics))
            continue

        # ------------- TRIGGER -----------------------------------------
        raw = raw_trigger_scan(branch, box, trade)
        diagnostics["branch_rule_fired"] = raw.fired
        diagnostics["branch_rule_ambiguous"] = raw.ambiguous
        diagnostics["branch_rule_direction"] = raw.direction
        trig_features = {
            "branch_rule_fired": raw.fired,
            "branch_rule_ambiguous": raw.ambiguous,
            "branch_rule_direction": raw.direction,
            "branch_rule_candle_time": raw.candle_time.isoformat() if raw.candle_time else None,
            "engine_owning_branch": owner,
            "frozen_priority_index": BRANCH_PRIORITY[branch],
        }

        if owner == branch:
            if record.outcome == "NO_TRADE" and record.reason == AMBIGUOUS_TRIGGER_REASONS.get(branch):
                stages.append(
                    StageEvaluation(
                        FunnelStage.TRIGGER, UnitStatus.AMBIGUOUS, False,
                        reason=record.reason, features=trig_features,
                    )
                )
                out.append(_unit(identity(branch), stages, UnitEconomics(), diagnostics))
                continue
            stages.append(StageEvaluation(FunnelStage.TRIGGER, UnitStatus.PASSED, True, features=trig_features))
        else:
            if raw.fired and owner is not None and BRANCH_PRIORITY[owner] < BRANCH_PRIORITY[branch]:
                reason = f"TRIGGER_PREEMPTED_BY_{owner}"
                status = UnitStatus.FAILED
            elif raw.ambiguous:
                # own rule is ambiguous but a higher-priority branch owned the
                # session: record the ambiguity honestly, fail closed.
                reason = f"TRIGGER_AMBIGUOUS_{branch}_NOT_OWNED_BY_ENGINE"
                status = UnitStatus.AMBIGUOUS
            elif raw.fired:
                raise FunnelReconciliationError(
                    f"{branch} rule fired at {symbol}/{session}/{trading_date_s} but the frozen "
                    f"engine attributed the session to {owner!r}; funnel cannot be reconciled"
                )
            else:
                reason = "TRIGGER_RULE_NOT_MET"
                status = UnitStatus.FAILED
            stages.append(StageEvaluation(FunnelStage.TRIGGER, status, False, reason=reason, features=trig_features))
            out.append(_unit(identity(branch), stages, UnitEconomics(), diagnostics))
            continue

        # ------------- GEOMETRY ----------------------------------------
        if record.outcome == "NO_TRADE":
            # Frozen engine triggered this branch but rejected its geometry.
            stages.append(
                StageEvaluation(
                    FunnelStage.GEOMETRY, UnitStatus.FAILED, False,
                    reason=record.reason,
                    features={"frozen_geometry_rejection": record.reason,
                              "reference_range": box.range, "quarter_range_r0": box.r0},
                )
            )
            out.append(_unit(identity(branch), stages, UnitEconomics(), diagnostics))
            continue

        trigger_candle = next((c for c in trade if c.time == decision.signal_timestamp), None)
        checks = geometry_checks(branch, decision, box, trigger_candle)
        failed = [name for name, ok in checks.items() if ok is False]
        geo_features = {
            **checks,
            "entry": decision.entry,
            "stop_loss": decision.stop_loss,
            "risk_distance": decision.risk_distance,
            "quarter_range_r0": box.r0,
            "target_4r": decision.target_4r,
            "target_5r": decision.target_5r,
            "direction": decision.direction,
            "entry_order_type": decision.entry_order_type,
        }
        if failed:
            raise FunnelReconciliationError(
                f"frozen SIGNAL at {symbol}/{session}/{trading_date_s}/{branch} violates its own "
                f"geometry contract: {failed}"
            )
        stages.append(StageEvaluation(FunnelStage.GEOMETRY, UnitStatus.PASSED, True, features=geo_features))

        # ------------- EXECUTION ---------------------------------------
        trade_id = f"STV2|{symbol}|{session}|{trading_date_s}|{branch}"
        campaign_trade = trades_by_id.get(trade_id)
        never_workable = bool((evaluation.intent_metadata or {}).get("never_workable"))
        exec_features = {
            "order_type": decision.entry_order_type,
            "workable_limit_bars": evaluation.workable_limit_bars,
            "never_workable": never_workable,
            "trade_id": trade_id,
        }

        if campaign_trade is None:
            if not never_workable:
                raise FunnelReconciliationError(
                    f"no campaign trade record for geometry-valid proposal {trade_id}"
                )
            stages.append(
                StageEvaluation(
                    FunnelStage.EXECUTION, UnitStatus.EXPIRED, False,
                    reason="LIMIT_NEVER_WORKABLE_IN_TRADE_WINDOW", features=exec_features,
                )
            )
            out.append(_unit(identity(branch), stages, UnitEconomics(), diagnostics))
            continue

        exec_features["replay_status"] = campaign_trade.status
        exec_features["same_bar_ambiguities"] = campaign_trade.same_bar_ambiguities
        if campaign_trade.status == "UNFILLED":
            stages.append(
                StageEvaluation(FunnelStage.EXECUTION, UnitStatus.UNFILLED, False,
                                reason="EXECUTION_UNFILLED", features=exec_features)
            )
            out.append(_unit(identity(branch), stages, UnitEconomics(
                order_type=campaign_trade.order_type, direction=campaign_trade.direction,
                risk_distance=campaign_trade.risk_distance,
                same_bar_ambiguities=campaign_trade.same_bar_ambiguities,
            ), diagnostics))
            continue
        if campaign_trade.status == "EXPIRED":
            stages.append(
                StageEvaluation(FunnelStage.EXECUTION, UnitStatus.EXPIRED, False,
                                reason="EXECUTION_LIMIT_EXPIRED", features=exec_features)
            )
            out.append(_unit(identity(branch), stages, UnitEconomics(
                order_type=campaign_trade.order_type, direction=campaign_trade.direction,
                risk_distance=campaign_trade.risk_distance,
                same_bar_ambiguities=campaign_trade.same_bar_ambiguities,
            ), diagnostics))
            continue

        stages.append(StageEvaluation(FunnelStage.EXECUTION, UnitStatus.PASSED, True, features=exec_features))

        # ------------- OUTCOME -----------------------------------------
        friction_r = friction_by_trade.get(trade_id)
        if campaign_trade.status == "FILLED_CLOSED":
            outcome_status = UnitStatus.CLOSED
            gross_r = campaign_trade.gross_r
            net_r = None if gross_r is None or friction_r is None else gross_r - friction_r
        else:  # FILLED_OPEN_AT_END — censored, never counted as a closed trade
            outcome_status = UnitStatus.OPEN_AT_END
            gross_r = None
            net_r = None

        holding = campaign_trade.holding_seconds
        out.append(
            _unit(
                identity(branch), stages,
                UnitEconomics(
                    outcome_status=outcome_status,
                    order_type=campaign_trade.order_type,
                    direction=campaign_trade.direction,
                    entry_time=campaign_trade.entry_time,
                    entry_price=campaign_trade.entry_price,
                    exit_time=campaign_trade.exit_time,
                    exit_price=campaign_trade.exit_price,
                    exit_reason=campaign_trade.exit_reason,
                    risk_distance=campaign_trade.risk_distance,
                    gross_r=gross_r,
                    friction_r=friction_r,
                    net_r=net_r,
                    tp1_4r_hit=campaign_trade.tp1_4r_hit,
                    runner_5r_hit=campaign_trade.runner_5r_hit,
                    runner_breakeven=campaign_trade.runner_breakeven,
                    runner_open_at_end=campaign_trade.runner_open_at_end,
                    same_bar_ambiguities=campaign_trade.same_bar_ambiguities,
                    bars_held=campaign_trade.bars_held,
                    holding_hours=None if holding is None else holding / 3600.0,
                ),
                diagnostics,
            )
        )
    return out


def _unit(identity: dict, stages: list[StageEvaluation], economics: UnitEconomics, diagnostics: dict) -> AnalysisUnit:
    return AnalysisUnit(**identity, stages=tuple(stages), economics=economics, diagnostics=dict(diagnostics))


def _to_candles(bars) -> tuple[Candle, ...]:
    return tuple(Candle(time=b.timestamp, open=b.open, high=b.high, low=b.low, close=b.close) for b in bars)


def _assert_identity_integrity(units: Sequence[AnalysisUnit]) -> None:
    seen: dict[str, AnalysisUnit] = {}
    for unit in units:
        clash = seen.get(unit.analysis_unit_id)
        if clash is not None:
            raise FunnelReconciliationError(
                "analysis_unit_id collision between "
                f"{clash.symbol}/{clash.session}/{clash.branch}/{clash.trading_date} and "
                f"{unit.symbol}/{unit.session}/{unit.branch}/{unit.trading_date}"
            )
        seen[unit.analysis_unit_id] = unit
        if unit.candidate_id != CANONICAL_CANDIDATE_ID:
            raise FunnelReconciliationError(f"canonical candidate identity drift: {unit.candidate_id}")


def identity_collisions(units: Sequence[AnalysisUnit]) -> int:
    return len(units) - len({u.analysis_unit_id for u in units})


def _to_record(unit: AnalysisUnit) -> Stv2AnalysisUnitRecord:
    as_of = datetime.fromisoformat(unit.opportunity_timestamp)
    results = []
    for evaluation in unit.stages:
        results.append(
            FunnelStageResult(
                candidate_id=unit.candidate_id,
                stage=evaluation.stage,
                passed=evaluation.retained,
                as_of=as_of,
                rule_results=(
                    RuleResult(
                        rule_id=f"STV2_{evaluation.stage.value}_{unit.branch}",
                        rule_version=STRATEGY_VERSION,
                        rule_hash=unit.analysis_unit_id[:16],
                        passed=evaluation.retained,
                        evaluated_at=as_of,
                        features={},
                        failure_reason=evaluation.reason,
                        rejection_code=evaluation.reason if not evaluation.retained else None,
                    ),
                ),
                failure_reason=evaluation.reason,
                rejection_codes=() if evaluation.retained or not evaluation.reason else (evaluation.reason,),
            )
        )
    return Stv2AnalysisUnitRecord(
        candidate_id=unit.candidate_id,
        instrument=unit.symbol,
        strategy_id=unit.strategy_id,
        strategy_version=unit.strategy_version,
        strategy_sha256=unit.analysis_unit_id,
        dataset_sha256=unit.dataset_sha256,
        stage_results=tuple(results),
        analysis_unit_id=unit.analysis_unit_id,
        segment_id=unit.segment,
    )


def _reconcile(
    units: Sequence[AnalysisUnit],
    trades: Sequence[CampaignTrade],
    friction_by_trade: Mapping[str, float],
) -> dict:
    """Prove the funnel's economics equal the campaign's own trade records."""
    campaign_closed = [t for t in trades if t.closed and t.gross_r is not None]
    campaign_net = sum(t.gross_r - friction_by_trade.get(t.trade_id, 0.0) for t in campaign_closed)
    funnel_closed = [u for u in units if u.closed_trade]
    funnel_net = sum(u.economics.net_r for u in funnel_closed if u.economics.net_r is not None)
    filled_campaign = sum(1 for t in trades if t.filled)
    filled_funnel = sum(1 for u in units if u.retained_at(FunnelStage.EXECUTION))
    ok = (
        len(campaign_closed) == len(funnel_closed)
        and filled_campaign == filled_funnel
        and abs(campaign_net - funnel_net) < 1e-9
    )
    if not ok:
        raise FunnelReconciliationError(
            f"funnel/campaign mismatch: closed {len(funnel_closed)} vs {len(campaign_closed)}, "
            f"filled {filled_funnel} vs {filled_campaign}, net_r {funnel_net} vs {campaign_net}"
        )
    return {
        "campaign_closed_trades": len(campaign_closed),
        "funnel_closed_trades": len(funnel_closed),
        "campaign_filled": filled_campaign,
        "funnel_filled": filled_funnel,
        "campaign_net_r": round(campaign_net, 10),
        "funnel_net_r": round(funnel_net, 10),
        "reconciled": True,
    }


# ---------------------------------------------------------------------------
# metric primitives
# ---------------------------------------------------------------------------


def profit_factor(values: Sequence[float]) -> tuple[float | None, str]:
    """PF with honest infinity/undefined semantics (never a sentinel like 999)."""
    if not values:
        return None, "UNDEFINED_NO_CLOSED_TRADES"
    gains = sum(v for v in values if v > 0)
    losses = abs(sum(v for v in values if v < 0))
    if losses > 0:
        return gains / losses, "DEFINED"
    if gains > 0:
        return None, "INFINITE_NO_LOSING_TRADES"
    return None, "UNDEFINED_NO_GROSS_PROFIT_AND_NO_LOSS"


def _mean(values: Sequence[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)


# ---------------------------------------------------------------------------
# stage statistics
# ---------------------------------------------------------------------------

#: Stages that are structurally impossible for a branch (none, for STV2 — all
#: five filtering stages are reachable for every branch).  Kept explicit so a
#: future branch with a degenerate stage is marked rather than silently absent.
STRUCTURALLY_IMPOSSIBLE_STAGES: dict[str, tuple[str, ...]] = {}


def _cohort_stats(cohort: Sequence[AnalysisUnit]) -> dict:
    """Downstream-conditional economics of the closed trades inside a cohort.

    'Cohort' = observations retained at a stage.  Only those that eventually
    produced a CLOSED trade under UNCHANGED downstream rules contribute
    economics.  Rejected / unfilled / open observations contribute NOTHING —
    they are never imputed as 0R.
    """
    closed = [u for u in cohort if u.closed_trade]
    net = [u.economics.net_r for u in closed if u.economics.net_r is not None]
    gross = [u.economics.gross_r for u in closed if u.economics.gross_r is not None]
    friction = [u.economics.friction_r for u in closed if u.economics.friction_r is not None]

    wins = sum(1 for r in net if r > BE_TOLERANCE)
    losses = sum(1 for r in net if r < -BE_TOLERANCE)
    breakeven = sum(1 for r in net if abs(r) <= BE_TOLERANCE)
    win_rate = (wins / len(net)) if net else None
    ci_low, ci_high = wilson_interval(wins, len(net))
    net_pf, net_pf_status = profit_factor(net)
    gross_pf, gross_pf_status = profit_factor(gross)

    return {
        "closed_trades": len(closed),
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "win_rate": _round(win_rate),
        "win_ci95_low": _round(ci_low),
        "win_ci95_high": _round(ci_high),
        "conditional_downstream_gross_expectancy_r": _round(_mean(gross)),
        "conditional_downstream_net_expectancy_r": _round(_mean(net)),
        "conditional_downstream_gross_pf": _round(gross_pf, 6),
        "conditional_downstream_gross_pf_status": gross_pf_status,
        "conditional_downstream_net_pf": _round(net_pf, 6),
        "conditional_downstream_net_pf_status": net_pf_status,
        "conditional_downstream_gross_r": _round(sum(gross)) if gross else None,
        "conditional_downstream_net_r": _round(sum(net)) if net else None,
        "friction_r": _round(sum(friction)) if friction else None,
        "average_cost_r": _round(_mean(friction)),
    }


def _fate_counts(cohort: Sequence[AnalysisUnit]) -> dict:
    """Downstream fate of a stage cohort (not imputed economics — pure counts)."""
    return {
        "signals": sum(1 for u in cohort if u.retained_at(FunnelStage.TRIGGER)),
        "geometry_valid": sum(1 for u in cohort if u.retained_at(FunnelStage.GEOMETRY)),
        "fills": sum(1 for u in cohort if u.retained_at(FunnelStage.EXECUTION)),
        "unfilled": sum(
            1 for u in cohort
            if (s := u.stage(FunnelStage.EXECUTION)) is not None and s.status == UnitStatus.UNFILLED
        ),
        "expired": sum(
            1 for u in cohort
            if (s := u.stage(FunnelStage.EXECUTION)) is not None and s.status == UnitStatus.EXPIRED
        ),
        "open_at_end": sum(1 for u in cohort if u.economics.outcome_status == UnitStatus.OPEN_AT_END),
    }


def stage_rows_for_units(
    units: Sequence[AnalysisUnit],
    *,
    scope: Mapping[str, str],
) -> list[dict]:
    """One row per filtering stage for a set of analysis units."""
    rows: list[dict] = []
    prev_stats: dict | None = None
    for index, stage in enumerate(FILTER_STAGES):
        inputs = [u for u in units if u.reached(stage)]
        retained = [u for u in inputs if u.retained_at(stage)]
        stats = _cohort_stats(retained)
        fates = _fate_counts(retained)

        data_invalid = sum(
            1 for u in inputs
            if (s := u.stage(stage)) is not None and s.status == UnitStatus.DATA_INVALID
        )
        ambiguity = sum(
            1 for u in inputs
            if (s := u.stage(stage)) is not None and s.status == UnitStatus.AMBIGUOUS
        )
        if stage == FunnelStage.EXECUTION:
            ambiguity += sum(u.economics.same_bar_ambiguities for u in retained)

        retained_pct = (len(retained) / len(inputs) * 100.0) if inputs else None
        win_lift = None
        exp_shift = None
        if prev_stats is not None:
            if stats["win_rate"] is not None and prev_stats["win_rate"] is not None:
                win_lift = round((stats["win_rate"] - prev_stats["win_rate"]) * 100.0, 6)
            a = stats["conditional_downstream_net_expectancy_r"]
            b = prev_stats["conditional_downstream_net_expectancy_r"]
            if a is not None and b is not None:
                exp_shift = round(a - b, 6)

        rows.append(
            {
                **dict(scope),
                "stage": stage.value,
                "stage_index": index,
                "structurally_possible": True,
                "stage_input_count": len(inputs),
                "stage_retained_count": len(retained),
                "stage_retained_pct": _round(retained_pct, 4),
                "data_invalid_count": data_invalid,
                "ambiguity_count": ambiguity,
                **fates,
                **stats,
                "win_rate_lift_pp": win_lift,
                "conditional_net_expectancy_shift_r": exp_shift,
                "metric_semantics": {
                    "retention": "ALWAYS_VALID",
                    "economics": "CONDITIONAL_DOWNSTREAM_CLOSED_TRADES_ONLY",
                    "note": (
                        "Economic columns describe ONLY the observations retained at this "
                        "stage that later produced a CLOSED trade under unchanged downstream "
                        "rules. They are NOT counterfactual expectancies for rejected "
                        "observations, and rejected/unfilled observations are never imputed as 0R."
                    ),
                },
            }
        )
        prev_stats = stats
    return rows


def outcome_summary_for_units(units: Sequence[AnalysisUnit], scope: Mapping[str, str]) -> dict:
    """OUTCOME summary (not a filtering stage)."""
    filled = [u for u in units if u.retained_at(FunnelStage.EXECUTION)]
    closed = [u for u in units if u.closed_trade]
    open_at_end = [u for u in units if u.economics.outcome_status == UnitStatus.OPEN_AT_END]
    stats = _cohort_stats(filled)
    holding = [u.economics.holding_hours for u in closed if u.economics.holding_hours is not None]
    return {
        **dict(scope),
        "stage": "OUTCOME",
        "filled": len(filled),
        "closed_trades": len(closed),
        "open_at_end": len(open_at_end),
        "tp1_4r_hits": sum(1 for u in closed if u.economics.tp1_4r_hit),
        "runner_5r_hits": sum(1 for u in closed if u.economics.runner_5r_hit),
        "runner_breakeven": sum(1 for u in closed if u.economics.runner_breakeven),
        "average_holding_hours": _round(_mean(holding), 4),
        **{k: v for k, v in stats.items() if k != "closed_trades"},
    }


# ---------------------------------------------------------------------------
# matrices and views
# ---------------------------------------------------------------------------


def _subset(units: Sequence[AnalysisUnit], **filters) -> list[AnalysisUnit]:
    return [u for u in units if all(getattr(u, k) == v for k, v in filters.items())]


def build_segment_manifest(units: Sequence[AnalysisUnit]) -> dict:
    segments = []
    for key in all_segment_keys():
        subset = _subset(units, branch=key.branch, symbol=key.symbol, session=key.session)
        segments.append(
            {
                "segment_id": key.segment_id,
                "branch": key.branch,
                "symbol": key.symbol,
                "session": key.session,
                "analysis_units": len(subset),
                "trading_dates": len({u.trading_date for u in subset}),
            }
        )
    return {
        "candidate_id": CANONICAL_CANDIDATE_ID,
        "expected_segments": EXPECTED_SEGMENTS,
        "segments": len(segments),
        "segments_match_expected": len(segments) == EXPECTED_SEGMENTS,
        "expected_analysis_units_note": (
            "EXPECTED_ANALYSIS_UNITS != 24. The analysis-unit count is data-driven: it is the "
            "number of (trading_date x symbol x session x branch) observations produced by the "
            "frozen DEV dataset and stage construction."
        ),
        "analysis_units": len(units),
        "identity_collisions": identity_collisions(units),
        "segment_rows": segments,
    }


#: Diagnostically meaningful feature whitelist for the persisted unit artifact.
#: Full feature payloads stay available in memory; the artifact keeps the keys
#: needed to reproduce every stage decision without a 19 MB file.
ARTIFACT_FEATURE_KEYS: dict[str, tuple[str, ...]] = {
    "CONTEXT": ("reference_bars_present", "reference_bars_expected", "reference_high",
                "reference_low", "reference_range", "reference_box_frozen_before_trade_window",
                "no_future_leakage"),
    "LOCATION": ("low_side_interactions", "high_side_interactions", "first_interaction_time"),
    "TRIGGER": ("branch_rule_fired", "branch_rule_ambiguous", "branch_rule_direction",
                "branch_rule_candle_time", "engine_owning_branch"),
    "GEOMETRY": ("entry", "stop_loss", "risk_distance", "quarter_range_r0", "target_4r",
                 "target_5r", "direction", "entry_order_type", "sweep_stop_protects_extreme",
                 "frozen_geometry_rejection"),
    "EXECUTION": ("order_type", "replay_status", "workable_limit_bars", "never_workable",
                  "same_bar_ambiguities"),
}


def unit_artifact_row(unit: AnalysisUnit) -> dict:
    """Compact, lossless-for-diagnostics serialization of one analysis unit."""
    row = {
        "analysis_unit_id": unit.analysis_unit_id,
        "candidate_id": unit.candidate_id,
        "symbol": unit.symbol,
        "session": unit.session,
        "branch": unit.branch,
        "segment_id": unit.segment,
        "trading_date": unit.trading_date,
        "opportunity_timestamp": unit.opportunity_timestamp,
        "event_sequence": unit.event_sequence,
        "dataset_sha256": unit.dataset_sha256,
        "terminal_stage": unit.terminal_stage,
        "stages": [
            {
                "stage": s.stage.value,
                "status": s.status.value,
                "retained": s.retained,
                **({"reason": s.reason} if s.reason else {}),
                **(
                    {"features": {k: v for k, v in s.features.items()
                                  if k in ARTIFACT_FEATURE_KEYS.get(s.stage.value, ()) and v is not None}}
                    if s.features else {}
                ),
            }
            for s in unit.stages
        ],
    }
    economics = {k: v for k, v in unit.economics.as_dict().items() if v is not None and v is not False}
    if economics:
        row["economics"] = economics
    return row


def build_context_analysis(units: Sequence[AnalysisUnit]) -> dict:
    """Why CONTEXT observations are discarded (never counted as losses)."""
    per_branch = _subset(units, branch=A)  # CONTEXT is branch-invariant
    invalid = [
        u for u in per_branch
        if (s := u.stage(FunnelStage.CONTEXT)) is not None and s.status == UnitStatus.DATA_INVALID
    ]
    no_bars = [
        u for u in invalid
        if (u.stage(FunnelStage.CONTEXT).features.get("reference_bars_present") == 0)
    ]
    partial = [u for u in invalid if u not in no_bars]
    return {
        "candidate_id": CANONICAL_CANDIDATE_ID,
        "session_observations": len(per_branch),
        "context_valid": len(per_branch) - len(invalid),
        "data_invalid": len(invalid),
        "data_invalid_pct": _round(len(invalid) / len(per_branch) * 100.0 if per_branch else None, 4),
        "data_invalid_no_reference_bars_at_all": len(no_bars),
        "data_invalid_partial_reference_window": len(partial),
        "reasons": _reason_histogram(per_branch, "CONTEXT"),
        "semantics": (
            "DATA_INVALID observations are counted separately and are NEVER converted into "
            "losses or 0R outcomes. Sessions with zero reference bars are non-trading calendar "
            "days (weekends/holidays) inside the DEV date range, not strategy rejections."
        ),
    }


def build_stage_matrix(units: Sequence[AnalysisUnit]) -> dict:
    rows: list[dict] = []
    outcomes: list[dict] = []
    for key in all_segment_keys():
        subset = _subset(units, branch=key.branch, symbol=key.symbol, session=key.session)
        scope = {
            "segment_id": key.segment_id,
            "branch": key.branch,
            "symbol": key.symbol,
            "session": key.session,
        }
        rows.extend(stage_rows_for_units(subset, scope=scope))
        outcomes.append(outcome_summary_for_units(subset, scope))
    return {
        "candidate_id": CANONICAL_CANDIDATE_ID,
        "expected_filter_stage_rows": EXPECTED_FILTER_STAGE_ROWS,
        "filter_stage_rows": len(rows),
        "rows_match_expected": len(rows) == EXPECTED_FILTER_STAGE_ROWS,
        "structurally_impossible_stages": dict(STRUCTURALLY_IMPOSSIBLE_STAGES),
        "rows": rows,
        "outcome_summaries": outcomes,
    }


def _dimension_summary(units: Sequence[AnalysisUnit], attribute: str, values: Iterable[str]) -> dict:
    out: dict[str, Any] = {"dimension": attribute, "summaries": []}
    for value in values:
        subset = _subset(units, **{attribute: value})
        scope = {attribute: value}
        rows = stage_rows_for_units(subset, scope=scope)
        by_stage = {r["stage"]: r for r in rows}
        out["summaries"].append(
            {
                attribute: value,
                "raw_context_n": by_stage["CONTEXT"]["stage_input_count"],
                "context_n": by_stage["CONTEXT"]["stage_retained_count"],
                "location_n": by_stage["LOCATION"]["stage_retained_count"],
                "trigger_n": by_stage["TRIGGER"]["stage_retained_count"],
                "geometry_n": by_stage["GEOMETRY"]["stage_retained_count"],
                "execution_n": by_stage["EXECUTION"]["stage_retained_count"],
                "closed_n": by_stage["EXECUTION"]["closed_trades"],
                "stage_rows": rows,
                "outcome": outcome_summary_for_units(subset, scope),
            }
        )
    return out


def build_branch_summary(units: Sequence[AnalysisUnit]) -> dict:
    return _dimension_summary(units, "branch", BRANCHES)


def build_symbol_summary(units: Sequence[AnalysisUnit]) -> dict:
    return _dimension_summary(units, "symbol", SYMBOLS)


def build_session_summary(units: Sequence[AnalysisUnit]) -> dict:
    return _dimension_summary(units, "session", SESSIONS)


def build_attrition_analysis(units: Sequence[AnalysisUnit]) -> dict:
    transitions = [
        ("CONTEXT", "LOCATION"),
        ("LOCATION", "TRIGGER"),
        ("TRIGGER", "GEOMETRY"),
        ("GEOMETRY", "EXECUTION"),
    ]
    out: list[dict] = []
    for key in all_segment_keys():
        subset = _subset(units, branch=key.branch, symbol=key.symbol, session=key.session)
        by_stage = {r["stage"]: r for r in stage_rows_for_units(subset, scope={})}
        entry = {
            "segment_id": key.segment_id,
            "branch": key.branch,
            "symbol": key.symbol,
            "session": key.session,
            "transitions": [],
        }
        for src, dst in transitions:
            retained_src = by_stage[src]["stage_retained_count"]
            retained_dst = by_stage[dst]["stage_retained_count"]
            lost = retained_src - retained_dst
            entry["transitions"].append(
                {
                    "from_stage": src,
                    "to_stage": dst,
                    "input_count": retained_src,
                    "retained_count": retained_dst,
                    "attrition_count": lost,
                    "attrition_pct": _round((lost / retained_src * 100.0) if retained_src else None, 4),
                    "rejection_reasons": _reason_histogram(subset, dst),
                }
            )
        out.append(entry)
    return {"candidate_id": CANONICAL_CANDIDATE_ID, "segments": out}


def _reason_histogram(units: Sequence[AnalysisUnit], stage_name: str) -> dict[str, int]:
    stage = FunnelStage(stage_name)
    hist: dict[str, int] = {}
    for unit in units:
        if not unit.reached(stage):
            continue
        evaluation = unit.stage(stage)
        if evaluation is None or evaluation.retained:
            continue
        key = evaluation.reason or evaluation.status.value
        hist[key] = hist.get(key, 0) + 1
    return dict(sorted(hist.items(), key=lambda kv: (-kv[1], kv[0])))


def build_geometry_analysis(units: Sequence[AnalysisUnit]) -> dict:
    rows: list[dict] = []
    for key in all_segment_keys():
        subset = _subset(units, branch=key.branch, symbol=key.symbol, session=key.session)
        triggered = [u for u in subset if u.retained_at(FunnelStage.TRIGGER)]
        valid = [u for u in triggered if u.retained_at(FunnelStage.GEOMETRY)]
        reasons = _reason_histogram(subset, "GEOMETRY")
        sweep_stop = reasons.get("SWEEP_STOP_DOES_NOT_PROTECT_EXTREME", 0)
        other = {k: v for k, v in reasons.items() if k != "SWEEP_STOP_DOES_NOT_PROTECT_EXTREME"}
        rows.append(
            {
                "segment_id": key.segment_id,
                "branch": key.branch,
                "symbol": key.symbol,
                "session": key.session,
                "triggered": len(triggered),
                "geometry_valid": len(valid),
                "geometry_rejected": len(triggered) - len(valid),
                "geometry_rejection_pct": _round(
                    ((len(triggered) - len(valid)) / len(triggered) * 100.0) if triggered else None, 4
                ),
                "sweep_stop_does_not_protect_extreme": sweep_stop,
                "sweep_stop_rejection_pct": _round(
                    (sweep_stop / len(triggered) * 100.0) if triggered else None, 4
                ),
                "other_geometry_rejection_reasons": other,
            }
        )
    return {"candidate_id": CANONICAL_CANDIDATE_ID, "segments": rows}


def build_execution_analysis(units: Sequence[AnalysisUnit]) -> dict:
    rows: list[dict] = []
    for key in all_segment_keys():
        subset = _subset(units, branch=key.branch, symbol=key.symbol, session=key.session)
        eligible = [u for u in subset if u.retained_at(FunnelStage.GEOMETRY)]
        filled = [u for u in eligible if u.retained_at(FunnelStage.EXECUTION)]
        statuses = [u.stage(FunnelStage.EXECUTION) for u in eligible]
        unfilled = sum(1 for s in statuses if s is not None and s.status == UnitStatus.UNFILLED)
        expired = sum(1 for s in statuses if s is not None and s.status == UnitStatus.EXPIRED)
        never_workable = sum(
            1 for s in statuses
            if s is not None and s.reason == "LIMIT_NEVER_WORKABLE_IN_TRADE_WINDOW"
        )
        rows.append(
            {
                "segment_id": key.segment_id,
                "branch": key.branch,
                "symbol": key.symbol,
                "session": key.session,
                "order_type": _dominant_order_type(eligible),
                "geometry_valid_signals": len(eligible),
                "fills": len(filled),
                "unfilled": unfilled,
                "expired": expired,
                "expired_never_workable": never_workable,
                "same_bar_ambiguities": sum(u.economics.same_bar_ambiguities for u in subset),
                "fill_rate": _round((len(filled) / len(eligible)) if eligible else None),
                "closed_trades": sum(1 for u in filled if u.closed_trade),
                "open_at_end": sum(
                    1 for u in filled if u.economics.outcome_status == UnitStatus.OPEN_AT_END
                ),
            }
        )
    return {"candidate_id": CANONICAL_CANDIDATE_ID, "segments": rows}


def _dominant_order_type(units: Sequence[AnalysisUnit]) -> str | None:
    for unit in units:
        geo = unit.stage(FunnelStage.GEOMETRY)
        if geo is not None and geo.features.get("entry_order_type"):
            return str(geo.features["entry_order_type"])
    return None


def build_friction_analysis(units: Sequence[AnalysisUnit]) -> dict:
    rows: list[dict] = []
    destroyed: list[str] = []
    for key in all_segment_keys():
        subset = _subset(units, branch=key.branch, symbol=key.symbol, session=key.session)
        closed = [u for u in subset if u.closed_trade]
        if not closed:
            rows.append(
                {
                    "segment_id": key.segment_id,
                    "branch": key.branch,
                    "symbol": key.symbol,
                    "session": key.session,
                    "closed_trades": 0,
                    "gross_r": None,
                    "net_r": None,
                    "friction_r": None,
                    "gross_expectancy_r": None,
                    "net_expectancy_r": None,
                    "friction_drag_per_trade_r": None,
                    "gross_positive_net_non_positive": None,
                    "note": "no executed trades — friction analysis not applicable",
                }
            )
            continue
        gross = [u.economics.gross_r for u in closed if u.economics.gross_r is not None]
        net = [u.economics.net_r for u in closed if u.economics.net_r is not None]
        friction = [u.economics.friction_r for u in closed if u.economics.friction_r is not None]
        gross_exp, net_exp = _mean(gross), _mean(net)
        flipped = (
            gross_exp is not None and net_exp is not None and gross_exp > 0 and net_exp <= 0
        )
        if flipped:
            destroyed.append(key.segment_id)
        rows.append(
            {
                "segment_id": key.segment_id,
                "branch": key.branch,
                "symbol": key.symbol,
                "session": key.session,
                "closed_trades": len(closed),
                "gross_r": _round(sum(gross)),
                "net_r": _round(sum(net)),
                "friction_r": _round(sum(friction)),
                "gross_expectancy_r": _round(gross_exp),
                "net_expectancy_r": _round(net_exp),
                "friction_drag_per_trade_r": _round(_mean(friction)),
                "gross_positive_net_non_positive": flipped,
                "note": None,
            }
        )
    return {
        "candidate_id": CANONICAL_CANDIDATE_ID,
        "segments": rows,
        "friction_destroyed_segments": destroyed,
        "semantics": (
            "Applied ONLY to actually executed closed trades. Segments without executed "
            "trades report null, never a fabricated zero."
        ),
    }


def build_conditional_expectancy_analysis(units: Sequence[AnalysisUnit]) -> dict:
    rows: list[dict] = []
    for key in all_segment_keys():
        subset = _subset(units, branch=key.branch, symbol=key.symbol, session=key.session)
        stage_rows = stage_rows_for_units(subset, scope={})
        rows.append(
            {
                "segment_id": key.segment_id,
                "branch": key.branch,
                "symbol": key.symbol,
                "session": key.session,
                "stages": [
                    {
                        "stage": r["stage"],
                        "retained": r["stage_retained_count"],
                        "closed_trades": r["closed_trades"],
                        "conditional_downstream_net_expectancy_r": r[
                            "conditional_downstream_net_expectancy_r"
                        ],
                        "conditional_downstream_gross_expectancy_r": r[
                            "conditional_downstream_gross_expectancy_r"
                        ],
                        "conditional_net_expectancy_shift_r": r["conditional_net_expectancy_shift_r"],
                        "win_rate": r["win_rate"],
                        "win_rate_lift_pp": r["win_rate_lift_pp"],
                    }
                    for r in stage_rows
                ],
            }
        )
    return {
        "candidate_id": CANONICAL_CANDIDATE_ID,
        "classification": "DIAGNOSTIC / NON-CAUSAL",
        "interpretation_rule": (
            "These are expectancy shifts among surviving/downstream CLOSED-TRADE cohorts under "
            "sequential filtering. They are diagnostic associations, NOT causal estimates, and "
            "NOT counterfactual expectancies for the observations removed at each stage. No "
            "counterfactual methodology is implemented in this mission."
        ),
        "segments": rows,
    }


# ---------------------------------------------------------------------------
# root-cause classification (calibrated)
# ---------------------------------------------------------------------------

MIN_SAMPLE_FOR_ECONOMIC_CLAIM = 30
#: Minimum number of observations entering a stage before a STRUCTURAL
#: (count-based) claim about that stage is allowed.
MIN_SAMPLE_FOR_STRUCTURAL_CLAIM = 30
LARGE_ATTRITION_PCT = 30.0
LOW_FILL_RATE = 0.60
#: Below this raw-rule fire rate the branch's own predicate really is rare;
#: above it, low authoritative trigger retention is precedence preemption,
#: not trigger weakness.
RARE_RULE_FIRE_RATE = 0.25


def classify_branch_root_cause(units: Sequence[AnalysisUnit], branch: str) -> dict:
    """Calibrated root-cause classification.

    Deliberately conservative: a contributor is only recorded when the
    underlying sample supports it, structural (count) claims are separated
    from economic claims, and precedence preemption is never mislabelled as
    trigger weakness.
    """
    subset = _subset(units, branch=branch)
    rows = {r["stage"]: r for r in stage_rows_for_units(subset, scope={})}
    context_n = rows["CONTEXT"]["stage_retained_count"]
    location_n = rows["LOCATION"]["stage_retained_count"]
    trigger_n = rows["TRIGGER"]["stage_retained_count"]
    geometry_n = rows["GEOMETRY"]["stage_retained_count"]
    execution_n = rows["EXECUTION"]["stage_retained_count"]
    closed_n = rows["EXECUTION"]["closed_trades"]

    raw_fired = sum(1 for u in subset if u.diagnostics.get("branch_rule_fired"))
    preempted = sum(
        1 for u in subset
        if (s := u.stage(FunnelStage.TRIGGER)) is not None
        and s.reason is not None and s.reason.startswith("TRIGGER_PREEMPTED_BY_")
    )
    raw_fire_rate = (raw_fired / location_n) if location_n else None

    evidence: list[str] = []
    contributors: list[str] = []

    loc_to_trig = ((location_n - trigger_n) / location_n * 100.0) if location_n else None
    trig_to_geo = ((trigger_n - geometry_n) / trigger_n * 100.0) if trigger_n else None
    fill_rate = (execution_n / geometry_n) if geometry_n else None

    # --- TRIGGER: weakness vs frozen A->B->C precedence preemption --------
    if location_n >= MIN_SAMPLE_FOR_STRUCTURAL_CLAIM and loc_to_trig is not None and loc_to_trig >= 95.0:
        if raw_fire_rate is not None and raw_fire_rate < RARE_RULE_FIRE_RATE:
            contributors.append("EVIDENCE_SUPPORTS_TRIGGER_WEAKNESS")
            evidence.append(
                f"{branch}: own trigger predicate fires on only {raw_fired}/{location_n} "
                f"({raw_fire_rate:.1%}) LOCATION observations — genuine trigger scarcity"
            )
        else:
            evidence.append(
                f"{branch}: LOCATION->TRIGGER attrition is {loc_to_trig:.1f}% "
                f"({location_n}->{trigger_n}) BUT the branch's own predicate fires on "
                f"{raw_fired}/{location_n} ({raw_fire_rate:.1%}) observations and {preempted} "
                "are removed by the frozen A->B->C precedence. This is precedence preemption, "
                "NOT trigger weakness — it is not classified as a trigger-rule defect."
            )
    elif loc_to_trig is not None:
        evidence.append(
            f"{branch}: LOCATION->TRIGGER attrition {loc_to_trig:.1f}% ({location_n}->{trigger_n}); "
            f"own predicate fired {raw_fired} times, {preempted} removed by frozen precedence"
        )

    # --- GEOMETRY --------------------------------------------------------
    if trigger_n >= MIN_SAMPLE_FOR_STRUCTURAL_CLAIM and trig_to_geo is not None and trig_to_geo >= LARGE_ATTRITION_PCT:
        contributors.append("EVIDENCE_SUPPORTS_GEOMETRY_ATTRITION")
        reasons = _reason_histogram(subset, "GEOMETRY")
        evidence.append(
            f"{branch}: TRIGGER->GEOMETRY attrition {trig_to_geo:.1f}% ({trigger_n}->{geometry_n}); "
            f"rejection reasons {reasons}"
        )
    elif trigger_n and trig_to_geo is not None and trig_to_geo < LARGE_ATTRITION_PCT:
        evidence.append(
            f"{branch}: geometry removes only {trig_to_geo:.1f}% of triggers "
            f"({trigger_n}->{geometry_n}) — geometry is not a material filter for this branch"
        )

    # --- EXECUTION -------------------------------------------------------
    if geometry_n >= MIN_SAMPLE_FOR_STRUCTURAL_CLAIM and fill_rate is not None and fill_rate < LOW_FILL_RATE:
        contributors.append("EVIDENCE_SUPPORTS_EXECUTION_FILL_STARVATION")
        evidence.append(
            f"{branch}: fill rate {fill_rate:.2%} ({execution_n}/{geometry_n} geometry-valid "
            "proposals filled under the frozen order model)"
        )
    elif fill_rate is not None and fill_rate < LOW_FILL_RATE:
        evidence.append(
            f"{branch}: fill rate {fill_rate:.2%} ({execution_n}/{geometry_n}) is low but the "
            f"{geometry_n}-proposal sample is below the {MIN_SAMPLE_FOR_STRUCTURAL_CLAIM}-"
            "observation threshold for a structural claim"
        )

    # --- FRICTION (economic, requires sample) -----------------------------
    gross_exp = rows["EXECUTION"]["conditional_downstream_gross_expectancy_r"]
    net_exp = rows["EXECUTION"]["conditional_downstream_net_expectancy_r"]
    if (
        closed_n >= MIN_SAMPLE_FOR_ECONOMIC_CLAIM
        and gross_exp is not None
        and net_exp is not None
        and gross_exp > 0
        and net_exp <= 0
    ):
        contributors.append("EVIDENCE_SUPPORTS_FRICTION_DECAY")
        evidence.append(
            f"{branch}: conditional downstream gross expectancy {gross_exp:+.4f}R flips to net "
            f"{net_exp:+.4f}R over {closed_n} closed trades "
            f"(avg cost {rows['EXECUTION']['average_cost_r']:.4f}R/trade)"
        )

    if closed_n < MIN_SAMPLE_FOR_ECONOMIC_CLAIM:
        evidence.append(
            f"{branch}: only {closed_n} closed trades (< {MIN_SAMPLE_FOR_ECONOMIC_CLAIM}); "
            "no economic claim about this branch is supportable"
        )

    deduped = list(dict.fromkeys(contributors))
    if not deduped:
        root_cause = "INSUFFICIENT_SAMPLE" if closed_n < MIN_SAMPLE_FOR_ECONOMIC_CLAIM else "INCONCLUSIVE"
    elif len(deduped) > 1:
        root_cause = "MULTIPLE_CONTRIBUTORS"
    else:
        root_cause = deduped[0]

    return {
        "branch": branch,
        "root_cause": root_cause,
        "contributors": deduped,
        "evidence": evidence,
        "context_n": context_n,
        "location_n": location_n,
        "trigger_n": trigger_n,
        "geometry_n": geometry_n,
        "execution_n": execution_n,
        "closed_n": closed_n,
        "raw_branch_rule_fired": raw_fired,
        "trigger_preempted_by_precedence": preempted,
        "fill_rate": _round(fill_rate),
        "sample_sufficient_for_economics": closed_n >= MIN_SAMPLE_FOR_ECONOMIC_CLAIM,
        "sample_sufficient_for_structural_claims": {
            "location": location_n >= MIN_SAMPLE_FOR_STRUCTURAL_CLAIM,
            "trigger": trigger_n >= MIN_SAMPLE_FOR_STRUCTURAL_CLAIM,
            "geometry": geometry_n >= MIN_SAMPLE_FOR_STRUCTURAL_CLAIM,
        },
    }


def analyze_b_reachability(units: Sequence[AnalysisUnit]) -> dict:
    """Why B_RANGE_REJECTION can almost never own a session under frozen V2.

    Purely a restatement of the frozen predicates — no rule is changed:

    * A long sweep requires ``low < ref_low`` AND ``close > ref_low``.
    * A long B rejection requires ``low <= ref_low`` AND ``ref_low < close < ref_high``.

    Every candle satisfying B's long predicate with ``low < ref_low`` also
    satisfies A's long predicate, and A is scanned first over the whole trade
    window.  B can therefore only own a session when price touches the
    reference boundary to the **exact tick** without breaching it (and no A
    sweep occurs anywhere in the window).  The same argument mirrors on the
    high side.
    """
    b_units = [u for u in _subset(units, branch=B) if u.retained_at(FunnelStage.TRIGGER)]
    exact = 0
    for unit in b_units:
        geo = unit.stage(FunnelStage.GEOMETRY)
        ctx = unit.stage(FunnelStage.CONTEXT)
        if geo is None or ctx is None:
            continue
        entry = geo.features.get("entry")
        if entry in (ctx.features.get("reference_low"), ctx.features.get("reference_high")):
            exact += 1
    return {
        "authoritative_b_triggers": len(b_units),
        "entries_exactly_on_reference_boundary": exact,
        "all_entries_exact_tick_touches": len(b_units) > 0 and exact == len(b_units),
        "structural_explanation": (
            "A's sweep predicate (low < ref_low AND close > ref_low) strictly subsumes B's "
            "rejection predicate (low <= ref_low AND inward close) whenever the boundary is "
            "BREACHED. Because the frozen engine scans A over the entire trade window before "
            "B, B can only own a session when price touches the reference boundary to the "
            "exact tick without breaching it, and no A sweep occurs anywhere in the window. "
            "B's scarcity is therefore a structural consequence of the frozen predicate "
            "overlap plus A->B->C precedence, not evidence that range rejection is a weak idea."
        ),
    }


def build_findings(
    units: Sequence[AnalysisUnit],
    attrition: Mapping[str, Any],
    geometry: Mapping[str, Any],
    execution: Mapping[str, Any],
    friction: Mapping[str, Any],
    stage_matrix: Mapping[str, Any],
) -> dict:
    """Evidence-ranked headline findings (no interpretation beyond the numbers)."""
    attrition_points: list[tuple[int, str]] = []
    for seg in attrition["segments"]:
        for t in seg["transitions"]:
            if t["attrition_count"] <= 0:
                continue
            top = next(iter(t["rejection_reasons"].items()), None)
            attrition_points.append(
                (
                    t["attrition_count"],
                    f"`{seg['segment_id']}` {t['from_stage']}→{t['to_stage']}: "
                    f"-{t['attrition_count']} of {t['input_count']} "
                    f"({t['attrition_pct']:.1f}%)"
                    + (f", dominant reason `{top[0]}` ×{top[1]}" if top else ""),
                )
            )
    attrition_points.sort(key=lambda x: -x[0])

    hotspots = [
        f"`{g['segment_id']}`: {g['sweep_stop_does_not_protect_extreme']}/{g['triggered']} "
        f"triggers rejected by `SWEEP_STOP_DOES_NOT_PROTECT_EXTREME` "
        f"({g['sweep_stop_rejection_pct']:.1f}%)"
        for g in sorted(
            geometry["segments"],
            key=lambda g: -(g["sweep_stop_does_not_protect_extreme"] or 0),
        )
        if g["sweep_stop_does_not_protect_extreme"]
    ]
    other_geo = [
        f"`{g['segment_id']}`: other geometry rejections {g['other_geometry_rejection_reasons']}"
        for g in geometry["segments"]
        if g["other_geometry_rejection_reasons"]
    ]

    starvation = [
        f"`{e['segment_id']}` ({e['order_type']}): {e['fills']}/{e['geometry_valid_signals']} "
        f"geometry-valid proposals filled (fill rate {e['fill_rate']:.2%}; "
        f"{e['expired']} expired, {e['unfilled']} unfilled)"
        for e in sorted(execution["segments"], key=lambda e: (e["fill_rate"] or 1.0))
        if e["geometry_valid_signals"] > 0 and (e["fill_rate"] or 1.0) < LOW_FILL_RATE
    ]

    # Conditional-cohort shifts are 0 by construction; the measurable economic
    # degradation is gross -> net on executed trades.
    drops: list[tuple[float, str]] = []
    improvements: list[tuple[float, str]] = []
    for f in friction["segments"]:
        if not f["closed_trades"] or f["gross_expectancy_r"] is None:
            continue
        delta = f["net_expectancy_r"] - f["gross_expectancy_r"]
        label = (
            f"`{f['segment_id']}`: gross {f['gross_expectancy_r']:+.4f}R → net "
            f"{f['net_expectancy_r']:+.4f}R ({delta:+.4f}R over {f['closed_trades']} closed trades)"
        )
        if delta < 0:
            drops.append((delta, label))
        else:
            improvements.append((delta, label))
    drops.sort(key=lambda x: x[0])
    improvements.sort(key=lambda x: -x[0])

    inconclusive = [
        f"`{f['segment_id']}`: {f['closed_trades']} closed trades "
        f"(< {MIN_SAMPLE_FOR_ECONOMIC_CLAIM}) — no economic conclusion supportable"
        for f in friction["segments"]
        if f["closed_trades"] < MIN_SAMPLE_FOR_ECONOMIC_CLAIM
    ]
    inconclusive.append(
        "Stage-to-stage conditional expectancy shifts are 0.0 by construction and therefore "
        "carry no information about whether any individual stage rule helps or hurts; "
        "answering that requires a preregistered counterfactual experiment, which is out of "
        "scope for this diagnostic mission."
    )

    return {
        "largest_attrition_points": [s for _, s in attrition_points[:12]],
        "geometry_rejection_hotspots": hotspots,
        "other_geometry_rejection_reasons": other_geo,
        "execution_fill_starvation": starvation,
        "friction_destroyed_segments": friction["friction_destroyed_segments"],
        "largest_conditional_expectancy_drops": [s for _, s in drops[:8]],
        "largest_conditional_expectancy_improvements": [s for _, s in improvements[:8]],
        "inconclusive": inconclusive,
        "conditional_shift_note": (
            "All conditional_net_expectancy_shift_r values are 0.0 by construction: the closed-"
            "trade cohort is identical at every stage because a trade can only close if it "
            "survived every stage. Reported shifts are therefore NOT evidence that any stage "
            "improves or degrades expectancy."
        ),
    }


def branch_counts(units: Sequence[AnalysisUnit], branch: str) -> dict[str, int]:
    rows = {r["stage"]: r for r in stage_rows_for_units(_subset(units, branch=branch), scope={})}
    return {
        "CONTEXT": rows["CONTEXT"]["stage_retained_count"],
        "LOCATION": rows["LOCATION"]["stage_retained_count"],
        "TRIGGER": rows["TRIGGER"]["stage_retained_count"],
        "GEOMETRY": rows["GEOMETRY"]["stage_retained_count"],
        "EXECUTION": rows["EXECUTION"]["stage_retained_count"],
        "CLOSED": rows["EXECUTION"]["closed_trades"],
        "RAW_CONTEXT_INPUT": rows["CONTEXT"]["stage_input_count"],
    }
