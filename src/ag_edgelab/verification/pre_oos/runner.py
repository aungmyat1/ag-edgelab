"""Orchestration: identity -> admission -> axes -> decision.

Kept separate from :mod:`gate` so the decision logic can be tested
against hand-built findings without constructing a whole population, and
so the ordering of the pipeline is visible in one place.

The order is not arbitrary. Identity is checked before anything is
measured, admission before anything is computed, and causality before
any axis trusts a timestamp. Each stage can only make the evidence
smaller or refuse it; none can rescue a failure upstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ag_edgelab.verification.pre_oos import axes as A
from ag_edgelab.verification.pre_oos.contract import RobustnessContract
from ag_edgelab.verification.pre_oos.gate import (
    Decision, Diagnosis, FrictionReadiness, GateDecision, decide,
    evaluate_bootstrap, evaluate_friction, evaluate_mean_median,
    evaluate_parameters, evaluate_regime, evaluate_sample, evaluate_symbol,
    evaluate_tail, evaluate_walk_forward, evaluate_year, temporal_integrity,
    AxisFinding,
)
from ag_edgelab.verification.pre_oos.identity import (
    CandidateIdentity, CandidateIdentityInvalid, assert_identity,
)
from ag_edgelab.verification.pre_oos.observations import (
    ConsumedWindow, DatasetRoleViolation, LineageContamination,
    LineageDeclaration, Observation, admit,
)


@dataclass
class RobustnessRun:
    """Everything the gate produced, ready for artifact emission."""

    decision: GateDecision
    identity: dict
    role_audit: dict
    sample: dict
    walk_forward: dict
    year: dict
    symbol: dict
    regime: dict
    tail: dict
    mean_median: dict
    bootstrap: dict
    parameters: dict
    blocked_reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "decision": self.decision.as_dict(),
            "candidate_identity": self.identity,
            "dataset_authority": self.role_audit,
            "sample_sufficiency": self.sample,
            "walk_forward": self.walk_forward,
            "leave_one_year_out": self.year,
            "leave_one_symbol_out": self.symbol,
            "regime_robustness": self.regime,
            "tail_contribution": self.tail,
            "mean_median_analysis": self.mean_median,
            "bootstrap_uncertainty": self.bootstrap,
            "parameter_neighborhood": self.parameters,
            "blocked_reason": self.blocked_reason,
        }


def _blocked(diagnosis: Diagnosis, reason: str, contract: RobustnessContract,
             friction: FrictionReadiness, identity: dict) -> RobustnessRun:
    finding = AxisFinding(axis="authority", diagnosis=diagnosis, fired=True,
                          evaluated=True, detail=reason)
    decision = GateDecision(
        decision=Decision.NOT_EVALUATED, primary_diagnosis=diagnosis,
        secondary_diagnoses=(), findings=[finding],
        contract_sha256=contract.hash(), friction_readiness=friction)
    empty: dict = {}
    return RobustnessRun(
        decision=decision, identity=identity, role_audit=empty, sample=empty,
        walk_forward=empty, year=empty, symbol=empty, regime=empty, tail=empty,
        mean_median=empty, bootstrap=empty, parameters=empty,
        blocked_reason=reason)


def run_gate(
    *,
    identity: CandidateIdentity,
    observations: list[Observation],
    lineage: LineageDeclaration,
    folds: list[A.Fold],
    contract: RobustnessContract,
    friction: FrictionReadiness,
    consumed_windows: tuple[ConsumedWindow, ...] = (),
    parameters: list[A.PerturbableParameter] | None = None,
    parameter_evaluator=None,
    regime_recompute=None,
    natural_target_median: float | None = None,
) -> RobustnessRun:
    """Run the full pre-OOS robustness campaign. Fails closed at each stage."""
    identity_blob = identity.as_dict()

    # ---- 1. identity -------------------------------------------------
    try:
        assert_identity(identity)
    except CandidateIdentityInvalid as exc:
        return _blocked(Diagnosis.CANDIDATE_IDENTITY_INVALID, str(exc),
                        contract, friction, identity_blob)

    # ---- 2. dataset role + lineage -----------------------------------
    try:
        admitted, audit = admit(observations, lineage=lineage,
                                consumed_windows=consumed_windows)
    except (DatasetRoleViolation, LineageContamination) as exc:
        return _blocked(Diagnosis.DATASET_ROLE_VIOLATION, str(exc),
                        contract, friction, identity_blob)

    # ---- 3. axes ------------------------------------------------------
    findings: list[AxisFinding] = []
    findings.append(temporal_integrity(admitted,
                                       regime_recompute=regime_recompute))

    sample = A.sample_sufficiency(admitted)
    findings.append(evaluate_sample(sample, contract))

    wf = A.walk_forward(admitted, folds,
                        natural_target_median=natural_target_median)
    findings.append(evaluate_walk_forward(wf, contract))

    year = A.leave_one_year_out(admitted)
    findings.append(evaluate_year(year, contract))

    symbol = A.leave_one_symbol_out(admitted)
    findings.append(evaluate_symbol(symbol, contract))

    regime = A.regime_robustness(admitted)
    findings.append(evaluate_regime(regime, contract))

    tail = A.tail_contribution(admitted, winsor_levels=contract.winsor_levels)
    findings.append(evaluate_tail(tail, contract))

    mm = A.mean_median_analysis(
        admitted, frequent_rate=contract.frequent_outcome_rate,
        divergence_ratio=contract.mean_median_divergence_ratio)
    findings.append(evaluate_mean_median(mm))

    boot = A.bootstrap_uncertainty(
        admitted, samples=contract.bootstrap_samples,
        seed=contract.bootstrap_seed, confidence=contract.bootstrap_confidence)
    findings.append(evaluate_bootstrap(boot, contract))

    params = A.parameter_neighborhood(
        parameters or [], parameter_evaluator or (lambda n, v: None),
        perturbations=contract.parameter_perturbations,
        min_positive_fraction=contract.min_positive_neighbor_fraction,
        max_relative_spike=contract.max_relative_spike)
    findings.append(evaluate_parameters(params))

    findings.append(evaluate_friction(friction))

    # ---- 4. decide ----------------------------------------------------
    decision = decide(findings, contract=contract, friction=friction)
    return RobustnessRun(
        decision=decision, identity=identity_blob, role_audit=audit.as_dict(),
        sample=sample, walk_forward=wf, year=year, symbol=symbol,
        regime=regime, tail=tail, mean_median=mm, bootstrap=boot,
        parameters=params)
