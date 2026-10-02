from __future__ import annotations

import math
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
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    mutation_id: str = Field(min_length=1)
    mutation_type: MutationType
    stage_id: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    old_rule_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    new_rule_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    parameters_before: Mapping[str, object] = Field(default_factory=dict)
    parameters_after: Mapping[str, object] = Field(default_factory=dict)


class FunnelVariant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    strategy_id: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    strategy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_strategy_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    mutations: tuple[ResearchMutation, ...] = ()
    development_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen: bool = False

    @model_validator(mode="after")
    def lineage_is_consistent(self) -> "FunnelVariant":
        if self.mutations and self.parent_strategy_sha256 is None:
            raise ValueError("mutated funnel variants require parent_strategy_sha256")
        if self.parent_strategy_sha256 == self.strategy_sha256:
            raise ValueError("variant cannot name itself as parent")
        return self


class StageContribution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    stage_id: str = Field(min_length=1)
    input_count: int = Field(ge=0)
    pass_count: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    win_rate: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    expectancy_r: float | None = Field(default=None, allow_inf_nan=False)
    profit_factor: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    net_r: float | None = Field(default=None, allow_inf_nan=False)
    delta_win_rate_pp: float | None = Field(default=None, allow_inf_nan=False)
    delta_expectancy_r: float | None = Field(default=None, allow_inf_nan=False)
    population_retained: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def counts_are_consistent(self) -> "StageContribution":
        if self.pass_count > self.input_count:
            raise ValueError("pass_count cannot exceed input_count")
        if self.wins + self.losses > self.pass_count:
            raise ValueError("outcomes cannot exceed passed population")
        expected_pass = 0.0 if self.input_count == 0 else self.pass_count / self.input_count
        if not math.isclose(self.pass_rate, expected_pass, abs_tol=1e-12):
            raise ValueError("pass_rate does not match counts")
        expected_retained = expected_pass
        if not math.isclose(self.population_retained, expected_retained, abs_tol=1e-12):
            raise ValueError("population_retained does not match counts")
        resolved = self.wins + self.losses
        if self.win_rate is not None:
            expected_win = 0.0 if resolved == 0 else self.wins / resolved
            if not math.isclose(self.win_rate, expected_win, abs_tol=1e-12):
                raise ValueError("win_rate does not match resolved outcomes")
        return self
