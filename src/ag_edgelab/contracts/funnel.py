from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field


class FunnelStage(StrEnum):
    CONTEXT = "CONTEXT"
    LOCATION = "LOCATION"
    TRIGGER = "TRIGGER"
    GEOMETRY = "GEOMETRY"
    EXECUTION = "EXECUTION"


class RuleResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    rule_version: str
    rule_hash: str
    passed: bool
    evaluated_at: datetime
    features: Mapping[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None


class FunnelStageResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    stage: FunnelStage
    passed: bool
    as_of: datetime
    rule_results: tuple[RuleResult, ...]
    failure_reason: str | None = None
