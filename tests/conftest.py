"""Test-session bootstrap: self-provision the pinned synthetic BTCUSDT fixture.

Why this exists
---------------
The canonical fixture CSVs under ``data/artifacts/synthetic_btcusdt/`` are
intentionally NOT version-controlled (repo-wide ``*.csv`` ignore): they are
byte-deterministic products of ``scripts/make_synthetic_btcusdt_fixture.py``
pinned by committed manifests. A fresh checkout — notably CI, which runs a
bare ``pytest`` — therefore arrives WITHOUT them, and every test touching the
fixture dies with FileNotFoundError (observed on PR #9 active CI, py3.12+3.13
``Test`` steps, exit code 1).

Guarantees (strengthening, not weakening)
-----------------------------------------
1. Artifacts missing OR hash-drifted -> regenerate with the PINNED defaults
   (the script's frozen ``--seed/--start/--days``), never with ad-hoc values.
2. After any generation, artifact bytes MUST match the committed manifest
   sha256 exactly, for both CSVs. A mismatch halts the whole session with a
   clear message: it means either the pinned generator drifted or the
   manifests do not describe what is on disk. Tests never run against
   untrusted fixture bytes.
3. No network, no strategy code, no fixture values change here.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_OUT = _ROOT / "data" / "artifacts" / "synthetic_btcusdt"
_GENERATOR = _ROOT / "scripts" / "make_synthetic_btcusdt_fixture.py"
_ARTIFACTS = ("BTCUSDT_M5_SYNTHETIC.csv", "BTCUSDT_FUNDING_SYNTHETIC.csv")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_sha(path: Path) -> str:
    return json.loads(path.with_suffix(path.suffix + ".manifest.json").read_text())["sha256"]


def _hashes_ok() -> bool:
    try:
        return all(_sha256(_OUT / name) == _manifest_sha(_OUT / name) for name in _ARTIFACTS)
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return False


def pytest_sessionstart(session: pytest.Session) -> None:  # noqa: ARG001
    if not _hashes_ok():
        # Self-provision (fresh checkout) or self-heal (local drift) using the
        # committed pinned generator. --with-manifest also rewrites manifests,
        # which must then be byte-identical to the committed ones by design.
        proc = subprocess.run(
            [sys.executable, str(_GENERATOR), "--with-manifest"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            pytest.exit(
                "synthetic fixture generator failed; cannot trust fixture bytes."
                f"\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}",
                returncode=3,
            )
    if not _hashes_ok():
        got = {n: _sha256(_OUT / n) if (_OUT / n).exists() else "<missing>" for n in _ARTIFACTS}
        want = {n: _manifest_sha(_OUT / n) for n in _ARTIFACTS}
        pytest.exit(
            "synthetic fixture bytes do NOT match their committed manifests;"
            " the pinned generator drifted or manifests are stale. Fix the"
            f" generator/manifest, not the data.\n  got: {got}\n  want: {want}",
            returncode=3,
        )
