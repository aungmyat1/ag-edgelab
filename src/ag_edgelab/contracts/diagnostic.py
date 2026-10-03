from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ag_edgelab.data.fingerprint import sha256_json

HEX64 = r"^[0-9a-f]{64}$"


class FunnelGroup(StrEnum):
    """Universal diagnostic groups. The thirds are categories, not scores."""

    TRIGGER = "TRIGGER"
    CONFIRMATION = "CONFIRMATION"
    OUTCOME = "OUTCOME"


class DiagnosticRuleBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node_id: str = Field(min_length=1)
    funnel_group: FunnelGroup
    sequence: int = Field(ge=0)


class DiagnosticDefinition(BaseModel):
    """Versioned mapping from strategy nodes to the universal three-funnel view."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    diagnostic_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    strategy_sha256: str = Field(pattern=HEX64)
    bindings: tuple[DiagnosticRuleBinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_bindings(self) -> "DiagnosticDefinition":
        node_ids = [item.node_id for item in self.bindings]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("each strategy node must map to exactly one funnel group")
        group_sequences = [(item.funnel_group, item.sequence) for item in self.bindings]
        if len(group_sequences) != len(set(group_sequences)):
            raise ValueError("sequence must be unique within each funnel group")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json({
            "diagnostic_id": self.diagnostic_id,
            "version": self.version,
            "strategy_sha256": self.strategy_sha256,
            "bindings": [
                {"node_id": item.node_id, "funnel_group": item.funnel_group, "sequence": item.sequence}
                for item in sorted(self.bindings, key=lambda x: (x.funnel_group, x.sequence, x.node_id))
            ],
        })


class ExcursionObservation(BaseModel):
    """Authoritative post-entry excursion measurement in initial-risk units."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    candidate_id: str = Field(min_length=1)
    trade_id: str = Field(min_length=1)
    mfe_r: float = Field(ge=0)
    mae_r: float = Field(ge=0)
    observation_policy_id: str = Field(min_length=1)


class StageExcursionObservation(BaseModel):
    """Frozen-policy future excursion attached to one reached rule boundary.

    This is diagnostic/counterfactual evidence only.  It does not assert that a
    trade existed, nor that the rule caused the excursion.  ``mfe_r``/``mae_r``
    must be computed by an external, preregistered observation policy defining
    the anchor, risk unit, horizon and stop/termination convention.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    candidate_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    mfe_r: float = Field(ge=0)
    mae_r: float = Field(ge=0)
    observation_policy_id: str = Field(min_length=1)


class ExitPolicyResult(BaseModel):
    """Realized result for a preregistered DEVELOPMENT exit policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    candidate_id: str = Field(min_length=1)
    trade_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    net_result_r: float


class WeakPointLabel(StrEnum):
    LOW_FLOW = "LOW_FLOW"
    OVER_FILTERING_CANDIDATE = "OVER_FILTERING_CANDIDATE"
    LOW_DISCRIMINATION = "LOW_DISCRIMINATION"
    POOR_TRIGGER_QUALITY = "POOR_TRIGGER_QUALITY"
    CONFIRMATION_ATTRITION = "CONFIRMATION_ATTRITION"
    ENTRY_UNREACHABLE = "ENTRY_UNREACHABLE"
    GEOMETRY_REJECTION = "GEOMETRY_REJECTION"
    TP_TOO_AMBITIOUS_CANDIDATE = "TP_TOO_AMBITIOUS_CANDIDATE"
    STOP_GEOMETRY_CANDIDATE = "STOP_GEOMETRY_CANDIDATE"
    FRICTION_SENSITIVE = "FRICTION_SENSITIVE"
    REGIME_SENSITIVE = "REGIME_SENSITIVE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    NO_DIAGNOSIS = "NO_DIAGNOSIS"
