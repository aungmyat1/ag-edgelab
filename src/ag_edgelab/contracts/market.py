from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MarketBar(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None

    @model_validator(mode="after")
    def valid_ohlc(self) -> "MarketBar":
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high is below OHLC values")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low is above OHLC values")
        return self


class EvaluationContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    instrument: str
    as_of: datetime
    attributes: Mapping[str, Any] = Field(default_factory=dict)
    bars: Mapping[str, tuple[MarketBar, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_future_bars(self) -> "EvaluationContext":
        for timeframe, rows in self.bars.items():
            for bar in rows:
                if bar.timestamp > self.as_of:
                    raise ValueError(f"future bar in {timeframe}: {bar.timestamp} > {self.as_of}")
        return self
