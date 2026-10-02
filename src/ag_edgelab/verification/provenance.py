from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Generic, Mapping, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.optimization.contracts import DatasetExposure
from ag_edgelab.verification.evidence import DatasetRecord
from ag_edgelab.verification.time import UTCDateTime

HEX64 = r"^[0-9a-f]{64}$"
T = TypeVar("T")

class UnknownProvenanceError(LookupError):
    pass


@dataclass(frozen=True, init=False)
class ContentAddressedStore(Generic[T]):
    _records: Mapping[str, T]

    def __init__(self, records: Mapping[str, T]):
        checked = dict(records)
        for key, value in checked.items():
            if not isinstance(key, str) or re.fullmatch(HEX64, key) is None:
                raise ValueError("content-address key must be canonical SHA-256")
            try:
                digest = value.sha256
            except Exception as exc:
                raise ValueError("record must expose a deterministic sha256") from exc
            if not isinstance(digest, str) or re.fullmatch(HEX64, digest) is None or digest != key:
                raise ValueError("content-address key does not match record hash")
        object.__setattr__(self, "_records", MappingProxyType(checked))

    @classmethod
    def build(cls, records: Mapping[str, T]) -> "ContentAddressedStore[T]":
        return cls(records)

    def resolve(self, sha256: str) -> T:
        if not isinstance(sha256, str) or re.fullmatch(HEX64, sha256) is None:
            raise UnknownProvenanceError("invalid content-address key")
        try:
            record = self._records[sha256]
        except KeyError as exc:
            raise UnknownProvenanceError(f"unknown evidence hash: {sha256}") from exc
        try:
            digest = record.sha256
        except Exception as exc:
            raise UnknownProvenanceError("stored record hash cannot be recomputed") from exc
        if digest != sha256:
            raise UnknownProvenanceError("stored record no longer matches its content address")
        return record


class FrozenVariantRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    strategy_id: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    strategy_sha256: str = Field(pattern=HEX64)
    friction_model_sha256: str = Field(pattern=HEX64)
    funnel_sha256: str = Field(pattern=HEX64)
    parameters_sha256: str = Field(pattern=HEX64)
    claimed_regimes: tuple[str, ...]
    regime_classifier_sha256: str = Field(pattern=HEX64)
    frozen_at: UTCDateTime

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
    observed_at: UTCDateTime
    previous_event_sha256: str | None = Field(default=None, pattern=HEX64)

    @model_validator(mode="after")
    def valid(self) -> "ExposureEvent":
        if self.previous == DatasetExposure.BURNED_HOLDOUT and self.current != DatasetExposure.BURNED_HOLDOUT:
            raise ValueError("BURNED_HOLDOUT is absorbing")
        allowed = {
            DatasetExposure.UNSEEN: {DatasetExposure.UNSEEN, DatasetExposure.DEVELOPMENT, DatasetExposure.OBSERVED_VALIDATION, DatasetExposure.BURNED_HOLDOUT},
            DatasetExposure.DEVELOPMENT: {DatasetExposure.DEVELOPMENT, DatasetExposure.OBSERVED_VALIDATION, DatasetExposure.BURNED_HOLDOUT},
            DatasetExposure.OBSERVED_VALIDATION: {DatasetExposure.OBSERVED_VALIDATION, DatasetExposure.BURNED_HOLDOUT},
            DatasetExposure.BURNED_HOLDOUT: {DatasetExposure.BURNED_HOLDOUT},
        }
        if self.current not in allowed[self.previous]:
            raise ValueError("invalid exposure-state transition")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


@dataclass(frozen=True)
class ExposureLedger:
    events: tuple[ExposureEvent, ...] = field(default_factory=tuple)

    def __post_init__(self):
        last = {}
        for e in self.events:
            p = last.get(e.dataset_sha256)
            if p is None and e.previous_event_sha256 is not None:
                raise ValueError("first exposure event cannot reference previous event")
            if p is not None and (e.previous_event_sha256 != p.sha256 or e.previous != p.current):
                raise ValueError("broken exposure ledger chain")
            if p is not None and e.observed_at <= p.observed_at:
                raise ValueError("exposure timestamps must increase strictly")
            last[e.dataset_sha256] = e

    def _events(self, dataset_sha256):
        found = tuple(e for e in self.events if e.dataset_sha256 == dataset_sha256)
        if not found:
            raise UnknownProvenanceError(f"dataset absent from exposure ledger: {dataset_sha256}")
        return found

    def state(self, dataset_sha256):
        return self._events(dataset_sha256)[-1].current

    def open_event(self, dataset_sha256):
        for e in self._events(dataset_sha256):
            if e.previous == DatasetExposure.UNSEEN and e.current == DatasetExposure.BURNED_HOLDOUT:
                return e
        raise UnknownProvenanceError("no authoritative UNSEEN->BURNED holdout-open event")

    def was_unseen_when_opened(self, dataset_sha256):
        try:
            self.open_event(dataset_sha256)
            return True
        except UnknownProvenanceError:
            return False

    def proof_sha256(self, dataset_sha256):
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
    def owner_approved_pair(cls, records: tuple[EngineRecord, EngineRecord]):
        if len(records) != 2 or any(not r.owner_approved for r in records):
            raise ValueError("exactly two owner-approved engines required")
        a, b = records
        if a.engine_id == b.engine_id or a.code_sha256 == b.code_sha256 or a.independence_group == b.independence_group:
            raise ValueError("approved parity engines must be independent")
        return cls(MappingProxyType({r.engine_id: r for r in records}))

    def resolve(self, engine_id):
        try:
            return self._by_id[engine_id]
        except KeyError as exc:
            raise UnknownProvenanceError(f"engine not owner-approved: {engine_id}") from exc


@dataclass(frozen=True)
class VerificationResolvers:
    variants: ContentAddressedStore[FrozenVariantRecord]
    evidence: ContentAddressedStore[object]
    datasets: ContentAddressedStore[DatasetRecord]
    engines: EngineRegistry
    exposure: ExposureLedger
