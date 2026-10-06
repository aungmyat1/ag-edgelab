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
* PARENT VERDICT ID **and the parent's VERDICT_RECORD_HASH** (when lineage
  exists) — the child embeds the parent's record hash, so any mutation of
  an earlier record's payload changes its recomputed hash and breaks the
  link to every descendant.

Hash linking is required NOW; cryptographic signing is a possible later
governance layer and is deliberately out of scope.  The record payload
contains no wall-clock fields, so identical inputs always produce an
identical VERDICT_RECORD_HASH.

Verification contract
---------------------
:func:`verify_verdict_chain` recomputes every record's hash and compares
it against the STORED hash when one is supplied (``stored_hashes`` or a
manifest via :func:`verify_chain_manifest`).  A mutated payload therefore
fails closed instead of silently re-verifying.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Mapping, Sequence

from ag_edgelab.data.fingerprint import sha256_json

VERDICT_RECORD_SCHEMA = "VERDICT_RECORD_V1"


class VerdictChainError(RuntimeError):
    """A hash-linked verdict chain is malformed, mutated, or dangling."""


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
    parent_verdict_record_hash: str = ""
    notes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.verdict_id:
            raise ValueError("verdict_id is required")
        if self.schema_version != VERDICT_RECORD_SCHEMA:
            raise ValueError(f"unsupported verdict record schema: {self.schema_version}")
        for name in ("policy_hash", "dataset_hash", "dataset_manifest_hash",
                     "candidate_contract_hash", "engine_code_sha",
                     "event_table_hash", "friction_authority_hash",
                     "verdict", "parent_verdict_id", "parent_verdict_record_hash"):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"{name} must be a string")

    def payload_dict(self) -> dict[str, object]:
        return asdict(self)

    @property
    def verdict_record_hash(self) -> str:
        """Deterministic identity over the full canonical payload."""
        return sha256_json(self.payload_dict())

    def as_dict(self) -> dict[str, object]:
        return dict(self.payload_dict(),
                    verdict_record_hash=self.verdict_record_hash)


def verify_verdict_chain(records: Sequence[VerdictRecord],
                         *, stored_hashes: Mapping[str, str] | None = None) -> None:
    """Fail closed on mutation, dangling parent links, or broken hash links.

    * verdict_ids must be unique;
    * every parent_verdict_id must reference an earlier record;
    * a child with a parent MUST embed that parent's exact record hash
      (``parent_verdict_record_hash``), recomputed from the parent's
      current payload — a mutated ancestor therefore breaks the chain;
    * when ``stored_hashes`` is supplied, every record's recomputed hash
      must equal the stored value (byte-level mutation detection).
    """
    recomputed: dict[str, str] = {}
    for record in records:
        if record.verdict_id in recomputed:
            raise VerdictChainError(f"duplicate verdict_id {record.verdict_id!r}")
        if record.parent_verdict_id:
            if record.parent_verdict_id == record.verdict_id:
                raise VerdictChainError(f"self-referential verdict {record.verdict_id!r}")
            if record.parent_verdict_id not in recomputed:
                raise VerdictChainError(
                    f"verdict {record.verdict_id!r} references unknown or "
                    f"forward parent {record.parent_verdict_id!r}")
            parent_hash = recomputed[record.parent_verdict_id]
            if not record.parent_verdict_record_hash:
                raise VerdictChainError(
                    f"verdict {record.verdict_id!r} names parent "
                    f"{record.parent_verdict_id!r} without embedding its "
                    "verdict_record_hash; hash linking is required")
            if record.parent_verdict_record_hash != parent_hash:
                raise VerdictChainError(
                    f"verdict {record.verdict_id!r} parent hash mismatch: "
                    f"embedded {record.parent_verdict_record_hash} != recomputed "
                    f"{parent_hash}; an ancestor record was mutated")
        recomputed[record.verdict_id] = record.verdict_record_hash
    if stored_hashes is not None:
        missing = set(recomputed) - set(stored_hashes)
        if missing:
            raise VerdictChainError(f"stored hashes missing for {sorted(missing)}")
        for verdict_id, stored in stored_hashes.items():
            if verdict_id not in recomputed:
                raise VerdictChainError(f"stored hash for unknown verdict {verdict_id!r}")
            if recomputed[verdict_id] != stored:
                raise VerdictChainError(
                    f"verdict {verdict_id!r} payload hash mismatch: recomputed "
                    f"{recomputed[verdict_id]} != stored {stored}; the record "
                    "was mutated after its hash was recorded")


def chain_manifest(records: Sequence[VerdictRecord]) -> dict[str, object]:
    """Deterministic manifest of a full verdict chain."""
    verify_verdict_chain(records)
    return {
        "schema_version": VERDICT_RECORD_SCHEMA,
        "records": [record.as_dict() for record in records],
        "chain_head_verdict_id": records[-1].verdict_id if records else "",
        "chain_head_verdict_record_hash": records[-1].verdict_record_hash if records else "",
    }


def verify_chain_manifest(manifest: Mapping[str, object]) -> None:
    """Verify a persisted chain manifest end-to-end, stored hashes included.

    Rebuilds each :class:`VerdictRecord` from the manifest payload, checks
    the manifest's own stored ``verdict_record_hash`` per record, validates
    the parent-hash links, and pins the chain head fields.
    """
    records_payload = manifest.get("records")
    if not isinstance(records_payload, list) or not records_payload:
        raise VerdictChainError("manifest has no records")
    records: list[VerdictRecord] = []
    stored: dict[str, str] = {}
    for item in records_payload:
        if not isinstance(item, Mapping):
            raise VerdictChainError("malformed manifest record")
        payload = dict(item)
        stored_hash = payload.pop("verdict_record_hash", None)
        if not isinstance(stored_hash, str) or not stored_hash:
            raise VerdictChainError("manifest record is missing its stored hash")
        try:
            record = VerdictRecord(**payload)
        except (TypeError, ValueError) as exc:
            raise VerdictChainError(f"malformed manifest record: {exc}") from exc
        if record.verdict_record_hash != stored_hash:
            raise VerdictChainError(
                f"manifest record {record.verdict_id!r} hash mismatch: "
                f"recomputed {record.verdict_record_hash} != stored {stored_hash}")
        if record.verdict_id in stored:
            raise VerdictChainError(f"duplicate verdict_id {record.verdict_id!r}")
        stored[record.verdict_id] = stored_hash
        records.append(record)
    verify_verdict_chain(records, stored_hashes=stored)
    head_id = manifest.get("chain_head_verdict_id")
    head_hash = manifest.get("chain_head_verdict_record_hash")
    if head_id != records[-1].verdict_id or head_hash != records[-1].verdict_record_hash:
        raise VerdictChainError("manifest chain head does not match its last record")


def policy_hash_of(payload: Mapping[str, object]) -> str:
    """Deterministic policy hash over a canonical policy payload."""
    return sha256_json(dict(payload))


def canonical_payload_sha256(payload: str) -> str:
    """sha256 of an already-canonical JSON string (byte-level pinning)."""
    import hashlib
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "VERDICT_RECORD_SCHEMA", "VerdictRecord", "VerdictChainError",
    "verify_verdict_chain", "verify_chain_manifest", "chain_manifest",
    "policy_hash_of", "canonical_payload_sha256",
]
