"""Provenance receipt types for the small Funnel Optimizer FX fixture.

The optimizer may be exercised with deterministic synthetic opportunities when
materialization is blocked, but synthetic facts never inherit the identity or
role of a missing public dataset.  This module keeps that boundary explicit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Sequence

from ag_edgelab.data.fingerprint import sha256_file, sha256_json


class FixtureDataStatus(StrEnum):
    REUSED_AUTHORIZED = "REUSED_AUTHORIZED"
    ACQUIRED_VERIFIED = "ACQUIRED_VERIFIED"
    DATA_BLOCKED = "DATA_BLOCKED"


@dataclass(frozen=True)
class FixtureFile:
    symbol: str
    year: int
    path: str
    sha256: str
    byte_size: int
    source: str

    def __post_init__(self) -> None:
        if self.symbol not in {"EURUSD", "GBPUSD"}:
            raise ValueError("Funnel Optimizer V1 FX fixture is limited to EURUSD/GBPUSD")
        if self.year not in {2015, 2016, 2017}:
            raise ValueError("Funnel Optimizer V1 FX fixture is limited to 2015-2017")
        if len(self.sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.sha256):
            raise ValueError("fixture file requires a lowercase sha256")
        if self.byte_size < 0:
            raise ValueError("fixture byte size cannot be negative")

    def as_dict(self) -> dict[str, object]:
        return {
            "byte_size": self.byte_size,
            "path": self.path,
            "sha256": self.sha256,
            "source": self.source,
            "symbol": self.symbol,
            "year": self.year,
        }

    def identity_dict(self) -> dict[str, object]:
        """Portable artifact identity; local materialization path is not data."""
        return {
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "source": self.source,
            "symbol": self.symbol,
            "year": self.year,
        }


@dataclass(frozen=True)
class FixtureDataReceipt:
    status: FixtureDataStatus
    source: str
    acquisition_seconds: float
    files: tuple[FixtureFile, ...]
    dataset_sha256: str | None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.acquisition_seconds) or self.acquisition_seconds < 0:
            raise ValueError("acquisition_seconds must be finite and non-negative")
        if self.status is FixtureDataStatus.DATA_BLOCKED:
            if self.files or self.dataset_sha256 is not None:
                raise ValueError("DATA_BLOCKED cannot claim fixture files or a dataset hash")
            if not self.reason_code:
                raise ValueError("DATA_BLOCKED requires a reason code")
        else:
            if not self.files or self.dataset_sha256 is None:
                raise ValueError("materialized data requires files and a dataset hash")

    @classmethod
    def blocked(cls, *, source: str, acquisition_seconds: float, reason_code: str) -> "FixtureDataReceipt":
        return cls(FixtureDataStatus.DATA_BLOCKED, source, acquisition_seconds, (), None, reason_code)

    @classmethod
    def verified(cls, *, status: FixtureDataStatus, source: str, acquisition_seconds: float,
                 files: Sequence[FixtureFile]) -> "FixtureDataReceipt":
        if status is FixtureDataStatus.DATA_BLOCKED:
            raise ValueError("use blocked() for DATA_BLOCKED")
        ordered = tuple(sorted(files, key=lambda f: (f.symbol, f.year, f.path)))
        dataset_sha256 = sha256_json({
            "files": [file.identity_dict() for file in ordered],
            "schema_version": "FUNNEL_OPTIMIZER_FX_FIXTURE_V1",
        })
        return cls(status, source, acquisition_seconds, ordered, dataset_sha256)

    def as_dict(self) -> dict[str, object]:
        return {
            "acquisition_seconds": self.acquisition_seconds,
            "dataset_sha256": self.dataset_sha256,
            "files": [file.as_dict() for file in self.files],
            "reason_code": self.reason_code,
            "source": self.source,
            "status": self.status.value,
        }


def verify_fixture_file(path: str | Path, *, symbol: str, year: int, source: str) -> FixtureFile:
    """Hash a materialized raw artifact; no missing file is silently accepted."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"fixture artifact unavailable: {file_path}")
    return FixtureFile(symbol=symbol, year=year, path=file_path.as_posix(),
                       sha256=sha256_file(file_path), byte_size=file_path.stat().st_size,
                       source=source)
