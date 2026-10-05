#!/usr/bin/env python
"""MISSION 3 PHASE 0 — governance preconditions for V2 design.

Fails closed. V2 design may not begin unless every check passes:
  * base identity (branch, HEAD, PR #18 head)
  * V1 evidence integrity (manifest hashes, final_return, frozen rule hash)
  * contamination registry covers the DEV windows and NOTHING later
  * every Sep-Dec OOS window is still FRESH under the R2 authority
  * the sealed holdout was never touched
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ag_edgelab.data.fingerprint import sha256_file
from ag_edgelab.data.fx_histdata_multiyear import AUTHORITY_ID, admitted_symbol_years
from ag_edgelab.strategies.asian_liquidity_displacement_v1 import (
    CANDIDATE_FAMILY_ID,
    STRATEGY_HASH,
)

GOV = Path("config/governance")
V1_MY = Path("data/artifacts/gen2_asian_liquidity_displacement_v1_multiyear")
V1_17 = Path("data/artifacts/gen2_asian_liquidity_displacement_v1")
OUT = Path("data/artifacts/gen2_asian_liquidity_displacement_v2")

V1_EXPECTED_RULE_HASH = "28c4f52f2ef6b54977e407e0c5ce93ef4f9b41a7bced37327a4844d392669a94"


def main() -> int:
    checks: list[dict] = []
    failures: list[str] = []

    def check(name: str, ok: bool, detail) -> None:
        checks.append({"check": name, "state": "PASS" if ok else "FAIL", "detail": detail})
        if not ok:
            failures.append(name)

    # ---- 1. base identity ------------------------------------------------
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              check=True).stdout.strip()

    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    head = git("rev-parse", "HEAD")
    check("base_branch_is_the_session_branch", branch == "arena/01a10add-ag-edgelab", branch)
    # New V2 files are expected; what must not happen is a modification or
    # deletion of anything already tracked -- V1 is closed evidence.
    dirty = [ln for ln in git("status", "--porcelain").splitlines()
             if not ln.startswith("??")]
    check("no_tracked_file_modified_v1_is_closed_evidence", not dirty, dirty or "clean")
    subject = git("log", "-1", "--format=%s")
    check("head_is_the_mission_2_final_commit",
          subject.startswith("GEN2 ALD V1 multi-year: emit the FINAL RETURN"),
          {"head": head, "subject": subject})

    # ---- 2. V1 evidence integrity ---------------------------------------
    check("v1_frozen_rule_hash_unchanged", STRATEGY_HASH == V1_EXPECTED_RULE_HASH, STRATEGY_HASH)

    bad = []
    for bundle in (V1_MY, V1_17):
        manifest_path = bundle / "artifact_manifest.json"
        if not manifest_path.exists():
            bad.append(f"{bundle}: no manifest")
            continue
        manifest = json.loads(manifest_path.read_text())
        for name, meta in manifest["files"].items():
            path = bundle / name
            if not path.exists():
                bad.append(f"{bundle}/{name}: missing")
            elif sha256_file(path) != meta["sha256"]:
                bad.append(f"{bundle}/{name}: sha256 drift")
    check("v1_evidence_bundles_hash_clean", not bad, bad or "all files match their manifests")

    fr = json.loads((V1_MY / "final_return.json").read_text())
    block = fr["FINAL_RETURN"]
    check("v1_final_return_is_the_closed_verdict",
          block["STATUS"] == "MULTIYEAR_DEV_INSUFFICIENT_SAMPLE"
          and block["NEXT"] == "NEW_V2_HYPOTHESIS_DESIGN"
          and block["ENTRY_AVAILABLE_N"] == 35
          and block["FROZEN_CANDIDATE"] == "NO",
          {k: block[k] for k in ("STATUS", "NEXT", "ENTRY_AVAILABLE_N", "FROZEN_CANDIDATE")})
    check("v1_final_return_sources_unmodified",
          all(sha256_file(V1_MY / n) == h for n, h in fr["derived_from"].items()),
          fr["derived_from"])

    # ---- 3. contamination registry --------------------------------------
    registry = json.loads((GOV / "candidate_contamination_registry.json").read_text())
    family = [r for r in registry["records"] if r["candidate_family_id"] == CANDIDATE_FAMILY_ID]
    dev_years = sorted({int(r["start"][:4]) for r in family})
    corpus_years = sorted({y for _, y in admitted_symbol_years()})
    check("every_dev_year_is_registered_development_known",
          dev_years == corpus_years and all(
              r["reuse_policy"] == "DEVELOPMENT_KNOWN" for r in family),
          {"registered": dev_years, "corpus": corpus_years, "records": len(family)})
    leaking = [r for r in family if not (r["start"].endswith("-01-01T00:00:00Z")
                                         and r["end"].endswith("-09-01T00:00:00Z"))]
    check("no_contamination_record_extends_past_september", not leaking,
          leaking or "every record is exactly [Y-01-01, Y-09-01)")

    # ---- 4. OOS freshness under the R2 authority ------------------------
    log = json.loads((GOV / "oos_access_log.json").read_text())
    r2_events = [e for e in log["events"] if e.get("dataset") == AUTHORITY_ID
                 or e.get("dataset_authority") == AUTHORITY_ID]
    check("zero_oos_access_events_under_the_r2_authority", not r2_events, r2_events or 0)
    check("r2_dataset_registered_as_unconsumed",
          "NEVER OPENED" in log["dataset_registry"][AUTHORITY_ID]["oos_consumption_status"],
          log["dataset_registry"][AUTHORITY_ID]["oos_consumption_status"][:120])
    family_oos = [e for e in log["events"]
                  if CANDIDATE_FAMILY_ID in json.dumps(e)]
    check("no_oos_event_belongs_to_this_candidate_family", not family_oos, family_oos or 0)

    # ---- 5. sealed holdout ----------------------------------------------
    blob = json.dumps(log) + json.dumps(registry)
    touched = [tok for tok in ("HOLDOUT_OPENED", "holdout_consumed", "SEALED_HOLDOUT_ACCESS")
               if tok in blob]
    check("sealed_holdout_untouched", not touched, touched or "no holdout access token present")
    gap = json.loads((GOV / "data_authority_gap.json").read_text())
    partitions = gap["multi_year_authority_r2"]["partitions_utc"]
    check("r2_partition_policy_still_reserves_oos_and_holdout",
          "FRESH, NEVER OPENED" in partitions["OOS"] and "SEALED" in partitions["SEALED_HOLDOUT"],
          partitions)

    # ---- report ----------------------------------------------------------
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "phase": "MISSION_3_PHASE_0_GOVERNANCE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_commit": head,
        "state": "FAIL" if failures else "PASS",
        "failures": failures,
        "checks": checks,
        "v1_closed_evidence": {
            "strategy_hash": STRATEGY_HASH,
            "final_return": {k: block[k] for k in (
                "OPPORTUNITY_N", "TRIGGER_PASS_N", "CONFIRMATION_PASS_N", "ENTRY_AVAILABLE_N",
                "1R", "5R", "NATURAL_TARGET_MEDIAN_R", "SAMPLE_CLASSIFICATION",
                "SECONDARY_DIAGNOSES", "STATUS")},
            "immutability_rule": "V1 is closed evidence. Mission 3 may read it and must not "
                                 "modify, re-run, re-tune or re-interpret it.",
        },
    }
    (OUT / "phase0_governance_verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")

    for c in checks:
        print(f"{c['state']:4}  {c['check']}")
    print(f"\nPHASE_0 = {report['state']}")
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
