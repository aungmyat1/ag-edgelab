#!/usr/bin/env python
"""GEN2_ALD_V1_MULTIYEAR_DEV_R1 — multi-year DEVELOPMENT replay of the FROZEN
ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1 rules.

No rule, threshold, session window or parameter is changed.  The only thing
that differs from the committed single-year campaign is the dataset binding.
OOS and SEALED_HOLDOUT are structurally unreachable: the R2 loader raises on
both for every year.

Usage:
    python scripts/run_gen2_ald_v1_multiyear_dev.py [--workers N] [data_dir]
"""
from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from ag_edgelab.data.fingerprint import canonical_json, sha256_file, sha256_json
from ag_edgelab.data.fx_histdata_multiyear import (
    AUTHORITY_ID,
    BALANCED_PANEL,
    admitted_symbol_years,
    authority_contract,
    load_manifest,
    manifest_path,
    verify_source_identity,
)
from ag_edgelab.strategies import asian_liquidity_displacement_analysis as A
from ag_edgelab.strategies import asian_liquidity_displacement_multiyear as M
from ag_edgelab.strategies import asian_liquidity_displacement_multiyear_analysis as MA
from ag_edgelab.strategies.asian_liquidity_displacement_prereg import (
    POOLED_ENTRY_ELIGIBILITY_N,
    pre_oos_gate_contract,
)
from ag_edgelab.strategies.asian_liquidity_displacement_v1 import (
    CANDIDATE_FAMILY_ID,
    STRATEGY_HASH,
    STRATEGY_ID,
    STRATEGY_VERSION,
    SYMBOL_UNIVERSE,
    TIMEFRAMES,
    VERIFIER_VERSION,
    contract_hashes,
    friction_contract,
    replay_symbol,
    strategy_contract,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_gen2_asian_liquidity_displacement_v1_dev import unit_row  # noqa: E402  (frozen row schema)

OUT = Path("data/artifacts/gen2_asian_liquidity_displacement_v1_multiyear")
CAS = Path("data/external/gen2_ald_v1_multiyear")
READINESS = Path("data/artifacts/edgelab_system_completion_v1/system_readiness.json")
CONTAMINATION = Path("config/governance/candidate_contamination_registry.json")
LEDGER = Path("config/governance/candidate_ledger.json")
OOS_LOG = Path("config/governance/oos_access_log.json")
NARROW = Path("data/artifacts/gen2_asian_liquidity_displacement_v1/final_report.json")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8")


def authority_gate() -> dict:
    readiness = json.loads(READINESS.read_text())
    required = {"SYSTEM_SOFTWARE_COMPLETE": "YES", "RESEARCH_GENERATION_2_ALLOWED": "YES",
                "OOS_ECONOMIC_AUTHORIZED": "NO", "HOLDOUT_AUTHORIZED": "NO",
                "LIVE_EXECUTION_AUTHORIZED": "NO"}
    observed = {k: readiness.get(k) for k in required}
    if observed != required:
        raise SystemExit(f"AUTHORITY GATE FAILED: required={required} observed={observed}")
    return {"state": "PASS", "required": required, "observed": observed,
            "evidence_sha256": sha256_file(READINESS)}


def contamination_check(windows: list[list[str]]) -> dict:
    """Family-freshness read BEFORE any bar is loaded (mission section 1)."""
    registry = json.loads(CONTAMINATION.read_text())
    family = [r for r in registry.get("records", [])
              if r.get("candidate_family_id") == CANDIDATE_FAMILY_ID]
    known, fresh = [], []
    for start, end in windows:
        overlap = [r for r in family if r.get("start", "") < end and start < r.get("end", "")]
        (known if overlap else fresh).append([start, end])
    return {
        "state": "PASS",
        "candidate_family_id": CANDIDATE_FAMILY_ID,
        "windows_checked_n": len(windows),
        "DEVELOPMENT_KNOWN_windows": known,
        "FRESH_DEVELOPMENT_windows_n": len(fresh),
        "prior_exposure_records": family,
        "disclosure": (
            "The 2017 DEV window is already DEVELOPMENT_KNOWN for this family and is reused "
            "deliberately as the comparison baseline. Every other DEV window is fresh "
            "DEVELOPMENT and becomes DEVELOPMENT_KNOWN for the family after this mission. "
            "No OOS or holdout window is read for any year."),
        "registry_sha256": sha256_file(CONTAMINATION),
        "candidate_ledger_sha256": sha256_file(LEDGER),
        "oos_access_log_sha256": sha256_file(OOS_LOG),
    }


# ---------------------------------------------------------------------------
# worker: one symbol-year, loaded and replayed twice (determinism)
# ---------------------------------------------------------------------------

def replay_one(task: tuple[str, int, str | None]) -> dict:
    symbol, year, data_dir = task
    from pathlib import Path as _P
    dd = _P(data_dir) if data_dir else None
    try:
        ds = M.load_year_dataset(symbol, year, dd)
    except Exception as exc:  # fail closed at symbol-year granularity, never patch
        return {"symbol": symbol, "year": year, "state": "EXCLUDED",
                "exclusion_reason": f"{type(exc).__name__}: {exc}", "units": []}
    units = replay_symbol(ds)
    units2 = replay_symbol(ds)
    rows = [unit_row(u) for u in units]
    rows2 = [unit_row(u) for u in units2]
    return {
        "symbol": symbol, "year": year, "state": "ADMITTED",
        "units": units,
        "frame_hashes": ds.frame_hashes,
        "quality": ds.quality,
        "double_pass": "BYTE_IDENTICAL" if canonical_json(rows) == canonical_json(rows2)
                       else "MISMATCH",
        "pass1_sha256": sha256_json(rows),
        "pass2_sha256": sha256_json(rows2),
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir", nargs="?", default=None)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--subset", default=None,
                    help="SMOKE TEST ONLY — comma separated SYMBOL:YEAR list. Forces the "
                         "output into a scratch directory so a partial corpus can never be "
                         "mistaken for the mission artifacts.")
    args = ap.parse_args()

    global OUT
    subset = None
    if args.subset:
        subset = {tuple(x.split(":")[0:1] + [int(x.split(":")[1])])
                  for x in args.subset.split(",")}
        OUT = Path("data/external/gen2_ald_v1_multiyear_smoke")
        OUT.mkdir(parents=True, exist_ok=True)
        for name in ("preregistration.json", "candidate_instance_identity.json"):
            src = Path("data/artifacts/gen2_asian_liquidity_displacement_v1_multiyear") / name
            (OUT / name).write_text(src.read_text())
        print(f"SMOKE SUBSET {sorted(subset)} -> {OUT}")

    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    head, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")

    # ---- 0. identity + authority ----------------------------------------
    rule_identity = M.assert_rule_identity()
    gate = authority_gate()
    prereg = json.loads((OUT / "preregistration.json").read_text())
    if prereg["preregistration_hash"] != M.preregistration()["preregistration_hash"]:
        raise SystemExit("PREREGISTRATION DRIFT: committed hash != recomputed hash")

    # ---- 1. data authority ----------------------------------------------
    manifest = load_manifest(Path(args.data_dir) if args.data_dir else None)
    manifest_sha = sha256_file(manifest_path(Path(args.data_dir) if args.data_dir else None))
    tasks = [t for t in admitted_symbol_years() if subset is None or t in subset]
    discovery = M.data_authority_discovery()
    windows = sorted({tuple(w["window_utc"]) for w in discovery["PERMITTED_DEV_WINDOWS"]})
    contamination = contamination_check([list(w) for w in windows])

    for symbol, year in tasks:
        verify_source_identity(symbol, year, manifest,
                               Path(args.data_dir) if args.data_dir else None)
    print(f"IDENTITY_VERIFIED {len(tasks)} symbol-year archives")

    # ---- 2. replay -------------------------------------------------------
    results = []
    payload = [(s, y, args.data_dir) for s, y in tasks]
    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for i, res in enumerate(pool.map(replay_one, payload), 1):
                results.append(res)
                print(f"[{i}/{len(payload)}] {res['symbol']} {res['year']} "
                      f"{res['state']} units={len(res['units'])}", flush=True)
    else:
        for i, task in enumerate(payload, 1):
            res = replay_one(task)
            results.append(res)
            print(f"[{i}/{len(payload)}] {res['symbol']} {res['year']} "
                  f"{res['state']} units={len(res['units'])}", flush=True)

    admitted = [r for r in results if r["state"] == "ADMITTED"]
    excluded = [{"symbol": r["symbol"], "year": r["year"],
                 "exclusion_reason": r["exclusion_reason"]}
                for r in results if r["state"] != "ADMITTED"]
    if any(r["double_pass"] != "BYTE_IDENTICAL" for r in admitted):
        raise SystemExit("DETERMINISM FAILURE: a symbol-year replay is not reproducible")

    units = [u for r in admitted for u in r["units"]]
    units.sort(key=lambda u: (u.symbol, u.day, u.session))
    rows = [unit_row(u) for u in units]

    dev_partition_hash = sha256_json(
        {f"{r['symbol']}_{r['year']}": r["frame_hashes"] for r in admitted})
    determinism = {
        "mode": "per-symbol-year double pass over the identical derived frames",
        "symbol_years_checked": len(admitted),
        "double_pass": "BYTE_IDENTICAL",
        "pooled_ledger_sha256": sha256_json(rows),
        "per_symbol_year": {f"{r['symbol']}_{r['year']}": r["pass1_sha256"] for r in admitted},
    }

    # ---- 3. evidence ledger (large -> external CAS pointer only) ---------
    CAS.mkdir(parents=True, exist_ok=True)
    ledger_path = CAS / "candidate_ledger.jsonl.gz"
    raw = ledger_path.with_suffix("")  # .jsonl
    with raw.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "record_type": "HEADER", "experiment_id": M.EXPERIMENT_ID,
            "strategy_id": STRATEGY_ID, "strategy_version": STRATEGY_VERSION,
            "strategy_hash": STRATEGY_HASH, "rules_changed": "NO",
            "preregistration_hash": prereg["preregistration_hash"],
            "dataset_authority": AUTHORITY_ID, "dataset_role": "DEVELOPMENT",
            "dev_partition_hash": dev_partition_hash, "implementation_sha": head,
        }, sort_keys=True, separators=(",", ":")) + "\n")
        for r in admitted:
            fh.write(json.dumps({
                "record_type": "DATASET_ACCESS", "symbol": r["symbol"], "year": r["year"],
                "dataset_role": "DEVELOPMENT", "authority_id": AUTHORITY_ID,
                "frame_sha256": r["frame_hashes"], "quality": r["quality"],
                "oos_requested": False, "holdout_requested": False,
            }, sort_keys=True, separators=(",", ":"), default=str) + "\n")
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    # gzip with mtime=0 so the artifact is byte-reproducible
    with raw.open("rb") as src, ledger_path.open("wb") as dst:
        with gzip.GzipFile(fileobj=dst, mode="wb", compresslevel=9, mtime=0) as gz:
            while chunk := src.read(1 << 20):
                gz.write(chunk)
    uncompressed_bytes = raw.stat().st_size
    uncompressed_sha = sha256_file(raw)
    raw.unlink()
    cas_pointer = {
        "artifact_id": "GEN2_ALD_V1_MULTIYEAR_CANDIDATE_LEDGER",
        "uncompressed_bytes": uncompressed_bytes,
        "uncompressed_sha256": uncompressed_sha,
        "sha256": sha256_file(ledger_path),
        "bytes": ledger_path.stat().st_size,
        "rows": len(rows) + len(admitted) + 1,
        "storage": "EXTERNAL — not committed to git",
        "path": str(ledger_path),
        "regeneration": ("python scripts/run_gen2_ald_v1_multiyear_dev.py after "
                         "python scripts/acquire_histdata_fx_multiyear.py; byte-identical by "
                         "construction (deterministic replay, gzip mtime=0)"),
    }

    # ---- 3b. gap inventory (data authority contract requirement) ---------
    quality_rows = {}
    for r in admitted:
        q = r["quality"]
        dev_days = (datetime.fromisoformat(q["partition_utc"][1])
                    - datetime.fromisoformat(q["partition_utc"][0])).days
        expected_m15 = dev_days * 96  # 24h x 4 buckets; weekends are genuine holes
        quality_rows[f"{r['symbol']}_{r['year']}"] = {
            "symbol": r["symbol"], "year": r["year"],
            "m1_rows_in_archive": q["m1_rows"],
            "m1_duplicate_timestamps": q["m1_duplicate_timestamps"],
            "m1_ohlc_violations": q["m1_ohlc_violations"],
            "bars": q["bars"],
            "first_m15": q["first_m15"], "last_m15": q["last_m15"],
            "m15_calendar_slots_in_window": expected_m15,
            "m15_fill_ratio_vs_calendar": round(q["bars"]["M15"] / expected_m15, 6),
        }
    fills = [v["m15_fill_ratio_vs_calendar"] for v in quality_rows.values()]
    write_json(OUT / "dataset_quality_report.json", {
        "contract": ("gap inventory required by config/governance/data_authority_gap.json "
                     "multi_year_data_authority_contract.gap_handling"),
        "rule": "a M15 bucket exists iff >= 13 of its 15 M1 minutes traded; never forward filled",
        "note": ("m15_fill_ratio_vs_calendar compares against ALL calendar slots including "
                 "weekends, so a complete FX year sits near 0.71, not 1.0. The ratio is "
                 "reported as a raw coverage fact; no threshold selects or drops a symbol-year."),
        "pooled": {"symbol_years": len(quality_rows),
                   "min_fill_ratio": min(fills), "max_fill_ratio": max(fills),
                   "duplicate_timestamps_total": sum(
                       v["m1_duplicate_timestamps"] for v in quality_rows.values()),
                   "ohlc_violations_total": sum(
                       v["m1_ohlc_violations"] for v in quality_rows.values())},
        "symbol_years": dict(sorted(quality_rows.items())),
        "excluded_symbol_years": excluded,
    })

    # ---- 4. analysis (frozen analyzers) ----------------------------------
    matrix = A.stage_matrix(units)
    trigger = A.trigger_analysis(units)
    confirmation = A.confirmation_analysis(units)
    capability = A.target_capability(units)
    survival = A.continuation_survival(units)
    temporal = A.temporal_diagnostics(units)
    analyzer = A.run_universal_funnel_analyzer(units, dev_partition_hash)
    attrition = MA.attrition_decomposition(units)
    years = MA.year_distribution(units)
    cells = MA.symbol_session_distribution(units)

    write_json(OUT / "target_capability.json", capability)
    write_json(OUT / "continuation_survival.json", survival)
    write_json(OUT / "temporal_diagnostics.json", temporal)
    write_json(OUT / "attrition_reasons.json", attrition)
    write_json(OUT / "funnel_report.json", {
        "analyzer": "ag_edgelab.analytics.diagnostic.analyze_three_funnel (accepted Universal Funnel Analyzer)",
        "experiment_id": M.EXPERIMENT_ID,
        "dataset_role": "DEVELOPMENT", "dataset_authority": AUTHORITY_ID,
        "dev_partition_hash": dev_partition_hash,
        "stage_matrix": matrix,
        "trigger_analysis": trigger,
        "confirmation_analysis": confirmation,
        "year_distribution": years,
        "symbol_session_distribution": cells,
        "universal_funnel_report": json.loads(analyzer.model_dump_json()),
        "determinism": determinism,
    })

    # ---- 5. matrices (csv) ----------------------------------------------
    yhead = ["YEAR", "SYMBOLS_COVERED", "OPPORTUNITY_N", "DIRECTION_DECIDABLE_N", "DIRECTIONAL_N",
             "TRIGGER_N", "CONFIRMATION_N", "GEOMETRY_VALID_N", "ENTRY_N",
             "entry_yield_per_1000", "1R", "2R", "3R", "4R", "5R", "natural_target_median_R"]
    ylines = [",".join(yhead)]
    for year, row in years["rows"].items():
        cap = row["fixed_r_capability"]
        ylines.append(",".join([
            year, str(len(row["symbols_covered"])), str(row["OPPORTUNITY_N"]),
            str(row["DIRECTION_DECIDABLE_N"]), str(row["DIRECTIONAL_N"]), str(row["TRIGGER_N"]),
            str(row["CONFIRMATION_N"]), str(row["GEOMETRY_VALID_N"]), str(row["ENTRY_N"]),
            str(row["entry_yield_per_1000_candidates"]),
            *[str(cap[f"{k}R"]) for k in (1, 2, 3, 4, 5)],
            str(row["natural_target_median_R"])]))
    (OUT / "year_matrix.csv").write_text("\n".join(ylines) + "\n", encoding="utf-8")

    shead = ["scope", "symbol", "session", "CANDIDATE_N", "TRIGGER_INPUT", "TRIGGER_PASS",
             "CONFIRMATION_INPUT", "CONFIRMATION_PASS", "GEOMETRY_VALID", "ENTRY_AVAILABLE",
             "1R", "2R", "3R", "4R", "5R", "natural_target_median_R", "management_expectancy_R",
             "STARVED_vs_cell_floor"]
    slines = [",".join(shead)]
    scopes = ([("CELL", s, t) for s in sorted({u.symbol for u in units})
               for t in sorted({u.session for u in units})]
              + [("SYMBOL", s, "ALL") for s in sorted({u.symbol for u in units})]
              + [("SESSION", "ALL", t) for t in sorted({u.session for u in units})]
              + [("POOLED", "ALL", "ALL")])
    for scope, sym, ses in scopes:
        sub = [u for u in units
               if (sym in ("ALL",) or u.symbol == sym) and (ses in ("ALL",) or u.session == ses)]
        c = A.stage_counts(sub)
        cap = A.target_capability(sub)
        slines.append(",".join([
            scope, sym, ses, str(c["CANDIDATE_N"]), str(c["TRIGGER_INPUT"]), str(c["TRIGGER_PASS"]),
            str(c["CONFIRMATION_INPUT"]), str(c["CONFIRMATION_PASS"]), str(c["GEOMETRY_VALID"]),
            str(c["ENTRY_AVAILABLE"]), *[str(c[f"{k}R"]) for k in (1, 2, 3, 4, 5)],
            str(cap["natural_target_R"]["median"]),
            str(cap["management_TP1_TP2_50_50"]["expectancy_r"]),
            "YES" if c["ENTRY_AVAILABLE"] < MA.STRATUM_MIN_N else "NO"]))
    (OUT / "symbol_session_matrix.csv").write_text("\n".join(slines) + "\n", encoding="utf-8")

    # ---- 6. robustness + gate -------------------------------------------
    entries_n = len(A.entries(units))
    neighborhood = None  # parameter neighborhood is gated behind eligibility; never a search
    robustness = MA.multiyear_robustness_report(units, neighborhood)
    robustness["preregistered_gate_contract"] = pre_oos_gate_contract()

    hashes = contract_hashes()
    identity_valid = (rule_identity["state"] == "PASS"
                      and hashes["strategy_contract_hash"] == STRATEGY_HASH == M.EXPECTED_RULE_HASH)
    friction_disclosed = friction_contract()["FRICTION_EDGE_VERIFICATION_READY"] == "NO"
    pre_oos = A.pre_oos_gate_result(units, robustness, capability,
                                    identity_valid=identity_valid,
                                    dataset_role_valid=True,
                                    friction_disclosed=friction_disclosed)
    write_json(OUT / "robustness_report.json", robustness)
    write_json(OUT / "pre_oos_gate_result.json", pre_oos)

    cause = A.root_cause(units, trigger, confirmation, capability, temporal,
                         A.analyzer_verdict(analyzer))

    # ---- 7. narrow vs multi-year + classification ------------------------
    pooled = matrix["POOLED"]
    pooled_counts = {
        "CANDIDATE_N": pooled["CANDIDATE_N"], "TRIGGER_PASS_N": pooled["TRIGGER_PASS"],
        "CONFIRMATION_PASS_N": pooled["CONFIRMATION_PASS"],
        "GEOMETRY_VALID_N": pooled["GEOMETRY_VALID"],
        "ENTRY_AVAILABLE_N": pooled["ENTRY_AVAILABLE"]}
    comparison = M.narrow_vs_multiyear(pooled_counts, len(admitted),
                                       MA.per_year_entry_yield(units))
    if NARROW.exists():
        narrow_report = json.loads(NARROW.read_text())
        comparison["narrow_campaign_evidence"] = {
            "final_report": str(NARROW),
            "sha256": sha256_file(NARROW),
            "PRIMARY_FUNNEL_WEAKNESS": narrow_report["PRIMARY_FUNNEL_WEAKNESS"],
            "PRE_OOS_RESULT": narrow_report["PRE_OOS_RESULT"],
            "STATUS": narrow_report["STATUS"],
        }
    classification = M.classify_sample(pooled_counts["ENTRY_AVAILABLE_N"],
                                       MA.cell_entry_counts(units),
                                       pre_oos["PRE_OOS_RESULT"])
    comparison["classification"] = classification

    # Secondary read on the BALANCED PANEL (years where all four symbols exist).
    # The panel was declared in the data authority BEFORE any result; it is a
    # coverage fact, not a selection, and it does not change the verdict.
    panel_years = {str(y) for y in BALANCED_PANEL}
    panel_units = [u for u in units if u.day[:4] in panel_years]
    panel_counts = A.stage_counts(panel_units)
    panel_symbol_years = len([r for r in admitted if r["year"] in BALANCED_PANEL])
    panel_cap = A.target_capability(panel_units)
    per_sy = (panel_counts["ENTRY_AVAILABLE"] / panel_symbol_years) if panel_symbol_years else 0.0
    comparison["balanced_panel"] = {
        "declared_in": "preregistration.data_authority.balanced_panel_years (pre-result)",
        "years": sorted(panel_years),
        "symbol_years": panel_symbol_years,
        "selection_authority": "NONE — reported alongside the pooled corpus, never instead of it",
        "counts": {"CANDIDATE_N": panel_counts["CANDIDATE_N"],
                   "DIRECTIONAL_N": panel_counts["T3_DIRECTION_NON_NEUTRAL"],
                   "TRIGGER_PASS_N": panel_counts["TRIGGER_PASS"],
                   "CONFIRMATION_PASS_N": panel_counts["CONFIRMATION_PASS"],
                   "ENTRY_AVAILABLE_N": panel_counts["ENTRY_AVAILABLE"]},
        "fixed_r_capability": panel_cap["fixed_r_capability"],
        "entries_per_symbol_year": round(per_sy, 6),
        "classification_on_panel_only": M.classify_sample(
            panel_counts["ENTRY_AVAILABLE"], MA.cell_entry_counts(panel_units),
            pre_oos["PRE_OOS_RESULT"])["SAMPLE_CLASSIFICATION"],
    }
    import math as _math
    comparison["sufficiency_projection"] = {
        "method": ("pure arithmetic on the observed entry yield; no extrapolation of "
                   "performance, only of SAMPLE SIZE"),
        "observed_entries_per_symbol_year_balanced_panel": round(per_sy, 6),
        "symbol_years_needed_for_pooled_eligibility": (
            None if per_sy <= 0 else int(_math.ceil(POOLED_ENTRY_ELIGIBILITY_N / per_sy))),
        "calendar_years_needed_at_4_symbols": (
            None if per_sy <= 0 else round(POOLED_ENTRY_ELIGIBILITY_N / per_sy / 4, 2)),
        "symbol_years_needed_for_every_cell_to_reach_the_30_entry_floor": (
            None if per_sy <= 0 else int(_math.ceil(8 * MA.STRATUM_MIN_N / per_sy))),
        "calendar_years_needed_for_full_cell_coverage_at_4_symbols": (
            None if per_sy <= 0 else round(8 * MA.STRATUM_MIN_N / per_sy / 4, 2)),
        "available_history": ("HistData FX M1 begins in 2000 and gold in 2009; the DEV half of "
                              "every year is already consumed by this experiment, so no further "
                              "DEVELOPMENT evidence of this kind exists to collect"),
    }
    write_json(OUT / "v1_narrow_vs_multiyear.json", comparison)

    # ---- 8. decision -----------------------------------------------------
    label = classification["SAMPLE_CLASSIFICATION"]
    if label == "SUFFICIENT_SAMPLE_NOW":
        status, nxt = "FROZEN_PRE_OOS_CANDIDATE", "WAIT_FOR_FRICTION_AUTHORITY"
        decision_case = "CASE_D"
    elif label == "NARROW_DATA_STARVATION":
        status = "PRE_OOS_FAILED" if pre_oos["PRE_OOS_RESULT"] == "FAIL" else "MULTIYEAR_DEV_INSUFFICIENT_SAMPLE"
        nxt, decision_case = "CONTINUE_V1", "CASE_A"
    elif label == "MIXED":
        status, nxt, decision_case = "MULTIYEAR_DEV_INSUFFICIENT_SAMPLE", "CONTINUE_V1", "CASE_C"
    else:
        status = "MULTIYEAR_DEV_INSUFFICIENT_SAMPLE"
        nxt, decision_case = "NEW_V2_HYPOTHESIS_DESIGN", "CASE_B"

    instance = json.loads((OUT / "candidate_instance_identity.json").read_text())
    instance["experiment_identity_realised"] = M.experiment_identity(
        dev_partition_hash=dev_partition_hash, dataset_manifest_sha256=manifest_sha)
    instance["dataset_manifest_sha256_matches_preregistration"] = (
        instance["experiment_identity_preregistered"]["dataset_manifest_sha256"] == manifest_sha)
    write_json(OUT / "candidate_instance_identity.json", instance)

    final = {
        "mission": "GEN2 ASIAN LIQUIDITY DISPLACEMENT V1 — MULTI-YEAR DEV REPLAY",
        "generated_at_utc": started,
        "IMPLEMENTATION_SHA": head, "TREE_SHA": tree,
        "EXPERIMENT_ID": M.EXPERIMENT_ID,
        "STRATEGY_ID": STRATEGY_ID, "STRATEGY_VERSION": STRATEGY_VERSION,
        "STRATEGY_HASH": STRATEGY_HASH,
        "EXPECTED_RULE_HASH": M.EXPECTED_RULE_HASH,
        "rule_identity_check": rule_identity,
        "RULES_CHANGED": "NO", "DATASET_BINDING_CHANGED": "YES",
        "PREREGISTRATION_HASH": prereg["preregistration_hash"],
        "contract_hashes": hashes,
        "authority_gate": gate,
        "contamination_check": contamination,
        "DATASET_AUTHORITY": AUTHORITY_ID,
        "dataset_authority_contract": authority_contract(),
        "DATASET_ROLE": "DEVELOPMENT",
        "DATASET_MANIFEST_SHA256": manifest_sha,
        "DEV_PARTITION_HASH": dev_partition_hash,
        "DEV_WINDOWS": [list(w) for w in windows],
        "DEV_YEARS_N": len({y for _, y in tasks}),
        "DEV_SYMBOL_YEARS_N": len(admitted),
        "EXCLUDED_SYMBOL_YEARS": excluded,
        "SYMBOLS": list(SYMBOL_UNIVERSE), "TIMEFRAMES": list(TIMEFRAMES),
        "SESSIONS": sorted({u.session for u in units}) + ["POOLED"],
        "OPPORTUNITY_N": pooled["CANDIDATE_N"],
        "DIRECTION_DECIDABLE_N": pooled["T2_DIRECTION_DECIDED"],
        "DIRECTIONAL_N": pooled["T3_DIRECTION_NON_NEUTRAL"],
        "TRIGGER_PASS_N": pooled["TRIGGER_PASS"],
        "CONFIRMATION_PASS_N": pooled["CONFIRMATION_PASS"],
        "GEOMETRY_VALID_N": pooled["GEOMETRY_VALID"],
        "ENTRY_AVAILABLE_N": pooled["ENTRY_AVAILABLE"],
        "CAPABILITY": {f"{k}R": capability["fixed_r_capability"][f"{k}R"] for k in (1, 2, 3, 4, 5)},
        "MFE_R": capability["MFE_R"], "MAE_R": capability["MAE_R"],
        "NATURAL_TARGET_MEDIAN_R": capability["natural_target_R"]["median"],
        "CONTINUATION": survival["conditional_continuation"],
        "ATTRITION": {"stages": attrition["stages"],
                      "trigger_failures": {k: v["n"] for k, v in attrition["trigger_failures"].items()},
                      "confirmation_failures": {k: v["n"] for k, v in attrition["confirmation_failures"].items()}},
        "YEAR_DISTRIBUTION": {y: {k: r[k] for k in
                                  ("OPPORTUNITY_N", "DIRECTIONAL_N", "TRIGGER_N",
                                   "CONFIRMATION_N", "ENTRY_N", "entry_yield_per_1000_candidates")}
                              for y, r in years["rows"].items()},
        "SYMBOL_STARVATION": cells["SYMBOL_STARVATION"],
        "SESSION_STARVATION": cells["SESSION_STARVATION"],
        "V1_NARROW_VS_MULTIYEAR": comparison,
        "SAMPLE_CLASSIFICATION": label,
        "DECISION_CASE": decision_case,
        "BALANCED_PANEL": comparison["balanced_panel"],
        "SUFFICIENCY_PROJECTION": comparison["sufficiency_projection"],
        "DATASET_QUALITY": json.loads((OUT / "dataset_quality_report.json").read_text())["pooled"],
        "PRIMARY_FUNNEL_WEAKNESS": cause["PRIMARY_FUNNEL_WEAKNESS"],
        "SECONDARY_DIAGNOSES": cause["SECONDARY_DIAGNOSES"],
        "root_cause": cause,
        "ROBUSTNESS_RUN": "YES" if entries_n >= POOLED_ENTRY_ELIGIBILITY_N else "NO",
        "ROBUSTNESS": {k: v.get("state") for k, v in robustness["axes"].items()},
        "PRE_OOS_RESULT": pre_oos["PRE_OOS_RESULT"],
        "FROZEN_CANDIDATE": "YES" if pre_oos["PRE_OOS_RESULT"] == "PASS" else "NO",
        "ECONOMIC_EDGE": "NOT_ESTIMABLE",
        "FRICTION_EDGE_VERIFICATION_READY": "NO",
        "OOS_OPENED": "NO", "HOLDOUT_TOUCHED": "NO",
        "PARAMETER_OPTIMIZATION": "NO", "STRATEGY_RULES_CHANGED": "NO",
        "STRATEGY_EXECUTION_ADDED": "NO", "BROKER_MUTATION": "NO",
        "SEARCH_LEDGER": {"optimizer_runs": 0, "trial_count": 0, "hypotheses_evaluated": 1,
                          "threshold_mutations": 0, "post_hoc_selection": "NONE",
                          "years_ranked_or_selected": "NONE",
                          "cells_removed": "NONE"},
        "evidence_ledger_cas_pointer": cas_pointer,
        "determinism": determinism,
        "STATUS": status, "NEXT": nxt,
    }
    write_json(OUT / "final_report.json", final)
    (OUT / "final_report.md").write_text(
        render_markdown(final, attrition, years, cells, capability, survival, temporal,
                        robustness, pre_oos, comparison, classification), encoding="utf-8")

    manifest_out = {
        "artifact_set": "GEN2_ASIAN_LIQUIDITY_DISPLACEMENT_V1_MULTIYEAR",
        "experiment_id": M.EXPERIMENT_ID,
        "generated_at_utc": started, "implementation_sha": head, "tree_sha": tree,
        "dataset_role": "DEVELOPMENT", "dataset_authority": AUTHORITY_ID,
        "external_evidence_pointer": {
            "raw_dataset": "NOT COMMITTED — 63 hash-pinned HistData zips fetched by "
                           "scripts/acquire_histdata_fx_multiyear.py",
            "dataset_manifest_sha256": manifest_sha,
            "candidate_ledger": cas_pointer,
        },
        "files": {p.name: {"sha256": sha256_file(p), "bytes": p.stat().st_size}
                  for p in sorted(OUT.iterdir())
                  if p.is_file() and p.name != "artifact_manifest.json"},
    }
    write_json(OUT / "artifact_manifest.json", manifest_out)

    print(json.dumps({k: final[k] for k in (
        "OPPORTUNITY_N", "DIRECTIONAL_N", "TRIGGER_PASS_N", "CONFIRMATION_PASS_N",
        "GEOMETRY_VALID_N", "ENTRY_AVAILABLE_N", "SAMPLE_CLASSIFICATION", "DECISION_CASE",
        "PRIMARY_FUNNEL_WEAKNESS", "SECONDARY_DIAGNOSES", "ROBUSTNESS_RUN",
        "PRE_OOS_RESULT", "FROZEN_CANDIDATE", "STATUS", "NEXT")}, indent=2))


# ---------------------------------------------------------------------------
# markdown
# ---------------------------------------------------------------------------

def render_markdown(final, attrition, years, cells, capability, survival, temporal,
                    robustness, pre_oos, comparison, classification) -> str:
    L: list[str] = []
    a = L.append
    a(f"# {final['mission']}")
    a("")
    a(f"**EXPERIMENT_ID** `{final['EXPERIMENT_ID']}` · **STATUS** `{final['STATUS']}` · "
      f"**NEXT** `{final['NEXT']}`")
    a("")
    a(f"- STRATEGY_ID `{final['STRATEGY_ID']}` @ `{final['STRATEGY_VERSION']}`")
    a(f"- STRATEGY_HASH `{final['STRATEGY_HASH']}` — reproduces EXPECTED_RULE_HASH "
      f"(**RULES_CHANGED = {final['RULES_CHANGED']}**, DATASET_BINDING_CHANGED = "
      f"{final['DATASET_BINDING_CHANGED']})")
    a(f"- DATASET_AUTHORITY `{final['DATASET_AUTHORITY']}`, role DEVELOPMENT, "
      f"{final['DEV_SYMBOL_YEARS_N']} symbol-years across {final['DEV_YEARS_N']} calendar years")
    a(f"- DEV_PARTITION_HASH `{final['DEV_PARTITION_HASH']}`")
    a(f"- OOS_OPENED **{final['OOS_OPENED']}** · HOLDOUT_TOUCHED **{final['HOLDOUT_TOUCHED']}** · "
      f"PARAMETER_OPTIMIZATION **{final['PARAMETER_OPTIMIZATION']}** · "
      f"BROKER_MUTATION **{final['BROKER_MUTATION']}**")
    a("")

    a("## 1. Verdict")
    a("")
    a(f"**SAMPLE_CLASSIFICATION = `{final['SAMPLE_CLASSIFICATION']}`** "
      f"({final['DECISION_CASE']}, rule `{classification['applied_rule']}` of "
      f"`{classification['contract_id']}`)")
    a("")
    a(f"Pooled ENTRY_AVAILABLE_N = **{classification['pooled_entry_n']}** against the "
      f"preregistered eligibility floor of {classification['pooled_eligibility_required']}; "
      f"no symbol x session cell reaches the {classification['cell_floor']}-entry floor "
      f"(viable cells: {classification['viable_cells'] or 'none'})." if not classification["viable_cells"]
      else f"Pooled ENTRY_AVAILABLE_N = **{classification['pooled_entry_n']}**; viable cells: "
           f"{classification['viable_cells']}; starved cells: {classification['starved_cells']}.")
    a("")

    a("## 2. Pooled funnel")
    a("")
    a("| stage | INPUT_N | PASS_N | FAIL_N | PASS_% | % of opportunity |")
    a("|---|---:|---:|---:|---:|---:|")
    for s in attrition["stages"]:
        a(f"| {s['stage']} | {s['INPUT_N']} | {s['PASS_N']} | {s['FAIL_N']} | "
          f"{s['PASS_PCT']} | {s['NEXT_STAGE_PCT']} |")
    a("")
    cap = final["CAPABILITY"]
    a(f"1R-5R capability: " + " · ".join(f"**{k}** {v}" for k, v in cap.items()))
    a("")
    a(f"natural_target_median_R = {final['NATURAL_TARGET_MEDIAN_R']}; "
      f"conditional continuation {survival['conditional_continuation']}")
    a("")

    a("## 3. Attrition decomposition")
    a("")
    a("Trigger failures (never collapsed into one bucket):")
    a("")
    a("| mission reason | n | frozen vocabulary |")
    a("|---|---:|---|")
    for label, payload in attrition["trigger_failures"].items():
        a(f"| {label} | {payload['n']} | "
          f"{', '.join(f'{k}={v}' for k, v in payload['frozen_reasons'].items()) or '—'} |")
    a("")
    a("Confirmation failures:")
    a("")
    a("| mission reason | n | frozen vocabulary |")
    a("|---|---:|---|")
    for label, payload in attrition["confirmation_failures"].items():
        a(f"| {label} | {payload['n']} | "
          f"{', '.join(f'{k}={v}' for k, v in payload['frozen_reasons'].items()) or '—'} |")
    a("")
    a(f"Reconciliation of mapped vs raw rejection counts: "
      f"`{attrition['reconciliation_ok']}`")
    a("")

    a("## 4. Year distribution (reported, never ranked)")
    a("")
    a("| year | symbols | OPPORTUNITY_N | DIRECTIONAL_N | TRIGGER_N | CONFIRMATION_N | ENTRY_N | entries / 1000 candidates |")
    a("|---|---:|---:|---:|---:|---:|---:|---:|")
    for year, r in years["rows"].items():
        a(f"| {year} | {len(r['symbols_covered'])} | {r['OPPORTUNITY_N']} | {r['DIRECTIONAL_N']} | "
          f"{r['TRIGGER_N']} | {r['CONFIRMATION_N']} | {r['ENTRY_N']} | "
          f"{r['entry_yield_per_1000_candidates']} |")
    a("")

    a("## 5. Symbol x session cells (independent, nothing removed)")
    a("")
    a("| cell | OPPORTUNITY_N | DIRECTIONAL_N | TRIGGER_N | CONFIRMATION_N | ENTRY_N | starved |")
    a("|---|---:|---:|---:|---:|---:|---|")
    for name, c in cells["cells"].items():
        a(f"| {name} | {c['OPPORTUNITY_N']} | {c['DIRECTIONAL_N']} | {c['TRIGGER_N']} | "
          f"{c['CONFIRMATION_N']} | {c['ENTRY_N']} | "
          f"{'YES' if c['SYMBOL_STARVATION'] else 'no'} |")
    a("")
    a(f"SYMBOL_STARVATION = {cells['SYMBOL_STARVATION']} · "
      f"SESSION_STARVATION = {cells['SESSION_STARVATION']}")
    a("")

    a("## 6. Narrow 2017 vs multi-year")
    a("")
    a("| metric | 2017 DEV | multi-year | growth x |")
    a("|---|---:|---:|---:|")
    for key in ("CANDIDATE_N", "TRIGGER_PASS_N", "CONFIRMATION_PASS_N", "GEOMETRY_VALID_N",
                "ENTRY_AVAILABLE_N"):
        a(f"| {key} | {comparison['narrow_2017_dev'][key]} | {comparison['multiyear'][key]} | "
          f"{comparison['growth_x'][key]} |")
    a(f"| symbol-years | {comparison['narrow_symbol_years']} | "
      f"{comparison['multiyear_symbol_years']} | {comparison['corpus_growth_x']} |")
    a("")
    a(f"2017 entry yield {comparison['yield_2017']} per 1000 candidates; other years span "
      f"{comparison['yield_other_years_range']}. **2017 representative: "
      f"{comparison['2017_representative']}**.")
    a("")

    a("## 6b. Data coverage and the balanced panel")
    a("")
    bp = final["BALANCED_PANEL"]
    a(f"HistData coverage is not uniform: gold starts in 2009 and the 2000 archives start in "
      f"May, so the four-symbol **balanced panel is {bp['years'][0]}-{bp['years'][-1]}** "
      f"({bp['symbol_years']} symbol-years), declared in the data authority before any result.")
    a("")
    a(f"- balanced-panel counts: {bp['counts']}")
    a(f"- balanced-panel capability: {bp['fixed_r_capability']}")
    a(f"- entries per symbol-year: **{bp['entries_per_symbol_year']}**")
    a(f"- classification computed on the panel alone: "
      f"`{bp['classification_on_panel_only']}` (same verdict as pooled)")
    a("")
    sp = final["SUFFICIENCY_PROJECTION"]
    a(f"At that yield the corpus would need **{sp['symbol_years_needed_for_pooled_eligibility']} "
      f"symbol-years** (~{sp['calendar_years_needed_at_4_symbols']} calendar years of four "
      f"symbols) merely to reach the pooled eligibility floor, and "
      f"{sp['symbol_years_needed_for_every_cell_to_reach_the_30_entry_floor']} symbol-years "
      f"(~{sp['calendar_years_needed_for_full_cell_coverage_at_4_symbols']} calendar years) for "
      f"every symbol x session cell to clear the 30-entry floor. {sp['available_history']}.")
    a("")
    a("## 7. Temporal diagnostics")
    a("")
    a(f"- entry window = {temporal['entry_window_m15_bars']['median']} M15 bars; median bars "
      f"remaining after reclaim = {temporal['m15_bars_remaining_after_reclaim']}")
    a(f"- sequential events still required after reclaim = "
      f"{temporal['sequential_events_still_required_after_reclaim']}")
    a(f"- window-bounded share of post-trigger attrition = "
      f"{temporal['window_bounded_rejection_share_of_post_trigger']}%; right-censored "
      f"{temporal['right_censored_n']}")
    a("")

    a("## 8. Robustness and the Pre-OOS gate")
    a("")
    a(f"ROBUSTNESS_RUN = **{final['ROBUSTNESS_RUN']}** "
      f"(pooled entries {robustness['eligibility']['pooled_entry_available_n']} vs required "
      f"{robustness['eligibility']['required']})")
    a("")
    a("| axis | state | provisional state if eligible |")
    a("|---|---|---|")
    for name, payload in robustness["axes"].items():
        a(f"| {name} | `{payload.get('state')}` | "
          f"`{payload.get('provisional_state_if_eligible', '—')}` |")
    a("")
    a(f"**PRE_OOS_RESULT = `{pre_oos['PRE_OOS_RESULT']}`** — failing axes "
      f"{pre_oos['failing_axes']}, unevaluable axes {len(pre_oos['unevaluable_axes'])}. "
      f"FROZEN_CANDIDATE = {final['FROZEN_CANDIDATE']}.")
    a("")

    a("## 9. Economics")
    a("")
    a(f"ECONOMIC_EDGE = **{final['ECONOMIC_EDGE']}**. Measured friction authority is still "
      "missing, so no spread, commission or slippage value exists anywhere in this bundle. "
      "Only structural R is reported.")
    a("")

    a("## 10. Research integrity")
    a("")
    for k, v in final["SEARCH_LEDGER"].items():
        a(f"- {k} = `{v}`")
    a(f"- EXCLUDED_SYMBOL_YEARS = `{final['EXCLUDED_SYMBOL_YEARS'] or 'none'}`")
    a(f"- determinism: per-symbol-year double pass `{final['determinism']['double_pass']}` "
      f"over {final['determinism']['symbol_years_checked']} symbol-years; pooled ledger sha256 "
      f"`{final['determinism']['pooled_ledger_sha256']}`")
    a("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
