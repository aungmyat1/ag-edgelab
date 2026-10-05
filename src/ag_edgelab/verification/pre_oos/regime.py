"""Deterministic regime classification using only completed past information.

The repository already owns a trend-state authority
(:func:`ag_edgelab.verification.regimes.classify_market_state`, close>open
=> TREND) and it is reused verbatim where market bars are available.

What it does not own is a volatility dimension, so this module adds a
minimal preregistered one. The construction is deliberately boring: for
each observation, look at the trailing window of the *same symbol's*
strictly earlier observations, take their terciles, and place the
current value. Nothing from the present or future observation enters its
own classification.

WHY TRAILING TERCILES
---------------------
A fixed absolute cut (e.g. "HIGH if range > 50 pips") is wrong across
four instruments whose scales differ by orders of magnitude, and wrong
across seven years in which volatility regimes shifted. Terciles of the
instrument's own recent past are scale-free and self-calibrating.

The cost is that the first ``min_history`` observations of each symbol
are UNCLASSIFIED. They are reported as such rather than being back-filled
from later data, because back-filling is exactly the leak this module
exists to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ag_edgelab.verification.regimes import (
    classify_market_state, regime_classifier_implementation_sha256,
)

REGIME_CLASSIFIER_ID = "PRE_OOS_CAUSAL_REGIME_V1"

#: Trailing same-symbol observations consulted for the terciles.
TRAILING_WINDOW = 100

#: Below this many priors the cell is UNCLASSIFIED rather than guessed.
MIN_HISTORY = 30


class Volatility(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNCLASSIFIED = "UNCLASSIFIED"


class TrendState(StrEnum):
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class FutureLeakDetected(RuntimeError):
    """A classifier was handed information it could not have had."""


@dataclass(frozen=True)
class RegimeLabel:
    volatility: Volatility
    trend_state: TrendState
    history_used: int

    @property
    def cell(self) -> str:
        return f"{self.volatility}/{self.trend_state}"

    @property
    def is_classified(self) -> bool:
        return self.volatility is not Volatility.UNCLASSIFIED


def _terciles(values: list[float]) -> tuple[float, float]:
    ordered = sorted(values)
    n = len(ordered)
    lo = ordered[max(0, min(n - 1, int(n / 3)))]
    hi = ordered[max(0, min(n - 1, int(2 * n / 3)))]
    return lo, hi


def classify_volatility(
    value: float | None,
    prior_values: list[float],
    *,
    min_history: int = MIN_HISTORY,
    trailing_window: int = TRAILING_WINDOW,
) -> tuple[Volatility, int]:
    """Place ``value`` against the terciles of strictly earlier values."""
    if value is None:
        return Volatility.UNCLASSIFIED, len(prior_values)
    window = prior_values[-trailing_window:]
    if len(window) < min_history:
        return Volatility.UNCLASSIFIED, len(window)
    lo, hi = _terciles(window)
    if value <= lo:
        return Volatility.LOW, len(window)
    if value >= hi:
        return Volatility.HIGH, len(window)
    return Volatility.MEDIUM, len(window)


def classify_trend(bar) -> TrendState:
    """Reuse the repository's frozen trend authority."""
    if bar is None:
        return TrendState.NOT_AVAILABLE
    return (TrendState.TRENDING
            if classify_market_state(bar) == "TREND" else TrendState.RANGING)


def label_sequence(
    values: list[float | None],
    *,
    symbols: list[str],
    bars: list[object] | None = None,
    min_history: int = MIN_HISTORY,
    trailing_window: int = TRAILING_WINDOW,
) -> list[RegimeLabel]:
    """Label a chronologically ordered sequence, causally.

    ``values`` is the volatility proxy (e.g. stop distance) and must be
    ordered by time. Each element is classified against the preceding
    elements of the same symbol only.
    """
    if len(values) != len(symbols):
        raise ValueError("values and symbols must be the same length")
    if bars is not None and len(bars) != len(values):
        raise ValueError("bars must align with values")

    history: dict[str, list[float]] = {}
    labels: list[RegimeLabel] = []
    for i, (value, symbol) in enumerate(zip(values, symbols)):
        priors = history.setdefault(symbol, [])
        # Classify BEFORE appending: the observation never sees itself.
        vol, used = classify_volatility(
            value, priors, min_history=min_history,
            trailing_window=trailing_window)
        trend = classify_trend(bars[i]) if bars is not None else \
            TrendState.NOT_AVAILABLE
        labels.append(RegimeLabel(vol, trend, used))
        if value is not None:
            priors.append(value)
    return labels


def classifier_fingerprint() -> dict:
    """Identity of the classification rules, for the artifact record."""
    return {
        "classifier_id": REGIME_CLASSIFIER_ID,
        "trailing_window": TRAILING_WINDOW,
        "min_history": MIN_HISTORY,
        "volatility_rule": ("terciles of the trailing same-symbol window of "
                            "STRICTLY EARLIER observations; the observation "
                            "never enters its own classification"),
        "trend_rule": "ag_edgelab.verification.regimes.classify_market_state",
        "trend_rule_sha256": regime_classifier_implementation_sha256(),
        "uses_future_data": False,
        "unclassified_policy": ("the first MIN_HISTORY observations per symbol "
                                "are UNCLASSIFIED and reported as such; they "
                                "are never back-filled from later data"),
    }
