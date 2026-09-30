from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class BootstrapInterval:
    estimate: float | None
    low: float | None
    high: float | None
    samples: int
    seed: int


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("empty quantile")
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    weight = pos - lo
    return sorted_values[lo] * (1 - weight) + sorted_values[hi] * weight


def bootstrap_expectancy_ci(
    trade_rs: Sequence[float], *, samples: int = 5000, seed: int = 0, confidence: float = 0.95
) -> BootstrapInterval:
    values = tuple(float(x) for x in trade_rs)
    if not values:
        return BootstrapInterval(None, None, None, samples, seed)
    if samples <= 0:
        raise ValueError("samples must be positive")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")

    rng = random.Random(seed)
    n = len(values)
    boot = []
    for _ in range(samples):
        draw = [values[rng.randrange(n)] for _ in range(n)]
        boot.append(sum(draw) / n)
    boot.sort()
    alpha = (1.0 - confidence) / 2.0
    return BootstrapInterval(
        estimate=sum(values) / n,
        low=_quantile(boot, alpha),
        high=_quantile(boot, 1.0 - alpha),
        samples=samples,
        seed=seed,
    )
