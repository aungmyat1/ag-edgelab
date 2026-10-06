#!/usr/bin/env python3
"""Generate machine-readable acceptance evidence for Funnel Optimizer V1.

The emitted event table is a deterministic *synthetic negative* proof of the
optimizer contracts.  It does not replay the materialized FX fixture because
REFERENCE_OUTCOME_MODEL and RANDOM_BASELINE_COUNT remain owner decisions.  No
OOS, sealed holdout, broker, or strategy-source access is performed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.data.fingerprint import sha256_file, sha256_json  # noqa: E402
from ag_edgelab.optimization.funnel_optimizer import (CampaignLedger, ChildStatus,
                                                       FastChildEngine, RandomBaselineConfig,
                                                       RuleState, leave_one_out,
                                                       stage_diagnostics,
                                                       structural_parent_eligibility)
from ag_edgelab.optimization.synthetic_fixture import SYNTHETIC_FIXTURE_ID, build_event_table  # noqa: E402

FROZEN_ALD_V2_SHA256 = "883e9095977cd25840201f5b2b3d5ce6e67b350c1157f30045654dbd13904920"


def main() -> int:
    output = ROOT / "artifacts" / "funnel_optimizer_v1"
    output.mkdir(parents=True, exist_ok=True)
    table = build_event_table()
    event_path, event_manifest = table.write_cache(output / "synthetic_negative_event_table.jsonl")

    diagnostics = stage_diagnostics(table)
    ablations = leave_one_out(table)
    real_fixture_gate = structural_parent_eligibility(table, baseline=None)
    synthetic_negative_proof = structural_parent_eligibility(
        table,
        baseline=RandomBaselineConfig(count=32, seed=17, synthetic_test_only=True),
        permit_synthetic_test=True,
    )

    # This is deliberately a separate mechanism proof, not an optimization
    # continuation of the terminally rejected negative parent fixture.
    child_engine = FastChildEngine(
        table,
        parent_id="SYNTHETIC_MECHANISM_PROOF_PARENT",
        campaign_id="FUNNEL_OPTIMIZER_V1_MECHANISM_PROOF",
        strategy_funnel_identity="SYNTHETIC_FUNNEL_MECHANISM_ID_V1",
    )
    ledger = CampaignLedger("FUNNEL_OPTIMIZER_V1_MECHANISM_PROOF")
    threshold_child = child_engine.change_threshold(
        rule_id="BODY_RATIO", old_value=0.6, new_value=0.8)
    structural_child = child_engine.remove_rule(rule_id="SWEEP")
    ledger.append(threshold_child)
    ledger.append(structural_child)
    ledger_path = ledger.write_jsonl(output / "mechanism_proof_campaign_ledger.jsonl")

    preregistration_path = ROOT / "config/governance/funnel_optimizer_v1_fixture_preregistration.json"
    preregistration = json.loads(preregistration_path.read_text(encoding="utf-8"))
    frozen_path = ROOT / "src/ag_edgelab/strategies/asian_liquidity_displacement_v2.py"
    frozen_actual = sha256_file(frozen_path)
    if frozen_actual != FROZEN_ALD_V2_SHA256:
        raise RuntimeError("frozen ALD V2 source changed; refusing acceptance artifact")

    counts = {state.value: 0 for state in RuleState}
    for row in table.rows:
        for cell in row.rule_cells.values():
            counts[cell.state.value] += 1

    evidence = {
        "acceptance_schema_version": "FUNNEL_OPTIMIZER_V1_ACCEPTANCE_V1",
        "artifacts": {
            "event_table_jsonl": event_path.relative_to(ROOT).as_posix(),
            "event_table_manifest": event_manifest.relative_to(ROOT).as_posix(),
            "mechanism_campaign_ledger": ledger_path.relative_to(ROOT).as_posix(),
            "preflight": "artifacts/funnel_optimizer_v1/preflight.json",
        },
        "campaign": {
            "mechanism_proof_only": True,
            "trial_count": ledger.trial_count,
            "trial_count_monotonic": [entry.trial_number for entry in ledger.entries] == [1, 2],
            "child_statuses": [entry.status.value for entry in ledger.entries],
        },
        "data_fixture": {
            "event_table_fixture": SYNTHETIC_FIXTURE_ID,
            "event_table_is_market_evidence": False,
            "materialized_fx_preregistration": preregistration,
            "real_replay_blockers": preregistration["owner_decisions_unresolved"],
        },
        "event_table": {
            "actual_trade_rows": sum(row.actual_trade for row in table.rows),
            "event_rows": len(table.rows),
            "reference_outcome_rows": sum(row.reference_outcome_r is not None for row in table.rows),
            "rule_cells": counts,
            "sha256": table.sha256,
        },
        "frozen_strategy": {
            "path": frozen_path.relative_to(ROOT).as_posix(),
            "sha256": frozen_actual,
            "unchanged": True,
        },
        "governance": {
            "broker_mutation": False,
            "edge_verified_issued": False,
            "holdout_accessed": False,
            "oos_accessed": False,
            "outcome_models_separate": True,
        },
        "eligibility": {
            "eligibility_mode": real_fixture_gate.mode.value,
            "economic_ranking": "BLOCKED",
            "real_fixture_gate": {
                "reason_code": real_fixture_gate.reason_code,
                "verdict": real_fixture_gate.verdict.value,
            },
            "synthetic_negative_proof": {
                "baseline_count": synthetic_negative_proof.baseline_count,
                "campaign_state": synthetic_negative_proof.campaign_state.value,
                "selection_delta_r": synthetic_negative_proof.selection_delta_r,
                "verdict": synthetic_negative_proof.verdict.value,
            },
        },
        "attribution": {
            "leave_one_out": [
                {
                    "expectancy_delta_vs_full_r": item.expectancy_delta_vs_full_r,
                    "reason_code": item.reason_code,
                    "rule_id": item.rule_id,
                    "status": item.status.value,
                }
                for item in ablations
            ],
            "stage_diagnostics": [
                {
                    "fail_expectancy_r": item.fail_expectancy_r,
                    "n_fail": item.n_fail,
                    "n_not_evaluable": item.n_not_evaluable,
                    "n_pass": item.n_pass,
                    "pass_expectancy_r": item.pass_expectancy_r,
                    "rule_id": item.rule_id,
                    "selection_delta_r": item.selection_delta_r,
                }
                for item in diagnostics
            ],
        },
    }
    evidence["evidence_sha256"] = sha256_json(evidence)
    evidence_path = output / "acceptance_evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"acceptance evidence: {evidence_path.relative_to(ROOT)}")
    print(f"event table sha256: {table.sha256}")
    print(f"evidence sha256: {evidence['evidence_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
