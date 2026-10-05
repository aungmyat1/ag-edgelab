"""The robustness axes. Each returns evidence; none returns a verdict.

Separating measurement from judgement matters here. These functions
compute distributions, shares and intervals and say nothing about
whether a candidate deserves an OOS window; :mod:`gate` applies the
frozen thresholds to what they produce. That split is what lets the
thresholds be preregistered independently of the measurement code.

Reuse is deliberate and load-bearing:

* :func:`ag_edgelab.statistics.performance.compute_performance` for
  trade statistics, so drawdown and profit factor mean here exactly what
  they mean everywhere else in the project.
* :func:`ag_edgelab.statistics.bootstrap.bootstrap_expectancy_ci` for
  every interval, including capability shares — a capability is the mean
  of an indicator variable, so the existing mean bootstrap covers it
  without a second resampler to keep in sync.
* :func:`ag_edgelab.optimization.stability.assess_parameter_stability`
  for the parameter neighbourhood.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime

from ag_edgelab.optimization.stability import assess_parameter_stability
from ag_edgelab.statistics.bootstrap import bootstrap_expectancy_ci
from ag_edgelab.statistics.performance import compute_performance
from ag_edgelab.verification.pre_oos.observations import Observation

CAPABILITY_LEVELS: tuple[float, ...] = (1.0, 2.0, 3.0, 4.0, 5.0)


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------

def capability(rs: list[float], level: float) -> float | None:
    """Share of outcomes reaching at least ``level`` R."""
    if not rs:
        return None
    return sum(1 for r in rs if r >= level) / len(rs)


def _quantile(sorted_values: list[float], q: float) -> float | None:
    """Linear-interpolated quantile, matching the repository bootstrap."""
    if not sorted_values:
        return None
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    w = pos - lo
    return sorted_values[lo] * (1 - w) + sorted_values[hi] * w


def describe(rs: list[float]) -> dict:
    """Full distribution summary for a population of R outcomes."""
    if not rs:
        return {"n": 0, "mean_r": None, "median_r": None, "gross_r": 0.0,
                "max_drawdown_r": None, "profit_factor": None,
                "capability": {f"{int(l)}R": None for l in CAPABILITY_LEVELS},
                "status": "NULL"}
    perf = compute_performance(rs)
    ordered = sorted(rs)
    mean_r = perf.expectancy_r
    return {
        "n": len(rs),
        "mean_r": mean_r,
        "median_r": statistics.median(rs),
        "gross_r": perf.total_r,
        "max_drawdown_r": perf.max_drawdown_r,
        "profit_factor": (None if perf.profit_factor is None
                          else (None if math.isinf(perf.profit_factor)
                                else perf.profit_factor)),
        "profit_factor_infinite": (perf.profit_factor is not None
                                   and math.isinf(perf.profit_factor)),
        "win_rate": perf.win_rate,
        "capability": {f"{int(l)}R": capability(rs, l)
                       for l in CAPABILITY_LEVELS},
        "percentiles": {
            "P10": _quantile(ordered, 0.10), "P25": _quantile(ordered, 0.25),
            "P50": _quantile(ordered, 0.50), "P75": _quantile(ordered, 0.75),
            "P90": _quantile(ordered, 0.90), "P95": _quantile(ordered, 0.95),
            "P99": _quantile(ordered, 0.99),
        },
        "min_r": ordered[0],
        "max_r": ordered[-1],
        "status": ("POSITIVE" if mean_r > 0 else
                   "NEGATIVE" if mean_r < 0 else "NULL"),
    }


def _rs(observations: list[Observation]) -> list[float]:
    return [o.gross_r for o in observations if o.gross_r is not None]


# ---------------------------------------------------------------------------
# sample sufficiency
# ---------------------------------------------------------------------------

def sample_sufficiency(observations: list[Observation]) -> dict:
    resolved = [o for o in observations if o.is_resolved]
    years = sorted({o.year for o in resolved})
    symbols = sorted({o.symbol for o in resolved})
    return {
        "offered": len(observations),
        "resolved": len(resolved),
        "unresolved": len(observations) - len(resolved),
        "distinct_years": len(years),
        "years": years,
        "distinct_symbols": len(symbols),
        "symbols": symbols,
        "per_year_n": {str(y): sum(1 for o in resolved if o.year == y)
                       for y in years},
        "per_symbol_n": {s: sum(1 for o in resolved if o.symbol == s)
                         for s in symbols},
        "unresolved_policy": ("excluded from metrics and counted; never "
                              "coerced to zero R"),
    }


# ---------------------------------------------------------------------------
# walk-forward
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Fold:
    fold_id: str
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime

    def __post_init__(self):
        if not (self.train_start < self.train_end <= self.test_start
                < self.test_end):
            raise ValueError(
                f"fold {self.fold_id} is not chronological: train "
                f"[{self.train_start}, {self.train_end}) must precede test "
                f"[{self.test_start}, {self.test_end})")


def assert_folds_ordered(folds: list[Fold]) -> None:
    """Test windows must not overlap; train must never follow test."""
    previous_end = None
    for fold in folds:
        if previous_end is not None and fold.test_start < previous_end:
            raise ValueError(
                f"walk-forward test windows overlap at {fold.fold_id}: "
                f"{fold.test_start} < previous end {previous_end}. Overlapping "
                "test windows double-count outcomes and inflate stability.")
        previous_end = fold.test_end


def walk_forward(observations: list[Observation], folds: list[Fold],
                 *, natural_target_median: float | None = None) -> dict:
    """Evaluate a FROZEN candidate fold by fold. No refitting happens here."""
    assert_folds_ordered(folds)
    rows = []
    for fold in folds:
        inside = [o for o in observations
                  if fold.test_start <= o.timestamp_utc < fold.test_end
                  and o.is_resolved]
        rs = _rs(inside)
        summary = describe(rs)
        per_symbol = {}
        for symbol in sorted({o.symbol for o in inside}):
            per_symbol[symbol] = describe(
                _rs([o for o in inside if o.symbol == symbol]))
        rows.append({
            "fold_id": fold.fold_id,
            "train_window": [fold.train_start.isoformat(),
                             fold.train_end.isoformat()],
            "validation_window": [fold.test_start.isoformat(),
                                  fold.test_end.isoformat()],
            "natural_target_median_r": natural_target_median,
            "pooled": summary,
            "per_symbol": per_symbol,
        })
    qualifying = [r for r in rows if r["pooled"]["n"] > 0]
    positive = [r for r in qualifying if r["pooled"]["status"] == "POSITIVE"]
    return {
        "fold_count": len(rows),
        "qualifying_fold_count": len(qualifying),
        "positive_fold_count": len(positive),
        "positive_fold_fraction": (len(positive) / len(qualifying)
                                   if qualifying else None),
        "refitting_performed": False,
        "note": ("the candidate is frozen; folds measure stability of one "
                 "fixed rule set, never a re-optimised one"),
        "folds": rows,
    }


# ---------------------------------------------------------------------------
# leave-one-out
# ---------------------------------------------------------------------------

def _loo(observations: list[Observation], key, label: str) -> dict:
    resolved = [o for o in observations if o.is_resolved]
    baseline = describe(_rs(resolved))
    groups = sorted({key(o) for o in resolved})
    rows = []
    for group in groups:
        kept = [o for o in resolved if key(o) != group]
        removed = [o for o in resolved if key(o) == group]
        result = describe(_rs(kept))
        base_mean = baseline["mean_r"]
        loo_mean = result["mean_r"]
        delta = (None if base_mean is None or loo_mean is None
                 else loo_mean - base_mean)
        relative = (None if delta is None or base_mean in (None, 0)
                    else abs(delta) / abs(base_mean))
        sign_flip = (base_mean is not None and loo_mean is not None
                     and base_mean > 0 >= loo_mean)
        rows.append({
            label: str(group),
            "baseline_metric": base_mean,
            "loo_metric": loo_mean,
            "delta": delta,
            "relative_delta": relative,
            "sign_flip": sign_flip,
            "observation_n": len(kept),
            "removed_n": len(removed),
            "removed_gross_r": sum(_rs(removed)),
        })
    return {
        "metric": "mean_gross_r",
        "baseline": baseline,
        "group_count": len(groups),
        "results": rows,
        "max_relative_delta": max(
            (r["relative_delta"] for r in rows
             if r["relative_delta"] is not None), default=None),
        "any_sign_flip": any(r["sign_flip"] for r in rows),
    }


def leave_one_year_out(observations: list[Observation]) -> dict:
    return _loo(observations, lambda o: o.year, "year_removed")


def leave_one_symbol_out(observations: list[Observation]) -> dict:
    out = _loo(observations, lambda o: o.symbol, "excluded_symbol")
    resolved = [o for o in observations if o.is_resolved]
    out["per_symbol_independent"] = {
        s: describe(_rs([o for o in resolved if o.symbol == s]))
        for s in sorted({o.symbol for o in resolved})
    }
    out["note"] = ("per-symbol evidence is reported independently so a pooled "
                   "result cannot hide four materially different behaviours")
    return out


# ---------------------------------------------------------------------------
# regime
# ---------------------------------------------------------------------------

def regime_robustness(observations: list[Observation]) -> dict:
    resolved = [o for o in observations if o.is_resolved and o.regime]
    unlabelled = [o for o in observations if o.is_resolved and not o.regime]
    all_rs = _rs(resolved)
    total_positive = sum(r for r in all_rs if r > 0)
    total_negative = sum(r for r in all_rs if r < 0)

    cells = {}
    for cell in sorted({o.regime for o in resolved}):
        rows = [o for o in resolved if o.regime == cell]
        rs = _rs(rows)
        pos = sum(r for r in rs if r > 0)
        neg = sum(r for r in rs if r < 0)
        summary = describe(rs)
        summary["share_of_total_positive_r"] = (
            pos / total_positive if total_positive > 0 else None)
        summary["share_of_total_negative_r"] = (
            neg / total_negative if total_negative < 0 else None)
        cells[cell] = summary
    return {
        "cells": cells,
        "cell_count": len(cells),
        "unlabelled_n": len(unlabelled),
        "total_positive_r": total_positive,
        "total_negative_r": total_negative,
        "max_single_cell_positive_share": max(
            (c["share_of_total_positive_r"] for c in cells.values()
             if c["share_of_total_positive_r"] is not None), default=None),
    }


# ---------------------------------------------------------------------------
# tail contribution
# ---------------------------------------------------------------------------

def winsorize(rs: list[float], level: float) -> list[float]:
    """Clip symmetrically at the (1-level, level) quantiles. Diagnostic only."""
    if not rs:
        return []
    ordered = sorted(rs)
    lo = _quantile(ordered, 1.0 - level)
    hi = _quantile(ordered, level)
    return [min(max(r, lo), hi) for r in rs]


def tail_contribution(observations: list[Observation],
                      *, winsor_levels: tuple[float, ...]) -> dict:
    rs = _rs([o for o in observations if o.is_resolved])
    summary = describe(rs)
    if not rs:
        return {"n": 0, "distribution": summary, "shares": {},
                "winsorized": {}, "note": "no resolved observations"}

    ordered_desc = sorted(rs, reverse=True)
    total_positive = sum(r for r in rs if r > 0)
    shares = {}
    for pct, key in ((0.01, "TOP_1_PCT_POSITIVE_R_SHARE"),
                     (0.05, "TOP_5_PCT_POSITIVE_R_SHARE"),
                     (0.10, "TOP_10_PCT_POSITIVE_R_SHARE")):
        k = max(1, math.ceil(pct * len(rs)))
        top = ordered_desc[:k]
        contribution = sum(r for r in top if r > 0)
        shares[key] = {
            "k": k,
            "share": (contribution / total_positive
                      if total_positive > 0 else None),
            "contributed_r": contribution,
        }

    winsorized = {}
    for level in winsor_levels:
        clipped = winsorize(rs, level)
        w_mean = sum(clipped) / len(clipped)
        winsorized[f"WINSORIZED_{int(level * 100)}"] = {
            "mean_r": w_mean,
            "median_r": statistics.median(clipped),
            "gross_r": sum(clipped),
            "sign_flip_vs_canonical": (
                summary["mean_r"] is not None
                and summary["mean_r"] > 0 >= w_mean),
        }
    return {
        "n": len(rs),
        "distribution": summary,
        "total_positive_r": total_positive,
        "total_negative_r": sum(r for r in rs if r < 0),
        "shares": shares,
        "winsorized": winsorized,
        "winsorization_policy": ("DIAGNOSTIC ONLY — the canonical metric is "
                                 "never replaced by a winsorized value"),
    }


# ---------------------------------------------------------------------------
# mean / median divergence
# ---------------------------------------------------------------------------

def mean_median_analysis(observations: list[Observation],
                         *, frequent_rate: float,
                         divergence_ratio: float) -> dict:
    rs = _rs([o for o in observations if o.is_resolved])
    if not rs:
        return {"n": 0, "shape": "NO_EVIDENCE"}
    n = len(rs)
    mean_r = sum(rs) / n
    median_r = statistics.median(rs)
    positive_rate = sum(1 for r in rs if r > 0) / n
    negative_rate = sum(1 for r in rs if r < 0) / n
    zero_rate = sum(1 for r in rs if r == 0) / n
    divergence = mean_r - median_r
    relative_divergence = (abs(divergence) / abs(mean_r)
                           if mean_r not in (0,) else None)

    asymmetric = mean_r > 0 >= median_r
    tail_driven = (relative_divergence is not None
                   and relative_divergence >= divergence_ratio)

    if positive_rate >= frequent_rate and mean_r > 0:
        shape = "FREQUENT_SMALL_WINS"
    elif negative_rate >= frequent_rate and mean_r > 0:
        shape = "RARE_LARGE_WINNER"
    elif negative_rate >= frequent_rate and mean_r <= 0:
        shape = "FREQUENT_SMALL_LOSSES"
    elif positive_rate >= frequent_rate and mean_r <= 0:
        shape = "RARE_LARGE_LOSER"
    else:
        shape = "BALANCED_DISTRIBUTION"
    if asymmetric and shape == "FREQUENT_SMALL_WINS":
        shape = "RARE_LARGE_WINNER"

    return {
        "n": n,
        "MEAN_R": mean_r,
        "MEDIAN_R": median_r,
        "MEAN_MINUS_MEDIAN_R": divergence,
        "relative_divergence": relative_divergence,
        "POSITIVE_OUTCOME_RATE": positive_rate,
        "NEGATIVE_OUTCOME_RATE": negative_rate,
        "ZERO_OUTCOME_RATE": zero_rate,
        "asymmetric_tail_dependence": asymmetric,
        "mean_is_tail_driven": tail_driven,
        "shape": shape,
        "shape_rules": {
            "FREQUENT_SMALL_WINS": "positive_rate >= frequent_rate and mean > 0",
            "RARE_LARGE_WINNER":
                "negative_rate >= frequent_rate and mean > 0, or mean > 0 >= median",
            "FREQUENT_SMALL_LOSSES":
                "negative_rate >= frequent_rate and mean <= 0",
            "RARE_LARGE_LOSER": "positive_rate >= frequent_rate and mean <= 0",
            "BALANCED_DISTRIBUTION": "otherwise",
        },
    }


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------

def bootstrap_uncertainty(observations: list[Observation], *, samples: int,
                          seed: int, confidence: float) -> dict:
    """Confidence intervals for the canonical structural metrics.

    Capability shares are bootstrapped as the mean of a 0/1 indicator,
    which lets the repository's single mean-bootstrap serve every metric
    instead of introducing a second resampler that could drift from it.
    """
    rs = _rs([o for o in observations if o.is_resolved])
    out: dict[str, dict] = {}

    def record(name: str, values: list[float], offset: int) -> None:
        interval = bootstrap_expectancy_ci(
            values, samples=samples, seed=seed + offset,
            confidence=confidence)
        out[name] = {
            "estimate": interval.estimate,
            "CI_LOW": interval.low,
            "CI_HIGH": interval.high,
            "bootstrap_n": interval.samples,
            "seed": interval.seed,
        }

    record("mean_r", rs, 0)
    record("gross_r_per_trade", rs, 1)
    for i, level in enumerate((1.0, 2.0, 3.0), start=2):
        record(f"capability_{int(level)}R",
               [1.0 if r >= level else 0.0 for r in rs], i)
    return {
        "metrics": out,
        "samples": samples,
        "base_seed": seed,
        "confidence": confidence,
        "engine": "ag_edgelab.statistics.bootstrap.bootstrap_expectancy_ci",
        "capability_method": ("mean of a 0/1 indicator, so the existing mean "
                              "bootstrap covers proportions without a second "
                              "implementation"),
    }


# ---------------------------------------------------------------------------
# parameter neighborhood
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PerturbableParameter:
    """A numeric, semantically continuous frozen parameter."""

    name: str
    frozen_value: float
    semantics: str
    perturbable: bool = True
    reason_not_perturbable: str = ""


def parameter_neighborhood(
    parameters: list[PerturbableParameter],
    evaluator,
    *,
    perturbations: tuple[float, ...],
    min_positive_fraction: float,
    max_relative_spike: float,
) -> dict:
    """Probe local fragility around each frozen numeric parameter.

    ``evaluator(name, value) -> float | None`` re-evaluates the frozen
    candidate with one parameter moved. This is NOT a search: no
    neighbour is ever promoted, the frozen value is never replaced, and
    the output records only whether the result survives the neighbourhood.
    """
    if not parameters:
        return {"status": "NOT_APPLICABLE",
                "reason": ("the candidate exposes no numeric, semantically "
                           "continuous parameter; categorical rules are never "
                           "mutated and none is invented"),
                "parameters": []}

    rows = []
    for param in parameters:
        if not param.perturbable:
            rows.append({
                "PARAMETER": param.name,
                "FROZEN_VALUE": param.frozen_value,
                "status": "NOT_APPLICABLE",
                "reason": param.reason_not_perturbable,
            })
            continue
        by_value: dict[float, float] = {}
        trials = []
        for multiplier in perturbations:
            value = param.frozen_value * multiplier
            result = evaluator(param.name, value)
            trials.append({
                "PERTURBATION": multiplier,
                "value": value,
                "RESULT": result,
            })
            if result is not None:
                by_value[value] = result
        frozen_result = next(
            (t["RESULT"] for t in trials if t["PERTURBATION"] == 1.00), None)
        for t in trials:
            t["DELTA_FROM_FROZEN"] = (
                None if t["RESULT"] is None or frozen_result is None
                else t["RESULT"] - frozen_result)

        assessment = None
        if len(by_value) >= 3 and param.frozen_value in by_value:
            s = assess_parameter_stability(
                by_value, param.frozen_value,
                min_positive_fraction=min_positive_fraction,
                max_relative_spike=max_relative_spike)
            assessment = {
                "center_expectancy_r": s.center_expectancy_r,
                "neighborhood_mean_r": s.neighborhood_mean_r,
                "positive_fraction": s.positive_fraction,
                "relative_spike": s.relative_spike,
                "stable": s.stable,
            }
        rows.append({
            "PARAMETER": param.name,
            "FROZEN_VALUE": param.frozen_value,
            "semantics": param.semantics,
            "status": "EVALUATED",
            "trials": trials,
            "assessment": assessment,
        })
    evaluated = [r for r in rows if r["status"] == "EVALUATED"
                 and r.get("assessment")]
    return {
        "status": "EVALUATED" if evaluated else "NOT_APPLICABLE",
        "is_search": False,
        "promotion_policy": ("no neighbour may be promoted; the frozen value "
                             "is never replaced by a better-scoring one"),
        "parameters": rows,
        "all_stable": (all(r["assessment"]["stable"] for r in evaluated)
                       if evaluated else None),
    }
