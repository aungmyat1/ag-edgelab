#!/usr/bin/env python
"""GENERATION 2 DEVELOPMENT replay + three-funnel analysis for
ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1.

DEVELOPMENT ONLY.  This script never requests the OOS or SEALED_HOLDOUT
partitions, never adds execution capability, and never mutates a verifier
threshold.  It consumes the preregistration committed before it ran.

Usage:
    python scripts/run_gen2_asian_liquidity_displacement_v1_dev.py [data_dir]
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ag_edgelab.data.fingerprint import canonical_json, sha256_file, sha256_json
from ag_edgelab.strategies import asian_liquidity_displacement_analysis as A
from ag_edgelab.strategies.asian_liquidity_displacement_prereg import (
    DISPLACEMENT_NEIGHBORHOOD,
    POOLED_ENTRY_ELIGIBILITY_N,
    PRE_OOS_GATE_ID,
    pre_oos_gate_contract,
    root_cause_contract,
)
from ag_edgelab.strategies.asian_liquidity_displacement_v1 import (
    CANDIDATE_FAMILY_ID,
    DISPLACEMENT_BODY_RANGE_MIN,
    FORBIDDEN_IDENTITY_REUSE,
    STRATEGY_HASH,
    STRATEGY_ID,
    STRATEGY_VERSION,
    SYMBOL_UNIVERSE,
    TIMEFRAMES,
    VERIFIER_VERSION,
    contract_hashes,
    load_development_dataset,
    replay_symbol,
    strategy_contract,
)
from ag_edgelab.system_completion import FrozenCandidateIdentity

OUT = Path("data/artifacts/gen2_asian_liquidity_displacement_v1")
DEFAULT_DATA = Path("data/external/histdata_fx_2017")
READINESS = Path("data/artifacts/edgelab_system_completion_v1/system_readiness.json")
CONTAMINATION = Path("config/governance/candidate_contamination_registry.json")
LEDGER = Path("config/governance/candidate_ledger.json")
OOS_LOG = Path("config/governance/oos_access_log.json")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8")


# ---------------------------------------------------------------------------
# 0. AUTHORITY GATE
# ---------------------------------------------------------------------------

def authority_gate() -> dict:
    readiness = json.loads(READINESS.read_text())
    required = {"SYSTEM_SOFTWARE_COMPLETE": "YES", "RESEARCH_GENERATION_2_ALLOWED": "YES",
                "OOS_ECONOMIC_AUTHORIZED": "NO", "HOLDOUT_AUTHORIZED": "NO",
                "LIVE_EXECUTION_AUTHORIZED": "NO"}
    observed = {k: readiness.get(k) for k in required}
    ok = observed == required
    if not ok:
        raise SystemExit(f"AUTHORITY GATE FAILED: required={required} observed={observed}")
    return {"state": "PASS", "required": required, "observed": observed,
            "evidence": str(READINESS), "evidence_sha256": sha256_file(READINESS)}


def contamination_check(dev_window: list[str]) -> dict:
    registry = json.loads(CONTAMINATION.read_text())
    overlaps = [r for r in registry.get("records", [])
                if r.get("candidate_family_id") == CANDIDATE_FAMILY_ID
                and r.get("start", "") < dev_window[1] and dev_window[0] < r.get("end", "")]
    ledger = json.loads(LEDGER.read_text())
    existing_ids = {r.get("CANDIDATE_ID") for r in ledger.get("records", [])}
    collisions = sorted(existing_ids & ({STRATEGY_ID} | set(FORBIDDEN_IDENTITY_REUSE)) & {STRATEGY_ID})
    return {
        "state": "PASS" if not overlaps and not collisions else "FAIL",
        "candidate_family_id": CANDIDATE_FAMILY_ID,
        "checked_window_utc": dev_window,
        "overlapping_exposure_records": overlaps,
        "identity_collision_with_existing_ledger": collisions,
        "historical_identities_not_reused": list(FORBIDDEN_IDENTITY_REUSE),
        "registry_sha256": sha256_file(CONTAMINATION),
        "candidate_ledger_sha256": sha256_file(LEDGER),
        "oos_access_log_sha256": sha256_file(OOS_LOG),
        "note": ("DEVELOPMENT reads require a family-freshness check by contract; the family "
                 "ASIAN_LIQUIDITY_DISPLACEMENT has no prior exposure record. DEV data is "
                 "DEVELOPMENT_KNOWN after this mission and can never serve as OOS."),
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DATA
    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    head = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")

    gate = authority_gate()
    contract = strategy_contract()
    hashes = contract_hashes()
    dev_window = contract["development_partition_utc"]
    contamination = contamination_check(dev_window)
    if contamination["state"] != "PASS":
        raise SystemExit(f"CONTAMINATION CHECK FAILED: {contamination}")

    prereg = json.loads((OUT / "preregistration.json").read_text())

    # ---------------- dataset ledger (DEVELOPMENT only) -------------------
    datasets = {}
    dataset_rows = []
    for symbol in SYMBOL_UNIVERSE:
        zip_path = data_dir / f"HISTDATA_COM_ASCII_{symbol}_M1_2017.zip"
        ds = load_development_dataset(zip_path, symbol)
        datasets[symbol] = ds
        dataset_rows.append({
            "record_type": "DATASET_ACCESS",
            "symbol": symbol, "dataset_role": "DEVELOPMENT",
            "partition_utc": dev_window,
            "source_file": zip_path.name, "source_sha256": ds.source_sha256,
            "frame_sha256": ds.frame_hashes, "quality": ds.quality,
            "oos_requested": False, "holdout_requested": False,
            "accessed_at_utc": started,
        })
    dev_partition_hash = sha256_json({s: datasets[s].frame_hashes for s in sorted(datasets)})

    # ---------------- DEV replay (frozen V1) ------------------------------
    units = []
    for symbol in SYMBOL_UNIVERSE:
        units.extend(replay_symbol(datasets[symbol]))
    units.sort(key=lambda u: (u.symbol, u.day, u.session))

    # determinism: a second independent pass must be byte-identical
    units2 = []
    for symbol in SYMBOL_UNIVERSE:
        units2.extend(replay_symbol(datasets[symbol]))
    units2.sort(key=lambda u: (u.symbol, u.day, u.session))
    ledger_rows = [unit_row(u) for u in units]
    ledger_rows2 = [unit_row(u) for u in units2]
    determinism = {
        "double_pass": "BYTE_IDENTICAL" if canonical_json(ledger_rows) == canonical_json(ledger_rows2)
        else "MISMATCH",
        "pass1_sha256": sha256_json(ledger_rows), "pass2_sha256": sha256_json(ledger_rows2)}
    if determinism["double_pass"] != "BYTE_IDENTICAL":
        raise SystemExit("DETERMINISM FAILURE: replay is not reproducible")

    # ---------------- artifacts -------------------------------------------
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "candidate_ledger.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "record_type": "HEADER", "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION, "strategy_hash": STRATEGY_HASH,
            "preregistration_hash": prereg["preregistration_hash"],
            "dataset_role": "DEVELOPMENT", "dev_partition_hash": dev_partition_hash,
            "implementation_sha": head, "generated_at_utc": started,
        }, sort_keys=True, separators=(",", ":")) + "\n")
        for row in dataset_rows:
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str) + "\n")
        for row in ledger_rows:
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")

    matrix = A.stage_matrix(units)
    trigger = A.trigger_analysis(units)
    confirmation = A.confirmation_analysis(units)
    capability = A.target_capability(units)
    survival = A.continuation_survival(units)
    temporal = A.temporal_diagnostics(units)
    analyzer = A.run_universal_funnel_analyzer(units, dev_partition_hash)

    write_json(OUT / "trigger_analysis.json", trigger)
    write_json(OUT / "confirmation_analysis.json", confirmation)
    write_json(OUT / "target_capability.json", capability)
    write_json(OUT / "continuation_survival.json", survival)
    write_json(OUT / "temporal_diagnostics.json", temporal)
    write_json(OUT / "funnel_report.json", {
        "analyzer": "ag_edgelab.analytics.diagnostic.analyze_three_funnel (accepted Universal Funnel Analyzer)",
        "dataset_role": "DEVELOPMENT", "dev_partition_hash": dev_partition_hash,
        "stage_matrix": matrix,
        "universal_funnel_report": json.loads(analyzer.model_dump_json()),
        "determinism": determinism,
    })

    # per symbol/session matrix (CSV)
    header = ["symbol", "session", "CANDIDATE_N", "TRIGGER_INPUT", "TRIGGER_PASS",
              "CONFIRMATION_INPUT", "CONFIRMATION_PASS", "GEOMETRY_VALID", "ENTRY_AVAILABLE",
              "1R", "2R", "3R", "4R", "5R", "natural_target_median_R", "management_expectancy_R"]
    lines = [",".join(header)]
    cells = [(s, t) for s in sorted({u.symbol for u in units})
             for t in sorted({u.session for u in units})]
    for sym, ses in cells + [("POOLED", "POOLED")]:
        sub = units if sym == "POOLED" else [u for u in units if u.symbol == sym and u.session == ses]
        c = A.stage_counts(sub)
        cap = A.target_capability(sub)
        lines.append(",".join([
            sym, ses, str(c["CANDIDATE_N"]), str(c["TRIGGER_INPUT"]), str(c["TRIGGER_PASS"]),
            str(c["CONFIRMATION_INPUT"]), str(c["CONFIRMATION_PASS"]), str(c["GEOMETRY_VALID"]),
            str(c["ENTRY_AVAILABLE"]),
            *[str(c[f"{k}R"]) for k in (1, 2, 3, 4, 5)],
            str(cap["natural_target_R"]["median"]),
            str(cap["management_TP1_TP2_50_50"]["expectancy_r"])]))
    (OUT / "per_symbol_session_matrix.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---------------- robustness + Pre-OOS gate ---------------------------
    entries_n = len(A.entries(units))
    neighborhood = None
    if entries_n >= POOLED_ENTRY_ELIGIBILITY_N:
        neighborhood = {}
        for threshold in DISPLACEMENT_NEIGHBORHOOD:
            alt = []
            for symbol in SYMBOL_UNIVERSE:
                alt.extend(replay_symbol(datasets[symbol], displacement_min=threshold))
            rs = [float(u.management_r) for u in A.entries(alt) if u.management_r is not None]
            neighborhood[float(threshold)] = (sum(rs) / len(rs)) if rs else 0.0
    robustness = A.robustness_report(units, neighborhood)
    robustness["preregistered_gate_contract"] = pre_oos_gate_contract()

    committed_contract = json.loads((OUT / "strategy_contract.json").read_text())
    identity_recheck = {
        "strategy_contract_hash_recomputed": hashes["strategy_contract_hash"],
        "strategy_contract_hash_preregistered":
            committed_contract["contract_hashes"]["strategy_contract_hash"],
        "preregistration_binds_same_contract":
            sha256_json(prereg["strategy_contract"]) == sha256_json(
                {k: v for k, v in committed_contract.items() if k != "contract_hashes"}),
    }
    identity_valid = (
        identity_recheck["strategy_contract_hash_recomputed"]
        == identity_recheck["strategy_contract_hash_preregistered"] == STRATEGY_HASH
        and identity_recheck["preregistration_binds_same_contract"])
    friction_disclosed = contract["friction_contract"]["FRICTION_EDGE_VERIFICATION_READY"] == "NO"
    pre_oos = A.pre_oos_gate_result(units, robustness, capability,
                                    identity_valid=identity_valid,
                                    dataset_role_valid=True,
                                    friction_disclosed=friction_disclosed)
    write_json(OUT / "robustness_report.json", robustness)
    write_json(OUT / "pre_oos_gate_result.json", pre_oos)

    cause = A.root_cause(units, trigger, confirmation, capability, temporal,
                         A.analyzer_verdict(analyzer))

    # ---------------- freeze decision -------------------------------------
    passed = pre_oos["PRE_OOS_RESULT"] == "PASS"
    identity = FrozenCandidateIdentity(
        strategy_code_hash=hashes["strategy_code_hash"],
        parameter_hash=hashes["parameter_hash"],
        funnel_hash=sha256_json({"trigger": hashes["trigger_contract_hash"],
                                 "confirmation": hashes["confirmation_contract_hash"]}),
        entry_contract_hash=hashes["entry_contract_hash"],
        sl_contract_hash=hashes["sl_contract_hash"],
        target_contract_hash=hashes["target_contract_hash"],
        session_contract_hash=hashes["session_contract_hash"],
        symbol_universe=tuple(SYMBOL_UNIVERSE),
        decision_timeframe="M15",
        execution_timeframe="M5",
        dev_dataset_authority="HISTDATA_ASCII_M1_2017_PR10_PINNED",
        dev_partition_hash=dev_partition_hash,
        friction_contract_hash=hashes["friction_contract_hash"],
        preregistration_hash=prereg["preregistration_hash"],
        verifier_version=VERIFIER_VERSION)
    freeze = {
        "FROZEN_CANDIDATE": "YES" if passed else "NO",
        "identity_contract": "FROZEN_CANDIDATE_IDENTITY_V1",
        "binding": identity.as_dict(),
        "candidate_identity_sha256": identity.candidate_identity_sha256 if passed else None,
        "computed_identity_sha256_for_audit": identity.candidate_identity_sha256,
        "reason": ("Pre-OOS Robustness Gate V1 PASSED" if passed else
                   f"Pre-OOS Robustness Gate V1 did not pass: {pre_oos['PRE_OOS_RESULT']}; "
                   f"failing axes={pre_oos['failing_axes']}; "
                   f"unevaluable axes={pre_oos['unevaluable_axes']}"),
        "OOS_OPENED": "NO", "HOLDOUT_TOUCHED": "NO",
    }
    write_json(OUT / "candidate_freeze.json", freeze)

    counts = matrix["POOLED"]
    if pre_oos["PRE_OOS_RESULT"] == "PASS":
        status, nxt = "FROZEN_PRE_OOS_CANDIDATE", "WAIT_FOR_FRICTION_AND_OOS_AUTHORIZATION"
    elif counts["ENTRY_AVAILABLE"] < POOLED_ENTRY_ELIGIBILITY_N:
        # The DEV sample never became structurally sufficient: this is a
        # DEVELOPMENT rejection of the V1 hypothesis, not a gate failure.
        status = "DEV_REJECTED"
        nxt = "DESIGN_NEW_V2_HYPOTHESIS"
    else:
        status, nxt = "PRE_OOS_FAILED", "DESIGN_NEW_V2_HYPOTHESIS"

    final = {
        "mission": "ARENA RESEARCH GENERATION 2 — FX SESSION CANDIDATE V1",
        "generated_at_utc": started,
        "IMPLEMENTATION_SHA": head, "TREE_SHA": tree,
        "STRATEGY_ID": STRATEGY_ID, "STRATEGY_VERSION": STRATEGY_VERSION,
        "STRATEGY_HASH": STRATEGY_HASH,
        "CANDIDATE_FAMILY_ID": CANDIDATE_FAMILY_ID,
        "PREREGISTRATION_HASH": prereg["preregistration_hash"],
        "contract_hashes": hashes,
        "identity_recheck": identity_recheck,
        "authority_gate": gate,
        "contamination_check": contamination,
        "DATASET_ROLE": "DEVELOPMENT",
        "DATASET_AUTHORITY": "HISTDATA_ASCII_M1_2017_PR10_PINNED",
        "DEV_PARTITION_UTC": dev_window,
        "DEV_PARTITION_HASH": dev_partition_hash,
        "SYMBOLS": list(SYMBOL_UNIVERSE), "TIMEFRAMES": list(TIMEFRAMES),
        "SESSIONS": sorted({u.session for u in units}) + ["POOLED"],
        "CANDIDATE_N": counts["CANDIDATE_N"],
        "TRIGGER_INPUT_N": counts["TRIGGER_INPUT"], "TRIGGER_PASS_N": counts["TRIGGER_PASS"],
        "CONFIRMATION_INPUT_N": counts["CONFIRMATION_INPUT"],
        "CONFIRMATION_PASS_N": counts["CONFIRMATION_PASS"],
        "GEOMETRY_VALID_N": counts["GEOMETRY_VALID"],
        "ENTRY_AVAILABLE_N": counts["ENTRY_AVAILABLE"],
        "CAPABILITY": {f"{k}R_CAPABILITY": capability["fixed_r_capability"][f"{k}R"]
                       for k in (1, 2, 3, 4, 5)},
        "NATURAL_TARGET_MEDIAN_R": capability["natural_target_R"]["median"],
        "CONTINUATION": survival["conditional_continuation"],
        "PRIMARY_FUNNEL_WEAKNESS": cause["PRIMARY_FUNNEL_WEAKNESS"],
        "SECONDARY_DIAGNOSES": cause["SECONDARY_DIAGNOSES"],
        "root_cause": cause,
        "ROBUSTNESS": {k: v.get("state") for k, v in robustness["axes"].items()},
        "PRE_OOS_RESULT": pre_oos["PRE_OOS_RESULT"],
        "FROZEN_CANDIDATE": freeze["FROZEN_CANDIDATE"],
        "CANDIDATE_IDENTITY_SHA256": freeze["candidate_identity_sha256"],
        "FRICTION_EDGE_VERIFICATION_READY": "NO",
        "ECONOMIC_METRICS": "NOT_ESTIMABLE_NO_FRICTION_AUTHORITY",
        "OOS_OPENED": "NO", "HOLDOUT_TOUCHED": "NO",
        "STRATEGY_EXECUTION_ADDED": "NO", "BROKER_MUTATION": "NO",
        "SEARCH_LEDGER": {"optimizer_runs": 0, "trial_count": 0,
                          "hypotheses_evaluated": 1,
                          "threshold_mutations": 0,
                          "post_hoc_selection": "NONE"},
        "determinism": determinism,
        "STATUS": status, "NEXT": nxt,
    }
    write_json(OUT / "final_report.json", final)
    (OUT / "final_report.md").write_text(render_markdown(
        final, matrix, trigger, confirmation, capability, survival, temporal, robustness,
        pre_oos, freeze), encoding="utf-8")

    manifest = {
        "artifact_set": "GEN2_ASIAN_LIQUIDITY_DISPLACEMENT_V1",
        "generated_at_utc": started, "implementation_sha": head, "tree_sha": tree,
        "dataset_role": "DEVELOPMENT",
        "external_evidence_pointer": {
            "raw_dataset": "NOT COMMITTED — hash-pinned HistData zips fetched by "
                           "scripts/acquire_histdata_fx_2017.sh into data/external/histdata_fx_2017",
            "pinned_sha256": contract["pinned_source_sha256"]},
        "files": {p.name: {"sha256": sha256_file(p), "bytes": p.stat().st_size}
                  for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "artifact_manifest.json"},
    }
    write_json(OUT / "artifact_manifest.json", manifest)

    print(json.dumps({k: final[k] for k in (
        "CANDIDATE_N", "TRIGGER_PASS_N", "CONFIRMATION_PASS_N", "GEOMETRY_VALID_N",
        "ENTRY_AVAILABLE_N", "PRIMARY_FUNNEL_WEAKNESS", "SECONDARY_DIAGNOSES",
        "PRE_OOS_RESULT", "FROZEN_CANDIDATE", "STATUS", "NEXT")}, indent=2))


def unit_row(u) -> dict:
    return {
        "record_type": "CANDIDATE", "candidate_id": u.candidate_id, "symbol": u.symbol,
        "day": u.day, "session": u.session, "quarter": u.quarter, "regime": u.regime,
        "dataset_role": "DEVELOPMENT",
        "d1_structure": u.d1_structure, "h4_structure": u.h4_structure, "h1_flow": u.h1_flow,
        "premium_discount_state": u.premium_discount_state, "prev_day_context": u.prev_day_context,
        "liquidity_pools_above": u.liquidity_context_above,
        "liquidity_pools_below": u.liquidity_context_below,
        "direction": u.direction, "asian_high": u.asian_high, "asian_low": u.asian_low,
        "asian_bars": u.asian_bars, "entry_window_m15_bars": u.entry_window_bars,
        "stages": dict(sorted(u.stages.items())), "reject_node": u.reject_node,
        "reject_reason": u.reject_reason,
        "sweep_time": u.sweep_time, "reclaim_time": u.reclaim_time,
        "displacement_time": u.displacement_time,
        "displacement_body_ratio": u.displacement_body_ratio,
        "mss_time": u.mss_time, "mss_primitive": u.mss_primitive,
        "fvg_time": u.fvg_time, "entry_time": u.entry_time,
        "entry": u.entry, "stop": u.stop, "risk": u.risk,
        "tp1": u.tp1, "tp1_r": u.tp1_r, "tp2": u.tp2, "tp2_r": u.tp2_r,
        "natural_target_r": u.natural_target_r,
        "mfe_r": u.mfe_r, "mae_r": u.mae_r, "reached": dict(sorted(u.reached.items())),
        "stopped_out": u.stopped_out, "stopped_same_bar": u.stopped_same_bar,
        "resolution": u.resolution, "management_r": u.management_r, "horizon_r": u.horizon_r,
        "forward_m5_bars": u.forward_bars,
        "m15_bars_after_sweep": u.m15_bars_after_sweep,
        "m15_bars_after_reclaim": u.m15_bars_after_reclaim,
        "m15_bars_after_displacement": u.m15_bars_after_displacement,
        "m5_bars_after_mss": u.m5_bars_after_mss,
        "opportunity_mfe_r": u.opp_mfe_r, "opportunity_mae_r": u.opp_mae_r,
    }


def render_markdown(final, matrix, trigger, confirmation, capability, survival, temporal,
                    robustness, pre_oos, freeze) -> str:
    c = matrix["POOLED"]
    cap = capability["fixed_r_capability"]
    rows = ["| stage | n | % of previous |", "|---|---:|---:|"]
    prev = c["CANDIDATE_N"]
    for label, key in (("CANDIDATE (symbol x day x session)", "CANDIDATE_N"),
                       ("TRIGGER_INPUT", "TRIGGER_INPUT"), ("TRIGGER_PASS", "TRIGGER_PASS"),
                       ("CONFIRMATION_PASS", "CONFIRMATION_PASS"),
                       ("GEOMETRY_VALID", "GEOMETRY_VALID"),
                       ("ENTRY_AVAILABLE", "ENTRY_AVAILABLE"),
                       ("1R", "1R"), ("2R", "2R"), ("3R", "3R"), ("4R", "4R"), ("5R", "5R")):
        n = c[key]
        rows.append(f"| {label} | {n} | {'' if prev == 0 else f'{n / prev * 100:.2f}%'} |")
        prev = n if n else prev
    sym_rows = ["| symbol | TRIGGER_PASS | CONFIRMATION_PASS | ENTRY_AVAILABLE |", "|---|---:|---:|---:|"]
    for sym, cc in matrix["BY_SYMBOL"].items():
        sym_rows.append(f"| {sym} | {cc['TRIGGER_PASS']} | {cc['CONFIRMATION_PASS']} | {cc['ENTRY_AVAILABLE']} |")
    ses_rows = ["| session | TRIGGER_PASS | CONFIRMATION_PASS | ENTRY_AVAILABLE |", "|---|---:|---:|---:|"]
    for ses, cc in matrix["BY_SESSION"].items():
        ses_rows.append(f"| {ses} | {cc['TRIGGER_PASS']} | {cc['CONFIRMATION_PASS']} | {cc['ENTRY_AVAILABLE']} |")
    chain = ["| step | input | pass | pass % | dominant reason |", "|---|---:|---:|---:|---|"]
    for step in confirmation["sequence"]:
        dom = next(iter(step["reason_counts"]), "-")
        pp = "-" if step["pass_pct_of_input"] is None else f"{step['pass_pct_of_input']:.2f}%"
        chain.append(f"| {step['step']} | {step['input_n']} | {step['pass_n']} | {pp} | {dom} |")
    axes = ["| axis | state |", "|---|---|"]
    for k, v in robustness["axes"].items():
        axes.append(f"| {k} | {v.get('state')} |")
    opp = trigger["opportunity_basis_capability"]
    sa = final["root_cause"]["starvation_attribution"]
    starvation_rows = ["| step | input | output | survival | absolute loss |", "|---|---:|---:|---:|---:|"]
    for st in sa["steps"]:
        sp = "-" if st["survival_pct"] is None else f"{st['survival_pct']:.2f}%"
        starvation_rows.append(
            f"| {st['from']} -> {st['to']} | {st['input_n']} | {st['output_n']} | {sp} | {st['absolute_loss']} |")
    la = sa["largest_absolute_attrition"]
    starvation_summary = (
        f"Largest absolute attrition (excluding calendar structure): **{la['to']}** "
        f"({la['input_n']} -> {la['output_n']}, survival {la['survival_pct']}%, "
        f"{la['absolute_loss']} candidates lost).")
    calendar_note = sa["steps"][0].get("calendar_note", "")
    av = final["root_cause"]["universal_funnel_analyzer_verdict"] or {"weak_points": [], "mapped_mission_labels": []}
    analyzer_rows = ["| label | scope | evidence |", "|---|---|---|"]
    for wp in av["weak_points"]:
        analyzer_rows.append(f"| `{wp['label']}` | {wp['scope']} | {wp['evidence']} |")
    analyzer_rows.append("")
    analyzer_rows.append(f"mapped mission labels: {', '.join(av['mapped_mission_labels']) or 'none'}")

    return f"""# ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1 — GENERATION 2 DEV report

STATUS: **{final['STATUS']}** · PRE_OOS_RESULT: **{final['PRE_OOS_RESULT']}** · FROZEN_CANDIDATE: **{final['FROZEN_CANDIDATE']}**

| field | value |
|---|---|
| strategy_id | `{final['STRATEGY_ID']}` |
| strategy_version | `{final['STRATEGY_VERSION']}` |
| strategy_hash | `{final['STRATEGY_HASH']}` |
| preregistration_hash | `{final['PREREGISTRATION_HASH']}` |
| implementation_sha | `{final['IMPLEMENTATION_SHA']}` |
| tree_sha | `{final['TREE_SHA']}` |
| dataset_role | `DEVELOPMENT` ({final['DEV_PARTITION_UTC'][0]} .. {final['DEV_PARTITION_UTC'][1]}) |
| dev_partition_hash | `{final['DEV_PARTITION_HASH']}` |
| symbols | {', '.join(final['SYMBOLS'])} |
| sessions | {', '.join(final['SESSIONS'])} |
| OOS_OPENED / HOLDOUT_TOUCHED | NO / NO |
| execution added / broker mutation | NO / NO |
| friction | FRICTION_EDGE_VERIFICATION_READY = NO → ECONOMIC_METRICS = NOT_ESTIMABLE |

## 1. Funnel (pooled)

{chr(10).join(rows)}

### per symbol

{chr(10).join(sym_rows)}

### per session

{chr(10).join(ses_rows)}

## 2. Confirmation chain (mission section 5 ordering)

{chr(10).join(chain)}

## 3. Target capability

| metric | value |
|---|---|
| 1R capability | {cap['1R']} |
| 2R capability | {cap['2R']} |
| 3R capability | {cap['3R']} |
| 4R capability | {cap['4R']} |
| 5R capability | {cap['5R']} |
| median natural target R | {capability['natural_target_R']['median']} |
| median MFE_R / MAE_R | {capability['MFE_R']['median']} / {capability['MAE_R']['median']} |
| continuation | {survival['conditional_continuation']} |

Economic profitability is **not** claimed: no measured friction authority exists
(section 13), so only structural R is reported.

## 4. Trigger quality (opportunity basis, frozen observation policy)

| population | n | 1R | 3R | 5R |
|---|---:|---:|---:|---:|
| DIRECTION_NON_NEUTRAL | {opp['non_neutral_n']} | {opp['reach_by_target_non_neutral']['1R']} | {opp['reach_by_target_non_neutral']['3R']} | {opp['reach_by_target_non_neutral']['5R']} |
| TRIGGER_PASS | {opp['trigger_pass_n']} | {opp['reach_by_target_trigger_pass']['1R']} | {opp['reach_by_target_trigger_pass']['3R']} | {opp['reach_by_target_trigger_pass']['5R']} |

## 5. Temporal diagnostics

- median M15 bars left in the entry window after the reclaim bar: **{temporal['m15_bars_remaining_after_reclaim']}**
- sequential events still required after the reclaim bar: **{temporal['sequential_events_still_required_after_reclaim']}**
- window-bounded share of post-trigger attrition: **{temporal['window_bounded_rejection_share_of_post_trigger']}%**

## 6. Root cause

- PRIMARY_FUNNEL_WEAKNESS: **{final['PRIMARY_FUNNEL_WEAKNESS']}**
- SECONDARY_DIAGNOSES: {final['SECONDARY_DIAGNOSES'] or 'none'}

{chr(10).join(f"- `{f['label']}` ({f.get('source', 'PREREGISTERED_DECISION_ORDER')}) — {f['evidence']}" for f in final['root_cause']['findings']) or '- none'}

### 6.1 Starvation attribution (which step destroyed the sample)

{chr(10).join(starvation_rows)}

{starvation_summary}

{calendar_note}

### 6.2 Universal Funnel Analyzer verdict (accepted system, frozen thresholds)

{chr(10).join(analyzer_rows)}

## 7. Robustness / Pre-OOS Robustness Gate V1

eligibility: pooled ENTRY_AVAILABLE = {robustness['eligibility']['pooled_entry_available_n']} (required {robustness['eligibility']['required']}) → eligible = {robustness['eligibility']['eligible']}

{chr(10).join(axes)}

PRE_OOS_RESULT = **{pre_oos['PRE_OOS_RESULT']}** · failing axes: {pre_oos['failing_axes'] or 'none'} · unevaluable: {pre_oos['unevaluable_axes'] or 'none'}

## 8. Freeze decision

FROZEN_CANDIDATE = **{freeze['FROZEN_CANDIDATE']}** — {freeze['reason']}

CANDIDATE_IDENTITY_SHA256 = `{freeze['candidate_identity_sha256']}`

## 9. Search policy compliance

optimizer runs = 0 · trials = 0 · hypotheses evaluated = 1 · verifier threshold mutations = 0 ·
post-hoc symbol/rule selection = NONE · session windows never widened · displacement threshold
0.70 frozen throughout.
"""


if __name__ == "__main__":
    main()
