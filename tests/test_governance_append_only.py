"""A1 (R3-CLOSE, RULING_R3_01): append-only enforcement for governance
records.

For each protected file, the version at the merge base of HEAD and
origin/main is compared against the current version. The test FAILS if any
existing JSON path's value changed or was removed. Pure additions are
allowed: new object keys and list growth at the end are the only legal
ways for these files to evolve.

This is a per-change guard: on a branch it verifies that THIS change did
not edit or remove any pre-existing path; on main (where HEAD ==
origin/main) the comparison is empty by construction. Historical identity
against the pinned snapshots (062265c, cc6e4a3) remains enforced by the
consolidation tests.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

PROTECTED_FILES = (
    "config/governance/candidate_ledger.json",
    "config/governance/candidate_contamination_registry.json",
    "config/governance/oos_access_log.json",
    "config/governance/external_artifact_registry.json",
)


def _merge_base() -> str:
    result = subprocess.run(
        ["git", "merge-base", "HEAD", "origin/main"],
        cwd=ROOT, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _version_at(commit: str, path: str):
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        return None  # file did not exist at the merge base
    return json.loads(result.stdout)


def _assert_append_only(base, current, path: str = "$") -> list[str]:
    """Collect every existing JSON path whose value changed or was removed."""
    problems: list[str] = []
    if isinstance(base, dict):
        if not isinstance(current, dict):
            return [f"{path}: object became {type(current).__name__}"]
        for key, value in base.items():
            child = f"{path}.{key}"
            if key not in current:
                problems.append(f"{child}: REMOVED")
            else:
                problems.extend(_assert_append_only(value, current[key], child))
    elif isinstance(base, list):
        if not isinstance(current, list):
            return [f"{path}: array became {type(current).__name__}"]
        if len(current) < len(base):
            problems.append(f"{path}: array SHRANK {len(base)} -> {len(current)}")
        for index, value in enumerate(base[:len(current)]):
            problems.extend(
                _assert_append_only(value, current[index], f"{path}[{index}]"))
    else:
        if current != base:
            problems.append(f"{path}: {base!r} -> {current!r}")
    return problems


@pytest.mark.parametrize("path", PROTECTED_FILES)
def test_protected_governance_file_is_append_only_since_merge_base(path):
    base = _version_at(_merge_base(), path)
    if base is None:
        pytest.skip(f"{path} did not exist at the merge base (new file)")
    current = json.loads((ROOT / path).read_text(encoding="utf-8"))
    problems = _assert_append_only(base, current)
    assert not problems, (
        "RULING_R3_01 violation — existing JSON paths changed or were removed "
        f"in {path}:\n" + "\n".join(problems))
