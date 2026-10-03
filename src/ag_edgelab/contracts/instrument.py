from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class InstrumentType(StrEnum):
    LINEAR_PERPETUAL = "LINEAR_PERPETUAL"
    INVERSE_PERPETUAL = "INVERSE_PERPETUAL"
    SPOT = "SPOT"
    CFD = "CFD"
    FUTURE_DATED = "FUTURE_DATED"


class InstrumentAuthority(BaseModel):
    """Exchange/broker instrument identity bound to a dataset.

    Different venues and instrument types for the same underlying are different
    economic instruments and are never combined into one dataset.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    venue: str
    symbol: str
    instrument_type: InstrumentType
    quote_currency: str
    base_currency: str
    price_precision: int = Field(ge=0)
    tick_size: float = Field(gt=0)
    source: str
    source_timeframe: str

    @property
    def instrument_domain(self) -> str:
        if self.instrument_type == InstrumentType.CFD:
            return f"{self.symbol}_CFD"
        return f"{self.symbol}_{self.instrument_type.value}"


BYBIT_BTCUSDT_LINEAR_PERP = InstrumentAuthority(
    venue="BYBIT",
    symbol="BTCUSDT",
    instrument_type=InstrumentType.LINEAR_PERPETUAL,
    quote_currency="USDT",
    base_currency="BTC",
    price_precision=1,
    tick_size=0.1,
    source="BYBIT_PUBLIC_KLINE_ARCHIVE",
    source_timeframe="M5",
)
