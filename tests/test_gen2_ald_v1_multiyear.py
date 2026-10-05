"""CI contract for GEN2_ALD_V1_MULTIYEAR_DEV_R1.

The mission's central claim is "the rules did not change, only the data did".
These tests exist to make that claim falsifiable:

  * the frozen rule hash must still reproduce,
  * the strategy source file must be byte-identical to the one the first
    campaign ran,
  * the multi-year replay path must reproduce the committed 2017 campaign
    unit-for-unit (when the pinned archives are present),
  * OOS and the sealed holdout must be structurally unreachable for EVERY year,
  * the A/B/C/D sample classification must be a pure, deterministic function of
    preregistered thresholds.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from ag_edgelab.data import fx_histdata_multiyear as D
from ag_edgelab.data.fx_histdata_2017 import PARTITIONS as PR10_PARTITIONS
from ag_edgelab.data.fx_histdata_2017 import PartitionError
from ag_edgelab.strategies import asian_liquidity_displacement_multiyear as M
from ag_edgelab.strategies import asian_liquidity_displacement_multiyear_analysis as MA
from ag_edgelab.strategies import asian_liquidity_displacement_v1 as S
from ag_edgelab.strategies.asian_liquidity_displacement_prereg import (
    POOLED_ENTRY_ELIGIBILITY_N,
)
from ag_edgelab.universal.fx_dev_campaign import MIN_ENTERED_N

ART = Path("data/artifacts/gen2_asian_liquidity_displacement_v1_multiyear")
NARROW_ART = Path("data/artifacts/gen2_asian_liquidity_displacement_v1")
DATA = Path("data/external/histdata_fx_multiyear")

REQUIRED_ARTIFACTS = (
    "preregistration.json", "dataset_binding.json", "candidate_instance_identity.json",
    "year_matrix.csv", "symbol_session_matrix.csv", "funnel_report.json",
    "attrition_reasons.json", "target_capability.json", "continuation_survival.json",
    "temporal_diagnostics.json", "v1_narrow_vs_multiyear.json", "robustness_report.json",
    "pre_oos_gate_result.json", "final_report.json", "final_report.md",
    "dataset_quality_report.json", "final_return.json", "artifact_manifest.json",
)

needs_data = pytest.mark.skipif(
    not (DATA / "manifest.json").exists(),
    reason="pinned multi-year archives absent; run scripts/acquire_histdata_fx_multiyear.py")
needs_run = pytest.mark.skipif(
    not (ART / "final_report.json").exists(),
    reason="multi-year replay has not been run in this checkout")


# ---------------------------------------------------------------------------
# 0. strategy identity — RULES_CHANGED = NO
# ---------------------------------------------------------------------------

def test_frozen_rule_hash_still_reproduces():
    assert S.STRATEGY_HASH == M.EXPECTED_RULE_HASH
    out = M.assert_rule_identity()
    assert out["state"] == "PASS"
    assert out["RULES_CHANGED"] == "NO"
    assert all(out["checks"].values())


def test_identity_check_stops_on_any_rule_drift(monkeypatch):
    monkeypatch.setattr(M, "DISPLACEMENT_BODY_RANGE_MIN", 0.65)
    with pytest.raises(M.StrategyIdentityMismatch) as exc:
        M.assert_rule_identity()
    assert "STRATEGY_IDENTITY_MISMATCH" in str(exc.value)


def test_identity_check_stops_when_the_expected_hash_does_not_match(monkeypatch):
    monkeypatch.setattr(M, "EXPECTED_RULE_HASH", "0" * 64)
    with pytest.raises(M.StrategyIdentityMismatch):
        M.assert_rule_identity()


def test_strategy_source_file_is_byte_identical_to_the_first_campaign():
    """The strongest form of RULES_CHANGED = NO: the code file itself."""
    committed = json.loads((NARROW_ART / "strategy_contract.json").read_text())
    assert S.contract_hashes()["strategy_code_hash"] == \
        committed["contract_hashes"]["strategy_code_hash"]


def test_sessions_and_displacement_are_the_preregistered_frozen_values():
    sc = S.session_contract()
    assert sc["asian_reference_utc"] == {"start_hour": 0, "end_hour": 6}
    assert sc["london_entry_utc"] == {"start_hour": 7, "end_hour": 10}
    assert sc["new_york_entry_utc"] == {"start_hour": 12, "end_hour": 15}
    assert sc["widening_allowed"] is False
    assert S.DISPLACEMENT_BODY_RANGE_MIN == 0.70
    assert S.sl_contract()["buffer_points"] == 0
    assert S.sl_contract()["buffer_pips"] == 0


def test_the_multiyear_layer_does_not_redefine_any_rule():
    """No rule constant may be re-bound in the multi-year modules."""
    rule_names = {"DISPLACEMENT_BODY_RANGE_MIN", "ASIAN_REFERENCE_UTC", "SESSION_PAIRS",
                  "MIN_ASIAN_M15_BARS", "SWING_ORDER_M15", "FIXED_R_TARGETS",
                  "OUTCOME_HORIZON_M5_BARS", "WARMUP_DAYS", "FVG_MAX_AGE_M5_BARS"}
    for module in (M, MA, D):
        tree = ast.parse(Path(module.__file__).read_text())
        assigned = {t.id for node in ast.walk(tree)
                    if isinstance(node, ast.Assign)
                    for t in node.targets if isinstance(t, ast.Name)}
        assert not (assigned & rule_names), \
            f"{module.__name__} re-binds rule constants {sorted(assigned & rule_names)}"


def test_dev_end_is_vestigial_in_the_frozen_rule_engine():
    """replay_symbol passes a 2017 dev_end; the rule body must never read it.

    This is what makes feeding per-year frames to the frozen replay exact.
    """
    tree = ast.parse(Path(S.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_evaluate_unit")
    body_names = {n.id for n in ast.walk(ast.Module(body=fn.body, type_ignores=[]))
                  if isinstance(n, ast.Name)}
    assert "dev_end" not in body_names, \
        "_evaluate_unit now reads dev_end; the multi-year loader must pass per-year bounds"


# ---------------------------------------------------------------------------
# 1. data authority R2
# ---------------------------------------------------------------------------

def test_annual_partitions_reproduce_the_pr10_2017_split_exactly():
    for role in ("DEVELOPMENT", "OOS", "SEALED_HOLDOUT"):
        assert D.partition_bounds(role, 2017) == PR10_PARTITIONS[role]


@pytest.mark.parametrize("year", [2000, 2009, 2013, 2016])
def test_annual_partitions_are_contiguous_and_cover_the_year(year):
    dev, oos, hold = (D.partition_bounds(r, year)
                      for r in ("DEVELOPMENT", "OOS", "SEALED_HOLDOUT"))
    assert dev[0].year == year and dev[0].month == 1 and dev[0].day == 1
    assert dev[1] == oos[0] and oos[1] == hold[0]
    assert hold[1].year == year + 1 and hold[1].month == 1 and hold[1].day == 1


def test_only_development_is_loadable_for_every_year():
    D.assert_partition_accessible("DEVELOPMENT")
    for role in ("OOS", "SEALED_HOLDOUT"):
        with pytest.raises(D.NonDevelopmentAccessError):
            D.assert_partition_accessible(role)
    with pytest.raises(PartitionError):
        D.assert_partition_accessible("RECENT_UNPARTITIONED")
    assert sorted(D.LOADABLE_ROLES) == ["DEVELOPMENT"]
    assert D.authority_contract()["loadable_roles"] == ["DEVELOPMENT"]


def test_build_dev_frames_refuses_a_non_development_request(monkeypatch):
    monkeypatch.setattr(D, "LOADABLE_ROLES", frozenset())
    with pytest.raises(D.NonDevelopmentAccessError):
        D.build_dev_frames("EURUSD", 2016, S.aggregate_m5)


def test_coverage_and_balanced_panel_are_declared_not_inferred():
    assert D.COVERAGE["XAUUSD"][0] == 2009, "gold history starts 2009; never backfilled"
    assert D.BALANCED_PANEL[0] == 2009 and D.BALANCED_PANEL[-1] == 2017
    assert len(D.admitted_symbol_years()) == 63
    assert set(D.SYMBOLS) == set(S.SYMBOL_UNIVERSE)


def test_the_derivation_code_is_the_frozen_pr10_module():
    assert D.authority_contract()["derivation_code"] == \
        "ag_edgelab.data.fx_histdata_2017 (unmodified)"
    src = Path(D.__file__).read_text()
    assert "def aggregate_m15" not in src, "M15 bucketing must not be reimplemented"
    assert "def load_histdata_m1" not in src, "the loader must not be reimplemented"


@needs_data
def test_manifest_carries_the_cross_source_identity_proof():
    manifest = D.load_manifest()
    proof = manifest["cross_source_identity_proof"]
    assert proof["result"] == "IDENTICAL_4_OF_4"
    assert set(proof["per_symbol"]) == set(S.SYMBOL_UNIVERSE)
    assert len(manifest["files"]) == 63


@needs_data
def test_load_manifest_fails_closed_without_the_proof(tmp_path):
    bad = tmp_path / "manifest.json"
    bad.write_text(json.dumps({"files": {}, "cross_source_identity_proof": {"result": "NO"}}))
    with pytest.raises(Exception) as exc:
        D.load_manifest(tmp_path)
    assert "BLOCKED_DATA_AUTHORITY" in str(exc.value)


@needs_data
def test_the_2017_mirror_payload_equals_the_pr10_pinned_payload():
    """Re-proves admissibility from the raw bytes, not from the manifest."""
    import hashlib
    import zipfile

    def inner(path):
        with zipfile.ZipFile(path) as zf:
            name = next(n for n in zf.namelist() if n.endswith(".csv"))
            return name, hashlib.sha256(zf.read(name)).hexdigest()

    for symbol in S.SYMBOL_UNIVERSE:
        pinned = Path("data/external/histdata_fx_2017") / \
            f"HISTDATA_COM_ASCII_{symbol}_M1_2017.zip"
        if not pinned.exists():
            pytest.skip("PR #10 pinned archives absent")
        assert inner(pinned) == inner(D.archive_path(symbol, 2017))


@needs_data
def test_source_identity_mismatch_is_a_hard_stop(tmp_path):
    manifest = D.load_manifest()
    tampered = json.loads(json.dumps(manifest))
    tampered["files"]["EURUSD_2016"]["zip_sha256"] = "0" * 64
    with pytest.raises(Exception) as exc:
        D.verify_source_identity("EURUSD", 2016, tampered)
    assert "BLOCKED_DATA_AUTHORITY" in str(exc.value)


# ---------------------------------------------------------------------------
# 2. preregistration
# ---------------------------------------------------------------------------

def test_preregistration_hash_is_reproducible():
    a, b = M.preregistration(), M.preregistration()
    assert a["preregistration_hash"] == b["preregistration_hash"]


@needs_run
def test_committed_preregistration_matches_the_code():
    committed = json.loads((ART / "preregistration.json").read_text())
    assert committed["preregistration_hash"] == M.preregistration()["preregistration_hash"]
    assert committed["RULES_CHANGED"] == "NO"
    assert committed["DATASET_BINDING_CHANGED"] == "YES"
    assert committed["EXPECTED_RULE_HASH"] == M.EXPECTED_RULE_HASH
    assert committed["search_policy"]["parameter_optimization"] == "NO"
    assert committed["search_policy"]["trial_count"] == 0


def test_preregistration_reuses_existing_thresholds_unmodified():
    prereg = M.preregistration()
    suff = prereg["sample_sufficiency"]
    assert suff["POOLED_ENTRY_ELIGIBILITY_N"] == POOLED_ENTRY_ELIGIBILITY_N == 100
    assert suff["MIN_ENTERED_N"] == MIN_ENTERED_N == 30
    gate = prereg["pre_oos_gate_contract"]
    assert gate["threshold_mutation_allowed"] is False


def test_discovery_excludes_every_oos_and_holdout_window_with_a_reason():
    disc = M.data_authority_discovery()
    roles = {e["role"] for e in disc["EXCLUDED_WINDOWS"]}
    assert {"OOS", "SEALED_HOLDOUT"} <= roles
    for entry in disc["EXCLUDED_WINDOWS"]:
        assert entry["EXCLUSION_REASON"].strip()
    assert disc["permitted_symbol_years_n"] == 63
    assert all(w["role"] == "DEVELOPMENT" for w in disc["PERMITTED_DEV_WINDOWS"])
    known = [w for w in disc["PERMITTED_DEV_WINDOWS"] if w["family_status"] == "DEVELOPMENT_KNOWN"]
    assert {w["year"] for w in known} == {2017}, "only 2017 was previously consumed by the family"


def test_no_permitted_window_touches_september_or_later():
    for w in M.data_authority_discovery()["PERMITTED_DEV_WINDOWS"]:
        assert w["window_utc"][0].endswith("-01-01T00:00:00+00:00")
        assert w["window_utc"][1].endswith("-09-01T00:00:00+00:00")


# ---------------------------------------------------------------------------
# 3. attrition decomposition (mission section 5)
# ---------------------------------------------------------------------------

def test_every_frozen_rejection_reason_is_mapped_exactly_once():
    mapped = [r for rs in MA.TRIGGER_REASON_MAP.values() for r in rs] + \
             [r for rs in MA.CONFIRMATION_REASON_MAP.values() for r in rs]
    assert len(mapped) == len(set(mapped)), "a reason is mapped to two buckets"
    rejections = set(S.REJECT_REASONS) - {"PASS"}  # "PASS" is the non-rejection sentinel
    assert set(mapped) == rejections, f"unmapped: {sorted(rejections - set(mapped))}"


def test_attrition_is_never_collapsed_into_one_bucket():
    required_trigger = {"NEUTRAL_DIRECTION", "DIRECTION_SWEEP_MISMATCH", "NO_ASIAN_SWEEP",
                        "NO_RECLAIM", "SESSION_EXPIRED", "OTHER_DEFINED_REASON"}
    required_conf = {"NO_DISPLACEMENT", "NO_MSS_BOS", "NO_FVG", "NO_FVG_RETRACE",
                     "TEMPORAL_INVALID"}
    assert required_trigger == set(MA.TRIGGER_REASON_MAP)
    assert required_conf <= set(MA.CONFIRMATION_REASON_MAP)
    assert "TRIGGER_FAIL" not in MA.TRIGGER_REASON_MAP


def _unit(symbol="EURUSD", day="2016-03-01", session="ASIAN_LONDON", reason="PASS",
          node=None, stages=None, management_r=None):
    u = S.CandidateUnit(symbol=symbol, day=day, session=session,
                        candidate_id=f"{symbol}|{day}|{session}")
    u.reject_reason = reason
    u.reject_node = node
    u.stages = stages or {}
    u.management_r = management_r
    u.quarter = f"{day[:4]}Q1"
    return u


def test_attrition_reconciles_mapped_counts_against_the_raw_vocabulary():
    units = [
        _unit(reason="DIRECTION_NEUTRAL", node="T3_DIRECTION_NON_NEUTRAL"),
        _unit(day="2016-03-02", reason="NO_CLOSE_BACK_INSIDE", node="T5_CLOSE_BACK_INSIDE"),
        _unit(day="2016-03-03", reason="NO_MSS_BOS_AFTER_DISPLACEMENT", node="C2_MSS_BOS"),
        _unit(day="2016-03-04", reason="RIGHT_CENSORED_DATA_BOUNDARY", node="C6_ENTRY_AVAILABLE"),
    ]
    out = MA.attrition_decomposition(units)
    assert out["reconciliation_ok"] is True
    assert out["unmapped_reasons"] == []
    assert out["trigger_failures"]["NEUTRAL_DIRECTION"]["n"] == 1
    assert out["trigger_failures"]["NO_RECLAIM"]["n"] == 1
    assert out["confirmation_failures"]["NO_MSS_BOS"]["n"] == 1
    assert out["confirmation_failures"]["TEMPORAL_INVALID"]["n"] == 1
    assert [s["stage"] for s in out["stages"]][:2] == \
        ["T1_ASIAN_REFERENCE_VALID", "T2_DIRECTION_DECIDED"]


# ---------------------------------------------------------------------------
# 4. sample classification (mission sections 8/10/11)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pooled,cells,gate,expected", [
    (120, {"EURUSD|ASIAN_LONDON": 40}, "PASS", "SUFFICIENT_SAMPLE_NOW"),
    (120, {"EURUSD|ASIAN_LONDON": 40}, "NOT_REACHED", "NARROW_DATA_STARVATION"),
    (100, {"EURUSD|ASIAN_LONDON": 1}, "FAIL", "NARROW_DATA_STARVATION"),
    (60, {"EURUSD|ASIAN_LONDON": 31, "GBPUSD|ASIAN_LONDON": 2}, "NOT_REACHED", "MIXED"),
    (60, {"EURUSD|ASIAN_LONDON": 29, "GBPUSD|ASIAN_LONDON": 2}, "NOT_REACHED",
     "STRATEGY_STRUCTURAL_STARVATION"),
    (0, {}, "NOT_REACHED", "STRATEGY_STRUCTURAL_STARVATION"),
])
def test_sample_classification_is_deterministic(pooled, cells, gate, expected):
    out = M.classify_sample(pooled, cells, gate)
    assert out["SAMPLE_CLASSIFICATION"] == expected
    assert out["SAMPLE_CLASSIFICATION"] in M.SAMPLE_CLASSIFICATIONS
    assert M.classify_sample(pooled, cells, gate) == out  # pure


def test_classification_boundaries_sit_exactly_on_the_frozen_thresholds():
    assert M.classify_sample(POOLED_ENTRY_ELIGIBILITY_N - 1, {}, "NOT_REACHED")[
        "SAMPLE_CLASSIFICATION"] == "STRATEGY_STRUCTURAL_STARVATION"
    assert M.classify_sample(POOLED_ENTRY_ELIGIBILITY_N, {}, "NOT_REACHED")[
        "SAMPLE_CLASSIFICATION"] == "NARROW_DATA_STARVATION"
    assert M.classify_sample(1, {"c": MIN_ENTERED_N}, "NOT_REACHED")[
        "SAMPLE_CLASSIFICATION"] == "MIXED"
    assert M.classify_sample(1, {"c": MIN_ENTERED_N - 1}, "NOT_REACHED")[
        "SAMPLE_CLASSIFICATION"] == "STRATEGY_STRUCTURAL_STARVATION"


def test_representativeness_is_a_range_test_not_a_ranking():
    pooled = {"CANDIDATE_N": 10000, "TRIGGER_PASS_N": 200, "CONFIRMATION_PASS_N": 20,
              "GEOMETRY_VALID_N": 10, "ENTRY_AVAILABLE_N": 10}
    inside = M.narrow_vs_multiyear(pooled, 40, {"2015": 0.5, "2016": 2.0, "2017": 1.0})
    assert inside["2017_representative"] is True
    outside = M.narrow_vs_multiyear(pooled, 40, {"2015": 2.0, "2016": 3.0, "2017": 0.1})
    assert outside["2017_representative"] is False
    assert inside["corpus_growth_x"] == 10.0


# ---------------------------------------------------------------------------
# 5. robustness extension
# ---------------------------------------------------------------------------

def test_multiyear_robustness_uses_a_real_calendar_year_axis():
    units = []
    for year in (2014, 2015, 2016):
        for i in range(5):
            u = _unit(day=f"{year}-0{i+1}-01", management_r=0.5)
            u.stages = {"C6_ENTRY_AVAILABLE": True}
            units.append(u)
    rep = MA.multiyear_robustness_report(units)
    axes = rep["axes"]
    assert axes["YEAR_STABILITY"]["substitution"] == "NONE — this is a true calendar-year axis"
    assert axes["YEAR_STABILITY"]["years_covered"] == ["2014", "2015", "2016"]
    assert "LEAVE_ONE_YEAR_OUT" in axes and "LEAVE_ONE_SYMBOL_OUT" in axes
    assert rep["multi_year_extension"]["years_n"] == 3


def test_robustness_axes_are_masked_while_the_sample_is_ineligible():
    units = []
    for i in range(5):
        u = _unit(day=f"2016-0{i+1}-01", management_r=1.0)
        u.stages = {"C6_ENTRY_AVAILABLE": True}
        units.append(u)
    rep = MA.multiyear_robustness_report(units)
    assert rep["eligibility"]["eligible"] is False
    for name in ("YEAR_STABILITY", "LEAVE_ONE_YEAR_OUT", "LEAVE_ONE_SYMBOL_OUT"):
        assert rep["axes"][name]["state"] == "NOT_RUN_INSUFFICIENT_SAMPLE"
        assert "provisional_state_if_eligible" in rep["axes"][name]


def test_leave_one_out_needs_the_frozen_fold_floor():
    units = []
    for i in range(10):
        u = _unit(day=f"2016-01-{i+1:02d}", management_r=1.0)
        u.stages = {"C6_ENTRY_AVAILABLE": True}
        units.append(u)
    axis = MA._leave_one_out_axis(units, lambda u: u.symbol)
    assert axis["min_fold_n"] == MA.STRATUM_MIN_N == 30
    assert axis["state"] == "INSUFFICIENT_SAMPLE"


# ---------------------------------------------------------------------------
# 6. governance guards
# ---------------------------------------------------------------------------

def _code_literals(module) -> set[str]:
    tree = ast.parse(Path(module.__file__).read_text())
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            d = ast.get_docstring(node, clean=False)
            if d is not None:
                docs.add(d)
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value not in docs}


def test_no_multiyear_module_imports_execution_or_broker_capability():
    forbidden = ("nautilus", "metatrader", "mt5", "broker", "order_send", "place_order")
    for module in (M, MA, D):
        tree = ast.parse(Path(module.__file__).read_text())
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        blob = " ".join(imported).lower()
        for token in forbidden:
            assert token not in blob, f"{module.__name__} imports {token}"


def test_the_only_partition_role_requested_in_code_is_development():
    """Structural check: every partition request names DEVELOPMENT.

    A substring scan is useless here because the discovery report has to *name*
    the OOS and holdout windows in order to declare them excluded.  What matters
    is that no call site ever asks the loader for them.
    """
    requesting = {"partition_bounds", "assert_partition_accessible", "load_year_dataset"}
    seen = 0
    for module in (M, MA, D):
        tree = ast.parse(Path(module.__file__).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in requesting or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                assert first.value == "DEVELOPMENT", f"{module.__name__} requests {first.value!r}"
                seen += 1
    assert seen, "no partition request found — the guard would be vacuous"
    # and the loader itself must admit exactly one role
    assert D.LOADABLE_ROLES == frozenset({"DEVELOPMENT"})


@needs_run
def test_all_required_artifacts_exist():
    missing = [n for n in REQUIRED_ARTIFACTS if not (ART / n).exists()]
    assert not missing, f"missing artifacts: {missing}"


@needs_run
def test_the_bulky_ledger_is_an_external_cas_pointer_only():
    assert not list(ART.glob("*.jsonl")), "the per-unit ledger must not be committed"
    assert not list(ART.glob("*.jsonl.gz"))
    manifest = json.loads((ART / "artifact_manifest.json").read_text())
    pointer = manifest["external_evidence_pointer"]["candidate_ledger"]
    assert len(pointer["sha256"]) == 64
    assert pointer["storage"].startswith("EXTERNAL")
    assert pointer["rows"] > 0


@needs_run
def test_manifest_hashes_match_every_committed_artifact():
    from ag_edgelab.data.fingerprint import sha256_file
    manifest = json.loads((ART / "artifact_manifest.json").read_text())
    for name, meta in manifest["files"].items():
        path = ART / name
        assert path.exists(), name
        assert sha256_file(path) == meta["sha256"], name


@needs_run
def test_final_report_states_the_mission_prohibitions():
    final = json.loads((ART / "final_report.json").read_text())
    assert final["OOS_OPENED"] == "NO"
    assert final["HOLDOUT_TOUCHED"] == "NO"
    assert final["PARAMETER_OPTIMIZATION"] == "NO"
    assert final["STRATEGY_RULES_CHANGED"] == "NO"
    assert final["RULES_CHANGED"] == "NO"
    assert final["BROKER_MUTATION"] == "NO"
    assert final["STRATEGY_EXECUTION_ADDED"] == "NO"
    assert final["ECONOMIC_EDGE"] == "NOT_ESTIMABLE"
    assert final["DATASET_ROLE"] == "DEVELOPMENT"
    assert final["STRATEGY_HASH"] == M.EXPECTED_RULE_HASH
    assert final["SEARCH_LEDGER"]["trial_count"] == 0
    assert final["SEARCH_LEDGER"]["years_ranked_or_selected"] == "NONE"
    assert final["SEARCH_LEDGER"]["cells_removed"] == "NONE"
    assert final["SAMPLE_CLASSIFICATION"] in M.SAMPLE_CLASSIFICATIONS
    assert final["STATUS"] in ("MULTIYEAR_DEV_INSUFFICIENT_SAMPLE", "DEV_REJECTED",
                               "PRE_OOS_FAILED", "FROZEN_PRE_OOS_CANDIDATE")


@needs_run
def test_no_numeric_friction_value_exists_anywhere_in_the_bundle():
    numeric_friction = re.compile(
        r'"(spread|commission|slippage|swap|funding)[a-z_]*"\s*:\s*-?[0-9]', re.IGNORECASE)
    for path in ART.iterdir():
        if path.is_file():
            hit = numeric_friction.search(path.read_text(encoding="utf-8", errors="ignore"))
            assert hit is None, f"{path.name}: {hit.group(0)}"


@needs_run
def test_every_dataset_access_recorded_is_development_only():
    binding = json.loads((ART / "dataset_binding.json").read_text())
    assert binding["OOS_OPENED"] == "NO" and binding["HOLDOUT_TOUCHED"] == "NO"
    for window in binding["data_authority_discovery"]["PERMITTED_DEV_WINDOWS"]:
        assert window["role"] == "DEVELOPMENT"
    final = json.loads((ART / "final_report.json").read_text())
    for start, end in final["DEV_WINDOWS"]:
        assert start.endswith("-01-01T00:00:00+00:00")
        assert end.endswith("-09-01T00:00:00+00:00")


@needs_run
def test_gate_cannot_pass_while_the_sample_is_ineligible():
    gate = json.loads((ART / "pre_oos_gate_result.json").read_text())
    rob = json.loads((ART / "robustness_report.json").read_text())
    if not rob["eligibility"]["eligible"]:
        assert gate["PRE_OOS_RESULT"] == "NOT_REACHED"
        assert gate["PRE_OOS_RESULT"] != "PASS"


@needs_run
def test_counts_agree_across_artifacts():
    final = json.loads((ART / "final_report.json").read_text())
    funnel = json.loads((ART / "funnel_report.json").read_text())
    attrition = json.loads((ART / "attrition_reasons.json").read_text())
    pooled = funnel["stage_matrix"]["POOLED"]
    assert final["OPPORTUNITY_N"] == pooled["CANDIDATE_N"] == attrition["CANDIDATE_N"]
    assert final["TRIGGER_PASS_N"] == pooled["TRIGGER_PASS"]
    assert final["ENTRY_AVAILABLE_N"] == pooled["ENTRY_AVAILABLE"]
    assert attrition["reconciliation_ok"] is True
    years = sum(r["OPPORTUNITY_N"] for r in final["YEAR_DISTRIBUTION"].values())
    assert years == final["OPPORTUNITY_N"], "year rows must partition the pooled population"


@needs_run
def test_the_comparison_against_the_2017_campaign_uses_the_committed_numbers():
    comp = json.loads((ART / "v1_narrow_vs_multiyear.json").read_text())
    narrow = json.loads((NARROW_ART / "final_report.json").read_text())
    for key in ("CANDIDATE_N", "TRIGGER_PASS_N", "CONFIRMATION_PASS_N", "GEOMETRY_VALID_N",
                "ENTRY_AVAILABLE_N"):
        assert comp["narrow_2017_dev"][key] == narrow[key], key


# ---------------------------------------------------------------------------
# 7. real-data reproduction (skipped without the pinned archives)
# ---------------------------------------------------------------------------

@needs_data
@pytest.mark.parametrize("symbol", ["EURUSD"])
def test_multiyear_path_reproduces_the_2017_campaign_unit_for_unit(symbol):
    """THE equivalence proof behind "only the data changed"."""
    ledger = NARROW_ART / "candidate_ledger.jsonl"
    if not ledger.exists():
        pytest.skip("single-year ledger not present in this checkout")
    import sys
    sys.path.insert(0, "scripts")
    from run_gen2_asian_liquidity_displacement_v1_dev import unit_row

    committed = {}
    for line in ledger.read_text().splitlines():
        rec = json.loads(line)
        if rec.get("record_type") == "CANDIDATE" and rec["symbol"] == symbol:
            committed[rec["candidate_id"]] = rec

    ds = M.load_year_dataset(symbol, 2017)
    mine = {r["candidate_id"]: r for r in (unit_row(u) for u in S.replay_symbol(ds))}
    assert set(mine) == set(committed)
    assert all(mine[k] == committed[k] for k in mine)


@needs_data
def test_a_year_loads_only_its_own_development_window():
    ds = M.load_year_dataset("EURUSD", 2013)
    for frame in ds.frames.values():
        for bar in frame:
            assert bar.timestamp.year == 2013
            assert bar.timestamp.month < 9, "a bar from the OOS/holdout months leaked in"
    assert ds.quality["dataset_role"] == "DEVELOPMENT"
    assert ds.quality["m1_duplicate_timestamps"] == 0


# --------------------------------------------------------------------------
# gap inventory, balanced panel and the sample-size projection
# --------------------------------------------------------------------------


@needs_run
def test_gap_inventory_covers_every_admitted_symbol_year_with_no_forward_fill():
    quality = json.loads((ART / "dataset_quality_report.json").read_text())
    binding = json.loads((ART / "dataset_binding.json").read_text())
    admitted = {f"{r['symbol']}_{r['year']}"
                for r in binding["new_binding"]["permitted_symbol_years"]}
    assert set(quality["symbol_years"]) == admitted
    assert quality["pooled"]["symbol_years"] == len(admitted)
    # the frozen M1 gate tolerates nothing, so the inventory must be clean
    assert quality["pooled"]["duplicate_timestamps_total"] == 0
    assert quality["pooled"]["ohlc_violations_total"] == 0
    assert "never forward filled" in quality["rule"]
    for key, row in quality["symbol_years"].items():
        assert row["bars"]["M15"] > 0, key
        assert 0.0 < row["m15_fill_ratio_vs_calendar"] <= 1.0, key


@needs_run
def test_coverage_shortfalls_are_disclosed_rather_than_silently_dropped():
    """A short symbol-year must stay in the pooled population."""
    quality = json.loads((ART / "dataset_quality_report.json").read_text())
    final = json.loads((ART / "final_report.json").read_text())
    worst = min(quality["symbol_years"].values(),
                key=lambda r: r["m15_fill_ratio_vs_calendar"])
    assert worst["m15_fill_ratio_vs_calendar"] < quality["pooled"]["max_fill_ratio"]
    import csv as _csv
    with (ART / "year_matrix.csv").open(newline="") as fh:
        years = {int(row["YEAR"]) for row in _csv.DictReader(fh)}
    assert worst["year"] in years, "a sparse symbol-year was dropped from the year matrix"
    assert final["DEV_SYMBOL_YEARS_N"] == quality["pooled"]["symbol_years"]


@needs_run
def test_balanced_panel_is_a_predeclared_coverage_fact_not_a_selection():
    final = json.loads((ART / "final_report.json").read_text())
    prereg = json.loads((ART / "preregistration.json").read_text())
    panel = final["BALANCED_PANEL"]
    assert [int(y) for y in panel["years"]] == list(
        prereg["data_authority"]["balanced_panel_years"])
    assert panel["selection_authority"].startswith("NONE")
    # the panel is a subset, never a replacement
    assert panel["counts"]["ENTRY_AVAILABLE_N"] <= final["ENTRY_AVAILABLE_N"]
    assert panel["counts"]["CANDIDATE_N"] < final["OPPORTUNITY_N"]
    # and it must not be used to upgrade the verdict
    assert panel["classification_on_panel_only"] == final["SAMPLE_CLASSIFICATION"]


@needs_run
def test_sufficiency_projection_extrapolates_sample_size_only():
    final = json.loads((ART / "final_report.json").read_text())
    proj = final["SUFFICIENCY_PROJECTION"]
    assert "only of SAMPLE SIZE" in proj["method"]
    panel = final["BALANCED_PANEL"]
    per_sy = panel["entries_per_symbol_year"]
    assert per_sy == pytest.approx(
        panel["counts"]["ENTRY_AVAILABLE_N"] / panel["symbol_years"], rel=1e-6)
    if final["ENTRY_AVAILABLE_N"] < 100:
        assert proj["symbol_years_needed_for_pooled_eligibility"] > final["DEV_SYMBOL_YEARS_N"]
        assert (proj["symbol_years_needed_for_every_cell_to_reach_the_30_entry_floor"]
                > proj["symbol_years_needed_for_pooled_eligibility"])
    # no performance figure may be projected
    blob = json.dumps(proj).lower()
    for forbidden in ("expectancy", "profit", "sharpe", "win_rate", "return"):
        assert forbidden not in blob


# --------------------------------------------------------------------------
# FINAL RETURN contract
# --------------------------------------------------------------------------


@needs_run
def test_final_return_carries_every_contract_field():
    block = json.loads((ART / "final_return.json").read_text())["FINAL_RETURN"]
    assert list(block) == list(MA.FINAL_RETURN_FIELDS), "field order/coverage drifted"
    assert not [k for k, v in block.items() if v is None or v == ""]


@needs_run
def test_final_return_values_are_copies_of_the_sealed_evidence():
    """No hand-typed number may enter the contract block."""
    final = json.loads((ART / "final_report.json").read_text())
    comparison = json.loads((ART / "v1_narrow_vs_multiyear.json").read_text())
    emitted = json.loads((ART / "final_return.json").read_text())["FINAL_RETURN"]
    assert emitted == MA.final_return_block(final, comparison)
    for key in ("OPPORTUNITY_N", "DIRECTIONAL_N", "TRIGGER_PASS_N", "CONFIRMATION_PASS_N",
                "GEOMETRY_VALID_N", "ENTRY_AVAILABLE_N", "STATUS", "NEXT",
                "SAMPLE_CLASSIFICATION", "PRE_OOS_RESULT"):
        assert emitted[key] == final[key], key
    assert emitted["2017_ENTRY_N"] == comparison["narrow_2017_dev"]["ENTRY_AVAILABLE_N"] == 3
    assert emitted["MULTIYEAR_ENTRY_N"] == comparison["multiyear"]["ENTRY_AVAILABLE_N"]
    assert emitted["MULTIYEAR_ENTRY_N"] == emitted["ENTRY_AVAILABLE_N"]
    for key in ("1R", "2R", "3R", "4R", "5R"):
        assert emitted[key] == final["CAPABILITY"][key], key


@needs_run
def test_final_return_prohibitions_are_hard_coded_not_observed():
    block = json.loads((ART / "final_return.json").read_text())["FINAL_RETURN"]
    for key, expected in MA.FINAL_RETURN_CONSTANTS.items():
        assert block[key] == expected == "NO", key
    # the block must refuse to be built if the evidence ever disagrees
    final = json.loads((ART / "final_report.json").read_text())
    comparison = json.loads((ART / "v1_narrow_vs_multiyear.json").read_text())
    for key in MA.FINAL_RETURN_CONSTANTS:
        tampered = dict(final, **{key: "YES"})
        with pytest.raises(ValueError, match=key):
            MA.final_return_block(tampered, comparison)


@needs_run
def test_final_return_funnel_is_monotonically_non_increasing():
    block = json.loads((ART / "final_return.json").read_text())["FINAL_RETURN"]
    ladder = [block[k] for k in ("OPPORTUNITY_N", "DIRECTION_DECIDABLE_N", "DIRECTIONAL_N",
                                 "TRIGGER_PASS_N", "CONFIRMATION_PASS_N", "GEOMETRY_VALID_N",
                                 "ENTRY_AVAILABLE_N")]
    assert ladder == sorted(ladder, reverse=True), ladder
    r = [block[k] for k in ("1R", "2R", "3R", "4R", "5R")]
    assert r == sorted(r, reverse=True), "R-ladder reach must be non-increasing"
    assert len(block["DEV_WINDOWS"]) == block["DEV_YEARS_N"]
    for start, end in block["DEV_WINDOWS"]:
        assert start.endswith("-01-01T00:00:00+00:00"), start
        assert end.endswith("-09-01T00:00:00+00:00"), end  # OOS months never loaded


@needs_run
def test_final_return_is_covered_by_the_artifact_manifest():
    from ag_edgelab.data.fingerprint import sha256_file
    manifest = json.loads((ART / "artifact_manifest.json").read_text())
    assert manifest["final_return_contract"] == "final_return.json"
    assert manifest["files"]["final_return.json"]["sha256"] == sha256_file(
        ART / "final_return.json")
