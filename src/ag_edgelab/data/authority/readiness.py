"""Structural readiness assessment — DATA properties only.

Section 10 of DATA_AUTHORITY_R1 asks whether the dataset is structurally
sufficient for walk-forward, regime and stability work. It explicitly does
NOT ask whether anything is profitable, and this module cannot answer that
question: it never sees a strategy, a rule, a signal, a parameter or a
trade. Every number here is a property of the price series itself —
how many bars, how complete, how volatile, how trending.

The returned flags are DATA readiness flags. ``REGIME_DATA_READY = YES``
means "the dataset contains distinguishable volatility and trend regimes
to test against". It does not mean any edge exists in any of them.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Sequence

from ag_edgelab.data.authority.schema import CanonicalBar

#: A walk-forward fold is structurally usable only with at least this many
#: observations on each side. Declared up front, not tuned to the result.
MIN_TRAIN_BARS = 2000
MIN_TEST_BARS = 400
MIN_FOLDS_FOR_READY = 8
MIN_YEARS_FOR_MULTIYEAR = 3
MIN_COVERAGE_PCT_FOR_READY = 90.0

#: Volatility regimes are "distinguishable" when the annual realized
#: volatility spread is at least this ratio between the calmest and most
#: volatile year.
MIN_VOL_DISPERSION_RATIO = 1.5


@dataclass
class WalkForwardFold:
    index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train_bars: int
    test_bars: int

    @property
    def usable(self) -> bool:
        return self.train_bars >= MIN_TRAIN_BARS and self.test_bars >= MIN_TEST_BARS

    def as_dict(self) -> dict:
        def iso(ts: datetime) -> str:
            return ts.isoformat().replace("+00:00", "Z")
        return {
            "fold": self.index,
            "train_window_utc": f"[{iso(self.train_start)}, {iso(self.train_end)})",
            "test_window_utc": f"[{iso(self.test_start)}, {iso(self.test_end)})",
            "train_bars": self.train_bars,
            "test_bars": self.test_bars,
            "usable": self.usable,
        }


def _add_months(ts: datetime, months: int) -> datetime:
    month_index = ts.month - 1 + months
    year = ts.year + month_index // 12
    month = month_index % 12 + 1
    return ts.replace(year=year, month=month)


def build_folds(
    timestamps: Sequence[datetime],
    *,
    start: datetime,
    end: datetime,
    train_months: int = 12,
    test_months: int = 3,
    step_months: int = 3,
) -> list[WalkForwardFold]:
    """Enumerate rolling folds and count observations in each.

    Purely combinatorial: it partitions time and counts bars. It does not
    fit, score, select or evaluate anything.
    """
    stamps = sorted(timestamps)
    folds: list[WalkForwardFold] = []
    index = 0
    train_start = start
    while True:
        train_end = _add_months(train_start, train_months)
        test_end = _add_months(train_end, test_months)
        if test_end > end:
            break
        index += 1
        folds.append(WalkForwardFold(
            index=index,
            train_start=train_start, train_end=train_end,
            test_start=train_end, test_end=test_end,
            train_bars=sum(1 for t in stamps if train_start <= t < train_end),
            test_bars=sum(1 for t in stamps if train_end <= t < test_end),
        ))
        train_start = _add_months(train_start, step_months)
    return folds


# ---------------------------------------------------------------------------
# regime characterisation
# ---------------------------------------------------------------------------

@dataclass
class YearRegime:
    symbol: str
    year: int
    bars: int
    realized_vol_annualized_pct: float
    efficiency_ratio: float
    max_drawdown_pct: float
    net_change_pct: float

    @property
    def trend_label(self) -> str:
        # Efficiency ratio = |net move| / total path length. High = trending,
        # low = ranging. Thresholds are declared, not fitted.
        if self.efficiency_ratio >= 0.30:
            return "TRENDING"
        if self.efficiency_ratio <= 0.10:
            return "RANGING"
        return "MIXED"

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "year": self.year,
            "d1_bars": self.bars,
            "realized_volatility_annualized_pct": round(
                self.realized_vol_annualized_pct, 4),
            "efficiency_ratio": round(self.efficiency_ratio, 6),
            "trend_label": self.trend_label,
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "net_change_pct": round(self.net_change_pct, 4),
        }


def characterise_year(bars: Sequence[CanonicalBar], *, symbol: str,
                      year: int) -> YearRegime | None:
    """Describe one year of D1 bars. No strategy, no parameters, no fitting."""
    closes = [b.close for b in bars]
    if len(closes) < 30:
        return None
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    vol = statistics.pstdev(returns) * math.sqrt(252) * 100.0 if len(returns) > 1 else 0.0
    path = sum(abs(b - a) for a, b in zip(closes, closes[1:]))
    net = abs(closes[-1] - closes[0])
    peak = closes[0]
    max_dd = 0.0
    for close in closes:
        peak = max(peak, close)
        max_dd = max(max_dd, (peak - close) / peak if peak else 0.0)
    return YearRegime(
        symbol=symbol, year=year, bars=len(closes),
        realized_vol_annualized_pct=vol,
        efficiency_ratio=(net / path) if path else 0.0,
        max_drawdown_pct=max_dd * 100.0,
        net_change_pct=100.0 * (closes[-1] - closes[0]) / closes[0],
    )


def session_distribution(timestamps: Sequence[datetime]) -> dict[str, int]:
    """Bars per UTC session bucket — a coverage statistic, not a signal."""
    buckets = {"ASIA_00_07": 0, "LONDON_07_12": 0, "LONDON_NY_12_16": 0,
               "NY_16_21": 0, "LATE_21_24": 0}
    for ts in timestamps:
        hour = ts.astimezone(timezone.utc).hour
        if hour < 7:
            buckets["ASIA_00_07"] += 1
        elif hour < 12:
            buckets["LONDON_07_12"] += 1
        elif hour < 16:
            buckets["LONDON_NY_12_16"] += 1
        elif hour < 21:
            buckets["NY_16_21"] += 1
        else:
            buckets["LATE_21_24"] += 1
    return buckets


@dataclass
class ReadinessVerdict:
    multiyear: str
    walk_forward: str
    regime: str
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "MULTIYEAR_FX_DATA_READY": self.multiyear,
            "WALK_FORWARD_DATA_READY": self.walk_forward,
            "REGIME_DATA_READY": self.regime,
            "interpretation": (
                "These are DATA readiness flags. They state that the dataset is "
                "structurally capable of supporting the named analysis. They are "
                "NOT edge claims and imply nothing about profitability."
            ),
            "reasons": list(self.reasons),
        }


def assess(
    *,
    years: Sequence[int],
    symbols: Sequence[str],
    min_coverage_pct: float,
    usable_folds: int,
    vol_by_year: dict[str, list[float]],
) -> ReadinessVerdict:
    reasons: list[str] = []

    multiyear = "YES" if len(years) >= MIN_YEARS_FOR_MULTIYEAR else "NO"
    reasons.append(
        f"{len(years)} calendar years touched x {len(symbols)} symbols "
        f"(threshold {MIN_YEARS_FOR_MULTIYEAR} years) -> MULTIYEAR={multiyear}. "
        "Not every year is complete for every symbol: the upstream mirror is "
        "partial at both ends and no data was fabricated to even it out — see "
        "COVERAGE.per_symbol_span and COVERAGE.common_window.")

    if min_coverage_pct < MIN_COVERAGE_PCT_FOR_READY:
        walk_forward = "NO"
        reasons.append(
            f"worst in-session coverage {min_coverage_pct:.2f}% is below the "
            f"{MIN_COVERAGE_PCT_FOR_READY}% floor -> WALK_FORWARD=NO")
    elif usable_folds < MIN_FOLDS_FOR_READY:
        walk_forward = "NO"
        reasons.append(
            f"only {usable_folds} structurally usable folds (need "
            f"{MIN_FOLDS_FOR_READY}) -> WALK_FORWARD=NO")
    else:
        walk_forward = "YES"
        reasons.append(
            f"{usable_folds} usable rolling folds at >= {MIN_TRAIN_BARS} train / "
            f">= {MIN_TEST_BARS} test bars, worst coverage "
            f"{min_coverage_pct:.2f}% -> WALK_FORWARD=YES")

    dispersions = []
    for symbol, vols in sorted(vol_by_year.items()):
        clean = [v for v in vols if v > 0]
        if len(clean) >= 2:
            dispersions.append((symbol, max(clean) / min(clean)))
    if dispersions and all(ratio >= MIN_VOL_DISPERSION_RATIO
                           for _, ratio in dispersions):
        regime = "YES"
        reasons.append(
            "annual realized-volatility dispersion (max/min) is "
            + ", ".join(f"{s}={r:.2f}x" for s, r in dispersions)
            + f"; all exceed {MIN_VOL_DISPERSION_RATIO}x -> REGIME=YES")
    elif dispersions:
        regime = "PARTIAL"
        weak = [s for s, r in dispersions if r < MIN_VOL_DISPERSION_RATIO]
        reasons.append(
            f"volatility dispersion below {MIN_VOL_DISPERSION_RATIO}x for {weak} "
            "-> REGIME=PARTIAL")
    else:
        regime = "NO"
        reasons.append("insufficient annual volatility samples -> REGIME=NO")

    return ReadinessVerdict(multiyear, walk_forward, regime, reasons)
