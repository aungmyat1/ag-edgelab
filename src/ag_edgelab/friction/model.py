from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import inspect
from typing import Iterable, Sequence


class FundingAuthority(StrEnum):
    """Provenance of funding-rate observations for a perpetual dataset."""

    MISSING = "MISSING"
    UNDECLARED = "UNDECLARED"
    BYBIT_PUBLIC_HISTORY = "BYBIT_PUBLIC_HISTORY"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"


class NetEconomicQualification(StrEnum):
    PASS = "PASS"
    NOT_ECONOMICALLY_QUALIFIED = "NOT_ECONOMICALLY_QUALIFIED"


@dataclass(frozen=True)
class FrictionScenario:
    """Execution cost expressed in R so it is account-size independent.

    `funding_r` extends the contract for perpetual carrying cost. It defaults
    to 0.0 ONLY for backwards compatibility of pre-perpetual (FX/CFD) usage;
    a scenario describing a perpetual trade must still declare an explicit
    `funding_provenance` — "UNDECLARED" means no real-world zero was assumed,
    it means funding was not modelled and net economics are not qualified.
    """

    scenario_id: str
    spread_r: float = 0.0
    commission_r: float = 0.0
    slippage_r: float = 0.0
    swap_r: float = 0.0
    funding_r: float = 0.0
    funding_provenance: str = "UNDECLARED"

    @property
    def funding_declared(self) -> bool:
        return self.funding_provenance not in ("UNDECLARED", "MISSING")

    @property
    def total_cost_r(self) -> float:
        return self.spread_r + self.commission_r + self.slippage_r + self.swap_r + self.funding_r


@dataclass(frozen=True)
class FundingEvent:
    """One funding settlement: rate applied to open positions at `timestamp`."""

    timestamp: datetime
    rate: float  # signed; positive rate charges longs and pays shorts


@dataclass(frozen=True)
class FundingSchedule:
    """Authoritative (or explicitly synthetic) funding history plus provenance."""

    authority: FundingAuthority
    events: tuple[FundingEvent, ...]
    source: str = ""
    source_sha256: str = ""

    def events_between(self, entry_time: datetime, exit_time: datetime) -> tuple[FundingEvent, ...]:
        # Funding accrues for settlements strictly after entry and up to and
        # including exit — a position opened at or after settlement ts never
        # pays ts; a position still open at settlement ts pays it.
        return tuple(e for e in self.events if entry_time < e.timestamp <= exit_time)


def funding_cost_r(
    *,
    entry_time: datetime,
    exit_time: datetime,
    side: str,
    entry_price: float,
    stop_price: float,
    schedule: FundingSchedule,
    conservative_absolute: bool = False,
) -> float:
    """Funding cost in R for a trade spanning settlement timestamps.

    Unit-R accounting: notional/risk = entry / |entry - stop|, so each
    settlement contributes rate * entry / |entry - stop| R, signed by side.
    With conservative_absolute=True every settlement is charged at |rate|
    (verification-style stress: funding can never manufacture edge).
    """
    risk = abs(entry_price - stop_price)
    if risk <= 0:
        raise ValueError("entry and stop imply zero risk")
    if schedule.authority in (FundingAuthority.MISSING, FundingAuthority.UNDECLARED):
        raise ValueError("funding authority missing: net economics must not be computed")
    direction = 1.0 if side == "LONG" else -1.0
    cost = 0.0
    for event in schedule.events_between(entry_time, exit_time):
        rate = abs(event.rate) if conservative_absolute else direction * event.rate
        cost += rate * entry_price / risk
    return cost


def assess_net_economic_qualification(
    *,
    instrument_is_perpetual: bool,
    funding_authority: FundingAuthority,
    dataset_is_authoritative: bool,
) -> NetEconomicQualification:
    """NET_ECONOMIC_QUALIFICATION gate (development scope, honest labelling).

    PASS requires an authoritative dataset and, for perpetuals, an
    authoritative funding history. Anything else yields at most a
    STRUCTURAL_GROSS_REPLAY qualification, never a net pass.
    """
    if not dataset_is_authoritative:
        return NetEconomicQualification.NOT_ECONOMICALLY_QUALIFIED
    if instrument_is_perpetual and funding_authority not in (FundingAuthority.BYBIT_PUBLIC_HISTORY,):
        return NetEconomicQualification.NOT_ECONOMICALLY_QUALIFIED
    return NetEconomicQualification.PASS


def apply_friction(gross_r: float, scenario: FrictionScenario) -> float:
    return gross_r - scenario.total_cost_r


def apply_normalized_r_stress(baseline_net_r: float, baseline_cost_r: float, multiplier: float) -> float:
    """Scale baseline costs while preserving the baseline net result at 1.0x."""
    return baseline_net_r - (multiplier - 1.0) * baseline_cost_r


def normalized_r_stress_implementation_sha256() -> str:
    """Hash the exact deterministic transform frozen by each variant."""
    return hashlib.sha256(inspect.getsource(apply_normalized_r_stress).encode("utf-8")).hexdigest()


def stress_curve(gross_rs: Iterable[float], scenarios: Iterable[FrictionScenario]) -> dict[str, dict[str, float | int | None]]:
    values = [float(r) for r in gross_rs]
    out: dict[str, dict[str, float | int | None]] = {}
    for scenario in scenarios:
        net = [apply_friction(r, scenario) for r in values]
        wins = [r for r in net if r > 0]
        losses = [r for r in net if r < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        out[scenario.scenario_id] = {
            "trades": len(net),
            "total_cost_r_per_trade": scenario.total_cost_r,
            "expectancy_r": (sum(net) / len(net)) if net else None,
            "profit_factor": (gross_profit / gross_loss) if gross_loss else (float("inf") if gross_profit > 0 else None),
        }
    return out


def total_funding_r(trade_windows: Sequence[tuple[datetime, datetime, str, float, float]], schedule: FundingSchedule) -> float:
    """Sum funding cost across (entry_time, exit_time, side, entry, stop) rows."""
    return sum(
        funding_cost_r(entry_time=e, exit_time=x, side=s, entry_price=ep, stop_price=sp, schedule=schedule)
        for e, x, s, ep, sp in trade_windows
    )
