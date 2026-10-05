"""Venue symbol contracts — the metadata every cost number depends on.

A spread of "1.2" means nothing without the instrument contract. 1.2 what?
Points? Pips? Dollars? On EURUSD at 5 digits, 1.2 pips is 12 points is
$12 per standard lot. On XAUUSD at 2 digits, 1.2 "pips" is not even a
well-defined quantity. Getting this layer wrong silently scales every
downstream economic claim by 10x, so this module refuses to guess.

TWO RULES
---------
1. **Never derive what the terminal reports.** ``trade_tick_value`` in
   particular is a broker-computed, account-currency figure that already
   folds in the profit-currency conversion (critical for USDJPY, where
   profit accrues in JPY). Recomputing it from contract size would be
   wrong whenever the account currency is not the profit currency.
2. **Absent means absent.** Every field is optional and defaults to
   ``None``. ``None`` is never coerced to zero, and any conversion that
   needs a missing field raises :class:`SymbolContractMissing`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

#: Fields MT5 exposes via ``symbol_info`` that this authority binds.
REQUIRED_SYMBOL_FIELDS: tuple[str, ...] = (
    "digits", "point", "trade_tick_size", "trade_tick_value", "contract_size",
    "currency_base", "currency_profit", "currency_margin",
)


class SymbolContractMissing(RuntimeError):
    """A cost conversion was attempted without the metadata it requires."""


class PipConvention(StrEnum):
    """How a 'pip' relates to a 'point' for this instrument.

    Retail FX quotes fractional pips: a 5-digit EURUSD has point=0.00001
    and pip=0.0001, so one pip is ten points. A 3-digit USDJPY has
    point=0.001 and pip=0.01 — also ten points. Four- and two-digit feeds
    quote whole pips, where pip == point.

    Metals and CFDs have no agreed pip. Vendors variously call 0.1, 0.01
    or 1.0 "a pip" on gold, so this authority refuses the term entirely
    for them and reports price (instrument units) and points instead.
    """

    FX_FRACTIONAL = "FX_FRACTIONAL"        # pip = 10 * point (5 or 3 digits)
    FX_WHOLE = "FX_WHOLE"                  # pip = point      (4 or 2 digits)
    INSTRUMENT_UNITS = "INSTRUMENT_UNITS"  # no pip; quote in price units


def default_pip_convention(symbol: str, digits: int | None) -> PipConvention:
    """Convention implied by the symbol class and quoted digits.

    Metals/CFDs are forced to INSTRUMENT_UNITS regardless of digits,
    because 'pip' is not standardised for them.
    """
    root = symbol.upper()
    if root.startswith(("XAU", "XAG", "XPT", "XPD")):
        return PipConvention.INSTRUMENT_UNITS
    if digits in (3, 5):
        return PipConvention.FX_FRACTIONAL
    if digits in (2, 4):
        return PipConvention.FX_WHOLE
    return PipConvention.INSTRUMENT_UNITS


@dataclass(frozen=True)
class SymbolSpec:
    """One venue instrument contract. Every value field may be absent."""

    symbol: str
    broker_symbol: str | None = None
    digits: int | None = None
    point: float | None = None
    trade_tick_size: float | None = None
    trade_tick_value: float | None = None
    contract_size: float | None = None
    currency_base: str | None = None
    currency_profit: str | None = None
    currency_margin: str | None = None
    volume_min: float | None = None
    volume_step: float | None = None
    volume_max: float | None = None
    pip_convention: PipConvention | None = None
    source: str | None = None
    captured_at: str | None = None

    # -- status ---------------------------------------------------------
    def missing_fields(self) -> tuple[str, ...]:
        return tuple(f for f in REQUIRED_SYMBOL_FIELDS if getattr(self, f) is None)

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields()

    def _require(self, *names: str) -> None:
        absent = [n for n in names if getattr(self, n) is None]
        if absent:
            raise SymbolContractMissing(
                f"{self.symbol}: cannot convert without {absent}. "
                "SYMBOL_CONTRACT=MISSING — a missing contract field is not zero, "
                "and substituting a default here would silently rescale every "
                "downstream economic figure.")

    @property
    def convention(self) -> PipConvention:
        return self.pip_convention or default_pip_convention(self.symbol, self.digits)

    @property
    def pip_size(self) -> float:
        """Price increment of one pip, or raise for instrument-unit symbols."""
        self._require("point")
        convention = self.convention
        if convention is PipConvention.FX_FRACTIONAL:
            return self.point * 10.0
        if convention is PipConvention.FX_WHOLE:
            return self.point
        raise SymbolContractMissing(
            f"{self.symbol}: 'pip' is not defined for this instrument "
            f"(convention={convention}). Report price (instrument units) or "
            "points instead — vendors disagree on what a gold pip is, and "
            "picking one silently would make cross-venue numbers incomparable.")

    @property
    def has_pips(self) -> bool:
        return self.convention in (PipConvention.FX_FRACTIONAL, PipConvention.FX_WHOLE)

    # -- conversions ----------------------------------------------------
    def price_to_points(self, price_delta: float) -> float:
        self._require("point")
        return price_delta / self.point

    def points_to_price(self, points: float) -> float:
        self._require("point")
        return points * self.point

    def price_to_pips(self, price_delta: float) -> float:
        return price_delta / self.pip_size

    def pips_to_price(self, pips: float) -> float:
        return pips * self.pip_size

    def price_to_money(self, price_delta: float, volume_lots: float) -> float:
        """Account-currency cost of a price move over ``volume_lots``.

        Uses the MT5 identity
        ``money = price_delta / trade_tick_size * trade_tick_value * volume``.
        ``trade_tick_value`` is taken from the terminal, never derived: the
        broker has already converted it into the account currency, which is
        the only correct figure when profit currency differs from account
        currency (USDJPY on a USD account being the obvious case).
        """
        self._require("trade_tick_size", "trade_tick_value")
        if self.trade_tick_size == 0:
            raise SymbolContractMissing(
                f"{self.symbol}: trade_tick_size is zero; the venue contract is "
                "unusable for money conversion")
        return (price_delta / self.trade_tick_size) * self.trade_tick_value * volume_lots

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "broker_symbol": self.broker_symbol,
            "digits": self.digits,
            "point": self.point,
            "trade_tick_size": self.trade_tick_size,
            "trade_tick_value": self.trade_tick_value,
            "contract_size": self.contract_size,
            "currency_base": self.currency_base,
            "currency_profit": self.currency_profit,
            "currency_margin": self.currency_margin,
            "volume_min": self.volume_min,
            "volume_step": self.volume_step,
            "volume_max": self.volume_max,
            "pip_convention": str(self.convention),
            "pip_size": (self.pip_size if self.has_pips and self.point is not None
                         else None),
            "quote_unit": ("pips" if self.has_pips else "instrument_units"),
            "source": self.source,
            "captured_at": self.captured_at,
            "complete": self.is_complete,
            "missing_fields": list(self.missing_fields()),
        }


@dataclass
class SymbolRegistry:
    """Declared universe plus whatever metadata was actually captured."""

    venue: str
    account_class: str
    specs: dict[str, SymbolSpec] = field(default_factory=dict)

    def add(self, spec: SymbolSpec) -> None:
        self.specs[spec.symbol] = spec

    def get(self, symbol: str) -> SymbolSpec:
        try:
            return self.specs[symbol]
        except KeyError:
            raise SymbolContractMissing(
                f"{symbol!r} has no captured venue contract for "
                f"{self.venue}/{self.account_class}. Refusing to assume one."
            ) from None

    @property
    def complete_symbols(self) -> tuple[str, ...]:
        return tuple(sorted(s for s, spec in self.specs.items() if spec.is_complete))

    @property
    def incomplete_symbols(self) -> tuple[str, ...]:
        return tuple(sorted(s for s, spec in self.specs.items() if not spec.is_complete))

    def as_dict(self) -> dict:
        return {
            "venue": self.venue,
            "account_class": self.account_class,
            "symbol_count": len(self.specs),
            "complete_symbols": list(self.complete_symbols),
            "incomplete_symbols": list(self.incomplete_symbols),
            "symbols": {s: spec.as_dict() for s, spec in sorted(self.specs.items())},
        }


def empty_spec(symbol: str) -> SymbolSpec:
    """A fully-absent contract: the honest state before any capture."""
    return SymbolSpec(symbol=symbol)
