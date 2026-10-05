"""V2.1 FUNNEL + ROBUSTNESS instrumentation (Mission 3B-A, Phases 7 and 9).

Prepared, not executed against any real corpus. Robustness semantics and every
threshold are reused UNCHANGED from PRE_OOS_ROBUSTNESS_GATE_V1.
"""
from __future__ import annotations

import random
import statistics
from collections import defaultdict
from typing import Callable, Sequence

from ag_edgelab.strategies import asian_liquidity_displacement_v2_1 as V
from ag_edgelab.strategies.asian_liquidity_displacement_prereg import (
    BOOTSTRAP_CONFIDENCE,
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    PRE_OOS_GATE_ID,
    STABILITY_MAX_RELATIVE_SPIKE,
    STABILITY_MIN_POSITIVE_FRACTION,
    STRATUM_MIN_N,
)
from ag_edgelab.strategies.asian_liquidity_displacement_v2_1_prereg import (
    BRANCH_MIN_N,
    SAMPLE_FLOOR,
)
from ag_edgelab.universal.fx_dev_campaign import (
    CONTINUATION_REACH_1R_MIN,
    CONTINUATION_REACH_3R_MIN,
    MIN_ENTERED_N,
)

#: Reported funnel order (Phase 7 minimum set, in contract order).
REPORTED_STAGES: tuple[str, ...] = (
    "OPPORTUNITY", "CONTEXT_ELIGIBLE", "LOCATION_ELIGIBLE", "SESSION_EVENT",
    "STRUCTURE_CONFIRM", "ENTRY_AVAILABLE", "GEOMETRY_VALID", "TRADE_COMPLETED",
)

REPORT_DIMENSIONS: tuple[str, ...] = (
    "pooled", "symbol", "session", "branch", "year",
    "symbol_session", "branch_symbol", "branch_session",
)


def _pct(num: int, den: int) -> float | None:
    return round(100.0 * num / den, 6) if den else None


def _year(row: dict) -> str:
    return str(row["trading_date"])[:4]


DIMENSION_KEYS: dict[str, Callable[[dict], str]] = {
    "symbol": lambda r: r["symbol"],
    "session": lambda r: r["session"],
    "branch": lambda r: r.get("branch") or "NO_BRANCH",
    "year": _year,
    "symbol_session": lambda r: f"{r['symbol']}|{r['session']}",
    "branch_symbol": lambda r: f"{r.get('branch') or 'NO_BRANCH'}|{r['symbol']}",
    "branch_session": lambda r: f"{r.get('branch') or 'NO_BRANCH'}|{r['session']}",
}


def stage_counts(trades: Sequence[dict]) -> dict[str, int]:
    out = {s: 0 for s in REPORTED_STAGES}
    for t in trades:
        for stage, ok in t["stages"].items():
            if ok and stage in out:
                out[stage] += 1
    return out


def funnel_table(trades: Sequence[dict]) -> list[dict]:
    """N, % previous stage, % original opportunities, per transition."""
    counts = stage_counts(trades)
    base = counts.get("OPPORTUNITY", 0)
    rows, prev = [], base
    for stage in REPORTED_STAGES:
        n = counts[stage]
        rows.append({
            "stage": stage, "N": n,
            "NEXT_STAGE_PERCENT": _pct(n, prev),
            "PCT_OF_PREVIOUS_STAGE": _pct(n, prev),
            "PCT_OF_OPPORTUNITIES": _pct(n, base),
            "INPUT_N": prev, "FAIL_N": max(prev - n, 0),
        })
        prev = n
    return rows


def funnel_by_dimension(trades: Sequence[dict]) -> dict:
    """Every required reporting dimension, including pooled."""
    out: dict = {"pooled": funnel_table(trades)}
    for dim, keyfn in DIMENSION_KEYS.items():
        buckets: dict[str, list[dict]] = defaultdict(list)
        for t in trades:
            buckets[keyfn(t)].append(t)
        out[dim] = {k: funnel_table(v) for k, v in sorted(buckets.items())}
    return out


def rejection_breakdown(trades: Sequence[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for t in trades:
        if t.get("reject_reason"):
            counts[t["reject_reason"]] += 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def transition_counts(transitions: Sequence[dict]) -> dict[str, int]:
    """Branch-specific state transitions, retained alongside the funnel."""
    counts: dict[str, int] = defaultdict(int)
    for t in transitions:
        counts[f"{t['branch']}:{t['from_state']}->{t['to_state']}"] += 1
    return dict(sorted(counts.items()))


# ---------------------------------------------------------------------------
# Outcome helpers
# ---------------------------------------------------------------------------

def completed(trades: Sequence[dict]) -> list[dict]:
    return [t for t in trades if t["stages"].get("TRADE_COMPLETED")]


def expectancy(trades: Sequence[dict]) -> float | None:
    rows = [t["realised_r"] for t in completed(trades) if t["realised_r"] is not None]
    return round(statistics.fmean(rows), 6) if rows else None


def target_capability(trades: Sequence[dict]) -> dict:
    done = completed(trades)
    n = len(done)
    cap = {f"{k}R": (round(sum(1 for t in done if t["reached"].get(f"{k}R")) / n, 6)
                     if n else None) for k in V.FIXED_R_TARGETS}
    nat = [t["natural_target_r"] for t in done if t["natural_target_r"] is not None]
    return {
        "TRADE_COMPLETED_N": n,
        "fixed_r_capability_DIAGNOSTIC_ONLY": cap,
        "MEDIAN_NATURAL_TARGET_R": round(statistics.median(nat), 6) if nat else None,
        "NATURAL_TARGET_REACHED_RATE": (
            round(sum(1 for t in done if t["outcome"] == "NATURAL_TARGET_REACHED") / n, 6)
            if n else None),
        "target_authority_mix": dict(sorted(
            (lambda c: c)({a: sum(1 for t in done if t["target_authority"] == a)
                           for a in V.TARGET_AUTHORITY_ORDER}).items())),
    }


def sample_gate(trades: Sequence[dict]) -> dict:
    n = sum(1 for t in trades if t["stages"].get("ENTRY_AVAILABLE"))
    ok = n >= SAMPLE_FLOOR
    return {"ENTRY_AVAILABLE_N": n, "SAMPLE_FLOOR": SAMPLE_FLOOR,
            "SAMPLE_GATE": "PASS" if ok else "FAIL",
            "verdict": None if ok else "DEV_REJECTED_INSUFFICIENT_SAMPLE",
            "relaxation_after_results": "FORBIDDEN"}


def branch_report(trades: Sequence[dict]) -> dict:
    """Branches are flagged when underpowered. They are NEVER deleted."""
    out = {}
    for branch in [b.value for b in V.Branch]:
        sub = [t for t in trades if t.get("branch") == branch]
        done = completed(sub)
        out[branch] = {
            "ENTRY_AVAILABLE_N": sum(1 for t in sub if t["stages"].get("ENTRY_AVAILABLE")),
            "TRADE_COMPLETED_N": len(done),
            "expectancy_R": expectancy(sub),
            "state": "BRANCH_POWERED" if len(done) >= BRANCH_MIN_N else "BRANCH_UNDERPOWERED",
            "branch_min_n": BRANCH_MIN_N,
            "deletion_policy": "A branch is never deleted for being unprofitable.",
        }
    return out


# ---------------------------------------------------------------------------
# PHASE 9 — robustness axes, thresholds UNCHANGED
# ---------------------------------------------------------------------------

def _stability(trades: Sequence[dict], keyfn, axis: str) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in completed(trades):
        groups[keyfn(t)].append(t)
    slices = {k: {"n": len(v), "expectancy_R": expectancy(v),
                  "qualifying": len(v) >= STRATUM_MIN_N}
              for k, v in sorted(groups.items())}
    qual = {k: v for k, v in slices.items() if v["qualifying"]}
    frac = (round(sum(1 for v in qual.values() if (v["expectancy_R"] or 0) > 0)
                  / len(qual), 6) if qual else None)
    vals = [abs(v["expectancy_R"]) for v in qual.values() if v["expectancy_R"] is not None]
    spike = (round(max(vals) / statistics.fmean(vals), 6)
             if vals and statistics.fmean(vals) > 0 else None)
    state = ("INSUFFICIENT_SAMPLE" if frac is None else
             "PASS" if (frac >= STABILITY_MIN_POSITIVE_FRACTION
                        and (spike is None or spike <= STABILITY_MAX_RELATIVE_SPIKE))
             else "FAIL")
    return {"axis": axis, "state": state, "slices": slices,
            "qualifying_n": len(qual), "positive_fraction": frac,
            "required_positive_fraction": STABILITY_MIN_POSITIVE_FRACTION,
            "relative_spike": spike,
            "max_relative_spike": STABILITY_MAX_RELATIVE_SPIKE,
            "min_slice_n": STRATUM_MIN_N}


def _bootstrap(trades: Sequence[dict]) -> dict:
    rows = [t["realised_r"] for t in completed(trades) if t["realised_r"] is not None]
    if len(rows) < MIN_ENTERED_N:
        return {"axis": "BOOTSTRAP", "state": "INSUFFICIENT_SAMPLE", "n": len(rows)}
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(rows)
    means = sorted(statistics.fmean([rows[rng.randrange(n)] for _ in range(n)])
                   for _ in range(BOOTSTRAP_SAMPLES))
    alpha = (1.0 - BOOTSTRAP_CONFIDENCE) / 2.0
    lo = means[int(alpha * BOOTSTRAP_SAMPLES)]
    hi = means[min(BOOTSTRAP_SAMPLES - 1, int((1 - alpha) * BOOTSTRAP_SAMPLES))]
    return {"axis": "BOOTSTRAP", "state": "PASS" if lo > 0 else "FAIL",
            "samples": BOOTSTRAP_SAMPLES, "seed": BOOTSTRAP_SEED,
            "confidence": BOOTSTRAP_CONFIDENCE,
            "point_estimate_R": round(statistics.fmean(rows), 6),
            "ci_low_R": round(lo, 6), "ci_high_R": round(hi, 6)}


def _tail_dependence(trades: Sequence[dict]) -> dict:
    rows = sorted((t["realised_r"] for t in completed(trades)
                   if t["realised_r"] is not None), reverse=True)
    if not rows:
        return {"axis": "TAIL_DEPENDENCE", "state": "INSUFFICIENT_SAMPLE"}
    full = statistics.fmean(rows)
    d1 = statistics.fmean(rows[1:]) if len(rows) > 1 else None
    k = max(1, int(round(0.05 * len(rows))))
    d5 = statistics.fmean(rows[k:]) if len(rows) > k else None
    ok = all(v is not None and v > 0 for v in (d1, d5))
    return {"axis": "TAIL_DEPENDENCE", "state": "PASS" if ok else "FAIL",
            "expectancy_R": round(full, 6),
            "without_best_trade": round(d1, 6) if d1 is not None else None,
            "without_best_5pct": round(d5, 6) if d5 is not None else None,
            "trades_removed_at_5pct": k}


def _pooled_expectancy(trades: Sequence[dict]) -> dict:
    e = expectancy(trades)
    return {"axis": "POOLED_EXPECTANCY",
            "state": ("INSUFFICIENT_SAMPLE" if e is None else
                      "PASS" if e > 0 else "FAIL"),
            "expectancy_R": e,
            "friction": "NONE MODELLED — structural R only"}


def _target_capability_axis(trades: Sequence[dict]) -> dict:
    cap = target_capability(trades)
    fixed = cap["fixed_r_capability_DIAGNOSTIC_ONLY"]
    n = cap["TRADE_COMPLETED_N"]
    if n < MIN_ENTERED_N:
        return {"axis": "TARGET_CAPABILITY", "state": "INSUFFICIENT_SAMPLE", "n": n}
    ok = ((fixed["1R"] or 0) >= CONTINUATION_REACH_1R_MIN
          and (fixed["3R"] or 0) >= CONTINUATION_REACH_3R_MIN)
    return {"axis": "TARGET_CAPABILITY", "state": "PASS" if ok else "FAIL",
            "reach_1R": fixed["1R"], "reach_1R_min": CONTINUATION_REACH_1R_MIN,
            "reach_3R": fixed["3R"], "reach_3R_min": CONTINUATION_REACH_3R_MIN,
            "n": n, "source": "frozen V0.3 floors, unchanged"}


def parameter_neighborhood_axis() -> dict:
    """V2.1 has free magnitudes but perturbing them is PARAMETER SEARCH.

    The frozen authority gives this axis no V2.1-specific semantics, so it is
    reported NOT_APPLICABLE with counts_toward_pass = false rather than being
    silently passed. It is never a PASS by default.
    """
    values = V.parameter_contract()["values"]
    return {
        "axis": "PARAMETER_NEIGHBORHOOD",
        "state": "NOT_APPLICABLE",
        "counts_toward_pass": False,
        "parameter_vector_size": len(values),
        "parameters": dict(sorted(values.items())),
        "explanation": (
            "The 2.1.0 contract does carry frozen magnitudes, but perturbing "
            "them to measure sensitivity is precisely the parameter search "
            "this research programme forbids, and no frozen authority defines "
            "a neighbourhood for them. The axis is therefore reported as "
            "NOT_APPLICABLE with counts_toward_pass = false. It is NEVER a "
            "silent PASS: a reviewer who considers the gate incomplete "
            "without it should treat the overall result as incomplete."
        ),
        "resolution_required_from": "contract owner / auditor",
    }


ROBUSTNESS_AXES: tuple[str, ...] = (
    "POOLED_EXPECTANCY", "BOOTSTRAP", "YEAR_STABILITY", "SYMBOL_STABILITY",
    "SESSION_STABILITY", "BRANCH_STABILITY", "REGIME_STABILITY",
    "TAIL_DEPENDENCE", "TARGET_CAPABILITY", "PARAMETER_NEIGHBORHOOD",
)


def robustness_report(trades: Sequence[dict], *,
                      regime_of: Callable[[dict], str] | None = None) -> dict:
    """All ten axes. Fail-closed; thresholds unchanged from V1."""
    gate = sample_gate(trades)
    if gate["SAMPLE_GATE"] != "PASS":
        return {"gate_id": PRE_OOS_GATE_ID, "PRE_OOS_RESULT": "NOT_REACHED",
                "reason": gate["verdict"], "thresholds_unchanged": True,
                "axes": {a: {"axis": a, "state": "NOT_RUN_INSUFFICIENT_SAMPLE"}
                         for a in ROBUSTNESS_AXES}}

    regime_key = regime_of or (lambda t: t.get("regime") or "UNCLASSIFIED")
    axes = {
        "POOLED_EXPECTANCY": _pooled_expectancy(trades),
        "BOOTSTRAP": _bootstrap(trades),
        "YEAR_STABILITY": _stability(trades, _year, "YEAR_STABILITY"),
        "SYMBOL_STABILITY": _stability(trades, lambda t: t["symbol"], "SYMBOL_STABILITY"),
        "SESSION_STABILITY": _stability(trades, lambda t: t["session"], "SESSION_STABILITY"),
        "BRANCH_STABILITY": _stability(trades, lambda t: t.get("branch") or "NO_BRANCH",
                                       "BRANCH_STABILITY"),
        "REGIME_STABILITY": _stability(trades, regime_key, "REGIME_STABILITY"),
        "TAIL_DEPENDENCE": _tail_dependence(trades),
        "TARGET_CAPABILITY": _target_capability_axis(trades),
        "PARAMETER_NEIGHBORHOOD": parameter_neighborhood_axis(),
    }
    decisive = {k: v for k, v in axes.items() if v.get("counts_toward_pass", True)}
    failed = sorted(k for k, v in decisive.items() if v["state"] != "PASS")
    return {
        "gate_id": PRE_OOS_GATE_ID,
        "semantics": "FAIL_CLOSED — passes only if every decisive axis is PASS",
        "thresholds_unchanged": True,
        "PRE_OOS_RESULT": "PASS" if not failed else "FAIL",
        "failed_axes": failed,
        "not_applicable_axes": sorted(k for k, v in axes.items()
                                      if not v.get("counts_toward_pass", True)),
        "axes": axes,
        "expectancy_metric": (
            "realised structural R per completed trade. No friction modelled; "
            "ECONOMIC_EDGE remains NOT_ESTIMABLE."),
    }
