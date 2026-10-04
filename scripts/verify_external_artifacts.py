#!/usr/bin/env python3
"""Verify externalized artifacts against their pinned sha256 pointers.

Every record in config/governance/external_artifact_registry.json points at
bytes stored OUTSIDE the mainline tree (currently: the git object database
at the producer commit). This script retrieves the bytes from each storage
location, recomputes sha256, and fails closed on any mismatch or missing
location. Run it whenever an external artifact is retrieved or re-pinned.

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


def main() -> int:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    failures = []
    for art in registry["artifacts"]:
        art_id = art["artifact_id"]
        digest = art["sha256"]
        if not HEX64.match(digest):
            failures.append(f"{art_id}: malformed sha256 pin")
            continue
        try:
            data = blob_bytes(art["storage_location"])
        except ValueError as exc:
            failures.append(f"{art_id}: {exc}")
            continue
        got = hashlib.sha256(data).hexdigest()
        size = len(data)
        if got != digest:
            failures.append(f"{art_id}: sha256 mismatch "
                            f"(pinned {digest[:16]}…, got {got[:16]}…)")
        elif size != art["byte_size"]:
            failures.append(f"{art_id}: byte_size mismatch "
                            f"(pinned {art['byte_size']}, got {size})")
        else:
            print(f"VERIFIED {art_id}  sha256={digest[:16]}…  "
                  f"{size} bytes")
    if failures:
        print("\nEXTERNAL ARTIFACT VERIFICATION FAILED (fail closed):",
              file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 2
    print(f"ALL {len(registry['artifacts'])} EXTERNAL ARTIFACT POINTERS "
          f"VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
