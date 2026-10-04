"""Analyzer rule classifier — classify imported strategy rules by FUNCTION.

Order of authority:
  1. explicit strategy metadata (`function` key declared by the owner),
  2. the registered per-rule authority map (explicit owner mapping, not
     keyword matching),
  3. otherwise fail CLOSED: RULE_CLASSIFICATION_AMBIGUOUS + owner review.

Rule names alone never classify anything.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Mapping

from pydantic import BaseModel, ConfigDict


class RuleFunction(StrEnum):
    TRIGGER_DIRECTION = "TRIGGER_DIRECTION"
    TRIGGER_LOCATION = "TRIGGER_LOCATION"
    CONFIRMATION_SETUP = "CONFIRMATION_SETUP"
    CONFIRMATION_ENTRY = "CONFIRMATION_ENTRY"
    TARGET_GEOMETRY = "TARGET_GEOMETRY"
    EXIT_MANAGEMENT = "EXIT_MANAGEMENT"
    RISK = "RISK"
    SESSION_CONTEXT = "SESSION_CONTEXT"
    OTHER = "OTHER"


AMBIGUOUS = "RULE_CLASSIFICATION_AMBIGUOUS"


class RuleClassification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    rule_version: str
    function: RuleFunction | None
    status: str  # "CLASSIFIED" | AMBIGUOUS
    basis: str   # "EXPLICIT_METADATA" | "REGISTERED_AUTHORITY_MAP" | "NONE"
    requires_owner_review: bool


# Explicit owner/research-authority map for rules already present in this
# repository. Each entry is a deliberate functional decision, not a keyword
# guess; new rules without metadata or an entry here fail closed.
REPOSITORY_RULE_AUTHORITY_MAP: Mapping[str, RuleFunction] = {
    # SYNTHETIC_BRANCHING_REFERENCE (reference_branching.py)
    "MARKET_STATE": RuleFunction.TRIGGER_DIRECTION,     # routes regime/thesis
    "TREND_DIRECTION": RuleFunction.TRIGGER_DIRECTION,
    "SWEEP": RuleFunction.CONFIRMATION_SETUP,           # routes setup branch
    "TREND_BUY": RuleFunction.CONFIRMATION_ENTRY,       # terminal trade nodes
    "TREND_SELL": RuleFunction.CONFIRMATION_ENTRY,
    "RANGE_SETUP": RuleFunction.CONFIRMATION_ENTRY,
    "SWEEP_SETUP": RuleFunction.CONFIRMATION_ENTRY,
    # ST_CRYPTO_MTF_SMC_V1 stages (crypto_mtf_smc.py)
    "HTF_ELIGIBLE": RuleFunction.TRIGGER_DIRECTION,
    "H1_POI_ACTIVE": RuleFunction.TRIGGER_LOCATION,
    "M15_SSL_SWEEP": RuleFunction.CONFIRMATION_SETUP,
    "M15_BSL_SWEEP": RuleFunction.CONFIRMATION_SETUP,
    "M5_BULLISH_CHOCH": RuleFunction.CONFIRMATION_SETUP,
    "M5_BEARISH_CHOCH": RuleFunction.CONFIRMATION_SETUP,
    "M5_DISPLACEMENT": RuleFunction.CONFIRMATION_SETUP,
    "M5_BULLISH_FVG": RuleFunction.CONFIRMATION_SETUP,
    "M5_BEARISH_FVG": RuleFunction.CONFIRMATION_SETUP,
    "FVG_RETEST": RuleFunction.CONFIRMATION_ENTRY,
    "ENTRY": RuleFunction.CONFIRMATION_ENTRY,
    "EXIT": RuleFunction.EXIT_MANAGEMENT,
    # Documented ST_ASIAN_SESSION_V1 reference rules (docs/FUNNEL_MODEL.md)
    "ASIAN_SESSION_V1": RuleFunction.SESSION_CONTEXT,
    "H1_BIAS_V1": RuleFunction.TRIGGER_DIRECTION,
    "ASIAN_RANGE_V1": RuleFunction.TRIGGER_LOCATION,
    "SWEEP_V1": RuleFunction.CONFIRMATION_SETUP,
    "DISPLACEMENT_V1": RuleFunction.CONFIRMATION_SETUP,
    "RANGE_25_SL_V1": RuleFunction.RISK,
    "RR_GATE_V1": RuleFunction.RISK,
    "ENTRY_RETEST_V1": RuleFunction.CONFIRMATION_ENTRY,
    "TP1_RANGE_V1": RuleFunction.TARGET_GEOMETRY,
    "BE_AFTER_TP1_V1": RuleFunction.EXIT_MANAGEMENT,
    "TP2_5R_V1": RuleFunction.TARGET_GEOMETRY,
}


def classify_rule(
    rule_id: str,
    rule_version: str,
    metadata: Mapping[str, object] | None = None,
    authority_map: Mapping[str, RuleFunction] = REPOSITORY_RULE_AUTHORITY_MAP,
) -> RuleClassification:
    # 1) explicit strategy metadata wins.
    if metadata and "function" in metadata:
        declared = metadata["function"]
        try:
            function = RuleFunction(str(declared))
        except ValueError:
            return RuleClassification(rule_id=rule_id, rule_version=rule_version, function=None,
                                      status=AMBIGUOUS, basis="EXPLICIT_METADATA",
                                      requires_owner_review=True)
        return RuleClassification(rule_id=rule_id, rule_version=rule_version, function=function,
                                  status="CLASSIFIED", basis="EXPLICIT_METADATA",
                                  requires_owner_review=False)
    # 2) explicit registered authority map.
    if rule_id in authority_map:
        return RuleClassification(rule_id=rule_id, rule_version=rule_version,
                                  function=authority_map[rule_id], status="CLASSIFIED",
                                  basis="REGISTERED_AUTHORITY_MAP", requires_owner_review=False)
    # 3) fail closed.
    return RuleClassification(rule_id=rule_id, rule_version=rule_version, function=None,
                              status=AMBIGUOUS, basis="NONE", requires_owner_review=True)
