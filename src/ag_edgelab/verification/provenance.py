from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
    _records: Mapping[str, T]

    @classmethod
    def build(cls, records: Mapping[str, T]) -> "ContentAddressedStore[T]":
        checked = dict(records)
        for key, value in checked.items():
            actual = getattr(value, "sha256", None)
            if actual is None or actual != key:
                raise ValueError("content-address key does not match record hash")
        return cls(MappingProxyType(checked))

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
    def valid(self) -> "FrozenVariantRecord":
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
    def valid(self) -> "ExposureEvent":
        if self.previous == DatasetExposure.BURNED_HOLDOUT and self.current != DatasetExposure.BURNED_HOLDOUT:
            raise ValueError("BURNED_HOLDOUT is absorbing")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


@dataclass(frozen=True)
class ExposureLedger:
    events: tuple[ExposureEvent, ...] = field(default_factory=tuple)

    def __post_init__(self):
        last: dict[str, ExposureEvent] = {}
        for event in self.events:
            prior = last.get(event.dataset_sha256)
            if prior is None:
                if event.previous_event_sha256 is not None:
                    raise ValueError("first exposure event cannot reference previous event")
            elif event.previous_event_sha256 != prior.sha256 or event.previous != prior.current:
                raise ValueError("broken exposure ledger chain")
            last[event.dataset_sha256] = event

    def _events(self, dataset_sha256: str) -> tuple[ExposureEvent, ...]:
        found = tuple(e for e in self.events if e.dataset_sha256 == dataset_sha256)
        if not found:
            raise UnknownProvenanceError(f"dataset absent from exposure ledger: {dataset_sha256}")
        return found

    def state(self, dataset_sha256: str) -> DatasetExposure:
        return self._events(dataset_sha256)[-1].current

    def was_unseen_when_opened(self, dataset_sha256: str) -> bool:
        return any(e.previous == DatasetExposure.UNSEEN and e.current == DatasetExposure.BURNED_HOLDOUT for e in self._events(dataset_sha256))

    def proof_sha256(self, dataset_sha256: str) -> str:
        return self._events(dataset_sha256)[-1].sha256


class EngineRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    engine_id: str = Field(min_length=1)
    code_sha256: str = Field(pattern=HEX64)
    independence_group: str = Field(min_length=1)
    owner_approved: bool = True

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


@dataclass(frozen=True)
class EngineRegistry:
    _by_id: Mapping[str, EngineRecord]

    @classmethod
    def owner_approved_pair(cls, records: tuple[EngineRecord, EngineRecord]) -> "EngineRegistry":
        if len(records) != 2 or any(not r.owner_approved for r in records):
            raise ValueError("exactly two owner-approved engines required")
        if records[0].engine_id == records[1].engine_id or records[0].code_sha256 == records[1].code_sha256 or records[0].independence_group == records[1].independence_group:
            raise ValueError("approved parity engines must be independent")
        return cls(MappingProxyType({r.engine_id: r for r in records}))

    def resolve(self, engine_id: str) -> EngineRecord:
        try:
            return self._by_id[engine_id]
        except KeyError as exc:
            raise UnknownProvenanceError(f"engine not owner-approved: {engine_id}") from exc


@dataclass(frozen=True)
class VerificationResolvers:
    variants: ContentAddressedStore[FrozenVariantRecord]
    evidence: ContentAddressedStore[object]
    engines: EngineRegistry
    exposure: ExposureLedger
