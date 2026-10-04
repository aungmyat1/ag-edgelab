"""Root-cause precedence logic (mission section 16, CASE A..E).

Preregistered thresholds; strict precedence A > B > C > D with E
(INSUFFICIENT_EVIDENCE) whenever comparable evidence is missing. The logic
never recommends optimizing a downstream funnel when an upstream funnel is
the diagnosed weakness.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ag_edgelab.universal.matrix import MIN_COMPARABLE_SAMPLE, compare_capability


class Diagnosis(StrEnum):
    TRIGGER_FUNNEL_WEAKNESS = "TRIGGER_FUNNEL_WEAKNESS"
    CONFIRMATION_VALUE_DESTRUCTION = "CONFIRMATION_VALUE_DESTRUCTION"
    TARGET_CONTINUATION_WEAKNESS = "TARGET_CONTINUATION_WEAKNESS"
    TARGET_MODEL_MISMATCH = "TARGET_MODEL_MISMATCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_DOMINANT_WEAKNESS = "NO_DOMINANT_WEAKNESS"


class NextFunnel(StrEnum):
    TRIGGER = "TRIGGER"
    CONFIRMATION = "CONFIRMATION"
    TARGET = "TARGET"
    NONE = "NONE"


# Preregistered decision thresholds (frozen; research diagnostics only).
USEFUL_TRIGGER_CAPABILITY_MIN = 0.30       # share reaching 2R (CASE A floor)
CONFIRMATION_DESTRUCTION_DROP_PP = 10.0    # capability loss pass-vs-before (CASE B)
DESIRED_TARGET_REACH_MIN = 0.25            # reach share at the desired target (CASE C)


class RootCauseInputs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trigger_n: int
    trigger_capability: float | None          # share of trigger population reaching 2R
    confirmed_n: int
    confirmed_capability: float | None        # same basis, confirmation-passed population
    desired_target_r: float                   # the strategy's frozen fixed target
    desired_target_reach: float | None        # share of confirmed population reaching it
    natural_target_median_r: float | None     # median natural TARGET_R (diagnostic)
    capability_basis: str
    comparable: bool                           # upstream matrix comparability flag


class RootCauseResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case: str  # "A".."E" or "NONE"
    primary: Diagnosis
    secondary: tuple[Diagnosis, ...] = ()
    next_funnel_to_change: NextFunnel
    rationale: str


def diagnose(inputs: RootCauseInputs, reference_basis: str) -> RootCauseResult:
    # Capability bases must match before ANY comparison (fail-closed guard).
    compare_capability(inputs.capability_basis, reference_basis)

    secondary: list[Diagnosis] = []
    mismatch = (inputs.natural_target_median_r is not None
                and inputs.natural_target_median_r < inputs.desired_target_r)

    # CASE E — no comparable evidence.
    if (not inputs.comparable or inputs.trigger_capability is None
            or inputs.trigger_n < MIN_COMPARABLE_SAMPLE):
        return RootCauseResult(
            case="E", primary=Diagnosis.INSUFFICIENT_EVIDENCE,
            next_funnel_to_change=NextFunnel.NONE,
            rationale=f"no comparable evidence (trigger_n={inputs.trigger_n}, "
                      f"comparable={inputs.comparable})")

    # CASE A — trigger weakness dominates; do NOT recommend confirmation work.
    if inputs.trigger_capability < USEFUL_TRIGGER_CAPABILITY_MIN:
        if mismatch:
            secondary.append(Diagnosis.TARGET_MODEL_MISMATCH)
        return RootCauseResult(
            case="A", primary=Diagnosis.TRIGGER_FUNNEL_WEAKNESS, secondary=tuple(secondary),
            next_funnel_to_change=NextFunnel.TRIGGER,
            rationale=f"trigger capability {inputs.trigger_capability:.3f} < "
                      f"{USEFUL_TRIGGER_CAPABILITY_MIN} — confirmation optimization not recommended")

    # CASE B — confirmation destroys comparable capability.
    if inputs.confirmed_capability is not None and inputs.confirmed_n >= MIN_COMPARABLE_SAMPLE:
        drop_pp = (inputs.trigger_capability - inputs.confirmed_capability) * 100.0
        if drop_pp >= CONFIRMATION_DESTRUCTION_DROP_PP:
            if mismatch:
                secondary.append(Diagnosis.TARGET_MODEL_MISMATCH)
            return RootCauseResult(
                case="B", primary=Diagnosis.CONFIRMATION_VALUE_DESTRUCTION, secondary=tuple(secondary),
                next_funnel_to_change=NextFunnel.CONFIRMATION,
                rationale=f"confirmation drops capability by {drop_pp:.1f}pp "
                          f">= {CONFIRMATION_DESTRUCTION_DROP_PP}pp")
    elif inputs.confirmed_capability is None or inputs.confirmed_n < MIN_COMPARABLE_SAMPLE:
        return RootCauseResult(
            case="E", primary=Diagnosis.INSUFFICIENT_EVIDENCE,
            next_funnel_to_change=NextFunnel.NONE,
            rationale=f"confirmation population not comparably measurable "
                      f"(confirmed_n={inputs.confirmed_n})")

    # CASE C — both funnels useful, movement dies before the desired target.
    if inputs.desired_target_reach is not None and inputs.desired_target_reach < DESIRED_TARGET_REACH_MIN:
        if mismatch:
            secondary.append(Diagnosis.TARGET_MODEL_MISMATCH)
        return RootCauseResult(
            case="C", primary=Diagnosis.TARGET_CONTINUATION_WEAKNESS, secondary=tuple(secondary),
            next_funnel_to_change=NextFunnel.TARGET,
            rationale=f"desired {inputs.desired_target_r:.0f}R reach "
                      f"{inputs.desired_target_reach:.3f} < {DESIRED_TARGET_REACH_MIN}")

    # CASE D — natural market objective consistently below the frozen target.
    if mismatch:
        return RootCauseResult(
            case="D", primary=Diagnosis.TARGET_MODEL_MISMATCH,
            next_funnel_to_change=NextFunnel.TARGET,
            rationale=f"median natural target {inputs.natural_target_median_r:.2f}R < "
                      f"frozen fixed target {inputs.desired_target_r:.0f}R "
                      f"(diagnostic only — the strategy target is NOT replaced)")

    return RootCauseResult(
        case="NONE", primary=Diagnosis.NO_DOMINANT_WEAKNESS,
        next_funnel_to_change=NextFunnel.NONE,
        rationale="no preregistered weakness threshold tripped")
