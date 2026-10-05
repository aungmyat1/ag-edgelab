#!/usr/bin/env python
"""MISSION 3 PHASE 4-6 — V2 DEVELOPMENT replay over the R2 multi-year corpus.

Runs only after the preregistration commit. DEVELOPMENT partitions only; the
loader fails closed on any other role.

Usage: scripts/run_gen2_ald_v2_dev.py [data_dir] [--workers N] [--subset SYM:YYYY,...]
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from ag_edgelab.data.fingerprint import sha256_file, sha256_json
from ag_edgelab.data.fx_histdata_multiyear import (
    AUTHORITY_ID,
    admitted_symbol_years,
    build_dev_frames,
    load_manifest,
    manifest_path,
    partition_bounds,
    verify_source_identity,
)
from ag_edgelab.strategies import asian_liquidity_displacement_v2 as V2
from ag_edgelab.strategies import asian_liquidity_displacement_v2_analysis as A
from ag_edgelab.strategies import asian_liquidity_displacement_v2_prereg as P

# M1->M5 bucketing is a DATA AGGREGATION primitive, not a rule. Reusing the
# frozen implementation guarantees V1 and V2 see byte-identical M5 frames,
# which is what makes the phase-5 comparison a comparison of architecture.
from ag_edgelab.strategies.asian_liquidity_displacement_v1 import aggregate_m5

OUT = Path("data/artifacts/gen2_asian_liquidity_displacement_v2")
CAS = Path("data/external/gen2_ald_v2")
GOV = Path("config/governance")
V1_FINAL = Path("data/artifacts/gen2_asian_liquidity_displacement_v1_multiyear/"
                "final_report.json")


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def unit_row(u: V2.V2Unit) -> dict:
    return {
        "record_type": "CANDIDATE", "strategy_id": V2.STRATEGY_ID,
        "strategy_version": V2.STRATEGY_VERSION, "experiment_id": P.EXPERIMENT_ID,
        "symbol": u.symbol, "day": u.day, "session": u.session, "branch": u.branch,
        "candidate_id": u.candidate_id, "direction": u.direction,
        "boundary_side": u.boundary_side,
        "reference_high": u.reference_high, "reference_low": u.reference_low,
        "reference_bars": u.reference_bars, "entry_window_m5_bars": u.entry_window_m5_bars,
        "d1_structure": u.d1_structure, "h4_structure": u.h4_structure,
        "h1_structure": u.h1_structure, "mtf_agreement": u.mtf_agreement,
        "premium_discount_state": u.premium_discount_state, "regime": u.regime,
        "quarter": u.quarter,
        "event_time": u.event_time, "reclaim_or_retest_time": u.reclaim_or_retest_time,
        "confirm_time": u.confirm_time, "confirm_primitive": u.confirm_primitive,
        "displacement_body_ratio_diagnostic": u.displacement_body_ratio,
        "stages": {k: bool(v) for k, v in sorted(u.stages.items())},
        "reject_node": u.reject_node, "reject_reason": u.reject_reason,
        "entry": u.entry, "stop": u.stop, "risk": u.risk,
        "target": u.target, "target_authority": u.target_authority,
        "natural_target_r": u.natural_target_r,
        "mfe_r": u.mfe_r, "mae_r": u.mae_r,
        "reached": {k: bool(v) for k, v in sorted(u.reached.items())},
        "stopped_out": u.stopped_out, "stopped_same_bar": u.stopped_same_bar,
        "target_reached": u.target_reached, "resolution": u.resolution,
        "realised_r": u.realised_r, "forward_bars": u.forward_bars,
    }


def _one(args) -> dict:
    symbol, year, data_dir = args
    try:
        frames, quality = build_dev_frames(symbol, year, aggregate_m5, data_dir)
        start, end = partition_bounds("DEVELOPMENT", year)
        units = V2.replay_symbol(frames, symbol, start, end)
        return {"symbol": symbol, "year": year, "state": "ADMITTED",
                "quality": quality, "rows": [unit_row(u) for u in units],
                "units": units}
    except Exception as exc:                                   # pragma: no cover
        return {"symbol": symbol, "year": year, "state": "EXCLUDED",
                "reason": f"{type(exc).__name__}: {exc}"}


def _prereg_commit() -> str:
    """The commit that FROZE the preregistration (committed before any V2 replay)."""
    import subprocess
    out = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--",
         "data/artifacts/gen2_asian_liquidity_displacement_v2/preregistration.json"],
        capture_output=True, text=True, check=False)
    return out.stdout.strip() or "UNRESOLVED"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir", nargs="?", default=None)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--subset", default=None)
    args = ap.parse_args()
    data_dir = Path(args.data_dir) if args.data_dir else None

    global OUT, CAS
    pairs = list(admitted_symbol_years())
    if args.subset:
        want = {(s.split(":")[0], int(s.split(":")[1])) for s in args.subset.split(",")}
        pairs = [p for p in pairs if p in want]
        OUT = Path("data/external/gen2_ald_v2_smoke")      # never the mission artifacts
        CAS = OUT
        OUT.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc).isoformat()
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()

    # ---- identity gate ---------------------------------------------------
    prereg = json.loads((OUT / "preregistration.json").read_text()) \
        if (OUT / "preregistration.json").exists() else json.loads(
            (Path("data/artifacts/gen2_asian_liquidity_displacement_v2")
             / "preregistration.json").read_text())
    if prereg["strategy"]["strategy_hash"] != V2.STRATEGY_HASH:
        print("STOP = STRATEGY_IDENTITY_MISMATCH (rules changed after preregistration)")
        return 2
    manifest = load_manifest(data_dir)
    for symbol, year in pairs:
        verify_source_identity(symbol, year, manifest, data_dir)
    manifest_sha = sha256_file(manifest_path(data_dir))
    if manifest_sha != prereg["dataset_authority"]["dataset_manifest_sha256"]:
        print("STOP = DATASET_IDENTITY_MISMATCH")
        return 2
    print(f"IDENTITY_VERIFIED {len(pairs)} symbol-year archives")

    # ---- replay ----------------------------------------------------------
    units: list[V2.V2Unit] = []
    rows: list[dict] = []
    admitted: list[dict] = []
    excluded: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, res in enumerate(pool.map(_one, [(s, y, data_dir) for s, y in pairs]), 1):
            if res["state"] != "ADMITTED":
                excluded.append({k: res[k] for k in ("symbol", "year", "reason")})
                print(f"[{i}/{len(pairs)}] {res['symbol']} {res['year']} EXCLUDED")
                continue
            units.extend(res["units"])
            rows.extend(res["rows"])
            admitted.append({"symbol": res["symbol"], "year": res["year"],
                             "quality": res["quality"]})
            print(f"[{i}/{len(pairs)}] {res['symbol']} {res['year']} "
                  f"ADMITTED units={len(res['units'])}")

    units.sort(key=lambda u: (u.symbol, u.day, u.session))
    rows.sort(key=lambda r: (r["symbol"], r["day"], r["session"]))

    # ---- external CAS ledger --------------------------------------------
    CAS.mkdir(parents=True, exist_ok=True)
    raw = CAS / "candidate_ledger.jsonl"
    with raw.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    gz = CAS / "candidate_ledger.jsonl.gz"
    with raw.open("rb") as src, gz.open("wb") as dst:
        with gzip.GzipFile(fileobj=dst, mode="wb", compresslevel=9, mtime=0) as z:
            z.write(src.read())
    cas_pointer = {
        "artifact_id": "GEN2_ALD_V2_CANDIDATE_LEDGER",
        "path": str(gz), "storage": "EXTERNAL — not committed to git",
        "rows": len(rows), "bytes": gz.stat().st_size,
        "sha256": sha256_file(gz),
        "uncompressed_bytes": raw.stat().st_size,
        "uncompressed_sha256": sha256_file(raw),
        "regeneration": "scripts/run_gen2_ald_v2_dev.py (deterministic, gzip mtime=0)",
    }
    raw.unlink()

    # ---- phase 4: funnel + strata ---------------------------------------
    pooled = A.stage_counts(units)
    funnel = A.funnel_table(units)
    reasons = A.rejection_breakdown(units)
    cap = A.capability(units)
    branches = A.branch_report(units)
    axes = {axis: A.by_axis(units, axis) for axis in
            ("branch", "symbol", "year", "session", "symbol_session",
             "branch_session", "regime")}

    write_json(OUT / "funnel_report.json", {
        "pooled_counts": pooled, "funnel": funnel,
        "taxonomy": P.funnel_taxonomy(),
    })
    write_json(OUT / "attrition_reasons.json", reasons)
    write_json(OUT / "target_capability.json", cap)
    write_json(OUT / "branch_report.json", branches)
    write_json(OUT / "strata_report.json", axes)

    for name, axis in (("year_matrix.csv", "year"),
                       ("symbol_session_matrix.csv", "symbol_session"),
                       ("branch_matrix.csv", "branch")):
        table = axes[axis]
        fields = ["key"] + list(next(iter(table.values())).keys()) if table else ["key"]
        with (OUT / name).open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow([f for f in fields if f != "fixed_r_capability"]
                       + [f"{k}R" for k in V2.FIXED_R_TARGETS])
            for key, row in table.items():
                base = [key] + [row[f] for f in fields[1:] if f != "fixed_r_capability"]
                w.writerow(base + [(row["fixed_r_capability"] or {}).get(f"{k}R")
                                   for k in V2.FIXED_R_TARGETS])

    # ---- phase 5: V1 comparison + sample gate ---------------------------
    comparison = A.v1_v2_comparison(units, P.V1_CLOSED_EVIDENCE)
    comparison["v1_evidence_sha256"] = sha256_file(V1_FINAL) if V1_FINAL.exists() else None
    gate = A.sample_gate(units)
    weakness = A.primary_funnel_weakness(units)
    write_json(OUT / "v1_vs_v2.json", comparison)
    write_json(OUT / "sample_gate.json", gate)

    # ---- phase 6: pre-OOS gate ------------------------------------------
    identity_valid = (V2.STRATEGY_HASH
                      == V2.contract_hashes()["strategy_contract_hash"]
                      == prereg["strategy"]["strategy_hash"]
                      and V2.STRATEGY_ID not in V2.FORBIDDEN_IDENTITY_REUSE)
    friction_disclosed = V2.friction_contract()["ECONOMIC_EDGE"] == "NOT_ESTIMABLE"
    if gate["SAMPLE_GATE"] == "PASS":
        pre_oos = A.pre_oos_gate(units, identity_valid=identity_valid,
                                 dataset_role_valid=True,
                                 friction_disclosed=friction_disclosed)
        pre_oos["contract"] = P.robustness_contract()
    else:
        pre_oos = {
            "PRE_OOS_RESULT": "NOT_REACHED",
            "reason": f"pooled ENTRY_AVAILABLE_N={gate['ENTRY_AVAILABLE_N']} is below the "
                      f"preregistered SAMPLE_FLOOR={gate['SAMPLE_FLOOR']}",
            "axes": {axis: "NOT_RUN_INSUFFICIENT_SAMPLE"
                     for axis in P.robustness_contract()["required_axes"]},
            "thresholds_unchanged": True,
            "contract": P.robustness_contract(),
        }
    write_json(OUT / "pre_oos_gate_result.json", pre_oos)

    sample_pass = gate["SAMPLE_GATE"] == "PASS"
    final = {
        "experiment_id": P.EXPERIMENT_ID,
        "generated_at_utc": started,
        "implementation_sha": head,
        "STRATEGY_ID": V2.STRATEGY_ID,
        "STRATEGY_VERSION": V2.STRATEGY_VERSION,
        "STRATEGY_CONTRACT_SHA256": V2.STRATEGY_HASH,
        "PREREGISTRATION_SHA256": prereg["PREREGISTRATION_SHA256"],
        "PREREGISTRATION_COMMIT": _prereg_commit(),
        "PREREGISTRATION_BASE_COMMIT": prereg["base_commit"],
        "V2_ARCHITECTURE": "A/B_BRANCH_MODEL("
                           "A_SWEEP_RECLAIM_REVERSAL|B_BREAKOUT_RETEST_CONTINUATION)",
        "DATASET_AUTHORITY": AUTHORITY_ID,
        "DEV_SYMBOL_YEARS_N": len(admitted),
        "DEV_YEARS_N": len({a["year"] for a in admitted}),
        "EXCLUDED_SYMBOL_YEARS": excluded,
        "OPPORTUNITY_N": pooled["OPPORTUNITY"],
        "CONTEXT_ELIGIBLE_N": pooled["S1_CONTEXT_ELIGIBLE"],
        "LOCATION_ELIGIBLE_N": pooled["S2_LOCATION_ELIGIBLE"],
        "SESSION_EVENT_N": pooled["S3_SESSION_EVENT"],
        "SWEEP_OR_BREAKOUT_N": pooled["S4_SWEEP_OR_BREAKOUT"],
        "RECLAIM_OR_RETEST_N": pooled["S5_RECLAIM_OR_RETEST"],
        "STRUCTURE_CONFIRM_N": pooled["S6_STRUCTURE_CONFIRM"],
        "ENTRY_AVAILABLE_N": pooled["S7_ENTRY_AVAILABLE"],
        "GEOMETRY_VALID_N": pooled["S8_GEOMETRY_VALID"],
        "TRADE_COMPLETED_N": pooled["S9_TRADE_COMPLETED"],
        "ENTRY_YIELD_PER_1000_OPPORTUNITIES": round(
            1000.0 * pooled["S7_ENTRY_AVAILABLE"] / pooled["OPPORTUNITY"], 6)
        if pooled["OPPORTUNITY"] else 0.0,
        "CAPABILITY": cap["fixed_r_capability"],
        "MEDIAN_NATURAL_TARGET_R": (cap["natural_target_R"] or {}).get("median")
        if cap["natural_target_R"] else None,
        "TARGET_REACHED_RATE": cap["target_reached_rate"],
        "SAMPLE_FLOOR": gate["SAMPLE_FLOOR"],
        "SAMPLE_GATE": gate["SAMPLE_GATE"],
        "BRANCHES": {b: {k: branches[b][k] for k in
                         ("OPPORTUNITY_N", "ENTRY_AVAILABLE_N", "TRADE_COMPLETED_N", "state")}
                     for b in V2.BRANCHES},
        "PRIMARY_FUNNEL_WEAKNESS": weakness["PRIMARY_FUNNEL_WEAKNESS"],
        "FUNNEL_WEAKNESS_DETAIL": weakness,
        "V1_VS_V2": comparison,
        "PRE_OOS_RESULT": pre_oos.get("PRE_OOS_RESULT", "NOT_REACHED"),
        "ROBUSTNESS_RUN": "YES" if gate["SAMPLE_GATE"] == "PASS" else "NO",
        "FAILED_ROBUSTNESS_AXES": pre_oos.get("failed_axes", []),
        "FROZEN_CANDIDATE": ("YES" if pre_oos.get("PRE_OOS_RESULT") == "PASS" else "NO"),
        "OOS_OPENED": "NO",
        "HOLDOUT_TOUCHED": "NO",
        "PARAMETER_OPTIMIZATION": "NO",
        "BROKER_MUTATION": "NO",
        "LIVE_EXECUTION": "NO",
        "EDGE_VERIFIED": "NO",
        "ECONOMIC_EDGE": "NOT_ESTIMABLE",
        "STATUS": (("V2_PRE_OOS_PASS_FROZEN_CANDIDATE"
                    if pre_oos.get("PRE_OOS_RESULT") == "PASS"
                    else "V2_DEV_SAMPLE_SUFFICIENT_PRE_OOS_FAILED") if sample_pass
                   else "DEV_REJECTED_INSUFFICIENT_SAMPLE"),
        "NEXT": (("AWAIT_OWNER_AUTHORIZED_OOS_MISSION — OOS is NOT opened here"
                  if pre_oos.get("PRE_OOS_RESULT") == "PASS"
                  else "PRE_OOS_FAILED — no OOS. Any revision needs a NEW preregistration.")
                 if sample_pass
                 else "NO_OOS. A V3 hypothesis would require its own preregistration."),
        "governance_inputs": {
            f"{n}_sha256": sha256_file(GOV / f"{n}.json") for n in
            ("candidate_contamination_registry", "oos_access_log", "data_authority_gap")},
    }
    write_json(OUT / "final_report.json", final)
    write_json(OUT / "dataset_binding.json", {
        "authority_id": AUTHORITY_ID, "role": "DEVELOPMENT",
        "dataset_manifest_sha256": manifest_sha,
        "cross_source_identity_proof": load_manifest(data_dir)["cross_source_identity_proof"],
        "symbol_years": [{"symbol": a["symbol"], "year": a["year"]} for a in admitted],
        "dev_partition_hash": sha256_json(
            [[a["symbol"], a["year"], a["quality"]["bars"]] for a in admitted]),
        "OOS_OPENED": "NO", "HOLDOUT_TOUCHED": "NO",
    })

    manifest_out = {
        "artifact_set": "GEN2_ASIAN_LIQUIDITY_DISPLACEMENT_V2",
        "experiment_id": P.EXPERIMENT_ID,
        "generated_at_utc": started, "implementation_sha": head,
        "dataset_role": "DEVELOPMENT", "dataset_authority": AUTHORITY_ID,
        "external_evidence_pointer": {"candidate_ledger": cas_pointer,
                                      "dataset_manifest_sha256": manifest_sha},
        "files": {p.name: {"sha256": sha256_file(p), "bytes": p.stat().st_size}
                  for p in sorted(OUT.iterdir())
                  if p.is_file() and p.name != "artifact_manifest.json"},
    }
    write_json(OUT / "artifact_manifest.json", manifest_out)

    print(json.dumps({k: final[k] for k in (
        "OPPORTUNITY_N", "SESSION_EVENT_N", "SWEEP_OR_BREAKOUT_N", "RECLAIM_OR_RETEST_N",
        "STRUCTURE_CONFIRM_N", "ENTRY_AVAILABLE_N", "GEOMETRY_VALID_N", "TRADE_COMPLETED_N",
        "ENTRY_YIELD_PER_1000_OPPORTUNITIES", "CAPABILITY", "MEDIAN_NATURAL_TARGET_R",
        "SAMPLE_FLOOR", "SAMPLE_GATE", "PRIMARY_FUNNEL_WEAKNESS", "PRE_OOS_RESULT",
        "FAILED_ROBUSTNESS_AXES", "FROZEN_CANDIDATE", "STATUS", "NEXT")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
