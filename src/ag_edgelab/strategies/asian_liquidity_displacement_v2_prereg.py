"""MISSION 3 PHASE 3 — preregistration for ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2.

Frozen and committed BEFORE a single V2 unit is replayed on the DEVELOPMENT
corpus. Everything a later result could tempt someone to move lives here:
rules, branch definitions, session clocks, entry/SL/target policy, expiry,
the sample floor, the robustness thresholds and the funnel taxonomy.

Nothing in this module may be edited after the preregistration commit. A
later change is a NEW preregistration with a NEW experiment id.
"""
from __future__ import annotations

from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.strategies import asian_liquidity_displacement_v2 as V2
from ag_edgelab.strategies.asian_liquidity_displacement_prereg import (
    BOOTSTRAP_CONFIDENCE,
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    POOLED_ENTRY_ELIGIBILITY_N,
    PRE_OOS_GATE_ID,
    STABILITY_MAX_RELATIVE_SPIKE,
    STABILITY_MIN_POSITIVE_FRACTION,
    STRATUM_MIN_N,
    pre_oos_gate_contract,
)

PREREG_ID = "GEN2_ASIAN_LIQUIDITY_DISPLACEMENT_V2_PREREGISTRATION"
PREREG_VERSION = "1.0.0"
EXPERIMENT_ID = "GEN2_ALD_V2_DEV_R1"

#: V1's closed evidence. Quoted so the V2 comparison cannot be renegotiated.
V1_CLOSED_EVIDENCE: dict[str, object] = {
    "experiment_id": "GEN2_ALD_V1_MULTIYEAR_DEV_R1",
    "strategy_hash": "28c4f52f2ef6b54977e407e0c5ce93ef4f9b41a7bced37327a4844d392669a94",
    "symbol_years": 63,
    "OPPORTUNITY_N": 26814,
    "TRIGGER_PASS_N": 441,
    "CONFIRMATION_PASS_N": 51,
    "GEOMETRY_VALID_N": 36,
    "ENTRY_AVAILABLE_N": 35,
    "capability": {"1R": 0.428571, "2R": 0.285714, "3R": 0.257143,
                   "4R": 0.057143, "5R": 0.0},
    "NATURAL_TARGET_MEDIAN_R": 1.003804,
    "SAMPLE_CLASSIFICATION": "STRATEGY_STRUCTURAL_STARVATION",
    "diagnoses": ["TRIGGER_FUNNEL_WEAKNESS", "CONFIRMATION_FUNNEL_WEAKNESS",
                  "TARGET_MODEL_MISMATCH"],
    "status": "CLOSED_EVIDENCE — readable, never modified, never re-tuned",
}

# ---------------------------------------------------------------------------
# Sample sufficiency — INHERITED UNCHANGED from EdgeLab. Not a V2 invention.
# ---------------------------------------------------------------------------

#: The mission's pass/fail line: pooled ENTRY_AVAILABLE_N must reach this.
SAMPLE_FLOOR = POOLED_ENTRY_ELIGIBILITY_N            # 100
#: Per-stratum (branch, symbol, session) minimum for a stratum to be judged.
BRANCH_MIN_N = STRATUM_MIN_N                         # 30

SAMPLE_GATE_RULE = (
    f"SAMPLE_GATE = PASS iff pooled ENTRY_AVAILABLE_N >= {SAMPLE_FLOOR}. "
    "Otherwise SAMPLE_GATE = FAIL and STATUS = DEV_REJECTED_INSUFFICIENT_SAMPLE. "
    "This floor is inherited unchanged from the EdgeLab verifier "
    "(POOLED_ENTRY_ELIGIBILITY_N) and was NOT chosen for V2. It may never be "
    "lowered after a result is seen; a short sample is a rejection, not a "
    "reason to move the line."
)


def sample_sufficiency_contract() -> dict:
    return {
        "SAMPLE_FLOOR": SAMPLE_FLOOR,
        "floor_applies_to": "pooled ENTRY_AVAILABLE_N across both branches",
        "BRANCH_MIN_N": BRANCH_MIN_N,
        "branch_rule": "a branch with fewer than BRANCH_MIN_N entries is reported as "
                       "BRANCH_UNDERPOWERED and is NEVER deleted, hidden or merged away",
        "rule": SAMPLE_GATE_RULE,
        "post_hoc_relaxation": "FORBIDDEN",
        "inherited_from": "asian_liquidity_displacement_prereg (V1 campaign, unchanged)",
    }


def robustness_contract() -> dict:
    """PRE_OOS_ROBUSTNESS_GATE_V1, unchanged. No V2-specific threshold exists."""
    return {
        "gate_id": PRE_OOS_GATE_ID,
        "unchanged_from_v1": True,
        "runs_only_if": f"pooled ENTRY_AVAILABLE_N >= {SAMPLE_FLOOR}",
        "required_axes": [
            "walk_forward", "year_stability", "symbol_stability",
            "session_stability", "branch_stability", "regime_stability",
            "tail_dependence", "bootstrap", "concentration",
        ],
        "thresholds": {
            "STABILITY_MIN_POSITIVE_FRACTION": STABILITY_MIN_POSITIVE_FRACTION,
            "STABILITY_MAX_RELATIVE_SPIKE": STABILITY_MAX_RELATIVE_SPIKE,
            "BOOTSTRAP_SAMPLES": BOOTSTRAP_SAMPLES,
            "BOOTSTRAP_SEED": BOOTSTRAP_SEED,
            "BOOTSTRAP_CONFIDENCE": BOOTSTRAP_CONFIDENCE,
            "STRATUM_MIN_N": STRATUM_MIN_N,
        },
        "v1_gate_contract": pre_oos_gate_contract(),
        "new_threshold_after_results": "FORBIDDEN",
    }


def funnel_taxonomy() -> dict:
    return {
        "stages_in_order": list(V2.STAGE_NODES),
        "outcome_nodes": list(V2.OUTCOME_NODES),
        "reject_reasons": list(V2.REJECT_REASONS),
        "reason_to_node": dict(V2.REASON_NODE),
        "reporting_rule": "for every transition report N, % of the previous stage and % of "
                          "the original opportunity population; never collapse a stage",
        "strata": ["branch", "symbol", "year", "session", "symbol x session", "regime"],
        "branches": list(V2.BRANCHES),
    }


def prohibitions() -> dict:
    return {
        "OOS_OPENED": "NO",
        "HOLDOUT_TOUCHED": "NO",
        "PARAMETER_OPTIMIZATION": "NO",
        "BROKER_MUTATION": "NO",
        "LIVE_EXECUTION": "NO",
        "EDGE_VERIFIED": "NO",
        "forbidden_actions": [
            "lowering V1's 0.70 displacement threshold because V1 starved",
            "optimizing risk/reward or any target multiple",
            "choosing the best symbol after seeing results",
            "choosing the best session after seeing results",
            "choosing or deleting a branch after seeing results",
            "using recent, OOS or holdout data to design V2",
            "relaxing the sample floor or any robustness threshold after a result",
            "claiming EDGE_VERIFIED or any economic profitability",
        ],
        "data_authority": "DEVELOPMENT partitions only, every one already classified "
                          "DEVELOPMENT_KNOWN for this candidate family",
    }


def preregistration(*, implementation_sha: str, base_commit: str,
                    dataset_authority: dict) -> dict:
    return {
        "prereg_id": PREREG_ID,
        "prereg_version": PREREG_VERSION,
        "experiment_id": EXPERIMENT_ID,
        "mission": "EDGELAB GEN2 MISSION 3 — V2 NEW HYPOTHESIS DESIGN",
        "task_class": "RESEARCH / GENERATION_2 / DEV_ONLY",
        "committed_before_any_v2_replay": True,
        "implementation_sha": implementation_sha,
        "base_commit": base_commit,
        "strategy": {
            "strategy_id": V2.STRATEGY_ID,
            "strategy_version": V2.STRATEGY_VERSION,
            "strategy_hash": V2.STRATEGY_HASH,
            "contract_hashes": V2.contract_hashes(),
            "full_contract": V2.strategy_contract(),
        },
        "architecture": V2.architecture_contract(),
        "session_clocks": V2.session_contract(),
        "entry_policy": V2.entry_contract(),
        "sl_policy": V2.sl_contract(),
        "target_policy": V2.target_contract(),
        "expiry_policy": V2.EXPIRY_POLICY,
        "duplicate_signal_policy": V2.DUPLICATE_SIGNAL_POLICY,
        "parameters": V2.parameter_contract(),
        "sample_sufficiency": sample_sufficiency_contract(),
        "robustness": robustness_contract(),
        "funnel_taxonomy": funnel_taxonomy(),
        "prohibitions": prohibitions(),
        "dataset_authority": dataset_authority,
        "v1_closed_evidence": V1_CLOSED_EVIDENCE,
        "comparison_plan": {
            "primary_question": "DID V2 SOLVE STRUCTURAL STARVATION?",
            "decision_rule": SAMPLE_GATE_RULE,
            "metrics_compared": [
                "opportunities", "event/trigger passes", "confirmations", "entries",
                "entry yield", "median natural R",
                "1R", "2R", "3R", "4R", "5R capability"],
            "comparison_authority": "DIAGNOSTIC ONLY — V2 is not optimized against V1 and "
                                    "V1 is never re-run, re-tuned or re-interpreted",
        },
        "mechanical_validation_before_freeze": (
            "V2's rules were validated on SYNTHETIC bars only (tests/test_gen2_ald_v2.py). "
            "No DEVELOPMENT unit was replayed, and no real V2 result existed, at the instant "
            "this preregistration was committed."),
    }


def preregistration_hash(payload: dict) -> str:
    return sha256_json(payload)
