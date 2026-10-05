from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "config" / "governance"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_v2_and_v21_ledger_records_exist():
    ledger = _load(GOV / "candidate_ledger.json")
    records = {record["CANDIDATE_ID"]: record for record in ledger["records"]}

    assert "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2@2.0.0-research" in records
    assert "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2@2.1.0-research" in records


def test_v2_ledger_record_preserves_failed_pre_oos_verdict():
    ledger = _load(GOV / "candidate_ledger.json")
    v2 = next(record for record in ledger["records"]
              if record["CANDIDATE_ID"] == "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2@2.0.0-research")

    assert v2["STATUS"] == "V2_DEV_SAMPLE_SUFFICIENT_PRE_OOS_FAILED"
    assert v2["PRE_OOS_RESULT"] == "FAIL"
    assert v2["OOS_ROLE"] == "NOT_CONSUMED"
    assert v2["HOLDOUT_TOUCHED"] == "NO"


def test_v21_ledger_record_remains_blocked_without_replay():
    ledger = _load(GOV / "candidate_ledger.json")
    v21 = next(record for record in ledger["records"]
               if record["CANDIDATE_ID"] == "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2@2.1.0-research")
    assert v21["STATUS"] == "BLOCKED_CONTRACT_AMBIGUITY"
    assert v21["OOS_ROLE"] == "NOT_CONSUMED"
    assert v21["HOLDOUT_TOUCHED"] == "NO"
    assert v21["REAL_HISTORICAL_REPLAY_EXECUTED"] is False


def test_r1_ledger_records_retain_semantic_identity_to_062265c():
    base = json.loads(subprocess.run(
        ["git", "show", "062265cc1e773d1f6762c9ac64f2e7fdd9f7e86f:config/governance/candidate_ledger.json"],
        cwd=ROOT, check=True, capture_output=True, text=True).stdout)
    current = _load(GOV / "candidate_ledger.json")
    current_records = {record["CANDIDATE_ID"]: record for record in current["records"]}
    for original in base["records"]:
        assert current_records[original["CANDIDATE_ID"]] == original


def test_oos_log_stays_exactly_two_events_and_sealed_holdout():
    oos = _load(GOV / "oos_access_log.json")
    assert [event["event_id"] for event in oos["events"]] == ["OOS-001", "OOS-002"]
    assert all("ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2" not in event["candidate_id"] for event in oos["events"])


def test_holdout_policy_remains_sealed_and_unopened():
    oos = _load(GOV / "oos_access_log.json")
    assert oos["dataset_registry"]["HISTDATA_ASCII_M1_2017_PR10_PINNED"]["holdout_policy"].startswith("SEALED")
    assert all(event["holdout_touched"] is False for event in oos["events"])


def test_contamination_registry_preserves_development_only_status():
    registry = _load(GOV / "candidate_contamination_registry.json")
    base = json.loads(subprocess.run(
        ["git", "show", "cc6e4a3:config/governance/candidate_contamination_registry.json"],
        cwd=ROOT, check=True, capture_output=True, text=True).stdout)
    assert registry == base
    assert all(record["candidate_family_id"] == "ASIAN_LIQUIDITY_DISPLACEMENT" for record in registry["records"])
    assert "SEALED_HOLDOUT_OPENED" not in json.dumps(registry)


def test_r2_evidence_and_owner_decision_package_are_present():
    evidence = _load(ROOT / "config" / "consolidation" / "consolidation_r2ab_evidence_v2.json")
    assert evidence["mission_id"] == "EDGELAB_CONSOLIDATION_R2_AB"
    assert evidence["supersedes"] == "config/consolidation/consolidation_r2ab_evidence_v1.json"
    assert evidence["merge_commit"] == "cc6e4a3"
    assert evidence["v2_1_status"] == "BLOCKED_CONTRACT_AMBIGUITY"
    assert evidence["test_counts"] == {
        "collected": 1506, "passed": 1490, "failed": 0, "skipped": 16,
    }
    assert evidence["r2c_verifier_summary"] == "8/10 VERIFIED, 2 ABSENT (regenerable), 0/64 CAS materialized"

    owner = _load(GOV / "owner_decisions_r2.json")
    assert owner["status"] == "UNRESOLVED"
    assert {item["issue_id"] for item in owner["decisions"]} == {
        "AMB_1", "AMB_2", "AMB_3", "AMB_4", "SESSION_AUTHORITY_CONFLICT",
        "V2.1_KILL_RULE", "FRICTION_VENUE",
    }
    assert all(item["status"] == "UNRESOLVED" for item in owner["decisions"])

    cleanup = _load(ROOT / "config" / "consolidation" / "branch_cleanup_r2.json")
    assert cleanup["deletions_executed"] is False
    assert len(cleanup["proposed_deletion_commands"]) == 2


def test_external_artifact_summary_separates_pointer_and_cas_counts(capsys):
    import importlib.util

    script = ROOT / "scripts" / "verify_external_artifacts.py"
    spec = importlib.util.spec_from_file_location("verify_external_artifacts_r2", script)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)

    assert verifier.main([]) == 0
    assert "8/10 VERIFIED, 2 ABSENT (regenerable), 0/64 CAS materialized" in capsys.readouterr().out.splitlines()
