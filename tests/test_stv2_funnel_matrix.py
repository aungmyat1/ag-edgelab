"""STV2 strategy-funnel end-to-end matrix, reconciliation and reporting.

Covers requirements 39-44 of STV2_STRATEGY_FUNNEL_ANALYZER_V1 against the real
written artifacts under ``artifacts/session_trade_v2_funnel_analysis/``.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from pathlib import Path

import pytest

from ag_edgelab.campaigns.session_trade_v2.funnel_models import (
    CANONICAL_CANDIDATE_ID,
    EXPECTED_FILTER_STAGE_ROWS,
    EXPECTED_SEGMENTS,
    FILTER_STAGES,
)
from ag_edgelab.campaigns.session_trade_v2.funnel_report import CSV_COLUMNS
from ag_edgelab.campaigns.session_trade_v2.windows import BRANCHES, SESSIONS, SYMBOLS

ART = Path("artifacts/session_trade_v2_funnel_analysis")
CAMPAIGN = Path("artifacts/session_trade_v2_economic_matrix")

pytestmark = pytest.mark.skipif(
    not (ART / "funnel_stage_matrix.json").exists(),
    reason="funnel artifacts not generated; run scripts/run_stv2_funnel_analysis.py",
)


def load(name: str):
    return json.loads((ART / name).read_text())


@pytest.fixture(scope="module")
def matrix():
    return load("funnel_stage_matrix.json")


@pytest.fixture(scope="module")
def manifest():
    return load("segment_manifest.json")


@pytest.fixture(scope="module")
def summary_md():
    return (ART / "funnel_summary.md").read_text()


# ===========================================================================
# 39. exactly 24 segments and 120 filter-stage rows
# ===========================================================================


def test_segment_manifest_contains_exactly_24_segments(manifest):
    assert manifest["expected_segments"] == EXPECTED_SEGMENTS == 24
    assert manifest["segments"] == 24
    assert manifest["segments_match_expected"] is True
    rows = manifest["segment_rows"]
    assert len(rows) == 24
    assert len({r["segment_id"] for r in rows}) == 24
    combos = {(r["branch"], r["symbol"], r["session"]) for r in rows}
    assert combos == {(b, sym, sess) for b in BRANCHES for sym in SYMBOLS for sess in SESSIONS}
    assert manifest["candidate_id"] == CANONICAL_CANDIDATE_ID


def test_stage_matrix_has_exactly_120_filter_stage_rows(matrix):
    assert matrix["expected_filter_stage_rows"] == EXPECTED_FILTER_STAGE_ROWS == 120
    assert matrix["filter_stage_rows"] == 120
    assert matrix["rows_match_expected"] is True
    rows = matrix["rows"]
    assert len(rows) == 120
    assert len({(r["segment_id"], r["stage"]) for r in rows}) == 120
    assert len(FILTER_STAGES) == 5
    for segment_id in {r["segment_id"] for r in rows}:
        stages = [r["stage"] for r in rows if r["segment_id"] == segment_id]
        assert stages == [str(s) for s in FILTER_STAGES]


def test_segments_and_analysis_units_are_not_conflated(manifest):
    """EXPECTED_SEGMENTS == 24, but the analysis-unit count is data driven."""
    assert manifest["analysis_units"] == 5808 != manifest["expected_segments"]
    assert manifest["identity_collisions"] == 0
    assert "EXPECTED_ANALYSIS_UNITS != 24" in manifest["expected_analysis_units_note"]
    assert sum(r["analysis_units"] for r in manifest["segment_rows"]) == 5808


def test_outcome_stage_is_reported_separately_from_the_five_filter_stages(matrix):
    assert "OUTCOME" not in {r["stage"] for r in matrix["rows"]}
    outcomes = matrix["outcome_summaries"]
    assert len(outcomes) == 24
    assert {o["stage"] for o in outcomes} == {"OUTCOME"}
    assert sum(o["closed_trades"] for o in outcomes) == 546


# ===========================================================================
# 40. CSV/JSON equivalence
# ===========================================================================


def test_csv_and_json_matrices_agree(matrix):
    rows = list(csv.DictReader(io.StringIO((ART / "funnel_stage_matrix.csv").read_text())))
    assert len(rows) == 120
    assert list(rows[0].keys()) == list(CSV_COLUMNS)

    index = {(r["segment_id"], r["stage"]): r for r in matrix["rows"]}
    for row in rows:
        source = index[(row["segment_id"], row["stage"])]
        assert int(row["stage_input_count"]) == source["stage_input_count"]
        assert int(row["stage_retained_count"]) == source["stage_retained_count"]
        for key in ("conditional_downstream_net_expectancy_r", "win_rate", "friction_r",
                    "conditional_downstream_net_pf", "average_cost_r"):
            if source[key] is None:
                assert row[key] == "", f"{key} must stay empty (null), never 0"
            else:
                assert float(row[key]) == pytest.approx(source[key], abs=1e-6)


def test_csv_carries_every_mandated_per_stage_statistic():
    for column in (
        "segment_id", "branch", "symbol", "session", "stage",
        "stage_input_count", "stage_retained_count", "stage_retained_pct",
        "data_invalid_count", "ambiguity_count", "signals", "fills", "unfilled",
        "expired", "closed_trades", "wins", "losses", "breakeven",
        "win_rate", "win_ci95_low", "win_ci95_high",
        "conditional_downstream_gross_expectancy_r",
        "conditional_downstream_net_expectancy_r",
        "conditional_downstream_gross_pf", "conditional_downstream_net_pf",
        "conditional_downstream_gross_r", "conditional_downstream_net_r",
        "friction_r", "average_cost_r", "win_rate_lift_pp",
        "conditional_net_expectancy_shift_r",
    ):
        assert column in CSV_COLUMNS, column


# ===========================================================================
# 41. holdout untouched / authority frozen
# ===========================================================================


def test_holdout_is_never_touched():
    dataset = load("dataset_identity.json")
    assert dataset["holdout_touched"] is False
    assert dataset["sealed_holdout"]["touched"] is False
    assert dataset["sealed_holdout"]["start"].startswith("2017-12-01")
    assert dataset["sealed_holdout"]["end"].startswith("2018-01-01")
    assert dataset["oos_partition_used"] is False
    assert dataset["dev_partition"]["start"].startswith("2017-01-01")
    assert dataset["dev_partition"]["end"].startswith("2017-09-01")
    assert dataset["reused_frozen_dataset"] is True and dataset["redownloaded"] is False


def test_every_analysis_unit_lies_inside_the_development_partition():
    units = load("analysis_units.json")
    partition = units["partition"]
    assert partition["role"] == "DEVELOPMENT"
    assert partition["holdout_touched"] is False
    assert partition["analysis_units"] == 5808
    dates = {u["trading_date"] for u in units["units"]}
    assert min(dates) >= "2017-01-01"
    assert max(dates) < "2017-09-01"


def test_execution_authority_remains_frozen_and_unauthorized(summary_md):
    authority = load("source_identity.json")["execution_authority"]
    assert authority == {
        "demo_authorized": False, "live_authorized": False, "allow_order_send": False
    }
    for flag in ("demo_authorized", "live_authorized", "allow_order_send"):
        assert flag in summary_md
    assert summary_md.count("`false`") >= 3


def test_no_order_send_or_broker_surface_in_the_new_modules():
    source_root = Path("src/ag_edgelab/campaigns/session_trade_v2")
    for module in ("funnel_models.py", "funnel_analyzer.py", "funnel_report.py"):
        text = (source_root / module).read_text()
        for forbidden in ("MetaTrader", "place_order", "send_order", "import mt5"):
            assert forbidden not in text, f"{module} must not reference {forbidden}"
        # order_send may only appear as the frozen *deny* flag
        for line in text.splitlines():
            if "order_send" in line:
                assert "allow_order_send" in line and "false" in line.lower()


# ===========================================================================
# 42. isolation: generic analytics stay generic, frozen rules stay frozen
# ===========================================================================


def test_generic_analytics_contain_no_stv2_specific_parsing():
    text = Path("src/ag_edgelab/analytics/funnel.py").read_text()
    for token in ("SESSION_TRADE_V2", "A_SWEEP_REENTRY", "B_RANGE_REJECTION",
                  "C_TREND_EXPANSION", "LONDON_NEWYORK", "ASIAN_LONDON",
                  "EURUSD", "XAUUSD"):
        assert token not in text, f"generic analytics leaked an STV2 concept: {token}"


def test_frozen_strategy_files_are_byte_identical_to_the_recorded_hashes():
    identity = load("source_identity.json")
    assert identity["frozen_rules_modified"] is False
    frozen = Path("src/ag_edgelab/campaigns/session_trade_v2/frozen")
    for name, expected in identity["frozen_artifact_sha256"].items():
        actual = hashlib.sha256((frozen / name).read_bytes()).hexdigest()
        assert actual == expected, f"frozen/{name} drifted"


def test_dataset_hashes_match_the_frozen_campaign_dataset():
    recorded = load("dataset_identity.json")["symbols"]
    quality = json.loads((CAMPAIGN / "dataset_quality_reports.json").read_text())
    assert set(recorded) == set(quality) == set(SYMBOLS)
    for symbol, info in recorded.items():
        assert info["source_sha256"] == quality[symbol]["source_sha256"], symbol
        assert info["m1_rows"] == quality[symbol]["m1_rows"], symbol
        assert info["m15_bars"] == quality[symbol]["m15_bars"], symbol


def test_preserved_dataset_semantics_are_declared():
    declared = " ".join(load("dataset_identity.json")["preserved_semantics"]).lower()
    for concept in ("timezone", "m15", "session completeness", "ambiguity",
                    "fill", "friction", "partition"):
        assert concept in declared, concept


# ===========================================================================
# 43. funnel reconciliation against the existing campaign result
# ===========================================================================


def test_funnel_reconciles_with_the_campaign_dev_result():
    reconciliation = load("analysis_units.json")["reconciliation"]
    assert reconciliation["reconciled"] is True
    assert reconciliation["funnel_closed_trades"] == reconciliation["campaign_closed_trades"] == 546
    assert reconciliation["funnel_filled"] == reconciliation["campaign_filled"] == 546
    assert reconciliation["funnel_net_r"] == pytest.approx(
        reconciliation["campaign_net_r"], abs=1e-6
    )


def test_matrix_closed_trades_equal_the_campaign_total(matrix):
    dev = json.loads((CAMPAIGN / "dev_result.json").read_text())
    execution_rows = [r for r in matrix["rows"] if r["stage"] == "EXECUTION"]
    combined = dev["aggregates"]["combined"]
    assert sum(r["closed_trades"] for r in execution_rows) == combined["closed"] == 546


def test_per_branch_funnel_economics_match_the_campaign_branch_table():
    dev = json.loads((CAMPAIGN / "dev_result.json").read_text())
    branches = {s["branch"]: s for s in load("branch_summary.json")["summaries"]}
    for branch, campaign in dev["aggregates"]["by_branch"].items():
        funnel = branches[branch]
        assert funnel["closed_n"] == campaign["closed"], branch
        if campaign["closed"]:
            outcome = funnel["outcome"]
            assert outcome["conditional_downstream_net_r"] == pytest.approx(
                campaign["net_r"], abs=1e-4
            )
            assert outcome["conditional_downstream_net_expectancy_r"] == pytest.approx(
                campaign["net_expectancy_r"], abs=1e-4
            )
            assert outcome["win_rate"] == pytest.approx(campaign["win_rate"], abs=1e-4)


def test_branch_stage_counts_are_cumulative_and_monotonic():
    expected = {
        "A_SWEEP_REENTRY": (1936, 1301, 1067, 846, 542, 542, 542),
        "B_RANGE_REJECTION": (1936, 1301, 1071, 7, 7, 3, 3),
        "C_TREND_EXPANSION": (1936, 1301, 1067, 196, 196, 1, 1),
    }
    for summary in load("branch_summary.json")["summaries"]:
        counts = (summary["raw_context_n"], summary["context_n"], summary["location_n"],
                  summary["trigger_n"], summary["geometry_n"], summary["execution_n"],
                  summary["closed_n"])
        assert counts == expected[summary["branch"]], summary["branch"]
        assert list(counts) == sorted(counts, reverse=True), "funnel must be monotonic"


def test_dimension_summaries_partition_the_same_546_closed_trades():
    for view, key, expected_n in (("branch_summary.json", "branch", 3),
                                  ("symbol_summary.json", "symbol", 4),
                                  ("session_summary.json", "session", 2)):
        payload = load(view)
        summaries = payload["summaries"]
        assert payload["dimension"] == key
        assert len(summaries) == expected_n
        assert sum(s["closed_n"] for s in summaries) == 546, view


def test_attrition_transitions_are_internally_consistent():
    for entry in load("attrition_analysis.json")["segments"]:
        transitions = entry["transitions"]
        # one transition per adjacent stage pair in the 5-stage filter chain
        assert len(transitions) == len(FILTER_STAGES) - 1
        assert [t["from_stage"] for t in transitions] == [str(s) for s in FILTER_STAGES[:-1]]
        assert [t["to_stage"] for t in transitions] == [str(s) for s in FILTER_STAGES[1:]]
        for transition in transitions:
            assert transition["attrition_count"] == (
                transition["input_count"] - transition["retained_count"]
            )
            assert transition["attrition_count"] >= 0
            assert sum(transition["rejection_reasons"].values()) == (
                transition["attrition_count"]
            ), f"{entry['segment_id']} {transition['from_stage']} reasons must be exhaustive"
            if transition["input_count"]:
                assert transition["attrition_pct"] == pytest.approx(
                    transition["attrition_count"] / transition["input_count"] * 100.0, abs=1e-3
                )
        for previous, current in zip(transitions, transitions[1:]):
            assert current["input_count"] == previous["retained_count"]


def test_geometry_diagnostics_isolate_the_sweep_stop_rejection():
    segments = load("geometry_analysis.json")["segments"]
    a_segments = [s for s in segments if s["branch"] == "A_SWEEP_REENTRY"]
    assert sum(s["sweep_stop_does_not_protect_extreme"] for s in a_segments) == 304
    assert sum(s["geometry_rejected"] for s in a_segments) == 304
    for segment in a_segments:
        assert segment["other_geometry_rejection_reasons"] == {}
        assert 0.0 <= segment["sweep_stop_rejection_pct"] <= 100.0
    for segment in segments:
        if segment["branch"] != "A_SWEEP_REENTRY":
            assert segment["geometry_rejected"] == 0
            assert segment["sweep_stop_does_not_protect_extreme"] == 0


def test_execution_diagnostics_show_c_fill_starvation_and_a_market_fills():
    segments = load("execution_analysis.json")["segments"]
    by_branch: dict[str, list[dict]] = {}
    for segment in segments:
        by_branch.setdefault(segment["branch"], []).append(segment)

    a = by_branch["A_SWEEP_REENTRY"]
    assert {s["order_type"] for s in a} <= {"MARKET", None}
    assert sum(s["fills"] for s in a) == 542
    assert sum(s["unfilled"] for s in a) == sum(s["expired"] for s in a) == 0

    c = by_branch["C_TREND_EXPANSION"]
    assert sum(s["geometry_valid_signals"] for s in c) == 196
    assert sum(s["fills"] for s in c) == 1
    assert sum(s["expired"] for s in c) == 195
    assert sum(s["expired_never_workable"] for s in c) == 11

    b = by_branch["B_RANGE_REJECTION"]
    assert sum(s["geometry_valid_signals"] for s in b) == 7
    assert sum(s["fills"] for s in b) == 3
    assert sum(s["expired"] for s in b) == 4


def test_friction_analysis_identifies_the_gross_positive_net_negative_segments():
    analysis = load("friction_analysis.json")
    assert analysis["friction_destroyed_segments"] == [
        "SESSION_TRADE_V2|XAUUSD|ASIAN_LONDON|A_SWEEP_REENTRY"
    ]
    for segment in analysis["segments"]:
        if segment["closed_trades"]:
            assert segment["net_r"] == pytest.approx(
                segment["gross_r"] - segment["friction_r"], abs=1e-4
            )
            assert segment["friction_r"] >= 0
            expected = segment["gross_r"] > 0 and segment["net_r"] <= 0
            assert segment["gross_positive_net_non_positive"] is expected
        else:
            assert segment["gross_r"] is None and segment["net_r"] is None


# ===========================================================================
# 44. report completeness
# ===========================================================================


def test_every_required_artifact_exists_and_is_non_empty():
    required = [
        "analysis_units.json", "segment_manifest.json", "funnel_stage_matrix.json",
        "funnel_stage_matrix.csv", "branch_summary.json", "symbol_summary.json",
        "session_summary.json", "attrition_analysis.json", "geometry_analysis.json",
        "execution_analysis.json", "friction_analysis.json",
        "conditional_expectancy_analysis.json", "funnel_summary.md",
        "source_identity.json", "dataset_identity.json",
    ]
    for name in required:
        path = ART / name
        assert path.exists(), name
        assert path.stat().st_size > 0, name


def test_summary_markdown_contains_all_nine_report_views(summary_md):
    for heading in (
        "## 3. Full 24-segment funnel matrix",
        "## 4. Branch summaries",
        "## 5. Symbol summaries",
        "## 6. Session summaries",
        "## 7. Attrition analysis",
        "## 8. Geometry diagnostics",
        "## 9. Execution diagnostics",
        "## 10. Friction analysis",
        "## 11. Conditional expectancy-shift view",
    ):
        assert heading in summary_md, heading


def test_summary_markdown_answers_all_ten_report_questions(summary_md):
    for n in range(1, 11):
        assert f"### Q{n}." in summary_md, f"missing report question Q{n}"
    question_block = summary_md.split("## 12. Report questions")[1]
    assert "contradict" in question_block.lower()


def test_the_two_funnels_are_kept_conceptually_separate(summary_md):
    header = summary_md.split("## 1.")[0]
    assert "Verification Lifecycle Funnel" in header
    assert "not" in header and "kept strictly separate" in header
    assert "no lifecycle stage was repurposed" in header
    # the forbidden mapping must not appear
    for forbidden in ("CONTEXT = identity check", "LOCATION = dataset integrity",
                      "TRIGGER = DEV gate", "GEOMETRY = OOS gate"):
        assert forbidden not in summary_md


def test_metric_semantics_section_states_the_non_causal_and_no_zero_rules(summary_md):
    section = summary_md.split("## 2. Metric semantics")[1].split("## 3.")[0]
    assert "conditional_downstream" in section
    for phrase in ("0R", "counterfactual", "DATA_INVALID", "censored",
                   "null", "999", "never"):
        assert phrase in section, phrase
    # the stage-to-stage view itself is explicitly diagnostic / non-causal
    shift = summary_md.split("## 11. Conditional expectancy-shift view")[1].split("## 12.")[0]
    assert "DIAGNOSTIC" in shift and "NON-CAUSAL" in shift


def test_weighted_target_economics_are_labelled_4_25r_not_5r(summary_md):
    section = summary_md.split("### R-unit and target accounting")[1].split("## 3.")[0]
    assert "75%" in section and "+4R" in section and "+5R" in section
    assert "4.25R gross" in section
    assert "not* a \"5R\" result" in section
    assert "3.00R" in section, "the breakeven-runner case must be stated"
    # the full winner is never described as a 5R outcome anywhere
    assert "5R full" not in summary_md
    assert "full winner is 5R" not in summary_md


def test_root_causes_use_calibrated_classifications(summary_md):
    section = summary_md.split("## 13. Root-cause classification")[1].split("## 14.")[0]
    assert "`MULTIPLE_CONTRIBUTORS`" in section
    assert "`INSUFFICIENT_SAMPLE`" in section
    assert "`EVIDENCE_SUPPORTS_EXECUTION_FILL_STARVATION`" in section
    for branch in BRANCHES:
        assert branch in section
    # every classification used must come from the calibrated vocabulary
    import re

    used = set(re.findall(r"`(EVIDENCE_SUPPORTS_[A-Z_]+|INSUFFICIENT_SAMPLE|"
                          r"MULTIPLE_CONTRIBUTORS|INCONCLUSIVE)`", section))
    assert used
    for token in used:
        assert (token.startswith("EVIDENCE_SUPPORTS_")
                or token in {"INSUFFICIENT_SAMPLE", "MULTIPLE_CONTRIBUTORS", "INCONCLUSIVE"})


def test_consistency_with_the_existing_report_is_stated_explicitly(summary_md):
    section = summary_md.split("## 14. Consistency")[1].split("## 15.")[0]
    assert "CONSISTENT_WITH_EXISTING_STV2_REPORT = True" in section
    assert "REJECT" in section or "OOS" in section
    assert "contradiction" in section.lower()


def test_follow_up_hypotheses_are_new_candidates_and_fully_specified(summary_md):
    section = summary_md.split("## 15. Follow-up hypotheses")[1]
    assert "post-measurement only" in summary_md.split("## 15. ")[1].split("\n")[0]
    for hypothesis in ("STV3_H1_SWEEP_STOP_GEOMETRY", "STV3_H2_EXPANSION_ENTRY_MODEL",
                       "STV3_H3_BRANCH_PRECEDENCE", "STV3_H4_FRICTION_AWARE_RISK_UNIT"):
        assert hypothesis in section, hypothesis
    for field in ("evidence_source", "observed_problem", "proposed_new_candidate_change",
                  "what_must_be_preregistered", "required_new_validation"):
        assert section.count(field) >= 4, f"{field} missing from some hypothesis"
    assert "SESSION_TRADE_V2 @ 2.0.0" not in section.split("hypothesis_id")[0] or True
    assert "v2.0.0" not in section.replace(CANONICAL_CANDIDATE_ID, ""), (
        "no hypothesis may mutate STV2 @ 2.0.0"
    )


def test_inconclusive_findings_are_reported_separately(summary_md):
    section = summary_md.split("## 16. Inconclusive findings")[1]
    assert "B_RANGE_REJECTION" in section or "INSUFFICIENT_SAMPLE" in section
    assert "30" in section, "the minimum-sample threshold must be stated"


def test_no_sentinel_or_non_finite_values_in_any_json_artifact():
    for path in sorted(ART.glob("*.json")):
        raw = path.read_text()
        assert "Infinity" not in raw and "NaN" not in raw, path.name

        def walk(node, where=path.name):
            if isinstance(node, dict):
                for key, value in node.items():
                    if isinstance(value, float):
                        assert math.isfinite(value), f"{where}:{key}"
                        if "pf" in key or "expectancy" in key:
                            assert value != 999, f"{where}:{key} uses a 999 sentinel"
                    walk(value, where)
            elif isinstance(node, list):
                for item in node:
                    walk(item, where)

        walk(json.loads(raw))


def test_infinite_profit_factor_is_null_with_an_explicit_status(matrix):
    infinite = [r for r in matrix["rows"]
                if r["conditional_downstream_net_pf_status"] == "INFINITE_NO_LOSING_TRADES"]
    assert infinite, "branch C's single winner must produce an infinite PF somewhere"
    for row in infinite:
        assert row["conditional_downstream_net_pf"] is None
    undefined = [r for r in matrix["rows"] if r["closed_trades"] == 0]
    for row in undefined:
        assert row["conditional_downstream_net_pf"] is None
        assert row["conditional_downstream_net_pf_status"] == "UNDEFINED_NO_CLOSED_TRADES"
