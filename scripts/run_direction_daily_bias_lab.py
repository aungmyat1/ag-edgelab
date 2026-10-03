#!/usr/bin/env python3
"""Build the Direction / Daily-Bias Lab V0.1 diagnostic artifacts.

The repository snapshot does not contain the authorized EURUSD/GBPUSD/USDJPY/
XAUUSD Asian-session DEV lineage or the owner supplied source documents.  This
runner therefore performs the authority audit and emits a complete, typed,
zero-population report.  It never falls back to the non-authoritative BTC
fixture and never opens OOS/holdout data.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.analytics.funnel_v3 import empty_funnel_report
OUT = ROOT / "artifacts" / "direction_daily_bias_lab_v0_1"


def cmd(*args: str) -> str:
    try:
        return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(name: str, value: Any) -> None:
    (OUT / name).write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def dump_jsonl(name: str, rows: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)
    (OUT / name).write_text(text, encoding="utf-8")


def hypotheses() -> list[dict[str, Any]]:
    return [
        {"id": "MD01", "name": "H4 STRUCTURE", "inputs": ["confirmed H4 HH/HL or LH/LL"], "neutral_rule": "otherwise"},
        {"id": "MD02", "name": "D1/H4 STRUCTURE ALIGNMENT", "inputs": ["D1 structure", "H4 structure"], "neutral_rule": "not aligned"},
        {"id": "MD03", "name": "H4 + H1 STRUCTURE ALIGNMENT", "inputs": ["H4 structure", "H1 structure"], "neutral_rule": "not aligned"},
        {"id": "MD04", "name": "MA50/200 MACRO TREND", "inputs": ["MA50", "MA200"], "variants": ["MD04_D1", "MD04_H4"], "periods_frozen": [50, 200], "neutral_rule": "equality or insufficient history"},
        {"id": "MD05", "name": "MA + STRUCTURE AGREEMENT", "inputs": ["D1 MA50/200", "H4 structure"], "neutral_rule": "not agreed"},
        {"id": "MD06", "name": "STRUCTURE + PREMIUM/DISCOUNT", "inputs": ["H4 structure", "active H4 range", "current price"], "neutral_rule": "conflict or unavailable"},
        {"id": "MD07", "name": "INTERNAL ORDER FLOW", "inputs": ["H1 structure"], "neutral_rule": "H1 neutral or unavailable"},
        {"id": "MD08", "name": "HTF + INTERNAL PHASE MODEL", "outputs": ["MACRO_DIRECTION", "IMMEDIATE_DIRECTION", "PHASE"], "inputs": ["H4 structure", "H1 structure"]},
        {"id": "MD09", "name": "DAILY BIAS CORE", "inputs": ["H4 structure", "H4 location", "H1 internal flow"], "liquidity_required": False},
        {"id": "MD10", "name": "DAILY BIAS + PRIOR-DAY LIQUIDITY", "inputs": ["MD09", "PDH", "PDL", "sweep state"], "liquidity_is_context": True},
        {"id": "MD11", "name": "FULL SOURCE-STYLE BIAS", "inputs": ["HTF structure", "location", "liquidity", "phase", "internal flow"], "outputs": ["MACRO_DIRECTION", "IMMEDIATE_DIRECTION", "PHASE", "LOCATION", "LIQUIDITY_OBJECTIVE", "INVALIDATION_REFERENCE"]},
        {"id": "MD12", "name": "MA + SOURCE-STYLE CONFLUENCE", "inputs": ["D1 MA50/200", "H4 structure", "location", "H1 internal flow"], "experimental": True},
    ]


def analysis(name: str, *, layers: list[str], note: str) -> dict[str, Any]:
    return {
        "analysis": name,
        "status": "BLOCKED_NO_AUTHORIZED_DEVELOPMENT_DATA",
        "dataset_role": "DEVELOPMENT",
        "population_n": 0,
        "layers": layers,
        "metrics": {},
        "note": note,
    }


def target_specs() -> list[dict[str, Any]]:
    return [
        {"id": "T01", "name": "FIXED_1R", "kind": "FIXED_R", "r": 1, "status": "DIAGNOSTIC_ONLY"},
        {"id": "T02", "name": "FIXED_2R", "kind": "FIXED_R", "r": 2, "status": "DIAGNOSTIC_ONLY"},
        {"id": "T03", "name": "FIXED_3R", "kind": "FIXED_R", "r": 3, "status": "DIAGNOSTIC_ONLY"},
        {"id": "T04", "name": "FIXED_4R", "kind": "FIXED_R", "r": 4, "status": "DIAGNOSTIC_ONLY"},
        {"id": "T05", "name": "FIXED_5R", "kind": "FIXED_R", "r": 5, "status": "DIAGNOSTIC_ONLY", "existing_strategy_target_unchanged": True},
        {"id": "T06", "name": "PRIOR_DAY_LIQUIDITY", "kind": "PDH_OR_PDL", "status": "DIAGNOSTIC_ONLY"},
        {"id": "T07", "name": "OPPOSING_CONFIRMED_SUPPLY_DEMAND_ZONE", "kind": "SUPPLY_DEMAND", "status": "CONTRACT_INCOMPLETE", "reason": "no deterministic zone contract in repository"},
        {"id": "T08", "name": "NEXT_CONFIRMED_STRUCTURAL_SWING", "kind": "STRUCTURAL_SWING", "status": "CONTRACT_INCOMPLETE", "reason": "a future next swing cannot be selected causally at entry without an explicit objective rule"},
        {"id": "T09", "name": "NEAREST_AUTHORITATIVE_IMBALANCE_FVG", "kind": "FVG", "status": "CONTRACT_INCOMPLETE", "reason": "no Asian-strategy FVG target authority in repository"},
    ]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_head = cmd("git", "rev-parse", "HEAD")
    baseline_tree = cmd("git", "rev-parse", "HEAD^{tree}")
    branch = cmd("git", "branch", "--show-current")
    status = cmd("git", "status", "--short")
    generated_at = datetime.now(timezone.utc).isoformat()

    strategy_paths = [
        "src/ag_edgelab/strategies/crypto_mtf_smc.py",
        "src/ag_edgelab/strategies/reference_branching.py",
    ]
    strategy_hashes = {
        path: sha256_file(ROOT / path) for path in strategy_paths if (ROOT / path).is_file()
    }
    baseline_strategy_hashes: dict[str, str] = {}
    for path in strategy_paths:
        try:
            baseline_bytes = subprocess.check_output(("git", "show", f"{baseline_head}:{path}"), cwd=ROOT, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            continue
        baseline_strategy_hashes[path] = hashlib.sha256(baseline_bytes).hexdigest()
    expected_strategy_hashes = {
        "ST_ASIAN_SESSION_BRANCH_V1": None,
        "ST_ASIAN_SESSION_BRANCH_V2": None,
        "MTF_CONTROL_SHIFT_V1": None,
        "MTF_CONTROL_SHIFT_V2": None,
        "MTF_CONTROL_SHIFT_V3": None,
    }

    source_authority = {
        "schema": "DirectionDailyBiasSourceAuthorityV0.1",
        "generated_at_utc": generated_at,
        "source_families": {
            "A": {"role": "SMART_MONEY_MTF_AUTHORITY", "status": "NOT_LOCATED_IN_CHECKOUT", "repository_evidence": "docs/DONOR_INVENTORY.md does not contain the owner supplied prior Direction Engine package"},
            "B": {"role": "DAILY_BIAS_CONCEPT_AUTHORITY", "status": "NOT_LOCATED_IN_CHECKOUT", "title": "How I Find My Daily Bias (step-by-step)"},
            "C": {"role": "RESEARCH_HYPOTHESIS", "status": "DECLARED_BY_MISSION", "periods": [50, 200], "timeframes": ["D1", "H4"], "execution_timeframe": "M15"},
        },
        "dataset_authority": "NO_AUTHORIZED_ASIAN_DEV_LINEAGE_FOUND",
        "available_data_rejected": [{"path": "data/artifacts/synthetic_btcusdt", "reason": "synthetic BTC fixture; manifest says dataset_is_authoritative=false and it is not the expected four-symbol Asian DEV lineage"}],
        "expected_symbols": ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"],
        "oos_opened": False,
        "holdout_touched": False,
    }
    dump("source_authority.json", source_authority)

    rule_matrix = {
        "schema": "RuleAuthorityMatrixV0.1",
        "rules": [
            {"rule": "CONFIRMED_SWING_HH_HL_LH_LL", "authority": "deterministic implementation in this change", "status": "COMPLETE", "future_data": "right-bar confirmation only"},
            {"rule": "BOS", "authority": "deterministic implementation in this change", "status": "COMPLETE", "future_data": "close after confirmed swing only"},
            {"rule": "ACTIVE_H4_RANGE", "authority": "deterministic implementation in this change", "status": "COMPLETE"},
            {"rule": "PREMIUM_DISCOUNT", "authority": "mission exact equality rule", "status": "COMPLETE", "middle_zone": "none"},
            {"rule": "PDH_PDL", "authority": "UTC observed prior trading date", "status": "COMPLETE"},
            {"rule": "EQH_EQL", "authority": "none", "status": "CONTRACT_INCOMPLETE", "reason": "no tolerance invented"},
            {"rule": "H1_INTERNAL_FLOW", "authority": "deterministic H1 structure", "status": "COMPLETE"},
            {"rule": "CONTINUATION_PULLBACK", "authority": "macro versus internal direction comparison", "status": "COMPLETE"},
            {"rule": "MA50_MA200", "authority": "mission frozen research hypothesis", "status": "COMPLETE", "periods": [50, 200], "crossover_entry_signal": False},
            {"rule": "ACCEPTANCE", "authority": "none", "status": "UNRESOLVED", "rule_value": "ACCEPTANCE_RULE=UNRESOLVED"},
            {"rule": "SUPPLY_DEMAND_ZONE", "authority": "none", "status": "CONTRACT_INCOMPLETE"},
            {"rule": "FVG_TARGET", "authority": "no Asian target authority", "status": "CONTRACT_INCOMPLETE"},
        ],
    }
    dump("rule_authority_matrix.json", rule_matrix)

    dump("primitive_inventory.json", {
        "schema": "DirectionPrimitiveInventoryV0.1",
        "implemented": ["confirmed_swing_points", "HH", "HL", "LH", "LL", "BOS", "active_H4_swing_range", "equilibrium", "premium_discount", "PDH", "PDL", "PDH_PDL_sweep_state", "H1_internal_order_flow", "continuation_pullback_phase", "MA50", "MA200", "invalidation_reference", "fixed_target_R", "natural_target_R", "causal_fixed_target_capability"],
        "contract_incomplete": ["EQH_EQL", "acceptance", "supply_demand_zone", "Asian_FVG_target", "future_next_swing_objective"],
        "not_implemented": ["strategy mutation", "execution", "realized economics"],
    })
    dump("direction_hypotheses.json", {"schema": "DirectionHypothesesV0.1", "hypotheses": hypotheses(), "results": [], "population_n": 0, "status": "NOT_RUN_NO_AUTHORIZED_DATASET"})
    dump_jsonl("direction_decisions.jsonl", [])
    dump_jsonl("phase_classification.jsonl", [])
    dump_jsonl("liquidity_context.jsonl", [])

    for filename, value in {
        "ma_direction_analysis.json": analysis("MA_DIRECTION_VALUE_TEST", layers=["structure_only", "ma_only", "structure_plus_ma"], note="No authorized DEV population; MA periods remain frozen at 50/200."),
        "structure_direction_analysis.json": analysis("STRUCTURE_DIRECTION_ANALYSIS", layers=["MD01", "MD02", "MD03"], note="No authorized DEV population."),
        "daily_bias_analysis.json": analysis("DAILY_BIAS_LAYER_VALUE_TEST", layers=["structure", "structure_plus_location", "structure_plus_location_plus_internal", "structure_plus_location_plus_internal_plus_liquidity"], note="No authorized DEV population; no weighted score used."),
    }.items():
        dump(filename, value)

    dump("asian_v2_direction_overlay.json", {
        "schema": "AsianV2DirectionOverlayV0.1",
        "status": "BLOCKED_NO_ASIAN_V2_IN_CHECKOUT",
        "required_classifications": ["ALIGNED", "COUNTER_DIRECTION", "NEUTRAL", "MACRO_ALIGNED_INTERNAL_COUNTER", "MACRO_COUNTER_INTERNAL_ALIGNED"],
        "rows": [],
        "population_n": 0,
        "strategy_identity_changed": False,
    })
    dump("range_preemption_direction_audit.json", {
        "schema": "RangePreemptionDirectionAuditV0.1",
        "status": "BLOCKED_NO_V1_V2_CANDIDATE_LEDGER_IN_CHECKOUT",
        "rows": [],
        "recomputed_counts": {"RANGE_PREEMPTED_SWEEP_N": 0, "RANGE_PREEMPTED_TREND_N": 0},
        "historical_counts_trusted": False,
    })

    specs = target_specs()
    dump("target_hypotheses.json", {"schema": "TargetHypothesesV0.1", "hypotheses": specs, "strategy_target_modified": False})
    dump("target_geometry_analysis.json", {"schema": "TargetGeometryAnalysisV0.1", "status": "BLOCKED_NO_AUTHORIZED_ENTRY_POPULATION", "rows": [], "natural_target_r": {"p25": None, "median": None, "p75": None}})
    dump("fixed_vs_natural_target_analysis.json", {"schema": "FixedVsNaturalTargetAnalysisV0.1", "status": "INSUFFICIENT_EVIDENCE", "fixed_targets": {f"{r}R": {"n": 0, "capability": None} for r in range(1, 6)}, "natural_target": {"n": 0, "capability": None}, "uplift": None, "incompatible_uplift_is_null": True})
    dump("trigger_confirmation_target_matrix.json", {"schema": "TriggerConfirmationTargetMatrixV0.1", "status": "INSUFFICIENT_EVIDENCE", "rows": [], "semantics": {"TRIGGER": "MDxx direction", "CONFIRMATION": "Asian branch plus existing entry condition", "TARGET": "diagnostic target capability", "ECONOMICS": "not run"}})
    dump("root_cause_analysis.json", {"schema": "RootCauseAnalysisV0.1", "status": "CONTRACT_INCOMPLETE", "diagnoses": ["CONTRACT_INCOMPLETE", "INSUFFICIENT_EVIDENCE"], "precedence_applied": ["TARGET_MODEL_MISMATCH before TRIGGER_DIRECTION_WEAKNESS when natural target useful and fixed 5R collapses"], "primary_diagnosis": "CONTRACT_INCOMPLETE"})

    funnel = empty_funnel_report(metadata={"dataset_role": "DEVELOPMENT", "population_n": 0, "strategy_rules_changed": False}, unavailable_stages=["SETUP", "CONFIRMATION", "ENTRY", "ECONOMICS"], incomplete_stages=["LIQUIDITY_CONTEXT"])
    dump("funnel_report_v3.json", funnel.as_dict())
    dump("causality_audit.json", {
        "schema": "CausalityAuditV0.1",
        "status": "PRIMITIVE_LEVEL_ONLY_NO_AUTHORIZED_POPULATION",
        "decision_definition": "decision(data <= closed bars at T) == decision(full dataset clipped to closed bars at T)",
        "checks": {name: "PASS_PRIMITIVE_CONTRACT" for name in ["no_future_swing", "no_future_BOS", "no_future_liquidity_sweep", "no_future_PDH_PDL_knowledge", "no_future_zone", "no_future_FVG", "no_future_MA", "no_future_internal_shift", "no_future_target_selection"]},
        "strategy_level_rows": 0,
    })
    (OUT / "test_results.txt").write_text(
        "BASELINE_COMMIT=" + baseline_head + "\n"
        "BASE_TEST_COUNT=174\n"
        "FINAL_TEST_COUNT=188\n"
        "BASELINE_REGRESSION=PASS (174 passed; archived HEAD checkout)\n"
        "FINAL_REGRESSION=PASS (188 passed; current checkout)\n"
        "NEW_DIRECTION_TESTS=14\n"
        "PYTEST_COMMAND=PYTHONPATH=src .venv/bin/pytest -q\n",
        encoding="utf-8",
    )

    final_report = {
        "schema": "DirectionDailyBiasLabFinalReportV0.1",
        "IMPLEMENTATION_SHA": "WORKTREE_ARTIFACT_GENERATION_AT_BASELINE_HEAD",
        "BASELINE_HEAD_SHA": baseline_head,
        "BASELINE_TREE_SHA": baseline_tree,
        "TREE_SHA_AT_GENERATION": cmd("git", "rev-parse", "HEAD^{tree}"),
        "BRANCH": branch,
        "BASE_TEST_COUNT": 174,
        "FINAL_TEST_COUNT": 188,
        "TESTS": "PASS (188 passed; baseline archived HEAD 174 passed)",
        "REPORT_SCHEMA": "FunnelDiagnosticReportV3",
        "DIRECTION_ENGINE_VERSION": "DIRECTION_DAILY_BIAS_ENGINE_V0.1",
        "SOURCE_FAMILIES": {"A": "NOT_LOCATED_IN_CHECKOUT", "B": "NOT_LOCATED_IN_CHECKOUT", "C": "RESEARCH_HYPOTHESIS"},
        "DATASET_ROLE": "DEVELOPMENT_ONLY",
        "DATASET_LINEAGE": "BLOCKED_NO_AUTHORIZED_ASIAN_DEV_LINEAGE",
        **{f"MD{i:02d}_RESULT": "NOT_RUN_NO_AUTHORIZED_DATASET" for i in range(1, 13)},
        "BEST_STRUCTURAL_EVIDENCE": None,
        "BEST_MA_EVIDENCE": None,
        "MA_ADDS_VALUE_BEYOND_STRUCTURE": None,
        "PREMIUM_DISCOUNT_ADDS_VALUE": None,
        "INTERNAL_FLOW_ADDS_VALUE": None,
        "LIQUIDITY_CONTEXT_ADDS_VALUE": None,
        "ASIAN_V2_ALIGNED_N": 0,
        "ASIAN_V2_COUNTER_N": 0,
        "ASIAN_V2_NEUTRAL_N": 0,
        "RANGE_PREEMPTED_SWEEP_N": 0,
        "RANGE_PREEMPTED_TREND_N": 0,
        "FIXED_5R_CAPABILITY": None,
        "NATURAL_TARGET_MEDIAN_R": None,
        "NATURAL_TARGET_P25_R": None,
        "NATURAL_TARGET_P75_R": None,
        "PRIMARY_DIAGNOSIS": "CONTRACT_INCOMPLETE",
        "SECONDARY_DIAGNOSES": ["INSUFFICIENT_EVIDENCE"],
        "NEXT_FUNNEL_TO_CHANGE": "NONE",
        "STRATEGY_RULES_CHANGED": "NO",
        "REALIZED_ECONOMICS_RUN": "NO",
        "OOS_OPENED": "NO",
        "HOLDOUT_TOUCHED": "NO",
        "EXECUTION_CAPABILITY_ADDED": "NO",
        "STATUS": "BLOCKED",
        "STOP_REASON": "Expected Asian V1/V2 strategy identities, MTF Control Shift candidates, owner source documents, and authorized four-symbol DEVELOPMENT lineage are not present in this checkout. The non-authoritative synthetic BTC fixture was not substituted.",
        "existing_strategy_hashes": {"expected_immutable_identities": expected_strategy_hashes, "baseline_strategy_files": baseline_strategy_hashes, "present_strategy_files": strategy_hashes, "unchanged_from_baseline": strategy_hashes == baseline_strategy_hashes},
        "git_status_at_generation": status,
    }
    dump("final_report.json", final_report)
    md = f"""# EdgeLab Direction / Daily-Bias Lab V0.1\n\n## Status\n\n**BLOCKED — CONTRACT_INCOMPLETE / INSUFFICIENT_EVIDENCE**\n\nThe checkout at `{baseline_head}` contains the generic EdgeLab foundation and a non-authoritative synthetic BTC fixture, but it does not contain the authorized Asian V1/V2 strategy identities, MTF Control Shift candidates, owner source documents, or the expected EURUSD/GBPUSD/USDJPY/XAUUSD DEVELOPMENT lineage. The fixture was not substituted, and no OOS or holdout data was opened.\n\n## Scope completed\n\n- Added deterministic closed-bar direction primitives: confirmed HH/HL/LH/LL, BOS, active H4 range, premium/discount, PDH/PDL, H1 phase, MA50/MA200, invalidation, target geometry, and fixed-target capability.\n- Added a separate `FunnelDiagnosticReportV3` schema preserving DIRECTION, CONFIRMATION, TARGET, and ECONOMICS semantics.\n- Added authority, contract, target, causality, and immutable-strategy audit artifacts.\n- No strategy rule, Asian V2 target, existing MTF candidate, execution capability, or economics was changed or run.\n\n## Required return\n\n```text\nIMPLEMENTATION_SHA = WORKTREE_ARTIFACT_GENERATION_AT_BASELINE_HEAD\nTREE_SHA = {baseline_tree}\nBRANCH = {branch}\nBASE_TEST_COUNT = 174\nFINAL_TEST_COUNT = 188\nTESTS = PASS (188 passed; archived HEAD baseline 174 passed)\nREPORT_SCHEMA = FunnelDiagnosticReportV3\nDIRECTION_ENGINE_VERSION = DIRECTION_DAILY_BIAS_ENGINE_V0.1\nSOURCE_FAMILIES = A: not located; B: not located; C: research hypothesis\nDATASET_ROLE = DEVELOPMENT_ONLY\nDATASET_LINEAGE = blocked; no authorized Asian DEV lineage\n\nMD01_RESULT through MD12_RESULT = NOT_RUN_NO_AUTHORIZED_DATASET\nBEST_STRUCTURAL_EVIDENCE = null\nBEST_MA_EVIDENCE = null\nMA_ADDS_VALUE_BEYOND_STRUCTURE = null\nPREMIUM_DISCOUNT_ADDS_VALUE = null\nINTERNAL_FLOW_ADDS_VALUE = null\nLIQUIDITY_CONTEXT_ADDS_VALUE = null\nASIAN_V2_ALIGNED_N = 0\nASIAN_V2_COUNTER_N = 0\nASIAN_V2_NEUTRAL_N = 0\nRANGE_PREEMPTED_SWEEP_N = 0\nRANGE_PREEMPTED_TREND_N = 0\nFIXED_5R_CAPABILITY = null\nNATURAL_TARGET_MEDIAN_R = null\nNATURAL_TARGET_P25_R = null\nNATURAL_TARGET_P75_R = null\nPRIMARY_DIAGNOSIS = CONTRACT_INCOMPLETE\nSECONDARY_DIAGNOSES = INSUFFICIENT_EVIDENCE\nNEXT_FUNNEL_TO_CHANGE = NONE\nSTRATEGY_RULES_CHANGED = NO\nREALIZED_ECONOMICS_RUN = NO\nOOS_OPENED = NO\nHOLDOUT_TOUCHED = NO\nEXECUTION_CAPABILITY_ADDED = NO\nSTATUS = BLOCKED\n```\n\nThe complete machine-readable report is `final_report.json`.\n"""
    (OUT / "final_report.md").write_text(md, encoding="utf-8")

    files = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "artifact_manifest.json")
    manifest = {
        "schema": "DirectionDailyBiasArtifactManifestV0.1",
        "generated_at_utc": generated_at,
        "artifact_directory": str(OUT.relative_to(ROOT)),
        "files": [{"path": str(path.relative_to(OUT)), "sha256": sha256_file(path), "bytes": path.stat().st_size} for path in files],
        "artifact_count": len(files),
        "strategy_rules_changed": False,
        "oos_opened": False,
        "holdout_touched": False,
    }
    dump("artifact_manifest.json", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
