"""VT_MARKETS_FRICTION_AUTHORITY_V1: the binding, hashed friction contract.

The contract binds, in one hashed object: the venue and account class,
the capture window, the per-symbol venue contract, the spread evidence
hashes, the commission/slippage/swap authorities, the cost-allocation
semantics and the scenario contract.

Two mismatch checks are first-class, because both failures are silent
and both invalidate everything downstream:

* **Venue identity mismatch** — friction captured on a demo server, or a
  different broker entity, priced against a live account.
* **Symbol metadata mismatch** — the contract says ``digits=5,
  contract_size=100000`` and the terminal now reports something else, so
  every money conversion in the authority is wrong.

Both raise. Neither is auto-repaired.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum

from ag_edgelab.friction.authority.components import (
    AuthorityStatus, CommissionSpec, SlippageAuthority, SwapApplicability, SwapSpec,
)
from ag_edgelab.friction.authority.scenarios import (
    HISTORICAL_FRICTION_LIMITATION, HistoricalCostPolicy, ScenarioContract,
)
from ag_edgelab.friction.authority.symbols import SymbolSpec

FRICTION_AUTHORITY_ID = "VT_MARKETS_FRICTION_AUTHORITY_V1"


class VenueIdentityMismatch(RuntimeError):
    """The venue the evidence came from is not the venue being priced."""


class SymbolMetadataMismatch(RuntimeError):
    """The symbol contract changed under a frozen friction authority."""


class AccountClass(StrEnum):
    DEMO = "DEMO"
    LIVE = "LIVE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class VenueIdentity:
    """Who actually produced the evidence."""

    broker: str | None = None
    server: str | None = None
    account_class: AccountClass = AccountClass.UNKNOWN
    account_type: str | None = None
    account_currency: str | None = None
    terminal_build: int | None = None

    @property
    def is_complete(self) -> bool:
        return (bool(self.broker) and bool(self.server)
                and self.account_class is not AccountClass.UNKNOWN
                and bool(self.account_currency))

    def assert_matches(self, other: "VenueIdentity") -> None:
        diffs = []
        for fname in ("broker", "server", "account_class", "account_currency"):
            a, b = getattr(self, fname), getattr(other, fname)
            if a != b:
                diffs.append(f"{fname}: authority={a!r} runtime={b!r}")
        if diffs:
            raise VenueIdentityMismatch(
                "friction authority was captured on a different venue identity "
                "than the one being priced; costs are not transferable between "
                "brokers, servers or account classes. Differences: "
                + "; ".join(diffs))

    def as_dict(self) -> dict:
        return {
            "broker": self.broker,
            "server": self.server,
            "account_class": str(self.account_class),
            "account_type": self.account_type,
            "account_currency": self.account_currency,
            "terminal_build": self.terminal_build,
            "complete": self.is_complete,
        }


def assert_symbol_metadata_matches(authority: SymbolSpec,
                                   runtime: SymbolSpec) -> None:
    """Every money-affecting field must be identical."""
    if authority.symbol != runtime.symbol:
        raise SymbolMetadataMismatch(
            f"symbol mismatch: {authority.symbol!r} vs {runtime.symbol!r}")
    diffs = []
    for fname in ("digits", "point", "trade_tick_size", "trade_tick_value",
                  "contract_size", "currency_base", "currency_profit",
                  "currency_margin"):
        a, b = getattr(authority, fname), getattr(runtime, fname)
        if a is None and b is None:
            continue
        if a is None or b is None or (
                isinstance(a, float) and abs(a - b) > 1e-12) or (
                not isinstance(a, float) and a != b):
            diffs.append(f"{fname}: authority={a!r} runtime={b!r}")
    if diffs:
        raise SymbolMetadataMismatch(
            f"symbol contract for {authority.symbol} changed under a frozen "
            f"friction authority; every money conversion derived from it is "
            f"invalid until re-captured. Differences: " + "; ".join(diffs))


@dataclass
class FrictionAuthorityContract:
    """The full, hashable friction authority."""

    venue: VenueIdentity = field(default_factory=VenueIdentity)
    symbols: dict[str, SymbolSpec] = field(default_factory=dict)
    commissions: dict[str, CommissionSpec] = field(default_factory=dict)
    swaps: dict[str, SwapSpec] = field(default_factory=dict)
    slippage: SlippageAuthority = field(default_factory=SlippageAuthority)
    swap_applicability: SwapApplicability = SwapApplicability.UNDETERMINED
    swap_applicability_reason: str = ""
    spread_evidence: dict[str, dict] = field(default_factory=dict)
    capture_started_utc: str | None = None
    capture_ended_utc: str | None = None
    spread_convention: str = "FULL_SPREAD_ON_ENTRY"
    scenario_contract: ScenarioContract = field(default_factory=ScenarioContract)
    historical_policy: HistoricalCostPolicy = field(
        default_factory=HistoricalCostPolicy)

    # -- status ---------------------------------------------------------
    @property
    def spread_authority_status(self) -> AuthorityStatus:
        if not self.spread_evidence:
            return AuthorityStatus.MISSING
        if any(e.get("n", 0) > 0 for e in self.spread_evidence.values()):
            return AuthorityStatus.CAPTURED
        return AuthorityStatus.MISSING

    @property
    def commission_authority_status(self) -> AuthorityStatus:
        if not self.commissions:
            return AuthorityStatus.MISSING
        if all(c.is_complete for c in self.commissions.values()):
            return AuthorityStatus.CAPTURED
        return AuthorityStatus.MISSING

    @property
    def swap_authority_status(self) -> AuthorityStatus:
        if self.swap_applicability is SwapApplicability.NOT_APPLICABLE:
            return AuthorityStatus.NOT_APPLICABLE
        if self.swaps and all(s.is_complete for s in self.swaps.values()):
            return AuthorityStatus.CAPTURED
        return AuthorityStatus.MISSING

    @property
    def is_complete(self) -> bool:
        return (self.venue.is_complete
                and bool(self.symbols)
                and all(s.is_complete for s in self.symbols.values())
                and self.spread_authority_status is AuthorityStatus.CAPTURED
                and self.commission_authority_status is AuthorityStatus.CAPTURED
                and self.slippage.is_complete
                and self.swap_authority_status in (
                    AuthorityStatus.CAPTURED, AuthorityStatus.NOT_APPLICABLE))

    def blockers(self) -> list[str]:
        out: list[str] = []
        if not self.venue.is_complete:
            out.append("VENUE_IDENTITY incomplete (broker/server/account class"
                       "/account currency required)")
        if not self.symbols:
            out.append("no symbol contracts captured")
        for sym, spec in sorted(self.symbols.items()):
            if not spec.is_complete:
                out.append(f"symbol contract {sym} missing "
                           f"{list(spec.missing_fields())}")
        if self.spread_authority_status is not AuthorityStatus.CAPTURED:
            out.append("SPREAD_AUTHORITY=MISSING (no quote observations)")
        if self.commission_authority_status is not AuthorityStatus.CAPTURED:
            out.append("COMMISSION_AUTHORITY=MISSING")
        if not self.slippage.is_complete:
            out.append("SLIPPAGE_AUTHORITY=MISSING (requires read-only fill "
                       "history; not inferable from quotes)")
        if self.swap_authority_status is AuthorityStatus.MISSING:
            out.append(f"SWAP_AUTHORITY=MISSING with applicability "
                       f"{self.swap_applicability}")
        return out

    # -- serialisation --------------------------------------------------
    def payload(self) -> dict:
        """The canonical, hashed body. Deterministic key order."""
        return {
            "friction_authority_id": FRICTION_AUTHORITY_ID,
            "venue": self.venue.as_dict(),
            "capture_window_utc": {
                "started": self.capture_started_utc,
                "ended": self.capture_ended_utc,
            },
            "symbols": {k: self.symbols[k].as_dict()
                        for k in sorted(self.symbols)},
            "spread_evidence": {k: self.spread_evidence[k]
                                for k in sorted(self.spread_evidence)},
            "commission": {k: self.commissions[k].as_dict()
                           for k in sorted(self.commissions)},
            "slippage": self.slippage.as_dict(),
            "swap": {
                "applicability": str(self.swap_applicability),
                "applicability_reason": self.swap_applicability_reason,
                "per_symbol": {k: self.swaps[k].as_dict()
                               for k in sorted(self.swaps)},
            },
            "cost_allocation_semantics": {
                "spread_convention": self.spread_convention,
                "spread_charged_per_round_trip": 1.0,
                "spread_invariant": (
                    "total spread cost depends only on volume, never on the "
                    "number of partial exits"),
                "commission_per_side": True,
                "commission_scales_with_closed_volume": True,
                "slippage_per_leg": True,
                "swap_per_rollover_on_open_volume": True,
                "reference_price_basis": "BID",
            },
            "scenario_contract": self.scenario_contract.as_dict(),
            "historical_applicability": {
                "limitation": HISTORICAL_FRICTION_LIMITATION,
                "policy": self.historical_policy.as_dict(),
            },
            "status": {
                "SPREAD_AUTHORITY": str(self.spread_authority_status),
                "COMMISSION_AUTHORITY": str(self.commission_authority_status),
                "SLIPPAGE_AUTHORITY": str(self.slippage.status),
                "SWAP_AUTHORITY": str(self.swap_authority_status),
                "FRICTION_AUTHORITY_COMPLETE": self.is_complete,
            },
        }

    def hash(self) -> str:
        blob = json.dumps(self.payload(), sort_keys=True,
                          separators=(",", ":")).encode()
        return hashlib.sha256(blob).hexdigest()

    def as_dict(self) -> dict:
        out = self.payload()
        out["FRICTION_AUTHORITY_SHA256"] = self.hash()
        out["blockers"] = self.blockers()
        return out

    def assert_usable_for_economics(self) -> None:
        """Fail closed. Never let a missing component become a silent zero."""
        blockers = self.blockers()
        if blockers:
            raise FrictionAuthorityIncomplete(
                "economic verification rejected: the friction authority is "
                "incomplete and missing components must not default to zero. "
                "Blockers: " + "; ".join(blockers))


class FrictionAuthorityIncomplete(RuntimeError):
    """Economic verification was attempted without a complete authority."""
