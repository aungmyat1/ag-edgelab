#!/usr/bin/env python3
"""Produce append-only R3 gate evidence; never runs child optimization."""

from __future__ import annotations

import json
import random
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.data.fingerprint import sha256_file, sha256_json  # noqa: E402
from ag_edgelab.optimization.eligibility_r3 import (  # noqa: E402
    R3EligibilityPolicy, R3EligibilityVerdict, evaluate_parent_r3,
)
from ag_edgelab.optimization.reference_outcome_v2 import (  # noqa: E402
    REFERENCE_MODEL_ID, ReferenceDirectionMode, ReferenceOutcomeV2Config,
    evaluate_reference_outcome_v2,
)
from ag_edgelab.strategies.asian_liquidity_displacement_v2_real_fixture import (  # noqa: E402
    produce_real_fixture, production_summary,
)

PREREG = ROOT / "config/governance/funnel_optimizer_v1_fixture_preregistration.json"
POLICY_PATH = ROOT / "config/governance/funnel_optimizer_v1_r3_proposed_policy.json"
R2_EVIDENCE = ROOT / "artifacts/funnel_optimizer_v1_real_fixture_r2/real_fixture_acceptance_evidence.json"
OUT = ROOT / "artifacts/funnel_optimizer_v1_r3_gate_repair"
FROZEN_ALD = ROOT / "src/ag_edgelab/strategies/asian_liquidity_displacement_v2.py"
FROZEN_ALD_SHA256 = "883e9095977cd25840201f5b2b3d5ce6e67b350c1157f30045654dbd13904920"


def _null_controls(policy: R3EligibilityPolicy) -> dict[str, object]:
    rng = random.Random(99117)
    outcomes = [rng.choice((-1.0, .5, .5)) for _ in range(1000)]
    selected_set = set(random.Random(11).sample(range(1000), 900))
    subsample = evaluate_parent_r3(outcomes, [i in selected_set for i in range(1000)], policy=policy)
    replicates, pass_count = 40, 0
    for seed in range(replicates):
        selector = random.Random(f"null-parent:{seed}")
        selected = [selector.random() < .25 for _ in outcomes]
        replicate_policy = R3EligibilityPolicy(
            min_reference_coverage=policy.min_reference_coverage,
            min_parent_percentile=policy.min_parent_percentile,
            min_parent_n=policy.min_parent_n,
            min_baseline_universe_n=policy.min_baseline_universe_n,
            n_bootstrap=300,
            rng_seed=8000 + seed,
        )
        pass_count += evaluate_parent_r3(outcomes, selected, policy=replicate_policy).verdict is R3EligibilityVerdict.PASS
    planted_selection = [value == .5 and index % 2 == 0 for index, value in enumerate(outcomes)]
    planted = evaluate_parent_r3(outcomes, planted_selection, policy=policy)
    low = evaluate_parent_r3([.5] * 12 + [None] * 88, [True] * 100, policy=policy)
    return {
        "SUBSAMPLE_NULL_PARENT": subsample.verdict.value,
        "RANDOM_RULE_PARENT": {
            "replicates": replicates,
            "pass_count": pass_count,
            "pass_rate": pass_count / replicates,
        },
        "PLANTED_SIGNAL_PARENT": planted.verdict.value,
        "LOW_REFERENCE_COVERAGE_PARENT": low.verdict.value,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    prereg = json.loads(PREREG.read_text())
    proposed = json.loads(POLICY_PATH.read_text())
    production = produce_real_fixture(preregistration_path=PREREG, root=ROOT)
    r2_summary = production_summary(production)
    r2_evidence = json.loads(R2_EVIDENCE.read_text())
    expected_r2_hash = r2_evidence["event_table"]["event_table_sha256"]
    if r2_summary["event_table_sha256"] != expected_r2_hash:
        raise RuntimeError("historical R2 reproduction mismatch; R3 evidence refused")

    reference_config = ReferenceOutcomeV2Config(
        direction_mode=ReferenceDirectionMode.BOTH_DIRECTIONS_SYMMETRIC,
        atr_period=proposed["reference_model"]["atr_period_m5_bars"],
        stop_atr_multiple=proposed["reference_model"]["stop_atr_multiple"],
        target_r=proposed["reference_model"]["target_r"],
        max_holding_bars=proposed["reference_model"]["max_holding_m5_bars"],
        rng_seed=proposed["resampling"]["rng_seed"],
    )
    outcomes: list[float | None] = []
    reasons: dict[str, int] = {}
    for row in production.table.rows:
        bars = production.frames[(row.symbol, row.timestamp_utc.year)].frames["M5"]
        outcome = evaluate_reference_outcome_v2(
            bars, row.timestamp_utc, event_id=row.event_id, config=reference_config)
        outcomes.append(outcome.outcome_r)
        reasons[outcome.exit_reason] = reasons.get(outcome.exit_reason, 0) + 1

    policy = R3EligibilityPolicy(
        min_reference_coverage=proposed["eligibility"]["minimum_reference_coverage"],
        min_parent_percentile=proposed["eligibility"]["parent_percentile_threshold"],
        min_parent_n=proposed["eligibility"]["minimum_parent_n"],
        min_baseline_universe_n=proposed["eligibility"]["minimum_baseline_universe_n"],
        n_bootstrap=proposed["resampling"]["bootstrap_count"],
        rng_seed=proposed["resampling"]["rng_seed"],
    )
    result = evaluate_parent_r3(outcomes, [row.all_rules_pass for row in production.table.rows], policy=policy)
    archives = []
    for item in prereg["materialization"]["files"]:
        path = ROOT / item["path"]
        actual = sha256_file(path)
        archives.append({
            "symbol": item["symbol"], "year": item["year"], "filename": path.name,
            "source": prereg["materialization"]["source"], "byte_count": path.stat().st_size,
            "sha256": actual, "expected_sha256": item["sha256"], "match": actual == item["sha256"],
            "dataset_role": "DEVELOPMENT_ONLY",
        })
    if len(archives) != 6 or not all(item["match"] for item in archives):
        raise RuntimeError("six hash-verified archives required")
    if sha256_file(FROZEN_ALD) != FROZEN_ALD_SHA256:
        raise RuntimeError("frozen ALD V2 changed")

    evidence = {
        "schema_version": "FUNNEL_OPTIMIZER_V1_R3_GATE_REPAIR",
        "status": "SUPERSEDING_ELIGIBILITY_EVIDENCE",
        "historical_r2": {
            "artifact_unchanged": True,
            "event_rows": r2_summary["rows"],
            "event_hash": r2_summary["event_table_sha256"],
            "rule_cells": r2_summary["rule_cells"],
            "eligibility_verdict": "STRUCTURAL_ELIGIBILITY_PASS",
            "eligibility_result": r2_evidence["eligibility"],
            "limitation": "weak eligibility criterion + overlapping baseline universe + insufficient reference coverage",
            "reproduction_verdict": "MATCH",
        },
        "archives": archives,
        "partition_boundary": {
            "data_role": "DEVELOPMENT_ONLY",
            "oos_rows_parsed": sum(v["oos_or_holdout_rows_parsed"] for v in r2_summary["frame_quality"].values()),
            "holdout_rows_parsed": 0,
            "development_windows": "[YYYY-01-01T00:00:00Z, YYYY-09-01T00:00:00Z)",
        },
        "reference_model": {
            "model_id": REFERENCE_MODEL_ID,
            "status": "PROVISIONAL_NOT_AUTHORIZED",
            "direction_mode": "BOTH_DIRECTIONS_SYMMETRIC_PROVISIONAL",
            "direction_authorized": False,
            "friction": "UNKNOWN_SEPARATE_NOT_APPLIED",
            "config": asdict(reference_config),
            "exit_reason_counts": dict(sorted(reasons.items())),
        },
        "r3_eligibility": asdict(result),
        "baseline_nonzero_explanation": (
            "The symmetric 2R/1R path model is not algebraically zero: a directional move commonly yields "
            "+2R on one side and -1R on the other (symmetric average +0.5R), while two stopped sides yield "
            "-1R. The observed gross baseline therefore reflects range/path and timeout geometry, not strategy edge."
        ),
        "null_controls": _null_controls(policy),
        "authority": {
            "r3_supersedes_r2_eligibility_authority": True,
            "real_campaign_authorized": False,
            "edge_verified_issued": False,
            "child_optimization_run": False,
            "table_query_safe_ald_v2_children": 0,
            "oos_accessed": False,
            "holdout_accessed": False,
            "broker_mutation": False,
        },
        "frozen_ald_v2": {"sha256": sha256_file(FROZEN_ALD), "unchanged": True},
        "proposed_policy_sha256": sha256_file(POLICY_PATH),
    }
    evidence["evidence_sha256"] = sha256_json(evidence)
    destination = OUT / "acceptance_evidence.json"
    destination.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"artifact": destination.relative_to(ROOT).as_posix(),
                      "r2_hash": expected_r2_hash, "r3": asdict(result),
                      "null_controls": evidence["null_controls"]}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
