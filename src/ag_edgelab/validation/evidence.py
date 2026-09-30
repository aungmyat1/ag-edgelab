from __future__ import annotations

from enum import StrEnum
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field


class EdgeVerdict(StrEnum):
    EDGE_SUPPORTED = "EDGE_SUPPORTED"
    NO_EDGE = "NO_EDGE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class EvidenceClass(StrEnum):
    ECONOMIC = "ECONOMIC"
    DETERMINISM = "DETERMINISM"
    DATA_LINEAGE = "DATA_LINEAGE"
    FORWARD = "FORWARD"


class EvidenceRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_repository: str
    source_path: str
    source_git_blob_sha: str | None = None
    evidence_class: EvidenceClass
    description: str


class EconomicSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trades: int = Field(ge=0)
    gross_r: float | None = None
    friction_r: float | None = None
    net_r: float | None = None
    expectancy_r: float | None = None
    profit_factor: float | None = None
    win_rate: float | None = Field(default=None, ge=0, le=1)
    max_drawdown_r: float | None = Field(default=None, ge=0)


class StrategyVerification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    verification_id: str
    asset_class: str
    strategy_id: str
    strategy_version: str
    instrument: str
    verdict: EdgeVerdict
    deterministic: bool | None = None
    economic: EconomicSummary | None = None
    evidence: tuple[EvidenceRef, ...] = ()
    blockers: tuple[str, ...] = ()
    notes: Mapping[str, str] = Field(default_factory=dict)

    @property
    def economically_verified(self) -> bool:
        return self.verdict in {EdgeVerdict.EDGE_SUPPORTED, EdgeVerdict.NO_EDGE}

    @classmethod
    def no_edge(cls, **kwargs):
        economic = kwargs.get("economic")
        if economic is None or economic.trades <= 0 or economic.expectancy_r is None:
            raise ValueError("NO_EDGE requires non-empty economic evidence")
        return cls(verdict=EdgeVerdict.NO_EDGE, **kwargs)

    @classmethod
    def edge_supported(cls, **kwargs):
        economic = kwargs.get("economic")
        if economic is None or economic.trades <= 0 or economic.expectancy_r is None:
            raise ValueError("EDGE_SUPPORTED requires non-empty economic evidence")
        if economic.expectancy_r <= 0:
            raise ValueError("EDGE_SUPPORTED requires positive expectancy")
        return cls(verdict=EdgeVerdict.EDGE_SUPPORTED, **kwargs)
