#!/usr/bin/env python3
"""Materialize only the small DEVELOPMENT FX fixture for Funnel Optimizer V1.

This script intentionally requests EURUSD and GBPUSD for 2015-2017 only.  It
never asks the existing broad multi-year tool to fetch its complete corpus.
The 2017 mirror archive is byte-checked against the repository-pinned HistData
archive before 2015/2016 mirror files are admitted to this *candidate* fixture.
A raw archive is hashed as a byte object; the script does not decode or replay
Sep-Nov OOS or December holdout observations.

On any network/authority/deadline failure it writes a DATA_BLOCKED receipt and
returns non-zero.  A synthetic optimizer proof may then run, but it must not
call itself real FX evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from ag_edgelab.optimization.fx_fixture import (FixtureDataReceipt, FixtureDataStatus,
                                                verify_fixture_file)

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DEST = REPO / "data" / "external" / "funnel_optimizer_fx_fixture"
SYMBOLS = ("EURUSD", "GBPUSD")
YEARS = (2015, 2016, 2017)
PINNED_2017_SHA256 = {
    "EURUSD": "0dcd66dc67d7af4716404a5315d376ee1e7eaebe292afbda3c1003d2dfa16f57",
    "GBPUSD": "e5ba3800e37fae0e326dbaa234952ca04e8f378c08b036530a2811206110c10b",
}
PINNED_SOURCE = "github.com/parrondo/deeptrading (repository-pinned HistData 2017 archive)"
MIRROR_SOURCE = "github.com/riknv/fx-m1-data (HistData Generic ASCII mirror)"


class FixtureBlocked(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(repo_path: str, target: Path, *, deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise FixtureBlocked("DATA_ACQUISITION_TIMEBOX_EXCEEDED")
    proc = subprocess.run(
        ["gh", "api", f"repos/{repo_path}", "-H", "Accept: application/vnd.github.raw"],
        capture_output=True,
        timeout=max(1.0, remaining),
        check=False,
    )
    if proc.returncode != 0 or len(proc.stdout) < 100_000:
        raise FixtureBlocked(
            f"DOWNLOAD_UNAVAILABLE:{repo_path}:rc={proc.returncode}:bytes={len(proc.stdout)}")
    target.write_bytes(proc.stdout)


def _assert_zip_container(path: Path) -> None:
    # Do not extract/decode an archive at acquisition time.  Container-format
    # validation reads central-directory metadata only, not bar observations.
    if not zipfile.is_zipfile(path):
        raise FixtureBlocked(f"ARCHIVE_INVALID:{path.name}")


def _write_receipt(dest: Path, receipt: FixtureDataReceipt, *, verification: dict) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    payload = receipt.as_dict() | {
        "fixture_population": {"symbols": list(SYMBOLS), "years": list(YEARS)},
        "data_role": "DEVELOPMENT_ONLY_CANDIDATE_FIXTURE",
        "oos_or_holdout_decoded": False,
        "verification": verification,
    }
    (dest / "receipt.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def materialize(dest: Path, *, timebox_minutes: float) -> FixtureDataReceipt:
    if timebox_minutes <= 0 or timebox_minutes > 60:
        raise ValueError("timebox-minutes must be in (0, 60]")
    started = time.monotonic()
    deadline = started + timebox_minutes * 60.0
    dest.mkdir(parents=True, exist_ok=True)
    verification: dict[str, dict[str, str]] = {}
    try:
        for symbol in SYMBOLS:
            pinned = dest / f"HISTDATA_COM_ASCII_{symbol}_M1_2017.zip"
            if not pinned.exists():
                _download(
                    f"parrondo/deeptrading/contents/data/raw/{symbol.lower()}/"
                    f"HISTDATA_COM_ASCII_{symbol}_M1_2017.zip",
                    pinned,
                    deadline=deadline,
                )
            got = _sha256(pinned)
            if got != PINNED_2017_SHA256[symbol]:
                raise FixtureBlocked(f"PINNED_2017_SHA256_MISMATCH:{symbol}:{got}")
            _assert_zip_container(pinned)
            verification[symbol] = {"pinned_2017_zip_sha256": got}

        files = []
        for symbol in SYMBOLS:
            for year in YEARS:
                target = dest / f"DAT_ASCII_{symbol}_M1_{year}.zip"
                if not target.exists():
                    _download(
                        f"riknv/fx-m1-data/contents/{symbol.lower()}/"
                        f"DAT_ASCII_{symbol}_M1_{year}.zip",
                        target,
                        deadline=deadline,
                    )
                target_sha = _sha256(target)
                _assert_zip_container(target)
                if year == 2017:
                    if target_sha != PINNED_2017_SHA256[symbol]:
                        raise FixtureBlocked(
                            f"CROSS_SOURCE_2017_ARCHIVE_MISMATCH:{symbol}:{target_sha}:")
                    verification[symbol]["cross_source_2017_archive_sha256"] = target_sha
                files.append(verify_fixture_file(
                    target, symbol=symbol, year=year,
                    source=f"{MIRROR_SOURCE}; 2017 archive cross-source proof={year == 2017}",
                ))
        receipt = FixtureDataReceipt.verified(
            status=FixtureDataStatus.ACQUIRED_VERIFIED,
            source=f"{PINNED_SOURCE}; {MIRROR_SOURCE}",
            acquisition_seconds=time.monotonic() - started,
            files=files,
        )
    except (FixtureBlocked, subprocess.TimeoutExpired, OSError) as exc:
        receipt = FixtureDataReceipt.blocked(
            source=f"{PINNED_SOURCE}; {MIRROR_SOURCE}",
            acquisition_seconds=time.monotonic() - started,
            reason_code=str(exc),
        )
    _write_receipt(dest, receipt, verification=verification)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--timebox-minutes", type=float, default=60.0)
    args = parser.parse_args(argv)
    receipt = materialize(args.dest, timebox_minutes=args.timebox_minutes)
    print(json.dumps(receipt.as_dict(), sort_keys=True))
    return 0 if receipt.status is not FixtureDataStatus.DATA_BLOCKED else 2


if __name__ == "__main__":
    raise SystemExit(main())
