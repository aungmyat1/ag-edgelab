"""MISSION 3 PHASES 4-5 — V2 funnel, strata and the V1/V2 diagnostic comparison.

Analysis only. Nothing here may alter a rule, a threshold or a verdict.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Iterable, Sequence

from ag_edgelab.strategies.asian_liquidity_displacement_v2 import (
    BRANCHES,
    FIXED_R_TARGETS,
    OUTCOME_NODES,
    REASON_NODE,
    REJECT_REASONS,
    STAGE_NODES,
    V2Unit,
)
from ag_edgelab.strategies.asian_liquidity_displacement_v2_prereg import (
    BRANCH_MIN_N,
    SAMPLE_FLOOR,
)


def entries(units: Iterable[V2Unit]) -> list[V2Unit]:
    return [u for u in units if u.passed("S7_ENTRY_AVAILABLE")]


def completed(units: Iterable[V2Unit]) -> list[V2Unit]:
    return [u for u in units if u.passed("S9_TRADE_COMPLETED")]


def stage_counts(units: Sequence[V2Unit]) -> dict[str, int]:
    counts = {"OPPORTUNITY": len(units)}
    for node in STAGE_NODES + OUTCOME_NODES:
        counts[node] = sum(1 for u in units if u.passed(node))
    return counts


def funnel_table(units: Sequence[V2Unit]) -> list[dict]:
    """N, % of previous stage and % of original opportunities, per transition."""
    total = len(units)
    rows: list[dict] = []
    prev_n = total
    prev_label = "OPPORTUNITY"
    for node in STAGE_NODES:
        n = sum(1 for u in units if u.passed(node))
        rows.append({
            "transition": f"{prev_label} -> {node}",
            "stage": node,
            "INPUT_N": prev_n,
            "N": n,
            "FAIL_N": prev_n - n,
            "PCT_OF_PREVIOUS_STAGE": round(100.0 * n / prev_n, 6) if prev_n else 0.0,
            "PCT_OF_OPPORTUNITIES": round(100.0 * n / total, 6) if total else 0.0,
        })
        prev_n, prev_label = n, node
    return rows


def rejection_breakdown(units: Sequence[V2Unit]) -> dict:
    raw: dict[str, int] = defaultdict(int)
    for u in units:
        if u.reject_reason != "PASS":
            raw[u.reject_reason] += 1
    by_node: dict[str, dict[str, int]] = defaultdict(dict)
    for reason, n in raw.items():
        by_node[REASON_NODE[reason]][reason] = n
    unmapped = sorted(set(raw) - set(REASON_NODE))
    return {
        "by_node": {k: dict(sorted(v.items())) for k, v in sorted(by_node.items())},
        "totals": dict(sorted(raw.items())),
        "unmapped_reasons": unmapped,
        "reconciliation_ok": not unmapped
        and sum(raw.values()) == sum(1 for u in units if u.reject_reason != "PASS"),
        "vocabulary": list(REJECT_REASONS),
    }


def capability(units: Sequence[V2Unit]) -> dict:
    """Capability is measured on COMPLETED trades only. 1R-5R are diagnostics."""
    done = completed(units)
    n = len(done)
    out: dict[str, object] = {
        "ENTRY_AVAILABLE_N": len(entries(units)),
        "TRADE_COMPLETED_N": n,
        "economic_claim": "NOT_ESTIMABLE — structural R only, no measured friction",
    }
    if not n:
        out.update({"fixed_r_capability": {f"{k}R": None for k in FIXED_R_TARGETS},
                    "natural_target_R": None, "MFE_R": None, "MAE_R": None,
                    "target_reached_rate": None, "realised_R": None, "resolution_mix": {}})
        return out
    out["fixed_r_capability"] = {
        f"{k}R": round(sum(1 for u in done if u.reached.get(f"{k}R")) / n, 6)
        for k in FIXED_R_TARGETS}
    nat = [u.natural_target_r for u in done if u.natural_target_r is not None]
    mfe = [u.mfe_r for u in done if u.mfe_r is not None]
    mae = [u.mae_r for u in done if u.mae_r is not None]
    real = [u.realised_r for u in done if u.realised_r is not None]
    out["natural_target_R"] = _summary(nat)
    out["MFE_R"] = _summary(mfe)
    out["MAE_R"] = _summary(mae)
    out["realised_R"] = _summary(real)
    out["target_reached_rate"] = round(
        sum(1 for u in done if u.target_reached) / n, 6)
    mix: dict[str, int] = defaultdict(int)
    for u in done:
        mix[u.resolution or "UNKNOWN"] += 1
    out["resolution_mix"] = dict(sorted(mix.items()))
    out["stopped_same_bar_n"] = sum(1 for u in done if u.stopped_same_bar)
    return out


def _summary(values: Sequence[float]) -> dict | None:
    if not values:
        return None
    return {"n": len(values),
            "median": round(statistics.median(values), 6),
            "mean": round(statistics.fmean(values), 6),
            "min": round(min(values), 6),
            "max": round(max(values), 6)}


def _slice_report(units: Sequence[V2Unit]) -> dict:
    counts = stage_counts(units)
    cap = capability(units)
    return {
        "OPPORTUNITY_N": counts["OPPORTUNITY"],
        "SESSION_EVENT_N": counts["S3_SESSION_EVENT"],
        "SWEEP_OR_BREAKOUT_N": counts["S4_SWEEP_OR_BREAKOUT"],
        "RECLAIM_OR_RETEST_N": counts["S5_RECLAIM_OR_RETEST"],
        "STRUCTURE_CONFIRM_N": counts["S6_STRUCTURE_CONFIRM"],
        "ENTRY_AVAILABLE_N": counts["S7_ENTRY_AVAILABLE"],
        "GEOMETRY_VALID_N": counts["S8_GEOMETRY_VALID"],
        "TRADE_COMPLETED_N": counts["S9_TRADE_COMPLETED"],
        "entry_yield_per_1000_opportunities": round(
            1000.0 * counts["S7_ENTRY_AVAILABLE"] / counts["OPPORTUNITY"], 6)
        if counts["OPPORTUNITY"] else 0.0,
        "fixed_r_capability": cap["fixed_r_capability"],
        "natural_target_R_median": (cap["natural_target_R"] or {}).get("median")
        if cap["natural_target_R"] else None,
        "target_reached_rate": cap["target_reached_rate"],
    }


def by_axis(units: Sequence[V2Unit], axis: str) -> dict[str, dict]:
    """Report every stratum independently. Never drops or ranks a stratum."""
    keyfn = {
        "branch": lambda u: u.branch or "NO_BRANCH",
        "symbol": lambda u: u.symbol,
        "year": lambda u: u.day[:4],
        "session": lambda u: u.session,
        "symbol_session": lambda u: f"{u.symbol}|{u.session}",
        "branch_session": lambda u: f"{u.branch or 'NO_BRANCH'}|{u.session}",
        "regime": lambda u: u.regime,
    }[axis]
    groups: dict[str, list[V2Unit]] = defaultdict(list)
    for u in units:
        groups[keyfn(u)].append(u)
    return {k: _slice_report(v) for k, v in sorted(groups.items())}


def branch_report(units: Sequence[V2Unit]) -> dict:
    """Both branches, always. Underpowered branches are flagged, never removed."""
    out: dict[str, dict] = {}
    for branch in BRANCHES:
        sub = [u for u in units if u.branch == branch]
        rep = _slice_report(sub)
        rep["capability_detail"] = capability(sub)
        n = rep["ENTRY_AVAILABLE_N"]
        rep["BRANCH_MIN_N"] = BRANCH_MIN_N
        rep["state"] = "BRANCH_POWERED" if n >= BRANCH_MIN_N else "BRANCH_UNDERPOWERED"
        rep["retention_rule"] = ("reported regardless of result; a branch may never be "
                                 "deleted, hidden or merged on the basis of its outcome")
        out[branch] = rep
    disjoint = sum(out[b]["OPPORTUNITY_N"] for b in BRANCHES)
    out["_branch_integrity"] = {
        "units_assigned_to_a_branch": disjoint,
        "units_with_no_branch": sum(1 for u in units if u.branch is None),
        "total_units": len(units),
        "disjoint_ok": disjoint + sum(1 for u in units if u.branch is None) == len(units),
        "note": "branches partition the event space by construction",
    }
    return out


def sample_gate(units: Sequence[V2Unit]) -> dict:
    n = len(entries(units))
    passed = n >= SAMPLE_FLOOR
    per_branch = {b: len([u for u in entries(units) if u.branch == b]) for b in BRANCHES}
    return {
        "SAMPLE_FLOOR": SAMPLE_FLOOR,
        "ENTRY_AVAILABLE_N": n,
        "SAMPLE_GATE": "PASS" if passed else "FAIL",
        "per_branch_entries": per_branch,
        "BRANCH_MIN_N": BRANCH_MIN_N,
        "underpowered_branches": sorted(b for b, c in per_branch.items() if c < BRANCH_MIN_N),
        "verdict": ("sample floor satisfied" if passed else
                    "DEV_REJECTED_INSUFFICIENT_SAMPLE"),
        "threshold_origin": "inherited unchanged from the EdgeLab verifier; never relaxed "
                            "after seeing a result",
    }


def primary_funnel_weakness(units: Sequence[V2Unit]) -> dict:
    """The single largest absolute attrition step, stated without editorialising."""
    rows = funnel_table(units)
    worst = max(rows, key=lambda r: r["FAIL_N"]) if rows else None
    reasons = rejection_breakdown(units)
    node_losses = {r["stage"]: r["FAIL_N"] for r in rows}
    return {
        "PRIMARY_FUNNEL_WEAKNESS": worst["stage"] if worst else None,
        "lost_at_that_stage": worst["FAIL_N"] if worst else 0,
        "pct_of_opportunities_lost_there": round(
            100.0 * worst["FAIL_N"] / len(units), 6) if worst and units else 0.0,
        "dominant_reasons_at_that_stage": reasons["by_node"].get(
            worst["stage"], {}) if worst else {},
        "loss_by_stage": node_losses,
        "rule": "largest absolute FAIL_N; reported as a diagnosis, never used to justify "
                "changing a rule inside this mission",
    }


def v1_v2_comparison(units: Sequence[V2Unit], v1: dict) -> dict:
    """Architecture comparison. V2 is NOT optimized against V1."""
    counts = stage_counts(units)
    cap = capability(units)
    v2_entries = counts["S7_ENTRY_AVAILABLE"]
    v1_entries = int(v1["ENTRY_AVAILABLE_N"])
    v1_opp = int(v1["OPPORTUNITY_N"])
    v2_opp = counts["OPPORTUNITY"]

    def ratio(a: float, b: float) -> float | None:
        return round(a / b, 6) if b else None

    v2_cap = cap["fixed_r_capability"]
    rows = [
        ("opportunities", v1_opp, v2_opp),
        ("event_or_trigger_passes", int(v1["TRIGGER_PASS_N"]), counts["S4_SWEEP_OR_BREAKOUT"]),
        ("confirmations", int(v1["CONFIRMATION_PASS_N"]), counts["S6_STRUCTURE_CONFIRM"]),
        ("entries", v1_entries, v2_entries),
        ("entry_yield_per_1000", round(1000.0 * v1_entries / v1_opp, 6) if v1_opp else 0.0,
         round(1000.0 * v2_entries / v2_opp, 6) if v2_opp else 0.0),
        ("median_natural_target_R", v1["NATURAL_TARGET_MEDIAN_R"],
         (cap["natural_target_R"] or {}).get("median") if cap["natural_target_R"] else None),
    ]
    for k in FIXED_R_TARGETS:
        rows.append((f"{k}R_capability", v1["capability"][f"{k}R"], v2_cap.get(f"{k}R")))

    table = [{"metric": m, "V1": a, "V2": b,
              "V2_over_V1": ratio(b, a) if isinstance(a, (int, float))
              and isinstance(b, (int, float)) else None}
             for m, a, b in rows]

    return {
        "comparison_table": table,
        "opportunity_basis_identical": v1_opp == v2_opp,
        "opportunity_basis_note": (
            "V2 deliberately uses V1's opportunity basis (one unit per symbol-day-session) "
            "so this table compares ARCHITECTURE, not a changed denominator."),
        "primary_question": "DID V2 SOLVE STRUCTURAL STARVATION?",
        "answer": ("YES — pooled entries reached the preregistered floor"
                   if v2_entries >= SAMPLE_FLOOR else
                   "NO — pooled entries remain below the preregistered floor"),
        "authority": "DIAGNOSTIC ONLY. V1 is closed evidence: not re-run, not re-tuned, "
                     "not re-interpreted. V2 was never optimized against these numbers.",
    }


# ---------------------------------------------------------------------------
# PHASE 6 — PRE_OOS_ROBUSTNESS_GATE_V1, thresholds UNCHANGED
# ---------------------------------------------------------------------------

import random  # noqa: E402

from ag_edgelab.strategies.asian_liquidity_displacement_prereg import (  # noqa: E402
    BOOTSTRAP_CONFIDENCE,
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    PRE_OOS_GATE_ID,
    STABILITY_MAX_RELATIVE_SPIKE,
    STABILITY_MIN_POSITIVE_FRACTION,
)
from ag_edgelab.universal.fx_dev_campaign import (  # noqa: E402
    CONTINUATION_REACH_1R_MIN,
    CONTINUATION_REACH_3R_MIN,
    MIN_ENTERED_N,
)


def expectancy(units: Sequence[V2Unit]) -> float | None:
    """Structural R expectancy of COMPLETED trades. No friction is modelled."""
    rows = [u.realised_r for u in completed(units) if u.realised_r is not None]
    return round(statistics.fmean(rows), 6) if rows else None


def _stability_axis(units: Sequence[V2Unit], keyfn, axis_id: str) -> dict:
    groups: dict[str, list[V2Unit]] = defaultdict(list)
    for u in completed(units):
        groups[keyfn(u)].append(u)
    slices = {}
    for key, sub in sorted(groups.items()):
        slices[key] = {"n": len(sub), "expectancy_R": expectancy(sub),
                       "qualifying": len(sub) >= BRANCH_MIN_N}
    qualifying = {k: v for k, v in slices.items() if v["qualifying"]}
    positive = [k for k, v in qualifying.items() if (v["expectancy_R"] or 0) > 0]
    frac = round(len(positive) / len(qualifying), 6) if qualifying else None
    values = [v["expectancy_R"] for v in qualifying.values() if v["expectancy_R"] is not None]
    spike = None
    if values and statistics.fmean([abs(v) for v in values]) > 0:
        spike = round(max(abs(v) for v in values)
                      / statistics.fmean([abs(v) for v in values]), 6)
    state = ("INSUFFICIENT_SAMPLE" if frac is None else
             "PASS" if (frac >= STABILITY_MIN_POSITIVE_FRACTION
                        and (spike is None or spike <= STABILITY_MAX_RELATIVE_SPIKE))
             else "FAIL")
    return {"axis": axis_id, "state": state, "slices": slices,
            "qualifying_n": len(qualifying), "positive_fraction": frac,
            "required_positive_fraction": STABILITY_MIN_POSITIVE_FRACTION,
            "relative_spike": spike, "max_relative_spike": STABILITY_MAX_RELATIVE_SPIKE,
            "min_slice_n": BRANCH_MIN_N}


def _walk_forward(units: Sequence[V2Unit]) -> dict:
    """Chronological non-overlapping monthly folds, in date order."""
    folds: dict[str, list[V2Unit]] = defaultdict(list)
    for u in completed(units):
        folds[u.day[:7]].append(u)
    rows = [{"fold": k, "n": len(v), "expectancy_R": expectancy(v)}
            for k, v in sorted(folds.items())]
    qualifying = [r for r in rows if r["n"] >= BRANCH_MIN_N]
    frac = (round(sum(1 for r in qualifying if (r["expectancy_R"] or 0) > 0)
                  / len(qualifying), 6) if qualifying else None)
    state = ("INSUFFICIENT_SAMPLE" if frac is None else
             "PASS" if frac >= STABILITY_MIN_POSITIVE_FRACTION else "FAIL")
    return {"axis": "WALK_FORWARD", "state": state, "folds": rows,
            "qualifying_folds": len(qualifying), "positive_fraction": frac,
            "required_positive_fraction": STABILITY_MIN_POSITIVE_FRACTION,
            "min_fold_n": BRANCH_MIN_N,
            "method": "chronological non-overlapping monthly test windows"}


def _tail_dependence(units: Sequence[V2Unit]) -> dict:
    rows = sorted((u.realised_r for u in completed(units) if u.realised_r is not None),
                  reverse=True)
    if not rows:
        return {"axis": "TAIL_DEPENDENCE", "state": "INSUFFICIENT_SAMPLE"}
    full = statistics.fmean(rows)
    drop1 = statistics.fmean(rows[1:]) if len(rows) > 1 else None
    k = max(1, int(round(0.05 * len(rows))))
    drop5 = statistics.fmean(rows[k:]) if len(rows) > k else None
    survives = all(v is not None and v > 0 for v in (drop1, drop5))
    return {"axis": "TAIL_DEPENDENCE",
            "state": "PASS" if survives else "FAIL",
            "expectancy_R": round(full, 6),
            "without_best_trade": round(drop1, 6) if drop1 is not None else None,
            "without_best_5pct": round(drop5, 6) if drop5 is not None else None,
            "trades_removed_at_5pct": k,
            "pass_rule": "pooled expectancy stays strictly positive after each removal"}


def _bootstrap(units: Sequence[V2Unit]) -> dict:
    rows = [u.realised_r for u in completed(units) if u.realised_r is not None]
    if len(rows) < MIN_ENTERED_N:
        return {"axis": "BOOTSTRAP", "state": "INSUFFICIENT_SAMPLE", "n": len(rows)}
    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    n = len(rows)
    for _ in range(BOOTSTRAP_SAMPLES):
        means.append(statistics.fmean([rows[rng.randrange(n)] for _ in range(n)]))
    means.sort()
    alpha = (1.0 - BOOTSTRAP_CONFIDENCE) / 2.0
    lo = means[int(alpha * BOOTSTRAP_SAMPLES)]
    hi = means[min(BOOTSTRAP_SAMPLES - 1, int((1 - alpha) * BOOTSTRAP_SAMPLES))]
    return {"axis": "BOOTSTRAP",
            "state": "PASS" if lo > 0 else "FAIL",
            "samples": BOOTSTRAP_SAMPLES, "seed": BOOTSTRAP_SEED,
            "confidence": BOOTSTRAP_CONFIDENCE,
            "point_estimate_R": round(statistics.fmean(rows), 6),
            "ci_low_R": round(lo, 6), "ci_high_R": round(hi, 6),
            "pass_rule": "lower confidence bound of pooled expectancy > 0"}


def _concentration(units: Sequence[V2Unit]) -> dict:
    done = completed(units)
    pos = [u for u in done if (u.realised_r or 0) > 0]
    total_gain = sum(u.realised_r for u in pos) if pos else 0.0
    shares: dict[str, float] = {}
    for axis, keyfn in (("symbol", lambda u: u.symbol),
                        ("year", lambda u: u.day[:4]),
                        ("branch", lambda u: u.branch or "NO_BRANCH"),
                        ("session", lambda u: u.session)):
        buckets: dict[str, float] = defaultdict(float)
        for u in pos:
            buckets[keyfn(u)] += u.realised_r or 0.0
        if total_gain > 0 and buckets:
            shares[f"max_{axis}_share_of_gross_gain"] = round(
                max(buckets.values()) / total_gain, 6)
    worst = max(shares.values()) if shares else None
    # fail-closed: no single stratum may carry a majority of the gross gain
    state = ("INSUFFICIENT_SAMPLE" if worst is None else
             "PASS" if worst <= 0.5 else "FAIL")
    return {"axis": "CONCENTRATION", "state": state, "shares": shares,
            "max_share": worst, "pass_rule": "no single stratum supplies > 50% of gross gain",
            "trades": len(done), "winning_trades": len(pos)}


def _structural_capability(units: Sequence[V2Unit]) -> dict:
    cap = capability(units)
    fixed = cap["fixed_r_capability"]
    n = cap["TRADE_COMPLETED_N"]
    if n < MIN_ENTERED_N:
        return {"axis": "STRUCTURAL_CAPABILITY", "state": "INSUFFICIENT_SAMPLE", "n": n}
    ok = (fixed["1R"] or 0) >= CONTINUATION_REACH_1R_MIN and \
         (fixed["3R"] or 0) >= CONTINUATION_REACH_3R_MIN
    return {"axis": "STRUCTURAL_CAPABILITY", "state": "PASS" if ok else "FAIL",
            "reach_1R": fixed["1R"], "reach_1R_min": CONTINUATION_REACH_1R_MIN,
            "reach_3R": fixed["3R"], "reach_3R_min": CONTINUATION_REACH_3R_MIN,
            "n": n, "source": "frozen V0.3 floors, unchanged"}


def pre_oos_gate(units: Sequence[V2Unit], *, identity_valid: bool,
                 dataset_role_valid: bool, friction_disclosed: bool) -> dict:
    gate = sample_gate(units)
    if gate["SAMPLE_GATE"] != "PASS":
        return {"gate_id": PRE_OOS_GATE_ID, "PRE_OOS_RESULT": "NOT_REACHED",
                "reason": gate["verdict"], "thresholds_unchanged": True}

    axes = {
        "WALK_FORWARD": _walk_forward(units),
        "YEAR_STABILITY": _stability_axis(units, lambda u: u.day[:4], "YEAR_STABILITY"),
        "SYMBOL_STABILITY": _stability_axis(units, lambda u: u.symbol, "SYMBOL_STABILITY"),
        "SESSION_STABILITY": _stability_axis(units, lambda u: u.session, "SESSION_STABILITY"),
        "BRANCH_STABILITY": _stability_axis(units, lambda u: u.branch or "NO_BRANCH",
                                            "BRANCH_STABILITY"),
        "REGIME_STABILITY": _stability_axis(units, lambda u: u.regime, "REGIME_STABILITY"),
        "TAIL_DEPENDENCE": _tail_dependence(units),
        "BOOTSTRAP": _bootstrap(units),
        "CONCENTRATION": _concentration(units),
        "STRUCTURAL_CAPABILITY": _structural_capability(units),
        "PARAMETER_NEIGHBORHOOD": {
            "axis": "PARAMETER_NEIGHBORHOOD",
            "state": "NOT_APPLICABLE_EMPTY_PARAMETER_VECTOR",
            "explanation": "V2 has no free numeric parameter, so there is no neighbourhood "
                           "to perturb and no parameter sensitivity to measure. This axis is "
                           "reported as NOT_APPLICABLE rather than silently PASSED; a "
                           "reviewer who disagrees should treat the gate as incomplete.",
            "counts_toward_pass": False,
        },
        "FRICTION_READINESS": {
            "axis": "FRICTION_READINESS",
            "state": "PASS" if friction_disclosed else "FAIL",
            "mode": "STRUCTURAL_DISCLOSURE",
            "ECONOMIC_EDGE": "NOT_ESTIMABLE",
        },
        "DATASET_ROLE_VALIDATION": {
            "axis": "DATASET_ROLE_VALIDATION",
            "state": "PASS" if dataset_role_valid else "FAIL",
            "OOS_OPENED": "NO", "HOLDOUT_TOUCHED": "NO",
        },
        "CANDIDATE_IDENTITY_VALIDATION": {
            "axis": "CANDIDATE_IDENTITY_VALIDATION",
            "state": "PASS" if identity_valid else "FAIL",
        },
    }
    decisive = {k: v for k, v in axes.items()
                if v.get("counts_toward_pass", True)}
    failed = sorted(k for k, v in decisive.items() if v["state"] != "PASS")
    result = "PASS" if not failed else "FAIL"
    return {
        "gate_id": PRE_OOS_GATE_ID,
        "semantics": "FAIL_CLOSED — the gate passes only if every decisive axis is PASS",
        "thresholds_unchanged": True,
        "PRE_OOS_RESULT": result,
        "failed_axes": failed,
        "not_applicable_axes": sorted(k for k, v in axes.items()
                                      if not v.get("counts_toward_pass", True)),
        "axes": axes,
        "expectancy_metric": "realised structural R per completed trade "
                             "(target reached -> +natural_target_R, stop -> -1R, "
                             "horizon -> mark-to-close R). No friction is modelled.",
        "year_stability_note": "V1 could only run an intra-year substitution because its "
                               "authority covered one calendar year. V2 runs TRUE calendar-"
                               "year stability over the multi-year corpus; the V1 standing "
                               "limitation no longer applies.",
    }
