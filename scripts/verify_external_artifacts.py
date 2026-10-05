#!/usr/bin/env python3
"""Verify pinned research-evidence pointers against their sha256 records.

Two pointer sections exist in
config/governance/external_artifact_registry.json:

- ``artifacts``      — EXTERNALIZED evidence: bytes live outside the
  mainline tree, currently in the git object database at the producer
  commit (``git:<commit>:<path>`` storage locations).
- ``in_tree_pinned`` — bulky evidence retained in the tree because
  runtime tests require it (``tree:<path>`` storage locations).
- ``content_addressed`` — datasets far too large for git, held in an
  external content-addressed store (``cas:<sha256>`` storage locations).
  The sha256 IS the address, so a pointer cannot drift from its content:
  any tampering changes the address and the lookup fails.

A content-addressed entry whose bytes are not present locally reports
UNMATERIALIZED rather than failing. That is deliberate: a clean checkout
legitimately has no external store, and the registry must still verify.
Materialization is only ENFORCED when ``--require-materialized`` is
passed, which is how a release or audit run asserts the data is actually
in hand.

A third scheme, ``local:<path>``, pins regenerable bulk evidence that is
gitignored by policy. It is verified when the bytes are present in the
checkout and reported as ABSENT (not a failure) when they are not; a present
copy that disagrees with the pin still fails closed.

This script retrieves the bytes from each storage location, recomputes
sha256, and fails closed on any mismatch, missing location, or byte-size
disagreement. Run it whenever evidence is retrieved, re-pinned, or
moved.

Exit codes: 0 = all resolvable pointers verified; 2 = any mismatch (fail
closed), or any unmaterialized content-addressed entry when
``--require-materialized`` is given.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "governance" / "external_artifact_registry.json"
CAS_ROOT = ROOT / "data" / "external" / "cas"

HEX64 = re.compile(r"^[0-9a-f]{64}$")
UNMATERIALIZED = "UNMATERIALIZED"


def cas_path(digest: str) -> Path:
    """Address-to-path mapping of the content-addressed store."""
    return CAS_ROOT / digest[:2] / digest


def verify_content_addressed(art: dict, failures: list[str]) -> str:
    """Verify one ``cas:<sha256>`` entry.

    Returns "VERIFIED", "UNMATERIALIZED", or "FAILED". Absence is not a
    failure here; corruption always is.
    """
    art_id = art.get("artifact_id", "<missing artifact_id>")
    digest = art.get("sha256", "")
    location = art.get("storage_location", "")

    if not HEX64.match(digest or ""):
        failures.append(f"[content_addressed] {art_id}: malformed sha256 {digest!r}")
        return "FAILED"
    if not location.startswith("cas:"):
        failures.append(f"[content_addressed] {art_id}: storage_location must be "
                        f"'cas:<sha256>', got {location!r}")
        return "FAILED"
    if location[len("cas:"):] != digest:
        failures.append(
            f"[content_addressed] {art_id}: storage_location address "
            f"{location[len('cas:'):]!r} does not equal the recorded sha256 "
            f"{digest!r} — a content-addressed pointer must BE its hash")
        return "FAILED"

    path = cas_path(digest)
    if not path.is_file():
        print(f"  {UNMATERIALIZED:14s} [content_addressed] {art_id} "
              f"(cas:{digest[:12]}... not present locally)")
        return UNMATERIALIZED

    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != digest:
        failures.append(
            f"[content_addressed] {art_id}: CONTENT MISMATCH at {path} — "
            f"recorded {digest}, computed {actual}")
        return "FAILED"

    size = path.stat().st_size
    recorded = art.get("byte_size")
    if recorded is not None and int(recorded) != size:
        failures.append(
            f"[content_addressed] {art_id}: byte_size mismatch — recorded "
            f"{recorded}, actual {size}")
        return "FAILED"
    return "VERIFIED"


def blob_bytes(location: str) -> bytes:
    """Resolve a 'git:<commit>:<path>' storage location to bytes."""
    if not location.startswith("git:"):
        raise ValueError(f"unsupported storage location: {location!r}")
    _, commit, path = location.split(":", 2)
    path = path.split(" (blob")[0].strip()
    result = subprocess.run(["git", "show", f"{commit}:{path}"],
                            cwd=ROOT, capture_output=True)
    if result.returncode != 0:
        raise ValueError(f"cannot resolve {commit}:{path}: "
                         f"{result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def tree_bytes(location: str) -> bytes:
    """Resolve a 'tree:<path>' storage location to bytes."""
    path = ROOT / location[len("tree:"):]
    if not path.is_file():
        raise ValueError(f"pinned path missing from tree: {path}")
    return path.read_bytes()


def local_bytes(location: str) -> bytes:
    """Resolve a 'local:<path>' storage location to bytes.

    ``local:`` evidence is deliberately NOT carried by the repository: it is
    bulky, gitignored, and regenerable byte-for-byte by its producer script
    from a hash-pinned source manifest. The pin is still mandatory — when the
    bytes are present they must match, and a regenerated copy that disagrees
    with the pin is a hard failure.
    """
    path = ROOT / location[len("local:"):].split(" (")[0].strip()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_bytes()


def verify_one(art: dict, section: str, failures: list) -> str:
    art_id = art["artifact_id"]
    digest = art["sha256"]
    if not HEX64.match(digest):
        failures.append(f"[{section}] {art_id}: malformed sha256 pin")
        return "FAILED"
    location = art["storage_location"]
    try:
        if location.startswith("tree:"):
            data = tree_bytes(location)
        elif location.startswith("local:"):
            data = local_bytes(location)
        else:
            data = blob_bytes(location)
    except FileNotFoundError as exc:
        # regenerable evidence absent from this checkout: report, do not verify
        print(f"ABSENT   [{section}] {art_id}  (regenerable; {exc}) "
              f"-> {art.get('retrieval', 'see producer_script')}")
        return "ABSENT"
    except (ValueError, OSError) as exc:
        failures.append(f"[{section}] {art_id}: {exc}")
        return "FAILED"
    got = hashlib.sha256(data).hexdigest()
    size = len(data)
    if got != digest:
        failures.append(f"[{section}] {art_id}: sha256 mismatch "
                        f"(pinned {digest[:16]}…, got {got[:16]}…)")
        return "FAILED"
    if size != art["byte_size"]:
        failures.append(f"[{section}] {art_id}: byte_size mismatch "
                        f"(pinned {art['byte_size']}, got {size})")
        return "FAILED"
    print(f"VERIFIED [{section}] {art_id}  sha256={digest[:16]}…  "
          f"{size} bytes")
    return "VERIFIED"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    require_materialized = "--require-materialized" in argv

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    failures: list[str] = []
    verified = 0
    absent_count = 0
    sections = [("externalized", registry["artifacts"]),
                ("in_tree_pinned", registry.get("in_tree_pinned", []))]
    for section, arts in sections:
        for art in arts:
            outcome = verify_one(art, section, failures)
            if outcome == "VERIFIED":
                verified += 1
            elif outcome == "ABSENT":
                absent_count += 1

    cas_entries = registry.get("content_addressed", [])
    cas_verified = 0
    cas_unmaterialized: list[str] = []
    for art in cas_entries:
        outcome = verify_content_addressed(art, failures)
        if outcome == "VERIFIED":
            cas_verified += 1
        elif outcome == UNMATERIALIZED:
            cas_unmaterialized.append(art.get("artifact_id", "<unknown>"))

    if require_materialized and cas_unmaterialized:
        failures.append(
            "--require-materialized: "
            f"{len(cas_unmaterialized)} content-addressed artifact(s) are not "
            f"present locally: {sorted(cas_unmaterialized)}")

    total_pointers = len(registry["artifacts"]) + len(registry.get("in_tree_pinned", []))

    if failures:
        print("\nARTIFACT POINTER VERIFICATION FAILED (fail closed):",
              file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 2
    summary = (f"{verified}/{total_pointers} VERIFIED, {absent_count} ABSENT "
               f"(regenerable), {cas_verified}/{len(cas_entries)} CAS materialized")
    if cas_unmaterialized:
        summary += (f"\n  {len(cas_unmaterialized)} content-addressed artifact(s) "
                    "UNMATERIALIZED (not an error: a clean checkout has no external "
                    "store; use --require-materialized to enforce presence)")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
