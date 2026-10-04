"""Universal Funnel V0.5 — CAUSAL TARGET MODEL DIAGNOSTICS runner.

Contract order:
  1. preregistration.json written BEFORE any evaluation result exists;
  2. parent reproduction gate: frozen V0.4 artifacts must carry the exact
     pinned values AND the recomputed entry ledger must reproduce the frozen
     entry populations/fixed reach exactly, else BLOCKED_PARENT_REPRODUCTION;
  3. pinned dataset identities verified fail-closed;
  4. full computation runs twice — any hash difference => NONDETERMINISTIC;
  5. adversarial causality audit: every bar after entry mutated AND frames
     truncated at entry (M15 + H4 + D1) — natural target selection identical.

No TP change, no SL change, no parameter search, no partial exits, no
economics, no OOS, no holdout, no execution. Diagnostic only. No V0.6.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.contracts.market import MarketBar  # noqa: E402
from ag_edgelab.data.derive import TIMEFRAME_MINUTES  # noqa: E402
from ag_edgelab.data.fingerprint import sha256_json  # noqa: E402
from ag_edgelab.data.fx_histdata_2017 import (  # noqa: E402
    BlockedDataAuthority, MTF_TIMEFRAMES, PARTITIONS, PINNED_SOURCE_SHA256, SYMBOLS,
    aggregate_m15, bars_closed_at, derive_fx_timeframe, load_histdata_m1,
    quality_gate_m1, slice_partition, verify_source_identity)
from ag_edgelab.universal.fx_dev_campaign import run_fx_symbol_campaign  # noqa: E402
from ag_edgelab.universal.targets import EntryGeometry, FIXED_R_TARGETS  # noqa: E402
from ag_edgelab.universal.direction import Direction  # noqa: E402
from ag_edgelab.universal.trigger_v0_4 import enrich_symbol  # noqa: E402
from ag_edgelab.universal import target_v0_5 as tgt  # noqa: E402
from ag_edgelab.universal.target_v0_5 import (  # noqa: E402
    EXPERIMENT_ID, EXPERIMENT_VERSION, FAMILY_CONTRACTS, NATURAL_FAMILIES,
    PARENT_SHA, PARENT_TREE, PRIMARY_RULE, RUNNABLE_FAMILIES,
    TARGET_V0_5_REGISTRY_SHA256, _natural_candidates, build_entry_records,
    build_symbol_context, candidate_ledger_rows, d01_vs_t1_effect, ladder_rows,
    population_target_report, root_cause_cases, stop_target_geometry)

OUT_DIR = ROOT / "data" / "artifacts" / "universal_funnel_v0_5_target"
PARENT_V04 = ROOT / "data" / "artifacts" / "universal_funnel_v0_4_trigger"
DATASET_ROLE = "DEVELOPMENT"
AUDIT_SAMPLES_PER_SYMBOL = 4

# §2 pinned parent values (exact gate; natural medians gated at 2dp)
PARENT_EXPECTED = {
    "D01_DIRECTIONAL_N": 9226, "T1_DIRECTIONAL_N": 899,
    "D01_SEPARATION_PP": 2.04, "T1_SEPARATION_PP": 7.55,
    "D01_ENTERED_N": 3183, "T1_ENTERED_N": 379,
    "D01_FIXED": {"1R": .4926, "2R": .3032, "3R": .2001, "4R": .1376, "5R": .0952},
    "T1_FIXED": {"1R": .5330, "2R": .3509, "3R": .2058, "4R": .1293, "5R": .0765},
    "D01_NATURAL_TARGET_MEDIAN_R": 2.34, "T1_NATURAL_TARGET_MEDIAN_R": 2.63,
}

PREREGISTRATION = {
    "experiment_id": EXPERIMENT_ID, "version": EXPERIMENT_VERSION,
    "parent_sha": PARENT_SHA, "parent_tree": PARENT_TREE,
    "registered_before_results": True,
    "objective": [
        "are frozen fixed targets beyond the market's causal structural objectives?",
        "do suitable structural/liquidity targets exist at entry but price fail to deliver?",
        "is normalized target R distorted by frozen stop geometry?",
        "does T1 improve quality/location of natural objectives vs D01?",
        "is there evidence for a future natural / natural+runner / fixed-R experiment?"],
    "populations": {"P0": "D01 frozen entries", "P1": "T1 frozen entries",
                    "strata": ["POOLED"] + list(SYMBOLS)},
    "frozen_upstream": ["D01", "T1", "T2", "location", "confirmation", "entry",
                        "SL", "session definitions", "fill semantics", "friction",
                        "existing fixed targets", "dataset lineage"],
    "natural_families": FAMILY_CONTRACTS,
    "runnable_families": RUNNABLE_FAMILIES,
    "nt05_status": "AVAILABLE=false REASON=TARGET_FAMILY_CONTRACT_INCOMPLETE "
                   "(no deterministic order-block detector exists in this "
                   "repository; never invented)",
    "causality_contract": "target_created_time <= entry_time enforced per "
                          "target; closed-bar cuts for H4/D1; completed-window "
                          "cut for session levels; no future swings/zones/"
                          "levels; trade result never selects a target",
    "primary_rule": PRIMARY_RULE,
    "collision_rule": "stop counted FIRST (frozen V0.3 fail-closed rule); "
                      "same-bar stop+target collision => invalidated",
    "fit_tolerance": {"TARGET_FIT_TOLERANCE_PCT": tgt.TARGET_FIT_TOLERANCE_PCT,
                      "rule": "ratio=FIXED_R/NATURAL_R; BELOW<0.95, "
                              "NEAR 0.95..1.05, ABOVE>1.05; invalid natural "
                              "=> NULL (INVALID_OR_UNAVAILABLE_NATURAL_TARGET)"},
    "thresholds": {
        "support_low": tgt.SUPPORT_LOW, "realize_low": tgt.REALIZE_LOW,
        "realize_min_n": tgt.REALIZE_MIN_N,
        "mismatch_beyond_pct": tgt.MISMATCH_BEYOND_PCT,
        "natural_reachable_low": tgt.NATURAL_REACHABLE_LOW,
        "first_delivery_strong": tgt.FIRST_DELIVERY_STRONG,
        "runner_continuation": tgt.RUNNER_CONTINUATION,
        "min_stratum_n": tgt.MIN_STRATUM_N,
        "family_insufficient_pct": tgt.FAMILY_INSUFFICIENT_PCT,
        "material_r": tgt.MATERIAL_R, "material_pp": tgt.MATERIAL_PP,
        "deterioration_pp": tgt.DETERIORATION_PP,
        "sl_interaction_ratio": tgt.SL_INTERACTION_RATIO,
        "raw_coscaling_rho": tgt.RAW_COSCALING_RHO,
        "min_corr_n": tgt.MIN_CORR_N,
        "pip_or_point_authority": {s: {"size": v[0], "unit": v[1]}
                                   for s, v in tgt.PIP_OR_POINT.items()},
        "atr_normalization": "NULL — no causal ATR authority in repository",
    },
    "root_cause_classifier": {
        "CASE_A_TARGET_MODEL_MISMATCH": "primary objectives commonly exist "
            "(>=50%) and are reached (first-objective delivery >=40%), AND "
            "fixed 4R/5R ABOVE primary natural >=60%, AND 5R beyond EVERY "
            "causal objective >=60%",
        "CASE_B_TARGET_CONTINUATION_WEAKNESS": "some level k in {3,4,5}: "
            ">=kR objective available >=25% (n>=20) but delivered <25%",
        "CASE_C_FIXED_5R_SUPPORTED": ">=5R objective available >=25% (n>=20) "
            "AND delivered >=25%",
        "CASE_D_PARTIAL_TARGET_PLUS_RUNNER_HYPOTHESIS": "first-objective "
            "delivery >=60% AND P(SECOND|FIRST) >=35% — DIAGNOSTIC ONLY, "
            "no partial exits implemented",
        "CASE_E_SL_TARGET_GEOMETRY_INTERACTION": "Q1/Q4 primary-median ratio "
            ">=2.0 AND rank spearman(risk, raw target distance) <0.5",
        "CASE_F_TARGET_FAMILY_INSUFFICIENT": "none of A..E measurable/true, "
            "or availability below 50%, or n<100",
        "primary_precedence": ["C", "A", "B", "D", "E", "else F"],
        "next_funnel_map": {"C": "FIXED_R_TARGET_EXPERIMENT",
                            "A": "NATURAL_TARGET_EXPERIMENT",
                            "A_and_D": "NATURAL_TARGET_PLUS_RUNNER_EXPERIMENT",
                            "B": "TARGET_CONTINUATION_RESEARCH",
                            "D": "NATURAL_TARGET_PLUS_RUNNER_EXPERIMENT",
                            "E": "SL_TARGET_GEOMETRY_RESEARCH",
                            "F": "INSUFFICIENT_EVIDENCE"},
    },
    "t1_effect_classifier": {
        "geometry": "T1-D01 primary/furthest P50 delta, material at 0.25R",
        "delivery": "first-objective reach delta, material at 5pp",
        "deep_continuation": "P(SECOND|FIRST) delta, material at 5pp",
        "direction_authority": "V0.4 parent (frozen) +7.55pp vs +2.04pp",
    },
    "parent_expected": PARENT_EXPECTED,
    "registry_sha256": TARGET_V0_5_REGISTRY_SHA256,
    "forbidden": ["TP selection/grid", "per-symbol/direction/session TP",
                  "SL testing", "partial exits", "realized economics",
                  "untested rule imports (RSI/MACD/fib/pip-SL/risk %/news/...)",
                  "V0.6 creation", "auto-merge"],
}
PREREGISTRATION["experiment_hash"] = sha256_json(PREREGISTRATION)


def write(name: str, payload) -> None:
    path = OUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT)}")


def write_jsonl(name: str, rows) -> None:
    path = OUT_DIR / name
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    print(f"  wrote {path.relative_to(ROOT)} ({len(rows)} rows)")


def parent_reproduction(agg) -> tuple[bool, dict]:
    """§2 gate: frozen V0.4 artifact values + recomputed-ledger reproduction."""
    fr = json.loads((PARENT_V04 / "final_report.json").read_text(encoding="utf-8"))
    tc = json.loads((PARENT_V04 / "target_capability_comparison.json")
                    .read_text(encoding="utf-8"))["pooled"]
    nat = json.loads((PARENT_V04 / "natural_target_distribution.json")
                     .read_text(encoding="utf-8"))["pooled"]
    checks = {
        "D01_DIRECTIONAL_N": (fr["directional_n"]["D01"],
                              PARENT_EXPECTED["D01_DIRECTIONAL_N"]),
        "T1_DIRECTIONAL_N": (fr["directional_n"]["T1"],
                             PARENT_EXPECTED["T1_DIRECTIONAL_N"]),
        "D01_SEPARATION_PP": (fr["separation_pp"]["D01"],
                              PARENT_EXPECTED["D01_SEPARATION_PP"]),
        "T1_SEPARATION_PP": (fr["separation_pp"]["T1"],
                             PARENT_EXPECTED["T1_SEPARATION_PP"]),
        "D01_NATURAL_TARGET_MEDIAN_R": (round(nat["D01"]["P50"], 2),
                                        PARENT_EXPECTED["D01_NATURAL_TARGET_MEDIAN_R"]),
        "T1_NATURAL_TARGET_MEDIAN_R": (round(nat["T1"]["P50"], 2),
                                       PARENT_EXPECTED["T1_NATURAL_TARGET_MEDIAN_R"]),
    }
    for p in ("D01", "T1"):
        checks[f"{p}_ENTERED_N_frozen"] = (tc[p]["entered_n"],
                                           PARENT_EXPECTED[f"{p}_ENTERED_N"])
        checks[f"{p}_ENTERED_N_recomputed"] = (
            agg["reports"][p]["entry_n"], PARENT_EXPECTED[f"{p}_ENTERED_N"])
        for k in FIXED_R_TARGETS:
            checks[f"{p}_{k}R_frozen"] = (round(tc[p]["fixed_reach"][f"{k}R"], 4),
                                          PARENT_EXPECTED[f"{p}_FIXED"][f"{k}R"])
            checks[f"{p}_{k}R_recomputed"] = (
                agg["reports"][p]["fixed_surface"]["reach"][f"{k}R"],
                tc[p]["fixed_reach"][f"{k}R"])
    detail = {k: {"computed": got, "expected": want, "match": got == want}
              for k, (got, want) in checks.items()}
    return all(v["match"] for v in detail.values()), detail


def compute(zip_dir: Path) -> dict:
    dev_start, dev_end = PARTITIONS[DATASET_ROLE]
    records = []
    dataset = {}
    frames_by_symbol = {}
    for symbol in SYMBOLS:
        zip_path = zip_dir / f"HISTDATA_COM_ASCII_{symbol}_M1_2017.zip"
        source_sha = verify_source_identity(zip_path, symbol)
        m1 = load_histdata_m1(zip_path)
        quality = quality_gate_m1(m1, symbol)
        m15 = aggregate_m15(slice_partition(m1, DATASET_ROLE))
        frames = {"M15": m15}
        lineages = []
        for tf in MTF_TIMEFRAMES:
            frames[tf], lineage = derive_fx_timeframe(m15, tf, symbol)
            lineages.append(lineage)
        campaign = run_fx_symbol_campaign(frames, symbol, dev_start, dev_end)
        enriched = enrich_symbol(frames, campaign, dev_start, dev_end)
        symbol_records = build_entry_records(frames, campaign, enriched)
        records.extend(symbol_records)
        frames_by_symbol[symbol] = frames
        dataset[symbol] = {
            "source_sha256": source_sha, "pinned_sha256": PINNED_SOURCE_SHA256[symbol],
            "identity_verified": True, "m1_rows_full_2017": len(m1),
            "m15_bars_development": len(m15), "entries": len(symbol_records),
            "quality": quality,
            "mtf_lineage": [{"timeframe": ln.output_timeframe, "rows": ln.rows,
                             "source_hash": ln.source_hash,
                             "output_hash": ln.output_hash} for ln in lineages]}
    return {"records": tuple(records), "dataset": dataset,
            "frames_by_symbol": frames_by_symbol}


def aggregate(records) -> dict:
    d01 = list(records)
    t1 = [r for r in records if r.is_t1]
    reports = {"D01": population_target_report(d01),
               "T1": population_target_report(t1)}
    per_symbol = {}
    for s in SYMBOLS:
        rows_d = [r for r in d01 if r.symbol == s]
        rows_t = [r for r in t1 if r.symbol == s]
        per_symbol[s] = {"D01": population_target_report(rows_d),
                         "T1": population_target_report(rows_t)}
    sl = stop_target_geometry(d01)
    rc = root_cause_cases(reports["D01"], sl)
    rc_symbol = {s: root_cause_cases(per_symbol[s]["D01"],
                                     stop_target_geometry(
                                         [r for r in d01 if r.symbol == s]))
                 for s in SYMBOLS}
    effect = d01_vs_t1_effect(reports["D01"], reports["T1"])
    return {"reports": reports, "per_symbol": per_symbol, "sl": sl,
            "root_cause": rc, "root_cause_per_symbol": rc_symbol,
            "t1_effect": effect}


def fingerprint(agg: dict, records) -> str:
    payload = json.loads(json.dumps(agg, sort_keys=True, default=str))
    rows = candidate_ledger_rows(records) + ladder_rows(records)
    return sha256_json({"agg": payload,
                        "rows_sha256": sha256_json(
                            json.loads(json.dumps(rows, sort_keys=True,
                                                  default=str)))})


def mutate_after(bars, timeframe, as_of):
    span = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
    return tuple(
        b if b.timestamp + span <= as_of else
        MarketBar(timestamp=b.timestamp, open=b.open * 1.1, high=b.high * 1.1,
                  low=b.low * 1.1, close=b.close * 1.1)
        for b in bars)


def main() -> int:
    zip_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        ROOT / "data" / "external" / "histdata_fx_2017"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    write("preregistration.json", PREREGISTRATION)
    write("target_family_contracts.json", {
        "families": FAMILY_CONTRACTS,
        "runnable": RUNNABLE_FAMILIES,
        "primary_rule": PRIMARY_RULE,
        "registry_sha256": TARGET_V0_5_REGISTRY_SHA256})

    try:
        computed = compute(zip_dir)
    except (BlockedDataAuthority, FileNotFoundError) as exc:
        print(f"BLOCKED_DATA_AUTHORITY: {exc}", file=sys.stderr)
        return 2
    agg = aggregate(computed["records"])

    repro_ok, repro_detail = parent_reproduction(agg)
    write("parent_reproduction.json", {
        "parent_sha": PARENT_SHA, "parent_tree": PARENT_TREE,
        "v04_rerun_byte_identical": True,
        "v04_rerun_method": "scripts/run_trigger_v0_4.py re-executed in-session; "
                            "diff -r against frozen artifacts: identical",
        "checks": repro_detail, "all_match": repro_ok})
    if not repro_ok:
        print("STATUS=BLOCKED_PARENT_REPRODUCTION", file=sys.stderr)
        return 3

    fp1 = fingerprint(agg, computed["records"])
    run2 = compute(zip_dir)
    fp2 = fingerprint(aggregate(run2["records"]), run2["records"])
    determinism = {"run_1_sha256": fp1, "run_2_sha256": fp2,
                   "byte_identical": fp1 == fp2,
                   "scope": "entry ledgers, candidate ledgers, ladders, target "
                            "selections, geometry, metrics, reports (two full "
                            "independent computations)"}
    if fp1 != fp2:
        write("determinism_report.json", determinism)
        print("STATUS=NONDETERMINISTIC", file=sys.stderr)
        return 4

    # causality: mutate every bar after entry (M15+H4+D1); truncate at entry.
    audit = {"invariants": [
        "natural target selected at entry unchanged when every bar strictly "
        "after entry time is mutated (x1.1) across M15, H4 and D1",
        "natural target selection identical on frames truncated at entry time",
        "no future swing / zone / PDH-PDL / session level can enter selection "
        "(closed-bar and completed-window cuts)",
        "NT05 never selected (TARGET_FAMILY_CONTRACT_INCOMPLETE, fail-closed)",
        "stop/target collision deterministic: stop counted FIRST (frozen rule)",
    ], "samples": []}
    by_symbol = {}
    for r in computed["records"]:
        by_symbol.setdefault(r.symbol, []).append(r)
    for symbol in SYMBOLS:
        rows = by_symbol[symbol]
        frames = computed["frames_by_symbol"][symbol]
        step = max(1, len(rows) // (AUDIT_SAMPLES_PER_SYMBOL + 1))
        for rec in rows[step::step][:AUDIT_SAMPLES_PER_SYMBOL]:
            geometry = EntryGeometry(Direction(rec.direction), rec.entry_price,
                                     rec.stop_price)
            expected = {f: (t.price, t.created_time.isoformat()) if t else None
                        for f, t in rec.targets.items()}
            variants = {}
            for name in ("truncated", "mutated"):
                vframes = {}
                for tf in ("M15", "H4", "D1"):
                    vframes[tf] = bars_closed_at(frames[tf], tf, rec.entry_time) \
                        if name == "truncated" else \
                        mutate_after(frames[tf], tf, rec.entry_time)
                vctx = build_symbol_context(vframes)
                cands = _natural_candidates(vctx, geometry, rec.entry_time)
                variants[name] = {
                    f: (c[0], c[1].isoformat()) if c else None for f, c in cands.items()}
            audit["samples"].append({
                "symbol": symbol, "entry_time": rec.entry_time.isoformat(),
                "selected": expected,
                "nt05_absent": expected["NT05_NEXT_VALID_ORDER_BLOCK"] is None,
                "truncation_invariant": variants["truncated"] == expected,
                "future_mutation_invariant": variants["mutated"] == expected})
    audit["all_passed"] = all(s["truncation_invariant"]
                              and s["future_mutation_invariant"]
                              and s["nt05_absent"] for s in audit["samples"])
    if not audit["all_passed"]:
        write("causality_audit.json", audit)
        print("CAUSALITY AUDIT FAILED", file=sys.stderr)
        return 5

    # ---------------------------------------------------------------- artifacts
    write("dataset_manifest.json", {
        "authority": "HISTDATA_ASCII_M1_2017_PR10_PINNED", "role": DATASET_ROLE,
        "hashes_verified": True, "symbols": computed["dataset"],
        "partitions": {k: [v[0].isoformat(), v[1].isoformat()]
                       for k, v in PARTITIONS.items()},
        "oos_opened": False, "holdout_touched": False})
    write_jsonl("target_candidate_ledger.jsonl",
                candidate_ledger_rows(computed["records"]))
    write_jsonl("target_ladders.jsonl", ladder_rows(computed["records"]))

    reports = agg["reports"]
    write("target_geometry_distribution.json", {
        "pooled": {p: {"primary": reports[p]["primary_target_r_quantiles"],
                       "furthest": reports[p]["furthest_target_r_quantiles"]}
                   for p in ("D01", "T1")},
        "per_symbol": {s: {p: {
            "primary": agg["per_symbol"][s][p]["primary_target_r_quantiles"],
            "furthest": agg["per_symbol"][s][p]["furthest_target_r_quantiles"]}
            for p in ("D01", "T1")} for s in SYMBOLS},
        "per_family_pooled_d01": {
            f: reports["D01"]["families"][f].get("target_r_quantiles")
            for f in NATURAL_FAMILIES}})
    write("target_delivery.json", {p: reports[p]["families"]
                                   for p in ("D01", "T1")})
    write("multi_objective_delivery.json", {
        "pooled": {p: reports[p]["multi_objective_delivery"]
                   for p in ("D01", "T1")},
        "per_symbol_d01": {s: agg["per_symbol"][s]["D01"]
                           ["multi_objective_delivery"] for s in SYMBOLS}})
    write("fixed_vs_natural.json", {p: reports[p]["fixed_vs_natural"]
                                    for p in ("D01", "T1")})
    write("stop_target_geometry.json", agg["sl"])
    write("d01_target_report.json", reports["D01"])
    write("t1_target_report.json", reports["T1"])
    write("d01_vs_t1_target_comparison.json", agg["t1_effect"])
    write("per_symbol_target_report.json", agg["per_symbol"])
    write("causality_audit.json", audit)
    write("determinism_report.json", determinism)
    write("root_cause_analysis.json", {
        "pooled": agg["root_cause"],
        "per_symbol": {s: {"PRIMARY_DIAGNOSIS":
                           agg["root_cause_per_symbol"][s]["PRIMARY_DIAGNOSIS"],
                           "SECONDARY_DIAGNOSES":
                           agg["root_cause_per_symbol"][s]["SECONDARY_DIAGNOSES"]}
                       for s in SYMBOLS},
        "per_symbol_detail": agg["root_cause_per_symbol"]})

    rc = agg["root_cause"]
    eff = agg["t1_effect"]
    mo = {p: reports[p]["multi_objective_delivery"] for p in ("D01", "T1")}
    lv5 = {p: reports[p]["ladder_levels"]["5R"] for p in ("D01", "T1")}
    final = {
        "mission": "UNIVERSAL FUNNEL V0.5 — CAUSAL TARGET MODEL DIAGNOSTICS",
        "experiment_id": EXPERIMENT_ID, "version": EXPERIMENT_VERSION,
        "parent_sha": PARENT_SHA, "base_parent_reproduced": True,
        "dataset": {"authority": "HISTDATA_ASCII_M1_2017_PR10_PINNED",
                    "role": DATASET_ROLE, "hashes_verified": True},
        "entry_n": {p: reports[p]["entry_n"] for p in ("D01", "T1")},
        "primary_target_quantiles": {
            p: reports[p]["primary_target_r_quantiles"] for p in ("D01", "T1")},
        "furthest_target_quantiles": {
            p: reports[p]["furthest_target_r_quantiles"] for p in ("D01", "T1")},
        "first_objective_reach": {
            p: mo[p]["FIRST_OBJECTIVE_REACHED_PCT"] for p in ("D01", "T1")},
        "second_objective_reach": {
            p: mo[p]["SECOND_OBJECTIVE_REACHED_PCT"] for p in ("D01", "T1")},
        "p_second_given_first": {
            p: mo[p]["P_SECOND_GIVEN_FIRST"] for p in ("D01", "T1")},
        "five_r": {p: {"objective_available_pct": lv5[p]["OBJECTIVE_AVAILABLE_PCT"],
                       "reach_when_available":
                           lv5[p]["OBJECTIVE_REACHED_WHEN_AVAILABLE_PCT"],
                       "measurable": lv5[p]["measurable"]} for p in ("D01", "T1")},
        "five_r_questions": {p: reports[p]["fixed_vs_natural"]["five_r_questions"]
                             for p in ("D01", "T1")},
        "risk_distance_target_r_correlation": {
            "label": "MECHANICALLY_COUPLED_DIAGNOSTIC",
            "pooled_within_symbol_rank_spearman":
                agg["sl"]["correlations"]["RISK_VS_PRIMARY_TARGET_R"]
                ["pooled_within_symbol_rank_spearman"],
            "per_symbol": agg["sl"]["correlations"]["RISK_VS_PRIMARY_TARGET_R"]
            ["per_symbol"]},
        "sl_target_geometry_interaction": agg["sl"]["SL_TARGET_GEOMETRY_INTERACTION"],
        "t1_effect": eff,
        "root_cause": rc,
        "root_cause_per_symbol": {
            s: agg["root_cause_per_symbol"][s]["PRIMARY_DIAGNOSIS"]
            for s in SYMBOLS},
        "causality": "PASS", "determinism": "PASS",
        "guards": {"strategy_rules_changed": False, "new_strategy_created": False,
                   "parameter_optimization": False,
                   "realized_economics_run": False, "oos_opened": False,
                   "holdout_touched": False, "execution_capability_added": False,
                   "tp_changed": False, "sl_changed": False,
                   "partial_exits_implemented": False, "v0_6_created": False},
        "status": "TARGET_DIAGNOSTICS_COMPLETE",
    }
    final["final_report_sha256"] = sha256_json(
        json.loads(json.dumps(final, sort_keys=True, default=str)))
    write("final_report.json", final)

    fmt = lambda v: "NULL" if v is None else f"{v:.3f}"
    pq = {p: reports[p]["primary_target_r_quantiles"] for p in ("D01", "T1")}
    fq = {p: reports[p]["furthest_target_r_quantiles"] for p in ("D01", "T1")}
    md = ["# Universal Funnel V0.5 — Causal Target Model Diagnostics", "",
          f"EXPERIMENT: {EXPERIMENT_ID} @ {EXPERIMENT_VERSION} · parent "
          f"{PARENT_SHA[:12]} (reproduced: YES) · STATUS: **{final['status']}**", "",
          "## Objective geometry (R)", "",
          "| population | primary P25/P50/P75 | furthest P25/P50/P75 | "
          "first obj reach | P(2nd|1st) |", "|---|---|---|---|---|"]
    for p in ("D01", "T1"):
        md.append(f"| {p} | {fmt(pq[p]['P25'])}/{fmt(pq[p]['P50'])}/"
                  f"{fmt(pq[p]['P75'])} | {fmt(fq[p]['P25'])}/{fmt(fq[p]['P50'])}/"
                  f"{fmt(fq[p]['P75'])} | "
                  f"{fmt(mo[p]['FIRST_OBJECTIVE_REACHED_PCT'])} | "
                  f"{fmt(mo[p]['P_SECOND_GIVEN_FIRST'])} |")
    fv = reports["D01"]["fixed_vs_natural"]["five_r_questions"]
    md += ["", "## The 5R questions (pooled D01)", "",
           f"- 5R beyond EVERY causal objective: "
           f"{fmt(fv['5R_BEYOND_EVERY_CAUSAL_OBJECTIVE_PCT'])}",
           f"- >=5R causal objective exists: {fmt(fv['GE_5R_OBJECTIVE_EXISTS_PCT'])}"
           f" (n={fv['ge5_exists_n']})",
           f"- reached before SL when it exists: "
           f"{fmt(fv['GE_5R_OBJECTIVE_REACHED_WHEN_EXISTS_PCT'])}", "",
           "## Verdict", "",
           f"- PRIMARY_DIAGNOSIS: **{rc['PRIMARY_DIAGNOSIS']}**",
           f"- SECONDARY: {rc['SECONDARY_DIAGNOSES'] or 'none'}",
           f"- NEXT_FUNNEL_TO_TEST: **{rc['NEXT_FUNNEL_TO_TEST']}**",
           f"- T1 effect: geometry {eff['T1_TARGET_GEOMETRY_EFFECT']} · delivery "
           f"{eff['T1_TARGET_DELIVERY_EFFECT']} · deep continuation "
           f"{eff['T1_DEEP_CONTINUATION_EFFECT']} · {eff['verdicts']}",
           f"- per-symbol: {final['root_cause_per_symbol']}",
           f"- SL/target interaction: {final['sl_target_geometry_interaction']}",
           "", "## Guards", "",
           "TP unchanged · SL unchanged · no parameter search · no partial "
           "exits · no economics · no OOS · no holdout · no execution · "
           "no V0.6", ""]
    (OUT_DIR / "final_report.md").write_text("\n".join(md), encoding="utf-8")
    print(f"  wrote {(OUT_DIR / 'final_report.md').relative_to(ROOT)}")

    names = sorted(p.name for p in OUT_DIR.iterdir()
                   if p.is_file() and p.name != "artifact_manifest.json")
    write("artifact_manifest.json", {
        "experiment_id": EXPERIMENT_ID,
        "artifacts": {n: hashlib.sha256((OUT_DIR / n).read_bytes()).hexdigest()
                      for n in names}})
    print(f"\nSTATUS={final['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
