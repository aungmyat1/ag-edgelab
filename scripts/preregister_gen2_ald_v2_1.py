#!/usr/bin/env python
"""MISSION 3A PHASE 10 — freeze the 2.1.0 preregistration.

Refuses to run if any performance artifact for this experiment already
exists: the preregistration must precede the replay, never rationalise it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ag_edgelab.strategies import asian_liquidity_displacement_v2_1 as V
from ag_edgelab.strategies import asian_liquidity_displacement_v2_1_prereg as P

OUT = Path("data/artifacts/gen2_ald_v2_1")
RESULT_ARTIFACTS = (
    "final_report.json", "funnel_report.json", "v1_vs_v2.json",
    "pre_oos_gate_result.json", "target_capability.json",
    "attrition_reasons.json", "branch_report.json", "strata_report.json",
    "sample_gate.json",
)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    present = [n for n in RESULT_ARTIFACTS if (OUT / n).exists()]
    if present:
        print(f"REFUSING: performance artifacts already exist: {present}",
              file=sys.stderr)
        print("A preregistration may not be written after its own results.",
              file=sys.stderr)
        return 2

    # Identity must be internally consistent before anything is frozen.
    assert V.contract_hash() == V.CONTRACT_HASH, "contract hash drifted at import"
    assert V.STRATEGY_ID not in V.FORBIDDEN_IDENTITY_REUSE
    assert V.EDGE_VERIFIED is False
    assert V.ECONOMIC_EDGE == "NOT_ESTIMABLE"
    assert len(list(V.Branch)) == 2, "exactly two branches"

    prereg = P.preregistration()
    assert prereg["results_present"] is False
    assert prereg["replay_started"] is False

    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()

    payload = dict(prereg)
    payload["frozen_at_utc"] = datetime.now(timezone.utc).isoformat()
    payload["base_commit"] = head

    (OUT / "preregistration.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n")

    identity = {
        "strategy_id": V.STRATEGY_ID,
        "strategy_version": V.STRATEGY_VERSION,
        "experiment_id": P.EXPERIMENT_ID,
        "contract_hash": V.contract_hash(),
        "contract_section_hashes": V.contract_hashes(),
        "preregistration_hash": P.preregistration_hash(),
        "dataset_binding_hash": P.dataset_binding_hash(),
        "implementation_sha": V.contract_hash(),
        "supersedes": V.SUPERSEDES,
        "superseded_evidence": V.SUPERSEDED_EVIDENCE,
        "look_index": V.LOOK_INDEX,
        "edge_verified": V.EDGE_VERIFIED,
        "economic_edge": V.ECONOMIC_EDGE,
        "oos_opened": "NO",
        "holdout_touched": "NO",
        "replay_started": False,
    }
    (OUT / "candidate_instance_identity.json").write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n")

    print(json.dumps({
        "EXPERIMENT_ID": P.EXPERIMENT_ID,
        "CONTRACT_HASH": V.contract_hash(),
        "PREREGISTRATION_HASH": P.preregistration_hash(),
        "DATASET_BINDING_HASH": P.dataset_binding_hash(),
        "SAMPLE_FLOOR": P.SAMPLE_FLOOR,
        "BRANCH_MIN_N": P.BRANCH_MIN_N,
        "LOOK_INDEX": V.LOOK_INDEX,
        "RESULTS_PRESENT": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
