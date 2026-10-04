"""Cross-asset parity — the same structural rule must behave identically for
FX and CRYPTO given structurally identical bars. Only explicitly
market-specific modules (sessions, friction authority, symbol geometry) may
differ; the core is shared code, so parity failures are core defects.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.universal.direction import Direction, structural_direction

Z = timezone.utc


def synthetic_structural_bars(
    pattern: str, base: float, scale: float,
    start: datetime | None = None, step_minutes: int = 240, cycles: int = 6,
    bars_per_leg: int = 3,
) -> tuple[MarketBar, ...]:
    """Deterministic zigzag ladder with confirmed HH/HL ("BULL"), LH/LL
    ("BEAR") or equal-high/equal-low structure ("NEUTRAL"), expressed as
    base + offset*scale so the SAME structure can be rendered at FX and
    crypto price geometry.

    Each leg is `bars_per_leg` monotone bars; the leg-end bar carries a 0.3
    overshoot wick so exactly one fractal pivot (order <= bars_per_leg - 1)
    confirms per leg.
    """
    if pattern not in ("BULL", "BEAR", "NEUTRAL"):
        raise ValueError("pattern must be BULL, BEAR or NEUTRAL")
    start = start or datetime(2026, 1, 1, tzinfo=Z)

    points: list[float] = [0.0]
    for k in range(cycles):
        if pattern == "BULL":
            points += [3.0 + k, 1.0 + k]        # rising peaks AND rising troughs
        elif pattern == "BEAR":
            points += [-3.0 - k, -1.0 - k]      # falling troughs AND falling peaks
        else:
            points += [3.0, 0.0]                # equal highs / equal lows

    bars: list[MarketBar] = []
    ts = start
    cursor = points[0]
    for target in points[1:]:
        step = (target - cursor) / bars_per_leg
        for j in range(bars_per_leg):
            o = cursor + j * step
            c = cursor + (j + 1) * step
            h, l = max(o, c), min(o, c)
            if j == bars_per_leg - 1:           # overshoot wick on the leg-end bar
                if step > 0:
                    h += 0.3
                else:
                    l -= 0.3
            o_, h_, l_, c_ = (base + v * scale for v in (o, h, l, c))
            bars.append(MarketBar(timestamp=ts, open=o_, high=max(h_, o_, c_),
                                  low=min(l_, o_, c_), close=c_, volume=1.0))
            ts += timedelta(minutes=step_minutes)
        cursor = target
    return tuple(bars)


class ParityResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern: str
    timeframe: str
    symbol_a: str
    symbol_b: str
    direction_a: Direction
    direction_b: Direction
    parity: bool


def structural_parity(
    pattern: str, timeframe: str,
    symbol_a: str, base_a: float, scale_a: float,
    symbol_b: str, base_b: float, scale_b: float,
    swing_order: int = 2,
) -> ParityResult:
    """Render one structural pattern at two symbol geometries; compare states."""
    bars_a = synthetic_structural_bars(pattern, base_a, scale_a)
    bars_b = synthetic_structural_bars(pattern, base_b, scale_b)
    dir_a = structural_direction(bars_a, timeframe, swing_order).direction
    dir_b = structural_direction(bars_b, timeframe, swing_order).direction
    return ParityResult(pattern=pattern, timeframe=timeframe,
                        symbol_a=symbol_a, symbol_b=symbol_b,
                        direction_a=dir_a, direction_b=dir_b, parity=dir_a == dir_b)
