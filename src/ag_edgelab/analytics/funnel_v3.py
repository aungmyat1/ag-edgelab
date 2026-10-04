"""Universal Funnel Diagnostic Report V3 contracts.

V3 is an analysis schema, not a strategy implementation.  Its stages preserve
trigger direction, setup/confirmation, target capability, and realized
 economics as different populations.  In particular, this module refuses to
calculate an uplift when the two sides do not have identical geometry and
population semantics.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence


class FunnelV3Stage(StrEnum):
    CONTEXT = "CONTEXT"
    DIRECTION = "DIRECTION"
    LOCATION = "LOCATION"
    LIQUIDITY_CONTEXT = "LIQUIDITY_CONTEXT"
    SETUP = "SETUP"
    CONFIRMATION = "CONFIRMATION"
    ENTRY = "ENTRY"
    TARGET = "TARGET"
    ECONOMICS = "ECONOMICS"


class StageStatus(StrEnum):
    RUN = "RUN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CONTRACT_INCOMPLETE = "CONTRACT_INCOMPLETE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


ROOT_CAUSES = (
    "TRIGGER_DIRECTION_WEAKNESS",
    "DIRECTION_LOCATION_MISMATCH",
    "DIRECTION_CONFIRMATION_MISMATCH",
    "CONFIRMATION_WEAKNESS",
    "EARLY_BRANCH_PREEMPTION",
    "TARGET_CONTINUATION_WEAKNESS",
    "TARGET_MODEL_MISMATCH",
    "INSUFFICIENT_STRUCTURAL_SAMPLE",
    "INCOMPARABLE_CAPABILITY_SEMANTICS",
    "CONTRACT_INCOMPLETE",
    "INSUFFICIENT_EVIDENCE",
)


@dataclass(frozen=True)
class StageObservation:
    stage: str
    status: str
    input_n: int = 0
    pass_n: int = 0
    fail_n: int = 0
    notes: tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "input_n": self.input_n,
            "pass_n": self.pass_n,
            "fail_n": self.fail_n,
            "notes": list(self.notes),
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class FunnelDiagnosticReportV3:
    schema: str = "FunnelDiagnosticReportV3"
    stages: tuple[StageObservation, ...] = ()
    root_causes: tuple[str, ...] = ()
    comparisons: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "stages": [stage.as_dict() for stage in self.stages],
            "root_causes": list(self.root_causes),
            "comparisons": _jsonable(self.comparisons),
            "metadata": _jsonable(self.metadata),
        }


def stage_observation(
    stage: FunnelV3Stage | str,
    *,
    input_n: int = 0,
    pass_n: int = 0,
    rule_available: bool = True,
    applicable: bool = True,
    notes: Sequence[str] = (),
    evidence: Mapping[str, Any] | None = None,
) -> StageObservation:
    """Create a stage with explicit V3 missing-population semantics."""
    stage = str(stage)
    if not applicable:
        status = StageStatus.NOT_APPLICABLE.value
    elif not rule_available:
        status = StageStatus.CONTRACT_INCOMPLETE.value
    elif input_n <= 0:
        status = StageStatus.INSUFFICIENT_SAMPLE.value
    else:
        status = StageStatus.RUN.value
    fail_n = max(0, input_n - pass_n)
    return StageObservation(stage, status, input_n, pass_n, fail_n, tuple(notes), evidence or {})


def empty_funnel_report(
    *,
    metadata: Mapping[str, Any] | None = None,
    unavailable_stages: Sequence[str] = (),
    incomplete_stages: Sequence[str] = (),
) -> FunnelDiagnosticReportV3:
    unavailable = set(unavailable_stages)
    incomplete = set(incomplete_stages)
    stages = tuple(
        stage_observation(
            stage,
            applicable=stage.value not in unavailable,
            rule_available=stage.value not in incomplete,
            notes=("no authorized population",) if stage.value not in unavailable else ("not used by strategy",),
        )
        for stage in FunnelV3Stage
    )
    root = ["INSUFFICIENT_EVIDENCE"]
    if incomplete:
        root.insert(0, "CONTRACT_INCOMPLETE")
    return FunnelDiagnosticReportV3(stages=stages, root_causes=tuple(root), metadata=metadata or {})


def comparable_uplift(
    aligned: float | None,
    counter: float | None,
    *,
    aligned_population: str,
    counter_population: str,
    aligned_geometry: str,
    counter_geometry: str,
) -> float | None:
    """Return aligned-counter only for identical population/geometry semantics."""
    if aligned is None or counter is None:
        return None
    if aligned_population != counter_population or aligned_geometry != counter_geometry:
        return None
    return aligned - counter


def capability_row(
    aligned: Sequence[str],
    counter: Sequence[str],
    *,
    aligned_population: str,
    counter_population: str,
    geometry: str,
) -> dict[str, Any]:
    """Summarize categorical capability without inventing rejected outcomes."""
    def rate(values: Sequence[str], label: str) -> float | None:
        return sum(value == label for value in values) / len(values) if values else None
    same = aligned_population == counter_population
    return {
        "aligned_n": len(aligned),
        "counter_n": len(counter),
        "aligned_capability": rate(aligned, "TARGET"),
        "counter_capability": rate(counter, "TARGET"),
        "uplift": comparable_uplift(
            rate(aligned, "TARGET"), rate(counter, "TARGET"),
            aligned_population=aligned_population, counter_population=counter_population,
            aligned_geometry=geometry, counter_geometry=geometry,
        ),
        "comparable": same,
        "incomparable_reason": None if same else "population semantics differ",
    }


def classify_root_causes(
    *,
    trigger_separation: bool | None,
    confirmation_degrades_comparable_capability: bool | None,
    natural_target_useful: bool | None,
    fixed_5r_collapses: bool | None,
    preemption_present: bool | None,
    structural_sample_sufficient: bool,
    contracts_complete: bool,
) -> tuple[str, ...]:
    """Apply the mission's precedence without turning diagnostics into claims."""
    if not contracts_complete:
        return ("CONTRACT_INCOMPLETE", "INSUFFICIENT_EVIDENCE")
    causes: list[str] = []
    if not structural_sample_sufficient:
        causes.append("INSUFFICIENT_STRUCTURAL_SAMPLE")
    if natural_target_useful and fixed_5r_collapses:
        # Target-model mismatch precedes trigger weakness by mission policy.
        causes.append("TARGET_MODEL_MISMATCH")
    elif trigger_separation is False:
        causes.append("TRIGGER_DIRECTION_WEAKNESS")
    if confirmation_degrades_comparable_capability:
        causes.append("CONFIRMATION_WEAKNESS")
    if preemption_present:
        causes.append("EARLY_BRANCH_PREEMPTION")
    return tuple(dict.fromkeys(causes or ["INSUFFICIENT_EVIDENCE"]))


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    return value


__all__ = [
    "FunnelDiagnosticReportV3", "FunnelV3Stage", "ROOT_CAUSES", "StageObservation",
    "StageStatus", "capability_row", "classify_root_causes", "comparable_uplift",
    "empty_funnel_report", "stage_observation",
]
