"""Data quality gate for authoritative bar datasets.

Hard violations -> FAIL. Documented structural gaps (missing bars on a 24/7
crypto grid) -> PASS_WITH_DOCUMENTED_GAPS, always enumerated, never hidden by
forward filling. This module never fabricates bars.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.derive import TIMEFRAME_MINUTES, floor_open


class QualityVerdict(StrEnum):
    PASS = "PASS"
    PASS_WITH_DOCUMENTED_GAPS = "PASS_WITH_DOCUMENTED_GAPS"
    FAIL = "FAIL"


class GapRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    gap_start: datetime
    gap_end: datetime
    missing_slots: int


class QualityIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    code: str
    detail: str


class QualityReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: QualityVerdict
    timeframe: str
    rows: int
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    expected_slots: int
    missing_slots: int
    gap_records: tuple[GapRecord, ...] = ()
    issues: tuple[QualityIssue, ...] = ()
    forward_filled: bool = False
    identity: dict[str, str] = Field(default_factory=dict)

    @property
    def gap_audit(self) -> str:
        if not self.gap_records:
            return "NO_GAPS"
        total = sum(g.missing_slots for g in self.gap_records)
        return f"{len(self.gap_records)} gaps / {total} missing slots"


MAX_GAP_FRACTION_FOR_PASS_WITH_GAPS = 0.05
MAX_SINGLE_GAP_SLOTS_FOR_PASS_WITH_GAPS = 2016  # one week of M5


def audit_bars(
    bars: tuple[MarketBar, ...],
    timeframe: str,
    *,
    symbol: str,
    venue: str,
    expected_start: datetime | None = None,
    expected_end: datetime | None = None,
    max_gap_fraction: float = MAX_GAP_FRACTION_FOR_PASS_WITH_GAPS,
) -> QualityReport:
    issues: list[QualityIssue] = []
    gaps: list[GapRecord] = []
    if timeframe not in TIMEFRAME_MINUTES:
        raise ValueError(f"unsupported timeframe {timeframe}")
    minutes = TIMEFRAME_MINUTES[timeframe]
    step = timedelta(minutes=minutes)

    first_ts = bars[0].timestamp if bars else None
    last_ts = bars[-1].timestamp if bars else None
    expected_slots = 0
    missing_slots = 0

    if not bars:
        issues.append(QualityIssue(code="EMPTY_DATASET", detail="no bars"))
    else:
        previous = None
        for index, bar in enumerate(bars):
            ts = bar.timestamp
            if ts.tzinfo is None or ts.utcoffset() != timedelta(0):
                issues.append(QualityIssue(code="TIMEZONE_INCONSISTENT", detail=f"bar {index} not UTC: {ts.isoformat()}"))
            if ts != floor_open(ts, minutes):
                issues.append(QualityIssue(code="TIMEFRAME_MISALIGNED", detail=f"bar {index} off grid: {ts.isoformat()}"))
            if min(bar.open, bar.high, bar.low, bar.close) <= 0:
                issues.append(QualityIssue(code="NONPOSITIVE_PRICE", detail=f"bar {index} at {ts.isoformat()}"))
            if bar.high < max(bar.open, bar.close, bar.low) or bar.low > min(bar.open, bar.close, bar.high):
                issues.append(QualityIssue(code="INVALID_OHLC", detail=f"bar {index} at {ts.isoformat()}"))
            if previous is not None:
                if ts == previous:
                    issues.append(QualityIssue(code="DUPLICATE_TIMESTAMP", detail=f"{ts.isoformat()}"))
                elif ts < previous:
                    issues.append(QualityIssue(code="NON_MONOTONIC_TIMESTAMP", detail=f"{ts.isoformat()} after {previous.isoformat()}"))
                else:
                    missed = int((ts - previous).total_seconds() // (minutes * 60)) - 1
                    if missed > 0:
                        gaps.append(GapRecord(gap_start=previous + step, gap_end=ts, missing_slots=missed))
            previous = ts

        if first_ts is not None and last_ts is not None:
            expected_slots = int((last_ts - first_ts).total_seconds() // (minutes * 60)) + 1
            missing_slots = max(0, expected_slots - len(bars))
            if expected_start is not None and first_ts > expected_start.astimezone(timezone.utc):
                issues.append(QualityIssue(
                    code="COVERAGE_START_SHORTFALL",
                    detail=f"first bar {first_ts.isoformat()} after expected {expected_start.isoformat()}",
                ))
            if expected_end is not None and last_ts + step < expected_end.astimezone(timezone.utc):
                issues.append(QualityIssue(
                    code="COVERAGE_END_SHORTFALL",
                    detail=f"last bar {last_ts.isoformat()} closes before expected {expected_end.isoformat()}",
                ))

    hard_codes = {
        "EMPTY_DATASET", "TIMEZONE_INCONSISTENT", "TIMEFRAME_MISALIGNED", "NONPOSITIVE_PRICE",
        "INVALID_OHLC", "DUPLICATE_TIMESTAMP", "NON_MONOTONIC_TIMESTAMP",
        "COVERAGE_START_SHORTFALL", "COVERAGE_END_SHORTFALL",
    }
    has_hard = any(issue.code in hard_codes for issue in issues)
    gap_fraction = (missing_slots / expected_slots) if expected_slots else 1.0
    largest_gap = max((g.missing_slots for g in gaps), default=0)

    if has_hard or gap_fraction > max_gap_fraction or largest_gap > MAX_SINGLE_GAP_SLOTS_FOR_PASS_WITH_GAPS:
        verdict = QualityVerdict.FAIL
        if not has_hard:
            issues.append(QualityIssue(
                code="GAP_BUDGET_EXCEEDED",
                detail=f"gap_fraction={gap_fraction:.4f} largest_gap={largest_gap}",
            ))
    elif gaps:
        verdict = QualityVerdict.PASS_WITH_DOCUMENTED_GAPS
    else:
        verdict = QualityVerdict.PASS

    return QualityReport(
        verdict=verdict,
        timeframe=timeframe,
        rows=len(bars),
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        expected_slots=expected_slots,
        missing_slots=missing_slots,
        gap_records=tuple(gaps),
        issues=tuple(issues),
        forward_filled=False,
        identity={"symbol": symbol, "venue": venue},
    )
