"""Candidate/null identical execution semantics (PHASE B5).

The candidate and every null draw must share EXACTLY the same execution
machinery.  This module freezes that machinery as an explicit, hashable
declaration and fails closed on any drift between the candidate's and the
null's execution configuration.

Friction authority: spread, slippage, commission, and swap/financing are
UNAVAILABLE/UNKNOWN in this policy generation.  Unknown friction is never
treated as zero.  A structural DEV gate operating without friction may run
only under the explicit label STRUCTURAL_DIAGNOSTIC_ONLY; no economic
promotion is possible from scenario or unknown friction.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

DECISION_TIMING = "T2_CONFIRMATION_M5_CLOSE"
ENTRY_CONVENTION = "FIRST_M5_OPEN_AT_OR_AFTER_T2"
REFERENCE_HORIZON_M5_BARS = 72
STOP_AUTHORITY = "ATR_14_M5_COMPLETED_BEFORE_ENTRY_X_1.0"
TARGET_AUTHORITY = "FIXED_2R"
INTRABAR_TIE = "CONSERVATIVE_STOP_FIRST"
SPREAD_AUTHORITY = "UNAVAILABLE_UNKNOWN"
SLIPPAGE_AUTHORITY = "UNAVAILABLE_UNKNOWN"
COMMISSION_AUTHORITY = "UNAVAILABLE_UNKNOWN"
SWAP_FINANCING_AUTHORITY = "UNAVAILABLE_UNKNOWN"
FRICTION_STATUS = "UNAVAILABLE_UNKNOWN"
STRUCTURAL_GATE_LABEL = "STRUCTURAL_DIAGNOSTIC_ONLY"


class FrictionZeroError(RuntimeError):
    """Unknown friction was silently converted to zero."""


class ExecutionDrift(RuntimeError):
    """Candidate and null execution semantics are not identical."""


@dataclass(frozen=True)
class ExecutionSemanticsV1:
    """The single frozen execution contract shared by candidate and nulls."""

    schema_version: str = "EXECUTION_SEMANTICS_V1"
    decision_timing: str = DECISION_TIMING
    entry_convention: str = ENTRY_CONVENTION
    reference_horizon_m5_bars: int = REFERENCE_HORIZON_M5_BARS
    stop_authority: str = STOP_AUTHORITY
    target_authority: str = TARGET_AUTHORITY
    intrabar_tie_policy: str = INTRABAR_TIE
    spread_authority: str = SPREAD_AUTHORITY
    slippage_authority: str = SLIPPAGE_AUTHORITY
    commission_authority: str = COMMISSION_AUTHORITY
    swap_financing_authority: str = SWAP_FINANCING_AUTHORITY
    friction_status: str = FRICTION_STATUS
    structural_gate_label: str = STRUCTURAL_GATE_LABEL

    def __post_init__(self) -> None:
        for name in ("spread_authority", "slippage_authority",
                     "commission_authority", "swap_financing_authority"):
            value = getattr(self, name)
            if value in ("ZERO", "NONE", "FREE", "0", 0, 0.0):
                raise FrictionZeroError(
                    f"{name} must be UNAVAILABLE/UNKNOWN, never zero")
        if self.friction_status in ("ZERO", "KNOWN", "APPLIED"):
            raise FrictionZeroError("friction_status must be UNAVAILABLE/UNKNOWN")


FROZEN_EXECUTION_SEMANTICS = ExecutionSemanticsV1()


def assert_friction_not_zero(config: Mapping[str, object]) -> None:
    """Guard: unknown friction may never be encoded as zero."""
    for name in ("spread", "slippage", "commission", "swap", "financing", "friction"):
        if config.get(name) in ("ZERO", 0, 0.0, "FREE", None) and name in config:
            raise FrictionZeroError(f"{name} cannot be zero or unset-as-zero; use UNAVAILABLE/UNKNOWN")


def assert_candidate_null_semantics_identical(
    candidate: ExecutionSemanticsV1 | Mapping[str, object],
    null: ExecutionSemanticsV1 | Mapping[str, object],
) -> None:
    """Candidate and null must share every execution field exactly."""
    left = (asdict(candidate) if isinstance(candidate, ExecutionSemanticsV1)
            else dict(candidate))
    right = (asdict(null) if isinstance(null, ExecutionSemanticsV1)
             else dict(null))
    if left != right:
        differing = {key for key in left.keys() & right.keys()
                     if left[key] != right[key]}
        missing = left.keys() ^ right.keys()
        raise ExecutionDrift(
            f"candidate/null execution semantics differ: fields={sorted(differing)} "
            f"asymmetric={sorted(missing)}")


def execution_semantics_hash(semantics: ExecutionSemanticsV1 = FROZEN_EXECUTION_SEMANTICS) -> str:
    """Deterministic identity of the frozen execution contract."""
    import hashlib

    from ag_edgelab.data.fingerprint import canonical_json
    return hashlib.sha256(canonical_json(asdict(semantics)).encode()).hexdigest()
