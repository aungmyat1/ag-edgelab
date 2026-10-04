"""Required diagnostic matrix — TRIGGER -> CONFIRMATION -> ENTRY -> 1R..5R.

Capability semantics: `capability` of a population is the share of its
candidates whose MFE_R reaches CAPABILITY_REACH_R (opportunity capability
under the shared diagnostic geometry). Populations are comparable ONLY when
they carry the same capability basis string; incompatible bases raise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

CAPABILITY_REACH_R = 2.0
CAPABILITY_BASIS = f"MFE_R_REACH_{CAPABILITY_REACH_R:.1f}R_SHARED_DIAGNOSTIC_GEOMETRY_V1"
MIN_COMPARABLE_SAMPLE = 20


class MatrixStage(StrEnum):
    TRIGGER_DIRECTION = "TRIGGER_DIRECTION"
    TRIGGER_LOCATION = "TRIGGER_LOCATION"
    CONFIRMATION_SETUP = "CONFIRMATION_SETUP"
    ENTRY = "ENTRY"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"


MATRIX_STAGES: tuple[MatrixStage, ...] = tuple(MatrixStage)


class IncomparableCapabilityError(ValueError):
    """Raised when two populations carry different capability semantics."""


@dataclass(frozen=True)
class MatrixCandidate:
    """One diagnostic candidate flowing through the stage chain."""

    candidate_id: str
    stage_pass: dict  # MatrixStage -> bool (monotone chain enforced by builder)
    mfe_r: float | None  # None => capability not measurable for this candidate
    capability_basis: str = CAPABILITY_BASIS
    attributes: dict = field(default_factory=dict)


class StageDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: MatrixStage
    input_n: int
    pass_n: int
    fail_n: int
    capability_before: float | None
    capability_after_pass: float | None
    capability_after_fail: float | None
    uplift_pp: float | None
    capability_basis: str | None
    comparable: bool


def _capability(candidates: list[MatrixCandidate]) -> tuple[float | None, str | None]:
    """Share of candidates reaching CAPABILITY_REACH_R. None if unmeasurable."""
    measured = [c for c in candidates if c.mfe_r is not None]
    if not measured:
        return None, None
    bases = {c.capability_basis for c in measured}
    if len(bases) != 1:
        raise IncomparableCapabilityError(f"mixed capability bases: {sorted(bases)}")
    share = sum(1 for c in measured if c.mfe_r >= CAPABILITY_REACH_R) / len(measured)
    return share, bases.pop()


def build_matrix(candidates: list[MatrixCandidate]) -> tuple[StageDiagnostic, ...]:
    """Stage-by-stage counts and capability uplift along the required chain.

    A candidate enters stage k only if it passed every earlier stage
    (monotone funnel). Capability comparisons are emitted only when the pass
    AND fail populations share one capability basis; otherwise the row is
    marked non-comparable with None capabilities (never a silent mix).
    """
    output: list[StageDiagnostic] = []
    current = list(candidates)
    for stage in MATRIX_STAGES:
        passed = [c for c in current if c.stage_pass.get(stage, False)]
        failed = [c for c in current if not c.stage_pass.get(stage, False)]
        try:
            cap_before, basis_b = _capability(current)
            cap_pass, basis_p = _capability(passed)
            cap_fail, basis_f = _capability(failed)
            bases = {b for b in (basis_b, basis_p, basis_f) if b is not None}
            if len(bases) > 1:
                raise IncomparableCapabilityError(f"mixed capability bases: {sorted(bases)}")
            comparable = (cap_before is not None and cap_pass is not None
                          and len(current) >= MIN_COMPARABLE_SAMPLE)
            basis = bases.pop() if bases else None
        except IncomparableCapabilityError:
            cap_before = cap_pass = cap_fail = None
            comparable = False
            basis = None
        output.append(StageDiagnostic(
            stage=stage, input_n=len(current), pass_n=len(passed), fail_n=len(failed),
            capability_before=cap_before, capability_after_pass=cap_pass,
            capability_after_fail=cap_fail,
            uplift_pp=None if not comparable else (cap_pass - cap_before) * 100.0,
            capability_basis=basis, comparable=comparable))
        current = passed
    return tuple(output)


def compare_capability(a_basis: str, b_basis: str) -> None:
    """Guard: comparing incompatible capability semantics is a hard error."""
    if a_basis != b_basis:
        raise IncomparableCapabilityError(
            f"never compare incompatible capability semantics: {a_basis!r} vs {b_basis!r}")
