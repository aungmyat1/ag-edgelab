from __future__ import annotations

from enum import StrEnum
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MutationType(StrEnum):
    REMOVE_STAGE = "REMOVE_STAGE"
    REPLACE_STAGE = "REPLACE_STAGE"
    ADD_STAGE = "ADD_STAGE"
    CHANGE_THRESHOLD = "CHANGE_THRESHOLD"
    CHANGE_EXIT = "CHANGE_EXIT"
    SPLIT_REGIME = "SPLIT_REGIME"


class DatasetExposure(StrEnum):
    UNSEEN = "UNSEEN"
    DEVELOPMENT = "DEVELOPMENT"
    OBSERVED_VALIDATION = "OBSERVED_VALIDATION"
    BURNED_HOLDOUT = "BURNED_HOLDOUT"


class ResearchMutation(BaseModel):
    """One auditable change to a strategy funnel. Research authority only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mutation_id: str
    mutation_type: MutationType
    stage_id: str
    rationale: str
    old_rule_hash: str | None = None
    new_rule_hash: str | None = None
    parameters_before: Mapping[str, object] = Field(default_factory=dict)
    parameters_after: Mapping[str, object] = Field(default_factory=dict)


class FunnelVariant(BaseModel):
    """Immutable parent/child lineage for an optimization candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: str
    strategy_version: str
    strategy_sha256: str
    parent_strategy_sha256: str | None = None
    mutations: tuple[ResearchMutation, ...] = ()
    development_dataset_sha256: str
    frozen: bool = False

    @model_validator(mode="after")
    def mutation_requires_parent(self) -> "FunnelVariant":
        if self.mutations and self.parent_strategy_sha256 is None:
            raise ValueError("mutated funnel variants require parent_strategy_sha256")
        return self


class StageContribution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage_id: str
    input_count: int = Field(ge=0)
    pass_count: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    win_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    expectancy_r: float | None = None
    profit_factor: float | None = Field(default=None, ge=0.0)
    net_r: float | None = None
    delta_win_rate_pp: float | None = None
    delta_expectancy_r: float | None = None
    population_retained: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def counts_are_consistent(self) -> "StageContribution":
        if self.pass_count > self.input_count:
            raise ValueError("pass_count cannot exceed input_count")
        if self.wins + self.losses > self.pass_count:
            raise ValueError("outcomes cannot exceed passed population")
        return self
