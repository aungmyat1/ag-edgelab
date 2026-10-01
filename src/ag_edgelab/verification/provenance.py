from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Generic, Mapping, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.optimization.contracts import DatasetExposure

HEX64 = r"^[0-9a-f]{64}$"
T = TypeVar("T")


class UnknownProvenanceError(LookupError):
    pass


@dataclass(frozen=True)
class ContentAddressedStore(Generic[T]):
    """Immutable resolver. Keys are canonical SHA-256 hashes of stored payloads."""
    _records: Mapping[str, T]

    @classmethod
    def build(cls, records: Mapping[str, T]) -> "ContentAddressedStore[T]":
        return cls(MappingProxyType(dict(records)))

    def resolve(self, sha256: str) -> T:
        try:
            return self._records[sha256]
        except KeyError as exc:
            raise UnknownProvenanceError(f"unknown evidence hash: {sha256}") from exc


class FrozenVariantRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    strategy_id: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    strategy_sha256: str = Field(pattern=HEX64)
    funnel_sha256: str = Field(pattern=HEX64)
    parameters_sha256: str = Field(pattern=HEX64)
    claimed_regimes: tuple[str, ...]
    regime_classifier_sha256: str = Field(pattern=HEX64)
    frozen_at: datetime

    @model_validator(mode="after")
    def regimes_are_canonical(self) -> "FrozenVariantRecord":
        if not self.claimed_regimes or len(set(self.claimed_regimes)) != len(self.claimed_regimes):
            raise ValueError("claimed regimes must be non-empty and unique")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


class ExposureEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    dataset_sha256: str = Field(pattern=HEX64)
    previous: DatasetExposure
    current: DatasetExposure
    observed_at: datetime
    previous_event_sha256: str | None = Field(default=None, pattern=HEX64)

    @model_validator(mode="after")
    def no_downgrade(self) -> "ExposureEvent":
        if self.previous == DatasetExposure.BURNED_HOLDOUT and self.current != DatasetExposure.BURNED_HOLDOUT:
            raise ValueError("BURNED_HOLDOUT is absorbing")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


@dataclass(frozen=True)
class ExposureLedger:
    """Read-only hash-chained ledger view used by verification."""
    events: tuple[ExposureEvent, ...] = field(default_factory=tuple)

    def __post_init__(self):
        last_by_dataset: dict[str, ExposureEvent] = {}
        for event in self.events:
            prior = last_by_dataset.get(event.dataset_sha256)
            if prior is None:
                if event.previous_event_sha256 is not None:
                    raise ValueError("first exposure event cannot reference a previous event")
            else:
                if event.previous_event_sha256 != prior.sha256 or event.previous != prior.current:
                    raise ValueError("broken exposure ledger chain")
            last_by_dataset[event.dataset_sha256] = event

    def state(self, dataset_sha256: str) -> DatasetExposure:
        matches = [e for e in self.events if e.dataset_sha256 == dataset_sha256]
        if not matches:
            raise UnknownProvenanceError(f"dataset absent from exposure ledger: {dataset_sha256}")
        return matches[-1].current

    def proof_sha256(self, dataset_sha256: str) -> str:
        matches = [e for e in self.events if e.dataset_sha256 == dataset_sha256]
        if not matches:
            raise UnknownProvenanceError(f"dataset absent from exposure ledger: {dataset_sha256}")
        return matches[-1].sha256


class EngineRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    engine_id: str = Field(min_length=1)
    code_sha256: str = Field(pattern=HEX64)
    independence_group: str = Field(min_length=1)

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


@dataclass(frozen=True)
class VerificationResolvers:
    variants: ContentAddressedStore[FrozenVariantRecord]
    evidence: ContentAddressedStore[object]
    engines: ContentAddressedStore[EngineRecord]
    exposure: ExposureLedger
