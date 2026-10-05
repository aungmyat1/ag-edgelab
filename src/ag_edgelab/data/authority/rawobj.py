"""Raw-object identity and immutability.

A raw object is a retrieved archive that EdgeLab treats as read-only
forever. Its identity must survive re-packaging: GitHub's tarball endpoint
does not emit byte-stable gzip, so hashing the ``.tar.gz`` would produce a
different "identity" for identical data. We therefore hash CONTENT:

    member_digest   = sha256(member bytes)
    leaf            = "<relative_path>\\n<member_digest>\\n"
    raw_tree_sha256 = sha256(concat(leaf for member in sorted(paths)))

This Merkle-style root is stable across archive formats, mirrors, and
compression settings, and changes if any byte of any member changes.

The per-member index (hundreds of thousands of rows across the corpus) is
NOT committed to git; only the root and the counts are. The full index is
written to content-addressed external storage — see :mod:`.cas`.
"""

from __future__ import annotations

import hashlib
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from pydantic import BaseModel, ConfigDict


class RawIdentityError(RuntimeError):
    """Raised when a raw object's identity cannot be verified exactly."""


@dataclass(frozen=True)
class RawMember:
    relative_path: str
    sha256: str
    byte_size: int


class RawObject(BaseModel):
    """Immutable record for one retrieved raw object.

    Every field required by DATA_AUTHORITY_R1 section 4 is present and
    non-optional, so a raw object cannot be registered half-described.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_id: str
    source_id: str
    symbol: str
    sha256: str                 # raw_tree_sha256 (content Merkle root)
    byte_size: int              # sum of member byte sizes
    member_count: int
    source: str                 # human-readable provenance string
    upstream_ref: str           # immutable upstream pin (e.g. git commit)
    coverage_start: datetime
    coverage_end: datetime
    retrieval_timestamp: datetime
    timezone: str
    format: str
    local_path: str | None = None
    member_index_sha256: str | None = None  # CAS address of the full index

    def as_dict(self) -> dict:
        payload = self.model_dump(mode="json")
        return payload


def _iter_members(archive: Path, include: Callable[[str], bool]) -> Iterator[tuple[str, bytes]]:
    with tarfile.open(archive, "r|gz") as tf:        # streaming: constant memory
        for member in tf:
            if not member.isfile():
                continue
            # Strip GitHub's "<org>-<repo>-<sha>/" wrapper directory.
            parts = member.name.split("/", 1)
            relative = parts[1] if len(parts) == 2 else member.name
            if not include(relative):
                continue
            handle = tf.extractfile(member)
            if handle is None:          # pragma: no cover - defensive
                continue
            yield relative, handle.read()


def hash_archive_members(
    archive: Path, *, include: Callable[[str], bool] = lambda _: True,
) -> tuple[str, tuple[RawMember, ...]]:
    """Return ``(raw_tree_sha256, members)`` for the selected members."""
    members: list[RawMember] = []
    for relative, payload in _iter_members(Path(archive), include):
        members.append(RawMember(
            relative_path=relative,
            sha256=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
        ))
    members.sort(key=lambda m: m.relative_path)
    return merkle_root(members), tuple(members)


def merkle_root(members: list[RawMember] | tuple[RawMember, ...]) -> str:
    digest = hashlib.sha256()
    for member in sorted(members, key=lambda m: m.relative_path):
        digest.update(member.relative_path.encode("utf-8"))
        digest.update(b"\n")
        digest.update(member.sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def member_index_document(members: tuple[RawMember, ...]) -> str:
    """Byte-stable text index of every member (for external storage)."""
    lines = ["# EDGELAB_RAW_MEMBER_INDEX_V1", "relative_path,sha256,byte_size"]
    lines.extend(
        f"{m.relative_path},{m.sha256},{m.byte_size}"
        for m in sorted(members, key=lambda m: m.relative_path)
    )
    return "\n".join(lines) + "\n"


def verify_raw_object(record: RawObject, archive: Path, *,
                      include: Callable[[str], bool] = lambda _: True) -> None:
    """Fail closed if the archive on disk no longer matches its record."""
    if not Path(archive).is_file():
        raise RawIdentityError(
            f"{record.raw_id}: raw object absent at {archive} — references MUST "
            "fail closed when the expected bytes are missing")
    root, members = hash_archive_members(Path(archive), include=include)
    if root != record.sha256:
        raise RawIdentityError(
            f"{record.raw_id}: raw_tree_sha256 mismatch — expected "
            f"{record.sha256}, got {root}; STATUS=BLOCKED_DATA_AUTHORITY")
    if len(members) != record.member_count:
        raise RawIdentityError(
            f"{record.raw_id}: member_count mismatch — expected "
            f"{record.member_count}, got {len(members)}")


@dataclass
class RawManifest:
    """Collection of raw object records, keyed by raw_id."""

    manifest_version: str = "DATA_AUTHORITY_R1_RAW_MANIFEST_V1"
    objects: list[RawObject] = field(default_factory=list)

    def add(self, record: RawObject) -> None:
        if any(o.raw_id == record.raw_id for o in self.objects):
            raise RawIdentityError(f"duplicate raw_id {record.raw_id}")
        self.objects.append(record)

    def by_id(self, raw_id: str) -> RawObject:
        for obj in self.objects:
            if obj.raw_id == raw_id:
                return obj
        raise RawIdentityError(
            f"unknown raw_id {raw_id!r} — derived datasets may only reference "
            "registered raw parents")

    def as_dict(self) -> dict:
        return {
            "manifest_version": self.manifest_version,
            "immutability_rule": (
                "Raw objects are never modified in place. Identity is the "
                "content Merkle root raw_tree_sha256 over sorted "
                "(relative_path, sha256(member bytes)) leaves, which is stable "
                "across re-packaging and mirrors."
            ),
            "object_count": len(self.objects),
            "objects": [o.as_dict() for o in sorted(self.objects, key=lambda o: o.raw_id)],
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)
