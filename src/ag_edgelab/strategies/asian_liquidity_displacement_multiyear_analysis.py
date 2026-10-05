"""Multi-year analysis layer for GEN2_ALD_V1_MULTIYEAR_DEV_R1.

Additive only.  Every funnel/target/gate computation is the already-accepted
``asian_liquidity_displacement_analysis`` module, unmodified; this file adds the
three things a multi-year corpus makes possible and a single-year corpus did
not:

  * a REAL calendar-year stability axis (the single-year campaign had to
    substitute intra-year quarters),
  * leave-one-year-out and leave-one-symbol-out folds,
  * the stage-by-stage attrition decomposition and per-year / per-cell matrices
    required by mission sections 5-7.

No threshold is introduced here: ``_stability_axis``, ``STRATUM_MIN_N`` and
``POOLED_ENTRY_ELIGIBILITY_N`` are imported from the frozen contracts.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Sequence

from ag_edgelab.strategies import asian_liquidity_displacement_analysis as A
from ag_edgelab.strategies.asian_liquidity_displacement_prereg import (
    POOLED_ENTRY_ELIGIBILITY_N,
    STRATUM_MIN_N,
)
from ag_edgelab.strategies.asian_liquidity_displacement_v1 import (
    CONFIRMATION_NODES,
    TRIGGER_NODES,
    CandidateUnit,
)

# ---------------------------------------------------------------------------
# mission section 5 — attrition decomposition
# ---------------------------------------------------------------------------

#: Mission reason label  ->  the frozen V1 rejection vocabulary it covers.
TRIGGER_REASON_MAP: dict[str, tuple[str, ...]] = {
    "NEUTRAL_DIRECTION": ("DIRECTION_NEUTRAL",),
    "DIRECTION_SWEEP_MISMATCH": (),
    "NO_ASIAN_SWEEP": ("NO_ASIAN_SWEEP_ON_DIRECTION_SIDE",),
    "NO_RECLAIM": ("NO_CLOSE_BACK_INSIDE",),
    "SESSION_EXPIRED": ("ENTRY_WINDOW_NO_BARS",),
    "OTHER_DEFINED_REASON": ("ASIAN_REFERENCE_INSUFFICIENT_BARS", "ASIAN_RANGE_DEGENERATE",
                             "DIRECTION_UNDECIDABLE"),
}

CONFIRMATION_REASON_MAP: dict[str, tuple[str, ...]] = {
    "NO_DISPLACEMENT": ("NO_DISPLACEMENT_BODY_RATIO",),
    "NO_MSS_BOS": ("NO_MSS_BOS_AFTER_DISPLACEMENT",),
    "NO_FVG": ("NO_FRESH_FVG_AFTER_MSS",),
    "NO_FVG_RETRACE": ("NO_CAUSAL_RETRACE_INTO_FVG", "RETRACE_INVALIDATED_BY_STOP_FIRST"),
    "TEMPORAL_INVALID": ("GEOMETRY_TEMPORAL_ORDER_INVALID", "RIGHT_CENSORED_DATA_BOUNDARY"),
    "GEOMETRY_INVALID": ("GEOMETRY_RISK_NON_POSITIVE", "GEOMETRY_TP1_NOT_BEYOND_ENTRY"),
}

#: ``DIRECTION_SWEEP_MISMATCH`` has no counterpart in the frozen vocabulary.
DIRECTION_SWEEP_MISMATCH_NOTE = (
    "The frozen V1 trigger does not emit a distinct direction/sweep mismatch rejection: "
    "the contract requires the sweep to be on the side OPPOSITE the decided direction, so a "
    "unit whose only sweep is on the direction side is rejected at T4_ASIAN_SWEEP with "
    "NO_ASIAN_SWEEP_ON_DIRECTION_SIDE. That bucket therefore carries both meanings and is "
    "reported once, under NO_ASIAN_SWEEP, rather than being split by an invented rule.")


def _pct(num: int, den: int) -> float | None:
    return None if not den else round(100.0 * num / den, 6)


def attrition_decomposition(units: Sequence[CandidateUnit]) -> dict:
    """Per-stage INPUT/PASS/FAIL/% chain plus separated failure reasons."""
    total = len(units)
    counts = A.stage_counts(units)
    entry_n = counts["ENTRY_AVAILABLE"]

    stages = []
    previous = total
    for node in (*TRIGGER_NODES, *CONFIRMATION_NODES):
        passed = counts[node]
        stages.append({
            "stage": node,
            "INPUT_N": previous,
            "PASS_N": passed,
            "FAIL_N": previous - passed,
            "PASS_PCT": _pct(passed, previous),
            "NEXT_STAGE_PCT": _pct(passed, total),
            "FINAL_ENTRY_PCT": _pct(entry_n, previous),
        })
        previous = passed

    raw = Counter(u.reject_reason for u in units if u.reject_reason != "PASS")
    trig_nodes = set(TRIGGER_NODES)

    def bucketize(mapping: dict[str, tuple[str, ...]], node_filter) -> dict:
        out: dict[str, dict] = {}
        for label, reasons in mapping.items():
            per_reason = {r: sum(1 for u in units
                                 if u.reject_reason == r and node_filter(u.reject_node))
                          for r in reasons}
            out[label] = {"n": sum(per_reason.values()), "frozen_reasons": per_reason}
        return out

    trigger_failures = bucketize(TRIGGER_REASON_MAP, lambda n: n in trig_nodes)
    trigger_failures["DIRECTION_SWEEP_MISMATCH"]["note"] = DIRECTION_SWEEP_MISMATCH_NOTE
    confirmation_failures = bucketize(CONFIRMATION_REASON_MAP, lambda n: n not in trig_nodes)

    trig_total = sum(v["n"] for v in trigger_failures.values())
    conf_total = sum(v["n"] for v in confirmation_failures.values())
    unmapped = sorted(set(raw) - {r for rs in TRIGGER_REASON_MAP.values() for r in rs}
                      - {r for rs in CONFIRMATION_REASON_MAP.values() for r in rs})

    return {
        "contract": "attrition is never collapsed into a single TRIGGER_FAIL bucket",
        "CANDIDATE_N": total,
        "stages": stages,
        "trigger_failures": dict(sorted(trigger_failures.items())),
        "trigger_failures_total": trig_total,
        "confirmation_failures": dict(sorted(confirmation_failures.items())),
        "confirmation_failures_total": conf_total,
        "raw_frozen_vocabulary_counts": dict(sorted(raw.items())),
        "unmapped_reasons": unmapped,
        "reconciliation_ok": trig_total + conf_total == sum(raw.values()) and not unmapped,
    }


# ---------------------------------------------------------------------------
# mission sections 6 / 7 — year and symbol x session distributions
# ---------------------------------------------------------------------------

def _cap(units: Sequence[CandidateUnit]) -> dict:
    return A.target_capability(units)


def year_distribution(units: Sequence[CandidateUnit]) -> dict:
    rows = {}
    for year in sorted({u.day[:4] for u in units}):
        sub = [u for u in units if u.day[:4] == year]
        c = A.stage_counts(sub)
        cap = _cap(sub)
        rows[year] = {
            "OPPORTUNITY_N": c["CANDIDATE_N"],
            "DIRECTION_DECIDABLE_N": c["T2_DIRECTION_DECIDED"],
            "DIRECTIONAL_N": c["T3_DIRECTION_NON_NEUTRAL"],
            "TRIGGER_N": c["TRIGGER_PASS"],
            "CONFIRMATION_N": c["CONFIRMATION_PASS"],
            "GEOMETRY_VALID_N": c["GEOMETRY_VALID"],
            "ENTRY_N": c["ENTRY_AVAILABLE"],
            "symbols_covered": sorted({u.symbol for u in sub}),
            "entry_yield_per_1000_candidates": round(
                1000.0 * c["ENTRY_AVAILABLE"] / c["CANDIDATE_N"], 6) if c["CANDIDATE_N"] else None,
            "trigger_yield_per_1000_candidates": round(
                1000.0 * c["TRIGGER_PASS"] / c["CANDIDATE_N"], 6) if c["CANDIDATE_N"] else None,
            "fixed_r_capability": cap["fixed_r_capability"],
            "natural_target_median_R": cap["natural_target_R"]["median"],
        }
    return {
        "selection_authority": "NONE — years are reported, never ranked and never selected",
        "rows": rows,
    }


def symbol_session_distribution(units: Sequence[CandidateUnit]) -> dict:
    """Independent cells first; pooling is reported last, never used to hide a cell."""
    cells = {}
    for sym in sorted({u.symbol for u in units}):
        for ses in sorted({u.session for u in units}):
            sub = [u for u in units if u.symbol == sym and u.session == ses]
            c = A.stage_counts(sub)
            cells[f"{sym}|{ses}"] = {
                "symbol": sym, "session": ses,
                "OPPORTUNITY_N": c["CANDIDATE_N"],
                "DIRECTIONAL_N": c["T3_DIRECTION_NON_NEUTRAL"],
                "TRIGGER_N": c["TRIGGER_PASS"],
                "CONFIRMATION_N": c["CONFIRMATION_PASS"],
                "GEOMETRY_VALID_N": c["GEOMETRY_VALID"],
                "ENTRY_N": c["ENTRY_AVAILABLE"],
                "years_covered": sorted({u.day[:4] for u in sub}),
                "SYMBOL_STARVATION": c["ENTRY_AVAILABLE"] < STRATUM_MIN_N,
            }
    by_symbol = {}
    for sym in sorted({u.symbol for u in units}):
        sub = [u for u in units if u.symbol == sym]
        c = A.stage_counts(sub)
        by_symbol[sym] = {"ENTRY_N": c["ENTRY_AVAILABLE"], "TRIGGER_N": c["TRIGGER_PASS"],
                          "OPPORTUNITY_N": c["CANDIDATE_N"],
                          "STARVED": c["ENTRY_AVAILABLE"] < STRATUM_MIN_N}
    by_session = {}
    for ses in sorted({u.session for u in units}):
        sub = [u for u in units if u.session == ses]
        c = A.stage_counts(sub)
        by_session[ses] = {"ENTRY_N": c["ENTRY_AVAILABLE"], "TRIGGER_N": c["TRIGGER_PASS"],
                           "OPPORTUNITY_N": c["CANDIDATE_N"],
                           "STARVED": c["ENTRY_AVAILABLE"] < STRATUM_MIN_N}
    return {
        "cell_floor_entries": STRATUM_MIN_N,
        "cells": cells,
        "BY_SYMBOL": by_symbol,
        "BY_SESSION": by_session,
        "SYMBOL_STARVATION": sorted(s for s, v in by_symbol.items() if v["STARVED"]),
        "SESSION_STARVATION": sorted(s for s, v in by_session.items() if v["STARVED"]),
        "removal_policy": "NO CELL IS REMOVED — weak cells are reported, never dropped",
    }


# ---------------------------------------------------------------------------
# mission section 9 — robustness, multi-year axes
# ---------------------------------------------------------------------------

def _leave_one_out_axis(units: Sequence[CandidateUnit], key) -> dict:
    """Expectancy of the COMPLEMENT of each held-out fold."""
    ent = [u for u in A.entries(units) if u.management_r is not None]
    groups = sorted({str(key(u)) for u in ent})
    folds = {}
    qualifying = []
    for g in groups:
        rest = [float(u.management_r) for u in ent if str(key(u)) != g]
        n = len(rest)
        exp = (sum(rest) / n) if n else None
        folds[f"WITHOUT_{g}"] = {"n": n, "expectancy_r": None if exp is None else round(exp, 6),
                                 "qualifying": n >= STRATUM_MIN_N}
        if n >= STRATUM_MIN_N and exp is not None:
            qualifying.append(exp)
    positive_fraction = (None if not qualifying
                         else round(sum(1 for v in qualifying if v > 0) / len(qualifying), 6))
    state = ("INSUFFICIENT_SAMPLE" if positive_fraction is None
             else ("PASS" if positive_fraction >= A.STABILITY_MIN_POSITIVE_FRACTION else "FAIL"))
    return {"folds": folds, "qualifying_folds": len(qualifying),
            "min_fold_n": STRATUM_MIN_N, "positive_fraction": positive_fraction,
            "required_positive_fraction": A.STABILITY_MIN_POSITIVE_FRACTION,
            "state": state}


def multiyear_robustness_report(units: Sequence[CandidateUnit],
                                neighborhood: dict[float, float] | None = None) -> dict:
    """The frozen battery, with the year axis upgraded and LOYO/LOSO added."""
    report = A.robustness_report(units, neighborhood)
    eligible = report["eligibility"]["eligible"]
    axes = report["axes"]

    years = sorted({u.day[:4] for u in units})
    calendar_year = A._stability_axis(A._stratum(units, lambda u: u.day[:4]))
    calendar_year["substitution"] = "NONE — this is a true calendar-year axis"
    calendar_year["years_covered"] = years
    calendar_year["standing_limitation"] = (
        "RESOLVED_FOR_YEAR_COVERAGE — the single-year campaign's "
        "YEAR_COVERAGE_LIMITED_SINGLE_CALENDAR_YEAR_2017 limitation no longer applies; "
        f"{len(years)} calendar years are covered")
    axes["YEAR_STABILITY"] = calendar_year
    axes["INTRA_YEAR_SEGMENT_STABILITY"] = A._stability_axis(A._stratum(units, lambda u: u.quarter))
    axes["LEAVE_ONE_YEAR_OUT"] = _leave_one_out_axis(units, lambda u: u.day[:4])
    axes["LEAVE_ONE_SYMBOL_OUT"] = _leave_one_out_axis(units, lambda u: u.symbol)

    if not eligible:
        for name in ("YEAR_STABILITY", "INTRA_YEAR_SEGMENT_STABILITY",
                     "LEAVE_ONE_YEAR_OUT", "LEAVE_ONE_SYMBOL_OUT"):
            payload = axes[name]
            payload["provisional_state_if_eligible"] = payload.get("state")
            payload["state"] = "NOT_RUN_INSUFFICIENT_SAMPLE"

    report["multi_year_extension"] = {
        "years_covered": years,
        "years_n": len(years),
        "added_axes": ["LEAVE_ONE_YEAR_OUT", "LEAVE_ONE_SYMBOL_OUT",
                       "INTRA_YEAR_SEGMENT_STABILITY"],
        "year_axis": "calendar year (no longer substituted by intra-year quarters)",
        "eligibility_rule": f"pooled ENTRY_AVAILABLE_N >= {POOLED_ENTRY_ELIGIBILITY_N}",
    }
    return report


# ---------------------------------------------------------------------------
# helpers for the runner
# ---------------------------------------------------------------------------

def per_year_entry_yield(units: Sequence[CandidateUnit]) -> dict[str, float]:
    out: dict[str, float] = {}
    by_year: dict[str, list[CandidateUnit]] = defaultdict(list)
    for u in units:
        by_year[u.day[:4]].append(u)
    for year, sub in by_year.items():
        c = A.stage_counts(sub)
        out[year] = round(1000.0 * c["ENTRY_AVAILABLE"] / c["CANDIDATE_N"], 6) if c["CANDIDATE_N"] else 0.0
    return dict(sorted(out.items()))


def cell_entry_counts(units: Sequence[CandidateUnit]) -> dict[str, int]:
    cells: dict[str, int] = {}
    for sym in sorted({u.symbol for u in units}):
        for ses in sorted({u.session for u in units}):
            sub = [u for u in units if u.symbol == sym and u.session == ses]
            cells[f"{sym}|{ses}"] = A.stage_counts(sub)["ENTRY_AVAILABLE"]
    return cells


# ---------------------------------------------------------------------------
# FINAL RETURN contract
# ---------------------------------------------------------------------------

FINAL_RETURN_FIELDS: tuple[str, ...] = (
    "STRATEGY_ID", "STRATEGY_HASH", "RULES_CHANGED", "EXPERIMENT_ID", "DATASET_AUTHORITY",
    "DEV_WINDOWS", "DEV_YEARS_N", "OPPORTUNITY_N", "DIRECTION_DECIDABLE_N", "DIRECTIONAL_N",
    "TRIGGER_PASS_N", "CONFIRMATION_PASS_N", "GEOMETRY_VALID_N", "ENTRY_AVAILABLE_N",
    "1R", "2R", "3R", "4R", "5R", "NATURAL_TARGET_MEDIAN_R",
    "2017_ENTRY_N", "MULTIYEAR_ENTRY_N", "SAMPLE_CLASSIFICATION", "PRIMARY_FUNNEL_WEAKNESS",
    "SECONDARY_DIAGNOSES", "ROBUSTNESS_RUN", "PRE_OOS_RESULT", "FROZEN_CANDIDATE",
    "OOS_OPENED", "HOLDOUT_TOUCHED", "PARAMETER_OPTIMIZATION", "STRATEGY_RULES_CHANGED",
    "BROKER_MUTATION", "STATUS", "NEXT",
)

#: Fields the mission fixes in advance. A run may never report anything else here.
FINAL_RETURN_CONSTANTS: dict[str, str] = {
    "RULES_CHANGED": "NO",
    "STRATEGY_RULES_CHANGED": "NO",
    "OOS_OPENED": "NO",
    "HOLDOUT_TOUCHED": "NO",
    "PARAMETER_OPTIMIZATION": "NO",
    "BROKER_MUTATION": "NO",
}


def final_return_block(final: dict, comparison: dict) -> dict:
    """Project the committed evidence onto the mission's FINAL RETURN contract.

    Every value is copied from an artifact; nothing is recomputed or retyped, so
    the block cannot drift from the evidence it summarises.
    """
    capability = final["CAPABILITY"]
    block = {
        "STRATEGY_ID": final["STRATEGY_ID"],
        "STRATEGY_HASH": final["STRATEGY_HASH"],
        "EXPERIMENT_ID": final["EXPERIMENT_ID"],
        "DATASET_AUTHORITY": final["DATASET_AUTHORITY"],
        "DEV_WINDOWS": final["DEV_WINDOWS"],
        "DEV_YEARS_N": final["DEV_YEARS_N"],
        "OPPORTUNITY_N": final["OPPORTUNITY_N"],
        "DIRECTION_DECIDABLE_N": final["DIRECTION_DECIDABLE_N"],
        "DIRECTIONAL_N": final["DIRECTIONAL_N"],
        "TRIGGER_PASS_N": final["TRIGGER_PASS_N"],
        "CONFIRMATION_PASS_N": final["CONFIRMATION_PASS_N"],
        "GEOMETRY_VALID_N": final["GEOMETRY_VALID_N"],
        "ENTRY_AVAILABLE_N": final["ENTRY_AVAILABLE_N"],
        "NATURAL_TARGET_MEDIAN_R": final["NATURAL_TARGET_MEDIAN_R"],
        "2017_ENTRY_N": comparison["narrow_2017_dev"]["ENTRY_AVAILABLE_N"],
        "MULTIYEAR_ENTRY_N": comparison["multiyear"]["ENTRY_AVAILABLE_N"],
        "SAMPLE_CLASSIFICATION": final["SAMPLE_CLASSIFICATION"],
        "PRIMARY_FUNNEL_WEAKNESS": final["PRIMARY_FUNNEL_WEAKNESS"],
        "SECONDARY_DIAGNOSES": final["SECONDARY_DIAGNOSES"],
        "ROBUSTNESS_RUN": final["ROBUSTNESS_RUN"],
        "PRE_OOS_RESULT": final["PRE_OOS_RESULT"],
        "FROZEN_CANDIDATE": final["FROZEN_CANDIDATE"],
        "STATUS": final["STATUS"],
        "NEXT": final["NEXT"],
    }
    block.update({k: capability[k] for k in ("1R", "2R", "3R", "4R", "5R")})
    for key, value in FINAL_RETURN_CONSTANTS.items():
        if final.get(key, value) != value:
            raise ValueError(f"{key} must be {value}, evidence says {final[key]!r}")
        block[key] = value
    missing = [f for f in FINAL_RETURN_FIELDS if f not in block]
    if missing:
        raise ValueError(f"FINAL RETURN contract incomplete: {missing}")
    return {f: block[f] for f in FINAL_RETURN_FIELDS}
