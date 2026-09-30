from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ag_edgelab.contracts.funnel import FunnelStage


class StageMode(StrEnum):
    ALL = "ALL"
    ANY = "ANY"
    SEQUENCE = "SEQUENCE"


class RuleRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    rule_version: str


class StageSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: FunnelStage
    mode: StageMode = StageMode.ALL
    rules: tuple[RuleRef, ...] = Field(min_length=1)


class FunnelDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    definition_id: str
    version: str
    stages: tuple[StageSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def stages_unique_and_ordered(self) -> "FunnelDefinition":
        expected_order = {
            FunnelStage.CONTEXT: 0,
            FunnelStage.LOCATION: 1,
            FunnelStage.TRIGGER: 2,
            FunnelStage.GEOMETRY: 3,
            FunnelStage.EXECUTION: 4,
        }
        seen = set()
        last = -1
        for spec in self.stages:
            if spec.stage in seen:
                raise ValueError(f"duplicate funnel stage: {spec.stage.value}")
            seen.add(spec.stage)
            current = expected_order[spec.stage]
            if current <= last:
                raise ValueError("funnel stages must follow canonical order")
            last = current
        return self
