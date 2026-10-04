"""FunnelDiagnosticReportV3 — cross-asset diagnostic report schema.

Crypto rule: session_context is serialized as the literal string
"NOT_APPLICABLE" — intentionally not applicable is NOT missing evidence and
must never appear as null/absent.
"""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ag_edgelab.universal.matrix import StageDiagnostic
from ag_edgelab.universal.profile import MarketType, SessionBehavior
from ag_edgelab.universal.root_cause import RootCauseResult

REPORT_SCHEMA = "FunnelDiagnosticReportV3"
SESSION_CONTEXT_NOT_APPLICABLE = "NOT_APPLICABLE"


class TriggerSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    direction: Mapping[str, Any]
    location: Mapping[str, Any]


class ConfirmationSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    setup: Mapping[str, Any]
    entry: Mapping[str, Any]


class TargetSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: Mapping[str, Any]
    natural_target: Mapping[str, Any]


class EconomicsSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    authoritative: bool
    realized: Mapping[str, Any] = Field(default_factory=dict)
    note: str = ""


class FunnelDiagnosticReportV3(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = REPORT_SCHEMA
    strategy_id: str
    market_type: MarketType
    session_behavior: SessionBehavior
    trigger: TriggerSection
    confirmation: ConfirmationSection
    target: TargetSection
    economics: EconomicsSection
    # FX: structured session context. CRYPTO: the literal "NOT_APPLICABLE".
    session_context: Mapping[str, Any] | str
    matrix: tuple[StageDiagnostic, ...] = ()
    root_cause: RootCauseResult | None = None
    dataset_role: str = "DEVELOPMENT"
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def session_context_rules(self) -> "FunnelDiagnosticReportV3":
        if self.market_type == MarketType.CRYPTO:
            if self.session_behavior == SessionBehavior.REQUIRED:
                raise ValueError("crypto reports cannot REQUIRE sessions")
            if self.session_behavior == SessionBehavior.NOT_APPLICABLE \
                    and self.session_context != SESSION_CONTEXT_NOT_APPLICABLE:
                raise ValueError(
                    "crypto session absence is intentional: session_context must be the "
                    "literal 'NOT_APPLICABLE', never missing/None/empty evidence")
        if self.market_type == MarketType.FX and isinstance(self.session_context, str):
            raise ValueError("FX reports must carry a structured session_context mapping")
        return self
