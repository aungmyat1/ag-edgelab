from __future__ import annotations

"""Focused tests: the final-report renderer.

Locks the REQUIRED report fields, the 24-row matrix rendering, the lifecycle
gate logic (EDGE_VERIFIED structurally unreachable from DEV alone) and the
machine-readable JSON payload.
"""

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))  # reuse the synthetic builder
from test_stv2_campaign_matrix import build_synthetic_bars  # noqa: E402

from ag_edgelab.campaigns.session_trade_v2.campaign import run_campaign  # noqa: E402
from ag_edgelab.campaigns.session_trade_v2.report import (  # noqa: E402
    ReportInputs,
    build_report_payload,
    lifecycle,
    render_markdown,
    write_report,
)

REQUIRED_FIELDS = (
    "FINAL_STATUS",
    "REPO",
    "BRANCH",
    "HEAD",
    "SOURCE_STRATEGY_SHA",
    "CANDIDATE_ID",
    "DATASETS",
    "DATASET_HASHES",
    "DEV_PARTITION",
    "OOS_PARTITION",
    "HOLDOUT_TOUCHED",
    "BRANCH_A_VERDICT",
    "BRANCH_B_VERDICT",
    "BRANCH_C_VERDICT",
    "CELLS_TO_FREEZE_FOR_OOS",
    "REJECTED",
    "INSUFFICIENT_SAMPLE",
    "BLOCKED",
    "AGGREGATE_NET_R",
    "AGGREGATE_EXPECTANCY",
    "AGGREGATE_PF",
    "MAX_DRAWDOWN_R",
    "TOTAL_FRICTION_R",
    "FILES_CHANGED",
    "TESTS_RUN",
    "TEST_RESULTS",
    "ARTIFACT_PATHS",
    "COMMIT_SHA",
    "PR_NUMBER",
    "NEXT_RECOMMENDED_ACTION",
    "FOLLOW_UP_HYPOTHESES",
)


def _inputs(dev, oos=None):
    return ReportInputs(
        dev_result=dev,
        oos_result=oos,
        repo={"repo": "aungmyat1/ag-edgelab", "branch": "b", "head": "h",
              "worktree_status": "clean"},
        tests={"tests_run": "pytest -q", "test_results": "212 passed"},
        files_changed=("src/ag_edgelab/campaigns/session_trade_v2/report.py",),
        artifact_paths=("artifacts/session_trade_v2_economic_matrix/",),
        commit_sha="abc123",
        pr_number=33,
    )


@pytest.fixture(scope="module")
def dev_result():
    bars = build_synthetic_bars([(date(2017, 3, 15), {"EURUSD": "A_SWEEP"}, False)])
    return run_campaign("DEVELOPMENT", bars)


def test_markdown_contains_every_required_field(dev_result):
    md = render_markdown(_inputs(dev_result))
    for field in REQUIRED_FIELDS:
        assert field in md, field
    # the required 24-row table with the exact column set
    assert "| Branch | Symbol | Session | N | Net R | Net Exp | Net PF | Win % | Max DD R | Friction R | Status |" in md
    body_rows = [l for l in md.splitlines()
                 if l.startswith(("| A_SWEEP_REENTRY |", "| B_RANGE_REJECTION |",
                                  "| C_TREND_EXPANSION |"))]
    assert len(body_rows) >= 24
    assert "HOLDOUT_TOUCHED: false" in md


def test_json_payload_has_every_required_key(dev_result):
    payload = build_report_payload(_inputs(dev_result))
    for field in REQUIRED_FIELDS:
        assert field in payload, field
    assert payload["HOLDOUT_TOUCHED"] is False
    assert payload["CANDIDATE_ID"] == dev_result.identity["candidate_id"]
    assert len(payload["DEV_MATRIX"]) == 24


def test_edge_verified_unreachable_from_dev_alone(dev_result):
    lc = lifecycle(dev_result, None, {})
    assert lc["reached"] != "EDGE_VERIFIED"
    assert lc["gates"]["EDGE_VERIFIED"] is False
    # even a passing DEV screen cannot jump the OOS/walk-forward/regime gates
    passing = {c.branch: c for c in dev_result.cells}  # any shape: gate is structural
    lc2 = lifecycle(dev_result, dev_result, {})  # OOS object supplied, no supp
    assert lc2["gates"]["OOS_PASS"] is False or lc2["gates"]["WALK_FORWARD_PASS"] is False
    assert lc2["gates"]["EDGE_VERIFIED"] is False


def test_no_survivors_is_complete_negative(dev_result):
    md = render_markdown(_inputs(dev_result))
    assert "FINAL_STATUS: COMPLETE" in md
    assert "no cell survives the DEV screen" in md


def test_write_report_produces_md_and_json(dev_result, tmp_path):
    md_path, json_path = write_report(_inputs(dev_result), tmp_path)
    assert md_path.exists() and json_path.exists()
    payload = json.loads(json_path.read_text())
    assert payload["FINAL_STATUS"] in ("COMPLETE", "BLOCKED", "PARTIAL")
    assert md_path.read_text().startswith("# SESSION_TRADE_V2")
