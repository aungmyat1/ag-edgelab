"""Schema and hash verification for a VT Markets evidence bundle.

The capture tool runs on the user's own Windows/MT5 machine; this module
is the contract between that tool and the repository. A bundle is a
directory:

    bundle/
      capture_metadata.json     venue identity, tool version, window
      symbol_metadata.json      per-symbol MT5 contract fields
      commission.json           commission authority, or MISSING
      swap.json                 swap_long / swap_short / mode
      slippage.json             fill-derived slippage, or MISSING
      quotes/<SYMBOL>.csv       raw tick observations, one row per quote
      BUNDLE_MANIFEST.json      sha256 of every file above

Every object is hash-verifiable: the manifest carries a sha256 per file
and a Merkle-style root over the sorted (path, sha256) pairs, so a
bundle that was edited after capture cannot be ingested unnoticed. The
large quote CSVs stay outside git; only the manifest, schema, hashes,
capture metadata and the summary report are committed.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

CAPTURE_SCHEMA_VERSION = "VT_MARKETS_FRICTION_CAPTURE_V1"

QUOTE_CSV_COLUMNS: tuple[str, ...] = (
    "timestamp_utc",
    "symbol",
    "bid",
    "ask",
    "spread_price",
    "spread_points",
    "session",
)

REQUIRED_BUNDLE_FILES: tuple[str, ...] = (
    "capture_metadata.json",
    "symbol_metadata.json",
    "commission.json",
    "swap.json",
    "slippage.json",
)

#: Fields the capture tool must read from MT5. Anything the terminal does
#: not expose is written as null and stays null — never defaulted.
REQUIRED_CAPTURE_METADATA: tuple[str, ...] = (
    "schema_version", "tool_version", "broker", "server", "account_class",
    "account_type", "account_currency", "terminal_build",
    "capture_started_utc", "capture_ended_utc", "symbols",
)


class BundleInvalid(RuntimeError):
    """The evidence bundle is malformed, incomplete or hash-mismatched."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_root(entries: dict[str, str]) -> str:
    """Stable root hash over sorted ``path -> sha256`` pairs."""
    h = hashlib.sha256()
    for path in sorted(entries):
        h.update(path.encode())
        h.update(b"\x00")
        h.update(entries[path].encode())
        h.update(b"\n")
    return h.hexdigest()


def build_manifest(bundle_dir: Path) -> dict:
    """Hash every file in the bundle except the manifest itself."""
    entries: dict[str, str] = {}
    for p in sorted(bundle_dir.rglob("*")):
        if not p.is_file() or p.name == "BUNDLE_MANIFEST.json":
            continue
        entries[p.relative_to(bundle_dir).as_posix()] = sha256_file(p)
    return {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "files": entries,
        "file_count": len(entries),
        "total_bytes": sum(
            (bundle_dir / rel).stat().st_size for rel in entries),
        "manifest_root_sha256": manifest_root(entries),
    }


def verify_bundle(bundle_dir: Path) -> dict:
    """Verify structure and hashes. Raises ``BundleInvalid`` on any fault."""
    bundle_dir = Path(bundle_dir)
    if not bundle_dir.is_dir():
        raise BundleInvalid(f"bundle directory not found: {bundle_dir}")

    manifest_path = bundle_dir / "BUNDLE_MANIFEST.json"
    if not manifest_path.is_file():
        raise BundleInvalid("BUNDLE_MANIFEST.json is missing; an unmanifested "
                            "bundle is not hash-verifiable evidence")
    manifest = json.loads(manifest_path.read_text())

    missing = [f for f in REQUIRED_BUNDLE_FILES
               if not (bundle_dir / f).is_file()]
    if missing:
        raise BundleInvalid(f"bundle is missing required files: {missing}")

    recorded = manifest.get("files", {})
    actual = build_manifest(bundle_dir)["files"]

    only_recorded = sorted(set(recorded) - set(actual))
    only_actual = sorted(set(actual) - set(recorded))
    if only_recorded:
        raise BundleInvalid(f"manifest lists files not present: {only_recorded}")
    if only_actual:
        raise BundleInvalid(f"bundle contains unmanifested files: {only_actual}")

    mismatched = [p for p in sorted(recorded) if recorded[p] != actual[p]]
    if mismatched:
        raise BundleInvalid(
            f"hash mismatch on {mismatched}: the bundle was modified after "
            "capture and cannot be treated as evidence")

    root = manifest_root(actual)
    if manifest.get("manifest_root_sha256") != root:
        raise BundleInvalid(
            f"manifest root mismatch: recorded "
            f"{manifest.get('manifest_root_sha256')!r} computed {root!r}")

    meta = json.loads((bundle_dir / "capture_metadata.json").read_text())
    missing_meta = [k for k in REQUIRED_CAPTURE_METADATA if k not in meta]
    if missing_meta:
        raise BundleInvalid(
            f"capture_metadata.json is missing keys {missing_meta}")
    if meta.get("schema_version") != CAPTURE_SCHEMA_VERSION:
        raise BundleInvalid(
            f"schema version {meta.get('schema_version')!r} != "
            f"{CAPTURE_SCHEMA_VERSION!r}")

    return {
        "bundle_dir": str(bundle_dir),
        "verified": True,
        "file_count": len(actual),
        "manifest_root_sha256": root,
        "files": actual,
    }


@dataclass(frozen=True)
class QuoteFileSummary:
    symbol: str
    path: str
    rows: int
    sha256: str


def read_quote_csv(path: Path) -> list[dict]:
    """Read a quote CSV, validating the header against the schema."""
    with Path(path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        header = tuple(reader.fieldnames or ())
        if header != QUOTE_CSV_COLUMNS:
            raise BundleInvalid(
                f"{path}: header {header} != expected {QUOTE_CSV_COLUMNS}")
        return list(reader)
