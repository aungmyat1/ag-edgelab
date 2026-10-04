"""Preregistered FX direction hypotheses D01..D10 (V0.3 engine, unchanged).

Every hypothesis maps observation context -> BULL | BEAR | NEUTRAL using the
V0.3 structural core (confirmed HH/HL -> BULL, LH/LL -> BEAR) plus declared
context gates. MA hypotheses are controls; nothing assumes MA improves
structural direction. The registry is frozen and hash-sealed — no
combinations beyond it are evaluated.

Session identity is deliberately absent from every hypothesis: direction
must come from causal market structure/context, never be manufactured from
the session clock (mission section 6).
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.strategies.crypto_mtf_smc import confirmed_swing_points
from ag_edgelab.universal.confirmation import structure_shift_events
from ag_edgelab.universal.direction import MA_FAST, MA_SLOW, Direction

SWING_ORDER = 2


# ---------------------------------------------------------------------------
# Causal per-bar series (one O(n) pass; .at(i) uses only bars <= i)
# ---------------------------------------------------------------------------

class StructuralSeries:
    """Per-index structural direction + dealing range for one timeframe.

    Equivalent, index by index, to V0.3 ``structural_direction(bars, tf,
    asof_index=i)`` — pivots confirm only after ``order`` right-side closes,
    so the value at index i never changes when later bars are appended or
    mutated (truncation/future-mutation invariance; tested).
    """

    def __init__(self, bars: tuple[MarketBar, ...], order: int = SWING_ORDER) -> None:
        self.bars = bars
        n = len(bars)
        swings = confirmed_swing_points(bars, order)
        by_confirm: dict[int, list] = {}
        for swing in swings:
            by_confirm.setdefault(swing.confirmed_index, []).append(swing)
        self.direction: list[Direction] = [Direction.NEUTRAL] * n
        self.range_high: list[float | None] = [None] * n
        self.range_low: list[float | None] = [None] * n
        self.high_count: list[int] = [0] * n
        self.low_count: list[int] = [0] * n
        self.high_prices: list[float] = []
        self.low_prices: list[float] = []
        current = Direction.NEUTRAL
        for i in range(n):
            for swing in by_confirm.get(i, ()):
                (self.high_prices if swing.kind == "HIGH" else self.low_prices).append(swing.price)
            highs, lows = self.high_prices, self.low_prices
            if len(highs) >= 2 and len(lows) >= 2:
                hh, hl = highs[-1] > highs[-2], lows[-1] > lows[-2]
                lh, ll = highs[-1] < highs[-2], lows[-1] < lows[-2]
                current = (Direction.BULL if hh and hl
                           else Direction.BEAR if lh and ll else Direction.NEUTRAL)
            self.direction[i] = current
            self.range_high[i] = highs[-1] if highs else None
            self.range_low[i] = lows[-1] if lows else None
            self.high_count[i] = len(highs)
            self.low_count[i] = len(lows)

    def at(self, index: int) -> Direction:
        return self.direction[index] if index >= 0 else Direction.NEUTRAL

    def recent_highs(self, index: int, k: int = 6) -> list[float]:
        return self.high_prices[max(0, self.high_count[index] - k): self.high_count[index]]

    def recent_lows(self, index: int, k: int = 6) -> list[float]:
        return self.low_prices[max(0, self.low_count[index] - k): self.low_count[index]]


class FlowSeries:
    """H1 internal flow: direction of the most recent BOS/MSS at or before i."""

    def __init__(self, bars: tuple[MarketBar, ...], timeframe: str = "H1",
                 order: int = SWING_ORDER) -> None:
        events = structure_shift_events(bars, timeframe, order)
        self._indices = [e.index for e in events]
        self._directions = [Direction(e.direction) for e in events]

    def at(self, index: int) -> Direction:
        pos = bisect_right(self._indices, index)
        return self._directions[pos - 1] if pos else Direction.NEUTRAL


class MaSeries:
    """MA50/MA200 direction per index (prefix sums; closes only)."""

    def __init__(self, bars: tuple[MarketBar, ...]) -> None:
        self._prefix = [0.0]
        for bar in bars:
            self._prefix.append(self._prefix[-1] + bar.close)

    def at(self, index: int) -> Direction:
        if index + 1 < MA_SLOW:
            return Direction.NEUTRAL
        fast = (self._prefix[index + 1] - self._prefix[index + 1 - MA_FAST]) / MA_FAST
        slow = (self._prefix[index + 1] - self._prefix[index + 1 - MA_SLOW]) / MA_SLOW
        if fast > slow:
            return Direction.BULL
        if fast < slow:
            return Direction.BEAR
        return Direction.NEUTRAL


class MeanRangeSeries:
    """Rolling mean bar range (window 20) per index — the tolerance unit."""

    def __init__(self, bars: tuple[MarketBar, ...], window: int = 20) -> None:
        self._prefix = [0.0]
        for bar in bars:
            self._prefix.append(self._prefix[-1] + (bar.high - bar.low))
        self._window = window

    def at(self, index: int) -> float:
        lo = max(0, index + 1 - self._window)
        count = index + 1 - lo
        if count <= 0:
            return 0.0
        return (self._prefix[index + 1] - self._prefix[lo]) / count


# ---------------------------------------------------------------------------
# Observation context + hypothesis registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DirectionContext:
    d1: Direction
    h4: Direction
    h1: Direction
    premium_discount: str | None     # "PREMIUM" | "DISCOUNT" | "EQUILIBRIUM" | None
    h1_flow: Direction               # last H1 BOS/MSS direction
    liquidity_support_bull: bool     # price at a BULL-supporting H4 liquidity level
    liquidity_support_bear: bool
    ma: Direction                    # H1 MA50/200


def _agree(*dirs: Direction) -> Direction:
    values = set(dirs)
    if len(values) == 1 and Direction.NEUTRAL not in values:
        return dirs[0]
    return Direction.NEUTRAL


def _pd_aligned(direction: Direction, state: str | None) -> bool:
    if direction == Direction.BULL:
        return state == "DISCOUNT"
    if direction == Direction.BEAR:
        return state == "PREMIUM"
    return False


def _gate(direction: Direction, condition: bool) -> Direction:
    return direction if direction != Direction.NEUTRAL and condition else Direction.NEUTRAL


def _liquidity_support(ctx: DirectionContext, direction: Direction) -> bool:
    if direction == Direction.BULL:
        return ctx.liquidity_support_bull
    if direction == Direction.BEAR:
        return ctx.liquidity_support_bear
    return False


def evaluate_direction_hypotheses(ctx: DirectionContext) -> dict[str, Direction]:
    """All ten preregistered hypotheses for one observation context."""
    d01 = ctx.h4
    d02 = _agree(ctx.d1, ctx.h4)
    out = {
        "D01": d01,
        "D02": d02,
        "D03": _agree(ctx.h4, ctx.h1),
        "D04": _agree(ctx.d1, ctx.h4, ctx.h1),
        "D05": _gate(d01, _pd_aligned(d01, ctx.premium_discount)),
        "D06": _gate(d02, ctx.h1_flow == d02),
        "D07": _gate(d01, _liquidity_support(ctx, d01)),
        "D08": _gate(d01, _pd_aligned(d01, ctx.premium_discount) and ctx.h1_flow == d01),
        "D09": ctx.ma,
        "D10": _agree(d01, ctx.ma),
    }
    return out


DIRECTION_HYPOTHESES: dict[str, str] = {
    "D01": "H4 market structure (confirmed HH/HL vs LH/LL)",
    "D02": "D1 + H4 structure agreement",
    "D03": "H4 + H1 structure agreement",
    "D04": "D1 + H4 + H1 structure agreement",
    "D05": "H4 structure gated by H4 premium/discount alignment",
    "D06": "D1+H4 structure gated by H1 internal flow (last H1 BOS/MSS) agreement",
    "D07": "H4 structure gated by supporting H4 liquidity-level context",
    "D08": "H4 structure gated by premium/discount AND H1 internal flow",
    "D09": "MA50/MA200 (H1) only — control hypothesis",
    "D10": "H4 structure + MA50/MA200 agreement — control hypothesis",
}

PRIMARY_FUNNEL_HYPOTHESIS = "D01"  # preregistered funnel authority (no post-hoc pick)

FX_DIRECTION_REGISTRY_SHA256 = sha256_json({
    "hypotheses": DIRECTION_HYPOTHESES,
    "primary_funnel_hypothesis": PRIMARY_FUNNEL_HYPOTHESIS,
    "swing_order": SWING_ORDER,
    "ma": {"fast": MA_FAST, "slow": MA_SLOW},
    "session_identity_in_direction": "FORBIDDEN",
})
