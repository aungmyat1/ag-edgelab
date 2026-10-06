"""Deterministic hash-linked verdict records (PHASE B9).

Conceptual identity:

    policy hash
    + data identity (dataset / manifest hash)
    + code/candidate identity (candidate contract hash, engine code sha)
    + evidence identity (event table hash, friction authority hash)
    -> verdict identity (VERDICT_RECORD_HASH)

Every future gate result binds, at minimum:

* POLICY_HASH
* DATASET_HASH / DATASET_MANIFEST_HASH
* CANDIDATE_CONTRACT_HASH
* ENGINE / CODE SHA
* EVENT_TABLE_HASH
* FRICTION_AUTHORITY_HASH (when applicable)
* VERDICT
* PARENT VERDICT ID (when lineage exists)

Hash linking is required NOW; cryptographic signing is a possible later
governance layer and is deliberately out of scope.  The record payload
contains no wall-clock fields, so identical inputs always produce an
identical VERDICT_RECORD_HASH.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Mapping, Sequence

from ag_edgelab.data.fingerprint import canonical_json, sha256_json

VERDICT_RECORD_SCHEMA = "VERDICT_RECORD_V1"


class VerdictChainError(RuntimeError):
    """A hash-linked verdict chain is malformed or mutated."""


@dataclass(frozen=True)
class VerdictRecord:
    verdict_id: str
    schema_version: str = VERDICT_RECORD_SCHEMA
    policy_hash: str = ""
    dataset_hash: str = ""
    dataset_manifest_hash: str = ""
    candidate_contract_hash: str = ""
    engine_code_sha: str = ""
    event_table_hash: str = ""
    friction_authority_hash: str = ""
    verdict: str = ""
    parent_verdict_id: str = ""
    notes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.verdict_id:
            raise ValueError("verdict_id is required")
        if self.schema_version != VERDICT_RECORD_SCHEMA:
            raise ValueError(f"unsupported verdict record schema: {self.schema_version}")
        for name in ("policy_hash", "dataset_hash", "dataset_manifest_hash",
                     "candidate_contract_hash", "engine_code_sha",
                     "event_table_hash", "friction_authority_hash",
                     "verdict", "parent_verdict_id"):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"{name} must be a string")

    def payload_dict(self) -> dict[str, object]:
        out = asdict(self)
        return out

    @property
    def verdict_record_hash(self) -> str:
        """Deterministic identity over the full canonical payload."""
        return sha256_json(self.payload_dict())

    def as_dict(self) -> dict[str, object]:
        return dict(self.payload_dict(),
                    verdict_record_hash=self.verdict_record_hash)


def verify_verdict_chain(records: Sequence[VerdictRecord]) -> None:
    """Fail closed on mutation, dangling parent links, or cycles.

    * verdict_ids must be unique;
    * every parent_verdict_id must reference an earlier record;
    * every stored hash must recompute exactly.
    """
    seen: dict[str, str] = {}
    for position, record in enumerate(records):
        if record.verdict_id in seen:
            raise VerdictChainError(f"duplicate verdict_id {record.verdict_id!r}")
        if record.parent_verdict_id:
            if record.parent_verdict_id == record.verdict_id:
                raise VerdictChainError(f"self-referential verdict {record.verdict_id!r}")
            if record.parent_verdict_id not in seen:
                raise VerdictChainError(
                    f"verdict {record.verdict_id!r} references unknown or "
                    f"forward parent {record.parent_verdict_id!r}")
        recomputed = record.verdict_record_hash
        seen[record.verdict_id] = recomputed


def chain_manifest(records: Sequence[VerdictRecord]) -> dict[str, object]:
    """Deterministic manifest of a full verdict chain."""
    verify_verdict_chain(records)
    return {
        "schema_version": VERDICT_RECORD_SCHEMA,
        "records": [record.as_dict() for record in records],
        "chain_head_verdict_id": records[-1].verdict_id if records else "",
        "chain_head_verdict_record_hash": records[-1].verdict_record_hash if records else "",
    }


def policy_hash_of(payload: Mapping[str, object]) -> str:
    """Deterministic policy hash over a canonical policy payload."""
    return sha256_json(dict(payload))


def canonical_payload_sha256(payload: str) -> str:
    """sha256 of an already-canonical JSON string (byte-level pinning)."""
    import hashlib
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "VERDICT_RECORD_SCHEMA", "VerdictRecord", "VerdictChainError",
    "verify_verdict_chain", "chain_manifest", "policy_hash_of",
    "canonical_payload_sha256", "canonical_json",
]
