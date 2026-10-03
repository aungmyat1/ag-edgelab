from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from ag_edgelab.analytics.temporal import TemporalFunnelAnalysis, _logical_stage, analyze_temporal_funnel
from ag_edgelab.contracts.diagnostics import FunnelDiagnosticReportV2
from ag_edgelab.contracts.funnel import FunnelStage
from ag_edgelab.ledger.candidate import CandidateRecord

DIAGNOSTIC_ORDER = (
    "TEMPORAL_FUNNEL_INCOMPATIBILITY",
    "CROSS_SESSION_TRIGGER",
    "STARVED_TRIGGER",
    "STARVED_CONFIRMATION",
    "LOW_TARGET_CAPABILITY",
    "CONFIRMATION_NO_UPLIFT",
    "FRICTION_DESTROYS_EDGE",
    "INSUFFICIENT_ECONOMIC_SAMPLE",
)


def _stage_flow(records: Sequence[CandidateRecord]) -> tuple[dict[str, Any], ...]:
    """Compute evidence-preserving flow rows from generic stage results."""
    rows: list[dict[str, Any]] = []
    stages = ["CONTEXT", "LOCATION", "TRIGGER", "CONFIRMATION", "GEOMETRY", "EXECUTION", "OUTCOME"]
    input_n = len(records)
    for stage in stages:
        results = [r for record in records for r in record.stage_results if _logical_stage(r) == stage]
        passed = [r for r in results if r.passed]
        reasons = Counter(
            r.failure_reason or code
            for r in results if not r.passed
            for code in (r.rejection_codes or (r.failure_reason or "UNSPECIFIED",))
        )
        # Funnel flow is sequential: a downstream rule receives only the
        # candidates that passed its immediate predecessor. Missing results
        # are therefore not fabricated as failures.
        pass_n = min(len(passed), input_n)
        rows.append({
            "rule": stage, "input_n": input_n, "pass_n": pass_n,
            "fail_n": input_n - pass_n,
            "pass_pct": (pass_n / input_n * 100.0) if input_n else None,
            "failure_reasons": dict(sorted(reasons.items())),
        })
        input_n = pass_n
    return tuple(rows)


def _temporal_payload(analysis: TemporalFunnelAnalysis) -> dict[str, Any]:
    stage_names = {"CONTEXT", "LOCATION", "TRIGGER", "CONFIRMATION", "GEOMETRY", "EXECUTION", "OUTCOME"}
    lifecycle = []
    presence = Counter()
    for audit in analysis.candidates:
        timestamps = {}
        cycles = {}
        for item in audit.lifecycle:
            timestamps[item.stage] = item.passed_at.isoformat() if item.passed_at else None
            cycles[item.stage] = item.cycle_id
            if item.passed_at and item.stage in stage_names:
                presence[item.stage] += 1
        lifecycle.append({
            "candidate_id": audit.candidate_id,
            "stage_timestamps": timestamps,
            "cycle_ids": cycles,
            "stage_order_valid": audit.stage_order_valid,
            "same_cycle": audit.same_cycle,
            "diagnostics": list(audit.diagnostics),
            "inter_stage_delays_minutes": dict(audit.inter_stage_delays_minutes),
        })
    cross = sum(not x.same_cycle for x in analysis.candidates)
    invalid = sum(not x.stage_order_valid for x in analysis.candidates)
    return {
        "stage_presence": {k: presence.get(k, 0) for k in sorted(stage_names)},
        "same_cycle_n": len(analysis.candidates) - cross,
        "cross_cycle_n": cross,
        "valid_order_n": len(analysis.candidates) - invalid,
        "invalid_order_n": invalid,
        "diagnostic_counts": dict(sorted(analysis.diagnostic_counts.items())),
        "lifecycle": lifecycle,
        "delay_distributions": [x.__dict__ for x in analysis.delay_distributions],
    }


def classify_root_cause(
    *, flow: Sequence[Mapping[str, Any]], temporal: Mapping[str, Any],
    target_capability: Mapping[str, Any], economics: Mapping[str, Any] | None,
) -> tuple[str | None, tuple[str, ...]]:
    """Apply stable precedence so downstream zeroes do not hide temporal causes."""
    temporal_counts = temporal.get("diagnostic_counts", {})
    flow_by_rule = {str(x.get("rule")): x for x in flow}
    trigger = flow_by_rule.get("TRIGGER", {})
    confirmation = flow_by_rule.get("CONFIRMATION", flow_by_rule.get("GEOMETRY", {}))
    primary: str | None = None
    secondary: list[str] = []
    if temporal_counts.get("TEMPORAL_FUNNEL_INCOMPATIBILITY", 0) > 0:
        primary = "TEMPORAL_FUNNEL_INCOMPATIBILITY"
    elif temporal_counts.get("CROSS_SESSION_TRIGGER", 0) > 0:
        primary = "CROSS_SESSION_TRIGGER"
    elif trigger.get("pass_n", 0) == 0:
        primary = "STARVED_TRIGGER"
    elif confirmation.get("pass_n", 0) == 0:
        primary = "STARVED_CONFIRMATION"
    if trigger.get("pass_n", 0) > 0 and confirmation.get("pass_n", 0) == 0:
        secondary.append("STARVED_CONFIRMATION")
    values = [x for x in target_capability.values() if isinstance(x, Mapping)]
    uplifts = [x.get("uplift_pp") for x in values if x.get("uplift_pp") is not None]
    if values and all(x.get("reach_after_pass") is None for x in values):
        secondary.append("LOW_TARGET_CAPABILITY")
    elif uplifts and confirmation.get("pass_n", 0) > 0 and all(float(x) <= 0 for x in uplifts):
        secondary.append("CONFIRMATION_NO_UPLIFT")
    if economics is None or economics.get("closed", 0) == 0:
        secondary.append("INSUFFICIENT_ECONOMIC_SAMPLE")
    elif economics.get("gross_R") is not None and economics.get("net_R") is not None and economics["gross_R"] > 0 and economics["net_R"] < 0:
        secondary.append("FRICTION_DESTROYS_EDGE")
    if primary in secondary:
        secondary.remove(primary)
    return primary, tuple(dict.fromkeys(secondary))


def build_funnel_diagnostic_report(
    records: Sequence[CandidateRecord], *, strategy_identity: Mapping[str, Any],
    dataset_identity: Mapping[str, Any], dataset_role: str,
    target_capability: Mapping[str, Any] | None = None,
    economics: Mapping[str, Any] | None = None,
    evidence_refs: Sequence[str] = (),
) -> FunnelDiagnosticReportV2:
    """Create the standard V2 report from generic candidate records."""
    flow = _stage_flow(records)
    temporal_analysis = analyze_temporal_funnel(records)
    temporal = _temporal_payload(temporal_analysis)
    target = target_capability or {f"{n}R": {"reach_before": None, "reach_after_pass": None, "reach_after_fail": None, "uplift_pp": None} for n in (1, 2, 3, 4, 5)}
    primary, secondary = classify_root_cause(flow=flow, temporal=temporal, target_capability=target, economics=economics)
    missing = []
    if all(v.get("reach_after_pass") is None for v in target.values() if isinstance(v, Mapping)):
        missing.append("TARGET_CAPABILITY_ENTRY_GEOMETRY")
    if economics is None or economics.get("closed", 0) == 0:
        missing.append("REALIZED_ECONOMICS")
    return FunnelDiagnosticReportV2.build(
        strategy_identity=strategy_identity, dataset_identity=dataset_identity,
        dataset_role=dataset_role, flow=flow, temporal=temporal,
        target_capability=target, economics=economics,
        primary_diagnosis=primary, secondary_diagnoses=secondary,
        evidence_refs=tuple(evidence_refs), missing_evidence=tuple(missing),
    )
