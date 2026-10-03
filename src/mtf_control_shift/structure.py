from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .models import Candle, Zone

SWING_STRENGTH = 2
OB_LOOKBACK = 6


@dataclass(frozen=True)
class Swing:
    kind: str  # HIGH | LOW
    index: int
    confirmation_index: int
    price: float


def validate_series(candles: Sequence[Candle]) -> None:
    if not candles:
        raise ValueError("candle series must not be empty")
    for candle in candles:
        candle.validate()
    times = [c.time for c in candles]
    if times != sorted(times) or len(times) != len(set(times)):
        raise ValueError("candles must be unique and chronological")


def confirmed_swings(candles: Sequence[Candle], strength: int = SWING_STRENGTH) -> tuple[Swing, ...]:
    out: list[Swing] = []
    if len(candles) < 2 * strength + 1:
        return tuple(out)
    for i in range(strength, len(candles) - strength):
        c = candles[i]
        left = candles[i - strength:i]
        right = candles[i + 1:i + strength + 1]
        if all(c.high > x.high for x in left) and all(c.high >= x.high for x in right):
            out.append(Swing("HIGH", i, i + strength, c.high))
        if all(c.low < x.low for x in left) and all(c.low <= x.low for x in right):
            out.append(Swing("LOW", i, i + strength, c.low))
    return tuple(out)


def structure_bias(candles: Sequence[Candle]) -> str:
    swings = confirmed_swings(candles)
    highs = [s for s in swings if s.kind == "HIGH" and s.confirmation_index < len(candles)]
    lows = [s for s in swings if s.kind == "LOW" and s.confirmation_index < len(candles)]
    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL"
    hh = highs[-1].price > highs[-2].price
    hl = lows[-1].price > lows[-2].price
    lh = highs[-1].price < highs[-2].price
    ll = lows[-1].price < lows[-2].price
    if hh and hl:
        return "BULLISH"
    if lh and ll:
        return "BEARISH"
    return "NEUTRAL"


def fvg(candles: Sequence[Candle], i: int) -> tuple[str, float, float] | None:
    if i < 2:
        return None
    first, third = candles[i - 2], candles[i]
    if third.low > first.high:
        return ("BULLISH", first.high, third.low)
    if third.high < first.low:
        return ("BEARISH", third.high, first.low)
    return None


def _latest_confirmed_swing(swings: Iterable[Swing], kind: str, before_index: int) -> Swing | None:
    eligible = [s for s in swings if s.kind == kind and s.confirmation_index < before_index]
    return eligible[-1] if eligible else None


def _origin(candles: Sequence[Candle], i: int, bullish: bool) -> int | None:
    start = max(0, i - OB_LOOKBACK)
    for j in range(i - 1, start - 1, -1):
        c = candles[j]
        if bullish and c.close < c.open:
            return j
        if not bullish and c.close > c.open:
            return j
    return None


def zones(candles: Sequence[Candle]) -> tuple[Zone, ...]:
    validate_series(candles)
    swings = confirmed_swings(candles)
    out: list[Zone] = []
    for i in range(2, len(candles)):
        gap = fvg(candles, i)
        if gap is None:
            continue
        direction, gap_low, gap_high = gap
        if direction == "BULLISH":
            swing = _latest_confirmed_swing(swings, "HIGH", i)
            if swing is None or candles[i].close <= swing.price:
                continue
            origin = _origin(candles, i, True)
            if origin is None:
                continue
            oc = candles[origin]
            out.append(Zone("DEMAND", oc.low, oc.high, oc.time, candles[i].time,
                            gap_low, gap_high, swing.price))
        else:
            swing = _latest_confirmed_swing(swings, "LOW", i)
            if swing is None or candles[i].close >= swing.price:
                continue
            origin = _origin(candles, i, False)
            if origin is None:
                continue
            oc = candles[origin]
            out.append(Zone("SUPPLY", oc.low, oc.high, oc.time, candles[i].time,
                            gap_low, gap_high, swing.price))
    return tuple(out)


def _overlap(c: Candle, z: Zone) -> bool:
    return c.high >= z.low and c.low <= z.high


def _invalidated(c: Candle, z: Zone) -> bool:
    return c.close < z.low if z.kind == "DEMAND" else c.close > z.high


def _active_before(candles: Sequence[Candle], zone: Zone, before_index: int) -> bool:
    """True when no closed candle invalidated the zone before `before_index`."""
    created = next(i for i, c in enumerate(candles) if c.time == zone.created_time)
    return not any(_invalidated(c, zone) for c in candles[created + 1:before_index])


def latest_fresh_zone(candles: Sequence[Candle], kind: str) -> Zone | None:
    """Latest zone not invalidated and not previously mitigated.

    The final closed candle may be the first touch; earlier touches make the zone mitigated.
    """
    all_zones = [z for z in zones(candles) if z.kind == kind]
    for z in reversed(all_zones):
        created = next(i for i, c in enumerate(candles) if c.time == z.created_time)
        later = candles[created + 1:]
        if any(_invalidated(c, z) for c in later):
            continue
        if any(_overlap(c, z) for c in later[:-1]):
            continue
        return z
    return None


def control_shift_zones(candles: Sequence[Candle], direction: str) -> tuple[Zone, ...]:
    """Zones whose displacement closes through an opposing zone still active before the break."""
    validate_series(candles)
    all_zones = zones(candles)
    wanted = "DEMAND" if direction == "BULLISH" else "SUPPLY"
    opposite = "SUPPLY" if direction == "BULLISH" else "DEMAND"
    out: list[Zone] = []
    for z in all_zones:
        if z.kind != wanted:
            continue
        created_idx = next(i for i, c in enumerate(candles) if c.time == z.created_time)
        prior = [p for p in all_zones
                 if p.kind == opposite and p.created_time < z.created_time and _active_before(candles, p, created_idx)]
        if not prior:
            continue
        active = prior[-1]
        close = candles[created_idx].close
        if direction == "BULLISH" and close > active.high:
            out.append(z)
        elif direction == "BEARISH" and close < active.low:
            out.append(z)
    return tuple(out)


def zone_touched(candles: Sequence[Candle], zone: Zone, lookback: int = 4) -> bool:
    return any(_overlap(c, zone) for c in candles[-lookback:])


def classify_false_shift(candles: Sequence[Candle], direction: str) -> str | None:
    """Diagnostic false-CHoCH classification. It never creates an entry."""
    validate_series(candles)
    last = candles[-1]
    history = candles[:-1]
    all_zones = zones(history) if history else ()
    opposite = "SUPPLY" if direction == "BULLISH" else "DEMAND"
    candidates = [z for z in all_zones if z.kind == opposite and _active_before(candles, z, len(candles) - 1)]
    if candidates:
        active = candidates[-1]
        if direction == "BULLISH" and last.high > active.high and last.close <= active.high:
            return "LIQUIDITY_SWEEP"
        if direction == "BEARISH" and last.low < active.low and last.close >= active.low:
            return "LIQUIDITY_SWEEP"
    # Diagnostic only: touch an older FVG without a valid close-through.
    for z in reversed(all_zones):
        if last.high >= z.fvg_low and last.low <= z.fvg_high:
            return "FVG_REBALANCE"
    return None


def structural_target(candles: Sequence[Candle], direction: str, entry: float, minimum: float) -> float | None:
    all_zones = zones(candles)
    if direction == "LONG":
        supply = sorted(z.low for z in all_zones if z.kind == "SUPPLY" and z.low > minimum)
        if supply:
            return supply[0]
        highs = sorted(s.price for s in confirmed_swings(candles) if s.kind == "HIGH" and s.price > minimum)
        return highs[0] if highs else None
    demand = sorted((z.high for z in all_zones if z.kind == "DEMAND" and z.high < minimum), reverse=True)
    if demand:
        return demand[0]
    lows = sorted((s.price for s in confirmed_swings(candles) if s.kind == "LOW" and s.price < minimum), reverse=True)
    return lows[0] if lows else None
