from __future__ import annotations

"""Temporal diagnostics for the Universal Funnel Analyzer.

This module is deliberately strategy-agnostic. It consumes the lifecycle
timestamps already present on ``FunnelStageResult`` and optional cycle labels
in rule features; it never changes stage decisions or creates strategies.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from statistics import quantiles
from typing import Mapping, Sequence

from ag_edgelab.contracts.funnel import FunnelStage
from ag_edgelab.ledger.candidate import CandidateRecord


class TemporalDiagnostic(StrEnum):
    TRIGGER_PRECEDES_LOCATION = "TRIGGER_PRECEDES_LOCATION"
    CONFIRMATION_PRECEDES_LOCATION = "CONFIRMATION_PRECEDES_LOCATION"
    CROSS_SESSION_TRIGGER = "CROSS_SESSION_TRIGGER"
    TEMPORAL_FUNNEL_INCOMPATIBILITY = "TEMPORAL_FUNNEL_INCOMPATIBILITY"


DEFAULT_TEMPORAL_STAGE_ORDER: tuple[str, ...] = (
    "CONTEXT", "LOCATION", "TRIGGER", "CONFIRMATION", "GEOMETRY", "EXECUTION", "OUTCOME"
)


def _utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        raise ValueError("temporal funnel timestamps must be timezone-aware")
    return ts.astimezone(timezone.utc)


def _stage_name(value: object) -> str:
    return getattr(value, "value", str(value)).upper()


def _logical_stage(stage_result) -> str:
    """Return an optional universal phase alias carried by rule features."""
    aliases = {"CONTEXT", "LOCATION", "TRIGGER", "CONFIRMATION", "GEOMETRY", "EXECUTION", "OUTCOME"}
    for rule in stage_result.rule_results:
        for key in ("logical_stage", "funnel_stage", "phase", "substage"):
            value = rule.features.get(key) if rule.features else None
            if value is not None and str(value).upper() in aliases:
                return str(value).upper()
    return _stage_name(stage_result.stage)


def _cycle_id(stage_result) -> str:
    """Use an explicit cycle/session label, otherwise use the UTC date.

    The UTC-date fallback is deterministic and prevents a missing cycle label
    from silently making cross-session observations look same-cycle.
    """
    features = {}
    for rule in stage_result.rule_results:
        if rule.features:
            features.update(rule.features)
    for key in ("cycle_id", "cycle", "session_cycle", "session_date", "date"):
        if features.get(key) is not None:
            return str(features[key])
    return _utc(stage_result.as_of).date().isoformat()


@dataclass(frozen=True)
class StageLifecycleTimestamp:
    stage: str
    observed_at: datetime
    passed_at: datetime | None
    cycle_id: str


@dataclass(frozen=True)
class TemporalCandidateAudit:
    candidate_id: str
    lifecycle: tuple[StageLifecycleTimestamp, ...]
    stage_order_valid: bool
    same_cycle: bool
    diagnostics: tuple[str, ...]
    inter_stage_delays_minutes: Mapping[str, float]


@dataclass(frozen=True)
class DelayDistribution:
    transition: str
    count: int
    minimum: float | None
    p25: float | None
    p50: float | None
    p75: float | None
    p90: float | None
    maximum: float | None


@dataclass(frozen=True)
class TemporalFunnelAnalysis:
    candidates: tuple[TemporalCandidateAudit, ...]
    diagnostic_counts: Mapping[str, int]
    delay_distributions: tuple[DelayDistribution, ...]
    stage_order: tuple[str, ...]


def _percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return float(ordered[low] + (ordered[high] - ordered[low]) * (position - low))


def _distribution(transition: str, values: Sequence[float]) -> DelayDistribution:
    return DelayDistribution(
        transition=transition,
        count=len(values),
        minimum=min(values) if values else None,
        p25=_percentile(values, .25), p50=_percentile(values, .50),
        p75=_percentile(values, .75), p90=_percentile(values, .90),
        maximum=max(values) if values else None,
    )


def _result_timestamps(record: CandidateRecord) -> list[StageLifecycleTimestamp]:
    out = []
    for result in record.stage_results:
        observed = _utc(result.as_of)
        out.append(StageLifecycleTimestamp(
            stage=_logical_stage(result), observed_at=observed,
            passed_at=observed if result.passed else None,
            cycle_id=_cycle_id(result),
        ))
    return out


def audit_candidate_temporal_order(
    record: CandidateRecord,
    *, stage_order: Sequence[str] = DEFAULT_TEMPORAL_STAGE_ORDER,
) -> TemporalCandidateAudit:
    """Audit one candidate without changing its funnel results."""
    lifecycle = _result_timestamps(record)
    passed = [x for x in lifecycle if x.passed_at is not None]
    rank = {name.upper(): i for i, name in enumerate(stage_order)}
    diagnostics: list[str] = []

    # Only compare stages actually observed and passed. Missing downstream
    # stages are attrition, not temporal violations.
    order_valid = True
    for left, right in zip(passed, passed[1:]):
        if left.observed_at > right.observed_at:
            order_valid = False
            diagnostics.append(TemporalDiagnostic.TEMPORAL_FUNNEL_INCOMPATIBILITY.value)
        if rank.get(left.stage, -1) > rank.get(right.stage, -1):
            order_valid = False
            diagnostics.append(TemporalDiagnostic.TEMPORAL_FUNNEL_INCOMPATIBILITY.value)

    by_stage: dict[str, StageLifecycleTimestamp] = {}
    for item in passed:
        by_stage.setdefault(item.stage, item)

    location = by_stage.get("LOCATION")
    trigger = by_stage.get("TRIGGER")
    confirmation = by_stage.get("CONFIRMATION")
    if location and trigger:
        if trigger.observed_at < location.observed_at:
            diagnostics.append(TemporalDiagnostic.TRIGGER_PRECEDES_LOCATION.value)
            order_valid = False
        if trigger.cycle_id != location.cycle_id:
            diagnostics.append(TemporalDiagnostic.CROSS_SESSION_TRIGGER.value)
            diagnostics.append(TemporalDiagnostic.TEMPORAL_FUNNEL_INCOMPATIBILITY.value)
            order_valid = False
    if location and confirmation and confirmation.observed_at < location.observed_at:
        diagnostics.append(TemporalDiagnostic.CONFIRMATION_PRECEDES_LOCATION.value)
        diagnostics.append(TemporalDiagnostic.TEMPORAL_FUNNEL_INCOMPATIBILITY.value)
        order_valid = False

    # De-duplicate while retaining stable diagnostic order.
    diagnostics = list(dict.fromkeys(diagnostics))
    cycles = {x.cycle_id for x in passed}
    delays: dict[str, float] = {}
    for left, right in zip(passed, passed[1:]):
        transition = f"{left.stage}->{right.stage}"
        delays[transition] = (right.observed_at - left.observed_at).total_seconds() / 60.0
    return TemporalCandidateAudit(
        candidate_id=record.candidate_id, lifecycle=tuple(lifecycle),
        stage_order_valid=order_valid, same_cycle=len(cycles) <= 1,
        diagnostics=tuple(diagnostics), inter_stage_delays_minutes=delays,
    )


def analyze_temporal_funnel(
    records: Sequence[CandidateRecord],
    *, stage_order: Sequence[str] = DEFAULT_TEMPORAL_STAGE_ORDER,
) -> TemporalFunnelAnalysis:
    """Produce lifecycle, order, cycle, diagnostic, and delay analytics."""
    audits = tuple(audit_candidate_temporal_order(r, stage_order=stage_order) for r in records)
    counts = {diagnostic.value: 0 for diagnostic in TemporalDiagnostic}
    values: dict[str, list[float]] = {}
    for audit in audits:
        for diagnostic in audit.diagnostics:
            counts[diagnostic] = counts.get(diagnostic, 0) + 1
        for transition, delay in audit.inter_stage_delays_minutes.items():
            values.setdefault(transition, []).append(delay)
    distributions = tuple(_distribution(k, values[k]) for k in sorted(values))
    return TemporalFunnelAnalysis(
        candidates=audits, diagnostic_counts=counts,
        delay_distributions=distributions, stage_order=tuple(str(x) for x in stage_order),
    )


# Descriptive alias for callers that use the analyzer terminology.
compute_temporal_funnel_diagnostics = analyze_temporal_funnel
