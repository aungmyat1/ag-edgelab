from __future__ import annotations

from enum import StrEnum
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field


class ExperimentStatus(StrEnum):
    DRAFT = "DRAFT"
    PREREGISTERED = "PREREGISTERED"
    SEALED = "SEALED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


class ExperimentManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: str
    hypothesis_id: str
    strategy_id: str
    strategy_version: str
    strategy_sha256: str
    dataset_id: str
    dataset_sha256: str
    status: ExperimentStatus
    random_seed: int = 0
    parameters: Mapping[str, object] = Field(default_factory=dict)
