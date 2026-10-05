#!/usr/bin/env python
"""MISSION 3B-A — emit the infrastructure evidence artifacts.

Phases 1 (implementation matrix), 3 (event governance validation),
4 (symbol normalization audit), 12 (synthetic determinism).

Synthetic fixtures only. No market corpus is read.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import canonical_json
from ag_edgelab.strategies import asian_liquidity_displacement_v2_1 as V
from ag_edgelab.strategies import symbol_metadata as SM
from ag_edgelab.strategies import v2_1_engine as E
from ag_edgelab.strategies import v2_1_funnel as F
from tests.fixtures_v2_1 import (  # noqa: E402
    SYNTHETIC_POLICY,
    build_scenarios,
    run_synthetic_engine,
)

OUT = Path("data/artifacts/gen2_ald_v2_1")
UTC = timezone.utc


# ---------------------------------------------------------------------------
# PHASE 1 — contract field -> implementation -> test -> replay output
# ---------------------------------------------------------------------------

MATRIX: tuple[dict, ...] = (
    {"contract_field": "branch_a.sweep_definition",
     "implementation": "v2_1.run_branch_a (BOUNDARY_UNTOUCHED->SWEEP_DETECTED)",
     "test": "test_branch_a_full_sequence_uses_three_distinct_increasing_bars",
     "replay_output": "transition_ledger[to_state=SWEEP_DETECTED]"},
    {"contract_field": "branch_a.min_sweep_geometry",
     "implementation": "v2_1.run_branch_a MIN_SWEEP_TICKS * meta.tick_size",
     "test": "test_branch_a_ignores_a_sub_tick_boundary_graze",
     "replay_output": "transition_ledger.reason_code=SWEEP_MIN_TICKS_MET"},
    {"contract_field": "branch_a.max_sweep_geometry",
     "implementation": "v2_1.run_branch_a MAX_SWEEP_RANGE_FRACTION",
     "test": "test_branch_a_rejects_a_sweep_deeper_than_the_reference_range",
     "replay_output": "reject_reason=SWEEP_GEOMETRY_EXCEEDED"},
    {"contract_field": "branch_a.reclaim_definition",
     "implementation": "v2_1.run_branch_a (RECLAIM_PENDING->RECLAIM_CONFIRMED)",
     "test": "test_branch_a_sweep_candle_can_never_be_the_reclaim_candle",
     "replay_output": "transition_ledger[to_state=RECLAIM_CONFIRMED]"},
    {"contract_field": "branch_a.reclaim_max_bars",
     "implementation": "v2_1.run_branch_a budget_end = sweep+1+RECLAIM_MAX_BARS",
     "test": "test_branch_a_reclaim_timeout",
     "replay_output": "reject_reason=RECLAIM_TIMEOUT"},
    {"contract_field": "branch_a.mss_definition",
     "implementation": "injected mss_confirmed_at, driven by run_branch_a",
     "test": "test_branch_a_reclaim_candle_can_never_be_the_mss_candle",
     "replay_output": "transition_ledger[to_state=MSS_CONFIRMED]"},
    {"contract_field": "branch_a.mss_lookback_bars",
     "implementation": "v2_1.run_branch_a budget_end = reclaim+1+MSS_LOOKBACK_BARS",
     "test": "test_branch_a_mss_timeout",
     "replay_output": "reject_reason=MSS_TIMEOUT"},
    {"contract_field": "branch_a.entry_definition",
     "implementation": "v2_1.run_branch_a entry_price = confirming bar close",
     "test": "test_branch_a_full_sequence_uses_three_distinct_increasing_bars",
     "replay_output": "trade_ledger.entry_price / entry_timestamp"},
    {"contract_field": "branch_a.stop_definition",
     "implementation": "v2_1.run_branch_a sweep_extreme (no buffer)",
     "test": "test_branch_a_stop_tracks_the_deepest_excursion_not_just_the_sweep_bar",
     "replay_output": "trade_ledger.stop_price"},
    {"contract_field": "branch_b.breakout_definition",
     "implementation": "v2_1.run_branch_b (BOUNDARY_UNTOUCHED->BREAKOUT_DETECTED)",
     "test": "test_branch_b_full_sequence_acceptance_precedes_retest",
     "replay_output": "transition_ledger[to_state=BREAKOUT_DETECTED]"},
    {"contract_field": "branch_b.acceptance_close_count",
     "implementation": "v2_1.run_branch_b consecutive-close streak",
     "test": "test_branch_b_requires_the_preregistered_number_of_acceptance_closes",
     "replay_output": "transition_ledger[to_state=ACCEPTED_BREAKOUT]"},
    {"contract_field": "branch_b.retest_definition",
     "implementation": "v2_1.run_branch_b (RETEST_PENDING->RETEST_CONFIRMED)",
     "test": "test_branch_b_retest_must_be_strictly_after_acceptance",
     "replay_output": "transition_ledger[to_state=RETEST_CONFIRMED]"},
    {"contract_field": "branch_b.retest_tolerance",
     "implementation": "v2_1.run_branch_b RETEST_TOLERANCE == 0.0 (exact touch)",
     "test": "test_branch_b_retest_has_no_tolerance_parameter",
     "replay_output": "transition_ledger.reason_code=EXACT_TOUCH_HELD_ON_BREAKOUT_SIDE"},
    {"contract_field": "branch_b.retest_max_bars",
     "implementation": "v2_1.run_branch_b budget_end = accept+1+RETEST_MAX_BARS",
     "test": "test_branch_b_retest_timeout",
     "replay_output": "reject_reason=RETEST_TIMEOUT"},
    {"contract_field": "branch_b.continuation_confirmation",
     "implementation": "injected continuation_confirmed_at",
     "test": "test_branch_b_confirmation_failure",
     "replay_output": "transition_ledger[to_state=CONTINUATION_CONFIRMED]"},
    {"contract_field": "branch_b.invalidation",
     "implementation": "v2_1.run_branch_b close-back-inside check",
     "test": "test_branch_b_close_back_inside_invalidates_the_breakout",
     "replay_output": "reject_reason=BREAKOUT_REJECTED_CLOSE_BACK_INSIDE"},
    {"contract_field": "branch_b.stop_definition",
     "implementation": "v2_1.run_branch_b retest_extreme (no buffer)",
     "test": "test_branch_b_full_sequence_acceptance_precedes_retest",
     "replay_output": "trade_ledger.stop_price"},
    {"contract_field": "session.reference_window_utc / london / new_york",
     "implementation": "engine Opportunity.bars built from SESSION_PAIRS",
     "test": "test_session_windows_are_the_frozen_clocks",
     "replay_output": "trade_ledger.session"},
    {"contract_field": "governance.event_id_inputs",
     "implementation": "v2_1.event_id",
     "test": "test_event_id_is_stable_and_discriminating",
     "replay_output": "event_ledger.EVENT_ID"},
    {"contract_field": "governance.duplicate_event_policy",
     "implementation": "v2_1.EventRegistry.accept_signal",
     "test": "test_first_valid_signal_locks_the_tuple_and_suppresses_duplicates",
     "replay_output": "event_ledger.DUPLICATE_SUPPRESSED"},
    {"contract_field": "governance.permitted_handovers / handover_max",
     "implementation": "v2_1.EventRegistry.may_hand_over / record_handover",
     "test": "test_handover_budget_is_enforced",
     "replay_output": "event_ledger.HANDOVERS"},
    {"contract_field": "governance.same_bar_collision_policy",
     "implementation": "v2_1_engine.evaluate_outcome (stop checked first)",
     "test": "test_same_bar_collision_resolves_to_the_stop",
     "replay_output": "trade_ledger.outcome=STOP_REACHED"},
    {"contract_field": "target.authority_order",
     "implementation": "v2_1.resolve_natural_target + engine.build_target_candidates",
     "test": "test_priority_order_wins_over_a_bigger_target",
     "replay_output": "trade_ledger.target_authority"},
    {"contract_field": "target.causality_rule",
     "implementation": "v2_1.resolve_natural_target known_at guard",
     "test": "test_future_target_is_forbidden",
     "replay_output": "raises before any ledger row is written"},
    {"contract_field": "target.min_natural_r",
     "implementation": "v2_1.resolve_natural_target post-selection floor",
     "test": "test_r_floor_is_not_a_selection_criterion",
     "replay_output": "reject_reason=NATURAL_R_BELOW_FLOOR"},
    {"contract_field": "target.synthetic_targets_forbidden",
     "implementation": "no R-multiple fallback exists anywhere",
     "test": "test_artificial_fixed_2r_target_is_absent_from_the_contract",
     "replay_output": "reject_reason=NO_NATURAL_TARGET"},
    {"contract_field": "symbol_metadata (tick_size / point / digits)",
     "implementation": "symbol_metadata.metadata_for",
     "test": "test_symbol_normalization",
     "replay_output": "symbol_normalization_audit.json"},
    {"contract_field": "friction (UNAVAILABLE / NOT_ESTIMABLE)",
     "implementation": "v2_1.economic_claim",
     "test": "test_unknown_friction_is_not_zero",
     "replay_output": "final_return.ECONOMIC_EDGE"},
    {"contract_field": "funnel.stages / report_axes",
     "implementation": "v2_1_funnel.funnel_table / funnel_by_dimension",
     "test": "test_funnel_table_reports_n_and_next_stage_percent",
     "replay_output": "funnel_report.json"},
    {"contract_field": "session.outcome_horizon_m5_bars",
     "implementation": "v2_1_engine.evaluate_outcome horizon slice",
     "test": "test_outcome_horizon_is_respected",
     "replay_output": "trade_ledger.outcome=SESSION_EXPIRED"},
)

UNIMPLEMENTABLE: tuple[dict, ...] = tuple(
    {"contract_field": a["contract_field"], "ambiguity_id": a["id"],
     "implementation": f"REQUIRED POLICY HOOK — {a['hook']} (no default)",
     "test": "test_engine_refuses_a_policy_that_does_not_resolve_every_ambiguity",
     "replay_output": "BLOCKED_CONTRACT_AMBIGUITY",
     "question_for_owner": a["question_for_owner"]}
    for a in E.CONTRACT_AMBIGUITIES
)


def write(name: str, payload) -> str:
    path = OUT / name
    body = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    path.write_text(body)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def phase1() -> dict:
    total = len(MATRIX) + len(UNIMPLEMENTABLE)
    payload = {
        "artifact": "v2_1_contract_implementation_matrix",
        "contract_hash": V.contract_hash(),
        "CONTRACT_FIELDS_TOTAL": total,
        "CONTRACT_FIELDS_IMPLEMENTED": len(MATRIX),
        "CONTRACT_FIELDS_BLOCKED_BY_AMBIGUITY": len(UNIMPLEMENTABLE),
        "CONTRACT_MAPPING_COMPLETE": len(UNIMPLEMENTABLE) == 0,
        "semantics": (
            "Every semantic field maps to an implementation, a test and a "
            "replay output field. Fields whose contract text does not "
            "determine behaviour are listed separately and fail closed; no "
            "interpretation was chosen by the implementing agent."
        ),
        "implemented": list(MATRIX),
        "blocked_by_contract_ambiguity": list(UNIMPLEMENTABLE),
    }
    return {"name": "v2_1_contract_implementation_matrix.json", "payload": payload}


# ---------------------------------------------------------------------------
# PHASE 4 — symbol normalization audit (classify every numeric literal)
# ---------------------------------------------------------------------------

SCANNED = (
    "src/ag_edgelab/strategies/asian_liquidity_displacement_v2_1.py",
    "src/ag_edgelab/strategies/symbol_metadata.py",
    "src/ag_edgelab/strategies/v2_1_engine.py",
    "src/ag_edgelab/strategies/v2_1_funnel.py",
    "src/ag_edgelab/governance/v2_1_data_authorization.py",
)
TOKENS = ("0.0001", "0.00001", "0.01", "0.1", "pip", "pips")


def phase4() -> dict:
    findings = []
    for rel in SCANNED:
        path = Path(rel)
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            for tok in TOKENS:
                if not re.search(rf"(?<![\w.]){re.escape(tok)}", stripped, re.I):
                    continue
                in_metadata = rel.endswith("symbol_metadata.py")
                is_comment = stripped.startswith("#") or stripped.startswith('"')
                if tok.lower().startswith("pip"):
                    cls = ("METADATA_AUTHORITY_DECLARATION" if in_metadata
                           else "PROSE_OR_PROHIBITION" if is_comment or '"' in stripped
                           else "RULE_USE_VIOLATION")
                else:
                    cls = ("METADATA_AUTHORITY_DECLARATION" if in_metadata
                           else "PROSE_OR_TEST_REFERENCE" if is_comment or '"' in stripped
                           else "NUMERIC_LITERAL_IN_RULE_CODE")
                findings.append({"file": rel, "line": lineno, "token": tok,
                                 "classification": cls, "text": stripped[:140]})
    violations = [f for f in findings
                  if f["classification"] in ("RULE_USE_VIOLATION",
                                             "NUMERIC_LITERAL_IN_RULE_CODE")]
    payload = {
        "artifact": "symbol_normalization_audit",
        "authority_id": SM.METADATA_AUTHORITY_ID,
        "instruments": {s: {"price_unit": m.price_unit, "digits": m.digits,
                            "tick_size": m.tick_size, "point": m.point,
                            "pip_size_REPORTING_ONLY": m.pip_size}
                        for s, m in sorted(SM.SYMBOL_METADATA.items())},
        "rule_admissible_fields": list(SM.RULE_ADMISSIBLE_FIELDS),
        "rule_forbidden_fields": list(SM.RULE_FORBIDDEN_FIELDS),
        "scanned_files": list(SCANNED),
        "scanned_tokens": list(TOKENS),
        "occurrences": findings,
        "occurrences_n": len(findings),
        "violations": violations,
        "violations_n": len(violations),
        "NO_UNIVERSAL_FX_CONSTANT_GOVERNS_JPY_OR_GOLD": not violations,
        "note": (
            "Rule magnitudes are TICK_SIZE multiples or dimensionless "
            "reference-range fractions. pip_size is reporting-only and is "
            "never read by a rule."
        ),
    }
    return {"name": "symbol_normalization_audit.json", "payload": payload}


# ---------------------------------------------------------------------------
# PHASE 3 — event governance validation over the mandated synthetic cases
# ---------------------------------------------------------------------------

def phase3() -> dict:
    cases = []
    for scenario in build_scenarios():
        engine, _ = run_synthetic_engine(scenario)
        cases.append({
            "case": scenario.name,
            "expectation": scenario.expectation,
            "events": engine.event_ledger(),
            "accepted_n": engine.registry.accepted_n,
            "suppressed_n": engine.registry.suppressed_n,
            "branches_selected": sorted({t["branch"] for t in engine.trade_ledger()
                                         if t["branch"]}),
        })
    payload = {
        "artifact": "event_governance_validation",
        "handover_max": V.HANDOVER_MAX,
        "permitted_handovers": [list(h) for h in V.PERMITTED_HANDOVERS],
        "lock_key": ["symbol", "trading_date", "session", "boundary"],
        "note": (
            "Arena implements frozen semantics only. Whether HANDOVER_MAX = 1 "
            "is statistically desirable is for the independent audit."
        ),
        "cases": cases,
        "cases_n": len(cases),
    }
    return {"name": "event_governance_validation.json", "payload": payload}


# ---------------------------------------------------------------------------
# PHASE 12 — synthetic determinism
# ---------------------------------------------------------------------------

def phase12() -> dict:
    def one_pass() -> dict:
        trades, transitions, events = [], [], []
        for scenario in build_scenarios():
            engine, _ = run_synthetic_engine(scenario)
            trades += engine.trade_ledger()
            transitions += engine.transition_ledger()
            events += engine.event_ledger()
        return {
            "event_ledger": events,
            "trade_ledger": trades,
            "transition_ledger": transitions,
            "funnel_report": F.funnel_by_dimension(trades),
            "robustness_fixture_report": F.robustness_report(trades),
            "final_return_fixture": {
                "OPPORTUNITY_N": F.stage_counts(trades)["OPPORTUNITY"],
                "ENTRY_AVAILABLE_N": F.stage_counts(trades)["ENTRY_AVAILABLE"],
                "TRADE_COMPLETED_N": F.stage_counts(trades)["TRADE_COMPLETED"],
                "sample_gate": F.sample_gate(trades),
                "target_capability": F.target_capability(trades),
                "branch_report": F.branch_report(trades),
                "ECONOMIC_EDGE": V.ECONOMIC_EDGE,
                "REAL_HISTORICAL_REPLAY_EXECUTED": "NO",
            },
        }

    run1, run2 = one_pass(), one_pass()
    h1 = hashlib.sha256(canonical_json(run1).encode("utf-8")).hexdigest()
    h2 = hashlib.sha256(canonical_json(run2).encode("utf-8")).hexdigest()
    per_section = {
        k: hashlib.sha256(canonical_json(run1[k]).encode("utf-8")).hexdigest()
        for k in sorted(run1)
    }
    payload = {
        "artifact": "synthetic_determinism_evidence",
        "fixtures": "SYNTHETIC_FIXTURE_ONLY — no market corpus was read",
        "SYNTHETIC_RUN_1_HASH": h1,
        "SYNTHETIC_RUN_2_HASH": h2,
        "DETERMINISTIC": h1 == h2,
        "per_section_hashes": per_section,
        "sections": sorted(run1),
    }
    return {"name": "synthetic_determinism_evidence.json", "payload": payload,
            "deterministic": h1 == h2, "h1": h1, "h2": h2}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    emitted = {}
    for build in (phase1, phase4, phase3):
        art = build()
        emitted[art["name"]] = write(art["name"], art["payload"])
    det = phase12()
    emitted[det["name"]] = write(det["name"], det["payload"])

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_hash": V.contract_hash(),
        "artifacts": emitted,
        "CONTRACT_FIELDS_TOTAL": len(MATRIX) + len(UNIMPLEMENTABLE),
        "CONTRACT_FIELDS_IMPLEMENTED": len(MATRIX),
        "CONTRACT_MAPPING_COMPLETE": len(UNIMPLEMENTABLE) == 0,
        "CONTRACT_AMBIGUITIES": [a["id"] for a in E.CONTRACT_AMBIGUITIES],
        "SYNTHETIC_RUN_1_HASH": det["h1"],
        "SYNTHETIC_RUN_2_HASH": det["h2"],
        "DETERMINISTIC": det["deterministic"],
        "REAL_HISTORICAL_REPLAY_EXECUTED": "NO",
    }
    write("infrastructure_build_summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
