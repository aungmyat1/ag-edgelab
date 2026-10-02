from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ag_edgelab.contracts.funnel import FunnelStage


class RejectionCode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    stage: FunnelStage
    description: str
    terminal: bool = True
