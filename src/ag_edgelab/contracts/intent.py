from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Side(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class Target(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    price: float
    allocation: float = Field(gt=0, le=1)
    move_stop_to_entry: bool = False


class OrderIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    instrument: str
    created_at: datetime
    side: Side
    order_type: OrderType
    entry_price: float | None = None
    stop_price: float
    targets: tuple[Target, ...]
    expire_after_bars: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def valid_geometry(self) -> "OrderIntent":
        if not self.targets:
            raise ValueError("at least one target is required")
        alloc = sum(t.allocation for t in self.targets)
        if abs(alloc - 1.0) > 1e-9:
            raise ValueError("target allocation must sum to 1.0")
        if self.entry_price is not None:
            if self.side == Side.LONG and self.stop_price >= self.entry_price:
                raise ValueError("long stop must be below entry")
            if self.side == Side.SHORT and self.stop_price <= self.entry_price:
                raise ValueError("short stop must be above entry")
        return self
