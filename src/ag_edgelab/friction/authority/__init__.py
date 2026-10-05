"""Venue-specific, content-addressed friction authority.

This package answers one question: what does it actually cost to run a
trade at a named venue, and do we have the evidence to say so?

The organising rule is that every cost component is a separate authority
with its own evidence requirement, and every one of them defaults to
MISSING. A missing component is never silently zero — it raises, so an
incomplete authority cannot quietly produce an optimistic NET_R.
"""

from ag_edgelab.friction.authority.components import (
    MISSING, AuthorityStatus, CommissionMode, CommissionSpec,
    DEFAULT_SLIPPAGE_REQUIREMENT, FrictionComponentMissing,
    SlippageAuthority, SlippageEvidenceKind, SwapApplicability, SwapMode,
    SwapSpec, determine_swap_applicability,
)
from ag_edgelab.friction.authority.contract import (
    AccountClass, FRICTION_AUTHORITY_ID, FrictionAuthorityContract,
    FrictionAuthorityIncomplete, SymbolMetadataMismatch, VenueIdentity,
    VenueIdentityMismatch, assert_symbol_metadata_matches,
)
from ag_edgelab.friction.authority.costmodel import (
    COST_MODEL_VERSION, CostBreakdown, ExitKind, ExitLeg, Side,
    SpreadConvention, TradePlan, compute_costs, economic_verification_ready,
)
from ag_edgelab.friction.authority.quotes import (
    QuoteDefect, Session, SpreadDistribution, SpreadEvidence,
    SpreadObservation, session_for, summarise,
)
from ag_edgelab.friction.authority.scenarios import (
    HISTORICAL_FRICTION_LIMITATION, FrictionRegime, HistoricalCostPolicy,
    PREREGISTERED_SCENARIOS, ScenarioContract, ScenarioName, ScenarioRule,
    assert_regime_compatible,
)
from ag_edgelab.friction.authority.symbols import (
    PipConvention, REQUIRED_SYMBOL_FIELDS, SymbolContractMissing,
    SymbolRegistry, SymbolSpec, default_pip_convention, empty_spec,
)

__all__ = [
    "MISSING", "AuthorityStatus", "CommissionMode", "CommissionSpec",
    "DEFAULT_SLIPPAGE_REQUIREMENT", "FrictionComponentMissing",
    "SlippageAuthority", "SlippageEvidenceKind", "SwapApplicability",
    "SwapMode", "SwapSpec", "determine_swap_applicability",
    "AccountClass", "FRICTION_AUTHORITY_ID", "FrictionAuthorityContract",
    "FrictionAuthorityIncomplete", "SymbolMetadataMismatch", "VenueIdentity",
    "VenueIdentityMismatch", "assert_symbol_metadata_matches",
    "COST_MODEL_VERSION", "CostBreakdown", "ExitKind", "ExitLeg", "Side",
    "SpreadConvention", "TradePlan", "compute_costs",
    "economic_verification_ready",
    "QuoteDefect", "Session", "SpreadDistribution", "SpreadEvidence",
    "SpreadObservation", "session_for", "summarise",
    "HISTORICAL_FRICTION_LIMITATION", "FrictionRegime", "HistoricalCostPolicy",
    "PREREGISTERED_SCENARIOS", "ScenarioContract", "ScenarioName",
    "ScenarioRule", "assert_regime_compatible",
    "PipConvention", "REQUIRED_SYMBOL_FIELDS", "SymbolContractMissing",
    "SymbolRegistry", "SymbolSpec", "default_pip_convention", "empty_spec",
]
