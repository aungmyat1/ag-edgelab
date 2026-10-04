"""Recovered PR #10 FX data authority — HistData ASCII M1 2017 pipeline.

LINEAGE: this module recovers, unchanged in semantics, the dataset authority
established by PR #10 (branch arena/01a100ce-ag-edgelab,
``campaigns/session_trade_v2/dataset.py``):

  * source: HistData ASCII M1 zips (HISTDATA_COM_ASCII_{SYM}_M1_2017.zip)
    mirrored in the public GitHub repository ``parrondo/deeptrading``;
  * timestamps are wall-clock America/New_York (DST-following) and are
    normalized to UTC before ANY session or structure logic;
  * raw zip SHA-256 identities are PINNED below and verified before use —
    a mismatch is a hard BLOCKED_DATA_AUTHORITY stop, never a warning;
  * M1 -> M15: a bucket becomes a bar iff >= 13 of its 15 minutes traded;
    buckets below that are MISSING bars and are NEVER forward-filled;
  * partition discipline: DEVELOPMENT / OOS / SEALED_HOLDOUT with the
    holdout structurally unreadable (fails closed).

NEW IN THIS MISSION (declared, not silent): M15 -> H1/H4/D1 derivation from
the SAME normalized M1 lineage (no independent higher-TF provider) under a
preregistered coverage rule, with full lineage hashes and anti-lookahead
accessors.
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.bars import dumps_bars
from ag_edgelab.data.derive import TIMEFRAME_MINUTES, floor_open

NY = ZoneInfo("America/New_York")
UTC = timezone.utc

SYMBOLS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")

M15_MINUTES_REQUIRED = 13  # of 15 — frozen PR #10 rule

# Preregistered higher-TF coverage rule (fraction of expected source slots
# that must be present for a bucket to become a bar). FX genuinely has no
# weekend bars, so a 100%-complete D1 cannot exist around the weekly
# open/close; 0.75 keeps full trading days and drops partial weekend
# stubs. Missing buckets stay MISSING — never filled.
MTF_COVERAGE_FRACTION = 0.75
MTF_TIMEFRAMES: tuple[str, ...] = ("H1", "H4", "D1")

# ---------------------------------------------------------------------------
# PINNED raw dataset identities (recovered from PR #10
# artifacts/session_trade_v2_economic_matrix/dataset_quality_reports.json)
# ---------------------------------------------------------------------------

PINNED_SOURCE_SHA256: dict[str, str] = {
    "EURUSD": "0dcd66dc67d7af4716404a5315d376ee1e7eaebe292afbda3c1003d2dfa16f57",
    "GBPUSD": "e5ba3800e37fae0e326dbaa234952ca04e8f378c08b036530a2811206110c10b",
    "USDJPY": "477a1f515586f06d67cb75b3662260160e1e29e63c51804a30a5e7d69b09df5f",
    "XAUUSD": "a39c1ccaaeb022c83309685107c9e619c2bcff8b2fd94fbd7405a721a4fe70ff",
}

# Frozen campaign window and partitions (PR #10 authority).
WINDOW_START = datetime(2017, 1, 1, tzinfo=UTC)
WINDOW_END = datetime(2018, 1, 1, tzinfo=UTC)

PARTITIONS = {
    "DEVELOPMENT": (datetime(2017, 1, 1, tzinfo=UTC), datetime(2017, 9, 1, tzinfo=UTC)),
    "OOS": (datetime(2017, 9, 1, tzinfo=UTC), datetime(2017, 12, 1, tzinfo=UTC)),
    "SEALED_HOLDOUT": (datetime(2017, 12, 1, tzinfo=UTC), datetime(2018, 1, 1, tzinfo=UTC)),
}


class BlockedDataAuthority(RuntimeError):
    """Raised when a raw dataset identity cannot be verified exactly."""


class HoldoutAccessError(PermissionError):
    """Raised on any attempt to load bars from the sealed holdout partition."""


class PartitionError(ValueError):
    """Raised for unknown partitions or invalid partition requests."""


def verify_source_identity(zip_path: Path, symbol: str) -> str:
    """sha256 of the raw zip; must equal the pinned PR #10 identity exactly."""
    if symbol not in PINNED_SOURCE_SHA256:
        raise BlockedDataAuthority(f"no pinned identity for symbol {symbol}")
    actual = hashlib.sha256(Path(zip_path).read_bytes()).hexdigest()
    expected = PINNED_SOURCE_SHA256[symbol]
    if actual != expected:
        raise BlockedDataAuthority(
            f"{symbol}: raw dataset identity mismatch — expected {expected}, got {actual}; "
            "STATUS=BLOCKED_DATA_AUTHORITY")
    return actual


def partition_bounds(role: str) -> tuple[datetime, datetime]:
    if role not in PARTITIONS:
        raise PartitionError(f"unknown partition role: {role}")
    return PARTITIONS[role]


def assert_partition_accessible(role: str) -> None:
    """The sealed holdout is never readable by any campaign stage."""
    if role == "SEALED_HOLDOUT":
        raise HoldoutAccessError(
            "SEALED_HOLDOUT partition is sealed; opening it requires an explicit "
            "owner-authorized unseal outside this campaign")


# ---------------------------------------------------------------------------
# Recovered loaders / aggregation (PR #10 semantics, unchanged)
# ---------------------------------------------------------------------------

def load_histdata_m1(zip_path: Path) -> tuple[MarketBar, ...]:
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


def quality_gate_m1(m1: tuple[MarketBar, ...], symbol: str) -> dict:
    """PR #10 gates: duplicates and OHLC violations are hard failures."""
    stamps = [b.timestamp for b in m1]
    duplicates = len(stamps) - len(set(stamps))
    if duplicates:
        raise ValueError(f"{symbol}: {duplicates} duplicate M1 timestamps — refusing to dedupe silently")
    ohlc_violations = sum(
        1 for b in m1
        if b.high < max(b.open, b.close, b.low) or b.low > min(b.open, b.close, b.high))
    if ohlc_violations:
        raise ValueError(f"{symbol}: {ohlc_violations} OHLC-invalid M1 bars")
    return {"m1_rows": len(m1), "m1_duplicate_timestamps": 0, "m1_ohlc_violations": 0}


def aggregate_m15(m1_bars: tuple[MarketBar, ...]) -> tuple[MarketBar, ...]:
    """Aggregate M1 bars to M15 under the frozen >=13/15 rule (no fills)."""
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
        out.append(MarketBar(
            timestamp=key,
            open=minutes[0].open,
            high=max(b.high for b in minutes),
            low=min(b.low for b in minutes),
            close=minutes[-1].close,
        ))
    return tuple(out)


def slice_partition(bars: tuple[MarketBar, ...], role: str) -> tuple[MarketBar, ...]:
    """Bars whose OPEN time falls inside the requested partition.

    The sealed holdout fails closed: no campaign stage may read it.
    """
    assert_partition_accessible(role)
    start, end = partition_bounds(role)
    return tuple(b for b in bars if start <= b.timestamp < end)


# ---------------------------------------------------------------------------
# Same-lineage MTF derivation (M15 -> H1/H4/D1), declared coverage rule
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FxDerivedLineage:
    symbol: str
    source_timeframe: str
    output_timeframe: str
    coverage_rule: str
    source_hash: str
    output_hash: str
    rows: int


def _bars_hash(bars: tuple[MarketBar, ...]) -> str:
    return hashlib.sha256(dumps_bars(bars).encode("utf-8")).hexdigest()


def derive_fx_timeframe(
    m15_bars: tuple[MarketBar, ...], target_timeframe: str, symbol: str,
) -> tuple[tuple[MarketBar, ...], FxDerivedLineage]:
    """Derive one higher timeframe from the SAME normalized M15 lineage.

    Preregistered rule: a UTC-floored bucket becomes a bar iff at least
    MTF_COVERAGE_FRACTION of its expected M15 slots are PRESENT in the feed.
    Under-covered buckets are MISSING bars (documented, never filled). The
    emitted bar's OHLC uses only minutes that actually traded.
    """
    if target_timeframe not in MTF_TIMEFRAMES:
        raise ValueError(f"unsupported FX derived timeframe: {target_timeframe}")
    tgt_minutes = TIMEFRAME_MINUTES[target_timeframe]
    expected_slots = tgt_minutes // 15
    required = -(-expected_slots * 3 // 4)  # ceil(0.75 * expected)

    buckets: dict[datetime, list[MarketBar]] = {}
    for bar in m15_bars:
        buckets.setdefault(floor_open(bar.timestamp, tgt_minutes), []).append(bar)

    out: list[MarketBar] = []
    for open_time in sorted(buckets):
        group = sorted(buckets[open_time], key=lambda b: b.timestamp)
        if len(group) < required:
            continue  # missing higher-TF bar — never filled
        out.append(MarketBar(
            timestamp=open_time,
            open=group[0].open,
            high=max(b.high for b in group),
            low=min(b.low for b in group),
            close=group[-1].close,
        ))
    bars = tuple(out)
    lineage = FxDerivedLineage(
        symbol=symbol, source_timeframe="M15", output_timeframe=target_timeframe,
        coverage_rule=f">= ceil({MTF_COVERAGE_FRACTION} * {expected_slots}) = {required} "
                      f"present M15 slots per UTC bucket; no forward fill",
        source_hash=_bars_hash(m15_bars), output_hash=_bars_hash(bars), rows=len(bars))
    return bars, lineage


def bars_closed_at(
    bars: tuple[MarketBar, ...], timeframe: str, as_of: datetime,
) -> tuple[MarketBar, ...]:
    """Anti-lookahead accessor: bars fully CLOSED at or before `as_of`.

    latest input timestamp (open) + span <= as_of for every returned bar.
    """
    span = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
    return tuple(b for b in bars if b.timestamp + span <= as_of)


def build_symbol_frames(
    zip_path: Path, symbol: str,
) -> tuple[dict[str, tuple[MarketBar, ...]], dict, tuple[FxDerivedLineage, ...]]:
    """Verify identity, load, gate, aggregate and derive ALL frames from one
    M1 lineage. Returns ({"M15","H1","H4","D1"}: bars, quality, lineages)."""
    source_sha = verify_source_identity(zip_path, symbol)
    m1 = load_histdata_m1(zip_path)
    quality = quality_gate_m1(m1, symbol)
    m15 = tuple(b for b in aggregate_m15(m1) if WINDOW_START <= b.timestamp < WINDOW_END)
    frames: dict[str, tuple[MarketBar, ...]] = {"M15": m15}
    lineages: list[FxDerivedLineage] = []
    for tf in MTF_TIMEFRAMES:
        frames[tf], lineage = derive_fx_timeframe(m15, tf, symbol)
        lineages.append(lineage)
    quality.update({
        "symbol": symbol,
        "source": zip_path.name,
        "source_sha256": source_sha,
        "m15_bars": len(m15),
        "h1_bars": len(frames["H1"]),
        "h4_bars": len(frames["H4"]),
        "d1_bars": len(frames["D1"]),
        "first_bar": m15[0].timestamp.isoformat() if m15 else None,
        "last_bar": m15[-1].timestamp.isoformat() if m15 else None,
        "timezone_rule": "source America/New_York (DST) normalized to UTC before any logic",
        "m15_rule": f">= {M15_MINUTES_REQUIRED}/15 M1 minutes per bucket; no forward fill",
    })
    return frames, quality, tuple(lineages)
