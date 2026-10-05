"""GEN2_ALD_V1_MULTIYEAR_DEV_R1 — multi-year DEVELOPMENT evidence expansion.

The strategy is NOT touched.  Every rule — sessions, direction engine, sweep,
reclaim, displacement 0.70, MSS/BOS, strict FVG, first causal FVG retracement,
SL = sweep extreme, TP1 = opposite Asian boundary, TP2 = nearest valid H1
liquidity objective — is executed by importing
``ag_edgelab.strategies.asian_liquidity_displacement_v1`` unmodified.  This
module changes exactly one thing: the DATASET BINDING.

  RULES_CHANGED            = NO
  DATASET_BINDING_CHANGED  = YES

``STRATEGY_HASH`` covers the 2017 dataset binding, so the frozen rule hash
``EXPECTED_RULE_HASH`` must still reproduce byte for byte; ``assert_rule_identity``
enforces that and stops with STRATEGY_IDENTITY_MISMATCH otherwise.  The new
dataset binding lives in a separate EXPERIMENT identity
(``experiment_identity``), never by mutating the strategy contract.

``replay_symbol`` is reused as-is.  It reads
``fx_histdata_2017.partition_bounds("DEVELOPMENT")`` for a ``dev_end`` value
that ``_evaluate_unit`` accepts but never references (right-censoring is driven
purely by the M5 bars present in the supplied frames), so feeding it per-year
frames is exact.  ``tests/test_gen2_ald_v1_multiyear.py`` pins both facts: the
parameter is unused in the rule body, and a 2017 multi-year replay reproduces
the committed single-year campaign unit-for-unit.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.data.fx_histdata_multiyear import (
    AUTHORITY_ID,
    BALANCED_PANEL,
    COVERAGE,
    PARTITION_POLICY_ID,
    admitted_symbol_years,
    authority_contract,
    build_dev_frames,
    partition_bounds,
)
from ag_edgelab.strategies.asian_liquidity_displacement_prereg import (
    BOOTSTRAP_CONFIDENCE,
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    POOLED_ENTRY_ELIGIBILITY_N,
    PRE_OOS_GATE_ID,
    STRATUM_MIN_N,
    pre_oos_gate_contract,
    root_cause_contract,
)
from ag_edgelab.strategies.asian_liquidity_displacement_v1 import (
    CANDIDATE_FAMILY_ID,
    DISPLACEMENT_BODY_RANGE_MIN,
    STRATEGY_HASH,
    STRATEGY_ID,
    STRATEGY_VERSION,
    SYMBOL_UNIVERSE,
    TIMEFRAMES,
    VERIFIER_VERSION,
    SymbolDataset,
    _bars_hash,
    aggregate_m5,
    contract_hashes,
    friction_contract,
    session_contract,
    sl_contract,
    strategy_contract,
    target_contract,
    trigger_contract,
)
from ag_edgelab.universal.fx_dev_campaign import MIN_DIRECTIONAL_N, MIN_ENTERED_N

UTC = timezone.utc

EXPERIMENT_ID = "GEN2_ALD_V1_MULTIYEAR_DEV_R1"
EXPERIMENT_VERSION = "1.0.0"
PREREG_ID = "GEN2_ALD_V1_MULTIYEAR_DEV_R1_PREREGISTRATION"

#: Mission section 0 — the frozen rule hash this experiment must reproduce.
EXPECTED_RULE_HASH = "28c4f52f2ef6b54977e407e0c5ce93ef4f9b41a7bced37327a4844d392669a94"

#: The committed single-year campaign this experiment is compared against.
NARROW_CAMPAIGN = {
    "artifact_set": "GEN2_ASIAN_LIQUIDITY_DISPLACEMENT_V1",
    "dev_window_utc": ["2017-01-01T00:00:00+00:00", "2017-09-01T00:00:00+00:00"],
    "symbol_years": 4,
    "CANDIDATE_N": 1768,
    "TRIGGER_PASS_N": 42,
    "CONFIRMATION_PASS_N": 6,
    "GEOMETRY_VALID_N": 3,
    "ENTRY_AVAILABLE_N": 3,
}

SAMPLE_CLASSIFICATIONS = ("NARROW_DATA_STARVATION", "STRATEGY_STRUCTURAL_STARVATION",
                          "MIXED", "SUFFICIENT_SAMPLE_NOW")


class StrategyIdentityMismatch(RuntimeError):
    """Raised when the frozen V1 rule hash no longer reproduces."""


def assert_rule_identity() -> dict:
    """Mission section 0 — hard stop unless the frozen V1 identity reproduces."""
    recomputed = STRATEGY_HASH
    contract = strategy_contract()
    checks = {
        "strategy_id": contract["strategy_id"] == STRATEGY_ID == "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1",
        "strategy_version": contract["strategy_version"] == STRATEGY_VERSION == "1.0.0-research",
        "strategy_hash": recomputed == EXPECTED_RULE_HASH,
        "asian_reference_utc": session_contract()["asian_reference_utc"] == {"start_hour": 0, "end_hour": 6},
        "london_entry_utc": session_contract()["london_entry_utc"] == {"start_hour": 7, "end_hour": 10},
        "new_york_entry_utc": session_contract()["new_york_entry_utc"] == {"start_hour": 12, "end_hour": 15},
        "session_widening_forbidden": session_contract()["widening_allowed"] is False,
        "displacement_threshold": DISPLACEMENT_BODY_RANGE_MIN == 0.70,
        "symbol_universe": list(SYMBOL_UNIVERSE) == ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"],
    }
    if not all(checks.values()):
        failed = sorted(k for k, v in checks.items() if not v)
        raise StrategyIdentityMismatch(
            f"STOP = STRATEGY_IDENTITY_MISMATCH; failing checks={failed}; "
            f"expected rule hash {EXPECTED_RULE_HASH}, recomputed {recomputed}")
    return {"state": "PASS", "EXPECTED_RULE_HASH": EXPECTED_RULE_HASH,
            "recomputed_strategy_hash": recomputed, "checks": checks,
            "RULES_CHANGED": "NO"}


# ---------------------------------------------------------------------------
# data authority discovery (mission section 1)
# ---------------------------------------------------------------------------

def data_authority_discovery() -> dict:
    """PERMITTED / EXCLUDED windows for this candidate family, with reasons."""
    permitted = [
        {"symbol": s, "year": y,
         "window_utc": [partition_bounds("DEVELOPMENT", y)[0].isoformat(),
                        partition_bounds("DEVELOPMENT", y)[1].isoformat()],
         "role": "DEVELOPMENT",
         "family_status": ("DEVELOPMENT_KNOWN" if y == 2017 else "FRESH_DEVELOPMENT")}
        for s, y in admitted_symbol_years()
    ]
    years = sorted({y for _, y in admitted_symbol_years()})
    return {
        "authority_id": AUTHORITY_ID,
        "partition_policy_id": PARTITION_POLICY_ID,
        "AVAILABLE_CORPUS_START": f"{min(years)}-01-01T00:00:00+00:00",
        "AVAILABLE_CORPUS_END": f"{max(years) + 1}-01-01T00:00:00+00:00",
        "PERMITTED_DEV_WINDOWS": permitted,
        "permitted_symbol_years_n": len(permitted),
        "balanced_panel_years": list(BALANCED_PANEL),
        "EXCLUDED_WINDOWS": [
            {"window": "[YYYY-09-01, YYYY-12-01) for every admitted year",
             "role": "OOS",
             "EXCLUSION_REASON":
                 "RESERVED_FRESH_OOS — the annual partition policy inherited from PR #10 "
                 "reserves Sep-Nov of every year as out-of-sample. For 2017 that window is "
                 "additionally ALREADY CONSUMED (OOS-001 SESSION_TRADE_V2, OOS-002 "
                 "TARGET_POLICY_C3_V1, see oos_access_log.json). For every other year it is "
                 "FRESH and must stay fresh: loading it here would permanently destroy the only "
                 "multi-year out-of-sample evidence this repository can ever have. The loader "
                 "fails closed on it."},
            {"window": "[YYYY-12-01, YYYY+1-01-01) for every admitted year",
             "role": "SEALED_HOLDOUT",
             "EXCLUSION_REASON":
                 "SEALED — never opened by any recorded event; unsealing requires an explicit "
                 "governance mission that amends the holdout policy first."},
            {"window": "[2018-01-01, ...)", "role": "NOT_ACQUIRED",
             "EXCLUSION_REASON":
                 "NO_WHOLE_YEAR_ARCHIVE — the mirror publishes 2018 only as monthly fragments "
                 "and stops in October 2018; an incomplete year would not carry the same "
                 "calendar composition as the other DEV windows."},
            {"window": "XAUUSD [2000-01-01, 2009-01-01)", "role": "NOT_PUBLISHED",
             "EXCLUSION_REASON":
                 "PROVIDER_COVERAGE — HistData gold history begins in 2009, so the panel is "
                 "unbalanced before then. Reported as a coverage limitation, never backfilled."},
        ],
        "contamination_position": (
            "The 2017 DEV window is DEVELOPMENT_KNOWN for family "
            f"{CANDIDATE_FAMILY_ID} (registered after the first campaign) and is RE-USED here "
            "deliberately and disclosed: it is the baseline the expansion is measured against. "
            "All other DEV windows are fresh DEVELOPMENT and become DEVELOPMENT_KNOWN for this "
            "family once this mission completes. No window is relabelled."),
        "coverage_years": {s: list(v) for s, v in sorted(COVERAGE.items())},
    }


# ---------------------------------------------------------------------------
# experiment identity (mission section 2) — strategy identity unchanged
# ---------------------------------------------------------------------------

def experiment_identity(dev_partition_hash: str, dataset_manifest_sha256: str) -> dict:
    hashes = contract_hashes()
    binding = {
        "experiment_id": EXPERIMENT_ID,
        "experiment_version": EXPERIMENT_VERSION,
        "candidate_family_id": CANDIDATE_FAMILY_ID,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "strategy_hash": STRATEGY_HASH,
        "rule_version_bump": "NONE",
        "dataset_authority_id": AUTHORITY_ID,
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "dev_partition_hash": dev_partition_hash,
        "symbol_universe": list(SYMBOL_UNIVERSE),
        "timeframes": list(TIMEFRAMES),
        "session_contract_hash": hashes["session_contract_hash"],
        "friction_contract_hash": hashes["friction_contract_hash"],
        "verifier_version": VERIFIER_VERSION,
    }
    return {**binding, "experiment_identity_sha256": sha256_json(binding)}


# ---------------------------------------------------------------------------
# preregistration (mission section 3) — written BEFORE the replay
# ---------------------------------------------------------------------------

def sample_classification_contract() -> dict:
    """The deterministic A/B/C/D rule, fixed before any multi-year result."""
    return {
        "contract_id": "MULTIYEAR_SAMPLE_CLASSIFICATION_V1",
        "inputs": {
            "pooled_entry_n": "ENTRY_AVAILABLE_N over all permitted DEV windows, pooled",
            "cell_entry_n": "ENTRY_AVAILABLE_N per symbol x session cell (8 cells)",
        },
        "thresholds_bound_by_reference": {
            "POOLED_ENTRY_ELIGIBILITY_N": POOLED_ENTRY_ELIGIBILITY_N,
            "MIN_ENTERED_N": MIN_ENTERED_N,
            "STRATUM_MIN_N": STRATUM_MIN_N,
            "source": "ag_edgelab.strategies.asian_liquidity_displacement_prereg / "
                      "ag_edgelab.universal.fx_dev_campaign — unmodified",
        },
        "decision_order": [
            f"1. SUFFICIENT_SAMPLE_NOW  iff pooled_entry_n >= {POOLED_ENTRY_ELIGIBILITY_N} "
            "AND PRE_OOS_RESULT == PASS",
            f"2. NARROW_DATA_STARVATION iff pooled_entry_n >= {POOLED_ENTRY_ELIGIBILITY_N} "
            "(the corpus now yields an adequate entry population; 2017 was simply too small)",
            f"3. MIXED                  iff at least one symbol x session cell has "
            f"cell_entry_n >= {MIN_ENTERED_N} while the pooled population is below "
            f"{POOLED_ENTRY_ELIGIBILITY_N} (heterogeneous viability)",
            "4. STRATEGY_STRUCTURAL_STARVATION otherwise",
        ],
        "supporting_measure": {
            "entry_yield_per_1000_candidates": "ENTRY_AVAILABLE_N / CANDIDATE_N * 1000, per year",
            "representativeness_rule":
                "2017 is REPRESENTATIVE iff its per-year entry yield lies inside the "
                "[min, max] range of the other permitted years; if the yields are "
                "statistically indistinguishable the starvation is a property of the rules, "
                "not of the 2017 window",
        },
        "prohibited": [
            "ranking years and selecting the best",
            "removing weak symbol or session cells",
            "cherry-picking a profitable subset",
            "re-deriving any threshold from the observed multi-year result",
        ],
    }


def preregistration() -> dict:
    payload = {
        "preregistration_id": PREREG_ID,
        "experiment_id": EXPERIMENT_ID,
        "experiment_version": EXPERIMENT_VERSION,
        "task_class": "STRATEGY_RESEARCH / DEVELOPMENT_EVIDENCE_EXPANSION",
        "primary_objective": (
            "Determine whether the sample starvation observed in the first "
            "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1 campaign is caused primarily by the narrow "
            "2017 DEV window or by the frozen strategy rules themselves."),
        "RULES_CHANGED": "NO",
        "DATASET_BINDING_CHANGED": "YES",
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "EXPECTED_RULE_HASH": EXPECTED_RULE_HASH,
        "strategy_contract_hashes": contract_hashes(),
        "frozen_contracts_restated": {
            "session_contract": session_contract(),
            "trigger_contract_id": trigger_contract()["contract_id"],
            "sl_contract": sl_contract(),
            "target_contract_id": target_contract()["contract_id"],
            "friction_contract": friction_contract(),
            "displacement_body_range_min": DISPLACEMENT_BODY_RANGE_MIN,
        },
        "symbol_universe": list(SYMBOL_UNIVERSE),
        "sessions_evaluated": ["ASIAN_LONDON", "LONDON_NEWYORK", "POOLED"],
        "data_authority": authority_contract(),
        "data_authority_discovery": data_authority_discovery(),
        "sample_sufficiency": {
            "source": "existing EdgeLab thresholds, unmodified",
            "POOLED_ENTRY_ELIGIBILITY_N": POOLED_ENTRY_ELIGIBILITY_N,
            "MIN_ENTERED_N": MIN_ENTERED_N,
            "MIN_DIRECTIONAL_N": MIN_DIRECTIONAL_N,
            "STRATUM_MIN_N": STRATUM_MIN_N,
            "on_insufficient": "STATUS = MULTIYEAR_DEV_INSUFFICIENT_SAMPLE and the exact "
                               "responsible funnel stage is named; V2 design is NOT performed "
                               "in this mission and requires owner authorization",
        },
        "sample_classification_contract": sample_classification_contract(),
        "pre_oos_gate_contract": pre_oos_gate_contract(),
        "root_cause_contract": root_cause_contract(),
        "robustness_policy": {
            "runs_only_if": f"pooled ENTRY_AVAILABLE_N >= {POOLED_ENTRY_ELIGIBILITY_N}",
            "axes": ["WALK_FORWARD", "YEAR_STABILITY", "LEAVE_ONE_YEAR_OUT",
                     "SYMBOL_STABILITY", "LEAVE_ONE_SYMBOL_OUT", "SESSION_STABILITY",
                     "REGIME_STABILITY", "TAIL_DEPENDENCE", "BOOTSTRAP",
                     "MEAN_MEDIAN_DIVERGENCE", "PARAMETER_NEIGHBORHOOD"],
            "gate": PRE_OOS_GATE_ID,
            "threshold_mutation_allowed": False,
            "bootstrap": {"samples": BOOTSTRAP_SAMPLES, "seed": BOOTSTRAP_SEED,
                          "confidence": BOOTSTRAP_CONFIDENCE},
        },
        "economic_policy": {
            "ECONOMIC_EDGE": "NOT_ESTIMABLE",
            "reason": "measured friction authority remains incomplete "
                      "(config/governance/friction_authority_gap.json)",
            "forbidden_substitutions": ["generic spreads", "fixed commission",
                                        "invented slippage", "industry defaults"],
            "allowed": "structural target capability in R only",
        },
        "search_policy": {
            "optimizer": "NONE",
            "parameter_optimization": "NO",
            "trial_count": 0,
            "hypotheses_evaluated": 1,
            "note": "one frozen V1 hypothesis replayed on a wider DEV corpus; the only "
                    "comparisons are those defined by the funnel analyzer and by the "
                    "preregistered sample-classification contract",
        },
        "prohibitions": ["DO NOT design V2", "DO NOT change trigger/confirmation/target rules",
                         "DO NOT optimize parameters", "DO NOT open OOS", "DO NOT open holdout"],
    }
    return {**payload, "preregistration_hash": sha256_json(payload)}


# ---------------------------------------------------------------------------
# loading / replay (frozen rules, per-year dataset binding)
# ---------------------------------------------------------------------------

def load_year_dataset(symbol: str, year: int, data_dir=None) -> SymbolDataset:
    """One symbol-year DEVELOPMENT dataset, frozen derivation semantics."""
    frames, quality = build_dev_frames(symbol, year, aggregate_m5, data_dir)
    frame_hashes = {tf: _bars_hash(rows) for tf, rows in sorted(frames.items())}
    return SymbolDataset(symbol=symbol, source_sha256=quality.get("source_sha256", ""),
                         frames=frames, quality=quality, frame_hashes=frame_hashes)


def classify_sample(pooled_entry_n: int, cell_entry_n: dict[str, int],
                    pre_oos_result: str) -> dict:
    """Apply MULTIYEAR_SAMPLE_CLASSIFICATION_V1 exactly as preregistered."""
    viable_cells = sorted(k for k, v in cell_entry_n.items() if v >= MIN_ENTERED_N)
    starved_cells = sorted(k for k, v in cell_entry_n.items() if v < MIN_ENTERED_N)
    if pooled_entry_n >= POOLED_ENTRY_ELIGIBILITY_N and pre_oos_result == "PASS":
        label, rule = "SUFFICIENT_SAMPLE_NOW", "decision_order[1]"
    elif pooled_entry_n >= POOLED_ENTRY_ELIGIBILITY_N:
        label, rule = "NARROW_DATA_STARVATION", "decision_order[2]"
    elif viable_cells:
        label, rule = "MIXED", "decision_order[3]"
    else:
        label, rule = "STRATEGY_STRUCTURAL_STARVATION", "decision_order[4]"
    return {
        "SAMPLE_CLASSIFICATION": label,
        "applied_rule": rule,
        "contract_id": "MULTIYEAR_SAMPLE_CLASSIFICATION_V1",
        "pooled_entry_n": pooled_entry_n,
        "pooled_eligibility_required": POOLED_ENTRY_ELIGIBILITY_N,
        "cell_entry_n": dict(sorted(cell_entry_n.items())),
        "cell_floor": MIN_ENTERED_N,
        "viable_cells": viable_cells,
        "starved_cells": starved_cells,
        "pre_oos_result": pre_oos_result,
    }


def narrow_vs_multiyear(pooled_counts: dict, symbol_years: int,
                        per_year_yield: dict[str, float]) -> dict:
    """Mission section 10 — the explicit campaign comparison."""
    narrow = NARROW_CAMPAIGN
    others = {y: v for y, v in per_year_yield.items() if y != "2017"}
    y2017 = per_year_yield.get("2017")
    if others and y2017 is not None:
        lo, hi = min(others.values()), max(others.values())
        representative = lo <= y2017 <= hi
    else:
        lo = hi = None
        representative = None

    def ratio(key: str) -> float | None:
        base = narrow[key]
        return None if not base else round(pooled_counts[key] / base, 4)

    return {
        "narrow_2017_dev": {k: narrow[k] for k in
                            ("CANDIDATE_N", "TRIGGER_PASS_N", "CONFIRMATION_PASS_N",
                             "GEOMETRY_VALID_N", "ENTRY_AVAILABLE_N")},
        "narrow_symbol_years": narrow["symbol_years"],
        "multiyear": {k: pooled_counts[k] for k in
                      ("CANDIDATE_N", "TRIGGER_PASS_N", "CONFIRMATION_PASS_N",
                       "GEOMETRY_VALID_N", "ENTRY_AVAILABLE_N")},
        "multiyear_symbol_years": symbol_years,
        "corpus_growth_x": round(symbol_years / narrow["symbol_years"], 4),
        "growth_x": {k: ratio(k) for k in
                     ("CANDIDATE_N", "TRIGGER_PASS_N", "CONFIRMATION_PASS_N",
                      "GEOMETRY_VALID_N", "ENTRY_AVAILABLE_N")},
        "entry_yield_per_1000_candidates_by_year": dict(sorted(per_year_yield.items())),
        "yield_2017": y2017,
        "yield_other_years_range": [lo, hi],
        "2017_representative": representative,
        "interpretation_rule": (
            "if the 2017 entry yield sits inside the range spanned by the other years, the "
            "2017 window was a representative sample of the rule's behaviour and the "
            "starvation is a property of the rules"),
    }


def mission_metadata() -> dict:
    return {
        "mission": "GEN2 ASIAN LIQUIDITY DISPLACEMENT V1 — MULTI-YEAR DEV REPLAY",
        "experiment_id": EXPERIMENT_ID,
        "generated_contract_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
