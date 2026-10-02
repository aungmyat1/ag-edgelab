from __future__ import annotations

from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field

from ag_edgelab.contracts.funnel import FunnelStage


class StrategyManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: str
    version: str
    source_sha256: str
    required_timeframes: tuple[str, ...]
    instruments: tuple[str, ...] = ()
    parameters: Mapping[str, object] = Field(default_factory=dict)
    funnel_stages: tuple[FunnelStage, ...] = (
        FunnelStage.CONTEXT,
        FunnelStage.LOCATION,
        FunnelStage.TRIGGER,
        FunnelStage.GEOMETRY,
        FunnelStage.EXECUTION,
    )
