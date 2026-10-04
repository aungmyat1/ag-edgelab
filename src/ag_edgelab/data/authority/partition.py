"""Dataset partition registry — who may read which observations, and why not.

This module is governance, not analytics. It records partitions and denies
reads. It never evaluates a strategy and never decides that a candidate is
good or bad.

ROLES
-----
``DEVELOPMENT``     freely readable; model selection allowed.
``WALK_FORWARD``    readable; intended for rolling re-fit/evaluate folds
                    whose own internal ordering is enforced elsewhere.
``OOS``             readable exactly once per candidate identity, then
                    permanently ``CONSUMED``.
``SEALED_HOLDOUT``  never readable. Unsealing requires an explicit
                    governance mission that amends the access log first;
                    this registry cannot unseal itself.

FAIL-CLOSED RULES
-----------------
1. Partitions of one (dataset_id, candidate_family) may not overlap. An
   observation belongs to exactly one role for a given family.
2. Reading a sealed partition raises :class:`SealedHoldoutDenied` — always,
   including for the registry owner.
3. Reading a ``CONSUMED`` OOS partition raises :class:`ConsumedOosDenied`.
   A verdict already extracted from a window cannot be re-extracted.
4. A window consumed by ANY family is, for every family defined
   afterwards, ``DEVELOPMENT_KNOWN`` information: its outcome has already
   influenced the researcher. :meth:`classify_for_new_family` returns that
   status so a new candidate cannot quietly re-use spent data as fresh OOS.
5. Records are append-only. :meth:`mark_consumed` may only move
   ``AVAILABLE -> CONSUMED``; it can never move backwards.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Iterable, Sequence

from pydantic import BaseModel, ConfigDict, model_validator


class PartitionRole(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    WALK_FORWARD = "WALK_FORWARD"
    OOS = "OOS"
    SEALED_HOLDOUT = "SEALED_HOLDOUT"


class AccessStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    CONSUMED = "CONSUMED"
    SEALED = "SEALED"
    DEVELOPMENT_KNOWN = "DEVELOPMENT_KNOWN"


class PartitionError(ValueError):
    """Base class for partition governance failures."""


class PartitionOverlapError(PartitionError):
    """Two partitions of the same family claim the same observation."""


class SealedHoldoutDenied(PermissionError):
    """An attempt to read a sealed holdout partition."""


class ConsumedOosDenied(PermissionError):
    """An attempt to re-open an out-of-sample window already spent."""


class UnknownPartition(PartitionError):
    """A read request names a partition that does not exist."""


class PartitionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: str
    dataset_hash: str
    role: PartitionRole
    candidate_family: str
    start: datetime
    end: datetime
    access_status: AccessStatus
    consumed_at: datetime | None = None
    consumed_by: str | None = None
    sealed: bool = False
    note: str = ""

    @model_validator(mode="after")
    def _check(self) -> "PartitionRecord":
        for field_name in ("start", "end"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset().total_seconds() != 0:
                raise PartitionError(f"{field_name} must be an aware UTC datetime")
        if self.start >= self.end:
            raise PartitionError(
                f"empty or inverted partition [{self.start.isoformat()}, "
                f"{self.end.isoformat()})")
        if self.role is PartitionRole.SEALED_HOLDOUT and not self.sealed:
            raise PartitionError("SEALED_HOLDOUT partitions must have sealed=True")
        if self.sealed and self.access_status is not AccessStatus.SEALED:
            raise PartitionError("sealed partitions must carry access_status=SEALED")
        if self.access_status is AccessStatus.CONSUMED and not self.consumed_by:
            raise PartitionError("a CONSUMED partition must record consumed_by")
        if self.access_status is AccessStatus.CONSUMED and self.consumed_at is None:
            raise PartitionError("a CONSUMED partition must record consumed_at")
        return self

    def contains(self, ts: datetime) -> bool:
        return self.start <= ts.astimezone(timezone.utc) < self.end

    def overlaps(self, other: "PartitionRecord") -> bool:
        return self.start < other.end and other.start < self.end

    def as_dict(self) -> dict:
        payload = self.model_dump(mode="json")
        payload["window_utc"] = (
            f"[{self.start.isoformat().replace('+00:00', 'Z')}, "
            f"{self.end.isoformat().replace('+00:00', 'Z')})")
        return payload


class DatasetPartitionRegistry:
    """Append-only registry of partitions with fail-closed read control."""

    registry_version = "DATA_AUTHORITY_R1_DATASET_PARTITION_REGISTRY_V1"

    def __init__(self, records: Iterable[PartitionRecord] = ()) -> None:
        self._records: list[PartitionRecord] = []
        for record in records:
            self.add(record)

    # -- construction ------------------------------------------------------

    def add(self, record: PartitionRecord) -> None:
        for existing in self._records:
            if (existing.dataset_id == record.dataset_id
                    and existing.candidate_family == record.candidate_family
                    and existing.overlaps(record)):
                raise PartitionOverlapError(
                    f"{record.dataset_id}/{record.candidate_family}: "
                    f"{record.role} {record.as_dict()['window_utc']} overlaps "
                    f"{existing.role} {existing.as_dict()['window_utc']}")
        self._records.append(record)

    @property
    def records(self) -> tuple[PartitionRecord, ...]:
        return tuple(self._records)

    def families(self, dataset_id: str | None = None) -> tuple[str, ...]:
        return tuple(sorted({
            r.candidate_family for r in self._records
            if dataset_id is None or r.dataset_id == dataset_id}))

    # -- queries -----------------------------------------------------------

    def find(self, *, dataset_id: str, candidate_family: str,
             role: PartitionRole) -> PartitionRecord:
        for record in self._records:
            if (record.dataset_id == dataset_id
                    and record.candidate_family == candidate_family
                    and record.role == role):
                return record
        raise UnknownPartition(
            f"no {role} partition for {dataset_id}/{candidate_family}")

    def role_at(self, *, dataset_id: str, candidate_family: str,
                timestamp: datetime) -> PartitionRole | None:
        for record in self._records:
            if (record.dataset_id == dataset_id
                    and record.candidate_family == candidate_family
                    and record.contains(timestamp)):
                return record.role
        return None

    def consumed_windows(self, dataset_id: str) -> tuple[PartitionRecord, ...]:
        return tuple(
            r for r in self._records
            if r.dataset_id == dataset_id and r.access_status is AccessStatus.CONSUMED)

    # -- access control ----------------------------------------------------

    def assert_readable(self, *, dataset_id: str, candidate_family: str,
                        role: PartitionRole, requester: str) -> PartitionRecord:
        """Fail closed unless this exact read is permitted."""
        record = self.find(dataset_id=dataset_id, candidate_family=candidate_family,
                           role=role)
        if record.sealed or record.access_status is AccessStatus.SEALED:
            raise SealedHoldoutDenied(
                f"{requester}: {dataset_id}/{candidate_family} SEALED_HOLDOUT "
                f"{record.as_dict()['window_utc']} is sealed. Unsealing requires an "
                "explicit governance mission that amends "
                "config/governance/oos_access_log.json first; the data layer "
                "cannot authorise itself.")
        if record.access_status is AccessStatus.CONSUMED:
            raise ConsumedOosDenied(
                f"{requester}: {dataset_id}/{candidate_family} {role} "
                f"{record.as_dict()['window_utc']} was CONSUMED by "
                f"{record.consumed_by} at "
                f"{record.consumed_at.isoformat() if record.consumed_at else 'unknown'}. "
                "A spent OOS window may not be re-opened; define a new "
                "preregistered candidate against an unspent window.")
        if record.access_status is AccessStatus.DEVELOPMENT_KNOWN:
            raise ConsumedOosDenied(
                f"{requester}: {dataset_id}/{candidate_family} {role} "
                f"{record.as_dict()['window_utc']} is DEVELOPMENT_KNOWN — its "
                "outcome was already observed by an earlier candidate, so it "
                "cannot serve as fresh out-of-sample evidence.")
        return record

    def mark_consumed(self, *, dataset_id: str, candidate_family: str,
                      role: PartitionRole, consumed_by: str,
                      consumed_at: datetime) -> PartitionRecord:
        """Move AVAILABLE -> CONSUMED. Never the reverse, never re-consume."""
        record = self.find(dataset_id=dataset_id, candidate_family=candidate_family,
                           role=role)
        if record.sealed:
            raise SealedHoldoutDenied("cannot consume a sealed partition")
        if record.access_status is not AccessStatus.AVAILABLE:
            raise ConsumedOosDenied(
                f"{dataset_id}/{candidate_family} {role} is already "
                f"{record.access_status}; consumption is append-only")
        updated = record.model_copy(update={
            "access_status": AccessStatus.CONSUMED,
            "consumed_by": consumed_by,
            "consumed_at": consumed_at.astimezone(timezone.utc),
        })
        self._records[self._records.index(record)] = updated
        return updated

    def classify_for_new_family(self, *, dataset_id: str, start: datetime,
                                end: datetime) -> AccessStatus:
        """Status a NEW candidate family must assign to ``[start, end)``.

        Intersecting any window already consumed by any family makes the
        span DEVELOPMENT_KNOWN: the researcher has seen it.
        """
        start = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)
        for record in self._records:
            if record.dataset_id != dataset_id:
                continue
            if record.sealed and record.start < end and start < record.end:
                return AccessStatus.SEALED
            if (record.access_status is AccessStatus.CONSUMED
                    and record.start < end and start < record.end):
                return AccessStatus.DEVELOPMENT_KNOWN
        return AccessStatus.AVAILABLE

    # -- serialization -----------------------------------------------------

    def as_dict(self) -> dict:
        return {
            "registry_version": self.registry_version,
            "roles": [r.value for r in PartitionRole],
            "access_statuses": [s.value for s in AccessStatus],
            "fail_closed_rules": [
                "Partitions of one (dataset_id, candidate_family) may not overlap.",
                "SEALED_HOLDOUT reads raise SealedHoldoutDenied unconditionally.",
                "CONSUMED OOS reads raise ConsumedOosDenied.",
                "A window consumed by any family is DEVELOPMENT_KNOWN for every "
                "family defined afterwards.",
                "mark_consumed only moves AVAILABLE -> CONSUMED; it is append-only.",
            ],
            "record_count": len(self._records),
            "records": [
                r.as_dict() for r in sorted(
                    self._records,
                    key=lambda r: (r.dataset_id, r.candidate_family, r.start, r.role))
            ],
        }


def no_overlap(records: Sequence[PartitionRecord]) -> bool:
    """True iff no two same-family partitions of one dataset overlap."""
    for i, a in enumerate(records):
        for b in records[i + 1:]:
            if (a.dataset_id == b.dataset_id
                    and a.candidate_family == b.candidate_family
                    and a.overlaps(b)):
                return False
    return True
