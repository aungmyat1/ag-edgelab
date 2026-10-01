from __future__ import annotations

import math
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.verification.time import UTCDateTime

HEX64 = r"^[0-9a-f]{64}$"


class DatasetRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    dataset_sha256: str = Field(pattern=HEX64)
    start: UTCDateTime
    end: UTCDateTime

    @model_validator(mode="after")
    def valid_window(self) -> "DatasetRecord":
        if not self.start < self.end:
            raise ValueError("dataset window must be increasing")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


class TradeOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    trade_id: str = Field(min_length=1)
    executed_at: UTCDateTime
    r: float = Field(allow_inf_nan=False)
    regime: str = Field(min_length=1)


class TradeListRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    dataset_sha256: str = Field(pattern=HEX64)
    strategy_sha256: str = Field(pattern=HEX64)
    engine_id: str = Field(min_length=1)
    engine_code_sha256: str = Field(pattern=HEX64)
    trades: tuple[TradeOutcome, ...]

    @model_validator(mode="after")
    def unique_and_ordered(self) -> "TradeListRecord":
        ids = [t.trade_id for t in self.trades]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate trade ids")
        times = [t.executed_at for t in self.trades]
        if times != sorted(times):
            raise ValueError("trade list must be chronological")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))

    @property
    def rs(self) -> tuple[float, ...]:
        return tuple(t.r for t in self.trades)


class FrictionEvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    points: tuple[tuple[float, str], ...]

    @model_validator(mode="after")
    def valid(self) -> "FrictionEvidenceRecord":
        ms = [m for m, _ in self.points]
        if any(not math.isfinite(m) or m < 1.0 for m in ms) or len(ms) != len(set(ms)):
            raise ValueError("invalid friction grid")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


class WalkForwardFoldRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    fold_id: str = Field(min_length=1)
    train_start: UTCDateTime
    train_end: UTCDateTime
    test_start: UTCDateTime
    test_end: UTCDateTime
    trade_list_sha256: str = Field(pattern=HEX64)

    @model_validator(mode="after")
    def chronological(self) -> "WalkForwardFoldRecord":
        if not self.train_start < self.train_end <= self.test_start < self.test_end:
            raise ValueError("invalid chronological fold")
        return self


class WalkForwardEvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    folds: tuple[WalkForwardFoldRecord, ...]

    @model_validator(mode="after")
    def nonoverlap(self) -> "WalkForwardEvidenceRecord":
        for a, b in zip(self.folds, self.folds[1:]):
            if b.test_start < a.test_end:
                raise ValueError("walk-forward test windows overlap")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


class StabilityEvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    center: float = Field(allow_inf_nan=False)
    neighborhoods: tuple[tuple[float, str], ...]

    @model_validator(mode="after")
    def valid(self) -> "StabilityEvidenceRecord":
        values = [v for v, _ in self.neighborhoods]
        if any(not math.isfinite(v) for v in values) or len(values) != len(set(values)):
            raise ValueError("invalid stability neighborhood")
        if self.center not in values:
            raise ValueError("stability center must be present")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


class ValidationBundleRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    variant_sha256: str = Field(pattern=HEX64)
    oos_trade_list_sha256: str = Field(pattern=HEX64)
    friction_sha256: str = Field(pattern=HEX64)
    walk_forward_sha256: str = Field(pattern=HEX64)
    stability_sha256: str = Field(pattern=HEX64)
    parity_reference_trade_list_sha256: str = Field(pattern=HEX64)
    parity_independent_trade_list_sha256: str = Field(pattern=HEX64)

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))
