"""Analysis layer for ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1 (DEVELOPMENT only).

Every number produced here is DESCRIPTIVE DEV evidence. Nothing in this
module selects a rule, tunes a threshold, or grants EDGE_VERIFIED. The
three-funnel view is produced by the ACCEPTED Universal Funnel Analyzer
(``ag_edgelab.analytics.diagnostic.analyze_three_funnel``); the extra
reports below only reorganize the same deterministic candidate records into
the artifacts the mission requires.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from statistics import median
from typing import Iterable, Sequence

from ag_edgelab.analytics.diagnostic import DiagnosticPolicy, analyze_three_funnel
from ag_edgelab.contracts.branching import FunnelEvent, FunnelRunResult, TradeResult
from ag_edgelab.contracts.diagnostic import (
    DiagnosticDefinition,
    DiagnosticRuleBinding,
    ExcursionObservation,
    ExitPolicyResult,
    FunnelGroup,
    StageExcursionObservation,
)
from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.statistics.bootstrap import bootstrap_expectancy_ci
from ag_edgelab.statistics.performance import compute_performance
from ag_edgelab.optimization.stability import assess_parameter_stability
from ag_edgelab.strategies.asian_liquidity_displacement_prereg import (
    BOOTSTRAP_CONFIDENCE,
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    DISPLACEMENT_NEIGHBORHOOD,
    POOLED_ENTRY_ELIGIBILITY_N,
    STABILITY_MAX_RELATIVE_SPIKE,
    STABILITY_MIN_POSITIVE_FRACTION,
    STRATUM_MIN_N,
)
from ag_edgelab.strategies.asian_liquidity_displacement_v1 import (
    CONFIRMATION_NODES,
    DISPLACEMENT_BODY_RANGE_MIN,
    FIXED_R_TARGETS,
    OBSERVATION_POLICY_ID,
    OUTCOME_NODES,
    STRATEGY_HASH,
    STRATEGY_ID,
    STRATEGY_VERSION,
    TRIGGER_NODES,
    CandidateUnit,
)
from ag_edgelab.universal.fx_dev_campaign import (
    CONTINUATION_REACH_1R_MIN,
    CONTINUATION_REACH_3R_MIN,
    MIN_DIRECTIONAL_N,
    MIN_ENTERED_N,
)

ALL_NODES: tuple[str, ...] = TRIGGER_NODES + CONFIRMATION_NODES + OUTCOME_NODES
ENTRY_OBSERVATION_POLICY_ID = (
    "ENTRY_BASIS_ALD_V1__anchor=M5_bar_after_fill;risk=|entry-sweep_extreme|;"
    "horizon=288_M5_bars;collision=STOP_FIRST"
)
_POLICY = DiagnosticPolicy()


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _hex(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _pct(num: int, den: int) -> float | None:
    return None if den == 0 else round(num / den * 100.0, 6)


def _med(values: Sequence[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(median(vals), 6) if vals else None


def _mean(values: Sequence[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 6) if vals else None


def reached_nodes(unit: CandidateUnit) -> list[tuple[str, bool]]:
    """Ordered (node, passed) pairs the candidate actually reached."""
    out: list[tuple[str, bool]] = []
    for node in TRIGGER_NODES + CONFIRMATION_NODES:
        if node not in unit.stages:
            return out
        out.append((node, unit.stages[node]))
        if not unit.stages[node]:
            return out
    for node in OUTCOME_NODES:
        if node not in unit.stages:
            return out
        out.append((node, unit.stages[node]))
        if not unit.stages[node]:
            return out
    return out


def entries(units: Iterable[CandidateUnit]) -> list[CandidateUnit]:
    return [u for u in units if u.stages.get("C6_ENTRY_AVAILABLE")]


# ---------------------------------------------------------------------------
# Universal Funnel Analyzer binding
# ---------------------------------------------------------------------------

def diagnostic_definition() -> DiagnosticDefinition:
    bindings = []
    for seq, node in enumerate(TRIGGER_NODES):
        bindings.append(DiagnosticRuleBinding(node_id=node, funnel_group=FunnelGroup.TRIGGER, sequence=seq))
    for seq, node in enumerate(CONFIRMATION_NODES):
        bindings.append(DiagnosticRuleBinding(node_id=node, funnel_group=FunnelGroup.CONFIRMATION, sequence=seq))
    for seq, node in enumerate(OUTCOME_NODES):
        bindings.append(DiagnosticRuleBinding(node_id=node, funnel_group=FunnelGroup.OUTCOME, sequence=seq))
    return DiagnosticDefinition(
        diagnostic_id="UNIVERSAL_FUNNEL_ALD_V1",
        version="1.0.0",
        strategy_sha256=STRATEGY_HASH,
        bindings=tuple(bindings),
    )


def funnel_sha256() -> str:
    return sha256_json({"TRIGGER": list(TRIGGER_NODES), "CONFIRMATION": list(CONFIRMATION_NODES),
                        "OUTCOME": list(OUTCOME_NODES), "strategy": STRATEGY_HASH})


def build_funnel_evidence(units: Sequence[CandidateUnit], dataset_sha256: str):
    """Translate candidate records into the accepted analyzer's input types."""
    from datetime import datetime, timezone

    funnel_sha = funnel_sha256()
    results: list[FunnelRunResult] = []
    stage_excursions: list[StageExcursionObservation] = []
    excursions: list[ExcursionObservation] = []
    exit_results: list[ExitPolicyResult] = []

    for unit in units:
        ts = datetime.fromisoformat(f"{unit.day}T00:00:00+00:00").astimezone(timezone.utc)
        events: list[FunnelEvent] = []
        for node, ok in reached_nodes(unit):
            events.append(FunnelEvent(
                event_id=_hex(unit.candidate_id, node),
                timestamp=ts, symbol=unit.symbol,
                dataset_sha256=dataset_sha256, funnel_sha256=funnel_sha,
                node_id=node, rule_version=STRATEGY_VERSION,
                input_json=sha256_json({"candidate": unit.candidate_id, "node": node})[:16],
                output="PASS" if ok else unit.reject_reason,
                outcome="PASS" if ok else "FAIL",
                measurements_json=sha256_json({"session": unit.session, "direction": unit.direction})[:16],
                trade_id=unit.candidate_id if unit.stages.get("C6_ENTRY_AVAILABLE") else None,
            ))
            if unit.opp_mfe_r is not None and node in TRIGGER_NODES + CONFIRMATION_NODES:
                stage_excursions.append(StageExcursionObservation(
                    candidate_id=unit.candidate_id, node_id=node,
                    mfe_r=unit.opp_mfe_r, mae_r=unit.opp_mae_r or 0.0,
                    observation_policy_id=OBSERVATION_POLICY_ID))

        trades: list[TradeResult] = []
        if unit.stages.get("C6_ENTRY_AVAILABLE") and unit.entry is not None:
            target = unit.tp2 if unit.tp2 is not None else unit.tp1
            trades.append(TradeResult(
                trade_id=unit.candidate_id,
                direction="LONG" if unit.direction == "BULL" else "SHORT",
                management="TP1_TP2_50_50_STRUCTURAL",
                entry=unit.entry, stop=unit.stop or 0.0, target=float(target),
                exit=float(unit.management_exit if unit.management_exit is not None else unit.entry),
                result_r=float(unit.management_r if unit.management_r is not None else 0.0)))
            excursions.append(ExcursionObservation(
                candidate_id=unit.candidate_id, trade_id=unit.candidate_id,
                mfe_r=float(unit.mfe_r or 0.0), mae_r=float(unit.mae_r or 0.0),
                observation_policy_id=ENTRY_OBSERVATION_POLICY_ID))
            for policy_id, value in fixed_r_policy_results(unit).items():
                exit_results.append(ExitPolicyResult(
                    candidate_id=unit.candidate_id, trade_id=unit.candidate_id,
                    policy_id=policy_id, net_result_r=value))

        results.append(FunnelRunResult(
            candidate_id=unit.candidate_id, symbol=unit.symbol,
            dataset_sha256=dataset_sha256, dataset_role="DEVELOPMENT",
            funnel_sha256=funnel_sha, events=tuple(events), trades=tuple(trades)))

    return results, stage_excursions, excursions, exit_results


def fixed_r_policy_results(unit: CandidateUnit) -> dict[str, float]:
    """Preregistered diagnostic exit policies. STRUCTURAL R only, no friction."""
    out: dict[str, float] = {}
    for k in FIXED_R_TARGETS:
        if unit.reached.get(f"{k}R"):
            out[f"FIXED_{k}R"] = float(k)
        elif unit.stopped_out:
            out[f"FIXED_{k}R"] = -1.0
        else:
            out[f"FIXED_{k}R"] = float(unit.horizon_r if unit.horizon_r is not None else 0.0)
    out["TP1_TP2_50_50"] = float(unit.management_r if unit.management_r is not None else 0.0)
    return out


def run_universal_funnel_analyzer(units: Sequence[CandidateUnit], dataset_sha256: str):
    results, stage_exc, exc, exits = build_funnel_evidence(units, dataset_sha256)
    report = analyze_three_funnel(
        diagnostic_definition(), results,
        downstream_outcomes_r={u.candidate_id: float(u.opp_mfe_r)
                               for u in units if u.opp_mfe_r is not None},
        stage_excursions=tuple(stage_exc), excursions=tuple(exc),
        exit_policy_results=tuple(exits),
        targets_r=tuple(float(k) for k in FIXED_R_TARGETS))
    return report


# ---------------------------------------------------------------------------
# Stage matrix
# ---------------------------------------------------------------------------

def stage_counts(units: Sequence[CandidateUnit]) -> dict[str, int]:
    counts = {"CANDIDATE_N": len(units)}
    for node in ALL_NODES:
        counts[node] = sum(1 for u in units if u.stages.get(node))
    counts["TRIGGER_INPUT"] = len(units)
    counts["TRIGGER_PASS"] = counts[TRIGGER_NODES[-1]]
    counts["CONFIRMATION_INPUT"] = counts["TRIGGER_PASS"]
    counts["CONFIRMATION_PASS"] = counts["C4_FVG_RETRACE_AVAILABLE"]
    counts["GEOMETRY_VALID"] = counts["C5_GEOMETRY_VALID"]
    counts["ENTRY_AVAILABLE"] = counts["C6_ENTRY_AVAILABLE"]
    for k in FIXED_R_TARGETS:
        counts[f"{k}R"] = counts[f"O{k}_{k}R"]
    return counts


def stage_matrix(units: Sequence[CandidateUnit]) -> dict:
    pooled = stage_counts(units)
    by_symbol = {}
    for sym in sorted({u.symbol for u in units}):
        by_symbol[sym] = stage_counts([u for u in units if u.symbol == sym])
    by_session = {}
    for ses in sorted({u.session for u in units}):
        by_session[ses] = stage_counts([u for u in units if u.session == ses])
    by_cell = {}
    for sym in sorted({u.symbol for u in units}):
        for ses in sorted({u.session for u in units}):
            cell = [u for u in units if u.symbol == sym and u.session == ses]
            by_cell[f"{sym}|{ses}"] = stage_counts(cell)
    return {"POOLED": pooled, "BY_SYMBOL": by_symbol, "BY_SESSION": by_session,
            "BY_SYMBOL_SESSION": by_cell}


# ---------------------------------------------------------------------------
# Funnel 1 — trigger analysis
# ---------------------------------------------------------------------------

def trigger_analysis(units: Sequence[CandidateUnit]) -> dict:
    decided = [u for u in units if u.stages.get("T2_DIRECTION_DECIDED")]
    non_neutral = [u for u in decided if u.stages.get("T3_DIRECTION_NON_NEUTRAL")]
    swept = [u for u in non_neutral if u.stages.get("T4_ASIAN_SWEEP")]
    trig = [u for u in swept if u.stages.get("T5_CLOSE_BACK_INSIDE")]

    def dist(key):
        return dict(sorted(Counter(getattr(u, key) for u in decided).items()))

    opp_all = [u.opp_mfe_r for u in non_neutral if u.opp_mfe_r is not None]
    opp_trig = [u.opp_mfe_r for u in trig if u.opp_mfe_r is not None]

    def reach(values, k):
        return None if not values else round(sum(1 for v in values if v >= k) / len(values), 6)

    return {
        "basis": "TRIGGER evidence is recorded component-by-component; no opaque composite score exists",
        "TRIGGER_INPUT": len(units),
        "DIRECTION_DECIDED": len(decided),
        "DIRECTION_NON_NEUTRAL": len(non_neutral),
        "ASIAN_SWEEP": len(swept),
        "TRIGGER_PASS": len(trig),
        "component_distributions": {
            "d1_structure": dist("d1_structure"),
            "h4_structure": dist("h4_structure"),
            "h1_flow": dist("h1_flow"),
            "premium_discount_state": dist("premium_discount_state"),
            "prev_day_context": dist("prev_day_context"),
            "regime": dist("regime"),
        },
        "liquidity_context": {
            "median_pools_above": _med([u.liquidity_context_above for u in decided]),
            "median_pools_below": _med([u.liquidity_context_below for u in decided]),
        },
        "direction_mix": dict(sorted(Counter(u.direction for u in decided).items())),
        "neutral_cause_counts": dict(sorted(Counter(
            f"D1={u.d1_structure};H4={u.h4_structure};H1={u.h1_flow}"
            for u in decided if u.direction == "NEUTRAL").items(),
            key=lambda kv: (-kv[1], kv[0]))[:12]),
        "direction_not_equal_sweep_side": {
            "contract": "BULL sweeps the Asian LOW, BEAR sweeps the Asian HIGH",
            "violations": sum(1 for u in swept if u.direction not in ("BULL", "BEAR")),
        },
        "opportunity_basis_capability": {
            "observation_policy_id": OBSERVATION_POLICY_ID,
            "non_neutral_n": len(opp_all),
            "trigger_pass_n": len(opp_trig),
            "reach_by_target_non_neutral": {f"{k}R": reach(opp_all, k) for k in FIXED_R_TARGETS},
            "reach_by_target_trigger_pass": {f"{k}R": reach(opp_trig, k) for k in FIXED_R_TARGETS},
            "median_mfe_r_non_neutral": _med(opp_all),
            "median_mfe_r_trigger_pass": _med(opp_trig),
            "selection_uplift_pp_5R": (
                None if not opp_all or not opp_trig else
                round((reach(opp_trig, 5) - reach(opp_all, 5)) * 100.0, 6)),
        },
        "rejection_counts": dict(sorted(Counter(
            u.reject_reason for u in units
            if u.reject_node in TRIGGER_NODES).items(), key=lambda kv: (-kv[1], kv[0]))),
    }


# ---------------------------------------------------------------------------
# Funnel 2 — confirmation analysis (mission section 5 sequential ordering)
# ---------------------------------------------------------------------------

SEQUENTIAL_CHAIN: tuple[tuple[str, str], ...] = (
    ("1_SWEEP", "T4_ASIAN_SWEEP"),
    ("2_CLOSE_BACK_INSIDE", "T5_CLOSE_BACK_INSIDE"),
    ("3_DISPLACEMENT", "C1_DISPLACEMENT"),
    ("4_MSS_BOS", "C2_MSS_BOS"),
    ("5_FRESH_FVG", "C3_FRESH_FVG"),
    ("6_FVG_RETRACE_AVAILABLE", "C4_FVG_RETRACE_AVAILABLE"),
)


def confirmation_analysis(units: Sequence[CandidateUnit]) -> dict:
    population = [u for u in units if u.stages.get("T3_DIRECTION_NON_NEUTRAL")]
    chain = []
    prev_n = len(population)
    for label, node in SEQUENTIAL_CHAIN:
        reached = [u for u in population if node in u.stages]
        passed = [u for u in reached if u.stages[node]]
        failed = [u for u in reached if not u.stages[node]]
        opp_in = [u.opp_mfe_r for u in reached if u.opp_mfe_r is not None]
        opp_pass = [u.opp_mfe_r for u in passed if u.opp_mfe_r is not None]

        def reach(values, k):
            return None if not values else round(sum(1 for v in values if v >= k) / len(values) * 100.0, 6)

        chain.append({
            "step": label, "node_id": node,
            "input_n": len(reached), "pass_n": len(passed), "fail_n": len(failed),
            "pass_pct_of_input": _pct(len(passed), len(reached)),
            "pass_pct_of_previous_step": _pct(len(passed), prev_n),
            "reason_counts": dict(sorted(Counter(u.reject_reason for u in failed).items(),
                                         key=lambda kv: (-kv[1], kv[0]))),
            "opportunity_reach_3R_input_pct": reach(opp_in, 3),
            "opportunity_reach_3R_pass_pct": reach(opp_pass, 3),
            "selection_uplift_3R_pp": (
                None if reach(opp_in, 3) is None or reach(opp_pass, 3) is None
                else round(reach(opp_pass, 3) - reach(opp_in, 3), 6)),
        })
        prev_n = len(passed)
    conf = [u for u in population if u.stages.get("C4_FVG_RETRACE_AVAILABLE")]
    return {
        "note": ("Steps 1-2 are the sweep/reclaim predicates that also constitute the TRIGGER "
                 "contract; they are shown here in the mission's sequential confirmation "
                 "ordering and are NOT double-counted in the funnel stage matrix."),
        "population": "DIRECTION_NON_NEUTRAL candidates",
        "population_n": len(population),
        "sequence": chain,
        "CONFIRMATION_PASS_N": len(conf),
        "displacement_rule": {"threshold": DISPLACEMENT_BODY_RANGE_MIN, "frozen": True,
                              "optimized_in_this_mission": False},
        "displacement_body_ratio_median": _med([u.displacement_body_ratio for u in units
                                                if u.displacement_body_ratio is not None]),
        "mss_primitive_mix": dict(sorted(Counter(
            u.mss_primitive for u in units if u.mss_primitive).items())),
        "same_bar_reclaim_displacement_n": sum(1 for u in units if u.same_bar_reclaim_displacement),
        "same_bar_displacement_mss_n": sum(1 for u in units if u.same_bar_displacement_mss),
    }


# ---------------------------------------------------------------------------
# Funnel 3 — target capability / continuation survival
# ---------------------------------------------------------------------------

def target_capability(units: Sequence[CandidateUnit]) -> dict:
    ent = entries(units)
    n = len(ent)

    def reach_pct(k):
        return None if n == 0 else round(sum(1 for u in ent if u.reached.get(f"{k}R")) / n, 6)

    nat = [u.natural_target_r for u in ent if u.natural_target_r is not None]
    tp1 = [u.tp1_r for u in ent if u.tp1_r is not None]
    tp2 = [u.tp2_r for u in ent if u.tp2_r is not None]
    mgmt = [u.management_r for u in ent if u.management_r is not None]
    perf = compute_performance(mgmt)
    return {
        "ENTRY_AVAILABLE_N": n,
        "economic_claim": "NOT_ESTIMABLE_NO_FRICTION_AUTHORITY — structural R only",
        "fixed_r_capability": {f"{k}R": reach_pct(k) for k in FIXED_R_TARGETS},
        "fixed_r_reached_n": {f"{k}R": sum(1 for u in ent if u.reached.get(f"{k}R"))
                              for k in FIXED_R_TARGETS},
        "MFE_R": {"median": _med([u.mfe_r for u in ent]), "mean": _mean([u.mfe_r for u in ent]),
                  "max": max([u.mfe_r for u in ent], default=None)},
        "MAE_R": {"median": _med([u.mae_r for u in ent]), "mean": _mean([u.mae_r for u in ent]),
                  "max": max([u.mae_r for u in ent], default=None)},
        "natural_target_R": {"median": _med(nat), "mean": _mean(nat), "n": len(nat)},
        "TP1_R": {"median": _med(tp1), "mean": _mean(tp1), "n": len(tp1)},
        "TP2_R": {"median": _med(tp2), "mean": _mean(tp2), "n": len(tp2),
                  "availability_pct": _pct(len(tp2), n)},
        "management_TP1_TP2_50_50": {
            "trades": perf.trades, "expectancy_r": perf.expectancy_r,
            "median_r": _med(mgmt), "total_r": perf.total_r,
            "win_rate": perf.win_rate, "profit_factor": (
                None if perf.profit_factor is None or math.isinf(perf.profit_factor)
                else perf.profit_factor),
            "max_drawdown_r": perf.max_drawdown_r,
            "max_consecutive_losses": perf.max_consecutive_losses,
        },
        "resolution_mix": dict(sorted(Counter(u.resolution for u in ent if u.resolution).items())),
        "stopped_same_bar_n": sum(1 for u in ent if u.stopped_same_bar),
    }


def continuation_survival(units: Sequence[CandidateUnit]) -> dict:
    ent = entries(units)
    reach = {k: sum(1 for u in ent if u.reached.get(f"{k}R")) for k in FIXED_R_TARGETS}
    cond = {}
    for k in FIXED_R_TARGETS[1:]:
        den = reach[k - 1]
        cond[f"P({k}R|{k-1}R)"] = None if den == 0 else round(reach[k] / den, 6)
    return {
        "ENTRY_AVAILABLE_N": len(ent),
        "reached_n": {f"{k}R": reach[k] for k in FIXED_R_TARGETS},
        "conditional_continuation": cond,
        "frozen_v0_3_floors": {"reach_1R_min": CONTINUATION_REACH_1R_MIN,
                               "reach_3R_min": CONTINUATION_REACH_3R_MIN},
        "note": "conditional probabilities are undefined (null) when the conditioning event is empty",
    }


# ---------------------------------------------------------------------------
# Temporal diagnostics
# ---------------------------------------------------------------------------

def temporal_diagnostics(units: Sequence[CandidateUnit]) -> dict:
    trig = [u for u in units if u.stages.get("T5_CLOSE_BACK_INSIDE")]
    disp = [u for u in units if u.stages.get("C1_DISPLACEMENT")]
    mss = [u for u in units if u.stages.get("C2_MSS_BOS")]
    window_bounded = ("NO_MSS_BOS_AFTER_DISPLACEMENT", "NO_FRESH_FVG_AFTER_MSS",
                      "NO_CAUSAL_RETRACE_INTO_FVG")
    post_trigger = [u for u in units if u.stages.get("T5_CLOSE_BACK_INSIDE")
                    and not u.stages.get("C6_ENTRY_AVAILABLE")]
    reasons = Counter(u.reject_reason for u in post_trigger)
    wb_n = sum(reasons[r] for r in window_bounded)
    return {
        "entry_window_m15_bars": {"median": _med([u.window_m15_bars for u in units
                                                  if u.window_m15_bars]),
                                  "contract": "3 UTC hours = 12 M15 bars per entry window"},
        "m15_bars_remaining_after_sweep": _med([u.m15_bars_after_sweep for u in units
                                                if u.m15_bars_after_sweep is not None]),
        "m15_bars_remaining_after_reclaim": _med([u.m15_bars_after_reclaim for u in trig
                                                  if u.m15_bars_after_reclaim is not None]),
        "m15_bars_remaining_after_displacement": _med([u.m15_bars_after_displacement for u in disp
                                                       if u.m15_bars_after_displacement is not None]),
        "m5_bars_remaining_after_mss": _med([u.m5_bars_after_mss for u in mss
                                             if u.m5_bars_after_mss is not None]),
        "sequential_events_still_required_after_reclaim": 4,
        "post_trigger_rejection_counts": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
        "window_bounded_rejection_n": wb_n,
        "window_bounded_rejection_share_of_post_trigger": _pct(wb_n, len(post_trigger)),
        "right_censored_n": sum(1 for u in units if u.reject_reason == "RIGHT_CENSORED_DATA_BOUNDARY"),
        "interpretation_rule": (
            "TEMPORAL_INCOMPATIBILITY is diagnosed when window-bounded failures dominate the "
            "post-trigger attrition AND the median M15 bars remaining after the reclaim bar is "
            "below the number of sequential events the contract still requires."),
    }


# ---------------------------------------------------------------------------
# Robustness battery + frozen Pre-OOS Robustness Gate V1
# ---------------------------------------------------------------------------

def _stratum(units: Sequence[CandidateUnit], key) -> dict[str, list[float]]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for u in entries(units):
        if u.management_r is not None:
            buckets[str(key(u))].append(float(u.management_r))
    return dict(sorted(buckets.items()))


def _stability_axis(buckets: dict[str, list[float]], min_n: int = STRATUM_MIN_N) -> dict:
    rows = {}
    qualifying = []
    for name, values in buckets.items():
        perf = compute_performance(values)
        rows[name] = {"n": len(values), "expectancy_r": perf.expectancy_r,
                      "median_r": _med(values), "total_r": perf.total_r,
                      "qualifying": len(values) >= min_n}
        if len(values) >= min_n:
            qualifying.append(perf.expectancy_r or 0.0)
    positive_fraction = (None if not qualifying
                         else round(sum(1 for v in qualifying if v > 0) / len(qualifying), 6))
    state = "PASS" if (positive_fraction is not None
                       and positive_fraction >= STABILITY_MIN_POSITIVE_FRACTION) else (
        "INSUFFICIENT_SAMPLE" if positive_fraction is None else "FAIL")
    return {"strata": rows, "qualifying_strata": len(qualifying),
            "min_stratum_n": min_n, "positive_fraction": positive_fraction,
            "required_positive_fraction": STABILITY_MIN_POSITIVE_FRACTION, "state": state}


def _walk_forward_buckets(units: Sequence[CandidateUnit]) -> dict[str, list[float]]:
    return _stratum(units, lambda u: u.day[:7])  # monthly, chronological, non-overlapping


def robustness_report(units: Sequence[CandidateUnit],
                      neighborhood: dict[float, float] | None = None) -> dict:
    ent = entries(units)
    mgmt = [float(u.management_r) for u in ent if u.management_r is not None]
    eligible = len(ent) >= POOLED_ENTRY_ELIGIBILITY_N

    axes: dict[str, dict] = {}
    axes["WALK_FORWARD"] = _stability_axis(_walk_forward_buckets(units))
    axes["YEAR_STABILITY"] = _stability_axis(_stratum(units, lambda u: u.quarter))
    axes["YEAR_STABILITY"]["substitution"] = (
        "INTRA_YEAR_SEGMENT_STABILITY over DEV calendar quarters — the committed FX "
        "authority covers a single calendar year (2017)")
    axes["YEAR_STABILITY"]["standing_limitation"] = "YEAR_COVERAGE_LIMITED_SINGLE_CALENDAR_YEAR_2017"
    axes["SYMBOL_STABILITY"] = _stability_axis(_stratum(units, lambda u: u.symbol))
    axes["SESSION_STABILITY"] = _stability_axis(_stratum(units, lambda u: u.session))
    axes["REGIME_STABILITY"] = _stability_axis(_stratum(units, lambda u: u.regime))
    axes["REGIME_STABILITY"]["classifier"] = (
        "ag_edgelab.verification.regimes.classify_market_state (frozen v1) on the D1 bar "
        "last closed before the entry-window open")

    # tail dependence
    if mgmt:
        ordered = sorted(mgmt, reverse=True)
        drop1 = ordered[1:]
        cut = max(1, int(math.ceil(0.05 * len(ordered))))
        drop5 = ordered[cut:]
        e_all = sum(mgmt) / len(mgmt)
        e1 = (sum(drop1) / len(drop1)) if drop1 else None
        e5 = (sum(drop5) / len(drop5)) if drop5 else None
        tail_state = "PASS" if (e1 is not None and e5 is not None and e1 > 0 and e5 > 0) else (
            "INSUFFICIENT_SAMPLE" if e1 is None or e5 is None else "FAIL")
    else:
        e_all = e1 = e5 = None
        tail_state = "INSUFFICIENT_SAMPLE"
    axes["TAIL_DEPENDENCE"] = {"expectancy_r_all": e_all, "expectancy_r_drop_best_1": e1,
                               "expectancy_r_drop_best_5pct": e5, "state": tail_state}

    # mean/median divergence
    mean_r = _mean(mgmt)
    median_r = _med(mgmt)
    if mean_r is None or median_r is None:
        mm_state = "INSUFFICIENT_SAMPLE"
    elif mean_r > 0 and median_r < 0:
        mm_state = "FAIL"
    else:
        mm_state = "PASS"
    axes["MEAN_MEDIAN_DIVERGENCE"] = {"mean_r": mean_r, "median_r": median_r,
                                      "divergence": (None if mean_r is None or median_r is None
                                                     else round(mean_r - median_r, 6)),
                                      "state": mm_state}

    # bootstrap uncertainty
    ci = bootstrap_expectancy_ci(mgmt, samples=BOOTSTRAP_SAMPLES, seed=BOOTSTRAP_SEED,
                                 confidence=BOOTSTRAP_CONFIDENCE)
    boot_state = "INSUFFICIENT_SAMPLE" if ci.low is None else ("PASS" if ci.low > 0 else "FAIL")
    axes["BOOTSTRAP"] = {"estimate_r": ci.estimate, "ci_low_r": ci.low, "ci_high_r": ci.high,
                         "samples": ci.samples, "seed": ci.seed,
                         "confidence": BOOTSTRAP_CONFIDENCE, "state": boot_state}

    # parameter neighborhood (NON-SELECTING)
    if neighborhood:
        try:
            res = assess_parameter_stability(
                neighborhood, DISPLACEMENT_BODY_RANGE_MIN,
                min_positive_fraction=STABILITY_MIN_POSITIVE_FRACTION,
                max_relative_spike=STABILITY_MAX_RELATIVE_SPIKE)
            axes["PARAMETER_NEIGHBORHOOD"] = {
                "neighborhood_expectancy_r": {str(k): v for k, v in sorted(neighborhood.items())},
                "center": res.center, "center_expectancy_r": res.center_expectancy_r,
                "neighborhood_mean_r": res.neighborhood_mean_r,
                "positive_fraction": res.positive_fraction,
                "relative_spike": res.relative_spike,
                "state": "PASS" if res.stable else "FAIL",
                "selection_authority": "NONE — diagnostic only; 0.70 remains frozen"}
        except ValueError as exc:
            axes["PARAMETER_NEIGHBORHOOD"] = {"state": "INSUFFICIENT_SAMPLE", "error": str(exc),
                                              "selection_authority": "NONE"}
    else:
        axes["PARAMETER_NEIGHBORHOOD"] = {
            "state": "NOT_RUN_INSUFFICIENT_SAMPLE",
            "reason": ("the pooled entry population never reached the preregistered eligibility "
                       f"floor of {POOLED_ENTRY_ELIGIBILITY_N}; a neighborhood diagnostic on an "
                       "empty/degenerate population would be noise, not evidence"),
            "selection_authority": "NONE — 0.70 remains frozen"}

    if not eligible:
        # Mission section 11: the robustness battery runs only when the DEV
        # sample is structurally sufficient. Measurements stay visible as
        # provisional evidence but carry NO gate authority.
        for name, payload in axes.items():
            payload["provisional_state_if_eligible"] = payload.get("state")
            payload["state"] = "NOT_RUN_INSUFFICIENT_SAMPLE"

    return {
        "eligibility": {"pooled_entry_available_n": len(ent),
                        "required": POOLED_ENTRY_ELIGIBILITY_N,
                        "eligible": eligible,
                        "stratum_min_n": STRATUM_MIN_N,
                        "preregistered_rule": "on ineligible -> PRE_OOS_RESULT = NOT_REACHED (never a PASS)"},
        "basis": "structural R under the TP1/TP2 50/50 management diagnostic; no friction applied",
        "axes": axes,
    }


def pre_oos_gate_result(units: Sequence[CandidateUnit], robustness: dict,
                        capability: dict, identity_valid: bool,
                        dataset_role_valid: bool, friction_disclosed: bool) -> dict:
    ent = entries(units)
    n = len(ent)
    checks: dict[str, dict] = {}

    eligible = robustness["eligibility"]["eligible"]
    checks["SAMPLE_ELIGIBILITY"] = {
        "state": "PASS" if eligible else "NOT_REACHED_INSUFFICIENT_SAMPLE",
        "observed": n, "required": POOLED_ENTRY_ELIGIBILITY_N}
    checks["TRIGGER_POPULATION"] = {
        "state": "PASS" if len(units) >= MIN_DIRECTIONAL_N else "FAIL",
        "observed": len(units), "required": MIN_DIRECTIONAL_N}
    checks["ENTRY_POPULATION"] = {
        "state": "PASS" if n >= MIN_ENTERED_N else "NOT_REACHED_INSUFFICIENT_SAMPLE",
        "observed": n, "required": MIN_ENTERED_N}

    r1 = capability["fixed_r_capability"]["1R"]
    r3 = capability["fixed_r_capability"]["3R"]
    for key, obs, req in (("STRUCTURAL_CAPABILITY_1R", r1, CONTINUATION_REACH_1R_MIN),
                          ("STRUCTURAL_CAPABILITY_3R", r3, CONTINUATION_REACH_3R_MIN)):
        if not eligible or obs is None:
            state = "NOT_RUN_INSUFFICIENT_SAMPLE"
        else:
            state = "PASS" if obs >= req else "FAIL"
        checks[key] = {"state": state, "observed": obs, "required": req,
                       "measured_on_n": n}

    for axis, payload in robustness["axes"].items():
        checks[axis] = {"state": payload.get("state", "INSUFFICIENT_SAMPLE")}

    checks["FRICTION_READINESS"] = {
        "state": "PASS" if friction_disclosed else "FAIL",
        "mode": "STRUCTURAL_DISCLOSURE",
        "FRICTION_EDGE_VERIFICATION_READY": "NO",
        "substituted_values_present": False}
    checks["DATASET_ROLE_VALIDATION"] = {"state": "PASS" if dataset_role_valid else "FAIL",
                                         "OOS_OPENED": "NO", "HOLDOUT_TOUCHED": "NO"}
    checks["CANDIDATE_IDENTITY_VALIDATION"] = {"state": "PASS" if identity_valid else "FAIL"}

    states = {k: v["state"] for k, v in checks.items()}
    if not eligible:
        # Preregistered: an ineligible DEV sample never reaches the gate and
        # can never produce a PASS.
        verdict = "NOT_REACHED"
    elif all(s == "PASS" for s in states.values()):
        verdict = "PASS"
    elif any(s == "FAIL" for s in states.values()):
        verdict = "FAIL"
    else:
        verdict = "NOT_REACHED"
    return {
        "gate_id": "PRE_OOS_ROBUSTNESS_GATE_V1",
        "semantics": "FAIL_CLOSED — PASS requires every axis PASS; thresholds are frozen",
        "threshold_mutation_in_this_mission": "NONE",
        "checks": checks,
        "eligible": eligible,
        "failing_axes": sorted(k for k, s in states.items() if s == "FAIL"),
        "unevaluable_axes": sorted(k for k, s in states.items()
                                   if s not in ("PASS", "FAIL")),
        "PRE_OOS_RESULT": verdict,
    }


# ---------------------------------------------------------------------------
# Root cause (preregistered decision order)
# ---------------------------------------------------------------------------

ANALYZER_LABEL_MAP = {
    "POOR_TRIGGER_QUALITY": "TRIGGER_FUNNEL_WEAKNESS",
    "LOW_FLOW": "TRIGGER_FUNNEL_WEAKNESS",
    "CONFIRMATION_ATTRITION": "CONFIRMATION_FUNNEL_WEAKNESS",
    "OVER_FILTERING_CANDIDATE": "CONFIRMATION_FUNNEL_WEAKNESS",
    "LOW_DISCRIMINATION": "CONFIRMATION_FUNNEL_WEAKNESS",
    "TP_TOO_AMBITIOUS_CANDIDATE": "TARGET_MODEL_MISMATCH",
    "STOP_GEOMETRY_CANDIDATE": "TARGET_MODEL_MISMATCH",
    "GEOMETRY_REJECTION": "TARGET_MODEL_MISMATCH",
    "ENTRY_UNREACHABLE": "TEMPORAL_INCOMPATIBILITY",
    "INSUFFICIENT_SAMPLE": "INSUFFICIENT_SAMPLE",
    "REGIME_SENSITIVE": "TARGET_CONTINUATION_WEAKNESS",
    "FRICTION_SENSITIVE": "TARGET_MODEL_MISMATCH",
}
_PRIORITY = {"INSUFFICIENT_SAMPLE": 1, "TEMPORAL_INCOMPATIBILITY": 2,
             "TRIGGER_FUNNEL_WEAKNESS": 3, "CONFIRMATION_FUNNEL_WEAKNESS": 4,
             "TARGET_MODEL_MISMATCH": 5, "TARGET_CONTINUATION_WEAKNESS": 6}


def starvation_attribution(units: Sequence[CandidateUnit]) -> dict:
    """Name the funnel step that produced the sample starvation.

    Preregistered under the INSUFFICIENT_SAMPLE rule ('the funnel stage that
    produced the starvation is still named'). Purely descriptive: the step
    with the largest ABSOLUTE candidate loss along the ordered funnel.
    """
    counts = stage_counts(units)
    steps = []
    prev_label, prev_n = "CANDIDATE_N", counts["CANDIDATE_N"]
    for node in ALL_NODES:
        n = counts[node]
        steps.append({"from": prev_label, "to": node, "input_n": prev_n, "output_n": n,
                      "absolute_loss": prev_n - n,
                      "survival_pct": _pct(n, prev_n)})
        prev_label, prev_n = node, n
    # The first step is dominated by non-trading calendar days (FX weekends);
    # it is reported but excluded from "weakness" attribution.
    calendar = [u for u in units if u.reject_reason == "ASIAN_REFERENCE_INSUFFICIENT_BARS"]
    weekend = sum(1 for u in calendar
                  if __import__("datetime").date.fromisoformat(u.day).weekday() >= 5)
    steps[0]["calendar_note"] = (
        f"{len(calendar)} rejects are ASIAN_REFERENCE_INSUFFICIENT_BARS, of which {weekend} fall on "
        "Saturday/Sunday (FX has no weekend session); this step is calendar structure, not a rule weakness")
    worst = max(steps[1:], key=lambda s: s["absolute_loss"])
    worst_rel = min((s for s in steps if s["input_n"] >= _POLICY.min_sample_n),
                    key=lambda s: (s["survival_pct"] if s["survival_pct"] is not None else 101.0))
    return {"steps": steps,
            "largest_absolute_attrition": worst,
            "lowest_survival_step_with_sample": worst_rel}


def analyzer_verdict(report) -> dict:
    """Verbatim weak points from the ACCEPTED Universal Funnel Analyzer."""
    raw = [{"label": wp.label.value, "scope": wp.scope, "evidence": wp.evidence}
           for wp in report.weak_points]
    mapped = sorted({ANALYZER_LABEL_MAP.get(w["label"], w["label"]) for w in raw})
    return {"analyzer": "ag_edgelab.analytics.diagnostic.analyze_three_funnel",
            "thresholds": "frozen DiagnosticPolicy defaults — unmodified by this mission",
            "weak_points": raw,
            "mapped_mission_labels": mapped}


def root_cause(units: Sequence[CandidateUnit], trigger: dict, confirmation: dict,
               capability: dict, temporal: dict, analyzer: dict | None = None) -> dict:
    findings: list[dict] = []
    counts = stage_counts(units)
    n_entry = counts["ENTRY_AVAILABLE"]

    if counts["TRIGGER_INPUT"] < MIN_DIRECTIONAL_N or n_entry < MIN_ENTERED_N:
        findings.append({
            "label": "INSUFFICIENT_SAMPLE", "priority": 1,
            "evidence": (f"TRIGGER_INPUT={counts['TRIGGER_INPUT']} (floor {MIN_DIRECTIONAL_N}), "
                         f"ENTRY_AVAILABLE={n_entry} (floor {MIN_ENTERED_N})")})

    wb_share = temporal["window_bounded_rejection_share_of_post_trigger"]
    remaining = temporal["m15_bars_remaining_after_reclaim"]
    required = temporal["sequential_events_still_required_after_reclaim"]
    if (wb_share is not None and wb_share >= 50.0 and remaining is not None
            and remaining < required):
        findings.append({
            "label": "TEMPORAL_INCOMPATIBILITY", "priority": 2,
            "evidence": (f"{wb_share:.2f}% of post-trigger attrition is window-bounded; median "
                         f"M15 bars remaining after reclaim={remaining} < {required} sequential "
                         "events still required inside the frozen entry window")})

    opp = trigger["opportunity_basis_capability"]
    reach5 = opp["reach_by_target_trigger_pass"].get("5R")
    reach3 = opp["reach_by_target_trigger_pass"].get("3R")
    if reach5 is not None and reach5 * 100.0 <= _POLICY.poor_trigger_target_reach_pct:
        findings.append({
            "label": "TRIGGER_FUNNEL_WEAKNESS", "priority": 3,
            "evidence": (f"opportunity-basis 5R reach among TRIGGER_PASS candidates = "
                         f"{reach5 * 100.0:.2f}% <= {_POLICY.poor_trigger_target_reach_pct}%; "
                         f"3R reach = {None if reach3 is None else round(reach3 * 100.0, 2)}%; "
                         f"selection uplift vs all non-neutral = {opp['selection_uplift_pp_5R']} pp")})

    for step in confirmation["sequence"]:
        if step["input_n"] >= _POLICY.min_sample_n and step["pass_pct_of_input"] is not None \
                and step["pass_pct_of_input"] <= _POLICY.over_filter_pass_pct:
            uplift = step["selection_uplift_3R_pp"]
            if uplift is None or abs(uplift) <= _POLICY.low_target_uplift_pp:
                findings.append({
                    "label": "CONFIRMATION_FUNNEL_WEAKNESS", "priority": 4,
                    "evidence": (f"{step['step']} passes {step['pass_pct_of_input']:.2f}% of "
                                 f"{step['input_n']} with 3R selection uplift {uplift} pp")})

    nat = capability["natural_target_R"]["median"]
    r1 = capability["fixed_r_capability"]["1R"]
    if nat is not None and nat < 1.0:
        findings.append({"label": "TARGET_MODEL_MISMATCH", "priority": 5,
                         "evidence": f"median natural_target_R={nat} < 1.0"})
    r3 = capability["fixed_r_capability"]["3R"]
    if r1 is not None and r3 is not None and r1 >= CONTINUATION_REACH_1R_MIN \
            and r3 < CONTINUATION_REACH_3R_MIN:
        findings.append({"label": "TARGET_CONTINUATION_WEAKNESS", "priority": 6,
                         "evidence": f"1R reach={r1} >= {CONTINUATION_REACH_1R_MIN} but 3R reach={r3} < {CONTINUATION_REACH_3R_MIN}"})

    # The accepted analyzer's own frozen-threshold verdict is authoritative
    # evidence and is folded in at the preregistered priority of its label.
    if analyzer:
        seen = {f["label"] for f in findings}
        for label in analyzer["mapped_mission_labels"]:
            if label in seen or label not in _PRIORITY:
                continue
            scopes = sorted({w["scope"] for w in analyzer["weak_points"]
                             if ANALYZER_LABEL_MAP.get(w["label"]) == label})
            ev = "; ".join(f"{w['scope']}: {w['evidence']}" for w in analyzer["weak_points"]
                           if ANALYZER_LABEL_MAP.get(w["label"]) == label)
            findings.append({"label": label, "priority": _PRIORITY[label],
                             "source": "UNIVERSAL_FUNNEL_ANALYZER",
                             "scopes": scopes, "evidence": ev})
            seen.add(label)

    findings.sort(key=lambda f: f["priority"])
    seen_labels: list[str] = []
    for f in findings:
        if f["label"] not in seen_labels:
            seen_labels.append(f["label"])
    primary = seen_labels[0] if seen_labels else "NO_DIAGNOSIS"
    secondary = seen_labels[1:]
    return {
        "starvation_attribution": starvation_attribution(units),
        "universal_funnel_analyzer_verdict": analyzer,
        "decision_order": ["INSUFFICIENT_SAMPLE", "TEMPORAL_INCOMPATIBILITY",
                           "TRIGGER_FUNNEL_WEAKNESS", "CONFIRMATION_FUNNEL_WEAKNESS",
                           "TARGET_MODEL_MISMATCH", "TARGET_CONTINUATION_WEAKNESS"],
        "findings": findings,
        "PRIMARY_FUNNEL_WEAKNESS": primary,
        "SECONDARY_DIAGNOSES": secondary,
        "upstream_principle_applied": (
            "No additional confirmation filter was designed or tested: the evidence names the "
            "first economically relevant weak point and the mission's search policy forbids "
            "adding filters in response to it."),
    }
