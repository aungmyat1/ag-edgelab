"""Preregistration + frozen Pre-OOS Robustness Gate V1 binding for
ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1 (GENERATION 2, DEVELOPMENT-ONLY).

Everything in this module is written and committed BEFORE any DEV result is
produced.  The gate thresholds are NOT invented here: every numeric value is
BOUND BY REFERENCE to a constant that is already frozen in the accepted
EdgeLab V1 system, so that no threshold can be altered in response to the
observed results (mission section "DO NOT alter EdgeLab verifier thresholds").

Bound authorities
    ag_edgelab.analytics.diagnostic.DiagnosticPolicy
        min_sample_n = 30, over_filter_pass_pct = 10.0,
        poor_trigger_target_reach_pct = 20.0, ambitious_tp_reach_pct = 15.0,
        low_target_uplift_pp = 3.0, low_discrimination_delta_r = 0.03
    ag_edgelab.universal.fx_dev_campaign (frozen V0.3 root-cause thresholds)
        CONTINUATION_REACH_1R_MIN = 0.50, CONTINUATION_REACH_3R_MIN = 0.25,
        MIN_ENTERED_N = 30, MIN_DIRECTIONAL_N = 200
    ag_edgelab.optimization.stability.assess_parameter_stability
        min_positive_fraction = 0.6, max_relative_spike = 2.0
    ag_edgelab.statistics.bootstrap.bootstrap_expectancy_ci (95%, seeded)
    ag_edgelab.verification.regimes.classify_market_state (frozen v1)
"""

from __future__ import annotations

from ag_edgelab.analytics.diagnostic import DiagnosticPolicy
from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.optimization.stability import assess_parameter_stability
from ag_edgelab.statistics.bootstrap import bootstrap_expectancy_ci
from ag_edgelab.strategies.asian_liquidity_displacement_v1 import (
    CANDIDATE_FAMILY_ID,
    DISPLACEMENT_BODY_RANGE_MIN,
    STRATEGY_ID,
    STRATEGY_VERSION,
    SYMBOL_UNIVERSE,
    strategy_contract,
)
from ag_edgelab.universal.fx_dev_campaign import (
    CONTINUATION_REACH_1R_MIN,
    CONTINUATION_REACH_3R_MIN,
    MIN_DIRECTIONAL_N,
    MIN_ENTERED_N,
)

PREREG_ID = "GEN2_ASIAN_LIQUIDITY_DISPLACEMENT_V1_PREREGISTRATION"
PREREG_VERSION = "1.0.0"
PRE_OOS_GATE_ID = "PRE_OOS_ROBUSTNESS_GATE_V1"

_POLICY = DiagnosticPolicy()

# Frozen stability defaults, read from the accepted implementation signature.
STABILITY_MIN_POSITIVE_FRACTION = 0.6
STABILITY_MAX_RELATIVE_SPIKE = 2.0
BOOTSTRAP_SAMPLES = 5000
BOOTSTRAP_SEED = 20251005
BOOTSTRAP_CONFIDENCE = 0.95

# Sample eligibility for running the robustness battery at all.
POOLED_ENTRY_ELIGIBILITY_N = 100
STRATUM_MIN_N = _POLICY.min_sample_n          # 30 (frozen)

# NON-SELECTING parameter neighborhood. The centre 0.70 is FROZEN: whatever
# this diagnostic shows, the V1 threshold is NOT changed in this mission.
DISPLACEMENT_NEIGHBORHOOD = (0.60, 0.65, 0.70, 0.75, 0.80)


def pre_oos_gate_contract() -> dict:
    return {
        "gate_id": PRE_OOS_GATE_ID,
        "semantics": "FAIL_CLOSED — the gate PASSES only if every axis is PASS",
        "threshold_mutation_allowed": False,
        "eligibility": {
            "pooled_entry_available_n_min": POOLED_ENTRY_ELIGIBILITY_N,
            "stratum_min_n": STRATUM_MIN_N,
            "pooled_direction_n_min": MIN_DIRECTIONAL_N,
            "on_ineligible": "PRE_OOS_RESULT = NOT_REACHED (never a PASS)",
        },
        "structural_capability_floors": {
            "reach_1R_min": CONTINUATION_REACH_1R_MIN,
            "reach_3R_min": CONTINUATION_REACH_3R_MIN,
            "entry_n_min": MIN_ENTERED_N,
            "source": "frozen V0.3 root-cause thresholds in ag_edgelab.universal.fx_dev_campaign",
        },
        "axes": {
            "WALK_FORWARD": {
                "method": "chronological non-overlapping DEV folds (monthly test windows)",
                "pass_rule": f"fraction of folds with positive management expectancy >= {STABILITY_MIN_POSITIVE_FRACTION}",
                "min_fold_n": STRATUM_MIN_N,
            },
            "YEAR_STABILITY": {
                "method": (
                    "the committed FX authority covers ONE calendar year (2017); per "
                    "config/governance/data_authority_gap.json no multi-year partition exists. "
                    "Substitution declared in advance: INTRA_YEAR_SEGMENT_STABILITY over the "
                    "DEV calendar quarters (2017Q1, 2017Q2, 2017Q3-partial)."
                ),
                "pass_rule": f"fraction of qualifying quarters with positive management expectancy >= {STABILITY_MIN_POSITIVE_FRACTION}",
                "standing_limitation": "YEAR_COVERAGE_LIMITED_SINGLE_CALENDAR_YEAR_2017",
            },
            "SYMBOL_STABILITY": {
                "pass_rule": f"fraction of qualifying symbols with positive management expectancy >= {STABILITY_MIN_POSITIVE_FRACTION}",
                "universe": list(SYMBOL_UNIVERSE),
            },
            "SESSION_STABILITY": {
                "pass_rule": f"fraction of qualifying session pairs with positive management expectancy >= {STABILITY_MIN_POSITIVE_FRACTION}",
            },
            "REGIME_STABILITY": {
                "classifier": "ag_edgelab.verification.regimes.classify_market_state (frozen v1) applied to the D1 bar last closed before the entry-window open",
                "pass_rule": f"fraction of qualifying regime slices with positive management expectancy >= {STABILITY_MIN_POSITIVE_FRACTION}",
            },
            "TAIL_DEPENDENCE": {
                "method": "remove the single best trade; separately remove the best 5% of trades",
                "pass_rule": "pooled management expectancy stays strictly positive under BOTH removals",
            },
            "MEAN_MEDIAN_DIVERGENCE": {
                "pass_rule": "NOT (mean management R > 0 AND median management R < 0) — a positive mean carried entirely by tails fails",
            },
            "BOOTSTRAP_UNCERTAINTY": {
                "method": f"ag_edgelab.statistics.bootstrap.bootstrap_expectancy_ci(samples={BOOTSTRAP_SAMPLES}, seed={BOOTSTRAP_SEED}, confidence={BOOTSTRAP_CONFIDENCE})",
                "pass_rule": "95% CI lower bound of management expectancy R strictly > 0",
            },
            "PARAMETER_NEIGHBORHOOD": {
                "method": f"ag_edgelab.optimization.stability.assess_parameter_stability over displacement body/range in {list(DISPLACEMENT_NEIGHBORHOOD)} centred on {DISPLACEMENT_BODY_RANGE_MIN}",
                "selection_authority": "NONE — diagnostic only; the V1 threshold 0.70 is frozen and is NOT changed by this mission under any outcome",
                "pass_rule": f"stable == True (positive_fraction >= {STABILITY_MIN_POSITIVE_FRACTION} and relative_spike <= {STABILITY_MAX_RELATIVE_SPIKE})",
            },
            "FRICTION_READINESS": {
                "mode": "STRUCTURAL_DISCLOSURE",
                "pass_rule": (
                    "the friction authority state is explicitly recorded, economic metrics are "
                    "suppressed as NOT_ESTIMABLE_NO_FRICTION_AUTHORITY, and NO substitute value "
                    "(generic spread, $7/lot, fixed slippage, industry default) appears anywhere "
                    "in the evidence bundle"
                ),
                "note": "FRICTION_EDGE_VERIFICATION_READY = NO does not block STRUCTURAL research (mission section 13)",
            },
            "DATASET_ROLE_VALIDATION": {
                "pass_rule": "every dataset read is role=DEVELOPMENT, recorded in the dataset ledger; OOS_OPENED=NO; HOLDOUT_TOUCHED=NO",
            },
            "CANDIDATE_IDENTITY_VALIDATION": {
                "pass_rule": "all contract hashes recomputed and equal; strategy identity collides with no historical candidate id",
            },
        },
    }


def root_cause_contract() -> dict:
    """Preregistered first-weak-point decision order (mission section 8)."""
    return {
        "labels": [
            "TRIGGER_FUNNEL_WEAKNESS",
            "CONFIRMATION_FUNNEL_WEAKNESS",
            "TARGET_MODEL_MISMATCH",
            "TARGET_CONTINUATION_WEAKNESS",
            "INSUFFICIENT_SAMPLE",
            "TEMPORAL_INCOMPATIBILITY",
        ],
        "decision_order": [
            {
                "label": "INSUFFICIENT_SAMPLE",
                "rule": f"pooled TRIGGER_INPUT < {MIN_DIRECTIONAL_N} or pooled ENTRY_AVAILABLE_N < {MIN_ENTERED_N}",
                "priority": 1,
                "note": "reported first as a measurement-capability statement, but the funnel stage that produced the starvation is still named",
            },
            {
                "label": "TEMPORAL_INCOMPATIBILITY",
                "rule": (
                    "the dominant rejection reason among TRIGGER-passing candidates is a "
                    "window-bounded failure (NO_MSS_BOS_AFTER_DISPLACEMENT, NO_FRESH_FVG_AFTER_MSS, "
                    "NO_CAUSAL_RETRACE_INTO_FVG) AND the median number of M15 bars remaining in the "
                    "entry window after the reclaim bar is below the number of sequential events the "
                    "contract still requires"
                ),
                "priority": 2,
            },
            {
                "label": "TRIGGER_FUNNEL_WEAKNESS",
                "rule": (
                    f"opportunity-basis reach of the maximum measured target among TRIGGER-passing "
                    f"candidates <= {_POLICY.poor_trigger_target_reach_pct} pct, i.e. the selected "
                    "population never had the capability that confirmation is being asked to find"
                ),
                "priority": 3,
            },
            {
                "label": "CONFIRMATION_FUNNEL_WEAKNESS",
                "rule": (
                    f"a CONFIRMATION node passes <= {_POLICY.over_filter_pass_pct} pct of its input "
                    f"while its target uplift vs input is <= {_POLICY.low_target_uplift_pp} pp "
                    "(attrition without selection value)"
                ),
                "priority": 4,
            },
            {
                "label": "TARGET_MODEL_MISMATCH",
                "rule": (
                    "median natural_target_R < 1.0 or the TP1/TP2 structural model is unreachable "
                    f"for > {100.0 - _POLICY.ambitious_tp_reach_pct} pct of entries while 1R capability "
                    f"is healthy (>= {CONTINUATION_REACH_1R_MIN})"
                ),
                "priority": 5,
            },
            {
                "label": "TARGET_CONTINUATION_WEAKNESS",
                "rule": (
                    f"1R capability >= {CONTINUATION_REACH_1R_MIN} but 3R capability < "
                    f"{CONTINUATION_REACH_3R_MIN} (frozen V0.3 continuation-collapse rule)"
                ),
                "priority": 6,
            },
        ],
        "upstream_principle": (
            "If confirmation optimization cannot produce viable target capability, the TRIGGER "
            "weakness is diagnosed FIRST and no further confirmation filters are added."
        ),
    }


def preregistration(*, implementation_sha: str, base_commit: str) -> dict:
    contract = strategy_contract()
    doc = {
        "preregistration_id": PREREG_ID,
        "preregistration_version": PREREG_VERSION,
        "mission": "ARENA RESEARCH GENERATION 2 — FX SESSION CANDIDATE V1 (6h dev-only sprint)",
        "task_class": "STRATEGY_RESEARCH / GENERATION_2 / DEVELOPMENT_ONLY",
        "candidate_family_id": CANDIDATE_FAMILY_ID,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "base_commit": base_commit,
        "implementation_sha": implementation_sha,
        "authority_gate": {
            "SYSTEM_SOFTWARE_COMPLETE": "YES",
            "RESEARCH_GENERATION_2_ALLOWED": "YES",
            "OOS_ECONOMIC_AUTHORIZED": "NO",
            "HOLDOUT_AUTHORIZED": "NO",
            "LIVE_EXECUTION_AUTHORIZED": "NO",
            "evidence": "data/artifacts/edgelab_system_completion_v1/system_readiness.json",
        },
        "prohibitions": {
            "OOS_OPEN": "FORBIDDEN",
            "HOLDOUT_OPEN": "FORBIDDEN",
            "BROKER_EXECUTION": "FORBIDDEN",
            "VERIFIER_THRESHOLD_MUTATION": "FORBIDDEN",
            "OPTUNA_OR_GRID_SEARCH": "FORBIDDEN",
            "SESSION_WINDOW_SEARCH": "FORBIDDEN",
            "RR_SEARCH": "FORBIDDEN",
            "POST_HOC_SYMBOL_OR_RULE_SELECTION": "FORBIDDEN",
        },
        "search_policy": {
            "hypotheses_evaluated": 1,
            "frozen_hypothesis": "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1 as specified in strategy_contract.json",
            "allowed": ["diagnostic comparisons defined by the Universal Funnel Analyzer",
                        "non-selecting parameter-neighborhood robustness diagnostic"],
            "optimizer_runs": 0,
            "trial_count": 0,
            "on_failure": "REJECT — a V2 hypothesis may only be designed later under a NEW preregistration",
        },
        "dataset_contract": {
            "authority": "HISTDATA_ASCII_M1_2017_PR10_PINNED",
            "allowed_roles": ["DEVELOPMENT"],
            "forbidden_roles": ["OOS", "SEALED_HOLDOUT", "RECENT_UNPARTITIONED"],
            "development_window_utc": contract["development_partition_utc"],
            "pinned_source_sha256": contract["pinned_source_sha256"],
            "contamination_registry": "config/governance/candidate_contamination_registry.json",
            "contamination_check": "candidate-family freshness is checked BEFORE any read",
            "ledger": "data/artifacts/gen2_asian_liquidity_displacement_v1/candidate_ledger.jsonl",
        },
        "strategy_contract": contract,
        "pre_oos_gate": pre_oos_gate_contract(),
        "root_cause_contract": root_cause_contract(),
        "outputs": [
            "preregistration.json", "strategy_contract.json", "candidate_ledger.jsonl",
            "funnel_report.json", "trigger_analysis.json", "confirmation_analysis.json",
            "target_capability.json", "continuation_survival.json", "temporal_diagnostics.json",
            "per_symbol_session_matrix.csv", "robustness_report.json", "pre_oos_gate_result.json",
            "candidate_freeze.json", "final_report.json", "final_report.md",
            "artifact_manifest.json",
        ],
        "terminal_states": ["FROZEN_PRE_OOS_CANDIDATE", "DEV_REJECTED", "PRE_OOS_FAILED",
                            "INSUFFICIENT_EVIDENCE"],
    }
    doc["preregistration_hash"] = sha256_json(
        {k: v for k, v in sorted(doc.items()) if k != "preregistration_hash"})
    return doc


__all__ = [
    "PREREG_ID", "PREREG_VERSION", "PRE_OOS_GATE_ID",
    "BOOTSTRAP_SAMPLES", "BOOTSTRAP_SEED", "BOOTSTRAP_CONFIDENCE",
    "POOLED_ENTRY_ELIGIBILITY_N", "STRATUM_MIN_N",
    "STABILITY_MIN_POSITIVE_FRACTION", "STABILITY_MAX_RELATIVE_SPIKE",
    "DISPLACEMENT_NEIGHBORHOOD",
    "pre_oos_gate_contract", "root_cause_contract", "preregistration",
    "assess_parameter_stability", "bootstrap_expectancy_ci",
]
