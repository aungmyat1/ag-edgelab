from __future__ import annotations

"""Frozen per-symbol friction authority for the SESSION_TRADE_V2 campaign.

Every cost is expressed in PRICE units per unit of underlying, per ROUND TURN
(entry + exit of one unit, including partial legs: the position crosses the
spread once per unit round turn and pays slippage/commission on each fill;
allocation-weighted partial exits collapse to the same per-unit round-turn
cost).

Cost is converted to R per trade as ``cost_price / risk_distance`` where the
risk distance is the strategy's own ``R = abs(entry - stop) = 0.25 * range``.

Evidence basis (frozen 2026-10-03, conservative end of each published range):

* EURUSD  spread 0.3 pip   — VT Markets RAW ECN average 0.1-0.3 pip
  (tradersunion.com/brokers/forex/view/vt_markets/fees-and-spread,
  brokerchooser.com VT Markets forex-spread review, fxstreet.com VT review).
* GBPUSD  spread 0.4 pip   — VT Markets RAW ECN average 0.2-0.4 pip (same
  sources).
* USDJPY  spread 0.4 pip   — VT Markets does not publish USDJPY; cross-broker
  live RAW/ECN average 0.47 pip (compareforexbrokers.com spread testing) and
  typical raw range 0.0-0.5 pip (algospecial.com USDJPY guide).  The lower
  bound of that evidence band is used as baseline and the 1.25x/1.5x stress
  grid covers underestimate risk.
* XAUUSD  spread $0.30/oz  — MEASURED Dukascopy bid/ask M1, Feb/Jun/Oct 2017,
  weekday session hours 06:00-14:00 UTC: median $0.237, p75 $0.259,
  p90 $0.280, p95 $0.284 (n=23,040).  Frozen above p95 and above VT Markets'
  published XAU/USD average ($0.18, brokerchooser.com).
* Commission $7/lot round turn for FX (VT Markets RAW ECN $3.00-$3.50/side)
  and $7/lot round turn for gold (Vantage/VT RAW ECN $3.00/side, 100 oz lot).
* Slippage 0.1 pip per side for FX majors, $0.05/oz per side for gold —
  conservative for M15-close decisions on liquid majors; limit fills are
  modeled at the limit price (no favorable slippage assumed).

Missing evidence fails CLOSED (``friction_r`` raises ``FrictionUnqualified``);
no cell is ever reported net-positive on unqualified friction.
"""

from dataclasses import dataclass

from ag_edgelab.friction.model import FrictionScenario, apply_normalized_r_stress

STRESS_MULTIPLIERS = (1.0, 1.25, 1.5)  # EdgeLab REQUIRED_FRICTION_GRID


class FrictionUnqualified(RuntimeError):
    """Raised when no frozen friction authority exists for an instrument."""


@dataclass(frozen=True)
class SymbolFriction:
    symbol: str
    spread_rt: float          # round-turn spread cost, price units per unit
    commission_usd_rt: float  # round-turn commission, USD per standard lot
    slippage_rt: float        # round-turn slippage, price units per unit
    evidence: str
    contract_size: float      # units of underlying per 1.0 standard lot
    quote_per_usd: bool = False  # True for USD-quoted-in-JPY (USDJPY)

    def round_turn_cost(self, entry_price: float) -> float:
        """Total round-turn cost in price units, at the trade's own price."""
        if self.quote_per_usd:
            # Commission is USD per lot on USD notional; price is JPY per USD.
            commission_price = self.commission_usd_rt * entry_price / self.contract_size
        else:
            commission_price = self.commission_usd_rt / self.contract_size
        return self.spread_rt + commission_price + self.slippage_rt


SYMBOL_FRICTION: dict[str, SymbolFriction] = {
    "EURUSD": SymbolFriction(
        symbol="EURUSD",
        spread_rt=0.3 * 0.0001,
        commission_usd_rt=7.0,
        slippage_rt=2 * 0.1 * 0.0001,
        evidence=(
            "VT Markets RAW ECN avg spread 0.1-0.3 pip (tradersunion.com, brokerchooser.com, "
            "fxstreet.com, 2026); commission $3.00-3.50/side => $7 RT baseline; slippage 0.1 pip/side"
        ),
        contract_size=100_000.0,
    ),
    "GBPUSD": SymbolFriction(
        symbol="GBPUSD",
        spread_rt=0.4 * 0.0001,
        commission_usd_rt=7.0,
        slippage_rt=2 * 0.1 * 0.0001,
        evidence=(
            "VT Markets RAW ECN avg spread 0.2-0.4 pip (tradersunion.com, brokerchooser.com, 2026); "
            "commission $7 RT baseline; slippage 0.1 pip/side"
        ),
        contract_size=100_000.0,
    ),
    "USDJPY": SymbolFriction(
        symbol="USDJPY",
        spread_rt=0.4 * 0.01,
        commission_usd_rt=7.0,
        slippage_rt=2 * 0.1 * 0.01,
        evidence=(
            "VT Markets publishes no USDJPY spread; cross-broker live RAW/ECN average 0.47 pip "
            "(compareforexbrokers.com, 2026) and typical raw band 0.0-0.5 pip (algospecial.com); "
            "baseline 0.4 pip + 1.25x/1.5x stress grid; commission $7 RT; slippage 0.1 pip/side"
        ),
        contract_size=100_000.0,
        quote_per_usd=True,
    ),
    "XAUUSD": SymbolFriction(
        symbol="XAUUSD",
        spread_rt=0.30,
        commission_usd_rt=7.0,
        slippage_rt=2 * 0.05,
        evidence=(
            "MEASURED Dukascopy bid/ask M1 2017 (Feb/Jun/Oct), weekday 06:00-14:00 UTC: median "
            "$0.237, p75 $0.259, p95 $0.284 (n=23,040); frozen at $0.30 (> p95, > VT Markets "
            "published $0.18); commission $7/lot RT on 100 oz (Vantage/VT RAW ECN $3.00/side); "
            "slippage $0.05/oz/side"
        ),
        contract_size=100.0,  # 100 troy oz per standard gold lot
    ),
}


def friction_r(symbol: str, entry_price: float, risk_distance: float) -> float:
    """Round-turn friction expressed in R for one trade. Fails closed."""
    model = SYMBOL_FRICTION.get(symbol)
    if model is None:
        raise FrictionUnqualified(f"no frozen friction authority for {symbol}")
    if risk_distance is None or risk_distance <= 0:
        raise FrictionUnqualified(f"non-positive risk distance for {symbol}")
    return model.round_turn_cost(entry_price) / risk_distance


def friction_scenario_r(symbol: str, entry_price: float, risk_distance: float) -> FrictionScenario:
    """EdgeLab friction scenario view of one trade's round-turn cost (in R)."""
    model = SYMBOL_FRICTION.get(symbol)
    if model is None:
        raise FrictionUnqualified(f"no frozen friction authority for {symbol}")
    if model.quote_per_usd:
        commission_price = model.commission_usd_rt * entry_price / model.contract_size
    else:
        commission_price = model.commission_usd_rt / model.contract_size
    return FrictionScenario(
        scenario_id=f"STV2_{symbol}_RT",
        spread_r=model.spread_rt / risk_distance,
        commission_r=commission_price / risk_distance,
        slippage_r=model.slippage_rt / risk_distance,
    )


def stressed_net_r(baseline_net_r: float, baseline_cost_r: float, multiplier: float) -> float:
    """Reuse EdgeLab's frozen normalized-R stress transform."""
    return apply_normalized_r_stress(baseline_net_r, baseline_cost_r, multiplier)
