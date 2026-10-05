"""Observations entering the gate, and the role authority that admits them.

Two rules govern this module and both are fail-closed.

**Every observation declares its dataset role.** There is no default.
An observation that does not know where it came from is not admissible
evidence, because the whole point of the gate is to certify that a
result came from data the researcher was allowed to look at.

**Lineage contamination is detected, not shrugged off.** A window whose
OOS verdict has already been spent becomes DEVELOPMENT_KNOWN — the
researcher has seen it. That is fine for a candidate designed before the
verdict existed. It is *not* fine for a descendant whose design was
informed by it: that candidate's "development" evidence silently
contains the outcome it was built to match. The registry already encodes
the first half of this (``classify_for_new_family``); this module adds
the descendant check and refuses rather than quietly filtering.

Offending observations are never silently dropped. Dropping them would
change the population the metrics describe while leaving the metrics
looking clean, which is the failure this gate exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum

ALLOWED_ROLES: frozenset[str] = frozenset({"DEVELOPMENT", "DEVELOPMENT_KNOWN"})
FORBIDDEN_ROLES: frozenset[str] = frozenset({
    "OOS", "SEALED_OOS", "HOLDOUT", "SEALED_HOLDOUT", "UNKNOWN",
})


class DatasetRoleViolation(RuntimeError):
    """An observation's role is forbidden, absent, or unrecognised."""


class LineageContamination(RuntimeError):
    """DEVELOPMENT_KNOWN evidence is being used by an informed descendant."""


class EvidenceRole(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    DEVELOPMENT_KNOWN = "DEVELOPMENT_KNOWN"


@dataclass(frozen=True)
class Observation:
    """One resolved candidate outcome offered as DEV evidence.

    ``gross_r`` may be ``None`` for an admitted-but-unresolved entry; such
    rows are counted and excluded from metrics with a reason, never
    coerced to zero.
    """

    observation_id: str
    symbol: str
    timestamp_utc: datetime
    gross_r: float | None
    dataset_role: str
    source_window_id: str | None = None
    session: str | None = None
    regime: str | None = None
    status: str | None = None
    risk_distance: float | None = None

    @property
    def year(self) -> int:
        return self.timestamp_utc.astimezone(timezone.utc).year

    @property
    def is_resolved(self) -> bool:
        return self.gross_r is not None


@dataclass(frozen=True)
class ConsumedWindow:
    """A window whose OOS verdict has already been spent."""

    window_id: str
    candidate_family: str
    consumed_by: str
    start_utc: datetime
    end_utc: datetime

    def contains(self, ts: datetime) -> bool:
        return self.start_utc <= ts.astimezone(timezone.utc) < self.end_utc


@dataclass(frozen=True)
class LineageDeclaration:
    """What the candidate under test knew when it was designed.

    ``informed_by_consumed_oos`` is the critical field. It is supplied by
    the candidate, and if it is left unset for a candidate whose evidence
    overlaps a consumed window, the gate fails closed rather than
    assuming innocence.
    """

    candidate_id: str
    candidate_family: str
    designed_at_utc: datetime | None = None
    informed_by_consumed_oos: bool | None = None
    informed_by_windows: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class RoleAudit:
    """Outcome of admitting a population."""

    total: int = 0
    admitted: int = 0
    by_role: dict[str, int] = field(default_factory=dict)
    violations: list[dict] = field(default_factory=list)
    contaminated: list[dict] = field(default_factory=list)
    resolved: int = 0
    unresolved: int = 0

    @property
    def clean(self) -> bool:
        return not self.violations and not self.contaminated

    def as_dict(self) -> dict:
        return {
            "total_offered": self.total,
            "admitted": self.admitted,
            "resolved": self.resolved,
            "unresolved": self.unresolved,
            "by_role": dict(sorted(self.by_role.items())),
            "violation_count": len(self.violations),
            "violations": self.violations[:50],
            "contamination_count": len(self.contaminated),
            "contaminated": self.contaminated[:50],
            "clean": self.clean,
            "policy": ("offending observations are reported, never silently "
                       "dropped; dropping them would change the population "
                       "the metrics describe while leaving them looking clean"),
        }


def admit(
    observations: list[Observation],
    *,
    lineage: LineageDeclaration,
    consumed_windows: tuple[ConsumedWindow, ...] = (),
) -> tuple[list[Observation], RoleAudit]:
    """Admit a population for robustness analysis, or fail closed.

    Raises :class:`DatasetRoleViolation` if any observation carries a
    forbidden, missing or unrecognised role, and
    :class:`LineageContamination` if DEVELOPMENT_KNOWN evidence drawn
    from a consumed window is offered by a candidate that was informed by
    that window.
    """
    audit = RoleAudit(total=len(observations))

    for obs in observations:
        role = obs.dataset_role
        audit.by_role[role] = audit.by_role.get(role, 0) + 1
        if not role or role in FORBIDDEN_ROLES or role not in ALLOWED_ROLES:
            audit.violations.append({
                "observation_id": obs.observation_id,
                "dataset_role": role or None,
                "reason": ("role is forbidden" if role in FORBIDDEN_ROLES
                           else "role is absent or unrecognised"),
            })

    if audit.violations:
        roles = sorted({v["dataset_role"] for v in audit.violations
                        if v["dataset_role"]})
        raise DatasetRoleViolation(
            f"DATASET_ROLE_VIOLATION: {len(audit.violations)} of "
            f"{len(observations)} observations carry a role outside "
            f"{sorted(ALLOWED_ROLES)} (offending roles: {roles or ['<absent>']}). "
            "The gate fails closed rather than filtering them out, because "
            "silently dropping them would change the population without "
            "changing how the metrics look.")

    # ---- lineage ------------------------------------------------------
    overlapping: list[tuple[Observation, ConsumedWindow]] = []
    for obs in observations:
        for window in consumed_windows:
            if window.contains(obs.timestamp_utc) or (
                    obs.source_window_id is not None
                    and obs.source_window_id == window.window_id):
                overlapping.append((obs, window))
                break

    if overlapping:
        if lineage.informed_by_consumed_oos is None:
            raise LineageContamination(
                f"DATASET_ROLE_VIOLATION: {len(overlapping)} observations fall "
                f"inside a consumed-OOS window, but candidate "
                f"{lineage.candidate_id!r} has not declared whether its design "
                "was informed by that verdict. Role authority is ambiguous, so "
                "the gate fails closed. Set informed_by_consumed_oos "
                "explicitly.")
        if lineage.informed_by_consumed_oos:
            for obs, window in overlapping:
                audit.contaminated.append({
                    "observation_id": obs.observation_id,
                    "window_id": window.window_id,
                    "consumed_by": window.consumed_by,
                    "reason": ("candidate design was informed by this window's "
                               "spent OOS verdict, so its outcomes are not "
                               "independent evidence for this descendant"),
                })
            raise LineageContamination(
                f"DATASET_ROLE_VIOLATION: candidate {lineage.candidate_id!r} "
                f"declares it was informed by a consumed OOS verdict, yet "
                f"{len(overlapping)} of its evidence observations come from "
                f"that same window. A descendant cannot use the outcome that "
                "shaped it as independent development evidence.")
        # Declared NOT informed: admissible as DEVELOPMENT_KNOWN, recorded.
        for obs, window in overlapping:
            audit.contaminated.append({
                "observation_id": obs.observation_id,
                "window_id": window.window_id,
                "consumed_by": window.consumed_by,
                "reason": ("inside a consumed window but candidate predates / "
                           "is uninformed by the verdict; admitted as "
                           "DEVELOPMENT_KNOWN and recorded"),
                "admitted": True,
            })
        audit.contaminated = [c for c in audit.contaminated
                              if not c.get("admitted")] or []

    audit.admitted = len(observations)
    audit.resolved = sum(1 for o in observations if o.is_resolved)
    audit.unresolved = audit.admitted - audit.resolved
    return observations, audit


def resolved_r(observations: list[Observation]) -> list[float]:
    """Gross R of resolved observations. Unresolved are excluded, not zeroed."""
    return [o.gross_r for o in observations if o.gross_r is not None]
