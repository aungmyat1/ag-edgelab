"""DATA AUTHORIZATION GATE for the V2.1 replay (Mission 3B-A, Phase 10).

Runs BEFORE any real-data read and fails closed. The gate is pure: it is
given registry contents as arguments and never reads a dataset itself, so
exercising it cannot record a dataset access.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from ag_edgelab.data.fingerprint import canonical_json

GATE_ID = "GEN2_ALD_V2_1_DATA_AUTHORIZATION_GATE_V1"

AUTHORIZED_DEVELOPMENT = "AUTHORIZED_DEVELOPMENT"
DENIED_CONTAMINATED = "DENIED_CONTAMINATED"
DENIED_OOS = "DENIED_OOS"
DENIED_HOLDOUT = "DENIED_HOLDOUT"
DENIED_IDENTITY_MISMATCH = "DENIED_IDENTITY_MISMATCH"
DENIED_UNKNOWN_EXPOSURE = "DENIED_UNKNOWN_EXPOSURE"

VERDICTS: tuple[str, ...] = (
    AUTHORIZED_DEVELOPMENT, DENIED_CONTAMINATED, DENIED_OOS, DENIED_HOLDOUT,
    DENIED_IDENTITY_MISMATCH, DENIED_UNKNOWN_EXPOSURE,
)

#: Roles that may ever be authorized. Anything else is unknown exposure.
ADMISSIBLE_ROLES: tuple[str, ...] = ("DEVELOPMENT", "DEVELOPMENT_KNOWN")


@dataclass(frozen=True)
class DataRequest:
    """What the replay wants to read."""

    symbols: tuple[str, ...]
    symbol_years: tuple[tuple[str, int], ...]
    date_range: tuple[str, str]
    role: str
    contract_hash: str
    preregistration_hash: str
    dataset_binding_hash: str
    policy_provenance: str


@dataclass(frozen=True)
class GovernanceState:
    """Registry contents, passed in rather than read, so the gate is pure."""

    expected_contract_hash: str
    expected_preregistration_hash: str
    expected_dataset_binding_hash: str
    permitted_symbol_years: frozenset[tuple[str, int]]
    contaminated_symbol_years: frozenset[tuple[str, int]]
    oos_windows: tuple[tuple[str, str], ...] = ()
    holdout_windows: tuple[tuple[str, str], ...] = ()
    required_policy_provenance: str = "OWNER_RESOLVED_CONTRACT_AMENDMENT"


def _overlaps(req: tuple[str, str], window: tuple[str, str]) -> bool:
    """Half-open [start, end) overlap on ISO date strings."""
    return req[0] < window[1] and window[0] < req[1]


def authorize(request: DataRequest, state: GovernanceState) -> dict:
    """Return exactly one verdict. Denials are ordered most-severe first."""
    checks: list[dict] = []

    def note(name: str, ok: bool, detail=None) -> bool:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    # 1. Identity must match before anything else is considered.
    identity_ok = all((
        note("contract_hash_matches",
             request.contract_hash == state.expected_contract_hash),
        note("preregistration_hash_matches",
             request.preregistration_hash == state.expected_preregistration_hash),
        note("dataset_binding_hash_matches",
             request.dataset_binding_hash == state.expected_dataset_binding_hash),
    ))
    if not identity_ok:
        return _verdict(DENIED_IDENTITY_MISMATCH, request, checks,
                        "a hash presented by the replay does not match the "
                        "frozen preregistration")

    # 2. Sealed holdout is the most severe exposure.
    for w in state.holdout_windows:
        if _overlaps(request.date_range, w):
            return _verdict(DENIED_HOLDOUT, request, checks,
                            f"requested range overlaps sealed holdout {w}")
    note("no_holdout_overlap", True)

    # 3. Reserved OOS.
    for w in state.oos_windows:
        if _overlaps(request.date_range, w):
            return _verdict(DENIED_OOS, request, checks,
                            f"requested range overlaps reserved OOS {w}")
    note("no_oos_overlap", True)

    # 4. Role.
    if request.role not in ADMISSIBLE_ROLES:
        return _verdict(DENIED_UNKNOWN_EXPOSURE, request, checks,
                        f"role {request.role!r} is not in {ADMISSIBLE_ROLES}")
    note("role_admissible", True, request.role)

    # 5. Contamination.
    contaminated = sorted(set(request.symbol_years) & state.contaminated_symbol_years)
    if contaminated:
        return _verdict(DENIED_CONTAMINATED, request, checks,
                        f"contaminated symbol-years requested: {contaminated}")
    note("no_contaminated_symbol_years", True)

    # 6. Everything requested must be explicitly permitted. Silence is denial.
    unknown = sorted(set(request.symbol_years) - state.permitted_symbol_years)
    if unknown:
        return _verdict(DENIED_UNKNOWN_EXPOSURE, request, checks,
                        f"symbol-years absent from the permitted binding: {unknown}")
    note("all_symbol_years_permitted", True, len(request.symbol_years))

    unknown_syms = sorted({s for s, _ in request.symbol_years} - set(request.symbols))
    if unknown_syms:
        return _verdict(DENIED_UNKNOWN_EXPOSURE, request, checks,
                        f"symbol-years reference undeclared symbols: {unknown_syms}")
    note("symbols_consistent", True)

    # 7. A synthetic policy may never touch a real partition.
    if request.policy_provenance != state.required_policy_provenance:
        return _verdict(DENIED_UNKNOWN_EXPOSURE, request, checks,
                        "replay policy provenance is "
                        f"{request.policy_provenance!r}; the unfrozen contract "
                        "decisions have not been resolved by the owner")
    note("policy_provenance_owner_resolved", True)

    return _verdict(AUTHORIZED_DEVELOPMENT, request, checks, None)


def _verdict(verdict: str, request: DataRequest, checks: list[dict],
             reason: str | None) -> dict:
    out = {
        "gate_id": GATE_ID,
        "verdict": verdict,
        "authorized": verdict == AUTHORIZED_DEVELOPMENT,
        "reason": reason,
        "checks": checks,
        "request": {
            "symbols": list(request.symbols),
            "symbol_years_n": len(request.symbol_years),
            "date_range": list(request.date_range),
            "role": request.role,
            "policy_provenance": request.policy_provenance,
        },
        "semantics": "FAIL_CLOSED — anything not explicitly permitted is denied",
    }
    out["verdict_hash"] = hashlib.sha256(
        canonical_json(out).encode("utf-8")).hexdigest()
    return out


def mock_governance_state(**overrides) -> GovernanceState:
    """Synthetic fixture state for tests. Deliberately NOT the real registry."""
    base = {
        "expected_contract_hash": "CONTRACT_X",
        "expected_preregistration_hash": "PREREG_X",
        "expected_dataset_binding_hash": "BINDING_X",
        "permitted_symbol_years": frozenset({("EURUSD", 2016), ("XAUUSD", 2016)}),
        "contaminated_symbol_years": frozenset({("GBPUSD", 2016)}),
        "oos_windows": (("2016-09-01", "2016-12-01"),),
        "holdout_windows": (("2016-12-01", "2017-01-01"),),
    }
    base.update(overrides)
    return GovernanceState(**base)
