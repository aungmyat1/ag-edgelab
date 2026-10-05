"""Broker symbol resolution and raw ``symbol_info`` snapshots.

WHY THIS EXISTS
---------------
``FRICTION_AUTHORITY_R1``'s capture tool asked the terminal for
``EURUSD`` literally. Most retail MT5 venues do not serve that name:
they serve ``EURUSD.r``, ``EURUSD-VIP``, ``EURUSDx``, ``EURUSD.pro`` or
some other account-class decoration. Asking for the bare name on such an
account returns ``None`` and the capture silently yields nothing.

Guessing the suffix is worse than failing. A wrong guess can resolve to
a *different contract* — a mini lot, a different swap schedule, a
different commission tier — and every downstream cost number would then
describe an instrument the owner does not trade.

So this module never constructs a candidate name. It reads the symbols
the terminal actually publishes and matches against them, deterministic
and ambiguity-aware: when more than one broker symbol could be the
canonical instrument, the ambiguity is recorded and the choice is made
by a declared rule, not by luck of iteration order.

Everything here is pure. The MetaTrader5 package is Windows-only, but
resolution logic is the part most likely to be wrong, so it is written
to be fully testable on any platform against recorded symbol lists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

#: The four FX/metal instruments EdgeLab's governed evidence uses.
CANONICAL_FX: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")

#: Alternate venue names for the same contract. Only names that are
#: unambiguous industry synonyms appear here — never account-class
#: suffixes, which are matched structurally instead.
CANONICAL_ALIASES: dict[str, tuple[str, ...]] = {
    "XAUUSD": ("GOLD", "GOLDUSD", "XAUUSD"),
}

#: Base assets treated as crypto when discovering the owner's symbols.
#: Used for DISCOVERY only; nothing is assumed to be present.
CRYPTO_BASES: tuple[str, ...] = (
    "BTC", "XBT", "ETH", "LTC", "XRP", "BCH", "ADA", "SOL", "DOT", "DOGE",
)

#: Quote assets a crypto pair may settle in.
CRYPTO_QUOTES: tuple[str, ...] = ("USD", "USDT", "USDC", "EUR")

#: Every ``symbol_info`` field this mission requires (§3). Anything the
#: terminal does not expose is recorded as ``None`` and stays ``None``.
EXTENDED_SYMBOL_FIELDS: tuple[str, ...] = (
    "digits", "point", "spread", "spread_float",
    "trade_tick_size", "trade_tick_value",
    "trade_tick_value_profit", "trade_tick_value_loss",
    "trade_contract_size",
    "currency_base", "currency_profit", "currency_margin",
    "volume_min", "volume_max", "volume_step",
    "swap_long", "swap_short", "swap_mode", "swap_rollover3days",
    "trade_stops_level", "trade_freeze_level",
    "trade_mode", "trade_calc_mode", "trade_exemode",
    "visible", "select", "path", "description",
)


class ResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    RESOLVED_AMBIGUOUS = "RESOLVED_AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"


def normalize(name: str) -> str:
    """Uppercase alphanumeric core of a broker symbol name."""
    return re.sub(r"[^A-Z0-9]", "", (name or "").upper())


def _strip_suffix(normalized: str, canonical: str) -> str | None:
    """Return the trailing decoration if ``normalized`` extends ``canonical``."""
    if normalized == canonical:
        return ""
    if normalized.startswith(canonical):
        return normalized[len(canonical):]
    return None


@dataclass(frozen=True)
class SymbolCandidate:
    """One broker symbol that could be the canonical instrument."""

    broker_symbol: str
    suffix: str
    visible: bool | None = None
    selectable: bool | None = None
    path: str | None = None

    def rank(self) -> tuple:
        """Deterministic preference. Lower sorts first.

        The rule, declared rather than emergent:
        1. an exact name match beats a decorated one;
        2. a symbol already visible in Market Watch beats a hidden one,
           because that is the contract the owner actually looks at;
        3. shorter decoration beats longer;
        4. lexicographic, so the result never depends on iteration order.
        """
        return (
            0 if self.suffix == "" else 1,
            0 if self.visible else 1,
            len(self.suffix),
            self.broker_symbol,
        )


@dataclass
class SymbolResolution:
    canonical: str
    status: ResolutionStatus
    broker_symbol: str | None = None
    candidates: list[SymbolCandidate] = field(default_factory=list)
    rule: str = ""
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "canonical": self.canonical,
            "status": str(self.status),
            "broker_symbol": self.broker_symbol,
            "candidate_count": len(self.candidates),
            "candidates": [
                {"broker_symbol": c.broker_symbol, "suffix": c.suffix,
                 "visible": c.visible, "selectable": c.selectable,
                 "path": c.path}
                for c in sorted(self.candidates, key=lambda c: c.rank())],
            "rule": self.rule,
            "note": self.note,
        }


def resolve_one(canonical: str, available: list[dict]) -> SymbolResolution:
    """Match one canonical instrument against the terminal's symbol list.

    ``available`` is a list of dicts with at least ``name``, optionally
    ``visible``, ``select`` and ``path`` — i.e. whatever ``symbols_get()``
    returned, already converted to plain dicts.
    """
    roots = {normalize(canonical)}
    roots.update(normalize(a) for a in CANONICAL_ALIASES.get(canonical, ()))

    candidates: list[SymbolCandidate] = []
    for entry in available:
        name = entry.get("name") or ""
        norm = normalize(name)
        for root in roots:
            suffix = _strip_suffix(norm, root)
            if suffix is None:
                continue
            # A trailing run of digits usually denotes a *different*
            # contract (EURUSD2, EURUSD500), not an account-class tag.
            if suffix and suffix.isdigit():
                continue
            candidates.append(SymbolCandidate(
                broker_symbol=name, suffix=suffix,
                visible=entry.get("visible"), selectable=entry.get("select"),
                path=entry.get("path")))
            break

    if not candidates:
        return SymbolResolution(
            canonical=canonical, status=ResolutionStatus.NOT_FOUND,
            rule="no published broker symbol shares this canonical root",
            note=("Not found. No name was constructed or guessed: a "
                  "fabricated suffix could resolve to a different contract "
                  "with different lot size, swap and commission."))

    ordered = sorted(candidates, key=lambda c: c.rank())
    best = ordered[0]
    ambiguous = len(ordered) > 1
    return SymbolResolution(
        canonical=canonical,
        status=(ResolutionStatus.RESOLVED_AMBIGUOUS if ambiguous
                else ResolutionStatus.RESOLVED),
        broker_symbol=best.broker_symbol,
        candidates=ordered,
        rule="exact-match > visible > shortest-suffix > lexicographic",
        note=("" if not ambiguous else
              f"{len(ordered)} broker symbols share this root; the declared "
              "rule selected one and every candidate is recorded so the "
              "choice can be audited or overridden."))


def discover_crypto(available: list[dict]) -> list[SymbolCandidate]:
    """Find crypto instruments the account actually publishes.

    Nothing is assumed about which two the owner trades; this reports
    what exists so the owner can confirm.
    """
    found: list[SymbolCandidate] = []
    for entry in available:
        name = entry.get("name") or ""
        norm = normalize(name)
        for base in CRYPTO_BASES:
            if not norm.startswith(base):
                continue
            rest = norm[len(base):]
            for quote in CRYPTO_QUOTES:
                if rest.startswith(quote):
                    found.append(SymbolCandidate(
                        broker_symbol=name, suffix=rest[len(quote):],
                        visible=entry.get("visible"),
                        selectable=entry.get("select"),
                        path=entry.get("path")))
                    break
            else:
                continue
            break
    return sorted(found, key=lambda c: c.rank())


def resolve_all(canonicals: tuple[str, ...], available: list[dict]) -> dict:
    """Resolve every canonical instrument and discover crypto symbols."""
    resolutions = {c: resolve_one(c, available) for c in canonicals}
    crypto = discover_crypto(available)
    unresolved = [c for c, r in resolutions.items()
                  if r.status is ResolutionStatus.NOT_FOUND]
    return {
        "schema": "VT_MARKETS_SYMBOL_RESOLUTION_V1",
        "broker_symbol_count": len(available),
        "canonical_requested": list(canonicals),
        "resolutions": {c: r.as_dict() for c, r in resolutions.items()},
        "mapping": {c: r.broker_symbol for c, r in resolutions.items()
                    if r.broker_symbol},
        "unresolved": unresolved,
        "all_resolved": not unresolved,
        "crypto_discovered": [
            {"broker_symbol": c.broker_symbol, "suffix": c.suffix,
             "visible": c.visible, "path": c.path} for c in crypto],
        "crypto_count": len(crypto),
        "suffix_policy": (
            "Suffixes are never constructed. Only names the terminal "
            "publishes are matched, and every candidate is recorded."),
    }


def raw_symbol_info(info, *, broker_symbol: str) -> dict:
    """Snapshot every required ``symbol_info`` field verbatim.

    Absent fields are ``None``. They are never defaulted to zero: a
    missing ``trade_tick_value`` is unknown, and zero would silently
    make the instrument look free to trade.
    """
    snapshot: dict = {"broker_symbol": broker_symbol}
    missing: list[str] = []
    for fieldname in EXTENDED_SYMBOL_FIELDS:
        value = getattr(info, fieldname, None)
        if value is None:
            missing.append(fieldname)
        snapshot[fieldname] = value
    snapshot["_missing_fields"] = missing
    snapshot["_complete"] = not missing
    return snapshot
