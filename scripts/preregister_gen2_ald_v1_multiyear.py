#!/usr/bin/env python
"""Preregister GEN2_ALD_V1_MULTIYEAR_DEV_R1 — BEFORE any multi-year result.

Writes preregistration.json, dataset_binding.json and
candidate_instance_identity.json, then stops.  Nothing in this script reads a
price bar or produces a funnel count: it exists so the contracts are committed
to git before the replay runs.

The only identity field that cannot be known here is ``dev_partition_hash``
(the hash of the derived DEV frames), which the runner fills in and which this
script pins indirectly through ``dataset_manifest_sha256`` plus the exact list
of permitted symbol-years.
"""
from __future__ import annotations

import json
from pathlib import Path

from ag_edgelab.data.fingerprint import sha256_file, sha256_json
from ag_edgelab.data.fx_histdata_multiyear import (
    admitted_symbol_years,
    authority_contract,
    load_manifest,
    manifest_path,
)
from ag_edgelab.strategies import asian_liquidity_displacement_multiyear as M

OUT = Path("data/artifacts/gen2_asian_liquidity_displacement_v1_multiyear")
DATA_AUTHORITY_GAP = Path("config/governance/data_authority_gap.json")
OOS_LOG = Path("config/governance/oos_access_log.json")
CONTAMINATION = Path("config/governance/candidate_contamination_registry.json")


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8")


def main() -> None:
    # Mission section 0 — hard stop unless the frozen rules reproduce exactly.
    identity = M.assert_rule_identity()
    print(f"RULE_IDENTITY={identity['state']} hash={identity['recomputed_strategy_hash']}")

    manifest = load_manifest()
    manifest_sha = sha256_file(manifest_path())

    prereg = M.preregistration()
    write_json(OUT / "preregistration.json", prereg)

    binding = {
        "binding_id": "GEN2_ALD_V1_MULTIYEAR_DEV_R1_DATASET_BINDING",
        "RULES_CHANGED": "NO",
        "DATASET_BINDING_CHANGED": "YES",
        "previous_binding": {
            "dataset_authority": "HISTDATA_ASCII_M1_2017_PR10_PINNED",
            "dev_window_utc": M.NARROW_CAMPAIGN["dev_window_utc"],
            "symbol_years": M.NARROW_CAMPAIGN["symbol_years"],
        },
        "new_binding": {
            "dataset_authority": authority_contract(),
            "dataset_manifest": str(manifest_path()),
            "dataset_manifest_sha256": manifest_sha,
            "permitted_symbol_years": [{"symbol": s, "year": y}
                                       for s, y in admitted_symbol_years()],
            "permitted_symbol_years_n": len(admitted_symbol_years()),
            "per_archive_identity": {k: {"zip_sha256": v["zip_sha256"],
                                         "inner_csv_sha256": v["inner_csv_sha256"],
                                         "inner_csv_bytes": v["inner_csv_bytes"]}
                                     for k, v in sorted(manifest["files"].items())},
        },
        "cross_source_identity_proof": manifest["cross_source_identity_proof"],
        "data_authority_discovery": M.data_authority_discovery(),
        "governance_inputs": {
            "data_authority_gap_sha256": sha256_file(DATA_AUTHORITY_GAP),
            "oos_access_log_sha256": sha256_file(OOS_LOG),
            "contamination_registry_sha256": sha256_file(CONTAMINATION),
        },
        "multi_year_data_authority_contract_compliance": {
            "source_provenance": "SATISFIED — provider, mirror, transport and retrieval method recorded",
            "raw_hashes": "SATISFIED — zip and inner-csv sha256 pinned for all 63 symbol-years before derivation",
            "timezone_normalization": "SATISFIED — inherited unchanged from the PR #10 loader contract",
            "gap_handling": "SATISFIED — frozen >=13/15 M15 rule and 0.75 MTF coverage; per-symbol-year gap inventory emitted by the runner",
            "duplicate_handling": "SATISFIED — zero tolerance; a failing symbol-year is excluded, never de-duplicated",
            "resampling": "SATISFIED — causal M1->M15->H1/H4/D1 via frozen code; per-frame hashes recorded",
            "partitioning": "SATISFIED — annual DEVELOPMENT/OOS/SEALED_HOLDOUT policy committed in this file before any candidate work",
        },
        "OOS_OPENED": "NO",
        "HOLDOUT_TOUCHED": "NO",
    }
    write_json(OUT / "dataset_binding.json", binding)

    instance = {
        "candidate_instance_id": M.EXPERIMENT_ID,
        "note": ("Strategy identity is UNCHANGED (no rule-version bump). This is a new "
                 "EXPERIMENT instance because the dataset partition changed."),
        "strategy_identity": {
            "strategy_id": M.STRATEGY_ID,
            "strategy_version": M.STRATEGY_VERSION,
            "strategy_hash": M.STRATEGY_HASH,
            "EXPECTED_RULE_HASH": M.EXPECTED_RULE_HASH,
            "rule_identity_check": identity,
        },
        "experiment_identity_preregistered": M.experiment_identity(
            dev_partition_hash="BOUND_AT_LOAD", dataset_manifest_sha256=manifest_sha),
        "preregistration_hash": prereg["preregistration_hash"],
        "preregistration_sha256_of_file": None,
    }
    write_json(OUT / "candidate_instance_identity.json", instance)
    instance["preregistration_sha256_of_file"] = sha256_file(OUT / "preregistration.json")
    write_json(OUT / "candidate_instance_identity.json", instance)

    print(json.dumps({
        "EXPERIMENT_ID": M.EXPERIMENT_ID,
        "PREREGISTRATION_HASH": prereg["preregistration_hash"],
        "DATASET_AUTHORITY": authority_contract()["authority_id"],
        "DATASET_MANIFEST_SHA256": manifest_sha,
        "PERMITTED_SYMBOL_YEARS": len(admitted_symbol_years()),
        "DEV_YEARS_N": len({y for _, y in admitted_symbol_years()}),
        "RULES_CHANGED": "NO",
        "DATASET_BINDING_CHANGED": "YES",
        "experiment_identity_sha256_preregistered":
            instance["experiment_identity_preregistered"]["experiment_identity_sha256"],
    }, indent=2))
    print("\nPREREGISTERED — commit this before running the replay.")


if __name__ == "__main__":
    main()
