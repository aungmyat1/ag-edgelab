#!/usr/bin/env python
"""Post-result, append-only governance record for GEN2_ALD_V1_MULTIYEAR_DEV_R1.

Run AFTER the replay.  Appends, never rewrites:
  * candidate_contamination_registry.json — one DEVELOPMENT_KNOWN record per
    newly consumed annual DEV window (2017 is already registered),
  * candidate_ledger.json              — the experiment's permanent record,
  * data_authority_gap.json            — the R2 resolution of FX_STATUS,
  * oos_access_log.json                — registers the R2 dataset and its
    partitions so future agents can see that Sep-Dec of 2000-2016 is FRESH and
    unconsumed. No access event is added: none occurred.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ag_edgelab.data.fingerprint import sha256_file
from ag_edgelab.data.fx_histdata_multiyear import (
    AUTHORITY_ID,
    COVERAGE,
    MIRROR,
    admitted_symbol_years,
    load_manifest,
    manifest_path,
    partition_bounds,
)
from ag_edgelab.strategies import asian_liquidity_displacement_multiyear as M
from ag_edgelab.strategies.asian_liquidity_displacement_v1 import CANDIDATE_FAMILY_ID
from ag_edgelab.system_completion import (
    ContaminationRecord,
    ContaminationRegistry,
    ExposureType,
    ReusePolicy,
)

GOV = Path("config/governance")
ART = Path("data/artifacts/gen2_asian_liquidity_displacement_v1_multiyear")


def write(path: Path, payload, *, sort_keys: bool) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=sort_keys) + "\n", encoding="utf-8")


def main() -> None:
    final = json.loads((ART / "final_report.json").read_text())
    prereg_hash = final["PREREGISTRATION_HASH"]
    years = sorted({y for _, y in admitted_symbol_years()})

    # ---- 1. contamination registry ---------------------------------------
    path = GOV / "candidate_contamination_registry.json"
    reg = json.loads(path.read_text())
    existing = {(r["candidate_family_id"], r["start"], r["end"]) for r in reg["records"]}
    new_records = []
    for year in years:
        start, end = partition_bounds("DEVELOPMENT", year)
        key = (CANDIDATE_FAMILY_ID, start.isoformat().replace("+00:00", "Z"),
               end.isoformat().replace("+00:00", "Z"))
        if key in existing or year == 2017:
            continue
        symbols = sorted(s for s, (a, b) in COVERAGE.items() if a <= year <= b)
        new_records.append({
            "candidate_family_id": CANDIDATE_FAMILY_ID,
            "source_candidate_id": f"{M.EXPERIMENT_ID} (ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1, rules unchanged)",
            "start": key[1], "end": key[2],
            "exposure_type": ExposureType.PRIOR_STRATEGY_DESIGN.value,
            "exposure_timestamp": final["generated_at_utc"],
            "knowledge_source": (
                f"multi-year DEVELOPMENT replay of the frozen V1 rules on {AUTHORITY_ID} "
                f"({', '.join(symbols)}); evidence {ART}/"),
            "reuse_policy": ReusePolicy.DEVELOPMENT_KNOWN.value,
            "notes": (
                f"DEVELOPMENT ONLY. The {year} OOS window [{year}-09-01, {year}-12-01) and "
                f"holdout [{year}-12-01, {year + 1}-01-01) were NOT opened and remain FRESH. "
                "This annual DEV window may never serve as OOS for any "
                "ASIAN_LIQUIDITY_DISPLACEMENT candidate."),
            "evidence_hash": prereg_hash,
        })
    reg["records"] = reg["records"] + new_records
    # validate through the accepted contract before writing
    validation = ContaminationRegistry(records=[
        ContaminationRecord(
            candidate_family_id=r["candidate_family_id"],
            source_candidate_id=r["source_candidate_id"], start=r["start"], end=r["end"],
            exposure_type=ExposureType(r["exposure_type"]),
            exposure_timestamp=r["exposure_timestamp"],
            knowledge_source=r["knowledge_source"],
            reuse_policy=ReusePolicy(r["reuse_policy"]), notes=r["notes"],
            evidence_hash=r["evidence_hash"]) for r in reg["records"]]).validate()
    assert validation["state"] == "PASS", validation
    write(path, reg, sort_keys=True)
    print(f"contamination registry: +{len(new_records)} records "
          f"(total {validation['record_count']})")

    # ---- 2. candidate ledger ---------------------------------------------
    path = GOV / "candidate_ledger.json"
    led = json.loads(path.read_text())
    already = any(r["CANDIDATE_ID"] == M.EXPERIMENT_ID for r in led["records"])
    comp = final["V1_NARROW_VS_MULTIYEAR"]
    record = {
        "CANDIDATE_ID": M.EXPERIMENT_ID,
        "CANDIDATE_HASH": final["STRATEGY_HASH"],
        "STATUS": final["STATUS"],
        "EDGE_STATUS": "INSUFFICIENT_EVIDENCE",
        "FAILURE_STAGE": "DEV_FUNNEL_STARVATION (confirmed on a multi-year corpus)",
        "OOS_VERDICT": f"NOT_RUN (PRE_OOS_RESULT = {final['PRE_OOS_RESULT']})",
        "ECONOMIC_VERDICT": "NOT_ESTIMABLE",
        "OOS_WINDOW": "not consumed for any year",
        "OOS_ROLE": "NOT_CONSUMED",
        "RELATED_MODEL_SELECTION_REUSE": (
            "CAUTIONED — the annual DEV windows [YYYY-01-01, YYYY-09-01) for "
            f"{years[0]}-{years[-1]} are now DEVELOPMENT_KNOWN for the "
            f"{CANDIDATE_FAMILY_ID} family (see candidate_contamination_registry.json). "
            "Sep-Dec of every year remains FRESH and unconsumed."),
        "HOLDOUT_TOUCHED": "NO",
        "lifecycle": "DEV_REJECTED",
        "verification_stage": "DEVELOPMENT_EVIDENCE_EXPANSION (multi-year replay, rules frozen)",
        "candidate_family_id": CANDIDATE_FAMILY_ID,
        "strategy_identity": {
            "strategy_id": final["STRATEGY_ID"], "strategy_version": final["STRATEGY_VERSION"],
            "RULES_CHANGED": "NO", "rule_version_bump": "NONE",
            "EXPECTED_RULE_HASH_reproduced": True},
        "preregistration": (f"{ART}/preregistration.json (sha256 {prereg_hash}, committed "
                            "BEFORE the multi-year replay)"),
        "evidence_bundle": f"{ART}/",
        "dataset": (f"{AUTHORITY_ID} — {final['DEV_SYMBOL_YEARS_N']} symbol-years over "
                    f"{final['DEV_YEARS_N']} calendar years, DEVELOPMENT partitions only"),
        "final_report": f"{ART}/final_report.json",
        "key_results": {
            "OPPORTUNITY_N": final["OPPORTUNITY_N"],
            "DIRECTIONAL_N": final["DIRECTIONAL_N"],
            "TRIGGER_PASS_N": final["TRIGGER_PASS_N"],
            "CONFIRMATION_PASS_N": final["CONFIRMATION_PASS_N"],
            "GEOMETRY_VALID_N": final["GEOMETRY_VALID_N"],
            "ENTRY_AVAILABLE_N": final["ENTRY_AVAILABLE_N"],
            "SAMPLE_CLASSIFICATION": final["SAMPLE_CLASSIFICATION"],
            "DECISION_CASE": final["DECISION_CASE"],
            "2017_ENTRY_N": comp["narrow_2017_dev"]["ENTRY_AVAILABLE_N"],
            "corpus_growth_x": comp["corpus_growth_x"],
            "2017_representative": comp["2017_representative"],
            "PRE_OOS_RESULT": final["PRE_OOS_RESULT"],
        },
        "governance_input_hash_semantics": (
            "dataset_binding.json records governance_inputs_sha256 as consulted IMMEDIATELY "
            "BEFORE the replay, i.e. the state in which the multi-year DEV windows were still "
            "FRESH_DEVELOPMENT. Those pins deliberately do NOT match the files at this commit, "
            "because this record and the 17 contamination records below were appended AFTER the "
            "replay finished. Post-append hashes are pinned in "
            "governance_input_hashes_after_append so both states are verifiable."),
        "governance_input_hashes_after_append": "FILLED_BELOW",
        "note": (
            "Dataset-expansion experiment on the UNCHANGED V1 rules. The corpus grew "
            f"{comp['corpus_growth_x']}x (4 -> {final['DEV_SYMBOL_YEARS_N']} symbol-years) and "
            f"the entry population went from {comp['narrow_2017_dev']['ENTRY_AVAILABLE_N']} to "
            f"{final['ENTRY_AVAILABLE_N']}. SAMPLE_CLASSIFICATION = "
            f"{final['SAMPLE_CLASSIFICATION']}. No rule, threshold, session window, symbol or "
            "year was selected or altered in response to any result. Never edit this record to "
            "rescue the candidate."),
    }
    record["governance_input_hashes_after_append"] = {
        f"{name}_sha256": sha256_file(GOV / f"{name}.json")
        for name in ("candidate_contamination_registry", "data_authority_gap", "oos_access_log")}
    record["governance_input_hashes_before_replay"] = json.loads(
        (ART / "dataset_binding.json").read_text())["governance_inputs"]
    if not already:  # append-only: never rewrite an existing verdict
        led["records"].append(record)
        write(path, led, sort_keys=False)
    print(f"candidate ledger: {len(led['records'])} records")

    # ---- 3. data authority gap -------------------------------------------
    path = GOV / "data_authority_gap.json"
    gap = json.loads(path.read_text())
    gap["FX_STATUS_R2"] = "MULTI_YEAR_AUTHORITY_ESTABLISHED"
    gap["multi_year_authority_r2"] = {
        "authority_id": AUTHORITY_ID,
        "established_by": M.EXPERIMENT_ID,
        "supersedes_limitation": "single calendar year (2017) — regime coverage insufficient",
        "coverage": {s: list(v) for s, v in sorted(COVERAGE.items())},
        "symbol_years": len(admitted_symbol_years()),
        "mirror": MIRROR,
        "manifest": str(manifest_path()),
        "manifest_sha256": sha256_file(manifest_path()),
        "admissibility_proof": load_manifest()["cross_source_identity_proof"]["method"],
        "partitions_utc": {
            "DEVELOPMENT": "[YYYY-01-01, YYYY-09-01) for every admitted year — CONSUMED by "
                           f"{M.EXPERIMENT_ID}",
            "OOS": "[YYYY-09-01, YYYY-12-01) for every admitted year — FRESH, NEVER OPENED "
                   "(2017 excepted: consumed by OOS-001 and OOS-002 for other candidates)",
            "SEALED_HOLDOUT": "[YYYY-12-01, YYYY+1-01-01) for every admitted year — SEALED",
        },
        "contract_compliance": "all seven multi_year_data_authority_contract requirements are "
                               f"mapped to mechanisms in {ART}/dataset_binding.json",
        "standing_limitations": [
            "one data provider (HistData); provider-specific artifacts are frozen in the loader",
            "EURUSD/GBPUSD/USDJPY 2000 archives begin in May, so those DEV windows are short",
            "XAUUSD has no history before 2009, so the panel is unbalanced before then",
        ],
    }
    write(path, gap, sort_keys=False)
    print("data_authority_gap: FX_STATUS_R2 recorded")

    # ---- 4. oos access log: register the dataset, add NO event -----------
    path = GOV / "oos_access_log.json"
    log = json.loads(path.read_text())
    before = len(log["events"])
    log["dataset_registry"][AUTHORITY_ID] = {
        "product": "HistData.com Generic ASCII M1, one archive per symbol-year",
        "mirror": MIRROR,
        "symbols": {s: f"{v[0]}-{v[1]}" for s, v in sorted(COVERAGE.items())},
        "manifest": str(manifest_path()),
        "manifest_sha256": sha256_file(manifest_path()),
        "partitions_utc": {
            "DEVELOPMENT": "[YYYY-01-01, YYYY-09-01) per year",
            "OOS": "[YYYY-09-01, YYYY-12-01) per year",
            "SEALED_HOLDOUT": "[YYYY-12-01, YYYY+1-01-01) per year",
        },
        "oos_consumption_status": (
            "NEVER OPENED for any year by any candidate under this authority. The 2017 OOS "
            "window is separately recorded as consumed under HISTDATA_ASCII_M1_2017_PR10_PINNED "
            "(events OOS-001, OOS-002). All other years' OOS windows are FRESH."),
        "registered_by": M.EXPERIMENT_ID,
        "registered_at_utc": final["generated_at_utc"],
    }
    write(path, log, sort_keys=False)
    assert len(log["events"]) == before, "no OOS access event may be added: none occurred"
    print(f"oos_access_log: dataset registered, events unchanged ({before})")

    # ---- 5. external artifact registry -----------------------------------
    # "No external artifact may exist without a pinned hash in this registry."
    path = GOV / "external_artifact_registry.json"
    reg = json.loads(path.read_text())
    artifact_id = "GEN2_ALD_V1_MULTIYEAR_CANDIDATE_LEDGER"
    if not any(a["artifact_id"] == artifact_id for a in reg["artifacts"]):
        pointer = json.loads(
            (ART / "artifact_manifest.json").read_text())["external_evidence_pointer"][
                "candidate_ledger"]
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        reg["artifacts"].append({
            "artifact_id": artifact_id,
            "sha256": pointer["sha256"],
            "byte_size": pointer["bytes"],
            "uncompressed_sha256": pointer["uncompressed_sha256"],
            "uncompressed_byte_size": pointer["uncompressed_bytes"],
            "rows": pointer["rows"],
            "schema_version": "GEN2_ALD_V1_CANDIDATE_LEDGER_ROWS_V1 (frozen, shared with the "
                              "2017 campaign: scripts/run_gen2_asian_liquidity_displacement_v1_"
                              "dev.py:unit_row)",
            "producer_commit": f"{head} (+ this commit)",
            "producer_script": "scripts/run_gen2_ald_v1_multiyear_dev.py",
            "candidate_id": M.EXPERIMENT_ID,
            "dataset_role": "DEVELOPMENT",
            "dataset_window": "[YYYY-01-01T00:00:00+00:00, YYYY-09-01T00:00:00+00:00) for "
                              f"{len(admitted_symbol_years())} symbol-years over {years[0]}-"
                              f"{years[-1]}",
            "storage_location": f"local: {pointer['path']} (gitignored; NOT committed)",
            "externalized_by_commit": M.EXPERIMENT_ID,
            "reason": ("33 MB per-unit replay ledger (one row per candidate unit); no runtime "
                       "test reads it — the tests read the aggregated artifacts — and it is "
                       "regenerable byte-for-byte by the producer script (deterministic replay, "
                       "gzip mtime=0) from the hash-pinned archive manifest."),
            "retrieval": ("re-run scripts/acquire_histdata_fx_multiyear.py then the producer "
                          f"script; verify sha256 == {pointer['sha256']}"),
        })
        write(path, reg, sort_keys=False)
    print(f"external_artifact_registry: {len(reg['artifacts'])} artifacts")


if __name__ == "__main__":
    main()
