from __future__ import annotations

"""Dataset pipeline for the SESSION_TRADE_V2 campaign.

Source (primary, all four symbols): HistData ASCII M1 zips mirrored in the
public repository ``parrondo/deeptrading`` (``HISTDATA_COM_ASCII_{SYM}_M1_2017.zip``).
Timestamps in these files are wall-clock ``America/New_York`` (DST-following;
verified from the weekly reopen pattern: FX reopens 17:00 New York every week
across the March/November DST transitions).  They are normalized to UTC before
any session assignment.

Secondary (XAUUSD only, cross-validation + spread evidence): Dukascopy M1
bid/ask CSVs mirrored in ``kevingtlin/Market-Data-Lab`` (epoch-ms, UTC).

M1 -> M15 aggregation rule (frozen, no synthetic fills):

* An M15 bucket becomes a bar iff at least 13 of its 15 M1 minutes are present
  (this tolerates the provider's documented 2-minute 17:00 America/New_York
  rollover gap and isolated zero-tick minutes; OHLC is aggregated from the
  minutes that actually traded — the close/high/low are exact last-tick
  semantics, the open is the first traded minute's open).
* A bucket with <= 12 present minutes is a MISSING bar.  Missing reference or
  trade-window bars make the session DATA_INVALID; they are never filled.
"""

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ag_edgelab.contracts.market import MarketBar

NY = ZoneInfo("America/New_York")
UTC = timezone.utc

M15_MINUTES_REQUIRED = 13  # of 15
SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")

# ---------------------------------------------------------------------------
# Campaign window and partitions (frozen)
# ---------------------------------------------------------------------------

WINDOW_START = datetime(2017, 1, 1, tzinfo=UTC)
WINDOW_END = datetime(2018, 1, 1, tzinfo=UTC)

PARTITIONS = {
    "DEVELOPMENT": (datetime(2017, 1, 1, tzinfo=UTC), datetime(2017, 9, 1, tzinfo=UTC)),
    "OOS": (datetime(2017, 9, 1, tzinfo=UTC), datetime(2017, 12, 1, tzinfo=UTC)),
    "SEALED_HOLDOUT": (datetime(2017, 12, 1, tzinfo=UTC), datetime(2018, 1, 1, tzinfo=UTC)),
}


class HoldoutAccessError(PermissionError):
    """Raised on any attempt to load bars from the sealed holdout partition."""


class PartitionError(ValueError):
    """Raised for unknown partitions or invalid partition requests."""


def partition_bounds(role: str) -> tuple[datetime, datetime]:
    if role not in PARTITIONS:
        raise PartitionError(f"unknown partition role: {role}")
    return PARTITIONS[role]


def assert_partition_accessible(role: str) -> None:
    """The sealed holdout is never readable by any campaign stage."""
    if role == "SEALED_HOLDOUT":
        raise HoldoutAccessError(
            "SEALED_HOLDOUT partition is sealed; opening it requires an explicit "
            "owner-authorized unseal outside this campaign"
        )


# ---------------------------------------------------------------------------
# Loading and aggregation
# ---------------------------------------------------------------------------


def load_histdata_m1(zip_path: Path, symbol: str) -> tuple[MarketBar, ...]:
    """Load a HistData ASCII M1 zip and normalize America/New_York -> UTC."""
    with zipfile.ZipFile(zip_path) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".csv"))
        with zf.open(name) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8")
            reader = csv.reader(text, delimiter=";")
            rows = [row for row in reader if row]
    bars: list[MarketBar] = []
    for row in rows:
        ts = datetime.strptime(row[0], "%Y%m%d %H%M%S").replace(tzinfo=NY).astimezone(UTC)
        o, h, l, c = (float(row[1]), float(row[2]), float(row[3]), float(row[4]))
        bars.append(MarketBar(timestamp=ts, open=o, high=h, low=l, close=c))
    bars.sort(key=lambda b: b.timestamp)
    return tuple(bars)


def aggregate_m15(m1_bars: tuple[MarketBar, ...]) -> tuple[MarketBar, ...]:
    """Aggregate M1 bars to M15 under the frozen >=13/15 rule."""
    buckets: dict[datetime, list[MarketBar]] = {}
    for bar in m1_bars:
        minute = (bar.timestamp.minute // 15) * 15
        key = bar.timestamp.replace(minute=minute, second=0, microsecond=0)
        buckets.setdefault(key, []).append(bar)
    out: list[MarketBar] = []
    for key in sorted(buckets):
        minutes = sorted(buckets[key], key=lambda b: b.timestamp)
        if len(minutes) < M15_MINUTES_REQUIRED:
            continue  # missing bar — never filled
        out.append(
            MarketBar(
                timestamp=key,
                open=minutes[0].open,
                high=max(b.high for b in minutes),
                low=min(b.low for b in minutes),
                close=minutes[-1].close,
            )
        )
    return tuple(out)


@dataclass(frozen=True)
class DatasetQualityReport:
    symbol: str
    source: str
    m1_rows: int
    m1_duplicate_timestamps: int
    m1_ohlc_violations: int
    m15_bars: int
    m15_buckets_with_lt13_minutes: int
    first_bar: datetime
    last_bar: datetime
    source_sha256: str
    notes: tuple[str, ...]


def build_symbol_dataset(zip_path: Path, symbol: str) -> tuple[tuple[MarketBar, ...], DatasetQualityReport]:
    """Load, quality-gate and aggregate one symbol's M1 history to UTC M15."""
    import hashlib

    sha = hashlib.sha256(Path(zip_path).read_bytes()).hexdigest()
    m1 = load_histdata_m1(zip_path, symbol)

    stamps = [b.timestamp for b in m1]
    duplicates = len(stamps) - len(set(stamps))
    if duplicates:
        raise ValueError(f"{symbol}: {duplicates} duplicate M1 timestamps — refusing to dedupe silently")

    ohlc_violations = 0
    for b in m1:
        if b.high < max(b.open, b.close, b.low) or b.low > min(b.open, b.close, b.high):
            ohlc_violations += 1
    if ohlc_violations:
        raise ValueError(f"{symbol}: {ohlc_violations} OHLC-invalid M1 bars")

    # bucket census for the quality report
    bucket_counts: dict[datetime, int] = {}
    for b in m1:
        minute = (b.timestamp.minute // 15) * 15
        key = b.timestamp.replace(minute=minute, second=0, microsecond=0)
        bucket_counts[key] = bucket_counts.get(key, 0) + 1
    lt13 = sum(1 for n in bucket_counts.values() if n < M15_MINUTES_REQUIRED)

    m15 = aggregate_m15(m1)
    m15 = tuple(b for b in m15 if WINDOW_START <= b.timestamp < WINDOW_END)

    report = DatasetQualityReport(
        symbol=symbol,
        source=str(zip_path.name),
        m1_rows=len(m1),
        m1_duplicate_timestamps=duplicates,
        m1_ohlc_violations=ohlc_violations,
        m15_bars=len(m15),
        m15_buckets_with_lt13_minutes=lt13,
        first_bar=m15[0].timestamp if m15 else None,
        last_bar=m15[-1].timestamp if m15 else None,
        source_sha256=sha,
        notes=(
            "timezone: source America/New_York (DST) normalized to UTC",
            f"M15 rule: >= {M15_MINUTES_REQUIRED}/15 M1 minutes per bucket",
        ),
    )
    return m15, report


def slice_partition(
    bars: tuple[MarketBar, ...], role: str
) -> tuple[MarketBar, ...]:
    """Bars whose OPEN time falls inside the requested partition.

    The sealed holdout fails closed: no campaign stage may read it.
    """
    assert_partition_accessible(role)
    start, end = partition_bounds(role)
    return tuple(b for b in bars if start <= b.timestamp < end)


def evaluable_trading_dates(bounds: tuple[datetime, datetime]) -> tuple[date, ...]:
    """UTC trading dates whose BOTH session cycles fit fully inside the bounds.

    A date is evaluable only when the Asian reference (D-1 22:00) and the
    London/NewYork trade end (D 14:00) both lie inside the partition, so no
    session ever straddles a partition boundary (no cross-partition
    contamination, no DEV/OOS leakage through window edges).
    """
    start, end = bounds
    out: list[date] = []
    d = start.date()
    while d <= end.date():
        al_ref_start = datetime.combine(d - timedelta(days=1), time(22, 0), tzinfo=UTC)
        ln_ref_start = datetime.combine(d, time(6, 0), tzinfo=UTC)
        trade_end = datetime.combine(d, time(14, 0), tzinfo=UTC)
        if al_ref_start >= start and ln_ref_start >= start and trade_end <= end:
            out.append(d)
        d += timedelta(days=1)
    return tuple(out)
