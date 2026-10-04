from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float

    def validate(self) -> None:
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close) or self.high < self.low:
            raise ValueError("invalid OHLC candle")


@dataclass(frozen=True)
class Zone:
    kind: str  # DEMAND | SUPPLY
    low: float
    high: float
    origin_time: datetime
    created_time: datetime
    fvg_low: float
    fvg_high: float
    bos_level: float

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2.0

    @property
    def height(self) -> float:
        return self.high - self.low


@dataclass(frozen=True)
class Decision:
    strategy_id: str
    strategy_version: str
    symbol: str
    cycle: str
    status: str
    reason_code: str
    bias: Optional[str] = None
    false_shift_class: Optional[str] = None
    h4_zone: Optional[Zone] = None
    h1_shift_zone: Optional[Zone] = None
    m15_entry_zone: Optional[Zone] = None
    direction: Optional[str] = None
    entry_order_type: Optional[str] = None
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    risk_distance: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    signal_timestamp: Optional[datetime] = None
    expiry_timestamp: Optional[datetime] = None
