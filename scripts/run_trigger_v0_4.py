"""Universal Funnel V0.4 — TRIGGER RESEARCH runner (D01 vs T1 vs T2).

Order of operations is part of the contract:
  1. preregistration.json is written BEFORE any T1/T2 target result exists;
  2. dataset identities are verified fail-closed (pinned PR #10 hashes);
  3. the frozen V0.3 campaign engine produces ALL downstream outcomes;
  4. the pooled D01 baseline must reproduce the frozen parent metrics
     exactly, else STATUS=BASELINE_REPRODUCTION_FAIL and STOP;
  5. the complete computation runs twice; any non-identical canonical hash
     => STATUS=NONDETERMINISTIC and STOP.

Research/diagnostic only: no strategy change, no economics, no OOS, no
holdout, no execution.
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.data.fingerprint import sha256_json  # noqa: E402
from ag_edgelab.data.fx_histdata_2017 import (  # noqa: E402
    BlockedDataAuthority, MTF_TIMEFRAMES, PARTITIONS, PINNED_SOURCE_SHA256, SYMBOLS,
    aggregate_m15, bars_closed_at, derive_fx_timeframe, load_histdata_m1,
    quality_gate_m1, slice_partition, verify_source_identity)
from ag_edgelab.universal.direction import Direction  # noqa: E402
from ag_edgelab.universal.fx_dev_campaign import (  # noqa: E402
    build_series, context_at, run_fx_symbol_campaign)
from ag_edgelab.universal import trigger_v0_4 as trg  # noqa: E402
from ag_edgelab.universal.trigger_v0_4 import (  # noqa: E402
    EXPERIMENT_ID, EXPERIMENT_VERSION, PARENT_SHA, PARENT_TREE, POLICY_DEFINITIONS,
    TRIGGER_POLICY_REGISTRY_SHA256, capability_deltas, confirmation_stability,
    enrich_symbol, interpret_policy, join_symbol, location_label, location_stability,
    ma_ablation, overall_interpretation, phase_distribution, phase_of, policy_metrics,
    pullback_realignment_report, session_stratification, t1_direction, t2_direction,
    t2ma_direction, target_distribution_shift)
from ag_edgelab.contracts.market import MarketBar  # noqa: E402
from ag_edgelab.data.derive import TIMEFRAME_MINUTES  # noqa: E402

OUT_DIR = ROOT / "data" / "artifacts" / "universal_funnel_v0_4_trigger"
PARENT_REPORT = ROOT / "data" / "artifacts" / "universal_price_action_v0_3_fx_dev" / "final_report.json"
DATASET_ROLE = "DEVELOPMENT"
AUDIT_SAMPLES_PER_SYMBOL = 4

PREREGISTRATION = {
    "experiment_id": EXPERIMENT_ID,
    "version": EXPERIMENT_VERSION,
    "parent_sha": PARENT_SHA,
    "parent_tree": PARENT_TREE,
    "registered_before_t1_t2_results": True,
    "policies": POLICY_DEFINITIONS,
    "policy_registry_sha256": TRIGGER_POLICY_REGISTRY_SHA256,
    "motivating_evidence": "V0.3 DEV exploration D08 (+7.55pp pooled) is MOTIVATING_"
                           "EVIDENCE only, not a promoted strategy rule; T1/T2 are "
                           "clean preregistered policies tested prospectively",
    "dataset_identity": {"authority": "HISTDATA_ASCII_M1_2017_PR10_PINNED",
                         "role": DATASET_ROLE,
                         "pinned_sha256": PINNED_SOURCE_SHA256,
                         "symbols": list(SYMBOLS)},
    "comparison_semantics": {
        "opportunity_basis": "MFE_R_REACH_2.0R_SHARED_DIAGNOSTIC_GEOMETRY_V1",
        "uplift_rule": "uplift only within one capability basis; entry-conditioned "
                       "vs opportunity uplift is always null with reason "
                       "INCOMPARABLE_CAPABILITY_SEMANTICS",
        "population_rule": "T1/T2 decided directions always equal the H4/D01 "
                           "direction, so policy populations are strict comparable "
                           "sub-populations of D01 with identical frozen downstream "
                           "semantics",
    },
    "diagnostic_threshold": {
        "separation_pp": trg.RESEARCH_DIAGNOSTIC_THRESHOLD_PP,
        "label": "RESEARCH_DIAGNOSTIC_THRESHOLD",
        "explicitly_not": ["edge threshold", "profit threshold",
                           "production threshold", "deployment threshold"],
    },
    "material_target_improvement": {
        "delta_2r_pp_min": trg.MATERIAL_DELTA_2R_PP,
        "delta_3r_pp_min": trg.MATERIAL_DELTA_3R_PP,
        "min_policy_directional_n": trg.MIN_POLICY_DIRECTIONAL_N,
        "min_policy_entered_n": trg.MIN_POLICY_ENTERED_N,
    },
    "pullback_realignment": {
        "measurement_window_h1_bars": trg.REALIGN_WINDOW_H1_BARS,
        "note": "diagnostic horizon only; no maximum-wait trading rule is defined",
    },
    "frozen_downstream_authority": [
        "location rules (V0.3)", "sweep/range/trend families (untouched)",
        "confirmation contracts (V0.3)", "entry geometry (V0.3)",
        "SL geometry (12-bar opposite extreme, V0.3)",
        "fixed 1R-5R targets", "natural target definitions (V0.3)",
        "session definitions (V0.3 preregistered UTC windows)",
    ],
    "ma_ablation": {"rule": "T2 vs T2+MA agreement only; 50/200 not tuned",
                    "separation_gain_pp_min": trg.MA_ABLATION_SEPARATION_PP},
}
PREREGISTRATION["experiment_hash"] = sha256_json(PREREGISTRATION)


def write(name: str, payload) -> Path:
    path = OUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT)}")
    return path


def mutate_future(bars, timeframe: str, as_of):
    span = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
    out = []
    for b in bars:
        if b.timestamp + span <= as_of:
            out.append(b)
        else:
            out.append(MarketBar(timestamp=b.timestamp, open=b.open * 1.1,
                                 high=b.high * 1.1, low=b.low * 1.1, close=b.close * 1.1))
    return tuple(out)


def trigger_states_from_frames(frames, as_of, price):
    """Independent recomputation of every trigger-relevant state at `as_of`
    using only bars closed at or before it (for the causality audit)."""
    cuts = {}
    for tf in ("H1", "H4", "D1"):
        span = timedelta(minutes=TIMEFRAME_MINUTES[tf])
        idx = -1
        for i, b in enumerate(frames[tf]):
            if b.timestamp + span <= as_of:
                idx = i
            else:
                break
        cuts[tf] = idx
    if min(cuts.values()) < 0:
        raise ValueError("audit point before frame availability")
    bundle = build_series(frames)
    ctx, extras = context_at(bundle, cuts["D1"], cuts["H4"], cuts["H1"], price)
    phase = phase_of(ctx.h4, ctx.h1_flow)
    t2 = t2_direction(phase)
    return {
        "h4": ctx.h4.value, "h1_flow": ctx.h1_flow.value, "phase": phase,
        "pd_state": extras["pd_state"], "location": location_label(extras["pd_state"]),
        "ma": ctx.ma.value,
        "t1": t1_direction(ctx.h4, ctx.h1_flow, extras["pd_state"]).value,
        "t2": t2.value, "t2ma": t2ma_direction(t2, ctx.ma).value,
    }


def enriched_states(en) -> dict:
    return {"h4": en.h4, "h1_flow": en.h1_flow, "phase": en.phase,
            "pd_state": en.pd_state, "location": en.location, "ma": en.ma,
            "t1": en.t1, "t2": en.t2, "t2ma": en.t2ma}


def compute_campaign(zip_dir: Path) -> dict:
    """Pure deterministic computation; run twice for the determinism audit."""
    dev_start, dev_end = PARTITIONS[DATASET_ROLE]
    per_symbol = {}
    dataset = {}
    frames_by_symbol = {}
    for symbol in SYMBOLS:
        zip_path = zip_dir / f"HISTDATA_COM_ASCII_{symbol}_M1_2017.zip"
        source_sha = verify_source_identity(zip_path, symbol)
        m1 = load_histdata_m1(zip_path)
        quality = quality_gate_m1(m1, symbol)
        m1_dev = slice_partition(m1, DATASET_ROLE)
        m15 = aggregate_m15(m1_dev)
        frames = {"M15": m15}
        lineages = []
        for tf in MTF_TIMEFRAMES:
            frames[tf], lineage = derive_fx_timeframe(m15, tf, symbol)
            lineages.append(lineage)
        campaign = run_fx_symbol_campaign(frames, symbol, dev_start, dev_end)
        enriched = enrich_symbol(frames, campaign, dev_start, dev_end)
        joined = join_symbol(campaign, enriched)
        per_symbol[symbol] = {"campaign": campaign, "enriched": enriched,
                              "joined": joined}
        frames_by_symbol[symbol] = frames
        dataset[symbol] = {
            "source_sha256": source_sha, "pinned_sha256": PINNED_SOURCE_SHA256[symbol],
            "identity_verified": True, "m1_rows_full_2017": len(m1),
            "m1_rows_development": len(m1_dev), "m15_bars_development": len(m15),
            "quality": quality,
            "mtf_lineage": [{"timeframe": ln.output_timeframe, "rows": ln.rows,
                             "coverage_rule": ln.coverage_rule,
                             "source_hash": ln.source_hash,
                             "output_hash": ln.output_hash} for ln in lineages],
        }
    return {"per_symbol": per_symbol, "dataset": dataset,
            "frames_by_symbol": frames_by_symbol,
            "dev_bounds": (dev_start, dev_end)}


def aggregate(computed: dict) -> dict:
    per_symbol = computed["per_symbol"]
    pooled_joined = tuple(j for s in SYMBOLS for j in per_symbol[s]["joined"])
    pooled_enriched = tuple(e for s in SYMBOLS for e in per_symbol[s]["enriched"])

    policy_names = ("D01", "T1", "T2", "T2_MA")
    pooled = {p: policy_metrics(pooled_joined, p) for p in policy_names}
    by_symbol = {s: {p: policy_metrics(per_symbol[s]["joined"], p)
                     for p in policy_names} for s in SYMBOLS}

    verdicts = {p: interpret_policy(pooled[p], pooled["D01"]) for p in ("T1", "T2")}
    overall = overall_interpretation(verdicts)

    return {
        "pooled_joined": pooled_joined,
        "pooled_enriched": pooled_enriched,
        "pooled": pooled,
        "by_symbol": by_symbol,
        "verdicts": verdicts,
        "overall": overall,
        "phase": {**{s: phase_distribution(per_symbol[s]["enriched"]) for s in SYMBOLS},
                  "POOLED": phase_distribution(pooled_enriched)},
        "pullback": {**{s: pullback_realignment_report(per_symbol[s]["enriched"])
                        for s in SYMBOLS},
                     "POOLED": pullback_realignment_report(pooled_enriched)},
        "location_stability": location_stability({p: pooled[p] for p in ("D01", "T1", "T2")}),
        "confirmation_stability": confirmation_stability(
            {p: pooled[p] for p in ("D01", "T1", "T2")}),
        "ma_ablation": ma_ablation(pooled["T2"], pooled["T2_MA"]),
        "sessions": session_stratification(pooled_joined),
        "raw_by_symbol": {s: per_symbol[s]["campaign"].raw_observations for s in SYMBOLS},
    }


def results_fingerprint(agg: dict) -> str:
    """Canonical hash over every numeric result (determinism audit)."""
    payload = {k: agg[k] for k in ("pooled", "by_symbol", "verdicts", "overall",
                                   "phase", "pullback", "location_stability",
                                   "confirmation_stability", "ma_ablation",
                                   "sessions", "raw_by_symbol")}
    return sha256_json(json.loads(json.dumps(payload, sort_keys=True, default=str)))


def check_baseline(pooled_d01: dict) -> tuple[bool, dict]:
    """Pooled D01 must reproduce the frozen parent metrics exactly."""
    parent = json.loads(PARENT_REPORT.read_text(encoding="utf-8"))
    checks = {
        "separation_pp": (pooled_d01["separation_pp"],
                          parent["direction_separation_pp"]),
        "entered_n": (pooled_d01["entered_n"], 3183),
        "confirmation_uplift_pp": (
            pooled_d01["confirmation"]["uplift_pp_same_basis"],
            parent["confirmation_uplift_pp_same_basis"]),
        "natural_median_r": (pooled_d01["natural_target_r"]["P50"],
                             parent["natural_target_pooled"]["median_r"]),
        "natural_p25_r": (pooled_d01["natural_target_r"]["P25"],
                          parent["natural_target_pooled"]["p25_r"]),
        "natural_p75_r": (pooled_d01["natural_target_r"]["P75"],
                          parent["natural_target_pooled"]["p75_r"]),
    }
    for k in (1, 2, 3, 4, 5):
        checks[f"reach_{k}R"] = (pooled_d01["fixed_reach"][f"{k}R"],
                                 parent["fixed_reach_pooled"][f"{k}R"])
    for a, b in (("P2_GIVEN_1", "P2_GIVEN_1"), ("P3_GIVEN_2", "P3_GIVEN_2"),
                 ("P4_GIVEN_3", "P4_GIVEN_3"), ("P5_GIVEN_4", "P5_GIVEN_4")):
        checks[a] = (pooled_d01["continuation_survival"][a],
                     parent["continuation_survival_pooled"][b])
    detail = {k: {"computed": got, "frozen": want, "match": got == want}
              for k, (got, want) in checks.items()}
    return all(v["match"] for v in detail.values()), detail


ASIAN_V2_IDENTITY = {
    "question": "is ST_ASIAN_SESSION_BRANCH_V2 identical to SESSION_TRADE_V2 @2.0.0?",
    "method": "identity comparison only; no substitution performed",
    "st_asian_session_branch_v2": {
        "definition_found": False,
        "search_scope": "all fetched branches incl. origin/arena/01a100ce (PR #10); "
                        "the name appears ONLY in V0.3 not-found reports",
        "comparable_semantics_available": False,
    },
    "session_trade_v2": {
        "source": "origin/arena/01a100ce-ag-edgelab:src/ag_edgelab/campaigns/"
                  "session_trade_v2/frozen/SESSION_TRADE_V2.yaml",
        "strategy_id": "SESSION_TRADE_V2", "version": "2.0.0",
        "status": "RESEARCH_SHADOW", "registered_utc": "2026-10-03",
        "self_declaration": "New deterministic authority. It does not replace "
                            "SESSION_TRADE_V1 or ST_ASIAN_SWEEP_5R_V1 until evidence "
                            "and owner promotion explicitly do so.",
        "instruments": ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"],
        "session_pairs": {"ASIAN_LONDON": {"reference_utc": ["22:00", "06:00"],
                                           "trade_utc": ["06:00", "09:00"]},
                          "LONDON_NEWYORK": {"reference_utc": ["06:00", "11:00"],
                                             "trade_utc": ["11:00", "14:00"]}},
        "setup_priority": ["A_SWEEP_REENTRY", "B_RANGE_REJECTION", "C_TREND_EXPANSION"],
        "total_target_r": 5.0,
    },
    "observable_relations": [
        "family overlap: Asian-session reference window, sweep/range/trend setup "
        "families, 5R total target",
        "SESSION_TRADE_V2 explicitly self-declares as a DISTINCT new authority, "
        "not a rename of any V1/branch lineage",
        "no artifact anywhere binds the name ST_ASIAN_SESSION_BRANCH_V2 to any "
        "rule set, hash, or version",
    ],
    "ASIAN_V2_IDENTITY_RESULT": "INSUFFICIENT_EVIDENCE",
    "reason": "one side of the comparison has no retrievable semantics (name only); "
              "a semantic identity verdict (IDENTICAL / SEMANTICALLY_EQUIVALENT / "
              "RELATED_BUT_DIFFERENT) cannot be established without owner-provided "
              "lineage; nothing was substituted automatically",
    "blocks_trigger_experiment": False,
}


def main() -> int:
    zip_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        ROOT / "data" / "external" / "histdata_fx_2017"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. preregistration FIRST — before any T1/T2 target result is computed.
    write("preregistration.json", PREREGISTRATION)
    write("experiment_identity.json", {
        "experiment_id": EXPERIMENT_ID, "version": EXPERIMENT_VERSION,
        "parent_sha": PARENT_SHA, "parent_tree": PARENT_TREE,
        "parent_status": "FX_DEV_FUNNEL_COMPLETE", "parent_pr": 14,
        "experiment_hash": PREREGISTRATION["experiment_hash"],
        "policy_registry_sha256": TRIGGER_POLICY_REGISTRY_SHA256,
        "funnel_engine_sha_v0_3": "2ae7474bd5dff5a6eea9fdf9cfdcfc7381692789",
    })

    # 2-3. compute (frozen V0.3 downstream engine) — twice, for determinism.
    try:
        computed = compute_campaign(zip_dir)
    except (BlockedDataAuthority, FileNotFoundError) as exc:
        print(f"BLOCKED_DATA_AUTHORITY: {exc}", file=sys.stderr)
        return 2
    agg = aggregate(computed)
    fp1 = results_fingerprint(agg)
    agg2 = aggregate(compute_campaign(zip_dir))
    fp2 = results_fingerprint(agg2)
    determinism = {"run_1_sha256": fp1, "run_2_sha256": fp2,
                   "byte_identical": fp1 == fp2,
                   "scope": "all candidate metrics, ledgers, verdicts, phase/"
                            "pullback/session/stability/ablation payloads"}
    if fp1 != fp2:
        write("determinism_audit.json", determinism)
        print("STATUS=NONDETERMINISTIC", file=sys.stderr)
        return 4

    # 4. baseline reproduction gate.
    baseline_ok, baseline_detail = check_baseline(agg["pooled"]["D01"])
    if not baseline_ok:
        write("d01_baseline.json", {"reproduced": False, "detail": baseline_detail})
        print("STATUS=BASELINE_REPRODUCTION_FAIL", file=sys.stderr)
        return 3

    # 5. causality audit on real data (trigger states only use closed bars).
    audit = {"invariants": [
        "completed-bar-only: every state at T reads bars with open+span <= T",
        "truncation invariant: rebuilding all series from frames truncated at T "
        "reproduces every trigger state",
        "future-mutation invariant: scaling every bar strictly after T by 1.1 "
        "changes no trigger state (no future swing/flow/range/MA/target leak)",
    ], "samples": []}
    for symbol in SYMBOLS:
        enriched = computed["per_symbol"][symbol]["enriched"]
        frames = computed["frames_by_symbol"][symbol]
        step = max(1, len(enriched) // (AUDIT_SAMPLES_PER_SYMBOL + 1))
        for en in enriched[step::step][:AUDIT_SAMPLES_PER_SYMBOL]:
            price = frames["M15"][en.feed_index].close
            truncated_frames = {tf: bars_closed_at(frames[tf], tf, en.observed_at)
                                for tf in ("H1", "H4", "D1")}
            truncated = trigger_states_from_frames(truncated_frames, en.observed_at, price)
            mutated_frames = {tf: mutate_future(frames[tf], tf, en.observed_at)
                              for tf in ("H1", "H4", "D1")}
            mutated = trigger_states_from_frames(mutated_frames, en.observed_at, price)
            expected = enriched_states(en)
            audit["samples"].append({
                "symbol": symbol, "observed_at": en.observed_at.isoformat(),
                "states": expected,
                "truncation_invariant": truncated == expected,
                "future_mutation_invariant": mutated == expected,
            })
    audit["all_passed"] = all(s["truncation_invariant"] and s["future_mutation_invariant"]
                              for s in audit["samples"])
    causality = "PASS" if audit["all_passed"] else "FAIL"
    if not audit["all_passed"]:
        write("causality_audit.json", audit)
        print("CAUSALITY AUDIT FAILED", file=sys.stderr)
        return 5

    # ------------------------------------------------------------------ artifacts
    pooled = agg["pooled"]
    d01, t1, t2, t2ma = pooled["D01"], pooled["T1"], pooled["T2"], pooled["T2_MA"]
    verdicts, overall = agg["verdicts"], agg["overall"]
    deltas = {"T1": capability_deltas(t1, d01), "T2": capability_deltas(t2, d01)}

    write("dataset_authority.json", {
        "authority": "HISTDATA_ASCII_M1_2017_PR10_PINNED", "role": DATASET_ROLE,
        "hashes_verified": True, "symbols": computed["dataset"],
        "partitions": {k: [v[0].isoformat(), v[1].isoformat()]
                       for k, v in PARTITIONS.items()},
        "unaltered": ["source", "timezone normalization", "resampling",
                      "partition boundaries", "symbol population",
                      "bar-admission rules"],
        "oos_opened": False, "holdout_touched": False})
    write("d01_baseline.json", {"reproduced": True, "detail": baseline_detail,
                                "pooled": d01,
                                "by_symbol": {s: agg["by_symbol"][s]["D01"]
                                              for s in SYMBOLS}})
    write("t1_strict.json", {"pooled": t1, "verdict": verdicts["T1"],
                             "by_symbol": {s: agg["by_symbol"][s]["T1"]
                                           for s in SYMBOLS}})
    write("t2_phase_aware.json", {"pooled": t2, "verdict": verdicts["T2"],
                                  "by_symbol": {s: agg["by_symbol"][s]["T2"]
                                                for s in SYMBOLS}})
    write("phase_distribution.json", agg["phase"])
    write("pullback_realignment.json", agg["pullback"])
    write("sample_attrition.json", {
        "D01_DIRECTIONAL_N": d01["directional_n"],
        "T1_DIRECTIONAL_N": t1["directional_n"],
        "T2_DIRECTIONAL_N": t2["directional_n"],
        "T1_ATTRITION_VS_D01_PCT": verdicts["T1"]["attrition_vs_d01_pct"],
        "T2_ATTRITION_VS_D01_PCT": verdicts["T2"]["attrition_vs_d01_pct"],
        "per_symbol": {s: {p: agg["by_symbol"][s][p]["directional_n"]
                           for p in ("D01", "T1", "T2")} for s in SYMBOLS},
        "rule": "winner is never chosen on separation alone (mission section 10)"})
    write("location_stability.json", agg["location_stability"])
    write("confirmation_stability.json", agg["confirmation_stability"])
    write("ma_ablation.json", agg["ma_ablation"])
    write("session_stratification.json", agg["sessions"])
    write("target_capability_comparison.json", {
        "pooled": {p: {"entered_n": pooled[p]["entered_n"],
                       "fixed_reach": pooled[p]["fixed_reach"],
                       "mfe_r_median": pooled[p]["mfe_r_median"],
                       "mae_r_median": pooled[p]["mae_r_median"]}
                   for p in ("D01", "T1", "T2", "T2_MA")},
        "deltas_vs_d01": deltas,
        "target_distribution_shift": {p: target_distribution_shift(deltas[p])
                                      for p in ("T1", "T2")}})
    write("continuation_survival.json", {
        "pooled": {p: pooled[p]["continuation_survival"]
                   for p in ("D01", "T1", "T2", "T2_MA")},
        "by_symbol": {s: {p: agg["by_symbol"][s][p]["continuation_survival"]
                          for p in ("D01", "T1", "T2")} for s in SYMBOLS}})
    write("natural_target_distribution.json", {
        "pooled": {p: {"n": pooled[p]["natural_target_n"],
                       **pooled[p]["natural_target_r"]}
                   for p in ("D01", "T1", "T2", "T2_MA")},
        "by_symbol": {s: {p: agg["by_symbol"][s][p]["natural_target_r"]
                          for p in ("D01", "T1", "T2")} for s in SYMBOLS}})
    write("funnel_value_attribution.json", {
        p: {"direction_separation_pp": pooled[p]["separation_pp"],
            "location_uplift_pp": round(
                (pooled[p]["location"]["aligned_capability"]
                 - pooled[p]["capability_decided_direction"]) * 100.0, 2)
            if pooled[p]["location"]["aligned_capability"] is not None
            and pooled[p]["capability_decided_direction"] is not None else None,
            "confirmation_uplift_pp_same_basis":
                pooled[p]["confirmation"]["uplift_pp_same_basis"],
            "entry_rate_from_confirmation": round(
                pooled[p]["entered_n"] / pooled[p]["funnel"]["CONFIRMATION_AVAILABLE"], 4)
            if pooled[p]["funnel"]["CONFIRMATION_AVAILABLE"] else None,
            "continuation_survival": pooled[p]["continuation_survival"]}
        for p in ("D01", "T1", "T2")})
    write("root_cause_analysis.json", {
        "parent_primary_diagnosis": "TRIGGER_FUNNEL_WEAKNESS (V0.3, frozen)",
        "per_policy_result": verdicts,
        "overall": overall,
        "acceptance_map": {"A": "TRIGGER_HYPOTHESIS_SUPPORTED_ON_DEV",
                           "B": "TRIGGER_DIRECTION_IMPROVED_TARGET_NOT_IMPROVED",
                           "C": "TRIGGER_HYPOTHESIS_NOT_SUPPORTED",
                           "D": "INSUFFICIENT_EVIDENCE"}})
    write("asian_v2_identity_comparison.json", ASIAN_V2_IDENTITY)
    write("causality_audit.json", audit)
    write("determinism_audit.json", determinism)

    final = {
        "mission": "UNIVERSAL FUNNEL V0.4 — TRIGGER RESEARCH (D01 vs T1 vs T2)",
        "experiment_id": EXPERIMENT_ID, "version": EXPERIMENT_VERSION,
        "parent_sha": PARENT_SHA, "base_parent_reproduced": True,
        "dataset": {"authority": "HISTDATA_ASCII_M1_2017_PR10_PINNED",
                    "role": DATASET_ROLE, "hashes_verified": True},
        "observations_raw": agg["raw_by_symbol"],
        "directional_n": {p: pooled[p]["directional_n"] for p in ("D01", "T1", "T2")},
        "separation_pp": {p: pooled[p]["separation_pp"] for p in ("D01", "T1", "T2")},
        "attrition_vs_d01_pct": {"T1": verdicts["T1"]["attrition_vs_d01_pct"],
                                 "T2": verdicts["T2"]["attrition_vs_d01_pct"]},
        "phase_pooled": agg["phase"]["POOLED"]["counts"],
        "pullback_pooled": {k: agg["pullback"]["POOLED"][k]
                            for k in ("PULLBACK_N", "PULLBACK_REALIGN_N",
                                      "PULLBACK_REALIGN_RATE",
                                      "REALIGN_DELAY_H1_BARS")},
        "fixed_reach": {p: pooled[p]["fixed_reach"] for p in ("D01", "T1", "T2")},
        "continuation_survival": {p: pooled[p]["continuation_survival"]
                                  for p in ("D01", "T1", "T2")},
        "natural_target_r": {p: pooled[p]["natural_target_r"]
                             for p in ("D01", "T1", "T2")},
        "deltas_vs_d01": deltas,
        "target_distribution_shift": {p: target_distribution_shift(deltas[p])
                                      for p in ("T1", "T2")},
        "location_value_stable": agg["location_stability"]["LOCATION_VALUE_STABLE"],
        "confirmation_value_stable":
            agg["confirmation_stability"]["CONFIRMATION_VALUE_STABLE"],
        "ma_adds_value_beyond_structure":
            agg["ma_ablation"]["MA_ADDS_VALUE_BEYOND_STRUCTURE"],
        "asian_v2_identity_result": ASIAN_V2_IDENTITY["ASIAN_V2_IDENTITY_RESULT"],
        "per_policy_result": verdicts, "overall": overall,
        "causality": causality, "determinism": "PASS",
        "guards": {"strategy_rules_changed": False, "new_strategy_created": False,
                   "realized_economics_run": False, "oos_opened": False,
                   "holdout_touched": False, "execution_capability_added": False},
        "status": "TRIGGER_RESEARCH_COMPLETE"
        if verdicts["T1"]["result_type"] != "D" or verdicts["T2"]["result_type"] != "D"
        else "INSUFFICIENT_EVIDENCE",
    }
    final["final_report_sha256"] = sha256_json(
        json.loads(json.dumps(final, sort_keys=True, default=str)))
    write("final_report.json", final)

    md = ["# Universal Funnel V0.4 — Trigger Research (D01 vs T1 vs T2)", "",
          f"EXPERIMENT: {EXPERIMENT_ID} @ {EXPERIMENT_VERSION} · parent {PARENT_SHA[:12]} "
          f"(reproduced: YES) · STATUS: **{final['status']}**", "",
          "## Policies", "",
          "| policy | directional N | separation (pp) | attrition vs D01 | entered | result |",
          "|---|---|---|---|---|---|"]
    for p in ("D01", "T1", "T2"):
        v = verdicts.get(p, {})
        md.append(f"| {p} | {pooled[p]['directional_n']} | {pooled[p]['separation_pp']} | "
                  f"{v.get('attrition_vs_d01_pct', '—')} | {pooled[p]['entered_n']} | "
                  f"{v.get('interpretation', 'frozen baseline')} |")
    md += ["", "## Target capability (pooled)", "",
           "| policy | 1R | 2R | 3R | 4R | 5R | natural P50 |", "|---|---|---|---|---|---|---|"]
    for p in ("D01", "T1", "T2"):
        fr = pooled[p]["fixed_reach"]
        p50 = pooled[p]["natural_target_r"]["P50"]
        cells = " | ".join(f"{fr[f'{k}R']:.4f}" if fr[f"{k}R"] is not None else "—"
                           for k in range(1, 6))
        tail = f" | {p50:.2f} |" if p50 is not None else " | — |"
        md.append(f"| {p} | {cells}{tail}")
    md += ["", "## Verdict", "",
           f"- Best policy: **{overall['best_policy']}** (type {overall['best_result_type']})",
           f"- PRIMARY_DIAGNOSIS: **{overall['primary_diagnosis']}**",
           f"- NEXT_FUNNEL_TO_TEST: **{overall['next_funnel_to_test']}**",
           f"- Propagates downstream: {overall['direction_improvement_propagates_downstream']}",
           "",
           "## Guards", "",
           "strategy rules changed: NO · new strategy: NO · economics: NO · OOS: NO · "
           "holdout: NO · execution: NO · Asian V2 identity: "
           f"{ASIAN_V2_IDENTITY['ASIAN_V2_IDENTITY_RESULT']}", ""]
    (OUT_DIR / "final_report.md").write_text("\n".join(md), encoding="utf-8")
    print(f"  wrote {(OUT_DIR / 'final_report.md').relative_to(ROOT)}")

    # manifest (includes test_results.txt if present)
    import hashlib
    names = sorted(p.name for p in OUT_DIR.iterdir()
                   if p.is_file() and p.name != "artifact_manifest.json")
    manifest = {"experiment_id": EXPERIMENT_ID,
                "artifacts": {n: hashlib.sha256((OUT_DIR / n).read_bytes()).hexdigest()
                              for n in names}}
    write("artifact_manifest.json", manifest)

    print(f"\nSTATUS={final['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
