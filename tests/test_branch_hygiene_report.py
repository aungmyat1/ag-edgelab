from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

SPEC = importlib.util.spec_from_file_location(
    "branch_hygiene_report",
    Path(__file__).resolve().parents[1] / "scripts" / "branch_hygiene_report.py",
)
assert SPEC and SPEC.loader
REPORT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = REPORT
SPEC.loader.exec_module(REPORT)


def test_remote_branch_names_excludes_local_and_head_refs():
    assert REPORT.remote_branch_names([
        "main",
        "origin/HEAD",
        "origin/main",
        "origin/feat/example",
    ]) == ["feat/example", "main"]


def test_classification_covers_requested_categories():
    assert REPORT.classify_branch("origin-placeholder", 0) == "MERGED"
    assert REPORT.classify_branch("feat/fx-edge-candidate", 2) == "OBSOLETE"
    assert REPORT.classify_branch("feat/crypto-btc-spot-candidate", 1) == "SALVAGE"
    assert REPORT.classify_branch("feat/r1-nautilus-adapter", 1) == "PARKED"
    assert REPORT.classify_branch("feat/new-work", 1) == "ACTIVE"
    assert REPORT.classify_branch("main", 0) == "ACTIVE"


def test_rendered_report_includes_count_classification_and_open_pr():
    report = REPORT.render_report([
        REPORT.BranchRecord(
            name="feat/example",
            classification="ACTIVE",
            ahead=3,
            open_prs=((42, "https://github.com/aungmyat1/ag-edgelab/pull/42"),),
        )
    ])

    assert "Remote branches: **1**" in report
    assert "| `feat/example` | ACTIVE | 3 | [#42]" in report