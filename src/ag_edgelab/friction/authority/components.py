"""Commission, slippage and swap authorities.

Each is a separate authority with its own evidence requirement, and each
defaults to MISSING. They are kept apart deliberately:

* **Spread** is observable from quotes alone.
* **Commission** is an account/contract fact. It is not in the quote feed.
* **Slippage** is a FILL fact. It cannot be inferred from bid/ask
  snapshots at any sampling rate, because a snapshot shows the quote that
  was displayed, not the price an order actually received.
* **Swap** is a financing fact, applicable only when a position is held
  across the venue rollover.

Conflating these is how an "all-in cost of 0.2 pips" assumption gets
manufactured. Every status here is explicit, and MISSING raises rather
than defaulting to zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

MISSING = "MISSING"


class AuthorityStatus(StrEnum):
    MISSING = "MISSING"
    CAPTURED = "CAPTURED"
    DECLARED_BY_VENUE = "DECLARED_BY_VENUE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class FrictionComponentMissing(RuntimeError):
    """A cost component was requested without the authority to supply it."""


# ---------------------------------------------------------------------------
# commission
# ---------------------------------------------------------------------------

class CommissionMode(StrEnum):
    """How the venue charges commission.

    The distinction between per-side and round-turn is a factor of two on
    the whole commission line, so it is never inferred.
    """

    PER_LOT_PER_SIDE = "PER_LOT_PER_SIDE"
    PER_LOT_ROUND_TURN = "PER_LOT_ROUND_TURN"
    PERCENT_OF_NOTIONAL_PER_SIDE = "PERCENT_OF_NOTIONAL_PER_SIDE"
    ZERO_COMMISSION_SPREAD_MARKUP = "ZERO_COMMISSION_SPREAD_MARKUP"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CommissionSpec:
    """Commission contract for one symbol (or the account default)."""

    symbol: str | None = None
    mode: CommissionMode = CommissionMode.UNKNOWN
    value: float | None = None
    currency: str | None = None
    scales_linearly_with_closed_volume: bool | None = None
    status: AuthorityStatus = AuthorityStatus.MISSING
    source: str | None = None
    source_hash: str | None = None
    note: str = ""

    @property
    def is_complete(self) -> bool:
        if self.status is AuthorityStatus.MISSING:
            return False
        if self.mode is CommissionMode.ZERO_COMMISSION_SPREAD_MARKUP:
            # A genuine zero still needs attribution and the partial-exit rule.
            return (self.currency is not None
                    and self.scales_linearly_with_closed_volume is not None
                    and bool(self.source))
        return (self.mode is not CommissionMode.UNKNOWN
                and self.value is not None
                and self.currency is not None
                and self.scales_linearly_with_closed_volume is not None
                and bool(self.source))

    def cost_for(self, *, volume_lots: float, sides: int,
                 notional: float | None = None) -> float:
        """Commission in account currency for ``sides`` crossings.

        ``sides=1`` is entry only; a full round trip is ``sides=2``. Modes
        quoted round-turn are halved per side so partial exits bill the
        volume they actually close and nothing more.
        """
        if not self.is_complete:
            raise FrictionComponentMissing(
                f"commission authority is {self.status} for "
                f"{self.symbol or 'account default'}; required fields are "
                f"{self.missing_fields()}. COMMISSION_AUTHORITY=MISSING — "
                "a generic industry assumption is not evidence.")
        if self.mode is CommissionMode.ZERO_COMMISSION_SPREAD_MARKUP:
            return 0.0
        if self.mode is CommissionMode.PER_LOT_PER_SIDE:
            return self.value * volume_lots * sides
        if self.mode is CommissionMode.PER_LOT_ROUND_TURN:
            return self.value * volume_lots * (sides / 2.0)
        if self.mode is CommissionMode.PERCENT_OF_NOTIONAL_PER_SIDE:
            if notional is None:
                raise FrictionComponentMissing(
                    "percent-of-notional commission needs a notional value")
            return self.value / 100.0 * notional * sides
        raise FrictionComponentMissing(f"unhandled commission mode {self.mode}")

    def missing_fields(self) -> tuple[str, ...]:
        out = []
        if self.status is AuthorityStatus.MISSING:
            out.append("status")
        if self.mode is CommissionMode.UNKNOWN:
            out.append("mode")
        if self.value is None and self.mode is not CommissionMode.ZERO_COMMISSION_SPREAD_MARKUP:
            out.append("value")
        if self.currency is None:
            out.append("currency")
        if self.scales_linearly_with_closed_volume is None:
            out.append("scales_linearly_with_closed_volume")
        if not self.source:
            out.append("source")
        return tuple(out)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "mode": str(self.mode),
            "value": self.value,
            "currency": self.currency,
            "scales_linearly_with_closed_volume":
                self.scales_linearly_with_closed_volume,
            "status": str(self.status),
            "source": self.source,
            "source_hash": self.source_hash,
            "complete": self.is_complete,
            "missing_fields": list(self.missing_fields()),
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# slippage
# ---------------------------------------------------------------------------

class SlippageEvidenceKind(StrEnum):
    NONE = "NONE"
    EXECUTED_FILL_HISTORY = "EXECUTED_FILL_HISTORY"
    VENUE_PUBLISHED_STATISTICS = "VENUE_PUBLISHED_STATISTICS"


@dataclass(frozen=True)
class SlippageAuthority:
    """Slippage status plus, when MISSING, what would close the gap."""

    status: AuthorityStatus = AuthorityStatus.MISSING
    evidence_kind: SlippageEvidenceKind = SlippageEvidenceKind.NONE
    sample_size: int | None = None
    median_points: float | None = None
    p90_points: float | None = None
    source: str | None = None
    source_hash: str | None = None
    future_evidence_requirement: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_complete(self) -> bool:
        return (self.status is AuthorityStatus.CAPTURED
                and self.evidence_kind is not SlippageEvidenceKind.NONE
                and self.sample_size is not None
                and self.median_points is not None)

    def cost_points(self, *, conservative: bool = True) -> float:
        if not self.is_complete:
            raise FrictionComponentMissing(
                "SLIPPAGE_AUTHORITY=MISSING. Slippage is a property of FILLS, "
                "not of quotes: a bid/ask snapshot records the price that was "
                "displayed, never the price an order received. No sampling rate "
                "of quotes can recover it, and inventing a 0.1-pip allowance "
                "would fabricate the single number most likely to decide "
                "marginal economics.")
        return self.p90_points if (conservative and self.p90_points is not None) \
            else self.median_points

    def as_dict(self) -> dict:
        return {
            "status": str(self.status),
            "evidence_kind": str(self.evidence_kind),
            "sample_size": self.sample_size,
            "median_points": self.median_points,
            "p90_points": self.p90_points,
            "source": self.source,
            "source_hash": self.source_hash,
            "complete": self.is_complete,
            "why_quotes_are_insufficient": (
                "Slippage is the difference between the decision price and the "
                "achieved fill. Quote snapshots contain no fills, so slippage is "
                "not estimable from spread evidence at any sampling rate."),
            "future_evidence_requirement": list(self.future_evidence_requirement),
        }


DEFAULT_SLIPPAGE_REQUIREMENT: tuple[str, ...] = (
    "Read-only MT5 deal history (order_get_deals / history_deals_get) covering "
    "executed fills, with requested price and achieved price per deal.",
    "At least a few hundred fills per symbol spread across sessions, so the "
    "tail is observed and not just the quiet median.",
    "Deal-level timestamps so each fill can be matched to the prevailing quote.",
    "Explicit separation of market, limit and stop fills — limit orders cannot "
    "slip negatively in the same way market orders can.",
    "If no live account history exists, slippage stays MISSING: this mission "
    "places no orders and will not manufacture fills to measure.",
)


# ---------------------------------------------------------------------------
# swap / financing
# ---------------------------------------------------------------------------

class SwapMode(StrEnum):
    """MT5 ``SYMBOL_SWAP_MODE``, named.

    ``DISABLED`` is a captured venue fact (the symbol charges no
    financing), which is categorically different from ``UNKNOWN`` (we did
    not look, or could not read it).
    """

    DISABLED = "DISABLED"
    POINTS = "POINTS"
    BASE_CURRENCY = "BASE_CURRENCY"
    INTEREST = "INTEREST"
    MARGIN_CURRENCY = "MARGIN_CURRENCY"
    UNKNOWN = "UNKNOWN"


class SwapApplicability(StrEnum):
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNDETERMINED = "UNDETERMINED"


@dataclass(frozen=True)
class SwapSpec:
    """Overnight financing for one symbol."""

    symbol: str
    swap_long: float | None = None
    swap_short: float | None = None
    swap_mode: SwapMode = SwapMode.UNKNOWN
    swap_rollover_3days: int | None = None
    status: AuthorityStatus = AuthorityStatus.MISSING
    source: str | None = None

    @property
    def is_complete(self) -> bool:
        if self.status is AuthorityStatus.MISSING:
            return False
        if self.swap_mode is SwapMode.UNKNOWN:
            return False
        if self.swap_mode is SwapMode.DISABLED:
            return True  # the venue charges nothing; that is the fact
        return self.swap_long is not None and self.swap_short is not None

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "swap_long": self.swap_long,
            "swap_short": self.swap_short,
            "swap_mode": str(self.swap_mode),
            "swap_rollover_3days": self.swap_rollover_3days,
            "status": str(self.status),
            "source": self.source,
            "complete": self.is_complete,
        }


def determine_swap_applicability(
    *,
    strategy_contract_closes_before_rollover: bool | None,
    contract_is_frozen: bool,
    max_holding_minutes: int | None = None,
) -> tuple[SwapApplicability, str]:
    """Decide whether swap can be excluded for a strategy lifecycle.

    NOT_APPLICABLE is only returned when a FROZEN strategy contract
    positively proves there is no rollover exposure. An unfrozen contract,
    or an unproven claim, yields UNDETERMINED and swap stays active —
    the asymmetry is deliberate, because wrongly excluding financing
    flatters every carry-negative position.
    """
    if strategy_contract_closes_before_rollover is None:
        return (SwapApplicability.UNDETERMINED,
                "no strategy contract supplied; swap remains active because "
                "rollover exposure has not been excluded")
    if not contract_is_frozen:
        return (SwapApplicability.UNDETERMINED,
                "the strategy contract is not frozen, so a 'closes before "
                "rollover' claim is not binding; swap remains active")
    if not strategy_contract_closes_before_rollover:
        return (SwapApplicability.APPLICABLE,
                "the frozen contract permits holding across rollover")
    detail = ("the frozen contract forces exit before the venue rollover, so "
              "no position can be open at the financing snapshot")
    if max_holding_minutes is not None:
        detail += f" (max holding {max_holding_minutes} min)"
    return SwapApplicability.NOT_APPLICABLE, detail
