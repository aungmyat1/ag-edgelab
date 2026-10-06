"""A0 (R3-CLOSE): owner_decisions_r3.json must parse and every key must be
present.

The file records the OWNER RULINGS verbatim (RULING_R3_01/02/03 and the
causal-library mandate) plus the inputs later steps read: the frozen R3
thresholds, the policy bindings, and the 16 pending decision records.
It is NOT owner authorization of the R3 policy: every authorization flag
stays false and every decision's owner_answer stays null until the owner
explicitly rules.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "config" / "governance" / "owner_decisions_r3.json"

EXPECTED_RULINGS = {
    "RULING_R3_01", "RULING_R3_02", "RULING_R3_03", "CAUSAL_LIBRARY_MANDATE",
}

EXPECTED_THRESHOLDS = {
    "REFERENCE_COVERAGE_MIN": 0.90,
    "PARENT_PERCENTILE_MIN": 0.95,
    "MIN_PARENT_N": 30,
    "BOOTSTRAP_CLUSTER_UNIT": "OPPORTUNITY",
    "BOOTSTRAP_REPLICATES": 2000,
    "NULL_REPLICATES": 2000,
    "NULL_MASTER_SEED": 4030341158,
    "PRIMARY_DIRECTIONAL_NULL": "RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY",
    "ROBUSTNESS_DIRECTIONAL_NULL": "MATCHED_DIRECTION_FREQUENCY_NULL",
    "REFERENCE_ATR_PERIOD": 14,
    "REFERENCE_ATR_MULTIPLE": 1.0,
    "TARGET_R": 2.0,
    "MAX_HOLDING_M5_BARS": 72,
    "INTRABAR_TIE_POLICY": "CONSERVATIVE_STOP_FIRST",
    "REFERENCE_ENTRY": "FIRST_M5_OPEN_AT_OR_AFTER_T2",
    "T1_DIRECTION_AVAILABLE": "EVENT_M15_OPEN + 15 minutes",
    "T2_DECISION_TIME": "CONFIRMATION_M5_CLOSE",
    "PARENT_MASK": "CAUSAL_ENTRY_GEOMETRY_MASK_V1",
    "MAX_CHILDREN_PER_PARENT": 100,
    "BASELINE_T2_TIMING_POLICY": "UNRESOLVED_OWNER_DECISION",
    "PASS_REQUIREMENT": ("PARENT_PERCENTILE >= 0.95 AND DELTA_CLUSTER_CI95_LOW_R > 0 "
                         "AND REFERENCE_COVERAGE >= 0.90 AND PARENT_N >= 30"),
}

EXPECTED_DECISION_IDS = [f"R3_OD_{i:02d}" for i in range(1, 17)]
EXPECTED_STATUS = {d: "RECOMMENDED_FROZEN_IN_PROPOSAL" for d in EXPECTED_DECISION_IDS}
EXPECTED_STATUS["R3_OD_05"] = "UNRESOLVED_OWNER_CHOICE_REQUIRED"

CAUSAL_LIBRARY_MODULES = (
    "causal_time", "causal_entry_mask", "execution_semantics",
    "baseline_timing_policy", "directional_null_policy", "verdict_record",
)


def _load():
    return json.loads(DECISIONS.read_text(encoding="utf-8"))


def test_file_parses_with_required_top_level_keys():
    document = _load()
    for key in ("mission_id", "packet_version", "status", "owner",
                "policy_freeze_base", "policy_hash",
                "owner_r3_policy_authorized", "real_campaign_authorized",
                "owner_ratified_decisions", "owner_rulings", "thresholds",
                "decisions"):
        assert key in document, key


def test_owner_rulings_block_is_present_verbatim_and_complete():
    document = _load()
    rulings = document["owner_rulings"]
    assert set(rulings) == EXPECTED_RULINGS
    for ruling_id, record in rulings.items():
        assert record["ruling"].strip(), ruling_id  # verbatim text present
        assert record["source"].startswith("R3-CLOSE resume instruction"), ruling_id

    # RULING_R3_01 names the four protected files exactly.
    assert set(rulings["RULING_R3_01"]["applies_to"]) == {
        "config/governance/candidate_ledger.json",
        "config/governance/candidate_contamination_registry.json",
        "config/governance/oos_access_log.json",
        "config/governance/external_artifact_registry.json",
    }
    # The causal-library mandate names all six library modules.
    mandated = rulings["CAUSAL_LIBRARY_MANDATE"]["applies_to"]
    for module in CAUSAL_LIBRARY_MODULES:
        assert any(module in path for path in mandated), module


def test_every_threshold_key_is_present_with_the_frozen_value():
    document = _load()
    thresholds = document["thresholds"]
    assert set(thresholds) == set(EXPECTED_THRESHOLDS) | {"BASELINE_T2_TIMING_CANDIDATES"}
    for key, value in EXPECTED_THRESHOLDS.items():
        assert thresholds[key] == value, key
    # The baseline timing candidates are the three compared policies.
    assert set(thresholds["BASELINE_T2_TIMING_CANDIDATES"]) == {
        "EMPIRICAL_MATCHED_DELAY",
        "STRATIFIED_EMPIRICAL_MATCHED_DELAY",
        "FIXED_CAUSAL_DELAY_FROM_T1",
    }


def test_every_decision_is_present_and_awaits_the_owner():
    document = _load()
    decisions = document["decisions"]
    assert [d["decision_id"] for d in decisions] == EXPECTED_DECISION_IDS
    for decision in decisions:
        did = decision["decision_id"]
        assert decision["status"] == EXPECTED_STATUS[did], did
        assert decision["owner_answer"] is None, did
        assert decision["owner"] == "TBD", did
        for field in ("question", "recommended_value", "alternatives",
                      "evidence", "risk_if_wrong"):
            assert decision[field], f"{did}.{field}"


def test_no_authorization_is_manufactured():
    document = _load()
    assert document["owner_r3_policy_authorized"] is False
    assert document["real_campaign_authorized"] is False
    assert document["owner_ratified_decisions"] == 0
    assert document["thresholds"]["BASELINE_T2_TIMING_POLICY"] == "UNRESOLVED_OWNER_DECISION"


def test_policy_bindings_match_the_frozen_proposal():
    document = _load()
    assert document["policy_freeze_base"] == "252059ec84e76562e8ecb7115311f42bb62eac41"
    assert document["policy_hash"] == "69ba55e06b23f1ef5694ffdbb97b6a35983e6976ec0c8d6fe5d420c7a905dffa"
