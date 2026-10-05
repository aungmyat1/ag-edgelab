"""Canonical bar schema — one deterministic representation for every source.

The canonical document is a byte-stable text format whose SHA-256 IS the
dataset identity. Determinism requirements:

* timestamps are UTC, bar-OPEN, second precision, ``...Z`` suffix;
* prices are fixed-point with a symbol-specific decimal count (never
  ``repr(float)``, which is platform- and value-shaped);
* optional columns are written as the empty string when absent — an absent
  observation is explicitly absent, never zero and never carried forward;
* the column order and the schema banner are frozen.

Required minimum fields: ``timestamp_utc, symbol, open, high, low, close``.
Optional source-supported fields: ``tick_volume, real_volume, spread, bid,
ask``. A source that cannot supply an optional field writes NULL; it must
never synthesise one.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Iterable, Sequence

from pydantic import BaseModel, ConfigDict, model_validator

CANONICAL_SCHEMA_VERSION = "EDGELAB_CANONICAL_BAR_V1"

REQUIRED_FIELDS: tuple[str, ...] = (
    "timestamp_utc", "symbol", "open", "high", "low", "close",
)
OPTIONAL_FIELDS: tuple[str, ...] = (
    "tick_volume", "real_volume", "spread", "bid", "ask",
)
COLUMNS: tuple[str, ...] = REQUIRED_FIELDS + OPTIONAL_FIELDS

#: Symbol price precision. A quote carrying MORE decimals than this is a
#: PRICE_PRECISION_ANOMALY and is classified, never silently rounded.
PRICE_DECIMALS: dict[str, int] = {
    "EURUSD": 5,
    "GBPUSD": 5,
    "USDJPY": 3,
    "XAUUSD": 3,
}

#: Spread is a derived statistic (mean over the bucket), not a quotable
#: price, so it carries one extra decimal. Declared, never implicit.
SPREAD_EXTRA_DECIMALS = 1

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
BANNER = f"# {CANONICAL_SCHEMA_VERSION}"
HEADER = ",".join(COLUMNS)


class SchemaViolation(ValueError):
    """Raised when data cannot be represented in the canonical schema."""


def price_decimals(symbol: str) -> int:
    try:
        return PRICE_DECIMALS[symbol]
    except KeyError:  # pragma: no cover - guarded by callers
        raise SchemaViolation(
            f"no declared price precision for symbol {symbol!r}; refusing to "
            "guess a tick size"
        ) from None


def tick_size(symbol: str) -> float:
    return 10.0 ** (-price_decimals(symbol))


def format_price(value: float, decimals: int) -> str:
    """Fixed-point, deterministic, locale-free price rendering."""
    if value != value or value in (float("inf"), float("-inf")):
        raise SchemaViolation(f"non-finite price {value!r}")
    return f"{value:.{decimals}f}"


class CanonicalBar(BaseModel):
    """One completed observation in the canonical schema.

    ``timestamp_utc`` is the bar OPEN time. A bar spanning N minutes is only
    observable from ``timestamp_utc + N minutes`` onwards; see
    :mod:`ag_edgelab.data.authority.resample` for the causal accessors.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp_utc: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    tick_volume: int | None = None
    real_volume: float | None = None
    spread: float | None = None
    bid: float | None = None
    ask: float | None = None

    @model_validator(mode="after")
    def _invariants(self) -> "CanonicalBar":
        ts = self.timestamp_utc
        if ts.tzinfo is None or ts.utcoffset() != ts.tzinfo.utcoffset(ts) or ts.utcoffset().total_seconds() != 0:
            raise SchemaViolation(
                f"timestamp_utc must be an aware UTC datetime, got {ts!r}")
        if ts.microsecond:
            raise SchemaViolation("canonical timestamps are second-precision")
        if self.symbol not in PRICE_DECIMALS:
            raise SchemaViolation(
                f"symbol {self.symbol!r} has no declared price precision")
        for name in ("open", "high", "low", "close"):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise SchemaViolation(f"{name} is not finite")
            if value <= 0:
                raise SchemaViolation(f"{name} must be positive, got {value!r}")
        if self.high < max(self.open, self.close, self.low):
            raise SchemaViolation("OHLC invariant: high below open/close/low")
        if self.low > min(self.open, self.close, self.high):
            raise SchemaViolation("OHLC invariant: low above open/close/high")
        if self.tick_volume is not None and self.tick_volume < 0:
            raise SchemaViolation("tick_volume must be >= 0")
        if self.real_volume is not None and self.real_volume < 0:
            raise SchemaViolation("real_volume must be >= 0")
        if self.spread is not None and self.spread < 0:
            raise SchemaViolation("spread must be >= 0")
        if (self.bid is None) != (self.ask is None):
            raise SchemaViolation(
                "bid and ask are a pair: supply both or neither; a half-quote "
                "would require inventing the other side")
        if self.bid is not None and self.ask is not None and self.ask < self.bid:
            raise SchemaViolation("ask below bid (crossed quote)")
        return self

    # -- serialization ----------------------------------------------------

    def to_row(self) -> str:
        dec = price_decimals(self.symbol)
        sdec = dec + SPREAD_EXTRA_DECIMALS
        cells = [
            self.timestamp_utc.strftime(TIMESTAMP_FORMAT),
            self.symbol,
            format_price(self.open, dec),
            format_price(self.high, dec),
            format_price(self.low, dec),
            format_price(self.close, dec),
            "" if self.tick_volume is None else str(int(self.tick_volume)),
            "" if self.real_volume is None else f"{self.real_volume:.6f}",
            "" if self.spread is None else format_price(self.spread, sdec),
            "" if self.bid is None else format_price(self.bid, dec),
            "" if self.ask is None else format_price(self.ask, dec),
        ]
        return ",".join(cells)

    @classmethod
    def from_row(cls, row: str) -> "CanonicalBar":
        cells = row.split(",")
        if len(cells) != len(COLUMNS):
            raise SchemaViolation(
                f"expected {len(COLUMNS)} canonical columns, got {len(cells)}")
        values = dict(zip(COLUMNS, cells))
        ts = datetime.strptime(values["timestamp_utc"], TIMESTAMP_FORMAT).replace(
            tzinfo=timezone.utc)
        return cls(
            timestamp_utc=ts,
            symbol=values["symbol"],
            open=float(values["open"]),
            high=float(values["high"]),
            low=float(values["low"]),
            close=float(values["close"]),
            tick_volume=int(values["tick_volume"]) if values["tick_volume"] else None,
            real_volume=float(values["real_volume"]) if values["real_volume"] else None,
            spread=float(values["spread"]) if values["spread"] else None,
            bid=float(values["bid"]) if values["bid"] else None,
            ask=float(values["ask"]) if values["ask"] else None,
        )


def dumps_canonical(bars: Sequence[CanonicalBar]) -> str:
    out = [BANNER, HEADER]
    out.extend(bar.to_row() for bar in bars)
    return "\n".join(out) + "\n"


def loads_canonical(text: str) -> tuple[CanonicalBar, ...]:
    lines = text.splitlines()
    if len(lines) < 2 or lines[0] != BANNER or lines[1] != HEADER:
        raise SchemaViolation("not a canonical bar document (banner/header)")
    return tuple(CanonicalBar.from_row(line) for line in lines[2:] if line)


def canonical_dataset_hash(bars: Sequence[CanonicalBar]) -> str:
    """SHA-256 of the canonical document — THE dataset identity."""
    return hashlib.sha256(dumps_canonical(bars).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# series-level invariants
# ---------------------------------------------------------------------------

def validate_canonical_series(
    bars: Iterable[CanonicalBar], *, symbol: str,
) -> tuple[CanonicalBar, ...]:
    """Enforce the series invariants the per-bar model cannot see.

    * strict chronological ordering (``<``, so duplicates are rejected too);
    * one symbol per series.

    Raises :class:`SchemaViolation` — this is a contract, not a repair pass:
    nothing is sorted, deduplicated, or dropped here.
    """
    rows = tuple(bars)
    previous: datetime | None = None
    for index, bar in enumerate(rows):
        if bar.symbol != symbol:
            raise SchemaViolation(
                f"row {index}: symbol {bar.symbol!r} in a {symbol!r} series")
        if previous is not None:
            if bar.timestamp_utc == previous:
                raise SchemaViolation(
                    f"row {index}: duplicate timestamp {bar.timestamp_utc.isoformat()}")
            if bar.timestamp_utc < previous:
                raise SchemaViolation(
                    f"row {index}: out-of-order timestamp "
                    f"{bar.timestamp_utc.isoformat()} after {previous.isoformat()}")
        previous = bar.timestamp_utc
    return rows
