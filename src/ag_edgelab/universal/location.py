"""Funnel 1 (part B) — LocationEvidence contract + deterministic detectors.

Direction alone is not a thesis; a Trigger candidate needs direction AND a
meaningful location per a preregistered hypothesis. Every detector below is
closed-bar, deterministic and scale-invariant (tolerances derive from the
instrument's own trailing ranges, never absolute price units).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.strategies.crypto_mtf_smc import confirmed_swing_points, detect_fvg
from ag_edgelab.universal.direction import Direction

# Preregistered geometry constants (frozen; not searched).
TOLERANCE_RANGE_BARS = 20          # trailing window defining the tolerance unit
LEVEL_TOLERANCE_FRACTION = 0.25    # zone half-width = 0.25 * mean trailing range
EQUAL_LEVEL_FRACTION = 0.10        # "equal highs/lows" max distance
DISPLACEMENT_BODY_MULT = 2.0       # body >= 2x median body of trailing window


class LocationFamily(StrEnum):
    STRUCTURAL_LEVEL = "STRUCTURAL_LEVEL"
    SUPPLY_DEMAND = "SUPPLY_DEMAND"
    LIQUIDITY_LEVEL = "LIQUIDITY_LEVEL"
    PREMIUM_DISCOUNT = "PREMIUM_DISCOUNT"
    ORDER_BLOCK = "ORDER_BLOCK"
    FVG = "FVG"
    SESSION_LEVEL = "SESSION_LEVEL"


class LocationSide(StrEnum):
    SUPPORT = "SUPPORT"        # meaningful for BULL theses
    RESISTANCE = "RESISTANCE"  # meaningful for BEAR theses


class LocationEvidence(BaseModel):
    """One detected location zone. Detection != entry: it only feeds a thesis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    family: LocationFamily
    timeframe: str
    side: LocationSide
    zone_low: float
    zone_high: float
    reference_index: int = Field(ge=0)  # bar index the zone derives from
    detector_id: str

    @model_validator(mode="after")
    def ordered_zone(self) -> "LocationEvidence":
        if self.zone_low > self.zone_high:
            raise ValueError("zone_low must be <= zone_high")
        return self

    def contains(self, price: float) -> bool:
        return self.zone_low <= price <= self.zone_high

    def supports(self, direction: Direction) -> bool:
        if direction == Direction.BULL:
            return self.side == LocationSide.SUPPORT
        if direction == Direction.BEAR:
            return self.side == LocationSide.RESISTANCE
        return False


def _mean_range(bars: tuple[MarketBar, ...], end_index: int, window: int = TOLERANCE_RANGE_BARS) -> float:
    rows = bars[max(0, end_index - window + 1): end_index + 1]
    if not rows:
        return 0.0
    return sum(b.high - b.low for b in rows) / len(rows)


def structural_levels(
    bars: tuple[MarketBar, ...], timeframe: str, swing_order: int = 2, asof_index: int | None = None,
) -> tuple[LocationEvidence, ...]:
    """Zones around the last confirmed swing high (resistance) / low (support)."""
    idx = len(bars) - 1 if asof_index is None else asof_index
    swings = confirmed_swing_points(bars[: idx + 1], swing_order)
    out: list[LocationEvidence] = []
    tol = LEVEL_TOLERANCE_FRACTION * _mean_range(bars, idx)
    for kind, side in (("HIGH", LocationSide.RESISTANCE), ("LOW", LocationSide.SUPPORT)):
        latest = None
        for swing in swings:
            if swing.kind == kind and swing.confirmed_index <= idx:
                latest = swing
        if latest is not None:
            out.append(LocationEvidence(
                family=LocationFamily.STRUCTURAL_LEVEL, timeframe=timeframe, side=side,
                zone_low=latest.price - tol, zone_high=latest.price + tol,
                reference_index=latest.index, detector_id="LOC_STRUCT_LEVEL_V1"))
    return tuple(out)


def supply_demand_zones(
    bars: tuple[MarketBar, ...], timeframe: str, asof_index: int | None = None, max_zones: int = 3,
) -> tuple[LocationEvidence, ...]:
    """Demand = last bearish candle before a bullish displacement; supply mirrored.

    Displacement contract: candle body >= DISPLACEMENT_BODY_MULT * median body
    of the preceding TOLERANCE_RANGE_BARS candles.
    """
    idx = len(bars) - 1 if asof_index is None else asof_index
    out: list[LocationEvidence] = []
    for i in range(TOLERANCE_RANGE_BARS, idx + 1):
        ref = bars[i - TOLERANCE_RANGE_BARS: i]
        bodies = sorted(abs(b.close - b.open) for b in ref)
        med = bodies[len(bodies) // 2]
        if med <= 0:
            continue
        bar = bars[i]
        body = abs(bar.close - bar.open)
        if body < DISPLACEMENT_BODY_MULT * med:
            continue
        origin = bars[i - 1]
        if bar.close > bar.open and origin.close < origin.open:  # bullish displacement from bearish origin
            out.append(LocationEvidence(
                family=LocationFamily.SUPPLY_DEMAND, timeframe=timeframe, side=LocationSide.SUPPORT,
                zone_low=origin.low, zone_high=origin.high, reference_index=i - 1,
                detector_id="LOC_SUPPLY_DEMAND_V1"))
        elif bar.close < bar.open and origin.close > origin.open:  # bearish displacement from bullish origin
            out.append(LocationEvidence(
                family=LocationFamily.SUPPLY_DEMAND, timeframe=timeframe, side=LocationSide.RESISTANCE,
                zone_low=origin.low, zone_high=origin.high, reference_index=i - 1,
                detector_id="LOC_SUPPLY_DEMAND_V1"))
    return tuple(out[-max_zones:])


def liquidity_levels(
    bars: tuple[MarketBar, ...], timeframe: str, swing_order: int = 2, asof_index: int | None = None,
) -> tuple[LocationEvidence, ...]:
    """Liquidity pools: equal highs (BSL) / equal lows (SSL) + latest swing extremes."""
    idx = len(bars) - 1 if asof_index is None else asof_index
    swings = [s for s in confirmed_swing_points(bars[: idx + 1], swing_order) if s.confirmed_index <= idx]
    tol = EQUAL_LEVEL_FRACTION * _mean_range(bars, idx)
    zone_tol = LEVEL_TOLERANCE_FRACTION * _mean_range(bars, idx)
    out: list[LocationEvidence] = []
    highs = [s for s in swings if s.kind == "HIGH"]
    lows = [s for s in swings if s.kind == "LOW"]
    for seq, side, detector in (
        (highs, LocationSide.RESISTANCE, "LOC_LIQUIDITY_EQUAL_HIGHS_V1"),
        (lows, LocationSide.SUPPORT, "LOC_LIQUIDITY_EQUAL_LOWS_V1"),
    ):
        for a, b in zip(seq, seq[1:]):
            if abs(a.price - b.price) <= tol:
                pool = max(a.price, b.price) if side == LocationSide.RESISTANCE else min(a.price, b.price)
                out.append(LocationEvidence(
                    family=LocationFamily.LIQUIDITY_LEVEL, timeframe=timeframe, side=side,
                    zone_low=pool - zone_tol, zone_high=pool + zone_tol,
                    reference_index=b.index, detector_id=detector))
    # Latest swing extremes always carry resting liquidity.
    if highs:
        out.append(LocationEvidence(
            family=LocationFamily.LIQUIDITY_LEVEL, timeframe=timeframe, side=LocationSide.RESISTANCE,
            zone_low=highs[-1].price - zone_tol, zone_high=highs[-1].price + zone_tol,
            reference_index=highs[-1].index, detector_id="LOC_LIQUIDITY_SWING_HIGH_V1"))
    if lows:
        out.append(LocationEvidence(
            family=LocationFamily.LIQUIDITY_LEVEL, timeframe=timeframe, side=LocationSide.SUPPORT,
            zone_low=lows[-1].price - zone_tol, zone_high=lows[-1].price + zone_tol,
            reference_index=lows[-1].index, detector_id="LOC_LIQUIDITY_SWING_LOW_V1"))
    return tuple(out)


class PremiumDiscountState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    timeframe: str
    range_high: float
    range_low: float
    midpoint: float
    state: str  # "PREMIUM" | "DISCOUNT" | "EQUILIBRIUM"
    detector_id: str = "LOC_PREMIUM_DISCOUNT_V1"


def premium_discount(
    bars: tuple[MarketBar, ...], timeframe: str, price: float, swing_order: int = 2,
    asof_index: int | None = None,
) -> PremiumDiscountState | None:
    """Dealing range = last confirmed swing high/low; below midpoint = DISCOUNT."""
    idx = len(bars) - 1 if asof_index is None else asof_index
    swings = [s for s in confirmed_swing_points(bars[: idx + 1], swing_order) if s.confirmed_index <= idx]
    highs = [s for s in swings if s.kind == "HIGH"]
    lows = [s for s in swings if s.kind == "LOW"]
    if not highs or not lows:
        return None
    hi, lo = highs[-1].price, lows[-1].price
    if hi <= lo:
        return None
    mid = (hi + lo) / 2.0
    state = "DISCOUNT" if price < mid else ("PREMIUM" if price > mid else "EQUILIBRIUM")
    return PremiumDiscountState(timeframe=timeframe, range_high=hi, range_low=lo, midpoint=mid, state=state)


def premium_discount_supports(state: PremiumDiscountState | None, direction: Direction) -> bool:
    """BULL theses want DISCOUNT; BEAR theses want PREMIUM. Fail-closed on None."""
    if state is None:
        return False
    if direction == Direction.BULL:
        return state.state == "DISCOUNT"
    if direction == Direction.BEAR:
        return state.state == "PREMIUM"
    return False


def fvg_zones(
    bars: tuple[MarketBar, ...], timeframe: str, asof_index: int | None = None, max_zones: int = 5,
) -> tuple[LocationEvidence, ...]:
    """Three-candle FVGs (usable only after the third candle closes)."""
    idx = len(bars) - 1 if asof_index is None else asof_index
    out: list[LocationEvidence] = []
    for gap in detect_fvg(bars[: idx + 1]):
        side = LocationSide.SUPPORT if gap.direction == "BULLISH" else LocationSide.RESISTANCE
        out.append(LocationEvidence(
            family=LocationFamily.FVG, timeframe=timeframe, side=side,
            zone_low=gap.lower, zone_high=gap.upper, reference_index=gap.index,
            detector_id="LOC_FVG_V1"))
    return tuple(out[-max_zones:])


def session_level_zones(
    previous_high: float | None, previous_low: float | None, timeframe: str,
    tolerance: float, reference_index: int = 0,
) -> tuple[LocationEvidence, ...]:
    """FX-only: previous-session high/low as location zones (SESSION_LEVEL family)."""
    out: list[LocationEvidence] = []
    if previous_high is not None:
        out.append(LocationEvidence(
            family=LocationFamily.SESSION_LEVEL, timeframe=timeframe, side=LocationSide.RESISTANCE,
            zone_low=previous_high - tolerance, zone_high=previous_high + tolerance,
            reference_index=reference_index, detector_id="LOC_SESSION_PREV_HIGH_V1"))
    if previous_low is not None:
        out.append(LocationEvidence(
            family=LocationFamily.SESSION_LEVEL, timeframe=timeframe, side=LocationSide.SUPPORT,
            zone_low=previous_low - tolerance, zone_high=previous_low + tolerance,
            reference_index=reference_index, detector_id="LOC_SESSION_PREV_LOW_V1"))
    return tuple(out)


def evidence_at_price(
    evidences: tuple[LocationEvidence, ...], price: float, direction: Direction,
    families: tuple[LocationFamily, ...] | None = None,
) -> tuple[LocationEvidence, ...]:
    """Evidences containing `price` that support `direction` (optionally by family)."""
    hits = []
    for ev in evidences:
        if families is not None and ev.family not in families:
            continue
        if ev.contains(price) and ev.supports(direction):
            hits.append(ev)
    return tuple(hits)
