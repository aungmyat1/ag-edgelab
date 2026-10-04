#!/usr/bin/env python3
"""Verify pinned research-evidence pointers against their sha256 records.

Two pointer sections exist in
config/governance/external_artifact_registry.json:

- ``artifacts``      — EXTERNALIZED evidence: bytes live outside the
  mainline tree, currently in the git object database at the producer
  commit (``git:<commit>:<path>`` storage locations).
- ``in_tree_pinned`` — bulky evidence retained in the tree because
  runtime tests require it (``tree:<path>`` storage locations).

This script retrieves the bytes from each storage location, recomputes
sha256, and fails closed on any mismatch, missing location, or byte-size
disagreement. Run it whenever evidence is retrieved, re-pinned, or
moved.

Exit codes: 0 = all pointers verified; 2 = any mismatch (fail closed).
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

HEX64 = re.compile(r"^[0-9a-f]{64}$")


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


def verify_one(art: dict, section: str, failures: list) -> bool:
    art_id = art["artifact_id"]
    digest = art["sha256"]
    if not HEX64.match(digest):
        failures.append(f"[{section}] {art_id}: malformed sha256 pin")
        return False
    try:
        if art["storage_location"].startswith("tree:"):
            data = tree_bytes(art["storage_location"])
        else:
            data = blob_bytes(art["storage_location"])
    except (ValueError, OSError) as exc:
        failures.append(f"[{section}] {art_id}: {exc}")
        return False
    got = hashlib.sha256(data).hexdigest()
    size = len(data)
    if got != digest:
        failures.append(f"[{section}] {art_id}: sha256 mismatch "
                        f"(pinned {digest[:16]}…, got {got[:16]}…)")
        return False
    if size != art["byte_size"]:
        failures.append(f"[{section}] {art_id}: byte_size mismatch "
                        f"(pinned {art['byte_size']}, got {size})")
        return False
    print(f"VERIFIED [{section}] {art_id}  sha256={digest[:16]}…  "
          f"{size} bytes")
    return True


def main() -> int:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    failures: list[str] = []
    verified = 0
    sections = [("externalized", registry["artifacts"]),
                ("in_tree_pinned", registry.get("in_tree_pinned", []))]
    for section, arts in sections:
        for art in arts:
            if verify_one(art, section, failures):
                verified += 1
    if failures:
        print("\nARTIFACT POINTER VERIFICATION FAILED (fail closed):",
              file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 2
    print(f"ALL {verified} ARTIFACT POINTERS VERIFIED "
          f"({len(registry['artifacts'])} externalized, "
          f"{len(registry.get('in_tree_pinned', []))} in-tree pinned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
