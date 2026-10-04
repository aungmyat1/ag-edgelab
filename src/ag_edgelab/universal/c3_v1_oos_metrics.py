"""TARGET_POLICY_C3_V1 — sealed structural OOS metrics + PREREGISTERED
verdict rules (V0.6.2 mission).

This module contains ONLY pure functions over plain evidence dicts:

  * exact metric definitions for every phase-4 structural metric;
  * the preregistered A/B/C/D verdict thresholds and combination rule
    (frozen in oos_preregistration.json BEFORE the OOS partition is
    opened — never tuned on OOS results);
  * DEV-reference extraction from the FROZEN DEV artifacts (the
    target_policy_c3_v1 DEV ledger + the committed V0.6 parent ledgers);
  * OOS evidence extraction from the frozen pipeline records.

It never imports the candidate builder and never touches market data.
The independent verifier imports this module to recompute metrics and the
verdict from its own reconstruction.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from ag_edgelab.universal.target_v0_5 import _quantile

SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")
TRADED_STATUSES = ("STOPPED_BEFORE_FIRST", "FIRST_PLUS_RUNNER_TARGET",
                   "FIRST_PLUS_RUNNER_STOP", "FIRST_PLUS_RUNNER_HORIZON",
                   "HORIZON_BEFORE_FIRST")
FIRST_REACHED_STATUSES = ("FIRST_PLUS_RUNNER_TARGET", "FIRST_PLUS_RUNNER_STOP",
                          "FIRST_PLUS_RUNNER_HORIZON")
NOT_APPLICABLE_STATUSES = ("NOT_APPLICABLE_NO_OBJECTIVE",
                           "NOT_APPLICABLE_NO_RUNNER_OBJECTIVE")
CENSORED_STATUS = "RIGHT_CENSORED_DATA_BOUNDARY"

# ---------------------------------------------------------------------------
# PREREGISTERED verdict thresholds (frozen before OOS open; V0.6.2 phase 1/7)
# ---------------------------------------------------------------------------

THRESHOLDS: dict[str, Any] = {
    # sample floors
    "POOLED_MIN_TRADED_N": 300,
    "SYMBOL_MIN_TRADED_N": 40,
    # percent-point gates (delta = OOS - DEV, in percentage points)
    "WEAKEN_DELTA_PP": 10.0,     # weakening if delta < -10.0 pp
    "FAIL_DELTA_PP": 20.0,       # failure   if delta < -20.0 pp
    "GATING_PP_METRICS": ("FIRST_OBJECTIVE_REACHED_PCT",
                          "P_SECOND_GIVEN_FIRST", "RUNNER_EXTENDED_REACH"),
    # mean structural R gate (gross, complete termination; NO net metrics)
    "MEAN_RETENTION_FOR_A": 0.5,   # A requires OOS mean >= 0.5 * DEV mean
    "MEAN_SURVIVE_FLOOR_R": 0.0,   # C if OOS mean <= 0.0 R
    # combination
    "SYMBOL_VERDICT_RULE":
        "C if any gating pp delta < -20pp OR symbol mean <= 0.0; "
        "else B if any gating pp delta < -10pp OR symbol mean < "
        "0.5 * DEV symbol mean; else A",
    "POOLED_VERDICT_RULE":
        "same rule on pooled values (A also requires pooled mean >= "
        "0.5 * DEV pooled mean)",
    "FINAL_VERDICT_RULE":
        "worst(pooled, sufficient-sample symbol verdicts); a symbol below "
        "SYMBOL_MIN_TRADED_N is D_SUBSAMPLED and caps the final verdict at "
        "B; D if pooled traded < POOLED_MIN_TRADED_N or >= 2 symbols below "
        "SYMBOL_MIN_TRADED_N; E overrides everything on verification failure",
    "NON_GATING_REPORTED_METRICS": [
        "R1_CAPABILITY", "R2_CAPABILITY", "R3_CAPABILITY", "R4_CAPABILITY",
        "R5_CAPABILITY", "NATURAL_TARGET_P25_R", "NATURAL_TARGET_MEDIAN_R",
        "NATURAL_TARGET_P75_R", "FURTHEST_TARGET_MEDIAN_R",
        "MEDIAN_STRUCTURAL_R", "MAX_STRUCTURAL_DRAWDOWN_R",
    ],
    "VERIFICATION_INVALID_E_CONDITIONS": [
        "candidate identity mismatch (contract sha256 != pinned)",
        "preregistration integrity failure",
        "DEV/OOS window overlap or holdout access",
        "causality audit failure",
        "independent reproduction mismatch (population, objectives, "
        "outcomes, gross structural R, metrics, or verdict)",
        "determinism failure",
        "unresolved runner (traded, unresolved, not right-censored)",
        "censoring accounting failure",
    ],
}

VERDICT_NAMES = {
    "A": "STRUCTURAL_EDGE_GENERALIZES",
    "B": "STRUCTURAL_SIGNAL_WEAKENS_BUT_SURVIVES",
    "C": "STRUCTURAL_GENERALIZATION_FAILS",
    "D": "INSUFFICIENT_OOS_SAMPLE",
    "D_SUBSAMPLED": "INSUFFICIENT_OOS_SAMPLE",
    "E": "VERIFICATION_INVALID",
}


# ---------------------------------------------------------------------------
# Evidence normalization
# ---------------------------------------------------------------------------

def normalize_rungs(rungs: Sequence) -> list[list]:
    """Ladder rungs -> distinct ascending [[R, reached], ...].

    Multiple families may quote the same level; a level is reached iff any
    rung at that exact R was reached (identical price => identical
    reachability, so `any` is exact, not an approximation)."""
    by_level: dict[float, bool] = {}
    for r, reached in rungs:
        by_level[float(r)] = by_level.get(float(r), False) or bool(reached)
    return [[r, by_level[r]] for r in sorted(by_level)]


def _rungs_from_parent_sequence(seq: Sequence) -> list[list]:
    return normalize_rungs([[run["R"], run["reached"]] for run in seq])


# ---------------------------------------------------------------------------
# Evidence extraction — OOS/DEV pipeline side (records + ledger rows)
# ---------------------------------------------------------------------------

def evidence_from_pipeline(records_by_symbol: dict, ledger_rows: Sequence[dict],
                           ) -> list[dict]:
    """Build evidence dicts from the frozen pipeline records (EntryRecord)
    joined with the candidate replay ledger rows."""
    rec_by_id: dict[str, Any] = {}
    for symbol, records in records_by_symbol.items():
        for rec in records:
            rec_by_id[f"{symbol}:{rec.obs_feed_index}"] = rec
    rows_by_id = {row["entry_id"]: row for row in ledger_rows}
    if set(rows_by_id) != set(rec_by_id):
        raise ValueError("ledger rows and pipeline records disagree on the "
                         f"population ({len(rows_by_id)} vs {len(rec_by_id)})")
    evidence = []
    for row in ledger_rows:               # preserve ledger (campaign) order
        rec = rec_by_id[row["entry_id"]]
        rungs = normalize_rungs([[r, reached]
                                 for _fam, _p, r, reached in rec.ladder])
        evidence.append({
            "entry_id": row["entry_id"],
            "symbol": row["symbol"],
            "entry_time": row["entry_time"],
            "direction": row["direction"],
            "is_t1": bool(rec.is_t1),
            "entry_price": row["entry_price"],
            "stop_price": row["stop_price"],
            "rungs": rungs,
            "fixed_reached": {k: bool(v)
                              for k, v in rec.fixed_reached.items()},
            "status": row["status"],
            "first_leg": row.get("first_leg"),
            "runner_leg": row.get("runner_leg"),
            "gross_trade_r": row.get("gross_trade_r"),
        })
    return evidence


# ---------------------------------------------------------------------------
# Evidence extraction — frozen DEV artifacts (preregistration side)
# ---------------------------------------------------------------------------

def evidence_from_dev_frozen(dev_ledger_path: Path,
                             parent_entry_ledger_path: Path,
                             parent_sequence_ledger_path: Path) -> list[dict]:
    """Reconstruct the DEV evidence from the FROZEN artifacts only:

    * target_policy_c3_v1/dev_resolution_ledger.jsonl — candidate statuses,
      legs, gross R (the frozen DEV reference of the freeze mission);
    * universal_funnel_v0_6_target_policy/entry_policy_ledger.jsonl —
      C0_kR statuses (== fixed kR reach) and the parent first-objective
      reached flags;
    * universal_funnel_v0_6_target_policy/objective_sequence_ledger.jsonl —
      the full causal objective ladders (R + reached per rung).
    """
    dev_rows = [json.loads(line) for line in
                Path(dev_ledger_path).read_text(encoding="utf-8").splitlines()
                if line]
    entry: dict[str, dict] = {}
    for line in Path(parent_entry_ledger_path).read_text(
            encoding="utf-8").splitlines():
        if line:
            row = json.loads(line)
            entry[row["entry_id"]] = row
    seq: dict[str, list] = {}
    for line in Path(parent_sequence_ledger_path).read_text(
            encoding="utf-8").splitlines():
        if line:
            row = json.loads(line)
            seq[row["entry_id"]] = row["objective_sequence"]

    evidence = []
    for row in dev_rows:
        eid = row["entry_id"]
        parent = entry[eid]
        rungs = _rungs_from_parent_sequence(seq[eid])
        # consistency: the frozen ledger's first objective must be the
        # ladder minimum; for TRADED rows the status must agree with the
        # first rung's reached flag (NOT_APPLICABLE rows are exempt: their
        # status reflects runner-objective availability, not first reach)
        first = row.get("first_objective")
        if first is not None:
            assert rungs, f"{eid}: first objective but empty ladder"
            assert rungs[0][0] == first["target_r"], \
                f"{eid}: ladder minimum != frozen first objective"
            if row["status"] in TRADED_STATUSES:
                status_first_reached = row["status"] in FIRST_REACHED_STATUSES
                assert rungs[0][1] == status_first_reached, \
                    f"{eid}: ladder first-reached flag disagrees with status"
        fixed = {k: parent["policies"][f"C0_{k}R"]["status"] == "FULL_TARGET"
                 for k in (1, 2, 3, 4, 5)}
        evidence.append({
            "entry_id": eid,
            "symbol": row["symbol"],
            "entry_time": row["entry_time"],
            "direction": row["direction"],
            "is_t1": bool(parent.get("is_t1", False)),
            "entry_price": row["entry_price"],
            "stop_price": row["stop_price"],
            "rungs": rungs,
            "fixed_reached": fixed,
            "status": row["status"],
            "first_leg": row.get("first_leg"),
            "runner_leg": row.get("runner_leg"),
            "gross_trade_r": row.get("gross_trade_r"),
        })
    return evidence


# ---------------------------------------------------------------------------
# Metrics (exact definitions; phase 4)
# ---------------------------------------------------------------------------

def _drawdown(rs: Sequence[float]) -> float:
    cum = 0.0
    peak = 0.0
    dd = 0.0
    for r in rs:
        cum += r
        if cum > peak:
            peak = cum
        if peak - cum > dd:
            dd = peak - cum
    return dd


def _metric_block(evidence: Sequence[dict]) -> dict:
    entry_n = len(evidence)
    traded = [e for e in evidence if e["status"] in TRADED_STATUSES]
    censored = [e for e in evidence if e["status"] == CENSORED_STATUS]
    first_reached = [e for e in traded
                     if e["status"] in FIRST_REACHED_STATUSES]
    not_applicable = [e for e in evidence
                      if e["status"] in NOT_APPLICABLE_STATUSES]

    first_available = [e for e in evidence if e["rungs"]]
    second_available = [e for e in evidence if len(e["rungs"]) >= 2]

    p_second_den = [e for e in first_reached if len(e["rungs"]) >= 2]
    p_second_num = [e for e in p_second_den if e["rungs"][1][1]]
    runner_ext_num = [e for e in first_reached
                      if (e.get("runner_leg") or {}).get("exit_reason")
                      == "RUNNER_TARGET"]

    gross = [e["gross_trade_r"] for e in traded]
    ordered = sorted(traded, key=lambda e: (e["entry_time"], e["entry_id"]))
    ordered_gross = [e["gross_trade_r"] for e in ordered]

    unresolved = [e for e in traded
                  if e["gross_trade_r"] is None
                  or e.get("first_leg") is None or e.get("runner_leg") is None]

    primary_r = sorted(e["rungs"][0][0] for e in first_available)
    furthest_r = sorted(e["rungs"][-1][0] for e in traded)

    runner_legs = [e["runner_leg"] for e in traded]
    contributions = {
        "FIRST_LEG_CONTRIBUTION_R": sum(
            (e["first_leg"] or {}).get("leg_r", 0.0) for e in traded),
        "RUNNER_CONTRIBUTION_R": sum(
            (leg or {}).get("leg_r", 0.0) for leg in runner_legs),
        "RUNNER_TARGET_CONTRIBUTION_R": sum(
            leg.get("leg_r", 0.0) for leg in runner_legs
            if leg and leg.get("exit_reason") == "RUNNER_TARGET"),
        "RUNNER_LOSS_CONTRIBUTION_R": sum(
            leg.get("leg_r", 0.0) for leg in runner_legs
            if leg and leg.get("exit_reason") == "SL"),
        "RUNNER_HORIZON_CLOSE_CONTRIBUTION_R": sum(
            leg.get("leg_r", 0.0) for leg in runner_legs
            if leg and leg.get("exit_reason") == "HORIZON_CLOSE"),
        "RUNNER_STOP_N": sum(1 for leg in runner_legs
                             if leg and leg.get("exit_reason") == "SL"),
        "RUNNER_TARGET_N": sum(1 for leg in runner_legs
                               if leg and leg.get("exit_reason")
                               == "RUNNER_TARGET"),
        "RUNNER_HORIZON_N": sum(1 for leg in runner_legs
                                if leg and leg.get("exit_reason")
                                == "HORIZON_CLOSE"),
    }

    return {
        "ENTRY_N": entry_n,
        "TRADED_N": len(traded),
        "NOT_APPLICABLE_N": len(not_applicable),
        "FIRST_OBJECTIVE_AVAILABLE_N": len(first_available),
        "SECOND_OBJECTIVE_AVAILABLE_N": len(second_available),
        "FURTHEST_OBJECTIVE_AVAILABLE_N": len(traded),
        "FIRST_OBJECTIVE_REACHED_N": len(first_reached),
        "FIRST_OBJECTIVE_REACHED_PCT":
            (len(first_reached) / len(traded)) if traded else None,
        "P_SECOND_GIVEN_FIRST":
            (len(p_second_num) / len(p_second_den)) if p_second_den else None,
        "RUNNER_EXTENDED_REACH":
            (len(runner_ext_num) / len(first_reached)) if first_reached
            else None,
        "R1_CAPABILITY": (sum(1 for e in evidence
                              if e["fixed_reached"].get(1)) / entry_n)
                         if entry_n else None,
        "R2_CAPABILITY": (sum(1 for e in evidence
                              if e["fixed_reached"].get(2)) / entry_n)
                         if entry_n else None,
        "R3_CAPABILITY": (sum(1 for e in evidence
                              if e["fixed_reached"].get(3)) / entry_n)
                         if entry_n else None,
        "R4_CAPABILITY": (sum(1 for e in evidence
                              if e["fixed_reached"].get(4)) / entry_n)
                         if entry_n else None,
        "R5_CAPABILITY": (sum(1 for e in evidence
                              if e["fixed_reached"].get(5)) / entry_n)
                         if entry_n else None,
        "NATURAL_TARGET_P25_R": _quantile(primary_r, 0.25),
        "NATURAL_TARGET_MEDIAN_R": _quantile(primary_r, 0.50),
        "NATURAL_TARGET_P75_R": _quantile(primary_r, 0.75),
        "FURTHEST_TARGET_MEDIAN_R": _quantile(furthest_r, 0.50),
        "GROSS_STRUCTURAL_R": sum(gross) if gross else 0.0,
        "MEAN_STRUCTURAL_R":
            (sum(gross) / len(gross)) if gross else None,
        "MEDIAN_STRUCTURAL_R": _quantile(sorted(gross), 0.50)
            if gross else None,
        "MAX_STRUCTURAL_DRAWDOWN_R": _drawdown(ordered_gross),
        "UNRESOLVED_RUNNER_N": len(unresolved),
        "RIGHT_CENSORED_N": len(censored),
        **contributions,
    }


def compute_metrics(evidence: Sequence[dict]) -> dict:
    """Pooled + per-symbol structural metrics from evidence dicts."""
    by_symbol = {s: [e for e in evidence if e["symbol"] == s]
                 for s in SYMBOLS}
    return {"pooled": _metric_block(evidence),
            "by_symbol": {s: _metric_block(rows) for s, rows in
                          by_symbol.items()}}


# ---------------------------------------------------------------------------
# DEV <-> OOS comparison (phase 5)
# ---------------------------------------------------------------------------

COMPARE_METRICS = (
    "FIRST_OBJECTIVE_REACHED_PCT", "P_SECOND_GIVEN_FIRST",
    "RUNNER_EXTENDED_REACH", "R1_CAPABILITY", "R2_CAPABILITY",
    "R3_CAPABILITY", "R4_CAPABILITY", "R5_CAPABILITY",
    "NATURAL_TARGET_MEDIAN_R", "MEAN_STRUCTURAL_R",
    "MEDIAN_STRUCTURAL_R", "MAX_STRUCTURAL_DRAWDOWN_R",
)


def _deltas(oos_block: dict, dev_block: dict) -> dict:
    out = {}
    for key in COMPARE_METRICS:
        o, d = oos_block.get(key), dev_block.get(key)
        if o is None or d is None:
            out[key] = {"oos": o, "dev": d, "delta": None}
        elif key.endswith("_PCT") or key.startswith("R") \
                or key in ("P_SECOND_GIVEN_FIRST", "RUNNER_EXTENDED_REACH"):
            out[key] = {"oos": o, "dev": d, "delta": (o - d) * 100.0,
                        "delta_pp": True}
        else:
            out[key] = {"oos": o, "dev": d, "delta": o - d}
    return out


def compare_dev_oos(oos_metrics: dict, dev_refs: dict) -> dict:
    comparison = {"pooled": _deltas(oos_metrics["pooled"], dev_refs["pooled"])}
    symbols = {}
    for symbol in SYMBOLS:
        symbols[symbol] = _deltas(oos_metrics["by_symbol"][symbol],
                                  dev_refs["by_symbol"][symbol])
    comparison["by_symbol"] = symbols
    return comparison


# ---------------------------------------------------------------------------
# PREREGISTERED verdict evaluation (phase 7)
# ---------------------------------------------------------------------------

def _gate_block(oos_block: dict, dev_block: dict, thresholds: dict) -> dict:
    gates = {}
    for key in thresholds["GATING_PP_METRICS"]:
        o, d = oos_block.get(key), dev_block.get(key)
        if o is None or d is None:
            gates[key] = {"oos": o, "dev": d, "delta_pp": None, "level": "E"}
            continue
        delta = (o - d) * 100.0
        if delta < -thresholds["FAIL_DELTA_PP"]:
            level = "C"
        elif delta < -thresholds["WEAKEN_DELTA_PP"]:
            level = "B"
        else:
            level = "OK"
        gates[key] = {"oos": o, "dev": d, "delta_pp": delta, "level": level}
    o_mean, d_mean = oos_block.get("MEAN_STRUCTURAL_R"), \
        dev_block.get("MEAN_STRUCTURAL_R")
    if o_mean is None or d_mean is None:
        gates["MEAN_STRUCTURAL_R"] = {"oos": o_mean, "dev": d_mean,
                                      "level": "E"}
    elif o_mean <= thresholds["MEAN_SURVIVE_FLOOR_R"]:
        gates["MEAN_STRUCTURAL_R"] = {"oos": o_mean, "dev": d_mean,
                                      "level": "C"}
    elif o_mean < thresholds["MEAN_RETENTION_FOR_A"] * d_mean:
        gates["MEAN_STRUCTURAL_R"] = {"oos": o_mean, "dev": d_mean,
                                      "level": "B"}
    else:
        gates["MEAN_STRUCTURAL_R"] = {"oos": o_mean, "dev": d_mean,
                                      "level": "OK"}
    return gates


def _verdict_from_gates(gates: dict) -> str:
    levels = [g["level"] for g in gates.values()]
    if "E" in levels:
        return "E"
    if "C" in levels:
        return "C"
    if "B" in levels:
        return "B"
    return "A"


_ORDER = {"A": 0, "B": 1, "C": 2, "D": 2, "D_SUBSAMPLED": 2}


def _worst(verdicts: Sequence[str]) -> str:
    return max(verdicts, key=lambda v: _ORDER[v])


def evaluate_verdict(oos_metrics: dict, dev_refs: dict,
                     thresholds: dict | None = None) -> dict:
    """Apply the preregistered A/B/C/D rules. E is returned here only for
    undefined metrics; verification-failure E is decided by the runner."""
    th = thresholds or THRESHOLDS
    pooled_gates = _gate_block(oos_metrics["pooled"], dev_refs["pooled"], th)
    pooled_verdict = _verdict_from_gates(pooled_gates)

    symbol_results = {}
    symbol_verdicts = []
    subsampled = []
    for symbol in SYMBOLS:
        block = oos_metrics["by_symbol"][symbol]
        traded_n = block["TRADED_N"]
        if traded_n < th["SYMBOL_MIN_TRADED_N"]:
            symbol_results[symbol] = {
                "traded_n": traded_n,
                "verdict": "D_SUBSAMPLED",
                "gates": None,
                "reason": f"traded {traded_n} < SYMBOL_MIN_TRADED_N "
                          f"{th['SYMBOL_MIN_TRADED_N']}",
            }
            subsampled.append(symbol)
            continue
        gates = _gate_block(block, dev_refs["by_symbol"][symbol], th)
        verdict = _verdict_from_gates(gates)
        symbol_results[symbol] = {"traded_n": traded_n, "verdict": verdict,
                                  "gates": gates}
        symbol_verdicts.append(verdict)

    pooled_traded = oos_metrics["pooled"]["TRADED_N"]
    insufficient = pooled_traded < th["POOLED_MIN_TRADED_N"]
    if insufficient or len(subsampled) >= 2:
        final = "D"
        final_reason = ("pooled traded "
                        f"{pooled_traded} < {th['POOLED_MIN_TRADED_N']}"
                        if insufficient else
                        f"{len(subsampled)} symbols below symbol floor: "
                        f"{subsampled}")
    elif "E" in symbol_verdicts or pooled_verdict == "E":
        final = "E"
        final_reason = ("undefined metric (verification-side E conditions "
                        "are evaluated separately by the runner)")
    else:
        final = _worst([pooled_verdict] + symbol_verdicts)
        if subsampled and final == "A":
            final = "B"
            final_reason = f"capped at B: subsampled symbol(s) {subsampled}"
        else:
            final_reason = "preregistered gate combination"

    return {
        "thresholds": th,
        "pooled": {"gates": pooled_gates, "verdict": pooled_verdict,
                   "traded_n": pooled_traded},
        "by_symbol": symbol_results,
        "subsampled_symbols": subsampled,
        "FINAL_VERDICT": final,
        "FINAL_VERDICT_NAME": VERDICT_NAMES[final],
        "final_reason": final_reason,
    }
