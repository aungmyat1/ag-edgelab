"""CONSOLIDATION R1 governance locks.

These tests make the governance records self-enforcing:
- the permanent C3 rejection record cannot silently change;
- the OOS access log stays consistent with the candidate ledger and the
  pinned dataset identities, and no event ever intersects the sealed
  holdout;
- every externalized/in-tree evidence pointer still resolves to bytes
  matching its pinned sha256;
- the edge-status vocabulary and ticket contract keep their required
  shapes.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "config" / "governance"
CONS = ROOT / "config" / "consolidation"

C3_HASH = "5a485308841d1c5d2096e348665ef3f9b1f689c1ed4ce4b30385eeaf2c828112"
C3_PREREG = "ff49d6fa2e61131c7dd90539f51ca0700052bf7320a7f19bf41285edcf19cae7"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ledger():
    return _load(GOV / "candidate_ledger.json")


@pytest.fixture(scope="module")
def oos_log():
    return _load(GOV / "oos_access_log.json")


@pytest.fixture(scope="module")
def c3_record(ledger):
    recs = [r for r in ledger["records"]
            if r["CANDIDATE_ID"] == "TARGET_POLICY_C3_V1"]
    assert len(recs) == 1
    return recs[0]


# ---------------------------------------------------------------------------
# 1. the permanent C3 rejection record (mission section 7 — exact values)
# ---------------------------------------------------------------------------

def test_c3_rejection_record_exact_fields(c3_record):
    assert c3_record["CANDIDATE_HASH"] == C3_HASH
    assert c3_record["STATUS"] == "REJECTED_OOS"
    assert c3_record["EDGE_STATUS"] == "NO_EDGE"
    assert c3_record["FAILURE_STAGE"] == "STRUCTURAL_OOS"
    assert c3_record["OOS_VERDICT"] == "C_STRUCTURAL_GENERALIZATION_FAILS"
    assert c3_record["ECONOMIC_VERDICT"] == \
        "NOT_ESTIMABLE_NO_FRICTION_AUTHORITY"
    assert c3_record["OOS_WINDOW"] == \
        "2017-09-01T00:00:00Z to 2017-12-01T00:00:00Z"
    assert c3_record["OOS_ROLE"] == "CONSUMED"
    assert c3_record["RELATED_MODEL_SELECTION_REUSE"] == "FORBIDDEN"
    assert c3_record["HOLDOUT_TOUCHED"] == "NO"


def test_c3_rejection_record_matches_sealed_final_report(c3_record):
    report = _load(ROOT / "data" / "artifacts" / "target_policy_c3_v1_oos"
                   / "final_report.json")
    assert report["CANDIDATE_SHA256"] == c3_record["CANDIDATE_HASH"]
    assert report["OOS_STRUCTURAL_VERDICT"] == "C"
    assert report["STATUS"] == "STRUCTURAL_GENERALIZATION_FAILED"
    assert report["OOS_PREREGISTRATION_SHA256"] == C3_PREREG
    assert report["EDGE_VERIFIED"] == "FALSE"
    assert report["ECONOMIC_METRICS"] == \
        "NOT_ESTIMABLE_NO_FRICTION_AUTHORITY"
    assert report["HOLDOUT_TOUCHED"] == "NO"
    k = c3_record["key_results"]
    assert k["ENTRY_N"] == report["ENTRY_N"]
    assert k["FIRST_OBJECTIVE_REACHED_PCT_OOS"] == \
        report["FIRST_OBJECTIVE_REACH"]
    assert k["P_SECOND_GIVEN_FIRST_OOS"] == report["P_SECOND_GIVEN_FIRST"]
    assert k["RUNNER_EXTENDED_REACH_OOS"] == report["RUNNER_EXTENDED_REACH"]
    assert k["MEAN_STRUCTURAL_R_OOS"] == report["MEAN_STRUCTURAL_R"]
    assert k["MAX_STRUCTURAL_DRAWDOWN_R_OOS"] == \
        report["MAX_STRUCTURAL_DRAWDOWN_R"]
    for symbol in ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD"):
        assert k["per_symbol_verdicts"][symbol] == report[f"{symbol}_VERDICT"]
        assert k["per_symbol_verdicts"][symbol] == "C"


def test_c3_preregistration_hash_is_committed_value(c3_record):
    assert c3_record["preregistration"].find(C3_PREREG) > 0
    # the pinned preregistration file on disk still hashes to it
    import hashlib
    digest = hashlib.sha256(
        (ROOT / "data" / "artifacts" / "target_policy_c3_v1_oos"
         / "oos_preregistration.json").read_bytes()).hexdigest()
    assert digest == C3_PREREG


# ---------------------------------------------------------------------------
# 2. OOS access log (mission section 8)
# ---------------------------------------------------------------------------

def test_oos_log_has_exactly_the_two_recorded_events(oos_log):
    ids = [e["event_id"] for e in oos_log["events"]]
    assert ids == ["OOS-001", "OOS-002"]


def test_oos_log_events_match_pinned_dataset_identities(oos_log):
    from ag_edgelab.data.fx_histdata_2017 import PINNED_SOURCE_SHA256
    registry = oos_log["dataset_registry"]["HISTDATA_ASCII_M1_2017_PR10_PINNED"]
    assert registry["symbols"] == dict(PINNED_SOURCE_SHA256)
    for event in oos_log["events"]:
        assert event["dataset_hash"] == dict(PINNED_SOURCE_SHA256)


def test_oos_log_events_never_touch_sealed_holdout(oos_log):
    for event in oos_log["events"]:
        assert event["holdout_touched"] is False
        assert event["window"].startswith("2017-09-01T00:00:00Z")
        assert event["window"].endswith("2017-12-01T00:00:00Z")


def test_oos_log_cross_checks_candidate_ledger(oos_log, ledger):
    consumed = {r["CANDIDATE_ID"]: r for r in ledger["records"]
                if r.get("OOS_ROLE") == "CONSUMED"}
    event_candidates = {e["candidate_id"] for e in oos_log["events"]}
    # every log event's candidate is a consumed-record candidate...
    for cand in event_candidates:
        assert cand in consumed, cand
    # ...and every consumed record has a log event
    for cand in consumed:
        assert cand in event_candidates, cand


def test_oos_log_c3_event_fields(oos_log):
    event = [e for e in oos_log["events"]
             if e["candidate_id"] == "TARGET_POLICY_C3_V1"][0]
    assert event["candidate_hash"] == C3_HASH
    assert event["preregistration_hash"] == C3_PREREG
    assert event["verdict"].startswith("C — STRUCTURAL_GENERALIZATION_FAILS")
    assert event["commit"].startswith("21b3ebb")
    assert "OOS-001" in event.get("prior_consumption_disclosed", "")


# ---------------------------------------------------------------------------
# 3. evidence pointers (mission section 6)
# ---------------------------------------------------------------------------

def _verify_script():
    spec = importlib.util.spec_from_file_location(
        "verify_external_artifacts",
        ROOT / "scripts" / "verify_external_artifacts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_all_evidence_pointers_resolve_and_hash_match():
    mod = _verify_script()
    assert mod.main() == 0


def test_registry_covers_every_large_evidence_file():
    registry = _load(GOV / "external_artifact_registry.json")
    externalized = {a["artifact_id"] for a in registry["artifacts"]}
    in_tree = {a["artifact_id"] for a in registry["in_tree_pinned"]}
    assert "UNIVERSAL_FUNNEL_V0_5_TARGET_CANDIDATE_LEDGER" in externalized
    assert "UNIVERSAL_FUNNEL_V0_5_TARGET_LADDERS" in externalized
    # the sealed C3 OOS ledger is pinned in-tree
    assert "TARGET_POLICY_C3_V1_OOS_LEDGER" in in_tree
    for section in ("artifacts", "in_tree_pinned"):
        for art in registry[section]:
            for field in ("artifact_id", "sha256", "byte_size",
                          "schema_version", "producer_commit",
                          "candidate_id", "dataset_role",
                          "storage_location"):
                assert art[field], (section, art["artifact_id"], field)


def test_externalized_files_are_absent_from_tree():
    # the two externalized V0.5 ledgers must NOT be in the mainline tree
    assert not (ROOT / "data" / "artifacts" / "universal_funnel_v0_5_target"
                / "target_candidate_ledger.jsonl").exists()
    assert not (ROOT / "data" / "artifacts" / "universal_funnel_v0_5_target"
                / "target_ladders.jsonl").exists()


# ---------------------------------------------------------------------------
# 4. vocabulary + ticket contract (mission sections 12/13)
# ---------------------------------------------------------------------------

def test_edge_status_vocabulary_is_exact():
    vocab = _load(GOV / "edge_status_vocabulary.json")
    assert vocab["edge_status"].keys() == {
        "UNVERIFIED", "INSUFFICIENT_EVIDENCE", "NO_EDGE", "EDGE_VERIFIED"}
    for stage in ("RESEARCH_CANDIDATE", "DEV_REJECTED", "OOS_REJECTED",
                  "VERIFICATION_FAILED", "EDGE_VERIFIED"):
        assert stage in vocab["verification_lifecycle"]


def test_ledger_uses_only_vocabulary_edge_statuses(ledger):
    allowed = {"UNVERIFIED", "INSUFFICIENT_EVIDENCE", "NO_EDGE",
               "EDGE_VERIFIED"}
    for rec in ledger["records"]:
        assert rec["EDGE_STATUS"] in allowed, rec["CANDIDATE_ID"]


def test_ticket_contract_execution_disabled():
    contract = _load(GOV / "ticket_integration_contract.json")
    perms = contract["permissions_model"]
    assert perms["current_state"].startswith("EXECUTION_DISABLED")
    assert "allow_order_send=false" in perms["current_state"]
    for field in ("strategy_id", "strategy_version", "strategy_hash",
                  "edge_status", "verification_stage",
                  "verification_evidence_id", "dataset_authority",
                  "friction_authority"):
        assert field in contract["required_fields"]


def test_friction_gap_status_is_missing_without_invented_values():
    gap = _load(GOV / "friction_authority_gap.json")
    assert gap["STATUS"] == "FRICTION_AUTHORITY_MISSING"
    assert "never be invented" in gap["why_missing"] or \
        "never be invented" in json.dumps(gap["why_missing"])
    for symbol in ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD"):
        assert symbol in gap["required_evidence_contract_per_symbol"]


def test_data_authority_gap_records_crypto_contract_reviews():
    gap = _load(GOV / "data_authority_gap.json")
    assert gap["FX_STATUS"] == "SINGLE_YEAR_AUTHORITY_EXISTS"
    assert gap["CRYPTO_STATUS"].startswith("REAL_DATA_AUTHORITY_INSUFFICIENT")
    bybit = gap["crypto_coverage"]["real_data_efforts_reviewed"][
        "bybit_public_archives"]["contract_review"]
    assert bybit["missing_bars"].startswith("FAIL")
    assert bybit["checksum_provenance"].startswith("FAIL")
    assert bybit["causal_timestamp_semantics"].startswith("PASS")
    assert bybit["duplicate_candles"].startswith("PASS")
    assert bybit["funding_handling"].startswith("PASS")
    assert gap["crypto_coverage"]["real_data_efforts_reviewed"][
        "bybit_public_archives"]["merge_decision"].startswith("NOT MERGED")


# ---------------------------------------------------------------------------
# 5. canonical subsystems + integration graph (mission sections 3/4)
# ---------------------------------------------------------------------------

def test_all_ten_subsystems_have_one_authority():
    subs = _load(GOV / "canonical_subsystems.json")["subsystems"]
    expected = {
        "funnel_analyzer", "verification_authority", "r8_1_protections",
        "friction_framework", "dataset_acquisition", "fx_campaign_engine",
        "crypto_data_adapter", "content_addressed_evidence",
        "candidate_ledger", "oos_governance"}
    assert set(subs) == expected
    for name, sub in subs.items():
        assert sub["authority"], name
        assert sub["why"], name
    assert subs["crypto_data_adapter"]["authority"].startswith("NONE")


def test_integration_graph_classifies_every_inventory_branch():
    graph = _load(CONS / "integration_graph.json")
    inventory = _load(CONS / "branch_inventory.json")
    classified = {n["branch"] for n in graph["nodes"]}
    inventoried = {b["name"] for b in inventory["branches"]}
    assert classified == inventoried
    valid = {"CANONICAL", "SUPERSEDED", "PARTIALLY_REUSED", "INDEPENDENT",
             "MERGED"}
    for node in graph["nodes"]:
        assert node["classification"] in valid, node["branch"]
        assert "action" in node and "supersession" in node, node["branch"]
