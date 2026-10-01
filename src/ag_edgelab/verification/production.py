from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ag_edgelab.data.fingerprint import sha256_json

HEX64 = r"^[0-9a-f]{64}$"
REQUIRED_FRICTION_GRID = (1.0, 1.25, 1.5)


class EdgeVerdict(StrEnum):
    EDGE_VERIFIED = "EDGE_VERIFIED"
    NO_EDGE = "NO_EDGE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    VERIFICATION_BLOCKED = "VERIFICATION_BLOCKED"


class VerificationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    policy_id: str
    min_oos_trades: int = Field(ge=30)
    min_oos_expectancy_r: float = Field(ge=0.0, allow_inf_nan=False)
    min_oos_profit_factor: float = Field(ge=1.0, allow_inf_nan=False)
    max_drawdown_r: float = Field(gt=0, le=20.0, allow_inf_nan=False)
    min_bootstrap_ci_low_r: float = Field(ge=0.0, allow_inf_nan=False)
    min_walk_forward_folds: int = Field(ge=3)
    min_positive_walk_forward_fraction: float = Field(ge=0.6, le=1.0, allow_inf_nan=False)
    min_regime_sample: int = Field(ge=10)
    required_friction_multipliers: tuple[float, ...]
    max_parity_trade_count_delta: int = Field(ge=0, le=1)
    max_parity_expectancy_delta_r: float = Field(ge=0.0, le=0.02, allow_inf_nan=False)

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


CANONICAL_POLICY_V1 = VerificationPolicy(
    policy_id="EDGE_VERIFICATION_V1",
    min_oos_trades=30,
    min_oos_expectancy_r=0.0,
    min_oos_profit_factor=1.0,
    max_drawdown_r=20.0,
    min_bootstrap_ci_low_r=0.0,
    min_walk_forward_folds=3,
    min_positive_walk_forward_fraction=0.6,
    min_regime_sample=10,
    required_friction_multipliers=REQUIRED_FRICTION_GRID,
    max_parity_trade_count_delta=1,
    max_parity_expectancy_delta_r=0.02,
)
POLICY_REGISTRY = {CANONICAL_POLICY_V1.policy_id: CANONICAL_POLICY_V1}


class MetricSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    trades: int = Field(ge=0)
    expectancy_r: float | None = Field(default=None, allow_inf_nan=False)
    profit_factor: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_drawdown_r: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class FrictionPoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    multiplier: float = Field(ge=1.0, allow_inf_nan=False)
    expectancy_r: float = Field(allow_inf_nan=False)


class FrictionStressResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    points: tuple[FrictionPoint, ...]

    @model_validator(mode="after")
    def grid_is_valid(self) -> "FrictionStressResult":
        multipliers = tuple(p.multiplier for p in self.points)
        if len(set(multipliers)) != len(multipliers):
            raise ValueError("duplicate friction multipliers")
        return self

    def survives(self, required: tuple[float, ...], oos_expectancy: float) -> bool:
        by_m = {p.multiplier: p.expectancy_r for p in self.points}
        if any(m not in by_m for m in required):
            return False
        if not math.isclose(by_m[1.0], oos_expectancy, abs_tol=1e-12):
            return False
        values = [by_m[m] for m in required]
        return all(v > 0 for v in values) and all(b <= a + 1e-12 for a, b in zip(values, values[1:]))


class StabilityEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    result_sha256: str = Field(pattern=HEX64)
    stable: bool


class WalkForwardResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    fold_expectancy_r: tuple[float, ...]

    @model_validator(mode="after")
    def finite(self) -> "WalkForwardResult":
        if any(not math.isfinite(x) for x in self.fold_expectancy_r):
            raise ValueError("walk-forward values must be finite")
        return self

    @property
    def positive_fraction(self) -> float:
        return 0.0 if not self.fold_expectancy_r else sum(x > 0 for x in self.fold_expectancy_r) / len(self.fold_expectancy_r)


class RegimeResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str = Field(min_length=1)
    trades: int = Field(ge=0)
    expectancy_r: float | None = Field(default=None, allow_inf_nan=False)


class ParityResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    reference_engine_id: str = Field(min_length=1)
    independent_engine_id: str = Field(min_length=1)
    reference_code_sha256: str = Field(pattern=HEX64)
    independent_code_sha256: str = Field(pattern=HEX64)
    reference_trade_list_sha256: str = Field(pattern=HEX64)
    independent_trade_list_sha256: str = Field(pattern=HEX64)
    reference_trades: int = Field(ge=0)
    independent_trades: int = Field(ge=0)
    reference_expectancy_r: float = Field(allow_inf_nan=False)
    independent_expectancy_r: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def engines_are_independent(self) -> "ParityResult":
        if self.reference_engine_id == self.independent_engine_id:
            raise ValueError("parity requires distinct engine ids")
        if self.reference_code_sha256 == self.independent_code_sha256:
            raise ValueError("parity requires distinct code hashes")
        return self


class EdgeValidationEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    strategy_id: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    strategy_sha256: str = Field(pattern=HEX64)
    funnel_sha256: str = Field(pattern=HEX64)
    parameters_sha256: str = Field(pattern=HEX64)
    oos_dataset_sha256: str = Field(pattern=HEX64)
    cost_model_sha256: str = Field(pattern=HEX64)
    verification_policy_id: str
    verification_policy_sha256: str = Field(pattern=HEX64)
    frozen_variant_sha256: str = Field(pattern=HEX64)
    exposure_ledger_proof_sha256: str = Field(pattern=HEX64)
    holdout_was_unseen: bool
    candidate_was_frozen: bool
    oos: MetricSet
    friction: FrictionStressResult | None = None
    stability: StabilityEvidence | None = None
    walk_forward: WalkForwardResult | None = None
    regimes: tuple[RegimeResult, ...] = ()
    parity: ParityResult | None = None
    bootstrap_ci_low_r: float | None = Field(default=None, allow_inf_nan=False)
    bootstrap_ci_high_r: float | None = Field(default=None, allow_inf_nan=False)
    evidence_hashes: tuple[str, ...]

    @model_validator(mode="after")
    def evidence_is_well_formed(self) -> "EdgeValidationEvidence":
        if not self.evidence_hashes or any(len(h) != 64 or any(c not in "0123456789abcdef" for c in h) for h in self.evidence_hashes):
            raise ValueError("non-empty valid evidence hashes required")
        if self.bootstrap_ci_low_r is not None and self.bootstrap_ci_high_r is not None and self.bootstrap_ci_low_r > self.bootstrap_ci_high_r:
            raise ValueError("bootstrap lower bound exceeds upper bound")
        names = [r.name for r in self.regimes]
        if len(names) != len(set(names)):
            raise ValueError("duplicate regime names")
        if sum(r.trades for r in self.regimes) > self.oos.trades:
            raise ValueError("regime trade counts exceed OOS population")
        return self


class EdgeValidationArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    evidence: EdgeValidationEvidence
    policy: VerificationPolicy
    verdict: EdgeVerdict
    gate_results: tuple[tuple[str, bool], ...]
    reasons: tuple[str, ...]
    verifier_version: str = "EDGE_VERIFIER_V1"
    seal_sha256: str = Field(pattern=HEX64)

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


def _canonical_policy(policy_id: str) -> VerificationPolicy:
    if policy_id not in POLICY_REGISTRY:
        raise ValueError("unknown verification policy")
    return POLICY_REGISTRY[policy_id]


def verify_edge(evidence: EdgeValidationEvidence) -> EdgeValidationArtifact:
    # Re-validate serialized input so model_construct/model_copy cannot smuggle invalid evidence.
    e = EdgeValidationEvidence.model_validate(evidence.model_dump(mode="python"))
    policy = _canonical_policy(e.verification_policy_id)
    gates: dict[str, bool] = {}
    gates["POLICY_HASH"] = e.verification_policy_sha256 == policy.sha256
    gates["FROZEN_UNSEEN"] = e.candidate_was_frozen and e.holdout_was_unseen
    gates["EVIDENCE_INTEGRITY"] = bool(e.evidence_hashes and e.frozen_variant_sha256 and e.exposure_ledger_proof_sha256)
    gates["OOS_POPULATION"] = e.oos.trades >= policy.min_oos_trades
    gates["OOS_EXPECTANCY"] = e.oos.expectancy_r is not None and e.oos.expectancy_r > policy.min_oos_expectancy_r
    gates["OOS_PF"] = e.oos.profit_factor is not None and e.oos.profit_factor > policy.min_oos_profit_factor
    gates["OOS_DD"] = e.oos.max_drawdown_r is not None and e.oos.max_drawdown_r <= policy.max_drawdown_r
    gates["BOOTSTRAP"] = e.bootstrap_ci_low_r is not None and e.bootstrap_ci_high_r is not None and e.bootstrap_ci_low_r > policy.min_bootstrap_ci_low_r
    gates["FRICTION_STRESS"] = e.friction is not None and e.oos.expectancy_r is not None and e.friction.survives(policy.required_friction_multipliers, e.oos.expectancy_r)
    gates["PARAMETER_STABILITY"] = e.stability is not None and e.stability.stable
    gates["WALK_FORWARD"] = e.walk_forward is not None and len(e.walk_forward.fold_expectancy_r) >= policy.min_walk_forward_folds and e.walk_forward.positive_fraction >= policy.min_positive_walk_forward_fraction
    eligible = [r for r in e.regimes if r.trades >= policy.min_regime_sample]
    # V1 supports a preregistered regime-specific edge: every adequately sampled claimed regime must remain positive.
    gates["REGIME_EVIDENCE"] = bool(eligible) and all(r.expectancy_r is not None and r.expectancy_r > 0 for r in eligible)
    gates["INDEPENDENT_PARITY"] = (
        e.parity is not None
        and e.parity.reference_trades == e.oos.trades
        and abs(e.parity.reference_trades - e.parity.independent_trades) <= policy.max_parity_trade_count_delta
        and e.oos.expectancy_r is not None
        and math.isclose(e.parity.reference_expectancy_r, e.oos.expectancy_r, abs_tol=1e-12)
        and abs(e.parity.reference_expectancy_r - e.parity.independent_expectancy_r) <= policy.max_parity_expectancy_delta_r
    )
    reasons = tuple(name for name, passed in gates.items() if not passed)
    blocking = {"POLICY_HASH", "FROZEN_UNSEEN", "EVIDENCE_INTEGRITY", "OOS_POPULATION", "BOOTSTRAP", "FRICTION_STRESS", "PARAMETER_STABILITY", "WALK_FORWARD", "REGIME_EVIDENCE", "INDEPENDENT_PARITY"}
    if any(not gates[x] for x in blocking):
        verdict = EdgeVerdict.INSUFFICIENT_EVIDENCE if gates["POLICY_HASH"] and gates["FROZEN_UNSEEN"] else EdgeVerdict.VERIFICATION_BLOCKED
    elif not (gates["OOS_EXPECTANCY"] and gates["OOS_PF"] and gates["OOS_DD"]):
        verdict = EdgeVerdict.NO_EDGE
    else:
        verdict = EdgeVerdict.EDGE_VERIFIED
    gate_results = tuple(sorted(gates.items()))
    seal_payload = {"evidence": e.model_dump(mode="python"), "policy": policy.model_dump(mode="python"), "verdict": verdict.value, "gate_results": gate_results, "reasons": reasons, "verifier_version": "EDGE_VERIFIER_V1"}
    seal = sha256_json(seal_payload)
    return EdgeValidationArtifact(evidence=e, policy=policy, verdict=verdict, gate_results=gate_results, reasons=reasons, seal_sha256=seal)


def validate_artifact(artifact: EdgeValidationArtifact) -> bool:
    """Consumers must validate/recompute rather than trust caller-supplied verdict fields."""
    canonical = verify_edge(artifact.evidence)
    return canonical.model_dump(mode="python") == artifact.model_dump(mode="python")
