"""Friction authority: the SCHEMA, deliberately without the VALUES.

DATA_AUTHORITY_R1 section 11 requires separating two things that are
routinely conflated:

``FRICTION_FRAMEWORK``        the code and schema that can carry, validate
                              and apply execution costs. Already present as
                              :mod:`ag_edgelab.friction.model` (R-space
                              scenarios, funding schedules, the
                              NET_ECONOMIC_QUALIFICATION gate) and completed
                              here with the per-venue quote schema.

``FRICTION_VALUE_AUTHORITY``  actual broker-sourced numbers — spreads,
                              commission, swap, contract specs — with
                              provenance and hashes.

The framework can be finished in this environment. The value authority
CANNOT: it requires a VT Markets account/terminal that does not exist here.
So every value field below is NULL and stays NULL.

NULL SEMANTICS — the central rule of this module
------------------------------------------------
NULL means "not measured". It does NOT mean zero.

:func:`net_economics_estimable` returns False whenever any required value
is NULL, and :func:`assert_estimable` raises. There is no default, no
fallback constant, and no "reasonable assumption" anywhere in this file.
A net/economic claim built on NULL friction is unreachable by construction
rather than merely discouraged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

FRICTION_QUOTE_SCHEMA_VERSION = "EDGELAB_FRICTION_QUOTE_V1"

#: Fields a venue observation must supply before any net claim is possible.
REQUIRED_VALUE_FIELDS: tuple[str, ...] = (
    "bid", "ask", "spread_points", "spread_pips", "commission",
    "swap_long", "swap_short", "contract_size", "tick_size", "tick_value",
)

#: Fields identifying WHERE a value came from. Also mandatory: an
#: unattributed number is not evidence.
REQUIRED_PROVENANCE_FIELDS: tuple[str, ...] = (
    "symbol", "venue", "account_type", "timestamp", "source", "source_hash",
)


class FrictionAuthorityMissing(RuntimeError):
    """Raised when a net/economic quantity is requested without authority."""


@dataclass(frozen=True)
class FrictionQuote:
    """One venue cost observation. Every value field is optional and NULL
    by default, because this environment has no authoritative broker feed."""

    # provenance
    symbol: str
    venue: str
    account_type: str
    timestamp: datetime | None = None
    source: str | None = None
    source_hash: str | None = None
    # values — NULL means NOT MEASURED, never zero
    bid: float | None = None
    ask: float | None = None
    spread_points: float | None = None
    spread_pips: float | None = None
    commission: float | None = None
    swap_long: float | None = None
    swap_short: float | None = None
    contract_size: float | None = None
    tick_size: float | None = None
    tick_value: float | None = None

    def missing_value_fields(self) -> tuple[str, ...]:
        return tuple(f for f in REQUIRED_VALUE_FIELDS if getattr(self, f) is None)

    def missing_provenance_fields(self) -> tuple[str, ...]:
        return tuple(f for f in REQUIRED_PROVENANCE_FIELDS if getattr(self, f) is None)

    @property
    def is_complete(self) -> bool:
        return not self.missing_value_fields() and not self.missing_provenance_fields()

    def as_dict(self) -> dict:
        return {
            "schema_version": FRICTION_QUOTE_SCHEMA_VERSION,
            "symbol": self.symbol,
            "venue": self.venue,
            "account_type": self.account_type,
            "timestamp": (None if self.timestamp is None
                          else self.timestamp.isoformat().replace("+00:00", "Z")),
            "bid": self.bid,
            "ask": self.ask,
            "spread_points": self.spread_points,
            "spread_pips": self.spread_pips,
            "commission": self.commission,
            "swap_long": self.swap_long,
            "swap_short": self.swap_short,
            "contract_size": self.contract_size,
            "tick_size": self.tick_size,
            "tick_value": self.tick_value,
            "source": self.source,
            "source_hash": self.source_hash,
            "complete": self.is_complete,
            "missing_value_fields": list(self.missing_value_fields()),
            "missing_provenance_fields": list(self.missing_provenance_fields()),
        }


def empty_quote(symbol: str, venue: str, account_type: str) -> FrictionQuote:
    """A fully-NULL quote: the honest state when nothing was measured."""
    return FrictionQuote(symbol=symbol, venue=venue, account_type=account_type)


def net_economics_estimable(quotes: Iterable[FrictionQuote]) -> bool:
    """True only if every supplied quote is complete AND at least one exists."""
    rows = list(quotes)
    return bool(rows) and all(q.is_complete for q in rows)


def assert_estimable(quotes: Iterable[FrictionQuote], *, context: str) -> None:
    """Fail closed on any attempt to compute net economics without authority."""
    rows = list(quotes)
    if not rows:
        raise FrictionAuthorityMissing(
            f"{context}: no friction quotes supplied. ECONOMIC_METRICS="
            "NOT_ESTIMABLE_NO_FRICTION_AUTHORITY. A missing value is not zero.")
    incomplete = {
        q.symbol: list(q.missing_value_fields() + q.missing_provenance_fields())
        for q in rows if not q.is_complete
    }
    if incomplete:
        raise FrictionAuthorityMissing(
            f"{context}: friction authority incomplete for {sorted(incomplete)}; "
            f"missing fields {incomplete}. ECONOMIC_METRICS="
            "NOT_ESTIMABLE_NO_FRICTION_AUTHORITY. Substituting an assumed value "
            "here would manufacture an economic claim out of nothing.")


@dataclass
class FrictionAuthorityStatus:
    """The gap record: what exists, what does not, and what would close it."""

    framework_ready: bool
    value_authority_complete: bool
    symbols: tuple[str, ...]
    venue: str
    account_type: str
    quotes: tuple[FrictionQuote, ...] = field(default_factory=tuple)
    blockers: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "FRICTION_FRAMEWORK_READY": "YES" if self.framework_ready else "NO",
            "FRICTION_AUTHORITY_COMPLETE": (
                "YES" if self.value_authority_complete else "NO"),
            "venue": self.venue,
            "account_type": self.account_type,
            "symbols": list(self.symbols),
            "null_semantics": (
                "NULL means NOT MEASURED. It never means zero. "
                "net_economics_estimable() is False and assert_estimable() "
                "raises while any required field is NULL, so no net claim can "
                "be produced from this record by accident."
            ),
            "quotes": [q.as_dict() for q in self.quotes],
            "blockers": list(self.blockers),
        }
