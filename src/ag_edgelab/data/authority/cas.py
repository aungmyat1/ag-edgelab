"""Content-addressed storage for bulky data-authority objects.

Git holds manifests, hashes, schemas, small reports and code. Normalized
bar datasets and raw member indexes are far too large for that, so they
live in a content-addressed store outside the tree:

    <root>/<first two hex chars>/<full sha256>

The address IS the hash, so the store cannot hold a mislabelled object, and
every reference is self-verifying.

FAIL-CLOSED CONTRACT
--------------------
:meth:`CasStore.get` raises when the object is absent
(:class:`ContentUnavailable`) and when the bytes do not hash to the
requested address (:class:`ContentMismatch`). There is no "best effort"
read: a consumer either gets exactly the bytes it asked for, or an
exception. Callers therefore cannot silently proceed on missing or
corrupted evidence.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

HEX64 = re.compile(r"^[0-9a-f]{64}$")

CAS_SCHEME = "cas:"


class CasError(RuntimeError):
    """Base class for content-addressed storage failures."""


class ContentUnavailable(CasError):
    """The referenced object is not present in this store."""


class ContentMismatch(CasError):
    """The stored bytes do not hash to the requested address."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(payload: str) -> str:
    return sha256_bytes(payload.encode("utf-8"))


@dataclass(frozen=True)
class CasEntry:
    artifact_id: str
    sha256: str
    byte_size: int
    schema_version: str
    description: str = ""

    @property
    def storage_location(self) -> str:
        return f"{CAS_SCHEME}{self.sha256}"

    def as_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "schema_version": self.schema_version,
            "storage_location": self.storage_location,
            "description": self.description,
        }


class CasStore:
    """A directory-backed content-addressed store."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)

    def path_for(self, digest: str) -> Path:
        if not HEX64.match(digest):
            raise CasError(f"not a canonical sha256 address: {digest!r}")
        return self.root / digest[:2] / digest

    def has(self, digest: str) -> bool:
        return self.path_for(digest).is_file()

    def put_bytes(self, payload: bytes) -> str:
        digest = sha256_bytes(payload)
        target = self.path_for(digest)
        if target.is_file():
            # Already stored; verify rather than trust the filename.
            if sha256_bytes(target.read_bytes()) != digest:
                raise ContentMismatch(
                    f"existing object at {target} no longer hashes to {digest}")
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".part")
        tmp.write_bytes(payload)
        tmp.replace(target)
        return digest

    def put_text(self, payload: str) -> str:
        return self.put_bytes(payload.encode("utf-8"))

    def get_bytes(self, digest: str) -> bytes:
        target = self.path_for(digest)
        if not target.is_file():
            raise ContentUnavailable(
                f"content-addressed object {digest} is not materialized at "
                f"{target}. References fail closed: rebuild it with the "
                "declared producer script, or materialize the store, before "
                "using any dataset that depends on it.")
        payload = target.read_bytes()
        actual = sha256_bytes(payload)
        if actual != digest:
            raise ContentMismatch(
                f"content-addressed object {digest} is corrupt: stored bytes "
                f"hash to {actual}; STATUS=BLOCKED_DATA_AUTHORITY")
        return payload

    def get_text(self, digest: str) -> str:
        return self.get_bytes(digest).decode("utf-8")

    def store_entry(self, artifact_id: str, payload: str, *,
                    schema_version: str, description: str = "") -> CasEntry:
        digest = self.put_text(payload)
        return CasEntry(
            artifact_id=artifact_id,
            sha256=digest,
            byte_size=len(payload.encode("utf-8")),
            schema_version=schema_version,
            description=description,
        )


def parse_cas_location(location: str) -> str:
    if not location.startswith(CAS_SCHEME):
        raise CasError(f"not a cas: storage location: {location!r}")
    digest = location[len(CAS_SCHEME):]
    if not HEX64.match(digest):
        raise CasError(f"malformed cas address in {location!r}")
    return digest
