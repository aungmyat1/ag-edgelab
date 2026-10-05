"""PRE_OOS_ROBUSTNESS_GATE_V1 — the authorization decision.

This module answers one narrow question:

    Is this frozen candidate's DEVELOPMENT evidence distributed, stable
    and reproducible enough that spending a fresh OOS window on it is
    justified?

It does not answer whether the candidate is profitable, economically
viable, or an edge. ``PRE_OOS_PASS`` is permission to run one test, not
a result. The distinction is enforced in code: the decision object has
no field that could carry an edge verdict, and
:func:`implies_edge_verified` exists purely to return ``False`` and be
asserted on.

Friction deserves a specific note. Missing VT Markets values must NOT
block structural analysis — structure is a property of price paths, not
of costs. But they MUST block any economic or edge claim. So friction
enters as a secondary diagnosis that cannot change the structural
verdict, while the economic verdict is pinned to the repository's
existing ``NOT_ESTIMABLE_NO_FRICTION_AUTHORITY`` token rather than a new
status invented for this mission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from ag_edgelab.verification.pre_oos.contract import (
    DIAGNOSIS_PRECEDENCE, SECONDARY_ONLY_DIAGNOSES, RobustnessContract,
)


class Decision(StrEnum):
    PRE_OOS_PASS = "PRE_OOS_PASS"
    PRE_OOS_FAIL = "PRE_OOS_FAIL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NOT_EVALUATED = "NOT_EVALUATED"


class Diagnosis(StrEnum):
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    DATASET_ROLE_VIOLATION = "DATASET_ROLE_VIOLATION"
    CANDIDATE_IDENTITY_INVALID = "CANDIDATE_IDENTITY_INVALID"
    TEMPORAL_CAUSALITY_FAILURE = "TEMPORAL_CAUSALITY_FAILURE"
    WALK_FORWARD_INSTABILITY = "WALK_FORWARD_INSTABILITY"
    YEAR_DEPENDENCY = "YEAR_DEPENDENCY"
    SYMBOL_DEPENDENCY = "SYMBOL_DEPENDENCY"
    REGIME_DEPENDENCY = "REGIME_DEPENDENCY"
    TAIL_DEPENDENCY = "TAIL_DEPENDENCY"
    ASYMMETRIC_TAIL_DEPENDENCE = "ASYMMETRIC_TAIL_DEPENDENCE"
    STATISTICAL_UNCERTAINTY = "STATISTICAL_UNCERTAINTY"
    PARAMETER_FRAGILITY = "PARAMETER_FRAGILITY"
    FRICTION_AUTHORITY_INCOMPLETE = "FRICTION_AUTHORITY_INCOMPLETE"
    ROBUSTNESS_SUPPORTED = "ROBUSTNESS_SUPPORTED"


class FrictionReadiness(StrEnum):
    FRICTION_UNAVAILABLE = "FRICTION_UNAVAILABLE"
    FRICTION_PARTIAL = "FRICTION_PARTIAL"
    FRICTION_SCENARIO_ONLY = "FRICTION_SCENARIO_ONLY"
    FRICTION_MEASURED = "FRICTION_MEASURED"

    @property
    def blocks_economic_claims(self) -> bool:
        return self is not FrictionReadiness.FRICTION_MEASURED


#: Reused from the repository's existing economic vocabulary rather than
#: inventing a parallel status for this mission.
ECONOMIC_VERDICT_NO_FRICTION = "NOT_ESTIMABLE_NO_FRICTION_AUTHORITY"
EDGE_STATUS_UNVERIFIED = "UNVERIFIED"


@dataclass
class AxisFinding:
    """One axis's contribution: did it fire, and on what evidence."""

    axis: str
    diagnosis: Diagnosis | None
    fired: bool
    evaluated: bool
    detail: str
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "axis": self.axis,
            "diagnosis": str(self.diagnosis) if self.diagnosis else None,
            "fired": self.fired,
            "evaluated": self.evaluated,
            "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass
class GateDecision:
    """The authorization decision and everything behind it."""

    decision: Decision
    primary_diagnosis: Diagnosis
    secondary_diagnoses: tuple[Diagnosis, ...]
    findings: list[AxisFinding]
    contract_sha256: str
    friction_readiness: FrictionReadiness
    economic_verdict: str = ECONOMIC_VERDICT_NO_FRICTION
    edge_status: str = EDGE_STATUS_UNVERIFIED
    unevaluated_axes: tuple[str, ...] = ()

    @property
    def authorized_for_oos(self) -> bool:
        return self.decision is Decision.PRE_OOS_PASS

    def implies_edge_verified(self) -> bool:
        """Always False. PRE_OOS_PASS is permission to test, not a result."""
        return False

    def implies_economic_verified(self) -> bool:
        """Always False while friction is not measured."""
        return (not self.friction_readiness.blocks_economic_claims
                and False)

    def as_dict(self) -> dict:
        return {
            "gate_id": "PRE_OOS_ROBUSTNESS_GATE_V1",
            "contract_sha256": self.contract_sha256,
            "DECISION": str(self.decision),
            "PRIMARY_DIAGNOSIS": str(self.primary_diagnosis),
            "SECONDARY_DIAGNOSES": [str(d) for d in self.secondary_diagnoses],
            "AUTHORIZED_FOR_OOS": self.authorized_for_oos,
            "FRICTION_READINESS": str(self.friction_readiness),
            "ECONOMIC_VERDICT": self.economic_verdict,
            "EDGE_STATUS": self.edge_status,
            "IMPLIES_EDGE_VERIFIED": self.implies_edge_verified(),
            "IMPLIES_ECONOMIC_VERIFIED": self.implies_economic_verified(),
            "unevaluated_axes": list(self.unevaluated_axes),
            "findings": [f.as_dict() for f in self.findings],
            "semantics": {
                "PRE_OOS_PASS": ("the frozen candidate has enough distributed "
                                 "DEV robustness to justify spending ONE fresh "
                                 "OOS window. It does not mean profitable, "
                                 "economically verified, or EDGE_VERIFIED."),
                "oos_inspected": False,
                "holdout_inspected": False,
            },
        }


# ---------------------------------------------------------------------------
# temporal integrity
# ---------------------------------------------------------------------------

def temporal_integrity(observations, *, regime_recompute=None) -> AxisFinding:
    """Chronology and causality checks over the admitted population."""
    problems: list[str] = []
    times = [o.timestamp_utc for o in observations]
    if any(t is None for t in times):
        problems.append("one or more observations carry no timestamp")
    else:
        out_of_order = sum(1 for a, b in zip(times, times[1:]) if b < a)
        if out_of_order:
            problems.append(
                f"{out_of_order} observations are out of chronological order; "
                "a robustness population must be orderable in time before "
                "fold, year or trailing-window logic can be trusted")
    if regime_recompute is not None:
        declared = [o.regime for o in observations]
        recomputed = regime_recompute(observations)
        if len(recomputed) != len(declared):
            problems.append("regime recomputation returned a different length")
        else:
            drift = sum(1 for a, b in zip(declared, recomputed)
                        if a is not None and a != b)
            if drift:
                problems.append(
                    f"{drift} regime labels do not reproduce from a strictly "
                    "causal recomputation, so a label saw data from its own "
                    "future")
    return AxisFinding(
        axis="temporal_integrity",
        diagnosis=Diagnosis.TEMPORAL_CAUSALITY_FAILURE if problems else None,
        fired=bool(problems), evaluated=True,
        detail="; ".join(problems) or "chronological and causally reproducible",
        evidence={"problems": problems, "n": len(observations)})


# ---------------------------------------------------------------------------
# axis evaluation
# ---------------------------------------------------------------------------

def evaluate_sample(sufficiency: dict, contract: RobustnessContract) -> AxisFinding:
    problems = []
    if sufficiency["resolved"] < contract.min_pooled_observations:
        problems.append(
            f"{sufficiency['resolved']} resolved observations < "
            f"{contract.min_pooled_observations} required")
    if sufficiency["distinct_years"] < contract.min_distinct_years:
        problems.append(
            f"{sufficiency['distinct_years']} distinct year(s) < "
            f"{contract.min_distinct_years} required — leave-one-year-out "
            "cannot distinguish a structural effect from a single-period "
            "artefact below three years")
    if sufficiency["distinct_symbols"] < contract.min_distinct_symbols:
        problems.append(
            f"{sufficiency['distinct_symbols']} symbol(s) < "
            f"{contract.min_distinct_symbols} required")
    return AxisFinding(
        axis="sample_sufficiency",
        diagnosis=Diagnosis.INSUFFICIENT_SAMPLE if problems else None,
        fired=bool(problems), evaluated=True,
        detail="; ".join(problems) or "sample is sufficient on every axis",
        evidence=sufficiency)


def evaluate_walk_forward(report: dict, contract: RobustnessContract) -> AxisFinding:
    qualifying = report.get("qualifying_fold_count", 0)
    if qualifying < contract.min_walk_forward_folds:
        return AxisFinding(
            axis="walk_forward", diagnosis=None, fired=False, evaluated=False,
            detail=(f"{qualifying} qualifying fold(s) < "
                    f"{contract.min_walk_forward_folds}; stability fraction "
                    "is not informative and the axis is NOT EVALUATED rather "
                    "than silently passed"),
            evidence={"qualifying_fold_count": qualifying})
    fraction = report.get("positive_fold_fraction")
    fired = fraction is not None and fraction < contract.min_positive_fold_fraction
    return AxisFinding(
        axis="walk_forward",
        diagnosis=Diagnosis.WALK_FORWARD_INSTABILITY if fired else None,
        fired=fired, evaluated=True,
        detail=(f"positive fold fraction {fraction} vs required "
                f">= {contract.min_positive_fold_fraction}"),
        evidence={"positive_fold_fraction": fraction,
                  "qualifying_fold_count": qualifying})


def _evaluate_loo(report: dict, contract: RobustnessContract, *, axis: str,
                  diagnosis: Diagnosis, min_groups: int,
                  group_word: str) -> AxisFinding:
    groups = report.get("group_count", 0)
    if groups < min_groups:
        return AxisFinding(
            axis=axis, diagnosis=None, fired=False, evaluated=False,
            detail=(f"{groups} {group_word}(s) available; leave-one-out needs "
                    f"at least {min_groups} to be a test rather than a "
                    "tautology. Axis NOT EVALUATED."),
            evidence={"group_count": groups})
    problems = []
    max_rel = report.get("max_relative_delta")
    if max_rel is not None and max_rel > contract.max_leave_one_out_relative_delta:
        problems.append(
            f"removing one {group_word} moves the metric by {max_rel:.1%} "
            f"> {contract.max_leave_one_out_relative_delta:.0%}")
    if contract.leave_one_out_sign_flip_is_dependency and report.get("any_sign_flip"):
        flipped = [r for r in report["results"] if r["sign_flip"]]
        problems.append(
            f"removing {[r.get('year_removed') or r.get('excluded_symbol') for r in flipped]} "
            "flips the sign of the metric")
    return AxisFinding(
        axis=axis, diagnosis=diagnosis if problems else None,
        fired=bool(problems), evaluated=True,
        detail="; ".join(problems) or f"no single {group_word} carries the result",
        evidence={"max_relative_delta": max_rel,
                  "any_sign_flip": report.get("any_sign_flip"),
                  "group_count": groups})


def evaluate_year(report: dict, contract: RobustnessContract) -> AxisFinding:
    return _evaluate_loo(report, contract, axis="leave_one_year_out",
                         diagnosis=Diagnosis.YEAR_DEPENDENCY,
                         min_groups=contract.min_distinct_years,
                         group_word="year")


def evaluate_symbol(report: dict, contract: RobustnessContract) -> AxisFinding:
    return _evaluate_loo(report, contract, axis="leave_one_symbol_out",
                         diagnosis=Diagnosis.SYMBOL_DEPENDENCY,
                         min_groups=contract.min_distinct_symbols,
                         group_word="symbol")


def evaluate_regime(report: dict, contract: RobustnessContract) -> AxisFinding:
    cells = {k: v for k, v in report.get("cells", {}).items()
             if v.get("n", 0) >= contract.min_observations_per_regime}
    if len(cells) < 2:
        return AxisFinding(
            axis="regime", diagnosis=None, fired=False, evaluated=False,
            detail=(f"{len(cells)} qualifying regime cell(s); at least two are "
                    "needed to compare. Axis NOT EVALUATED."),
            evidence={"qualifying_cells": len(cells)})
    problems = []
    max_share = max((c["share_of_total_positive_r"] for c in cells.values()
                     if c["share_of_total_positive_r"] is not None),
                    default=None)
    if max_share is not None and max_share > contract.max_single_regime_positive_r_share:
        dominant = [k for k, c in cells.items()
                    if c["share_of_total_positive_r"] == max_share]
        problems.append(
            f"regime {dominant} holds {max_share:.1%} of all positive R "
            f"> {contract.max_single_regime_positive_r_share:.0%}")
    positive = sum(1 for c in cells.values() if c["status"] == "POSITIVE")
    fraction = positive / len(cells)
    if fraction < contract.min_positive_regime_fraction:
        problems.append(
            f"only {positive}/{len(cells)} regime cells are positive "
            f"({fraction:.0%} < {contract.min_positive_regime_fraction:.0%})")
    return AxisFinding(
        axis="regime",
        diagnosis=Diagnosis.REGIME_DEPENDENCY if problems else None,
        fired=bool(problems), evaluated=True,
        detail="; ".join(problems) or "effect is present across regimes",
        evidence={"max_single_cell_positive_share": max_share,
                  "positive_cell_fraction": fraction,
                  "qualifying_cells": len(cells)})


def evaluate_tail(report: dict, contract: RobustnessContract) -> AxisFinding:
    if report.get("n", 0) == 0:
        return AxisFinding(axis="tail", diagnosis=None, fired=False,
                           evaluated=False, detail="no resolved observations",
                           evidence={})
    problems = []
    shares = report.get("shares", {})
    for key, limit in (
            ("TOP_1_PCT_POSITIVE_R_SHARE", contract.max_top_1_pct_positive_r_share),
            ("TOP_5_PCT_POSITIVE_R_SHARE", contract.max_top_5_pct_positive_r_share),
            ("TOP_10_PCT_POSITIVE_R_SHARE", contract.max_top_10_pct_positive_r_share)):
        share = shares.get(key, {}).get("share")
        if share is not None and share > limit:
            problems.append(f"{key}={share:.1%} > {limit:.0%}")
    if contract.winsor_sign_flip_is_tail_dependency:
        for name, blob in report.get("winsorized", {}).items():
            if blob.get("sign_flip_vs_canonical"):
                problems.append(
                    f"{name} flips the mean from positive to non-positive, so "
                    "the result does not survive clipping its own tail")
    return AxisFinding(
        axis="tail",
        diagnosis=Diagnosis.TAIL_DEPENDENCY if problems else None,
        fired=bool(problems), evaluated=True,
        detail="; ".join(problems) or "upside is not concentrated in few outcomes",
        evidence={"shares": {k: v.get("share") for k, v in shares.items()},
                  "winsorized": {k: v.get("mean_r")
                                 for k, v in report.get("winsorized", {}).items()}})


def evaluate_mean_median(report: dict) -> AxisFinding:
    fired = bool(report.get("asymmetric_tail_dependence"))
    return AxisFinding(
        axis="mean_median",
        diagnosis=Diagnosis.ASYMMETRIC_TAIL_DEPENDENCE if fired else None,
        fired=fired, evaluated=report.get("n", 0) > 0,
        detail=(f"mean {report.get('MEAN_R')} vs median "
                f"{report.get('MEDIAN_R')}; shape {report.get('shape')}"),
        evidence={"shape": report.get("shape"),
                  "MEAN_MINUS_MEDIAN_R": report.get("MEAN_MINUS_MEDIAN_R"),
                  "asymmetric": fired})


def evaluate_bootstrap(report: dict, contract: RobustnessContract) -> AxisFinding:
    mean_block = report.get("metrics", {}).get("mean_r", {})
    low = mean_block.get("CI_LOW")
    if low is None:
        return AxisFinding(axis="bootstrap", diagnosis=None, fired=False,
                           evaluated=False, detail="no resolved observations",
                           evidence={})
    fired = low <= contract.mean_r_required_floor
    return AxisFinding(
        axis="bootstrap",
        diagnosis=Diagnosis.STATISTICAL_UNCERTAINTY if fired else None,
        fired=fired, evaluated=True,
        detail=(f"mean R 95% CI lower bound {low:.6f} vs required floor "
                f"{contract.mean_r_required_floor}"),
        evidence={"mean_r": mean_block})


def evaluate_parameters(report: dict) -> AxisFinding:
    if report.get("status") == "NOT_APPLICABLE":
        reasons = report.get("reason") or "; ".join(
            f"{p['PARAMETER']}: {p['reason']}"
            for p in report.get("parameters", []) if p.get("reason"))
        return AxisFinding(
            axis="parameter_neighborhood", diagnosis=None, fired=False,
            evaluated=False,
            detail=f"NOT_APPLICABLE — {reasons or 'no perturbable parameter'}",
            evidence={"status": "NOT_APPLICABLE",
                      "parameters": report.get("parameters", [])})
    all_stable = report.get("all_stable")
    fired = all_stable is False
    return AxisFinding(
        axis="parameter_neighborhood",
        diagnosis=Diagnosis.PARAMETER_FRAGILITY if fired else None,
        fired=fired, evaluated=all_stable is not None,
        detail=("a small perturbation destroys the result" if fired
                else "result survives the local neighbourhood"),
        evidence={"all_stable": all_stable})


def evaluate_friction(readiness: FrictionReadiness) -> AxisFinding:
    fired = readiness.blocks_economic_claims
    return AxisFinding(
        axis="friction_readiness",
        diagnosis=Diagnosis.FRICTION_AUTHORITY_INCOMPLETE if fired else None,
        fired=fired, evaluated=True,
        detail=(f"{readiness}: structural analysis proceeds, economic and "
                "edge claims are blocked" if fired
                else "friction measured; economic claims unblocked"),
        evidence={"readiness": str(readiness),
                  "blocks_structural_analysis": False,
                  "blocks_economic_claims": fired})


# ---------------------------------------------------------------------------
# decision
# ---------------------------------------------------------------------------

def decide(findings: list[AxisFinding], *, contract: RobustnessContract,
           friction: FrictionReadiness) -> GateDecision:
    """Apply the frozen precedence to the axis findings."""
    fired = {str(f.diagnosis): f for f in findings
             if f.fired and f.diagnosis is not None}

    primary_name = next((d for d in DIAGNOSIS_PRECEDENCE if d in fired), None)
    secondary = [Diagnosis(d) for d in DIAGNOSIS_PRECEDENCE
                 if d in fired and d != primary_name]
    secondary += [Diagnosis(d) for d in SECONDARY_ONLY_DIAGNOSES if d in fired]

    # Friction is derived from the readiness argument directly, not only
    # from a finding that a caller might forget to pass. The gate must not
    # be able to report a clean verdict while friction is unmeasured
    # merely because one axis was omitted from the findings list.
    if (friction is not FrictionReadiness.FRICTION_MEASURED
            and Diagnosis.FRICTION_AUTHORITY_INCOMPLETE not in secondary):
        secondary.append(Diagnosis.FRICTION_AUTHORITY_INCOMPLETE)

    unevaluated = tuple(f.axis for f in findings if not f.evaluated)

    if primary_name is None:
        # Nothing blocking fired. If any axis could not be evaluated the
        # evidence is incomplete rather than supportive.
        blocking_unevaluated = tuple(
            a for a in unevaluated if a != "parameter_neighborhood")
        if blocking_unevaluated:
            return GateDecision(
                decision=Decision.INSUFFICIENT_EVIDENCE,
                primary_diagnosis=Diagnosis.INSUFFICIENT_SAMPLE,
                secondary_diagnoses=tuple(secondary),
                findings=findings, contract_sha256=contract.hash(),
                friction_readiness=friction, unevaluated_axes=unevaluated)
        return GateDecision(
            decision=Decision.PRE_OOS_PASS,
            primary_diagnosis=Diagnosis.ROBUSTNESS_SUPPORTED,
            secondary_diagnoses=tuple(secondary),
            findings=findings, contract_sha256=contract.hash(),
            friction_readiness=friction, unevaluated_axes=unevaluated)

    primary = Diagnosis(primary_name)
    decision = (Decision.INSUFFICIENT_EVIDENCE
                if primary in (Diagnosis.INSUFFICIENT_SAMPLE,)
                else Decision.PRE_OOS_FAIL)
    return GateDecision(
        decision=decision, primary_diagnosis=primary,
        secondary_diagnoses=tuple(secondary), findings=findings,
        contract_sha256=contract.hash(), friction_readiness=friction,
        unevaluated_axes=unevaluated)
