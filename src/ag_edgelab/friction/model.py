from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class FrictionScenario:
    """Execution cost expressed in R so it is account-size independent."""

    scenario_id: str
    spread_r: float = 0.0
    commission_r: float = 0.0
    slippage_r: float = 0.0
    swap_r: float = 0.0

    @property
    def total_cost_r(self) -> float:
        return self.spread_r + self.commission_r + self.slippage_r + self.swap_r


def apply_friction(gross_r: float, scenario: FrictionScenario) -> float:
    return gross_r - scenario.total_cost_r


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
