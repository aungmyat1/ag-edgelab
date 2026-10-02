from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ag_edgelab.contracts.intent import Side


class ExecutionStatus(StrEnum):
    NO_FILL = "NO_FILL"
    OPEN_AT_END = "OPEN_AT_END"
    CLOSED = "CLOSED"


class ExitReason(StrEnum):
    STOP = "STOP"
    TARGETS_COMPLETE = "TARGETS_COMPLETE"
    DATA_END = "DATA_END"


class ExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    instrument: str
    side: Side
    status: ExecutionStatus
    entry_time: datetime | None = None
    entry_price: float | None = None
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: ExitReason | None = None
    gross_r: float | None = None
    remaining_allocation: float = 0.0
    engine_name: str
    engine_version: str
