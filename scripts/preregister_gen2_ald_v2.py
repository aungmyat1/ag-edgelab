#!/usr/bin/env python
"""MISSION 3 PHASE 3 — write and freeze the V2 preregistration.

Run ONCE, commit the result, and only then replay. Refuses to run if any V2
result artifact already exists.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ag_edgelab.data.fingerprint import sha256_file, sha256_json
from ag_edgelab.data.fx_histdata_multiyear import (
    AUTHORITY_ID,
    COVERAGE,
    PARTITION_POLICY_ID,
    admitted_symbol_years,
    manifest_path,
    partition_bounds,
)
from ag_edgelab.strategies import asian_liquidity_displacement_v2 as V2
from ag_edgelab.strategies import asian_liquidity_displacement_v2_prereg as P

OUT = Path("data/artifacts/gen2_asian_liquidity_displacement_v2")
GOV = Path("config/governance")
RESULT_ARTIFACTS = ("final_report.json", "funnel_report.json", "final_return.json")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in RESULT_ARTIFACTS:
        if (OUT / name).exists():
            print(f"REFUSING: {name} already exists — preregistration must precede results")
            return 2

    phase0 = json.loads((OUT / "phase0_governance_verification.json").read_text())
    if phase0["state"] != "PASS":
        print("REFUSING: phase 0 governance did not pass")
        return 2

    years = sorted({y for _, y in admitted_symbol_years()})
    registry = json.loads((GOV / "candidate_contamination_registry.json").read_text())
    known = {int(r["start"][:4]) for r in registry["records"]
             if r["candidate_family_id"] == V2.CANDIDATE_FAMILY_ID
             and r["reuse_policy"] == "DEVELOPMENT_KNOWN"}
    missing = [y for y in years if y not in known]
    if missing:
        print(f"REFUSING: years not registered DEVELOPMENT_KNOWN: {missing}")
        return 2

    dataset_authority = {
        "authority_id": AUTHORITY_ID,
        "partition_policy_id": PARTITION_POLICY_ID,
        "role": "DEVELOPMENT",
        "classification": "DEVELOPMENT_KNOWN for every window (registered by the V1 "
                          "multi-year campaign; re-use is deliberate and disclosed)",
        "dataset_manifest": str(manifest_path()),
        "dataset_manifest_sha256": sha256_file(manifest_path()),
        "symbol_years_n": len(admitted_symbol_years()),
        "years": years,
        "coverage": {s: list(v) for s, v in sorted(COVERAGE.items())},
        "dev_windows_utc": [[partition_bounds("DEVELOPMENT", y)[0].isoformat(),
                             partition_bounds("DEVELOPMENT", y)[1].isoformat()]
                            for y in years],
        "excluded": {
            "OOS [Y-09-01, Y-12-01)": "FRESH — never opened under this authority, and this "
                                      "mission does not open it",
            "SEALED_HOLDOUT [Y-12-01, Y+1-01-01)": "SEALED",
            "2018+": "NO_WHOLE_YEAR_ARCHIVE",
        },
        "dev_partition_hash": "BOUND_AT_LOAD",
    }

    head = git("rev-parse", "HEAD")
    payload = P.preregistration(
        implementation_sha=sha256_file(Path(V2.__file__)),
        base_commit=head,
        dataset_authority=dataset_authority,
    )
    digest = P.preregistration_hash(payload)
    payload_out = {
        "PREREGISTRATION_SHA256": digest,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    (OUT / "preregistration.json").write_text(
        json.dumps(payload_out, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    identity = {
        "experiment_id": P.EXPERIMENT_ID,
        "strategy_id": V2.STRATEGY_ID,
        "strategy_version": V2.STRATEGY_VERSION,
        "candidate_family_id": V2.CANDIDATE_FAMILY_ID,
        "strategy_hash": V2.STRATEGY_HASH,
        "strategy_contract_sha256": V2.contract_hashes()["strategy_contract_hash"],
        "preregistration_sha256": digest,
        "dataset_authority_id": AUTHORITY_ID,
        "dataset_manifest_sha256": dataset_authority["dataset_manifest_sha256"],
        "symbol_universe": list(V2.SYMBOL_UNIVERSE),
        "branches": list(V2.BRANCHES),
        "verifier_version": V2.VERIFIER_VERSION,
        "generation": 2,
        "supersedes": "none — V1 remains closed evidence and is not superseded, retuned "
                      "or re-run by this experiment",
        "rule_lineage": "NEW ARCHITECTURE. V2 shares V1's session clocks, data authority and "
                        "measurement contracts so the comparison is fair; it shares no trigger, "
                        "confirmation, entry or target rule.",
    }
    identity["experiment_identity_sha256"] = sha256_json(identity)
    (OUT / "candidate_instance_identity.json").write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"PREREGISTRATION_SHA256   = {digest}")
    print(f"STRATEGY_CONTRACT_SHA256 = {V2.STRATEGY_HASH}")
    print(f"EXPERIMENT_ID            = {P.EXPERIMENT_ID}")
    print(f"SAMPLE_FLOOR             = {P.SAMPLE_FLOOR}")
    print(f"symbol-years             = {dataset_authority['symbol_years_n']}")
    print("\nartifacts: preregistration.json, candidate_instance_identity.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
