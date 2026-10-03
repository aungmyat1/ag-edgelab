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

    @property
    def body_high(self) -> float:
        return max(self.open, self.close)

    @property
    def body_low(self) -> float:
        return min(self.open, self.close)


@dataclass(frozen=True)
class Decision:
    strategy_id: str
    strategy_version: str
    symbol: str
    cycle: str
    status: str
    reason_code: str
    setup: Optional[str] = None
    direction: Optional[str] = None
    entry_order_type: Optional[str] = None
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    risk_distance: Optional[float] = None
    target_4r: Optional[float] = None
    target_5r: Optional[float] = None
    box_high: Optional[float] = None
    box_low: Optional[float] = None
    box_mid: Optional[float] = None
    signal_timestamp: Optional[datetime] = None
    management: Optional[str] = None
