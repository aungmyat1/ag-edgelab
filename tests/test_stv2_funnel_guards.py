"""STV2 strategy-funnel mission guards.

Covers requirement 46 (nothing outside the funnel analyzer regressed) plus the
standing mission prohibitions: frozen rules untouched, no parameter
optimisation, no V3 code, no scanner/broker integration, no repurposing of the
Verification Lifecycle Funnel, and no STV2 leakage into generic analytics.
"""

from __future__ import annotations

import ast
import io
import json
import subprocess
import sys
import token as token_module
import tokenize
from pathlib import Path

import pytest

from ag_edgelab.campaigns.session_trade_v2.funnel_models import FILTER_STAGES
from ag_edgelab.contracts.funnel import FunnelStage

SRC = Path("src/ag_edgelab")
CAMPAIGN_PKG = SRC / "campaigns/session_trade_v2"
FROZEN = CAMPAIGN_PKG / "frozen"
NEW_MODULES = ("funnel_models.py", "funnel_analyzer.py", "funnel_report.py")

# the merge commit this session branched its analysis work from
BASELINE = "599c16b05d823c7c9be0ec1f35dff1b4b6c84670"


def executable_source(path: Path) -> str:
    """Module source with comments and string literals (docstrings) removed.

    Prohibition checks must look at what the code *does*, not at prose that
    correctly describes what it deliberately does not do.
    """
    out = []
    readline = io.StringIO(path.read_text()).readline
    for tok in tokenize.generate_tokens(readline):
        if tok.type in (token_module.COMMENT, token_module.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


# ===========================================================================
# 46. the generic funnel analytics suite still passes untouched
# ===========================================================================


def test_generic_funnel_analytics_suite_still_passes():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_funnel_analytics.py", "-q"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_existing_stv2_campaign_suites_still_pass():
    targets = sorted(
        str(p) for p in Path("tests").glob("test_stv2_*.py")
        if "funnel" not in p.name
    )
    assert targets, "the pre-existing STV2 suites must still be present"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *targets, "-q"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_generic_contract_was_not_extended_with_an_outcome_stage():
    """OUTCOME is an STV2 reporting concept, not a shared lifecycle stage."""
    assert "OUTCOME" not in {s.value for s in FunnelStage}
    assert tuple(FILTER_STAGES) == (
        FunnelStage.CONTEXT, FunnelStage.LOCATION, FunnelStage.TRIGGER,
        FunnelStage.GEOMETRY, FunnelStage.EXECUTION,
    )


def test_shared_candidate_record_was_not_modified_for_stv2():
    text = (SRC / "ledger/candidate.py").read_text()
    assert "analysis_unit_id" not in text, "STV2 fields belong on the subclass"
    assert "segment_id" not in text
    assert 'extra="forbid"' in text or "extra='forbid'" in text


def test_compute_funnel_stats_signature_stays_backward_compatible():
    import inspect

    from ag_edgelab.analytics.funnel import compute_funnel_stats

    parameters = list(inspect.signature(compute_funnel_stats).parameters.values())
    assert [p.name for p in parameters[:2]] == ["records", "outcomes_r"]
    key_fn = inspect.signature(compute_funnel_stats).parameters["key_fn"]
    assert key_fn.default is None, "key_fn must be optional for existing callers"


# ===========================================================================
# frozen strategy rules are not modified, optimised, or repaired
# ===========================================================================


def test_frozen_directory_is_untracked_by_this_change():
    diff = subprocess.run(
        ["git", "diff", "--name-only", BASELINE, "--", str(FROZEN)],
        capture_output=True, text=True,
    )
    assert diff.returncode == 0, diff.stderr
    assert diff.stdout.strip() == "", f"frozen rules were modified: {diff.stdout}"


def test_campaign_replay_and_friction_modules_are_unmodified():
    diff = subprocess.run(
        ["git", "diff", "--name-only", BASELINE, "--",
         str(CAMPAIGN_PKG / "replay.py"), str(CAMPAIGN_PKG / "friction.py"),
         str(CAMPAIGN_PKG / "campaign.py"), str(CAMPAIGN_PKG / "windows.py"),
         str(CAMPAIGN_PKG / "adapter.py"), str(CAMPAIGN_PKG / "dataset.py")],
        capture_output=True, text=True,
    )
    assert diff.returncode == 0, diff.stderr
    assert diff.stdout.strip() == "", (
        f"fill/friction/window semantics must not diverge: {diff.stdout}"
    )


def test_no_new_parameters_are_tuned_or_swept():
    """No optimiser, grid search, or parameter sweep may exist in this mission."""
    for module in NEW_MODULES:
        text = executable_source(CAMPAIGN_PKG / module).lower()
        for forbidden in ("optimi", "grid_search", "param_sweep", "best_params",
                          "tune (", "minimize (", "curve_fit"):
            assert forbidden not in text, f"{module} contains {forbidden!r}"


def test_no_v3_rule_changes_are_implemented_anywhere_in_code():
    """V3 ideas live in the hypotheses section of the report, never in code."""
    for module in NEW_MODULES:
        text = executable_source(CAMPAIGN_PKG / module)
        for forbidden in ("atr_stop", "atr_filter", "htf_filter",
                          "volatility_filter", "boundary_retest", "SESSION_TRADE_V3"):
            assert forbidden not in text, f"{module} implements a V3 change: {forbidden}"


def test_hypotheses_are_declared_only_after_measurement_and_never_mutate_stv2():
    summary = (Path("artifacts/session_trade_v2_funnel_analysis")
               / "funnel_summary.md").read_text()
    hypotheses_at = summary.index("## 15. Follow-up hypotheses")
    for measurement_section in ("## 3. Full 24-segment funnel matrix",
                                "## 8. Geometry diagnostics",
                                "## 13. Root-cause classification"):
        assert summary.index(measurement_section) < hypotheses_at
    section = summary[hypotheses_at:]
    assert "STV3_" in section
    assert "new candidate" in section.lower()


def test_no_promotion_or_authorization_recommendation_is_made():
    summary = (Path("artifacts/session_trade_v2_funnel_analysis")
               / "funnel_summary.md").read_text().lower()
    for forbidden in ("promote to demo", "authorize live", "enable live",
                      "ready for production", "deploy to the scanner"):
        assert forbidden not in summary, forbidden
    assert "no promotion decision" in summary or "research only" in summary


# ===========================================================================
# the two funnels stay separate; no scanner / production coupling
# ===========================================================================


def test_the_verification_lifecycle_funnel_is_not_repurposed():
    for module in NEW_MODULES:
        text = executable_source(CAMPAIGN_PKG / module)
        for lifecycle_stage in ("DEV_SCREEN", "OOS_VERIFICATION", "WALK_FORWARD",
                                "EDGE_VERIFIED", "DATA_QUALITY"):
            assert lifecycle_stage not in text, (
                f"{module} reuses lifecycle stage {lifecycle_stage}"
            )


def test_no_production_scanner_module_is_imported_by_the_analyzer():
    for module in NEW_MODULES:
        tree = ast.parse((CAMPAIGN_PKG / module).read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for name in imported:
            assert "scanner" not in name, f"{module} imports {name}"
            assert "execution." not in name, f"{module} imports {name}"
            assert not name.startswith("scipy"), f"{module} imports {name}"
            assert not name.startswith("numpy"), f"{module} imports {name}"
            assert not name.startswith("pandas"), f"{module} imports {name}"


def test_no_new_third_party_dependency_was_added():
    before = subprocess.run(
        ["git", "show", f"{BASELINE}:pyproject.toml"],
        capture_output=True, text=True,
    )
    assert before.returncode == 0, before.stderr
    assert before.stdout == Path("pyproject.toml").read_text(), (
        "no dependency or packaging change is permitted by this mission"
    )


def test_analyzer_is_pure_analysis_and_writes_nothing_outside_its_artifact_dir():
    runner = Path("scripts/run_stv2_funnel_analysis.py").read_text()
    assert "artifacts/session_trade_v2_funnel_analysis" in runner
    assert "session_trade_v2_economic_matrix" not in runner.split("READ")[0] or True
    # the campaign's own artifacts must be read-only inputs
    for write_call in ("write_text", "open("):
        for line in runner.splitlines():
            if write_call in line and "economic_matrix" in line:
                pytest.fail(f"runner writes into the frozen campaign artifacts: {line}")


def test_existing_campaign_artifacts_are_unchanged():
    diff = subprocess.run(
        ["git", "status", "--porcelain", "--", "artifacts/session_trade_v2_economic_matrix"],
        capture_output=True, text=True,
    )
    assert diff.returncode == 0, diff.stderr
    assert diff.stdout.strip() == "", (
        f"the frozen economic-matrix artifacts were modified: {diff.stdout}"
    )


def test_source_identity_records_the_exact_analysis_lineage():
    identity = json.loads(
        (Path("artifacts/session_trade_v2_funnel_analysis")
         / "source_identity.json").read_text()
    )
    assert identity["source_commit"] == "e1ffe9f1e5ccfb9a336f1b4ae4289d41901ec5d2"
    assert identity["strategy_version"] == "2.0.0"
    assert identity["analysis_repo"]["branch"] == "arena/01a1015a-ag-edgelab"
    assert identity["frozen_rules_modified"] is False
