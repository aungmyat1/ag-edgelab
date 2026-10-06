"""Enforce append-only changes to governance JSON records."""

from __future__ import annotations

from collections import Counter
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROTECTED_PATHS = (
    "config/governance/candidate_ledger.json",
    "config/governance/candidate_contamination_registry.json",
    "config/governance/oos_access_log.json",
    "config/governance/external_artifact_registry.json",
)
OWNER_DECISIONS_PATHSPEC = ":(glob)config/governance/owner_decisions_*.json"


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _comparison_base() -> str:
    head = _git("rev-parse", "HEAD").strip()
    main = _git("rev-parse", "origin/main").strip()
    if head == main:
        return _git("rev-parse", "HEAD^1").strip()
    return _git("merge-base", "HEAD", "origin/main").strip()


def _protected_paths_changed(base: str) -> list[str]:
    paths = _git(
        "diff",
        "--name-only",
        "--no-renames",
        base,
        "HEAD",
        "--",
        *PROTECTED_PATHS,
        OWNER_DECISIONS_PATHSPEC,
    )
    return sorted(path for path in paths.splitlines() if path)


def _version_at(commit: str, path: str):
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def _append_only_problems(base, current, path: str = "$") -> list[str]:
    problems: list[str] = []
    if isinstance(base, dict):
        if not isinstance(current, dict):
            return [f"{path}: object became {type(current).__name__}"]
        for key, value in base.items():
            child_path = f"{path}.{key}"
            if key not in current:
                problems.append(f"{child_path}: REMOVED")
            else:
                problems.extend(
                    _append_only_problems(value, current[key], child_path)
                )
    elif isinstance(base, list):
        if not isinstance(current, list):
            return [f"{path}: array became {type(current).__name__}"]
        if len(current) < len(base):
            problems.append(f"{path}: array SHRANK {len(base)} -> {len(current)}")
        for index, value in enumerate(base[:len(current)]):
            problems.extend(
                _append_only_problems(value, current[index], f"{path}[{index}]")
            )
    elif current != base:
        problems.append(f"{path}: {base!r} -> {current!r}")
    return problems


def _is_trailing_comma_addition(removed_line: str, added_line: str) -> bool:
    return added_line == removed_line + ","


def _raw_diff_problems(base: str, path: str) -> list[str]:
    diff = _git(
        "diff", "--no-ext-diff", "--no-color", "--unified=0", base, "HEAD",
        "--", path,
    )
    removed_lines = [
        line[1:] for line in diff.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    added_lines = [
        line[1:] for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    available_additions = Counter(added_lines)
    problems = []
    for removed_line in removed_lines:
        comma_variants = [
            line for line, count in available_additions.items()
            if count and _is_trailing_comma_addition(removed_line, line)
        ]
        if comma_variants:
            available_additions[comma_variants[0]] -= 1
        else:
            problems.append(f"removed line is not a trailing-comma edit: {removed_line}")
    return problems


@pytest.mark.parametrize("path", PROTECTED_PATHS)
def test_existing_governance_values_are_append_only(path):
    base_commit = _comparison_base()
    base = _version_at(base_commit, path)
    if base is None:
        pytest.skip(f"{path} did not exist at the comparison base")

    current = _version_at("HEAD", path)
    assert current is not None, f"{path} was removed"
    problems = _append_only_problems(base, current)
    assert not problems, "Existing governance JSON paths changed:\n" + "\n".join(problems)


def test_owner_decisions_json_is_in_the_protected_path_set():
    assert OWNER_DECISIONS_PATHSPEC.endswith("owner_decisions_*.json")
    governance_dir = ROOT / "config" / "governance"
    owner_decision_paths = {
        path.relative_to(ROOT).as_posix()
        for path in governance_dir.glob("owner_decisions_*.json")
    }
    assert "config/governance/owner_decisions_r3.json" in owner_decision_paths


def test_governance_json_raw_diff_only_removes_for_trailing_commas():
    base_commit = _comparison_base()
    problems = [
        f"{path}: {problem}"
        for path in _protected_paths_changed(base_commit)
        for problem in _raw_diff_problems(base_commit, path)
    ]
    assert not problems, "Governance JSON raw diff is not append-only:\n" + "\n".join(problems)


def test_raw_diff_accepts_only_a_trailing_comma_addition():
    original_line = '      "note": "unchanged"'
    assert _is_trailing_comma_addition(original_line, original_line + ",")
    assert not _is_trailing_comma_addition(original_line, '      "note": "changed"')
    assert not _is_trailing_comma_addition(original_line, original_line + ",,")