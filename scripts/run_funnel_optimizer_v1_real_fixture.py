#!/usr/bin/env python3
"""Run Funnel Optimizer V1 R2 on the registered real FX DEVELOPMENT fixture.

Owner policy for this mission is encoded here and in the generated evidence:
FIXED_REFERENCE_2R_V1, 1000 matched seeded baselines, STRUCTURAL eligibility,
and no friction scenario.  The producer refuses any role other than
DEVELOPMENT; it never opens OOS or holdout data and has no broker dependency.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.data.fingerprint import sha256_file, sha256_json  # noqa: E402
from ag_edgelab.optimization.funnel_optimizer import (AblationStatus, RandomBaselineConfig,
                                                       structural_parent_eligibility,
                                                       leave_one_out, stage_diagnostics)
from ag_edgelab.strategies.asian_liquidity_displacement_v2_real_fixture import (  # noqa: E402
    REFERENCE_MODEL_ID, produce_real_fixture, production_summary,
)

OUT = ROOT / "artifacts" / "funnel_optimizer_v1_real_fixture_r2"
PREREGISTRATION = ROOT / "config" / "governance" / "funnel_optimizer_v1_fixture_preregistration.json"
RANDOM_BASELINE_COUNT = 1000


def _seed(preregistration: dict) -> int:
    """Stable seed derived from immutable campaign inputs, not a tuned value."""
    digest = sha256_json({
        "campaign": "FUNNEL_OPTIMIZER_V1_REAL_FIXTURE_R2",
        "dataset_sha256": preregistration["materialization"]["dataset_sha256"],
        "random_baseline_count": RANDOM_BASELINE_COUNT,
        "reference_model": REFERENCE_MODEL_ID,
        "seed_contract": "SHA256_PREFIX_64_V1",
    })
    return int(digest[:16], 16)


def _diagnostic_json(diagnostics):
    return [{
        "rule_id": item.rule_id,
        "pass_expectancy_r": item.pass_expectancy_r,
        "fail_expectancy_r": item.fail_expectancy_r,
        "selection_delta_r": item.selection_delta_r,
        "n_pass": item.n_pass,
        "n_fail": item.n_fail,
        "n_not_evaluable": item.n_not_evaluable,
        "n_reference_not_evaluable": item.n_reference_not_evaluable,
    } for item in diagnostics]


def main(argv: list[str] | None = None) -> int:
    verify_determinism = "--skip-second-run" not in (argv or sys.argv[1:])
    OUT.mkdir(parents=True, exist_ok=True)
    preregistration = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    production = produce_real_fixture(preregistration_path=PREREGISTRATION, root=ROOT)
    summary = production_summary(production)
    if verify_determinism:
        independent = produce_real_fixture(preregistration_path=PREREGISTRATION, root=ROOT)
        if production.table.sha256 != independent.table.sha256:
            raise RuntimeError("real event table hash is non-deterministic")
        determinism = {
            "independent_runs": 2,
            "event_table_sha256_match": True,
            "event_table_sha256": production.table.sha256,
        }
    else:
        determinism = {"independent_runs": 1, "event_table_sha256_match": None,
                       "event_table_sha256": production.table.sha256}

    event_path, event_manifest = production.table.write_cache(OUT / "real_development_event_table.jsonl")
    seed = _seed(preregistration)
    eligibility = structural_parent_eligibility(
        production.table,
        baseline=RandomBaselineConfig(
            count=RANDOM_BASELINE_COUNT,
            seed=seed,
            authority_id="OWNER_POLICY_FUNNEL_OPTIMIZER_V1_REAL_FIXTURE_R2",
        ),
    )
    diagnostics = stage_diagnostics(production.table)
    ablations = leave_one_out(production.table)
    valid = [item for item in ablations if item.status is AblationStatus.VALID]
    # All current ALD V2 stages are explicitly structural/path-dependent.
    # Therefore no fast child is legal, even though structural eligibility
    # passed.  No trial is silently recorded for a non-evaluated child.
    child_optimization_started = False
    real_trial_count = 0

    evidence = {
        "schema_version": "FUNNEL_OPTIMIZER_V1_REAL_FIXTURE_R2",
        "reference_model": REFERENCE_MODEL_ID,
        "owner_policy": {
            "random_baseline_count": RANDOM_BASELINE_COUNT,
            "baseline_seed": seed,
            "baseline_seed_contract": "SHA256_PREFIX_64_V1 over immutable campaign inputs",
            "eligibility_mode": "STRUCTURAL",
            "friction_scenario": "UNRESOLVED",
            "economic_ranking": "BLOCKED",
            "campaign_search_budget": 100,
        },
        "fixture": {
            "symbols": preregistration["symbols"],
            "years": preregistration["years"],
            "data_role": preregistration["data_role"],
            "dataset_sha256": preregistration["materialization"]["dataset_sha256"],
            "preregistration_sha256": sha256_file(PREREGISTRATION),
        },
        "event_table": summary | {
            "event_table_jsonl": event_path.relative_to(ROOT).as_posix(),
            "event_table_manifest": event_manifest.relative_to(ROOT).as_posix(),
        },
        "determinism": determinism,
        "eligibility": {
            "verdict": ("STRUCTURAL_ELIGIBILITY_PASS" if eligibility.verdict.value == "PASS"
                        else "STRUCTURAL_ELIGIBILITY_FAIL" if eligibility.verdict.value == "FAIL"
                        else eligibility.verdict.value),
            "campaign_state": eligibility.campaign_state.value,
            "parent_expectancy_r": eligibility.parent_metrics.reference_expectancy_r,
            "baseline_mean_r": eligibility.baseline_mean_expectancy_r,
            "baseline_median_r": eligibility.baseline_median_r,
            "baseline_p05_r": eligibility.baseline_p05_r,
            "baseline_p95_r": eligibility.baseline_p95_r,
            "parent_percentile": eligibility.parent_percentile,
            "sample_n": eligibility.sample_n,
            "baseline_count": eligibility.baseline_count,
            "selection_delta_r": eligibility.selection_delta_r,
            "reason_code": eligibility.reason_code,
        },
        "attribution": {
            "stage_diagnostics": _diagnostic_json(diagnostics),
            "leave_one_out": [{
                "rule_id": item.rule_id,
                "status": item.status.value,
                "reason_code": item.reason_code,
                "expectancy_delta_vs_full_r": item.expectancy_delta_vs_full_r,
            } for item in ablations],
            "valid_ablations": len(valid),
            "requires_full_replay_count": sum(item.status is AblationStatus.REQUIRES_FULL_REPLAY
                                                for item in ablations),
        },
        "child_optimization": {
            "started": child_optimization_started,
            "real_trial_count": real_trial_count,
            "reason": "NO_TABLE_QUERY_SAFE_ALD_V2_RULES",
        },
        "governance": {
            "oos_accessed": False,
            "holdout_accessed": False,
            "broker_mutation": False,
            "edge_verified_issued": False,
        },
    }
    evidence["evidence_sha256"] = sha256_json(evidence)
    evidence_path = OUT / "real_fixture_acceptance_evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "event_table_sha256": production.table.sha256,
        "rows": summary["rows"],
        "reference_outcome_rows": summary["reference_outcome_rows"],
        "eligibility": evidence["eligibility"],
        "evidence_path": evidence_path.relative_to(ROOT).as_posix(),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
