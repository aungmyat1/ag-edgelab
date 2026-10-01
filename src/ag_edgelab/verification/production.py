from __future__ import annotations

from enum import StrEnum
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ag_edgelab.data.fingerprint import sha256_json


class EdgeVerdict(StrEnum):
    EDGE_VERIFIED = "EDGE_VERIFIED"
    NO_EDGE = "NO_EDGE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    VERIFICATION_BLOCKED = "VERIFICATION_BLOCKED"


class VerificationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    policy_id: str = "EDGE_VERIFICATION_V1"
    min_oos_trades: int = Field(default=30, ge=1)
    min_oos_expectancy_r: float = 0.0
    min_oos_profit_factor: float = Field(default=1.0, gt=0)
    max_drawdown_r: float = Field(default=20.0, gt=0)
    min_positive_walk_forward_fraction: float = Field(default=0.6, ge=0, le=1)
    min_regime_sample: int = Field(default=10, ge=1)
    max_friction_multiplier_required: float = Field(default=1.5, ge=1)
    max_parity_trade_count_delta: int = Field(default=1, ge=0)
    max_parity_expectancy_delta_r: float = Field(default=0.02, ge=0)
    require_parameter_stability: bool = True
    require_independent_parity: bool = True

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


class MetricSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    trades: int = Field(ge=0)
    expectancy_r: float | None = None
    profit_factor: float | None = Field(default=None, ge=0)
    max_drawdown_r: float | None = Field(default=None, ge=0)


class FrictionStressResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    expectancy_by_multiplier: Mapping[float, float]

    def survives(self, multiplier: float) -> bool:
        eligible = [m for m in self.expectancy_by_multiplier if m >= multiplier]
        return bool(eligible) and self.expectancy_by_multiplier[min(eligible)] > 0


class WalkForwardResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    fold_expectancy_r: tuple[float, ...]

    @property
    def positive_fraction(self) -> float:
        return 0.0 if not self.fold_expectancy_r else sum(x > 0 for x in self.fold_expectancy_r) / len(self.fold_expectancy_r)


class RegimeResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    trades: int = Field(ge=0)
    expectancy_r: float | None = None


class ParityResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    reference_trades: int = Field(ge=0)
    independent_trades: int = Field(ge=0)
    reference_expectancy_r: float
    independent_expectancy_r: float


class EdgeValidationEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    strategy_id: str
    strategy_version: str
    strategy_sha256: str
    funnel_sha256: str
    parameters_sha256: str
    oos_dataset_sha256: str
    cost_model_sha256: str
    verification_policy_sha256: str
    holdout_was_unseen: bool
    candidate_was_frozen: bool
    oos: MetricSet
    friction: FrictionStressResult | None = None
    parameter_stable: bool | None = None
    walk_forward: WalkForwardResult | None = None
    regimes: tuple[RegimeResult, ...] = ()
    parity: ParityResult | None = None
    bootstrap_ci_low_r: float | None = None
    bootstrap_ci_high_r: float | None = None
    evidence_hashes: tuple[str, ...] = ()


class EdgeValidationArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    evidence: EdgeValidationEvidence
    verdict: EdgeVerdict
    gate_results: Mapping[str, bool]
    reasons: tuple[str, ...]

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


def verify_edge(e: EdgeValidationEvidence, policy: VerificationPolicy) -> EdgeValidationArtifact:
    gates: dict[str, bool] = {}
    reasons: list[str] = []
    gates["POLICY_HASH"] = e.verification_policy_sha256 == policy.sha256
    gates["FROZEN_UNSEEN"] = e.candidate_was_frozen and e.holdout_was_unseen
    gates["OOS_POPULATION"] = e.oos.trades >= policy.min_oos_trades
    gates["OOS_EXPECTANCY"] = e.oos.expectancy_r is not None and e.oos.expectancy_r > policy.min_oos_expectancy_r
    gates["OOS_PF"] = e.oos.profit_factor is not None and e.oos.profit_factor > policy.min_oos_profit_factor
    gates["OOS_DD"] = e.oos.max_drawdown_r is not None and e.oos.max_drawdown_r <= policy.max_drawdown_r
    gates["BOOTSTRAP"] = e.bootstrap_ci_low_r is not None and e.bootstrap_ci_low_r > 0
    gates["FRICTION_STRESS"] = e.friction is not None and e.friction.survives(policy.max_friction_multiplier_required)
    gates["PARAMETER_STABILITY"] = (e.parameter_stable is True) if policy.require_parameter_stability else True
    gates["WALK_FORWARD"] = e.walk_forward is not None and e.walk_forward.positive_fraction >= policy.min_positive_walk_forward_fraction
    eligible_regimes = [r for r in e.regimes if r.trades >= policy.min_regime_sample]
    gates["REGIME_EVIDENCE"] = bool(eligible_regimes)
    if policy.require_independent_parity:
        gates["INDEPENDENT_PARITY"] = e.parity is not None and abs(e.parity.reference_trades-e.parity.independent_trades) <= policy.max_parity_trade_count_delta and abs(e.parity.reference_expectancy_r-e.parity.independent_expectancy_r) <= policy.max_parity_expectancy_delta_r
    else:
        gates["INDEPENDENT_PARITY"] = True

    for name, passed in gates.items():
        if not passed:
            reasons.append(name)

    blocking = {"POLICY_HASH", "FROZEN_UNSEEN", "OOS_POPULATION", "BOOTSTRAP", "FRICTION_STRESS", "PARAMETER_STABILITY", "WALK_FORWARD", "REGIME_EVIDENCE", "INDEPENDENT_PARITY"}
    if any(not gates[x] for x in blocking):
        verdict = EdgeVerdict.INSUFFICIENT_EVIDENCE if gates["POLICY_HASH"] and gates["FROZEN_UNSEEN"] else EdgeVerdict.VERIFICATION_BLOCKED
    elif not (gates["OOS_EXPECTANCY"] and gates["OOS_PF"] and gates["OOS_DD"]):
        verdict = EdgeVerdict.NO_EDGE
    else:
        verdict = EdgeVerdict.EDGE_VERIFIED
    return EdgeValidationArtifact(evidence=e, verdict=verdict, gate_results=gates, reasons=tuple(reasons))
