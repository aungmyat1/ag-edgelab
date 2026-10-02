from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Mapping


@dataclass(frozen=True)
class StabilityResult:
    center: float
    center_expectancy_r: float
    neighborhood_mean_r: float
    positive_fraction: float
    relative_spike: float
    stable: bool


def assess_parameter_stability(
    expectancy_by_value: Mapping[float, float],
    center: float,
    *,
    min_positive_fraction: float = 0.6,
    max_relative_spike: float = 2.0,
) -> StabilityResult:
    """Detect isolated optimum spikes using the supplied coarse neighborhood."""
    if center not in expectancy_by_value:
        raise ValueError("center parameter missing from neighborhood")
    if len(expectancy_by_value) < 3:
        raise ValueError("at least three parameter values are required")

    vals = [float(v) for v in expectancy_by_value.values()]
    center_exp = float(expectancy_by_value[center])
    positive_fraction = sum(v > 0 for v in vals) / len(vals)
    others = [v for k, v in expectancy_by_value.items() if k != center]
    neighbor_mean = mean(others)
    denom = max(abs(neighbor_mean), 1e-12)
    relative_spike = max(0.0, (center_exp - neighbor_mean) / denom)
    stable = positive_fraction >= min_positive_fraction and relative_spike <= max_relative_spike
    return StabilityResult(center, center_exp, neighbor_mean, positive_fraction, relative_spike, stable)
