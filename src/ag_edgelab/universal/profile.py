"""MarketProfile — the per-asset-class declaration consumed by the common core.

The structural engine (direction/location/confirmation/target) is identical
for every market type. A MarketProfile only declares *explicitly*
market-specific modules: session behavior, friction authority, symbol
geometry. Core logic is never duplicated per asset class.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MarketType(StrEnum):
    FX = "FX"
    CRYPTO = "CRYPTO"
    OTHER = "OTHER"


class SessionBehavior(StrEnum):
    REQUIRED = "REQUIRED"
    OPTIONAL_DIAGNOSTIC = "OPTIONAL_DIAGNOSTIC"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class MarketProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    market_type: MarketType
    symbols: tuple[str, ...] = Field(min_length=1)
    base_timeframe: str
    higher_timeframes: tuple[str, ...] = Field(min_length=1)
    session_behavior: SessionBehavior
    friction_authority: str = Field(min_length=1)

    @model_validator(mode="after")
    def session_rules(self) -> "MarketProfile":
        # Crypto core strategies operate continuously: sessions may be
        # diagnostic metadata but are NEVER a validity requirement unless a
        # future crypto strategy preregisters such a rule explicitly.
        if self.market_type == MarketType.CRYPTO and self.session_behavior == SessionBehavior.REQUIRED:
            raise ValueError(
                "CRYPTO profiles must not REQUIRE sessions; preregister a dedicated "
                "strategy rule instead (mission section 5)"
            )
        return self


# ---------------------------------------------------------------------------
# Repository reference profiles (DEVELOPMENT / research only)
# ---------------------------------------------------------------------------

FX_REFERENCE_PROFILE = MarketProfile(
    market_type=MarketType.FX,
    symbols=("EURUSD",),
    base_timeframe="M5",
    higher_timeframes=("M15", "H1", "H4", "D1"),
    session_behavior=SessionBehavior.OPTIONAL_DIAGNOSTIC,
    friction_authority="FX_SPREAD_COMMISSION_DECLARED_SCENARIO",
)

# The Asian-session strategy makes session structure part of the strategy
# itself, therefore REQUIRED (mission section 4).
FX_ASIAN_SESSION_PROFILE = MarketProfile(
    market_type=MarketType.FX,
    symbols=("EURUSD",),
    base_timeframe="M5",
    higher_timeframes=("M15", "H1", "H4", "D1"),
    session_behavior=SessionBehavior.REQUIRED,
    friction_authority="FX_SPREAD_COMMISSION_DECLARED_SCENARIO",
)

CRYPTO_REFERENCE_PROFILE = MarketProfile(
    market_type=MarketType.CRYPTO,
    symbols=("BTCUSDT",),
    base_timeframe="M5",
    higher_timeframes=("M15", "H1", "H4", "D1"),
    session_behavior=SessionBehavior.NOT_APPLICABLE,
    friction_authority="BYBIT_LINEAR_PERP_FUNDING_PLUS_DECLARED_EXECUTION_SCENARIO",
)
