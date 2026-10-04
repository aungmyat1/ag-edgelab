"""Funnel 3 — target/outcome lab: fixed-R capability + natural-target families.

Fixed R targets 1R..5R are PRESERVED, never replaced. Natural targets are
diagnostic only. For crypto, PDH/PDL are never a mandatory directional
authority — they are an optional daily-liquidity feature when preregistered.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.strategies.crypto_mtf_smc import confirmed_swing_points, detect_fvg
from ag_edgelab.universal.direction import Direction
from ag_edgelab.universal.location import LocationEvidence, LocationFamily, LocationSide

FIXED_R_TARGETS: tuple[int, ...] = (1, 2, 3, 4, 5)
TARGET_R_BUCKETS: tuple[str, ...] = ("<1R", "1-2R", "2-3R", "3-4R", "4-5R", ">5R")


class NaturalTargetFamily(StrEnum):
    NEXT_SWING = "NEXT_SWING"
    OPPOSING_SUPPLY_DEMAND = "OPPOSING_SUPPLY_DEMAND"
    PDH_PDL = "PDH_PDL"            # FX natural family; crypto: optional diagnostic only
    LIQUIDITY_POOL = "LIQUIDITY_POOL"
    FVG_IMBALANCE = "FVG_IMBALANCE"


@dataclass(frozen=True)
class EntryGeometry:
    direction: Direction  # BULL -> long, BEAR -> short
    entry: float
    stop: float

    @property
    def risk(self) -> float:
        risk = abs(self.entry - self.stop)
        if risk <= 0:
            raise ValueError("entry geometry requires non-zero risk")
        return risk


class ExcursionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mfe_r: float
    mae_r: float
    bars_evaluated: int
    fixed_target_reached: dict[int, bool]  # k -> reached kR BEFORE stop
    stopped_out: bool
    stop_bar_offset: int | None = None


def compute_excursions(
    forward_bars: tuple[MarketBar, ...], geometry: EntryGeometry, horizon: int,
) -> ExcursionResult:
    """MFE/MAE in R units plus fixed 1R..5R reachability over `horizon` bars.

    `forward_bars` must contain only bars strictly AFTER the entry decision
    bar — outcome measurement is the only place future bars are legal.
    Ambiguity rule (fail-closed): if one bar touches both the stop and an
    unreached R level, the stop is counted FIRST.
    """
    if geometry.direction not in (Direction.BULL, Direction.BEAR):
        raise ValueError("entry geometry requires a non-neutral direction")
    risk = geometry.risk
    rows = forward_bars[:horizon]
    reached: dict[int, bool] = {k: False for k in FIXED_R_TARGETS}
    mfe = 0.0
    mae = 0.0
    stopped = False
    stop_offset: int | None = None
    for offset, bar in enumerate(rows):
        if geometry.direction == Direction.BULL:
            favorable = (bar.high - geometry.entry) / risk
            adverse = (geometry.entry - bar.low) / risk
            hit_stop = bar.low <= geometry.stop
        else:
            favorable = (geometry.entry - bar.low) / risk
            adverse = (bar.high - geometry.entry) / risk
            hit_stop = bar.high >= geometry.stop
        mfe = max(mfe, favorable)
        mae = max(mae, adverse)
        if not stopped:
            if hit_stop:
                stopped = True
                stop_offset = offset
            else:
                for k in FIXED_R_TARGETS:
                    if not reached[k] and favorable >= k:
                        reached[k] = True
        if stopped:
            break
    return ExcursionResult(mfe_r=mfe, mae_r=mae, bars_evaluated=len(rows),
                           fixed_target_reached=reached, stopped_out=stopped,
                           stop_bar_offset=stop_offset)


def natural_target_r(entry: float, stop: float, target: float) -> float:
    """TARGET_R = abs(target - entry) / abs(entry - stop)."""
    risk = abs(entry - stop)
    if risk <= 0:
        raise ValueError("natural target R requires non-zero risk")
    return abs(target - entry) / risk


def classify_target_r(value: float) -> str:
    if value < 1.0:
        return "<1R"
    if value < 2.0:
        return "1-2R"
    if value < 3.0:
        return "2-3R"
    if value < 4.0:
        return "3-4R"
    if value <= 5.0:
        return "4-5R"
    return ">5R"


class NaturalTarget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    family: NaturalTargetFamily
    price: float
    target_r: float
    bucket: str


def _mk(family: NaturalTargetFamily, price: float, geometry: EntryGeometry) -> NaturalTarget:
    r = natural_target_r(geometry.entry, geometry.stop, price)
    return NaturalTarget(family=family, price=price, target_r=r, bucket=classify_target_r(r))


def next_swing_target(
    bars: tuple[MarketBar, ...], geometry: EntryGeometry, swing_order: int = 2,
    asof_index: int | None = None,
) -> NaturalTarget | None:
    """Most recent confirmed OPPOSING swing beyond entry (deterministic)."""
    idx = len(bars) - 1 if asof_index is None else asof_index
    swings = [s for s in confirmed_swing_points(bars[: idx + 1], swing_order) if s.confirmed_index <= idx]
    if geometry.direction == Direction.BULL:
        candidates = [s.price for s in swings if s.kind == "HIGH" and s.price > geometry.entry]
    else:
        candidates = [s.price for s in swings if s.kind == "LOW" and s.price < geometry.entry]
    if not candidates:
        return None
    return _mk(NaturalTargetFamily.NEXT_SWING, candidates[-1], geometry)


def opposing_zone_target(
    zones: tuple[LocationEvidence, ...], geometry: EntryGeometry,
    family: LocationFamily, natural_family: NaturalTargetFamily,
) -> NaturalTarget | None:
    """Nearest opposing zone edge beyond entry (supply for longs, demand for shorts)."""
    if geometry.direction == Direction.BULL:
        edges = [z.zone_low for z in zones
                 if z.family == family and z.side == LocationSide.RESISTANCE and z.zone_low > geometry.entry]
        price = min(edges) if edges else None
    else:
        edges = [z.zone_high for z in zones
                 if z.family == family and z.side == LocationSide.SUPPORT and z.zone_high < geometry.entry]
        price = max(edges) if edges else None
    if price is None:
        return None
    return _mk(natural_family, price, geometry)


def pdh_pdl_target(
    d1_bars: tuple[MarketBar, ...], geometry: EntryGeometry, *, is_crypto: bool,
    preregistered_for_crypto: bool = False,
) -> NaturalTarget | None:
    """Previous-day high/low target.

    FX: a standard natural-target family. CRYPTO: never mandatory directional
    authority; only usable when explicitly preregistered as an optional
    daily-liquidity feature — otherwise the function fails closed (None).
    """
    if is_crypto and not preregistered_for_crypto:
        return None
    if not d1_bars:
        return None
    prev = d1_bars[-1]
    price = prev.high if geometry.direction == Direction.BULL else prev.low
    if geometry.direction == Direction.BULL and price <= geometry.entry:
        return None
    if geometry.direction == Direction.BEAR and price >= geometry.entry:
        return None
    return _mk(NaturalTargetFamily.PDH_PDL, price, geometry)


def fvg_target(
    bars: tuple[MarketBar, ...], geometry: EntryGeometry, asof_index: int | None = None,
) -> NaturalTarget | None:
    """Nearest opposing FVG midpoint beyond entry."""
    idx = len(bars) - 1 if asof_index is None else asof_index
    gaps = detect_fvg(bars[: idx + 1])
    if geometry.direction == Direction.BULL:
        mids = [g.midpoint for g in gaps if g.direction == "BEARISH" and g.midpoint > geometry.entry]
        price = min(mids) if mids else None
    else:
        mids = [g.midpoint for g in gaps if g.direction == "BULLISH" and g.midpoint < geometry.entry]
        price = max(mids) if mids else None
    if price is None:
        return None
    return _mk(NaturalTargetFamily.FVG_IMBALANCE, price, geometry)
