"""EDGELAB_SYSTEM_READINESS_V1: fail-closed system governance contracts.

This module contains software-only authority contracts.  It deliberately does not
open datasets, perform OOS evaluation, or provide execution capabilities.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class ReadinessState(str, Enum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAIL = "FAIL"


class FrictionEvidence(str, Enum):
    MEASURED = "MEASURED"
    PARTIAL = "PARTIAL"
    SCENARIO = "SCENARIO"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ExposureType(str, Enum):
    CONSUMED_OOS = "CONSUMED_OOS"
    SEALED_HOLDOUT_OPEN = "SEALED_HOLDOUT_OPEN"
    MANUAL_CHART_REVIEW = "MANUAL_CHART_REVIEW"
    USER_PROVIDED_TRADE_EXAMPLE = "USER_PROVIDED_TRADE_EXAMPLE"
    LIVE_OBSERVATION = "LIVE_OBSERVATION"
    PRIOR_STRATEGY_DESIGN = "PRIOR_STRATEGY_DESIGN"
    EXTERNAL_REPORT = "EXTERNAL_REPORT"
    UNKNOWN_EXPOSURE = "UNKNOWN_EXPOSURE"


class ReusePolicy(str, Enum):
    FRESH = "FRESH"
    DEVELOPMENT_KNOWN = "DEVELOPMENT_KNOWN"
    FORBIDDEN_AS_OOS = "FORBIDDEN_AS_OOS"
    SEALED = "SEALED"
    UNKNOWN = "UNKNOWN"


EDGE_STATUSES = {"UNVERIFIED", "INSUFFICIENT_EVIDENCE", "NO_EDGE", "EDGE_VERIFIED"}
VERIFICATION_STAGES = {"RESEARCH_CANDIDATE", "DEV_ACTIVE", "DEV_REJECTED", "PRE_OOS_FAILED", "FROZEN_CANDIDATE", "OOS_REJECTED", "OOS_PASSED", "HOLDOUT_REJECTED", "VERIFICATION_FAILED", "EDGE_VERIFIED"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class ContaminationRecord:
    candidate_family_id: str
    source_candidate_id: str
    start: str
    end: str
    exposure_type: ExposureType
    exposure_timestamp: str
    knowledge_source: str
    reuse_policy: ReusePolicy
    notes: str = ""
    evidence_hash: str = ""


@dataclass
class ContaminationRegistry:
    records: list[ContaminationRecord] = field(default_factory=list)

    def add(self, record: ContaminationRecord) -> None:
        if not record.candidate_family_id or not record.source_candidate_id:
            raise ValueError("candidate family and source candidate are required")
        self.records.append(record)

    def validate(self) -> dict[str, Any]:
        errors = []
        for r in self.records:
            if r.exposure_type == ExposureType.UNKNOWN_EXPOSURE or r.reuse_policy == ReusePolicy.UNKNOWN:
                errors.append(f"unknown exposure/policy for {r.source_candidate_id}")
        return {"state": ReadinessState.PASS.value if not errors else ReadinessState.FAIL.value, "errors": errors, "record_count": len(self.records)}

    def is_fresh(self, family: str, start: str, end: str) -> bool:
        """Freshness is family/date based, not source-file based."""
        for r in self.records:
            overlaps = r.candidate_family_id == family and r.start < end and start < r.end
            if overlaps:
                return False
        return True

    def assert_oos_fresh(self, family: str, start: str, end: str) -> None:
        if not self.is_fresh(family, start, end):
            raise GovernanceError("candidate-family contamination makes OOS data non-fresh")


@dataclass(frozen=True)
class FrozenCandidateIdentity:
    strategy_code_hash: str
    parameter_hash: str
    funnel_hash: str
    entry_contract_hash: str
    sl_contract_hash: str
    target_contract_hash: str
    session_contract_hash: str
    symbol_universe: tuple[str, ...]
    decision_timeframe: str
    execution_timeframe: str
    dev_dataset_authority: str
    dev_partition_hash: str
    friction_contract_hash: str
    preregistration_hash: str
    verifier_version: str

    @property
    def candidate_identity_sha256(self) -> str:
        return sha256_json(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass(frozen=True)
class FrictionAuthority:
    spread: FrictionEvidence
    commission: FrictionEvidence
    slippage: FrictionEvidence
    swap: FrictionEvidence
    funding: FrictionEvidence = FrictionEvidence.NOT_APPLICABLE

    def edge_verification_ready(self) -> bool:
        return all(x in {FrictionEvidence.MEASURED, FrictionEvidence.NOT_APPLICABLE} for x in (self.spread, self.commission, self.slippage, self.swap, self.funding))

    def readiness(self) -> dict[str, bool]:
        structural = all(x != FrictionEvidence.UNAVAILABLE for x in (self.spread, self.commission, self.slippage, self.swap, self.funding))
        economic = all(x in {FrictionEvidence.MEASURED, FrictionEvidence.PARTIAL, FrictionEvidence.SCENARIO, FrictionEvidence.NOT_APPLICABLE} for x in (self.spread, self.commission, self.slippage, self.swap, self.funding))
        return {"FRICTION_STRUCTURAL_READY": structural, "FRICTION_ECONOMIC_SCREEN_READY": economic, "FRICTION_EDGE_VERIFICATION_READY": self.edge_verification_ready()}

    def assert_regime_compatible(self, authority_regime: str, claim_regime: str) -> None:
        if authority_regime != claim_regime:
            raise GovernanceError("friction authority regime is temporally incompatible with claim")


@dataclass(frozen=True)
class SearchRecord:
    search_id: str
    candidate_family: str
    dataset_role: str
    search_space_hash: str
    objective: str
    trial_count: int
    algorithm: str
    seed: int
    best_candidate_id: str
    best_candidate_hash: str
    timestamp: str

    def validate(self) -> None:
        if self.dataset_role != "DEVELOPMENT":
            raise GovernanceError("search and Optuna are DEVELOPMENT-only")
        if self.trial_count < 0:
            raise ValueError("trial_count cannot be negative")


class SearchLedger:
    """Append-only search pressure ledger; validation is intentionally strict."""
    def __init__(self) -> None:
        self.records: list[SearchRecord] = []

    def record(self, item: SearchRecord) -> None:
        item.validate()
        if any(x.search_id == item.search_id for x in self.records):
            raise GovernanceError("search_id is immutable and cannot be reused")
        self.records.append(item)

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            for item in self.records:
                item.validate()
        except (GovernanceError, ValueError) as exc:
            errors.append(str(exc))
        return {"state": "PASS" if not errors else "FAIL", "record_count": len(self.records), "errors": errors}


class GovernanceError(RuntimeError):
    pass


def authorize_oos(*, candidate_frozen: bool, candidate_hash_valid: bool, pre_oos_pass: bool, dataset_role: str, family_fresh: bool, already_consumed: bool, preregistration_hash: str) -> None:
    checks = (candidate_frozen, candidate_hash_valid, pre_oos_pass, dataset_role == "OOS", family_fresh, not already_consumed, bool(preregistration_hash))
    if not all(checks):
        raise GovernanceError("OOS authorization denied: required freeze, identity, PRE-OOS, role, freshness, single-use, or preregistration gate failed")


def authorize_holdout(*, oos_pass: bool, economic_authority: bool, candidate_unchanged: bool, holdout_unconsumed: bool, preregistration_hash: str) -> None:
    if not all((oos_pass, economic_authority, candidate_unchanged, holdout_unconsumed, bool(preregistration_hash))):
        raise GovernanceError("sealed holdout authorization denied")


def verification_verdict(*, candidate_identity_valid: bool, data_lineage_valid: bool, causality_pass: bool, pre_oos_pass: bool, oos_pass: bool, holdout_pass: bool, diagnostics_pass: bool, friction_ready: bool, independent_reproduction_pass: bool, uncontaminated: bool) -> str:
    required = (candidate_identity_valid, data_lineage_valid, causality_pass, pre_oos_pass, oos_pass, holdout_pass, diagnostics_pass, friction_ready, independent_reproduction_pass, uncontaminated)
    if not all(required):
        return "INSUFFICIENT_EVIDENCE"
    return "EDGE_VERIFIED"


def ticket_status(*, strategy_id: str, strategy_version: str, strategy_hash: str, edge_status: str, verification_stage: str, verification_evidence_id: str, verification_evidence_hash: str, data_authority_id: str, friction_authority_id: str, last_verified_at: str | None) -> dict[str, Any]:
    if edge_status not in EDGE_STATUSES or verification_stage not in VERIFICATION_STAGES:
        raise ValueError("unknown ticket status vocabulary")
    return locals()


def readiness_audit(checks: Mapping[str, ReadinessState | str], *, broker_friction_values_ready: bool = False, recent_data_ready: bool = False, crypto_corpus_ready: bool = False) -> dict[str, Any]:
    normalized = {k: (v.value if isinstance(v, ReadinessState) else v) for k, v in checks.items()}
    software = all(v == ReadinessState.PASS.value for v in normalized.values())
    return {"system": "EDGELAB_SYSTEM_READINESS_V1", "checks": normalized, "SYSTEM_SOFTWARE_COMPLETE": "YES" if software else "NO", "SYSTEM_OPERATIONAL_EVIDENCE_COMPLETE": "YES" if software and broker_friction_values_ready and recent_data_ready else "NO", "RESEARCH_GENERATION_2_ALLOWED": "YES" if software else "NO", "external": {"BROKER_FRICTION_VALUES_READY": broker_friction_values_ready, "RECENT_2019_2025_DATA_READY": recent_data_ready, "REAL_CRYPTO_CORPUS_READY": crypto_corpus_ready}, "OOS_ECONOMIC_AUTHORIZED": "YES" if software and broker_friction_values_ready else "NO", "HOLDOUT_AUTHORIZED": "NO", "LIVE_EXECUTION_AUTHORIZED": "NO"}
