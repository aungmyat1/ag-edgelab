"""Immutable daily capture bundles and their append-only registry.

Spread evidence is only worth anything if it accumulates honestly. A
capture that rewrites yesterday's file every time it runs is not
evidence, it is a moving average of whatever the market happened to be
doing when someone last looked.

So the rules here are deliberately rigid:

* one sealed bundle per capture run, named ``friction_capture_YYYYMMDD``
  (with ``_002``, ``_003`` … for additional runs on the same day);
* a bundle is **sealed** once its manifest is written, and re-sealing
  with different content raises rather than overwriting;
* the registry is **append-only** — a new run adds a row, it never
  edits a prior one;
* the registry records sha256, byte size, capture window, symbol set and
  sample count per bundle, so the evidence base can be audited without
  reading the (large, un-committed) quote CSVs.

Scheduler safety matters because the whole point is unattended repeated
execution. A lock file prevents two overlapping runs from interleaving
writes into the same directory.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ag_edgelab.friction.authority.capture_schema import (
    build_manifest, sha256_file,
)

REGISTRY_SCHEMA = "VT_MARKETS_CAPTURE_REGISTRY_V1"
REGISTRY_NAME = "capture_registry.json"
BUNDLE_PREFIX = "friction_capture_"
BUNDLE_RE = re.compile(r"^friction_capture_(\d{8})(?:_(\d{3}))?$")


class CaptureLocked(RuntimeError):
    """Another capture is already running against this root."""


class BundleSealed(RuntimeError):
    """An attempt was made to modify evidence that is already sealed."""


class RegistryViolation(RuntimeError):
    """An append-only registry rule was violated."""


def bundle_name(day: datetime, sequence: int = 1) -> str:
    stamp = day.astimezone(timezone.utc).strftime("%Y%m%d")
    return (f"{BUNDLE_PREFIX}{stamp}" if sequence <= 1
            else f"{BUNDLE_PREFIX}{stamp}_{sequence:03d}")


def parse_bundle_name(name: str) -> tuple[str, int] | None:
    m = BUNDLE_RE.match(name)
    if not m:
        return None
    return m.group(1), int(m.group(2) or 1)


def next_bundle_dir(root: Path, day: datetime | None = None) -> Path:
    """Pick the next unused bundle directory for ``day``.

    Never returns a path that already exists, so a scheduled re-run
    appends a new bundle instead of touching the previous one.
    """
    root = Path(root)
    day = day or datetime.now(timezone.utc)
    for sequence in range(1, 1000):
        candidate = root / bundle_name(day, sequence)
        if not candidate.exists():
            return candidate
    raise RegistryViolation(
        "1000 bundles already exist for this day; refusing to continue")


@contextmanager
def capture_lock(root: Path, *, stale_after_seconds: float = 6 * 3600):
    """Prevent overlapping scheduled captures from sharing a directory."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".capture.lock"
    if lock.exists():
        age = datetime.now(timezone.utc).timestamp() - lock.stat().st_mtime
        if age < stale_after_seconds:
            raise CaptureLocked(
                f"{lock} is held (age {age:.0f}s). Another capture is "
                "running; this one is exiting rather than interleaving "
                "writes into the same evidence directory.")
        lock.unlink()                      # stale: previous run died
    lock.write_text(json.dumps({
        "acquired_utc": datetime.now(timezone.utc).isoformat()}))
    try:
        yield lock
    finally:
        lock.unlink(missing_ok=True)


def seal_bundle(bundle_dir: Path) -> dict:
    """Write BUNDLE_MANIFEST.json, making the bundle immutable evidence."""
    bundle_dir = Path(bundle_dir)
    manifest_path = bundle_dir / "BUNDLE_MANIFEST.json"
    manifest = build_manifest(bundle_dir)
    manifest["sealed_utc"] = datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z")
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text())
        if existing.get("manifest_root_sha256") != manifest["manifest_root_sha256"]:
            raise BundleSealed(
                f"{bundle_dir.name} is already sealed with a different root "
                f"hash ({existing.get('manifest_root_sha256', '')[:16]}... vs "
                f"{manifest['manifest_root_sha256'][:16]}...). Prior evidence "
                "is never rewritten; capture a new bundle instead.")
        return existing
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


@dataclass(frozen=True)
class RegistryRow:
    bundle: str
    manifest_root_sha256: str
    byte_size: int
    file_count: int
    capture_started_utc: str | None
    capture_ended_utc: str | None
    symbols: tuple[str, ...]
    sample_count: int
    quote_counts: dict

    def as_dict(self) -> dict:
        return {
            "bundle": self.bundle,
            "manifest_root_sha256": self.manifest_root_sha256,
            "byte_size": self.byte_size,
            "file_count": self.file_count,
            "capture_started_utc": self.capture_started_utc,
            "capture_ended_utc": self.capture_ended_utc,
            "symbols": list(self.symbols),
            "sample_count": self.sample_count,
            "quote_counts": self.quote_counts,
        }


def row_for(bundle_dir: Path, manifest: dict, metadata: dict) -> RegistryRow:
    counts = metadata.get("quote_counts", {}) or {}
    return RegistryRow(
        bundle=Path(bundle_dir).name,
        manifest_root_sha256=manifest["manifest_root_sha256"],
        byte_size=manifest["total_bytes"],
        file_count=manifest["file_count"],
        capture_started_utc=metadata.get("capture_started_utc"),
        capture_ended_utc=metadata.get("capture_ended_utc"),
        symbols=tuple(metadata.get("symbols", []) or []),
        sample_count=int(sum(counts.values())) if counts else 0,
        quote_counts=counts,
    )


def load_registry(root: Path) -> dict:
    path = Path(root) / REGISTRY_NAME
    if not path.is_file():
        return {"schema": REGISTRY_SCHEMA, "bundles": [],
                "append_only": True, "bundle_count": 0,
                "total_samples": 0, "total_bytes": 0}
    return json.loads(path.read_text())


def append_registry(root: Path, row: RegistryRow) -> dict:
    """Append one bundle. Refuses to modify or duplicate an existing row."""
    root = Path(root)
    registry = load_registry(root)
    for existing in registry["bundles"]:
        if existing["bundle"] != row.bundle:
            continue
        if existing["manifest_root_sha256"] == row.manifest_root_sha256:
            return registry                 # idempotent re-append
        raise RegistryViolation(
            f"{row.bundle} is already registered with a different hash. "
            "The registry is append-only; prior evidence is never edited.")

    registry["bundles"].append(row.as_dict())
    registry["bundles"].sort(key=lambda r: r["bundle"])
    registry["schema"] = REGISTRY_SCHEMA
    registry["append_only"] = True
    registry["bundle_count"] = len(registry["bundles"])
    registry["total_samples"] = sum(r["sample_count"] for r in registry["bundles"])
    registry["total_bytes"] = sum(r["byte_size"] for r in registry["bundles"])
    registry["symbols_seen"] = sorted(
        {s for r in registry["bundles"] for s in r["symbols"]})
    registry["updated_utc"] = datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z")
    (root / REGISTRY_NAME).write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n")
    return registry


def verify_registry(root: Path) -> dict:
    """Re-hash every registered bundle and report any drift."""
    root = Path(root)
    registry = load_registry(root)
    problems: list[str] = []
    verified = 0
    for row in registry["bundles"]:
        bundle_dir = root / row["bundle"]
        manifest_path = bundle_dir / "BUNDLE_MANIFEST.json"
        if not manifest_path.is_file():
            problems.append(f"{row['bundle']}: manifest absent")
            continue
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("manifest_root_sha256") != row["manifest_root_sha256"]:
            problems.append(f"{row['bundle']}: manifest root differs from registry")
            continue
        actual = build_manifest(bundle_dir)
        if actual["manifest_root_sha256"] != row["manifest_root_sha256"]:
            problems.append(
                f"{row['bundle']}: on-disk content no longer matches its "
                "sealed manifest")
            continue
        verified += 1
    return {
        "bundle_count": registry["bundle_count"],
        "verified": verified,
        "problems": problems,
        "all_verified": not problems and verified == registry["bundle_count"],
    }
