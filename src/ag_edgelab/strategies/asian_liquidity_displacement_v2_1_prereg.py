"""PREREGISTRATION — ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2 @ 2.1.0-research.

Mission 3A, Phase 10. Written and committed BEFORE any replay under this
contract. The commit that carries it contains no performance result.

Sample floor and robustness thresholds are RE-EXPORTED UNCHANGED from the V1
preregistration. They are not re-derived, not re-argued, and explicitly not
adjusted in the light of the GEN2_ALD_V2_DEV_R1 outcome.
"""
from __future__ import annotations

import hashlib

from ag_edgelab.data.fingerprint import canonical_json
from ag_edgelab.strategies import asian_liquidity_displacement_v2_1 as V
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

PREREG_ID = "GEN2_ALD_V2_1_PREREGISTRATION"
EXPERIMENT_ID = "GEN2_ALD_V2_1_DEV_R2"

#: UNCHANGED from V1. Re-exported, never re-derived.
SAMPLE_FLOOR = POOLED_ENTRY_ELIGIBILITY_N      # 100
BRANCH_MIN_N = STRATUM_MIN_N                   # 30

#: Dataset identity, pinned by hash. Recorded here so the binding is frozen
#: with the contract rather than discovered at replay time.
DATASET_AUTHORITY_ID = "HISTDATA_ASCII_M1_MULTIYEAR_R2"
DATASET_MANIFEST_SHA256 = (
    "14a85f854acf8856c46c4f2abc5031feded848f3400855c32548d5b57d1f949f")
DEV_PARTITION_HASH = (
    "f3d4b4299a3e653430473d8f9578e1e8a62847cb08a80db87b04155d5020b1d1")
DEV_WINDOW = "[Y-01-01T00:00:00+00:00, Y-09-01T00:00:00+00:00)"
DEV_SYMBOL_YEARS_N = 63
DEV_YEARS = tuple(range(2000, 2018))

V1_CLOSED_EVIDENCE = {
    "status": "DEV_REJECTED",
    "diagnosis": "STRATEGY_STRUCTURAL_STARVATION",
    "OPPORTUNITY_N": 26814,
    "TRIGGER_PASS_N": 441,
    "CONFIRMATION_PASS_N": 51,
    "ENTRY_AVAILABLE_N": 35,
    "SAMPLE_FLOOR": 100,
    "R1_REACH": 0.429,
    "R5_REACH": 0.0,
    "MEDIAN_NATURAL_TARGET_R": 1.004,
    "OOS_OPENED": "NO",
    "HOLDOUT_TOUCHED": "NO",
    "note": "Quoted, never recomputed. V1 is closed and must not be modified.",
}

V2_PROTOTYPE_CLOSED_EVIDENCE = {
    "experiment_id": "GEN2_ALD_V2_DEV_R1",
    "contract_version": "2.0.0-research",
    "status": "SUPERSEDED_BY_2.1.0",
    "why_superseded": (
        "Contract identity was incomplete (frozen fields could move without "
        "moving the hash), distances were not instrument-normalized, the "
        "branch sequences did not enforce strictly distinct bars, and "
        "duplicate governance was implicit. Those are identity and "
        "measurement defects, not unfavourable results."
    ),
    "note": (
        "Its numbers are NOT quoted here. They are deliberately excluded so "
        "that no magnitude in the 2.1.0 contract can be traced to them."
    ),
}


def contamination_disclosure() -> dict:
    """The honest statement about look order. Reported with any result."""
    return {
        "LOOK_INDEX": V.LOOK_INDEX,
        "statement": (
            "This contract was authored after a development replay of the "
            "2.0.0 prototype on the same DEVELOPMENT partition had been "
            "observed. Any result produced under 2.1.0 is therefore a SECOND "
            "look at the same data by the same researcher and cannot carry "
            "the evidential weight of a first look."
        ),
        "mitigations": [
            "Every magnitude is derived in PARAMETER_PROVENANCE from a "
            "mechanism, an existing clock, or a minimality argument.",
            "No R1 artifact was read or scanned while choosing any value.",
            "No value was varied to observe its effect.",
            "R1 numbers are deliberately not quoted in this preregistration.",
        ],
        "required_reporting": (
            "LOOK_INDEX must appear in the final return of any replay run "
            "under this contract."
        ),
        "does_not_apply_to": (
            "The sample floor and robustness thresholds, which are inherited "
            "unchanged from V1 and predate both V2 looks."
        ),
    }


def sample_sufficiency_contract() -> dict:
    return {
        "pooled_entry_available_n_min": SAMPLE_FLOOR,
        "branch_min_n": BRANCH_MIN_N,
        "source": "V1 preregistration, re-exported UNCHANGED",
        "on_failure": "DEV_REJECTED_INSUFFICIENT_SAMPLE",
        "relaxation_after_results": "FORBIDDEN",
        "note": (
            "Branches below BRANCH_MIN_N are flagged BRANCH_UNDERPOWERED and "
            "reported. A branch is NEVER deleted for being unprofitable."
        ),
    }


def robustness_contract() -> dict:
    return {
        "gate_id": PRE_OOS_GATE_ID,
        "thresholds_unchanged": True,
        "creation_of_a_v2_specific_threshold": "FORBIDDEN",
        "stability_min_positive_fraction": STABILITY_MIN_POSITIVE_FRACTION,
        "stability_max_relative_spike": STABILITY_MAX_RELATIVE_SPIKE,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_confidence": BOOTSTRAP_CONFIDENCE,
        "v1_gate_contract": pre_oos_gate_contract(),
    }


def prohibitions() -> tuple[str, ...]:
    return (
        "DO NOT modify V1 — it is closed evidence.",
        "DO NOT rewrite the GEN2_ALD_V2_DEV_R1 evidence bundle.",
        "DO NOT tune any magnitude after observing a result.",
        "DO NOT relax SAMPLE_FLOOR after observing a result.",
        "DO NOT create a V2-specific robustness threshold.",
        "DO NOT add a third branch.",
        "DO NOT delete a losing branch, symbol, session, year or regime.",
        "DO NOT choose the best symbol, session or branch after results.",
        "DO NOT open OOS. DO NOT open the sealed holdout.",
        "DO NOT assign unknown spread/slippage/commission/swap a value of 0.",
        "DO NOT claim EDGE_VERIFIED or economic profitability.",
        "DO NOT manufacture an R multiple when no natural target exists.",
        "DO NOT add a pip/point/ATR buffer to a structural stop.",
    )


def dataset_binding() -> dict:
    return {
        "authority_id": DATASET_AUTHORITY_ID,
        "role": "DEVELOPMENT",
        "dataset_manifest_sha256": DATASET_MANIFEST_SHA256,
        "dev_partition_hash": DEV_PARTITION_HASH,
        "dev_window": DEV_WINDOW,
        "dev_symbol_years_n": DEV_SYMBOL_YEARS_N,
        "dev_years": list(DEV_YEARS),
        "symbol_universe": list(V.__dict__.get("SYMBOL_UNIVERSE",
                                               ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD"))),
        "OOS_OPENED": "NO",
        "HOLDOUT_TOUCHED": "NO",
        "reserved_fresh_oos": "[Y-09-01, Y-12-01) — untouched",
        "sealed_holdout": "[Y-12-01, Y+1-01-01) — sealed",
    }


def dataset_binding_hash() -> str:
    return hashlib.sha256(
        canonical_json(dataset_binding()).encode("utf-8")).hexdigest()


def funnel_taxonomy() -> dict:
    return V.funnel_contract()


def preregistration() -> dict:
    """THE preregistration artifact."""
    return {
        "prereg_id": PREREG_ID,
        "experiment_id": EXPERIMENT_ID,
        "mission": "ARENA_EDGELAB_GEN2_MISSION_3A",
        "research_question": V.RESEARCH_QUESTION,
        "branches": [b.value for b in V.Branch],
        "third_branch": "FORBIDDEN",
        "strategy_contract": V.strategy_contract(),
        "contract_hash": V.contract_hash(),
        "contract_section_hashes": V.contract_hashes(),
        "dataset_binding": dataset_binding(),
        "dataset_binding_hash": dataset_binding_hash(),
        "sample_sufficiency": sample_sufficiency_contract(),
        "robustness": robustness_contract(),
        "funnel_taxonomy": funnel_taxonomy(),
        "contamination_disclosure": contamination_disclosure(),
        "v1_closed_evidence": V1_CLOSED_EVIDENCE,
        "v2_prototype_closed_evidence": V2_PROTOTYPE_CLOSED_EVIDENCE,
        "prohibitions": list(prohibitions()),
        "results_present": False,
        "replay_started": False,
        "declaration": (
            "Frozen before any replay under contract 2.1.0. Changing any "
            "frozen field changes contract_hash and invalidates this "
            "preregistration; a new one must then be written and committed "
            "before replay."
        ),
    }


def preregistration_hash() -> str:
    return hashlib.sha256(
        canonical_json(preregistration()).encode("utf-8")).hexdigest()
