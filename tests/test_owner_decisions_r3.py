import json
from pathlib import Path


OWNER_DECISIONS = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "governance"
    / "owner_decisions_r3.json"
)


def test_owner_decisions_r3_exact_values_and_keys():
    record = json.loads(OWNER_DECISIONS.read_text(encoding="utf-8"))

    assert record == {
        "record_id": "OWNER_DECISIONS_R3",
        "owner": "aungmyat1",
        "recorded_on": "2026-10-06",
        "base": "6d41f899",
        "owner_rulings": {
            "RULING_R3_01": "APPEND-ONLY DEFINITION (governance JSON): Allowed: new records; new keys inside existing records; syntactic changes required by those additions (e.g. trailing comma). Forbidden: changing or removing any existing value or key. PR #24 ledger diff conforms (two new r3_causal_audit_disposition keys; note text unchanged).",
            "RULING_R3_02": "PR #24 LEGACY-ROOT GRANDFATHER (one-time): The 4 files under artifacts/funnel_optimizer_v1_r3_causal_policy_freeze/ were authored on base 252059e before the legacy-freeze rule. They stay in place (moving would alter freeze_summary.json bytes bound to POLICY_HASH/VERDICT_RECORD_HASH). The layout-guard snapshot includes them. No further exceptions without a new ruling.",
            "RULING_R3_03": "BLOCKED-STEP PROTOCOL (all future missions): On a rule conflict: write docs/governance/rulings/PROPOSED_<id>.md (conflict, options, recommendation), SKIP only the blocked step, continue independent steps, and list proposals in the final report. Full-mission stop only for: pinned-hash mismatch, OOS/holdout/DEV_VALIDATION exposure, broker mutation, frozen-bytes change, test-count drop.",
            "RULING_R3_04": "PRECEDENCE: owner_decisions_r3.json values supersede any agent-authored proposal values. PR #24 proposal values PARENT_PERCENTILE_MIN=0.95 and MAX_CHILDREN_PER_PARENT=100 are SUPERSEDED by PARENT_ELIGIBILITY_MIN_PERCENTILE=0.90 and CHILD_TRIAL_BUDGET=20. Gate V2 PASS = percentile >= 0.90 AND day-clustered CI95 low of selection_delta > 0 AND reference coverage >= 0.90 AND parent N >= 30.",
            "RULING_R3_05": "BASELINE_T2_TIMING_POLICY = STRATIFIED_EMPIRICAL_MATCHED_DELAY (primary); FIXED_CAUSAL_DELAY_FROM_T1 and EMPIRICAL_MATCHED_DELAY are mandatory robustness runs; a verdict that flips across policies -> INSUFFICIENT_EVIDENCE.",
        },
        "owner_inputs": {
            "OWNER_APPROVAL_B": True,
            "DELETE_DUPLICATE_ARENA": True,
            "RANDOM_BASELINE_COUNT": 1000,
            "PARENT_ELIGIBILITY_MIN_PERCENTILE": 0.90,
            "DEV_SEARCH": {"start": "2011-01-01", "end": "2016-12-31"},
            "DEV_VALIDATION": {
                "start": "2018-01-01",
                "end": "2018-06-06",
                "status": "SEALED_OWNER_OPENS",
            },
            "CHILD_TRIAL_BUDGET": 20,
            "DEV_FRICTION_SCENARIO": "NONE",
        },
        "gate_v2": {
            "MIN_REFERENCE_COVERAGE": 0.90,
            "MIN_PARENT_N": 30,
            "CI_REQUIREMENT": "day-clustered CI95 low of selection_delta > 0",
        },
        "not_owner_decided": {
            "note": "Pending decision packet docs/OWNER_R3_CAUSAL_POLICY_DECISIONS.md (PR #24) remains PENDING except where superseded by R3_04/R3_05. Its recommended values are NOT owner decisions.",
            "authority_flags": {
                "EDGE_VERIFIED_AUTHORIZED": False,
                "OOS_AUTHORIZED": False,
                "DEV_VALIDATION_OPEN": False,
            },
        },
    }
    assert "PARENT_PERCENTILE_MIN" not in record
    assert "MAX_CHILDREN_PER_PARENT" not in record