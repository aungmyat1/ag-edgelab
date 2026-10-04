"""Universal Funnel V0.5 — TARGET MODEL DIAGNOSTICS runner.

Contract order:
  1. preregistration.json written BEFORE any evaluation result exists;
  2. pinned dataset identities verified fail-closed;
  3. frozen V0.3/V0.4 engines produce all entries and policy states; every
     reconstructed entry must reproduce the frozen ledger exactly;
  4. pooled D01/T1 entry populations must equal the frozen parent values,
     else STATUS=BASELINE_REPRODUCTION_FAIL;
  5. full computation runs twice — any hash difference => NONDETERMINISTIC;
  6. adversarial causality audit: bars after entry mutated, frames truncated
     at entry — natural target selection must be identical.

No TP change, no SL change, no parameter search, no economics, no OOS,
no holdout, no execution.
"""

from __future__ import annotations

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
    EXPERIMENT_ID, EXPERIMENT_VERSION, NATURAL_FAMILIES, NEAREST_OBJECTIVE_RULE,
    PARENT_SHA, PARENT_TREE, SELECTION_REASON, TARGET_V0_5_REGISTRY_SHA256,
    _natural_candidates, build_entry_records, build_symbol_context,
    continuation_chain, direction_asymmetry, distribution_comparison,
    entry_ledger_rows, family_report, fixed_surface, level_diagnostic,
    level_verdict, objective_ladder_report, quantile_block, root_cause,
    sl_target_interaction, stratum_diagnosis, target_fit_curve)

OUT_DIR = ROOT / "data" / "artifacts" / "universal_funnel_v0_5_target"
PARENT_V04 = ROOT / "data" / "artifacts" / "universal_funnel_v0_4_trigger"
DATASET_ROLE = "DEVELOPMENT"
AUDIT_SAMPLES_PER_SYMBOL = 4

PREREGISTRATION = {
    "experiment_id": EXPERIMENT_ID, "version": EXPERIMENT_VERSION,
    "parent_sha": PARENT_SHA, "parent_tree": PARENT_TREE,
    "registered_before_results": True,
    "question": "is the frozen fixed-R target model mismatched with the causal "
                "natural market objective?",
    "frozen_upstream": ["D01", "T1", "T2", "market structure", "premium/discount",
                        "H1 internal flow", "location", "sweep/range/trend",
                        "confirmation", "entry geometry", "SL geometry",
                        "session definitions", "dataset lineage"],
    "primary_populations": ["D01 confirmed entries", "T1 confirmed entries"],
    "t2_role": "diagnostic control only, never a candidate target policy",
    "natural_families": {
        "NT01_NEXT_SWING": "most recent confirmed opposing H4 swing beyond entry",
        "NT02_PDH_PDL": "directionally appropriate previous-day high/low",
        "NT03_LIQUIDITY": "nearest of the last 6 confirmed opposing H4 swings "
                          "beyond entry (frozen V0.3 liquidity basis)",
        "NT04_OPPOSING_SUPPLY_DEMAND": "nearest opposing S/D zone edge beyond entry "
                                       "(deterministic causal contract -> RUN)",
        "NT05_FVG_IMBALANCE": "nearest opposing H4 FVG midpoint beyond entry "
                              "(deterministic causal contract -> RUN)",
    },
    "target_existence_rule": "TARGET_CREATED_TIME <= ENTRY_TIME enforced per target",
    "nearest_objective_rule": NEAREST_OBJECTIVE_RULE,
    "nearest_objective_eligibility": [
        "target existed at entry (TARGET_CREATED_TIME <= ENTRY_TIME)",
        "target is in the intended trade direction",
        "target is beyond entry (positive distance)",
        "target family is contract-complete",
        "target not invalidated at entry",
        "then: smallest positive absolute price distance from entry "
        "(== min positive TARGET_R under the frozen SL)"],
    "selection_reason": SELECTION_REASON,
    "objective_ladder": "full ladder preserved per entry (FIRST / SECONDARY / "
                        "EXTENDED / MAX objectives kept distinct); price is "
                        "never assumed to stop at the nearest objective",
    "collision_rule": "stop counted FIRST (frozen V0.3 fail-closed rule)",
    "amendments": [{
        "id": "A-J_GOVERNANCE_HARDENING",
        "authority": "owner directive, 2026-10-04",
        "changes": [
            "TARGET_FIT_TOLERANCE_PCT=5.0 ratio rule replaces the 0.1.0 "
            "absolute 0.25R tolerance; invalid/unavailable natural targets "
            "classify as NULL with reason INVALID_OR_UNAVAILABLE_NATURAL_TARGET",
            "per-family target records persisted per entry (never collapsed)",
            "eligibility-gated NEAREST_CAUSAL_OBJECTIVE + objective ladder + "
            "reach sequence (FIRST/SECOND/EXTENDED, MAX_CAUSAL_OBJECTIVE)",
            "raw price/pip distances persisted alongside R metrics "
            "(pip authority fail-closed: XAUUSD pips = NULL)",
            "Pearson+Spearman coupling diagnostics; RISK vs TARGET_R labelled "
            "MECHANICALLY_COUPLED_DIAGNOSTIC (denominator coupling)",
            "risk quartiles are within-symbol distribution-based (no invented "
            "pip thresholds) with full per-quartile capability tables",
            "root-cause evidence refinement: TARGET_MODEL_MISMATCH requires "
            "existence + materially-beyond + reachability legs, never merely "
            "a low natural median; SL interaction requires raw-distance AND "
            "stratified evidence",
        ],
        "note": "the superseded 0.1.0 run's artifacts were discarded and the "
                "entire evaluation recomputed under this amendment"}],
    "thresholds": {
        "target_fit_tolerance_pct": tgt.TARGET_FIT_TOLERANCE_PCT,
        "deterioration_pp": tgt.DETERIORATION_PP,
        "support_low": tgt.SUPPORT_LOW, "realize_low": tgt.REALIZE_LOW,
        "realize_min_n": tgt.REALIZE_MIN_N,
        "median_mismatch_r_corroborating_only": tgt.MEDIAN_MISMATCH_R,
        "mismatch_beyond_pct": tgt.MISMATCH_BEYOND_PCT,
        "natural_reachable_low": tgt.NATURAL_REACHABLE_LOW,
        "min_stratum_n": tgt.MIN_STRATUM_N,
        "family_insufficient_pct": tgt.FAMILY_INSUFFICIENT_PCT,
        "asymmetry_median_r": tgt.ASYMMETRY_MEDIAN_R,
        "asymmetry_reach_pp": tgt.ASYMMETRY_REACH_PP,
        "sl_interaction_ratio": tgt.SL_INTERACTION_RATIO,
        "raw_coscaling_rho": tgt.RAW_COSCALING_RHO,
        "min_corr_n": tgt.MIN_CORR_N,
        "tail_shift_r": tgt.TAIL_SHIFT_R,
        "pip_size_authority": tgt.PIP_SIZE,
    },
    "registry_sha256": TARGET_V0_5_REGISTRY_SHA256,
    "forbidden": ["TP selection (e.g. pick 2R/2.5R because it wins)",
                  "TP parameter search", "per-symbol/direction/session TP",
                  "SL testing", "realized economics"],
}
PREREGISTRATION["experiment_hash"] = sha256_json(PREREGISTRATION)


def write(name: str, payload) -> None:
    path = OUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT)}")


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
    pops = {"D01": d01, "T1": t1}

    def nearest_vals(rows):
        return [r.nearest_target_r for r in rows if r.nearest_target_r is not None]

    def pop_summary(rows):
        return {"entry_n": len(rows),
                "by_symbol": {s: sum(1 for r in rows if r.symbol == s) for s in SYMBOLS},
                "by_direction": {d: sum(1 for r in rows if r.direction == d)
                                 for d in ("BULL", "BEAR")},
                "by_session": {sess: sum(1 for r in rows if r.session == sess)
                               for sess in ("ASIAN", "LONDON", "LONDON_NEWYORK_OVERLAP",
                                            "NEW_YORK", "OFF_SESSION")},
                "risk_distance_quantiles": quantile_block(
                    [r.risk_distance for r in rows])}

    def stratum_with_reach(rows):
        d = stratum_diagnosis(rows)
        n = len(rows)
        d["reach_2r"] = (sum(1 for r in rows if r.fixed_reached.get(2, False)) / n) \
            if n else None
        return d

    surfaces = {p: fixed_surface(rows) for p, rows in pops.items()}
    chains = {p: continuation_chain(rows) for p, rows in pops.items()}
    families = {p: family_report(rows) for p, rows in pops.items()}
    fit = {p: target_fit_curve(rows) for p, rows in pops.items()}
    levels = {p: {f"{k}R": level_diagnostic(rows, k) for k in (2, 3, 4, 5)}
              for p, rows in pops.items()}
    geometry = {
        "D01": quantile_block(nearest_vals(d01)),
        "T1": quantile_block(nearest_vals(t1)),
        "by_symbol_d01": {s: quantile_block(nearest_vals(
            [r for r in d01 if r.symbol == s])) for s in SYMBOLS},
        "by_direction_d01": {d: quantile_block(nearest_vals(
            [r for r in d01 if r.direction == d])) for d in ("BULL", "BEAR")},
        "by_session_d01": {sess: quantile_block(nearest_vals(
            [r for r in d01 if r.session == sess]))
            for sess in ("ASIAN", "LONDON", "LONDON_NEWYORK_OVERLAP",
                         "NEW_YORK", "OFF_SESSION")},
        # raw-distance geometry (F): per symbol — raw price scales must not be
        # pooled across symbols; pips only where pip authority exists.
        "raw_by_symbol_d01": {s: {
            "risk_distance_price": quantile_block(
                [r.risk_distance for r in rows]),
            "risk_distance_pips": (quantile_block(
                [r.risk_distance_pips for r in rows
                 if r.risk_distance_pips is not None])
                if any(r.risk_distance_pips is not None for r in rows)
                else {"n": 0, "null_reason": "NO_PIP_AUTHORITY"}),
            "nearest_target_distance_price": quantile_block(
                [r.nearest_distance for r in rows
                 if r.nearest_distance is not None]),
            "mfe_distance_price": quantile_block([r.mfe_distance for r in rows]),
            "mae_distance_price": quantile_block([r.mae_distance for r in rows]),
        } for s in SYMBOLS for rows in [[r for r in d01 if r.symbol == s]]}}
    ladder = {p: objective_ladder_report(rows) for p, rows in pops.items()}
    symbol_diags = {s: stratum_with_reach([r for r in d01 if r.symbol == s])
                    for s in SYMBOLS}
    bull = stratum_with_reach([r for r in d01 if r.direction == "BULL"])
    bear = stratum_with_reach([r for r in d01 if r.direction == "BEAR"])
    asym = direction_asymmetry(bull, bear)
    sl = sl_target_interaction(d01)
    pooled_diag = stratum_with_reach(d01)
    rc = root_cause(pooled_diag, symbol_diags, asym, sl, len(d01))
    sessions = {sess: {
        "n": len(rows),
        "nearest_quantiles": quantile_block(nearest_vals(rows)),
        "fixed_reach": fixed_surface(rows)["reach"] if rows else None,
        "continuation": continuation_chain(rows)["chain"] if rows else None}
        for sess in ("ASIAN", "LONDON", "LONDON_NEWYORK_OVERLAP", "NEW_YORK",
                     "OFF_SESSION")
        for rows in [[r for r in d01 if r.session == sess]]}
    mfe_mae = {p: {"mfe_r": quantile_block([r.mfe_r for r in rows]),
                   "mae_r": quantile_block([r.mae_r for r in rows]),
                   "risk_distance": quantile_block([r.risk_distance for r in rows])}
               for p, rows in pops.items()}
    return {"pop_summary": {p: pop_summary(rows) for p, rows in pops.items()},
            "surfaces": surfaces, "chains": chains, "families": families,
            "fit": fit, "levels": levels, "geometry": geometry, "ladder": ladder,
            "symbol_diags": symbol_diags, "bull": bull, "bear": bear, "asym": asym,
            "sl": sl, "pooled_diag": pooled_diag, "root_cause": rc,
            "sessions": sessions, "mfe_mae": mfe_mae,
            "comparison": distribution_comparison(d01, t1)}


def fingerprint(agg: dict) -> str:
    return sha256_json(json.loads(json.dumps(agg, sort_keys=True, default=str)))


def check_baseline(agg: dict) -> tuple[bool, dict]:
    v04 = json.loads((PARENT_V04 / "target_capability_comparison.json")
                     .read_text(encoding="utf-8"))["pooled"]
    checks = {"D01_ENTRY_N": (agg["pop_summary"]["D01"]["entry_n"], v04["D01"]["entered_n"]),
              "T1_ENTRY_N": (agg["pop_summary"]["T1"]["entry_n"], v04["T1"]["entered_n"])}
    for p in ("D01", "T1"):
        for k in FIXED_R_TARGETS:
            checks[f"{p}_{k}R"] = (agg["surfaces"][p]["reach"][f"{k}R"],
                                   v04[p]["fixed_reach"][f"{k}R"])
    detail = {k: {"computed": got, "frozen": want, "match": got == want}
              for k, (got, want) in checks.items()}
    return all(v["match"] for v in detail.values()), detail


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
    write("experiment_identity.json", {
        "experiment_id": EXPERIMENT_ID, "version": EXPERIMENT_VERSION,
        "parent_sha": PARENT_SHA, "parent_tree": PARENT_TREE,
        "parent_status": "TRIGGER_RESEARCH_COMPLETE", "pr": 14,
        "experiment_hash": PREREGISTRATION["experiment_hash"],
        "registry_sha256": TARGET_V0_5_REGISTRY_SHA256})

    try:
        computed = compute(zip_dir)
    except (BlockedDataAuthority, FileNotFoundError) as exc:
        print(f"BLOCKED_DATA_AUTHORITY: {exc}", file=sys.stderr)
        return 2
    agg = aggregate(computed["records"])
    fp1 = fingerprint(agg)
    fp2 = fingerprint(aggregate(compute(zip_dir)["records"]))
    determinism = {"run_1_sha256": fp1, "run_2_sha256": fp2,
                   "byte_identical": fp1 == fp2,
                   "scope": "entry ledgers, target selections, geometry, metrics, "
                            "reports (two full independent computations)"}
    if fp1 != fp2:
        write("determinism_audit.json", determinism)
        print("STATUS=NONDETERMINISTIC", file=sys.stderr)
        return 4

    baseline_ok, baseline_detail = check_baseline(agg)
    if not baseline_ok:
        write("d01_baseline_check.json", baseline_detail)
        print("STATUS=BASELINE_REPRODUCTION_FAIL", file=sys.stderr)
        return 3

    # causality: mutate every bar after entry; truncate frames at entry.
    audit = {"invariants": [
        "natural target selected at entry unchanged when every bar strictly after "
        "entry time is mutated (x1.1)",
        "natural target selection identical on frames truncated at entry time",
        "no future swing / liquidity / PDH-PDL / supply-demand / FVG can enter "
        "selection (closed-bar cuts)",
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
                vframes = {"M15": frames["M15"]}
                for tf in ("H4", "D1"):
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
                "truncation_invariant": variants["truncated"] == expected,
                "future_mutation_invariant": variants["mutated"] == expected})
    audit["all_passed"] = all(s["truncation_invariant"] and s["future_mutation_invariant"]
                              for s in audit["samples"])
    if not audit["all_passed"]:
        write("causality_audit.json", audit)
        print("CAUSALITY AUDIT FAILED", file=sys.stderr)
        return 5

    # ---------------------------------------------------------------- artifacts
    d01_n = agg["pop_summary"]["D01"]["entry_n"]
    write("dataset_authority.json", {
        "authority": "HISTDATA_ASCII_M1_2017_PR10_PINNED", "role": DATASET_ROLE,
        "hashes_verified": True, "symbols": computed["dataset"],
        "partitions": {k: [v[0].isoformat(), v[1].isoformat()]
                       for k, v in PARTITIONS.items()},
        "oos_opened": False, "holdout_touched": False})
    ledger_rows = entry_ledger_rows(computed["records"])
    write("entry_population_d01.json", {
        "baseline_check": baseline_detail,
        **agg["pop_summary"]["D01"],
        "per_entry_ledger_contract": "every natural family persisted "
                                     "separately per entry (never collapsed); "
                                     "raw price/pip distances alongside R",
        "per_entry_ledger": ledger_rows})
    write("entry_population_t1.json", {
        **agg["pop_summary"]["T1"],
        "per_entry_ledger_note": "T1 rows are the is_t1=true subset of the "
                                 "per_entry_ledger in entry_population_d01.json "
                                 "(not duplicated)"})
    write("fixed_target_surface.json", agg["surfaces"])
    write("continuation_survival.json", {
        **agg["chains"],
        "by_symbol_d01": {s: continuation_chain(
            [r for r in computed["records"] if r.symbol == s])["chain"]
            for s in SYMBOLS}})
    write("mfe_mae_distribution.json", agg["mfe_mae"])
    write("natural_target_inventory.json", {
        "families": PREREGISTRATION["natural_families"],
        "nt04_nt05_status": "RUN (repository contracts deterministic and causal)",
        "availability_d01": {f: agg["families"]["D01"][f]["TARGET_AVAILABLE_PCT"]
                             for f in NATURAL_FAMILIES},
        "nearest_family_share_d01":
            agg["families"]["D01"]["NEAREST_OBJECTIVE"]["family_share"],
        "target_existence_rule": "TARGET_CREATED_TIME <= ENTRY_TIME (asserted "
                                 "per target during the build)"})
    write("natural_target_geometry.json", {
        **agg["geometry"],
        "objective_ladder": agg["ladder"]})
    write("natural_target_reachability.json", {
        "families": agg["families"],
        "objective_ladder_reach_sequence": agg["ladder"]})
    write("fixed_vs_natural_target.json", {"fit": agg["fit"],
                                           "level_diagnostics": agg["levels"]})
    write("target_fit_curve.json", {"central_diagnostic": True, **agg["fit"]})
    write("d01_vs_t1_target_distribution.json", agg["comparison"])
    write("symbol_target_analysis.json", agg["symbol_diags"])
    write("direction_target_analysis.json", {"BULL": agg["bull"], "BEAR": agg["bear"],
                                             "asymmetry": agg["asym"]})
    write("session_target_analysis.json", {
        **agg["sessions"],
        "note": "diagnostic only; session rules unchanged"})
    write("sl_target_interaction.json", agg["sl"])
    write("root_cause_analysis.json", {"pooled": agg["pooled_diag"],
                                       "verdicts_2r_3r_5r": {
                                           k: level_verdict(agg["levels"]["D01"][k])
                                           for k in ("2R", "3R", "5R")},
                                       **agg["root_cause"]})
    write("causality_audit.json", audit)
    write("determinism_audit.json", determinism)

    lv = agg["levels"]["D01"]
    final = {
        "mission": "UNIVERSAL FUNNEL V0.5 — TARGET MODEL DIAGNOSTICS",
        "experiment_id": EXPERIMENT_ID, "version": EXPERIMENT_VERSION,
        "parent_sha": PARENT_SHA, "base_parent_reproduced": True,
        "dataset": {"authority": "HISTDATA_ASCII_M1_2017_PR10_PINNED",
                    "role": DATASET_ROLE, "hashes_verified": True},
        "entry_n": {"D01": d01_n, "T1": agg["pop_summary"]["T1"]["entry_n"]},
        "fixed_reach": {p: agg["surfaces"][p]["reach"] for p in ("D01", "T1")},
        "continuation": {p: agg["chains"][p]["chain"] for p in ("D01", "T1")},
        "earliest_material_deterioration": {
            p: agg["chains"][p]["earliest_material_deterioration"]
            for p in ("D01", "T1")},
        "natural_target_quantiles": {"D01": agg["geometry"]["D01"],
                                     "T1": agg["geometry"]["T1"]},
        "TARGET_FIT_TOLERANCE_PCT": tgt.TARGET_FIT_TOLERANCE_PCT,
        "natural_family_available_pct": {
            f: agg["families"]["D01"][f]["TARGET_AVAILABLE_PCT"]
            for f in NATURAL_FAMILIES},
        "NEAREST_CAUSAL_OBJECTIVE_AVAILABLE_PCT":
            agg["families"]["D01"]["NEAREST_OBJECTIVE"]["TARGET_AVAILABLE_PCT"],
        "MAX_CAUSAL_OBJECTIVE_R_quantiles":
            agg["ladder"]["D01"]["max_causal_objective_r_quantiles"],
        "MULTI_OBJECTIVE_ENTRY_PCT":
            agg["ladder"]["D01"]["MULTI_OBJECTIVE_ENTRY_PCT"],
        "FIRST_OBJECTIVE_REACHED_PCT":
            agg["ladder"]["D01"]["FIRST_OBJECTIVE_REACHED_PCT"],
        "SECOND_OBJECTIVE_REACHED_PCT":
            agg["ladder"]["D01"]["SECOND_OBJECTIVE_REACHED_PCT"],
        "EXTENDED_OBJECTIVE_REACHED_PCT":
            agg["ladder"]["D01"]["EXTENDED_OBJECTIVE_REACHED_PCT"],
        "P_SECOND_REACHED_GIVEN_FIRST_REACHED":
            agg["ladder"]["D01"]["P_SECOND_REACHED_GIVEN_FIRST_REACHED"],
        "RISK_DISTANCE_by_symbol": {
            s: {p: agg["geometry"]["raw_by_symbol_d01"][s]
                ["risk_distance_price"][p] for p in ("P25", "P50", "P75")}
            for s in SYMBOLS},
        "RISK_VS_TARGET_R": {
            "label": "MECHANICALLY_COUPLED_DIAGNOSTIC",
            "pooled_within_symbol_rank_spearman":
                agg["sl"]["correlations"]["RISK_VS_TARGET_R"]
                ["pooled_within_symbol_rank_spearman"],
            "per_symbol": agg["sl"]["correlations"]["RISK_VS_TARGET_R"]
            ["per_symbol"]},
        "RISK_VS_TARGET_DISTANCE": {
            "pooled_within_symbol_rank_spearman":
                agg["sl"]["correlations"]["RISK_VS_TARGET_DISTANCE"]
                ["pooled_within_symbol_rank_spearman"],
            "per_symbol": agg["sl"]["correlations"]["RISK_VS_TARGET_DISTANCE"]
            ["per_symbol"]},
        "RISK_VS_MFE_DISTANCE":
            agg["sl"]["correlations"]["RISK_VS_MFE_DISTANCE"]
            ["pooled_within_symbol_rank_spearman"],
        "RISK_VS_MAE_DISTANCE":
            agg["sl"]["correlations"]["RISK_VS_MAE_DISTANCE"]
            ["pooled_within_symbol_rank_spearman"],
        "RISK_QUARTILE_TARGET_ANALYSIS":
            agg["sl"]["risk_quartile_target_analysis"],
        "target_available_pct":
            agg["families"]["D01"]["NEAREST_OBJECTIVE"]["TARGET_AVAILABLE_PCT"],
        "natural_target_ge_pct": {f"{k}R": lv[f"{k}R"]["SUPPORT_pct"]
                                  for k in (2, 3, 4, 5)},
        "realize_when_supported": {f"{k}R": lv[f"{k}R"]["REALIZE_when_supported_pct"]
                                   for k in (2, 3, 4, 5)},
        "reach_5r_when_natural_lt_5r": lv["5R"]["reach_when_not_supported_pct"],
        "fixed_fit": {f"{k}R": {
            "pct_below_natural": agg["fit"]["D01"][f"{k}R"]["pct_below_natural"],
            "pct_near_natural": agg["fit"]["D01"][f"{k}R"]["pct_near_natural"],
            "pct_beyond_natural": agg["fit"]["D01"][f"{k}R"]["pct_beyond_natural"]}
            for k in (2, 3, 4, 5)},
        "d01_vs_t1_distribution": agg["comparison"],
        "symbol_diagnosis": {s: agg["symbol_diags"][s]["diagnosis"] for s in SYMBOLS},
        "direction_diagnosis": {"BULL": agg["bull"]["diagnosis"],
                                "BEAR": agg["bear"]["diagnosis"],
                                "asymmetry": agg["asym"]},
        "sl_target_interaction": agg["sl"]["SL_TARGET_GEOMETRY_INTERACTION"],
        "root_cause": agg["root_cause"],
        "causality": "PASS", "determinism": "PASS",
        "guards": {"strategy_rules_changed": False, "new_strategy_created": False,
                   "realized_economics_run": False, "oos_opened": False,
                   "holdout_touched": False, "execution_capability_added": False,
                   "tp_changed": False, "sl_changed": False,
                   "parameter_search": False},
        "status": "TARGET_DIAGNOSTICS_COMPLETE"
        if agg["root_cause"]["primary"] != "INSUFFICIENT_EVIDENCE"
        else "INSUFFICIENT_EVIDENCE",
    }
    final["final_report_sha256"] = sha256_json(
        json.loads(json.dumps(final, sort_keys=True, default=str)))
    write("final_report.json", final)

    rc = agg["root_cause"]
    md = ["# Universal Funnel V0.5 — Target Model Diagnostics", "",
          f"EXPERIMENT: {EXPERIMENT_ID} @ {EXPERIMENT_VERSION} · parent "
          f"{PARENT_SHA[:12]} (reproduced: YES) · STATUS: **{final['status']}**", "",
          "## Natural objective vs fixed targets (pooled D01)", "",
          "| level | natural >= level | realize when supported | fit: beyond natural |",
          "|---|---|---|---|"]
    fmt = lambda v: "NULL" if v is None else f"{v:.3f}"
    for k in (2, 3, 4, 5):
        md.append(f"| {k}R | {fmt(lv[f'{k}R']['SUPPORT_pct'])} | "
                  f"{fmt(lv[f'{k}R']['REALIZE_when_supported_pct'])} | "
                  f"{fmt(agg['fit']['D01'][f'{k}R']['pct_beyond_natural'])} |")
    g = agg["geometry"]
    md += ["", f"Nearest-objective quantiles — D01: P10 {g['D01']['P10']:.2f} / P25 "
               f"{g['D01']['P25']:.2f} / P50 {g['D01']['P50']:.2f} / P75 "
               f"{g['D01']['P75']:.2f} / P90 {g['D01']['P90']:.2f}; T1: P50 "
               f"{g['T1']['P50']:.2f}, P90 {g['T1']['P90']:.2f}", "",
           "## Verdict", "",
           f"- PRIMARY_DIAGNOSIS: **{rc['primary']}**",
           f"- SECONDARY: {rc['secondary'] or 'none'}",
           f"- NEXT_RECOMMENDED_RESEARCH: **{rc['next_recommended_research']}**",
           f"- Symbol states: {final['symbol_diagnosis']}",
           f"- SL/target interaction: {final['sl_target_interaction']}", "",
           "## Guards", "",
           "TP unchanged · SL unchanged · no parameter search · no economics · "
           "no OOS · no holdout · no execution", ""]
    (OUT_DIR / "final_report.md").write_text("\n".join(md), encoding="utf-8")
    print(f"  wrote {(OUT_DIR / 'final_report.md').relative_to(ROOT)}")

    import hashlib
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
