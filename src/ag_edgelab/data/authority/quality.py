"""Per-symbol, per-year data quality classification.

Nothing in this module repairs anything. It measures, classifies, and
publishes. A suspicious observation keeps its place in the dataset and
gains a label.

MISSING-BAR SEMANTICS
---------------------
"Missing" is meaningless against a naive 24/7 grid: these instruments do
not trade at the weekend, so a 24/7 grid would report ~28% of every year
as missing and drown the real holes. The expected grid is the instrument's
DECLARED venue session contract (see
:mod:`ag_edgelab.data.authority.session`) — Sunday-to-Friday 17:00 New York
for spot FX, 17:00 Chicago for CME metals — expressed in exchange wall
clock and converted to UTC per week, so it tracks venue DST automatically.

Minutes inside the window are EXPECTED. Minutes outside it are NOT
expected, and a bar appearing there is reported as a
``weekend_observation`` anomaly rather than quietly accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence
from ag_edgelab.data.authority.resample import TIMEFRAME_MINUTES, floor_utc
from ag_edgelab.data.authority.schema import CanonicalBar, PRICE_DECIMALS
from ag_edgelab.data.authority.session import SessionContract, contract_for

GAP_CLASSES: tuple[tuple[str, int], ...] = (
    ("MICRO_LE_5MIN", 5),
    ("SHORT_LE_60MIN", 60),
    ("MEDIUM_LE_1DAY", 1440),
    ("LARGE_GT_1DAY", 10 ** 9),
)

#: A session-boundary observation later/earlier than this many minutes from
#: the declared boundary is flagged for inspection.
SESSION_BOUNDARY_TOLERANCE_MIN = 15


def trading_windows(start: datetime, end: datetime,
                    contract: SessionContract) -> list[tuple[datetime, datetime]]:
    """Declared trading windows in ``[start, end)`` as UTC half-open spans."""
    return contract.windows(start, end)


def expected_minutes(windows: Sequence[tuple[datetime, datetime]]) -> int:
    return sum(int((e - s).total_seconds()) // 60 for s, e in windows)


@dataclass
class GapRecord:
    start: datetime
    end: datetime
    missing_minutes: int
    gap_class: str

    def as_dict(self) -> dict:
        return {
            "gap_start_utc": self.start.isoformat().replace("+00:00", "Z"),
            "gap_end_utc": self.end.isoformat().replace("+00:00", "Z"),
            "missing_minutes": self.missing_minutes,
            "class": self.gap_class,
        }


def classify_gap(minutes: int) -> str:
    for name, bound in GAP_CLASSES:
        if minutes <= bound:
            return name
    return GAP_CLASSES[-1][0]      # pragma: no cover - unreachable


@dataclass
class YearQuality:
    symbol: str
    year: int
    timeframe: str
    session_contract: str = ""
    bar_count: int = 0
    expected_bars: int = 0
    missing_bars: int = 0
    duplicate_timestamps: int = 0
    invalid_ohlc: int = 0
    weekend_observations: int = 0
    timezone_anomalies: int = 0
    grid_misalignments: int = 0
    non_monotonic: int = 0
    price_precision_anomalies: int = 0
    session_boundary_anomalies: int = 0
    largest_gap_minutes: int = 0
    largest_gap_start: datetime | None = None
    coverage_pct: float = 0.0
    observed_span_expected_bars: int = 0
    observed_span_coverage_pct: float = 0.0
    first_bar: datetime | None = None
    last_bar: datetime | None = None
    gap_class_counts: dict[str, int] = field(default_factory=dict)
    top_gaps: list[GapRecord] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "year": self.year,
            "timeframe": self.timeframe,
            "session_contract": self.session_contract,
            "bar_count": self.bar_count,
            "expected_bars_in_session": self.expected_bars,
            "missing_bars": self.missing_bars,
            "coverage_pct": round(self.coverage_pct, 6),
            "observed_span_expected_bars": self.observed_span_expected_bars,
            "observed_span_coverage_pct": round(self.observed_span_coverage_pct, 6),
            "coverage_note": (
                "coverage_pct is measured against the FULL calendar year. When the "
                "upstream mirror only publishes part of a year, that number is low "
                "by construction and says nothing about data quality — "
                "observed_span_coverage_pct, measured between the first and last "
                "observation, is the integrity figure."),
            "duplicate_timestamps": self.duplicate_timestamps,
            "invalid_ohlc": self.invalid_ohlc,
            "weekend_observations": self.weekend_observations,
            "timezone_anomalies": self.timezone_anomalies,
            "grid_misalignments": self.grid_misalignments,
            "non_monotonic_timestamps": self.non_monotonic,
            "price_precision_anomalies": self.price_precision_anomalies,
            "session_boundary_anomalies": self.session_boundary_anomalies,
            "largest_gap_minutes": self.largest_gap_minutes,
            "largest_gap_start_utc": (
                None if self.largest_gap_start is None
                else self.largest_gap_start.isoformat().replace("+00:00", "Z")),
            "first_bar_utc": (None if self.first_bar is None
                              else self.first_bar.isoformat().replace("+00:00", "Z")),
            "last_bar_utc": (None if self.last_bar is None
                             else self.last_bar.isoformat().replace("+00:00", "Z")),
            "gap_class_counts": dict(sorted(self.gap_class_counts.items())),
            "largest_gaps": [g.as_dict() for g in self.top_gaps],
            "notes": list(self.notes),
            "repair_policy": "NONE — observations are classified, never altered",
        }


def _decimals_ok(value: float, decimals: int) -> bool:
    scaled = value * (10 ** decimals)
    return abs(scaled - round(scaled)) < 1e-6


def assess_year(
    bars: Sequence[CanonicalBar],
    *,
    symbol: str,
    year: int,
    timeframe: str,
    contract: SessionContract | None = None,
    top_gap_count: int = 10,
) -> YearQuality:
    """Classify one (symbol, year, timeframe) slice. Never mutates input."""
    contract = contract or contract_for(symbol)
    report = YearQuality(symbol=symbol, year=year, timeframe=timeframe,
                         session_contract=contract.contract_id)
    minutes = TIMEFRAME_MINUTES[timeframe]
    step = timedelta(minutes=minutes)
    decimals = PRICE_DECIMALS.get(symbol)

    year_start = datetime(year, 1, 1, tzinfo=timezone.utc)
    year_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    windows = trading_windows(year_start, year_end, contract)
    report.expected_bars = expected_minutes(windows) // minutes

    if not bars:
        report.notes.append("EMPTY_SLICE")
        return report

    report.bar_count = len(bars)
    report.first_bar = bars[0].timestamp_utc
    report.last_bar = bars[-1].timestamp_utc

    seen: set[datetime] = set()
    previous: datetime | None = None
    in_session: list[datetime] = []
    window_index = 0

    for bar in bars:
        ts = bar.timestamp_utc
        if ts.tzinfo is None or ts.utcoffset().total_seconds() != 0:
            report.timezone_anomalies += 1
        if ts != floor_utc(ts, minutes):
            report.grid_misalignments += 1
        if ts in seen:
            report.duplicate_timestamps += 1
        seen.add(ts)
        if previous is not None and ts < previous:
            report.non_monotonic += 1
        previous = ts
        if bar.high < max(bar.open, bar.close, bar.low) or \
           bar.low > min(bar.open, bar.close, bar.high):
            report.invalid_ohlc += 1
        if decimals is not None and not all(
                _decimals_ok(v, decimals)
                for v in (bar.open, bar.high, bar.low, bar.close)):
            report.price_precision_anomalies += 1

        while window_index < len(windows) and windows[window_index][1] <= ts:
            window_index += 1
        if window_index < len(windows) and windows[window_index][0] <= ts < windows[window_index][1]:
            in_session.append(ts)
        else:
            report.weekend_observations += 1

    # gaps strictly inside each trading window
    gaps: list[GapRecord] = []
    by_window: dict[int, list[datetime]] = {}
    idx = 0
    for ts in in_session:
        while idx < len(windows) and windows[idx][1] <= ts:
            idx += 1
        by_window.setdefault(idx, []).append(ts)

    for widx, stamps in by_window.items():
        w_start, w_end = windows[widx]
        cursor = floor_utc(w_start, minutes)
        if cursor < w_start:
            cursor += step
        for ts in stamps:
            if ts > cursor:
                missing = int((ts - cursor).total_seconds()) // (minutes * 60)
                if missing > 0:
                    gaps.append(GapRecord(cursor, ts, missing * minutes,
                                          classify_gap(missing * minutes)))
            cursor = ts + step
        if cursor < w_end:
            missing = int((w_end - cursor).total_seconds()) // (minutes * 60)
            if missing > 0:
                gaps.append(GapRecord(cursor, w_end, missing * minutes,
                                      classify_gap(missing * minutes)))

    report.missing_bars = max(report.expected_bars - len(in_session), 0)
    report.coverage_pct = (
        100.0 * len(in_session) / report.expected_bars if report.expected_bars else 0.0)

    # Coverage measured only between the first and last observation, so a
    # partially published year is not mistaken for a defective one.
    span_windows = trading_windows(report.first_bar,
                                   report.last_bar + timedelta(minutes=minutes),
                                   contract)
    report.observed_span_expected_bars = expected_minutes(span_windows) // minutes
    in_span = [t for t in in_session
               if report.first_bar <= t <= report.last_bar]
    report.observed_span_coverage_pct = (
        100.0 * len(in_span) / report.observed_span_expected_bars
        if report.observed_span_expected_bars else 0.0)
    for gap in gaps:
        report.gap_class_counts[gap.gap_class] = \
            report.gap_class_counts.get(gap.gap_class, 0) + 1
    if gaps:
        largest = max(gaps, key=lambda g: g.missing_minutes)
        report.largest_gap_minutes = largest.missing_minutes
        report.largest_gap_start = largest.start
        report.top_gaps = sorted(gaps, key=lambda g: -g.missing_minutes)[:top_gap_count]

    # session-boundary behaviour: how promptly does each week start/end?
    for w_start, w_end in windows:
        stamps = [t for t in in_session if w_start <= t < w_end]
        if not stamps:
            report.session_boundary_anomalies += 1
            continue
        late_open = int((stamps[0] - w_start).total_seconds()) // 60
        early_close = int((w_end - (stamps[-1] + step)).total_seconds()) // 60
        if late_open > SESSION_BOUNDARY_TOLERANCE_MIN or \
           early_close > SESSION_BOUNDARY_TOLERANCE_MIN:
            report.session_boundary_anomalies += 1
    return report


def aggregate_quality(reports: Iterable[YearQuality]) -> dict:
    rows = list(reports)
    total_bars = sum(r.bar_count for r in rows)
    total_expected = sum(r.expected_bars for r in rows)
    return {
        "slices": len(rows),
        "total_bars": total_bars,
        "total_expected_bars_in_session": total_expected,
        "aggregate_coverage_pct": round(
            100.0 * (total_bars - sum(r.weekend_observations for r in rows))
            / total_expected, 6) if total_expected else 0.0,
        "total_duplicate_timestamps": sum(r.duplicate_timestamps for r in rows),
        "total_invalid_ohlc": sum(r.invalid_ohlc for r in rows),
        "total_weekend_observations": sum(r.weekend_observations for r in rows),
        "total_timezone_anomalies": sum(r.timezone_anomalies for r in rows),
        "total_grid_misalignments": sum(r.grid_misalignments for r in rows),
        "total_non_monotonic": sum(r.non_monotonic for r in rows),
        "total_price_precision_anomalies": sum(r.price_precision_anomalies for r in rows),
        "total_session_boundary_anomalies": sum(r.session_boundary_anomalies for r in rows),
        "worst_gap_minutes": max((r.largest_gap_minutes for r in rows), default=0),
    }
