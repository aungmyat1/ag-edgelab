from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ag_edgelab.data.fingerprint import sha256_json


class DatasetRole(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    OOS = "OOS"
    SEALED_OOS = "SEALED_OOS"
    FORWARD = "FORWARD"


class DatasetArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    timeframe: str
    path: str
    sha256: str
    rows: int | None = Field(default=None, ge=0)


class DatasetRange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def ordered(self) -> "DatasetRange":
        if self.end < self.start:
            raise ValueError("dataset range end precedes start")
        return self


class DatasetManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: str
    instrument: str
    broker_symbol: str | None = None
    asset_class: str
    provider: str
    broker: str | None = None
    source_timezone: str
    normalized_timezone: str = "UTC"
    timeframes: tuple[str, ...]
    date_range: DatasetRange
    role: DatasetRole
    artifacts: tuple[DatasetArtifact, ...]
    sealed: bool = False
    parent_dataset_id: str | None = None
    lineage: Mapping[str, str] = Field(default_factory=dict)
    metadata: Mapping[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistent_artifacts(self) -> "DatasetManifest":
        if len(set(self.timeframes)) != len(self.timeframes):
            raise ValueError("duplicate timeframe")
        artifact_tfs = tuple(item.timeframe for item in self.artifacts)
        if len(set(artifact_tfs)) != len(artifact_tfs):
            raise ValueError("duplicate dataset artifact timeframe")
        if set(artifact_tfs) != set(self.timeframes):
            raise ValueError("artifacts must cover exactly the declared timeframes")
        for item in self.artifacts:
            if len(item.sha256) != 64 or any(ch not in "0123456789abcdef" for ch in item.sha256.lower()):
                raise ValueError(f"invalid sha256 for {item.timeframe}")
        if self.role == DatasetRole.SEALED_OOS and not self.sealed:
            raise ValueError("SEALED_OOS dataset must be sealed")
        return self

    @property
    def manifest_sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))
