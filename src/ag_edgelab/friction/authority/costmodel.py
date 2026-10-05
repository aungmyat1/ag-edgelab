"""Transaction-cost legs: GROSS_R to NET_R without double counting.

A trade is not one event. A scaled exit is an entry plus a first-objective
partial plus a runner, and each crossing has its own cost. The two ways
this goes wrong are symmetric and both common:

* **Under-counting** — charge one spread and one commission for the whole
  trade, ignoring that every partial exit crosses the book again.
* **Over-counting** — charge a full spread on the entry AND a full spread
  on every exit, which bills a two-partial trade three round trips.

This module makes the allocation explicit. A spread convention is
declared once, and the invariant it must satisfy is that the total spread
cost of a round trip depends only on the volume traded, never on how many
pieces the exit was broken into. ``test_partial_exits_do_not_double_count_spread``
enforces exactly that.

Reference price basis
---------------------
``FULL_SPREAD_ON_ENTRY`` is the correct convention for this repository's
data authority, whose canonical OHLC is built from the BID series. A long
signalled on bid actually enters at ask (bid + spread) and exits at bid,
so the whole spread is paid once, at entry. ``HALF_SPREAD_PER_LEG`` is
provided for mid-price reference series. Both produce the same round-trip
total; they differ only in which leg carries it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from ag_edgelab.friction.authority.components import (
    AuthorityStatus, CommissionSpec, FrictionComponentMissing, SlippageAuthority,
    SwapApplicability, SwapMode, SwapSpec,
)
from ag_edgelab.friction.authority.symbols import SymbolSpec

COST_MODEL_VERSION = "EDGELAB_FRICTION_COST_MODEL_V1"


class Side(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"

    @property
    def direction(self) -> float:
        return 1.0 if self is Side.LONG else -1.0


class ExitKind(StrEnum):
    """Why a leg closed. Diagnostic, and it selects the slippage profile."""

    TARGET_PARTIAL = "TARGET_PARTIAL"
    RUNNER = "RUNNER"
    STOP = "STOP"
    HORIZON = "HORIZON"
    FORCED_CLOSE = "FORCED_CLOSE"
    FULL_TARGET = "FULL_TARGET"


class SpreadConvention(StrEnum):
    FULL_SPREAD_ON_ENTRY = "FULL_SPREAD_ON_ENTRY"
    HALF_SPREAD_PER_LEG = "HALF_SPREAD_PER_LEG"


@dataclass(frozen=True)
class ExitLeg:
    """One closing crossing."""

    volume_lots: float
    exit_price: float
    kind: ExitKind
    timestamp_utc: datetime | None = None
    slippage_points_override: float | None = None


@dataclass(frozen=True)
class TradePlan:
    """A complete position lifecycle, priced end to end."""

    symbol: str
    side: Side
    entry_price: float
    stop_price: float
    volume_lots: float
    exits: tuple[ExitLeg, ...]
    entry_timestamp_utc: datetime | None = None
    rollovers_held: int = 0
    entry_slippage_points_override: float | None = None

    @property
    def closed_volume(self) -> float:
        return sum(leg.volume_lots for leg in self.exits)

    def validate(self) -> None:
        if self.volume_lots <= 0:
            raise ValueError("volume_lots must be positive")
        if not self.exits:
            raise ValueError("a trade plan must close its position")
        if abs(self.closed_volume - self.volume_lots) > 1e-9:
            raise ValueError(
                f"exit volume {self.closed_volume} does not close the opened "
                f"{self.volume_lots}: every lot entered must be accounted for, "
                "otherwise costs are allocated against a phantom position")
        if abs(self.entry_price - self.stop_price) <= 0:
            raise ValueError("entry and stop imply zero risk; R is undefined")


@dataclass
class CostBreakdown:
    """Money and R accounting for one trade plan."""

    symbol: str
    risk_money: float
    gross_money: float = 0.0
    spread_money: float = 0.0
    commission_money: float = 0.0
    slippage_money: float = 0.0
    swap_money: float = 0.0
    legs: list[dict] = field(default_factory=list)
    spread_convention: str = ""
    swap_applicability: str = ""

    @property
    def total_cost_money(self) -> float:
        return (self.spread_money + self.commission_money
                + self.slippage_money + self.swap_money)

    @property
    def net_money(self) -> float:
        return self.gross_money - self.total_cost_money

    @property
    def gross_r(self) -> float:
        return self.gross_money / self.risk_money

    @property
    def net_r(self) -> float:
        return self.net_money / self.risk_money

    @property
    def total_cost_r(self) -> float:
        return self.total_cost_money / self.risk_money

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "cost_model_version": COST_MODEL_VERSION,
            "spread_convention": self.spread_convention,
            "swap_applicability": self.swap_applicability,
            "risk_money": round(self.risk_money, 8),
            "gross_money": round(self.gross_money, 8),
            "spread_money": round(self.spread_money, 8),
            "commission_money": round(self.commission_money, 8),
            "slippage_money": round(self.slippage_money, 8),
            "swap_money": round(self.swap_money, 8),
            "total_cost_money": round(self.total_cost_money, 8),
            "net_money": round(self.net_money, 8),
            "GROSS_R": round(self.gross_r, 8),
            "total_cost_R": round(self.total_cost_r, 8),
            "NET_R": round(self.net_r, 8),
            "legs": list(self.legs),
        }


def price_cost_of_spread(spread_price: float, spec: SymbolSpec,
                         volume_lots: float) -> float:
    return spec.price_to_money(spread_price, volume_lots)


def compute_costs(
    plan: TradePlan,
    *,
    spec: SymbolSpec,
    spread_price: float,
    commission: CommissionSpec,
    slippage: SlippageAuthority,
    swap: SwapSpec,
    swap_applicability: SwapApplicability,
    spread_convention: SpreadConvention = SpreadConvention.FULL_SPREAD_ON_ENTRY,
    require_slippage: bool = True,
) -> CostBreakdown:
    """Price a trade plan. Fails closed on any missing required authority."""
    plan.validate()
    if spread_price < 0:
        raise ValueError("spread_price must be non-negative (ask >= bid)")

    risk_price = abs(plan.entry_price - plan.stop_price)
    risk_money = spec.price_to_money(risk_price, plan.volume_lots)
    if risk_money <= 0:
        raise ValueError("risk resolves to zero money; R is undefined")

    out = CostBreakdown(symbol=plan.symbol, risk_money=risk_money,
                        spread_convention=str(spread_convention),
                        swap_applicability=str(swap_applicability))

    # --- spread -------------------------------------------------------
    if spread_convention is SpreadConvention.FULL_SPREAD_ON_ENTRY:
        entry_spread_price = spread_price
        exit_spread_fraction = 0.0
    else:
        entry_spread_price = spread_price / 2.0
        exit_spread_fraction = 0.5
    out.spread_money += price_cost_of_spread(entry_spread_price, spec,
                                             plan.volume_lots)

    # --- entry commission --------------------------------------------
    notional_entry = ((spec.contract_size or 0.0) * plan.entry_price
                      * plan.volume_lots) or None
    out.commission_money += commission.cost_for(
        volume_lots=plan.volume_lots, sides=1, notional=notional_entry)

    # --- entry slippage ----------------------------------------------
    entry_slip_points = _slippage_points(
        slippage, plan.entry_slippage_points_override, require_slippage)
    out.slippage_money += spec.price_to_money(
        spec.points_to_price(entry_slip_points), plan.volume_lots)

    out.legs.append({
        "leg": "ENTRY",
        "volume_lots": plan.volume_lots,
        "price": plan.entry_price,
        "spread_money": round(price_cost_of_spread(entry_spread_price, spec,
                                                   plan.volume_lots), 8),
        "commission_money": round(commission.cost_for(
            volume_lots=plan.volume_lots, sides=1, notional=notional_entry), 8),
        "slippage_points": entry_slip_points,
    })

    # --- exits --------------------------------------------------------
    for leg in plan.exits:
        if leg.volume_lots <= 0:
            raise ValueError("exit legs must close positive volume")
        leg_spread_price = spread_price * exit_spread_fraction
        leg_spread = price_cost_of_spread(leg_spread_price, spec, leg.volume_lots)
        notional_exit = ((spec.contract_size or 0.0) * leg.exit_price
                         * leg.volume_lots) or None
        leg_commission = commission.cost_for(
            volume_lots=leg.volume_lots, sides=1, notional=notional_exit)
        leg_slip_points = _slippage_points(
            slippage, leg.slippage_points_override, require_slippage)
        leg_slip = spec.price_to_money(
            spec.points_to_price(leg_slip_points), leg.volume_lots)

        pnl_price = (leg.exit_price - plan.entry_price) * plan.side.direction
        leg_gross = spec.price_to_money(pnl_price, leg.volume_lots)

        out.spread_money += leg_spread
        out.commission_money += leg_commission
        out.slippage_money += leg_slip
        out.gross_money += leg_gross
        out.legs.append({
            "leg": str(leg.kind),
            "volume_lots": leg.volume_lots,
            "price": leg.exit_price,
            "gross_money": round(leg_gross, 8),
            "spread_money": round(leg_spread, 8),
            "commission_money": round(leg_commission, 8),
            "slippage_points": leg_slip_points,
        })

    # --- swap ---------------------------------------------------------
    out.swap_money += _swap_cost(plan, spec, swap, swap_applicability)
    return out


def _slippage_points(slippage: SlippageAuthority, override: float | None,
                     require: bool) -> float:
    if override is not None:
        return override
    if slippage.is_complete:
        return slippage.cost_points()
    if require:
        raise FrictionComponentMissing(
            "SLIPPAGE_AUTHORITY=MISSING and require_slippage=True. Set an "
            "explicit per-leg override, or run with require_slippage=False to "
            "produce an EXPLICITLY SLIPPAGE-FREE figure that must be labelled "
            "as such — it is a lower bound on cost, never a net result.")
    return 0.0


def _swap_cost(plan: TradePlan, spec: SymbolSpec, swap: SwapSpec,
               applicability: SwapApplicability) -> float:
    if applicability is SwapApplicability.NOT_APPLICABLE:
        return 0.0
    if plan.rollovers_held <= 0:
        return 0.0
    if applicability is SwapApplicability.UNDETERMINED:
        raise FrictionComponentMissing(
            "SWAP_APPLICABILITY=UNDETERMINED with rollovers held. Swap may only "
            "be skipped when a FROZEN strategy contract proves the position "
            "cannot be open at the venue rollover.")
    if not swap.is_complete:
        raise FrictionComponentMissing(
            f"SWAP_AUTHORITY=MISSING for {plan.symbol} but the plan holds "
            f"{plan.rollovers_held} rollover(s); financing cannot be assumed zero.")
    if swap.swap_mode is SwapMode.DISABLED:
        return 0.0
    rate = swap.swap_long if plan.side is Side.LONG else swap.swap_short
    if swap.swap_mode is SwapMode.POINTS:
        per_night = spec.price_to_money(spec.points_to_price(rate),
                                        plan.volume_lots)
    else:
        raise FrictionComponentMissing(
            f"swap_mode={swap.swap_mode} is not convertible without an "
            "account-currency rate from the terminal; refusing to approximate.")
    # Cost is positive when the rate is negative (a charge).
    return -per_night * plan.rollovers_held


# ---------------------------------------------------------------------------
# readiness
# ---------------------------------------------------------------------------

def economic_verification_ready(
    *,
    spec: SymbolSpec,
    spread_observations: int,
    commission: CommissionSpec,
    slippage: SlippageAuthority,
    swap: SwapSpec,
    swap_applicability: SwapApplicability,
) -> tuple[bool, list[str]]:
    """Can NET_R be computed for this symbol? Lists every blocker."""
    blockers: list[str] = []
    if not spec.is_complete:
        blockers.append(
            f"symbol contract incomplete: missing {list(spec.missing_fields())}")
    if spread_observations <= 0:
        blockers.append("no spread observations captured")
    if not commission.is_complete:
        blockers.append(
            f"commission authority {commission.status}: missing "
            f"{list(commission.missing_fields())}")
    if not slippage.is_complete:
        blockers.append(f"slippage authority {slippage.status}")
    if (swap_applicability is not SwapApplicability.NOT_APPLICABLE
            and not swap.is_complete):
        blockers.append(
            f"swap authority {swap.status} and applicability {swap_applicability}")
    return (not blockers), blockers
