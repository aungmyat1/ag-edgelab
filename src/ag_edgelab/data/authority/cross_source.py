"""Cross-source diagnostics — measure disagreement, never reconcile it.

Two independent authorities covering the same instrument and window will
not agree exactly, and they should not be made to. Different liquidity
pools, different aggregation rules and different inclusion thresholds all
produce legitimate differences. This module quantifies them.

EXPLICIT NON-GOALS
------------------
* It does not adjust, blend, patch, or re-base either source.
* It does not pick a winner.
* It does not change any dataset hash.

Its output is evidence for a human decision, plus one automatic guard: if
the two sources disagree about the PRICE LEVEL by orders of magnitude, a
scale/convention error exists somewhere and the comparison reports
``SCALE_DISAGREEMENT`` so the pipeline can fail closed instead of
publishing a mis-scaled dataset.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

from ag_edgelab.data.authority.schema import CanonicalBar, PRICE_DECIMALS

AGREEMENT = "AGREEMENT"
MATERIAL_DIFFERENCE = "MATERIAL_DIFFERENCE"
SCALE_DISAGREEMENT = "SCALE_DISAGREEMENT"
NO_OVERLAP = "NO_OVERLAP"

#: Materiality is judged in RELATIVE terms, not ticks, so the same rule is
#: meaningful for a 1.05 EURUSD tick (1e-5) and a 1250.00 XAUUSD tick
#: (1e-3). One basis point of price is the declared advisory threshold.
#: Tick statistics are still reported, they are just not the classifier.
MATERIAL_RELATIVE_THRESHOLD = 1e-4

#: A median relative difference above this is not a venue difference, it is
#: a scale or convention error.
SCALE_DISAGREEMENT_RELATIVE = 0.05


@dataclass
class CrossSourceComparison:
    symbol: str
    timeframe: str
    source_a: str
    source_b: str
    window_start: datetime | None
    window_end: datetime | None
    bars_a: int
    bars_b: int
    common_timestamps: int
    only_in_a: int
    only_in_b: int
    timestamp_agreement_pct: float
    median_abs_close_diff_ticks: float | None
    p95_abs_close_diff_ticks: float | None
    max_abs_close_diff_ticks: float | None
    median_relative_close_diff: float | None
    median_abs_high_diff_ticks: float | None
    median_abs_low_diff_ticks: float | None
    large_outliers: int
    price_decimals_a: int
    price_decimals_b: int
    verdict: str
    notes: list[str] = field(default_factory=list)
    outlier_examples: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "source_a": self.source_a,
            "source_b": self.source_b,
            "window_start_utc": (None if self.window_start is None
                                 else self.window_start.isoformat().replace("+00:00", "Z")),
            "window_end_utc": (None if self.window_end is None
                               else self.window_end.isoformat().replace("+00:00", "Z")),
            "bars_source_a": self.bars_a,
            "bars_source_b": self.bars_b,
            "common_timestamps": self.common_timestamps,
            "timestamps_only_in_a": self.only_in_a,
            "timestamps_only_in_b": self.only_in_b,
            "timestamp_agreement_pct": round(self.timestamp_agreement_pct, 4),
            "median_abs_close_diff_ticks": self.median_abs_close_diff_ticks,
            "p95_abs_close_diff_ticks": self.p95_abs_close_diff_ticks,
            "max_abs_close_diff_ticks": self.max_abs_close_diff_ticks,
            "median_relative_close_diff": self.median_relative_close_diff,
            "median_abs_high_diff_ticks": self.median_abs_high_diff_ticks,
            "median_abs_low_diff_ticks": self.median_abs_low_diff_ticks,
            "large_outliers": self.large_outliers,
            "price_precision_a_decimals": self.price_decimals_a,
            "price_precision_b_decimals": self.price_decimals_b,
            "verdict": self.verdict,
            "notes": list(self.notes),
            "outlier_examples": list(self.outlier_examples),
            "action_taken": "NONE — diagnostic only; neither source was altered",
        }


def _percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[index]


def compare(
    a: Sequence[CanonicalBar],
    b: Sequence[CanonicalBar],
    *,
    symbol: str,
    timeframe: str,
    source_a: str,
    source_b: str,
    outlier_tick_threshold: float = 100.0,
    max_examples: int = 10,
) -> CrossSourceComparison:
    """Compare two canonical series on their overlapping timestamps."""
    decimals = PRICE_DECIMALS.get(symbol, 5)
    tick = 10.0 ** (-decimals)

    map_a = {bar.timestamp_utc: bar for bar in a}
    map_b = {bar.timestamp_utc: bar for bar in b}
    if not map_a or not map_b:
        return CrossSourceComparison(
            symbol, timeframe, source_a, source_b, None, None, len(a), len(b),
            0, len(a), len(b), 0.0, None, None, None, None, None, None, 0,
            decimals, decimals, NO_OVERLAP,
            notes=["one side is empty — no comparable observations"])

    lo = max(min(map_a), min(map_b))
    hi = min(max(map_a), max(map_b))
    if lo > hi:
        return CrossSourceComparison(
            symbol, timeframe, source_a, source_b, None, None, len(a), len(b),
            0, len(a), len(b), 0.0, None, None, None, None, None, None, 0,
            decimals, decimals, NO_OVERLAP,
            notes=["the two series do not overlap in time"])

    win_a = {t: bar for t, bar in map_a.items() if lo <= t <= hi}
    win_b = {t: bar for t, bar in map_b.items() if lo <= t <= hi}
    common = sorted(set(win_a) & set(win_b))
    union = len(set(win_a) | set(win_b))

    close_diffs: list[float] = []
    rel_diffs: list[float] = []
    high_diffs: list[float] = []
    low_diffs: list[float] = []
    outliers: list[dict] = []

    for ts in common:
        bar_a, bar_b = win_a[ts], win_b[ts]
        dc = abs(bar_a.close - bar_b.close)
        close_diffs.append(dc / tick)
        rel_diffs.append(dc / bar_b.close if bar_b.close else 0.0)
        high_diffs.append(abs(bar_a.high - bar_b.high) / tick)
        low_diffs.append(abs(bar_a.low - bar_b.low) / tick)
        if dc / tick > outlier_tick_threshold and len(outliers) < max_examples:
            outliers.append({
                "timestamp_utc": ts.isoformat().replace("+00:00", "Z"),
                "close_a": bar_a.close, "close_b": bar_b.close,
                "diff_ticks": round(dc / tick, 3),
            })

    median_close = statistics.median(close_diffs) if close_diffs else None
    median_rel = statistics.median(rel_diffs) if rel_diffs else None
    large = sum(1 for d in close_diffs if d > outlier_tick_threshold)

    notes: list[str] = []
    if median_rel is not None and median_rel > SCALE_DISAGREEMENT_RELATIVE:
        verdict = SCALE_DISAGREEMENT
        notes.append(
            f"median relative close difference {median_rel:.4f} exceeds "
            f"{SCALE_DISAGREEMENT_RELATIVE}: this is a scale or quoting-convention "
            "error, not a venue difference — STATUS=BLOCKED_DATA_AUTHORITY")
    elif median_rel is not None and median_rel > MATERIAL_RELATIVE_THRESHOLD:
        verdict = MATERIAL_DIFFERENCE
        notes.append(
            f"median relative close difference {median_rel:.2e} exceeds the "
            f"{MATERIAL_RELATIVE_THRESHOLD:.0e} ({MATERIAL_RELATIVE_THRESHOLD*1e4:.0f} "
            "basis point) advisory threshold; recorded, not reconciled")
    else:
        verdict = AGREEMENT
        if median_rel is not None:
            notes.append(
                f"the two independent sources agree to {median_rel:.2e} relative "
                f"({median_close:.1f} ticks median). Agreement at this level also "
                "independently corroborates the price scale and the UTC timezone "
                "frame: a wrong decimal scale or a one-hour clock error could not "
                "produce it.")

    if len(common) and len(common) < union:
        notes.append(
            f"{union - len(common)} timestamps exist in exactly one source; "
            "different inclusion rules are expected and are NOT errors")

    return CrossSourceComparison(
        symbol=symbol, timeframe=timeframe, source_a=source_a, source_b=source_b,
        window_start=lo, window_end=hi, bars_a=len(win_a), bars_b=len(win_b),
        common_timestamps=len(common),
        only_in_a=len(set(win_a) - set(win_b)),
        only_in_b=len(set(win_b) - set(win_a)),
        timestamp_agreement_pct=100.0 * len(common) / union if union else 0.0,
        median_abs_close_diff_ticks=(None if median_close is None
                                     else round(median_close, 4)),
        p95_abs_close_diff_ticks=round(_percentile(close_diffs, 0.95), 4) if close_diffs else None,
        max_abs_close_diff_ticks=round(max(close_diffs), 4) if close_diffs else None,
        median_relative_close_diff=(None if median_rel is None else round(median_rel, 8)),
        median_abs_high_diff_ticks=(round(statistics.median(high_diffs), 4)
                                    if high_diffs else None),
        median_abs_low_diff_ticks=(round(statistics.median(low_diffs), 4)
                                   if low_diffs else None),
        large_outliers=large,
        price_decimals_a=decimals, price_decimals_b=decimals,
        verdict=verdict, notes=notes, outlier_examples=outliers,
    )
