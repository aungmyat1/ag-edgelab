from __future__ import annotations

from enum import StrEnum
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field


class DatasetRole(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    OOS = "OOS"
    SEALED_OOS = "SEALED_OOS"
    FORWARD = "FORWARD"


class DatasetManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: str
    instrument: str
    asset_class: str
    source: str
    timezone: str = "UTC"
    timeframes: tuple[str, ...]
    role: DatasetRole
    sha256: Mapping[str, str]
    sealed: bool = False
    metadata: Mapping[str, str] = Field(default_factory=dict)
