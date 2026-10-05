"""SYMBOL METADATA AUTHORITY — instrument normalization for GEN2 research.

WHY THIS MODULE EXISTS
----------------------
The V2 prototype carried universal price assumptions (``0.0001`` style pip
arithmetic is the classic one) that are silently wrong for USDJPY and
catastrophically wrong for XAUUSD. Any rule expressed in absolute price units
is therefore not one rule but four different rules wearing the same name.

Every distance in the hardened contract — sweep depth, retest tolerance, stop
geometry, boundary proximity — must be expressed in INSTRUMENT-NORMALIZED
units resolved through this module.

PROVENANCE RULE (binding)
-------------------------
These values come from the quoting convention of the instrument. **None of
them was inferred, fitted, or selected from strategy performance.** Changing a
value here changes the contract hash, which invalidates a preregistration.

UNIT VOCABULARY (kept deliberately separate)
--------------------------------------------
PRICE_UNIT  the unit the quote is denominated in (quote currency per base,
            or USD per troy ounce for XAUUSD). Reporting only.
TICK_SIZE   the smallest representable price increment in the source feed.
            This is the only unit with ARITHMETIC authority in the rules: it
            defines what "strictly beyond a level" means at machine precision.
POINT       the last-decimal increment. For a 5-digit FX feed POINT ==
            TICK_SIZE; the two are kept separate because they diverge on
            feeds that quote fractional ticks.
PIP_SIZE    the conventional dealing unit. REPORTING ONLY — no rule may use
            it, because the gold convention is genuinely ambiguous (see
            XAUUSD below) and we refuse to let an ambiguity enter a rule.

STRUCTURAL UNITS ARE PREFERRED OVER ALL OF THE ABOVE
----------------------------------------------------
Where a rule needs a magnitude rather than a precision floor, it is expressed
as a FRACTION OF THE REFERENCE SESSION RANGE — a quantity measured from the
market itself, on the day, in the instrument's own scale. That is
dimensionless and therefore identical across all four symbols. TICK_SIZE is
used only as a non-degeneracy floor.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

METADATA_AUTHORITY_ID = "GEN2_SYMBOL_METADATA_AUTHORITY_V1"
METADATA_SOURCE = (
    "Instrument quoting convention of the HISTDATA_ASCII_M1 generic feed. "
    "Declared a priori; NEVER inferred from strategy performance."
)


@dataclass(frozen=True)
class SymbolMetadata:
    """Frozen per-instrument normalization record."""

    symbol: str
    price_unit: str
    digits: int
    tick_size: float
    point: float
    pip_size: float
    pip_convention_note: str

    def ticks(self, price_distance: float) -> float:
        """Express an absolute price distance in ticks."""
        return abs(price_distance) / self.tick_size

    def at_least_one_tick(self, price_distance: float) -> bool:
        """Is this distance real at machine precision, or float noise?

        Uses a half-tick guard so that a distance that *is* exactly one tick
        survives binary rounding in the feed's decimal-to-float conversion.
        """
        return abs(price_distance) >= self.tick_size * 0.5


#: The four admitted instruments. A symbol absent from this table has NO
#: metadata authority and must be refused rather than defaulted.
SYMBOL_METADATA: Mapping[str, SymbolMetadata] = {
    "EURUSD": SymbolMetadata(
        symbol="EURUSD",
        price_unit="USD_PER_EUR",
        digits=5,
        tick_size=0.00001,
        point=0.00001,
        pip_size=0.0001,
        pip_convention_note="Standard 4th-decimal FX pip on a 5-digit feed.",
    ),
    "GBPUSD": SymbolMetadata(
        symbol="GBPUSD",
        price_unit="USD_PER_GBP",
        digits=5,
        tick_size=0.00001,
        point=0.00001,
        pip_size=0.0001,
        pip_convention_note="Standard 4th-decimal FX pip on a 5-digit feed.",
    ),
    "USDJPY": SymbolMetadata(
        symbol="USDJPY",
        price_unit="JPY_PER_USD",
        digits=3,
        tick_size=0.001,
        point=0.001,
        pip_size=0.01,
        pip_convention_note=(
            "JPY-quoted pair: the pip is the 2nd decimal, 100x the EURUSD pip "
            "in absolute price. This is precisely the assumption that a "
            "universal 0.0001 constant gets wrong by two orders of magnitude."
        ),
    ),
    "XAUUSD": SymbolMetadata(
        symbol="XAUUSD",
        price_unit="USD_PER_TROY_OUNCE",
        digits=2,
        tick_size=0.01,
        point=0.01,
        pip_size=0.1,
        pip_convention_note=(
            "AMBIGUOUS BY CONVENTION. Gold is variously dealt in $1.00, $0.10 "
            "and $0.01 'pips' depending on venue. We declare 0.1 for "
            "REPORTING ONLY and forbid any rule from consuming pip_size, so "
            "the ambiguity cannot reach a research result. Rules use "
            "tick_size (unambiguous) and reference-range fractions "
            "(dimensionless)."
        ),
    ),
}

SYMBOL_UNIVERSE: tuple[str, ...] = tuple(sorted(SYMBOL_METADATA))

#: Rules may consume these fields; pip_size is deliberately NOT among them.
RULE_ADMISSIBLE_FIELDS: tuple[str, ...] = ("tick_size", "point")
RULE_FORBIDDEN_FIELDS: tuple[str, ...] = ("pip_size",)


class UnknownSymbolError(KeyError):
    """Raised instead of defaulting when a symbol has no metadata record."""


def metadata_for(symbol: str) -> SymbolMetadata:
    """Resolve instrument metadata, failing closed on an unknown symbol."""
    try:
        return SYMBOL_METADATA[symbol]
    except KeyError as exc:  # pragma: no cover - exercised by tests
        raise UnknownSymbolError(
            f"{symbol!r} has no metadata authority; refusing to assume a "
            f"default tick size. Admitted: {SYMBOL_UNIVERSE}"
        ) from exc


def validate_observed_precision(symbol: str, prices: list[float]) -> dict:
    """Runtime check that the feed agrees with the declared TICK_SIZE.

    Declared metadata is an a-priori claim about the data. This turns it into
    a falsifiable one: every observed price must be an integer multiple of the
    declared tick size (within float tolerance). Returns a diagnostic record;
    callers decide whether a mismatch is fatal.
    """
    meta = metadata_for(symbol)
    violations = 0
    for price in prices:
        quotient = price / meta.tick_size
        if abs(quotient - round(quotient)) > 1e-6:
            violations += 1
    return {
        "symbol": symbol,
        "declared_tick_size": meta.tick_size,
        "prices_checked": len(prices),
        "violations": violations,
        "consistent": violations == 0,
    }


def metadata_contract() -> dict:
    """Frozen, hashable projection of the metadata authority."""
    return {
        "authority_id": METADATA_AUTHORITY_ID,
        "source": METADATA_SOURCE,
        "inferred_from_performance": False,
        "rule_admissible_fields": list(RULE_ADMISSIBLE_FIELDS),
        "rule_forbidden_fields": list(RULE_FORBIDDEN_FIELDS),
        "forbidden_field_rationale": (
            "pip_size is ambiguous for XAUUSD; admitting it into a rule would "
            "make the rule venue-dependent."
        ),
        "symbols": {
            sym: {
                "price_unit": m.price_unit,
                "digits": m.digits,
                "tick_size": m.tick_size,
                "point": m.point,
                "pip_size_reporting_only": m.pip_size,
                "pip_convention_note": m.pip_convention_note,
            }
            for sym, m in sorted(SYMBOL_METADATA.items())
        },
    }
