"""Adapter: Dukascopy public tick archives (FX-Data GitHub mirror) -> canonical M1.

SOURCE SHAPE
------------
One CSV per UTC hour at ``{SYMBOL}/{YYYY}/{MM}/{YYYY}-{MM}-{DD}--{HH}h_ticks.csv``::

    2017.01.02 00:00:16.483,1.0523,1.05283,1.00,1.25
    <timestamp>,<bid>,<ask>,<bid_volume>,<ask_volume>

PRICE REPRESENTATION — DECLARED, VERIFIED, NEVER GUESSED
--------------------------------------------------------
The mirror's converter writes EVERY instrument on a fixed 1e-5 decimal grid
rather than in the instrument's quoting convention. Raw USDJPY therefore
reads ``1.15578`` for a true 115.578 quote and raw XAUUSD reads ``11.46039``
for 1146.039.

This is NOT corrected by an inferred multiplier. The contract is structural
and declared once:

    source_points      = round(raw_decimal * 1e5)        # exact integer parse
    canonical_price    = source_points / 10**PRICE_DECIMALS[symbol]

i.e. the provider grid is reinterpreted at the symbol's declared quoting
precision. For EURUSD/GBPUSD (5 dp) this is the identity; for USDJPY/XAUUSD
(3 dp) it restores the quoting convention. The rule is then CHECKED, not
trusted, two ways and fails closed on either:

  1. every normalized price must lie inside the symbol's declared
     plausibility band (:data:`PLAUSIBILITY_BANDS`);
  2. for any year that overlaps an independent authority, the cross-source
     comparison must agree to within the configured tolerance
     (see :mod:`ag_edgelab.data.authority.cross_source`).

ANOMALY POLICY
--------------
Suspicious observations are CLASSIFIED and COUNTED, never silently
repaired. Only observations that cannot be placed on the canonical grid at
all are excluded from bar construction, and every exclusion is counted:

  ``MALFORMED_ROW``            unparseable row
  ``PRECISION_EXCEEDED``       more than 5 source decimals (off-grid)
  ``NONPOSITIVE_PRICE``        bid or ask <= 0
  ``TIMESTAMP_FILE_MISMATCH``  row date/hour != the file's declared hour
  ``CROSSED_QUOTE``            ask < bid — counted, NOT excluded: the bid
                               series is still a valid bid series, and
                               dropping it would silently repair the book
  ``NON_MONOTONIC_TICK``       row earlier than its predecessor — counted;
                               provider file order remains authoritative
"""

from __future__ import annotations

import re
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from ag_edgelab.data.authority.schema import (
    CanonicalBar,
    PRICE_DECIMALS,
    SPREAD_EXTRA_DECIMALS,
    SchemaViolation,
)

SOURCE_ID = "DUKASCOPY_TICK_FX31337_MIRROR_V1"

#: Decimal places on the provider's fixed integer grid (all instruments).
SOURCE_GRID_DECIMALS = 5

#: Coarse, declared sanity bands. They exist only to catch gross
#: mis-scaling; they are NOT fitted to the data and are deliberately wide.
PLAUSIBILITY_BANDS: dict[str, tuple[float, float]] = {
    "EURUSD": (0.50, 2.00),
    "GBPUSD": (0.80, 2.50),
    "USDJPY": (50.0, 200.0),
    "XAUUSD": (500.0, 5000.0),
}

TICK_FILE_RE = re.compile(
    r"(?P<symbol>[A-Z]{6})/(?P<year>\d{4})/(?P<month>\d{2})/"
    r"(?P<d_year>\d{4})-(?P<d_month>\d{2})-(?P<d_day>\d{2})--(?P<hour>\d{2})h_ticks\.csv$"
)


class SourceContractViolation(RuntimeError):
    """Raised when the source violates its declared structural contract."""


@dataclass
class NormalizationAnomalies:
    malformed_row: int = 0
    precision_exceeded: int = 0
    nonpositive_price: int = 0
    timestamp_file_mismatch: int = 0
    crossed_quote: int = 0
    non_monotonic_tick: int = 0
    out_of_band_price: int = 0
    examples: list[str] = field(default_factory=list)

    def note(self, code: str, detail: str) -> None:
        setattr(self, code, getattr(self, code) + 1)
        if len(self.examples) < 20:
            self.examples.append(f"{code}: {detail}")

    @property
    def excluded_ticks(self) -> int:
        return (self.malformed_row + self.precision_exceeded
                + self.nonpositive_price + self.timestamp_file_mismatch)

    def as_dict(self) -> dict:
        return {
            "MALFORMED_ROW": self.malformed_row,
            "PRECISION_EXCEEDED": self.precision_exceeded,
            "NONPOSITIVE_PRICE": self.nonpositive_price,
            "TIMESTAMP_FILE_MISMATCH": self.timestamp_file_mismatch,
            "CROSSED_QUOTE": self.crossed_quote,
            "NON_MONOTONIC_TICK": self.non_monotonic_tick,
            "OUT_OF_BAND_PRICE": self.out_of_band_price,
            "excluded_from_bars": self.excluded_ticks,
            "counted_but_retained": self.crossed_quote + self.non_monotonic_tick,
            "examples": list(self.examples),
        }


@dataclass
class NormalizationResult:
    symbol: str
    year: int
    bars: tuple[CanonicalBar, ...]
    tick_count: int
    file_count: int
    anomalies: NormalizationAnomalies

    @property
    def naive_source_timestamps(self) -> tuple[datetime, ...]:
        """Bar open times as the PROVIDER's own clock values (tz stripped).

        Normalization never shifts the provider clock, so the naive part of
        each canonical timestamp is literally what the provider wrote. The
        timezone proof consumes these to identify the frame independently.
        """
        return tuple(b.timestamp_utc.replace(tzinfo=None) for b in self.bars)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "year": self.year,
            "m1_bars": len(self.bars),
            "ticks_ingested": self.tick_count,
            "hour_files": self.file_count,
            "anomalies": self.anomalies.as_dict(),
        }


_POW10 = [10 ** i for i in range(12)]


def parse_points(token: str) -> int:
    """Exact integer parse of a decimal price onto the 1e-5 provider grid.

    Returns the price scaled by ``10**SOURCE_GRID_DECIMALS``. Raises
    :class:`ValueError` if the token carries more precision than the grid —
    we never round a quote into existence.
    """
    dot = token.find(".")
    if dot < 0:
        return int(token) * _POW10[SOURCE_GRID_DECIMALS]
    frac = token[dot + 1:]
    width = len(frac)
    if width > SOURCE_GRID_DECIMALS:
        raise ValueError(f"off-grid precision: {token!r}")
    return int(token[:dot]) * _POW10[SOURCE_GRID_DECIMALS] + int(frac) * _POW10[SOURCE_GRID_DECIMALS - width]


def iter_tick_files(archive: Path, symbol: str, year: int) -> Iterator[tuple[datetime, str, bytes]]:
    """Yield ``(file_hour_utc, relative_path, payload)`` in archive order."""
    with tarfile.open(archive, "r|gz") as tf:
        for member in tf:
            if not member.isfile():
                continue
            parts = member.name.split("/", 1)
            relative = parts[1] if len(parts) == 2 else member.name
            match = TICK_FILE_RE.search(relative)
            if match is None:
                continue
            if match["symbol"] != symbol or int(match["year"]) != year:
                continue
            if match["d_year"] != match["year"] or match["d_month"] != match["month"]:
                raise SourceContractViolation(
                    f"{relative}: file name contradicts its directory placement")
            handle = tf.extractfile(member)
            if handle is None:          # pragma: no cover - defensive
                continue
            hour = datetime(
                int(match["d_year"]), int(match["d_month"]), int(match["d_day"]),
                int(match["hour"]), tzinfo=timezone.utc)
            yield hour, relative, handle.read()


def normalize_archive_to_m1(
    archive: Path, symbol: str, year: int,
) -> NormalizationResult:
    """Deterministically aggregate one symbol-year of ticks into canonical M1.

    Bucketing is by UTC minute floor. A minute with no tick produces NO bar:
    absence stays absent. OHLC is built from the BID series (declared price
    basis); ``bid``/``ask`` carry the closing quote and ``spread`` the mean
    ask-bid over the bucket. Nothing is forward filled or interpolated.
    """
    if symbol not in PRICE_DECIMALS:
        raise SchemaViolation(f"undeclared symbol {symbol!r}")
    dec = PRICE_DECIMALS[symbol]
    # provider grid -> canonical grid is a pure decimal-point reinterpretation
    price_divisor = float(_POW10[dec])
    spread_divisor = float(_POW10[dec]) * _POW10[SPREAD_EXTRA_DECIMALS]
    lo_band, hi_band = PLAUSIBILITY_BANDS[symbol]

    anomalies = NormalizationAnomalies()
    # bucket -> [open, high, low, close, ticks, vol_sum, spread_pts_sum, bid, ask]
    buckets: dict[datetime, list] = {}
    tick_count = 0
    file_count = 0

    for hour_utc, relative, payload in iter_tick_files(archive, symbol, year):
        file_count += 1
        expected_prefix = (
            f"{hour_utc.year:04d}.{hour_utc.month:02d}.{hour_utc.day:02d} "
            f"{hour_utc.hour:02d}:"
        )
        previous_key = -1
        text = payload.decode("ascii", errors="replace")
        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            cells = line.split(",")
            if len(cells) != 5:
                anomalies.note("malformed_row", f"{relative}: {line[:48]}")
                continue
            stamp = cells[0]
            if len(stamp) < 19 or not stamp.startswith(expected_prefix):
                anomalies.note("timestamp_file_mismatch", f"{relative}: {stamp}")
                continue
            try:
                bid_pts = parse_points(cells[1])
                ask_pts = parse_points(cells[2])
                bid_vol = float(cells[3])
                ask_vol = float(cells[4])
            except ValueError as exc:
                code = ("precision_exceeded" if "off-grid" in str(exc) else "malformed_row")
                anomalies.note(code, f"{relative}: {line[:48]}")
                continue
            if bid_pts <= 0 or ask_pts <= 0:
                anomalies.note("nonpositive_price", f"{relative}: {line[:48]}")
                continue
            if ask_pts < bid_pts:
                anomalies.note("crossed_quote", f"{relative}: {line[:48]}")

            minute = int(stamp[14:16])
            second = int(stamp[17:19])
            key = minute * 60 + second
            if key < previous_key:
                anomalies.note("non_monotonic_tick", f"{relative}: {stamp}")
            previous_key = key

            tick_count += 1
            open_time = hour_utc + timedelta(minutes=minute)
            slot = buckets.get(open_time)
            spread_pts = ask_pts - bid_pts
            if slot is None:
                buckets[open_time] = [bid_pts, bid_pts, bid_pts, bid_pts, 1,
                                      bid_vol + ask_vol, spread_pts, bid_pts, ask_pts]
            else:
                if bid_pts > slot[1]:
                    slot[1] = bid_pts
                if bid_pts < slot[2]:
                    slot[2] = bid_pts
                slot[3] = bid_pts
                slot[4] += 1
                slot[5] += bid_vol + ask_vol
                slot[6] += spread_pts
                slot[7] = bid_pts
                slot[8] = ask_pts

    bars: list[CanonicalBar] = []
    for open_time in sorted(buckets):
        o, h, low, c, ticks, vol, spread_sum, bid, ask = buckets[open_time]
        op, hp, lp, cp = (o / price_divisor, h / price_divisor,
                          low / price_divisor, c / price_divisor)
        if not (lo_band <= lp and hp <= hi_band):
            anomalies.note(
                "out_of_band_price",
                f"{symbol} {open_time.isoformat()} low={lp} high={hp} "
                f"outside declared band [{lo_band}, {hi_band}]")
        mean_spread_pts = spread_sum / ticks
        bars.append(CanonicalBar(
            timestamp_utc=open_time,
            symbol=symbol,
            open=op, high=hp, low=lp, close=cp,
            tick_volume=ticks,
            real_volume=round(vol, 6),
            spread=round(max(mean_spread_pts, 0.0) * _POW10[SPREAD_EXTRA_DECIMALS]
                         / spread_divisor, dec + SPREAD_EXTRA_DECIMALS),
            bid=bid / price_divisor,
            ask=ask / price_divisor,
        ))

    if anomalies.out_of_band_price:
        raise SourceContractViolation(
            f"{symbol} {year}: {anomalies.out_of_band_price} normalized bars fall "
            f"outside the declared plausibility band {PLAUSIBILITY_BANDS[symbol]} — "
            "the provider grid contract is violated; STATUS=BLOCKED_DATA_AUTHORITY")

    return NormalizationResult(
        symbol=symbol, year=year, bars=tuple(bars), tick_count=tick_count,
        file_count=file_count, anomalies=anomalies,
    )
