#!/usr/bin/env python3
"""Freeze PRE_OOS_ROBUSTNESS_CONTRACT_V1 to artifacts/preregistration.json.

Run and COMMIT this before the gate is pointed at any candidate evidence.
The commit that writes ``preregistration.json`` must precede the commit
that writes any result, so that "the thresholds were fixed first" is a
checkable property of the git history rather than a claim in a report.

The contract contains no candidate-specific value and reads no candidate
evidence, so this script is safe to re-run; it is byte-stable.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.verification.pre_oos.contract import (  # noqa: E402
    FROZEN_CONTRACT,
)
from ag_edgelab.verification.pre_oos.regime import (  # noqa: E402
    classifier_fingerprint,
)

OUT_DIR = ROOT / "artifacts" / "pre_oos_robustness_gate_v1"


def build() -> dict:
    return {
        "preregistration_version": "PRE_OOS_ROBUSTNESS_PREREGISTRATION_V1",
        "frozen_at_utc": "2026-10-05T00:00:00Z",
        "mission": "EDGELAB_PRE_OOS_ROBUSTNESS_GATE_V1",
        "purpose": (
            "Decide whether a frozen candidate's DEVELOPMENT evidence is "
            "distributed, stable and reproducible enough to justify spending "
            "one fresh OOS window. This is an authorization decision, not an "
            "edge verdict."),
        "contract": FROZEN_CONTRACT.as_dict(),
        "regime_classifier": classifier_fingerprint(),
        "calibration_policy": {
            "calibrated_against_candidate_results": False,
            "calibrated_against_c3_oos_result": False,
            "statement": (
                "No threshold in this contract was selected by observing a "
                "candidate's outcome. The C3 negative control is executed "
                "only AFTER this file is committed, and the contract is not "
                "amended afterwards regardless of whether the gate's verdict "
                "agrees with C3's known OOS rejection. Agreement is weak "
                "evidence the gate works; disagreement is reported as-is."),
            "disclosure": (
                "Before freezing, the agent observed STRUCTURAL metadata of "
                "the C3 DEV evidence (its window is 2017-01-01 to 2017-09-01, "
                "i.e. a single calendar year) from dev_accounting.json. That "
                "is schema-level metadata, not an outcome. The "
                "MIN_DISTINCT_YEARS=3 rule is justified by the construction "
                "of the leave-one-year-out test itself — with two years, "
                "removing one leaves a single year and the comparison is "
                "tautological — and would hold for any candidate. No R "
                "distribution, mean, median or verdict was inspected before "
                "this contract was frozen and committed."),
        },
        "oos_policy": {
            "gate_reads_oos": False,
            "gate_reads_holdout": False,
            "statement": (
                "The gate decides using DEVELOPMENT and DEVELOPMENT_KNOWN "
                "observations only. Reading OOS to decide whether to read OOS "
                "would consume the thing the decision is about."),
        },
        "decisions": ["PRE_OOS_PASS", "PRE_OOS_FAIL", "INSUFFICIENT_EVIDENCE",
                      "NOT_EVALUATED"],
        "pass_semantics": (
            "PRE_OOS_PASS means only that spending one fresh OOS window is "
            "justified. It does NOT mean profitable, economically verified, "
            "or EDGE_VERIFIED."),
        "taxonomy": [
            "INSUFFICIENT_SAMPLE", "DATASET_ROLE_VIOLATION",
            "CANDIDATE_IDENTITY_INVALID", "TEMPORAL_CAUSALITY_FAILURE",
            "WALK_FORWARD_INSTABILITY", "YEAR_DEPENDENCY", "SYMBOL_DEPENDENCY",
            "REGIME_DEPENDENCY", "TAIL_DEPENDENCY",
            "ASYMMETRIC_TAIL_DEPENDENCE", "STATISTICAL_UNCERTAINTY",
            "PARAMETER_FRAGILITY", "FRICTION_AUTHORITY_INCOMPLETE",
            "ROBUSTNESS_SUPPORTED",
        ],
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = build()
    path = OUT_DIR / "preregistration.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {path}")
    print(f"CONTRACT_SHA256 = {payload['contract']['CONTRACT_SHA256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
