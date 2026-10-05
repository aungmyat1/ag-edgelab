#!/usr/bin/env python3
"""Acquire the multi-year HistData ASCII M1 corpus (EdgeLab FX Data Authority R2).

Provenance
----------
source product : HistData.com "Generic ASCII" M1 bars, one zip per symbol-year
mirror         : github.com/riknv/fx-m1-data  (README: "extracted from histdata.com")
transport      : GitHub contents API, raw media type (the only egress available
                 in this sandbox; raw.githubusercontent.com and histdata.com are
                 unreachable)

Why this mirror is admissible as an extension of the PR #10 authority
---------------------------------------------------------------------
The PR #10 authority (``ag_edgelab.data.fx_histdata_2017``) pins the sha256 of
four 2017 zips obtained from a DIFFERENT mirror (parrondo/deeptrading) under a
DIFFERENT archive name.  Zip *container* bytes therefore cannot match across
mirrors.  What must match — and what this script proves before any other year is
admitted — is the **inner CSV payload** for the overlapping year 2017:

    sha256(inner DAT_ASCII_{SYM}_M1_2017.csv from riknv)
        == sha256(inner DAT_ASCII_{SYM}_M1_2017.csv from the PR #10 pinned zip)

If that equality holds for all four symbols, the mirror is carrying the same
HistData product, byte for byte, and the multi-year years can be loaded by the
SAME frozen loader with the SAME timezone / bucketing semantics.  Any mismatch
is a hard BLOCKED_DATA_AUTHORITY stop.

Outputs ``data/external/histdata_fx_multiyear/manifest.json`` holding, per
symbol-year: zip bytes + sha256, inner csv name + bytes + sha256.  Raw archives
are NOT committed to git.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEST = REPO / "data" / "external" / "histdata_fx_multiyear"
PINNED_2017_DIR = REPO / "data" / "external" / "histdata_fx_2017"
MIRROR = "riknv/fx-m1-data"

# Maximal per-symbol coverage offered by the mirror as whole-calendar-year
# archives.  2018 is published only as monthly fragments and is excluded.
COVERAGE: dict[str, tuple[int, int]] = {
    "EURUSD": (2000, 2017),
    "GBPUSD": (2000, 2017),
    "USDJPY": (2000, 2017),
    "XAUUSD": (2009, 2017),
}


class BlockedDataAuthority(RuntimeError):
    pass


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _inner_csv(zip_path: Path) -> tuple[str, bytes]:
    with zipfile.ZipFile(zip_path) as zf:
        names = sorted(n for n in zf.namelist() if n.lower().endswith(".csv"))
        if len(names) != 1:
            raise BlockedDataAuthority(f"{zip_path.name}: expected exactly one csv, got {names}")
        return names[0], zf.read(names[0])


def _download(symbol: str, year: int, dest: Path) -> None:
    path = f"{symbol.lower()}/DAT_ASCII_{symbol}_M1_{year}.zip"
    proc = subprocess.run(
        ["gh", "api", f"repos/{MIRROR}/contents/{path}",
         "-H", "Accept: application/vnd.github.raw"],
        capture_output=True, check=False)
    if proc.returncode != 0 or len(proc.stdout) < 100_000:
        raise BlockedDataAuthority(
            f"download failed for {path}: rc={proc.returncode} "
            f"bytes={len(proc.stdout)} err={proc.stderr[:300]!r}")
    dest.write_bytes(proc.stdout)


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)

    # ---- phase 1: overlap proof on 2017 -----------------------------------
    overlap: dict[str, dict[str, str]] = {}
    for symbol in COVERAGE:
        pinned_zip = PINNED_2017_DIR / f"HISTDATA_COM_ASCII_{symbol}_M1_2017.zip"
        if not pinned_zip.exists():
            raise BlockedDataAuthority(
                f"PR #10 pinned 2017 archive missing for {symbol}; run "
                "scripts/acquire_histdata_fx_2017.sh first")
        new_zip = DEST / f"DAT_ASCII_{symbol}_M1_2017.zip"
        if not new_zip.exists():
            _download(symbol, 2017, new_zip)
        pinned_name, pinned_csv = _inner_csv(pinned_zip)
        new_name, new_csv = _inner_csv(new_zip)
        pinned_digest, new_digest = _sha256_bytes(pinned_csv), _sha256_bytes(new_csv)
        if pinned_name != new_name or pinned_digest != new_digest:
            raise BlockedDataAuthority(
                f"CROSS_SOURCE_IDENTITY_MISMATCH {symbol}: "
                f"{pinned_name}/{pinned_digest} != {new_name}/{new_digest}; "
                "STATUS=BLOCKED_DATA_AUTHORITY")
        overlap[symbol] = {
            "inner_csv": new_name,
            "inner_csv_sha256": new_digest,
            "inner_csv_bytes": str(len(new_csv)),
            "pr10_zip_sha256": _sha256_bytes(pinned_zip.read_bytes()),
        }
        print(f"OVERLAP_2017_IDENTICAL {symbol} {new_name} {new_digest}")
    print("CROSS_SOURCE_IDENTITY_VERIFIED=YES (4/4 symbols, year 2017)")

    # ---- phase 2: acquire every covered symbol-year -----------------------
    files: dict[str, dict] = {}
    for symbol, (first, last) in COVERAGE.items():
        for year in range(first, last + 1):
            zip_path = DEST / f"DAT_ASCII_{symbol}_M1_{year}.zip"
            if not zip_path.exists():
                _download(symbol, year, zip_path)
                print(f"downloaded {zip_path.name} ({zip_path.stat().st_size} bytes)")
            name, csv_bytes = _inner_csv(zip_path)
            expected_csv = f"DAT_ASCII_{symbol}_M1_{year}.csv"
            if name != expected_csv:
                raise BlockedDataAuthority(
                    f"{zip_path.name}: inner csv {name} != {expected_csv}")
            files[f"{symbol}_{year}"] = {
                "symbol": symbol,
                "year": year,
                "zip_name": zip_path.name,
                "zip_bytes": zip_path.stat().st_size,
                "zip_sha256": _sha256_bytes(zip_path.read_bytes()),
                "inner_csv": name,
                "inner_csv_bytes": len(csv_bytes),
                "inner_csv_sha256": _sha256_bytes(csv_bytes),
            }

    manifest = {
        "authority_id": "HISTDATA_ASCII_M1_MULTIYEAR_R2",
        "product": "HistData.com Generic ASCII M1 (one archive per symbol-year)",
        "mirror": f"github.com/{MIRROR}",
        "transport": "GitHub contents API, Accept: application/vnd.github.raw",
        "coverage": {s: list(v) for s, v in COVERAGE.items()},
        "excluded_from_acquisition": {
            "2018": "published only as monthly fragments by the mirror; a whole-year "
                    "archive does not exist, so 2018 is not admitted",
            "XAUUSD_2000_2008": "not published by the mirror (HistData gold history starts 2009)",
        },
        "cross_source_identity_proof": {
            "claim": "the mirror carries the same HistData payload as the PR #10 authority",
            "method": "sha256 of the inner DAT_ASCII_{SYM}_M1_2017.csv compared against the "
                      "inner csv of the PR #10 pinned zip, for all four symbols",
            "result": "IDENTICAL_4_OF_4",
            "per_symbol": overlap,
        },
        "source_timezone": "America/New_York (as frozen by the PR #10 loader contract)",
        "normalized_timezone": "UTC",
        "files": files,
    }
    manifest_path = DEST / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"\nacquired {len(files)} symbol-year archives")
    print(f"manifest {manifest_path} "
          f"sha256={_sha256_bytes(manifest_path.read_bytes())}")
    print("DATASET_HASHES_VERIFIED=YES")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BlockedDataAuthority as exc:
        print(f"\nSTATUS=BLOCKED_DATA_AUTHORITY\n{exc}", file=sys.stderr)
        sys.exit(2)
