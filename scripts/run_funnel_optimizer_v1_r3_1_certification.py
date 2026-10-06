#!/usr/bin/env python3
"""Generate superseding R3.1 clustered statistical-certification evidence."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.data.fingerprint import canonical_json, sha256_file, sha256_json  # noqa: E402
from ag_edgelab.optimization.eligibility_r3 import R3EligibilityPolicy, R3EligibilityVerdict  # noqa: E402
from ag_edgelab.optimization.eligibility_r3_1 import (  # noqa: E402
    DirectionalOpportunity, evaluate_parent_r3_1,
)
from ag_edgelab.optimization.reference_outcome_v2 import (  # noqa: E402
    ReferenceDirectionMode, ReferenceOutcomeV2Config, evaluate_reference_outcome_v2,
)
from ag_edgelab.optimization.statistical_controls_r3_1 import run_r3_1_controls  # noqa: E402
from ag_edgelab.strategies.asian_liquidity_displacement_v2_real_fixture import (  # noqa: E402
    produce_real_fixture, production_summary,
)

ORIGINAL_PR23_HEAD = "458b8fb13b21134ce26c247759e3544454fb712b"
ORIGINAL_R3 = ROOT / "artifacts/funnel_optimizer_v1_r3_gate_repair/acceptance_evidence.json"
R2 = ROOT / "artifacts/funnel_optimizer_v1_real_fixture_r2/real_fixture_acceptance_evidence.json"
PREREG = ROOT / "config/governance/funnel_optimizer_v1_fixture_preregistration.json"
POLICY_PATH = ROOT / "config/governance/funnel_optimizer_v1_r3_1_proposed_policy.json"
OUT = ROOT / "artifacts/funnel_optimizer_v1_r3_1_statistical_certification"
FROZEN_ALD = ROOT / "src/ag_edgelab/strategies/asian_liquidity_displacement_v2.py"
FROZEN_ALD_SHA256 = "883e9095977cd25840201f5b2b3d5ce6e67b350c1157f30045654dbd13904920"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    original_r3 = json.loads(ORIGINAL_R3.read_text())
    r2 = json.loads(R2.read_text())
    proposed = json.loads(POLICY_PATH.read_text())
    production = produce_real_fixture(preregistration_path=PREREG, root=ROOT)
    r2_reproduction = production_summary(production)
    if r2_reproduction["event_table_sha256"] != r2["event_table"]["event_table_sha256"]:
        raise RuntimeError("R2 reproduction changed; R3.1 evidence refused")
    if sha256_file(FROZEN_ALD) != FROZEN_ALD_SHA256:
        raise RuntimeError("frozen ALD V2 changed")

    reference_config = ReferenceOutcomeV2Config(
        direction_mode=ReferenceDirectionMode.BOTH_DIRECTIONS_SYMMETRIC,
        rng_seed=proposed["inference"]["bootstrap_seed"],
    )
    records: list[DirectionalOpportunity] = []
    exit_reasons: dict[str, int] = {}
    for row in production.table.rows:
        bars = production.frames[(row.symbol, row.timestamp_utc.year)].frames["M5"]
        outcome = evaluate_reference_outcome_v2(
            bars, row.timestamp_utc, event_id=row.event_id, config=reference_config)
        parent_unit = production.parent_units[row.event_id]
        direction = ({"BULL": "LONG", "BEAR": "SHORT"}.get(parent_unit.direction)
                     if row.all_rules_pass else None)
        record = DirectionalOpportunity(
            opportunity_id=row.event_id,
            timestamp_utc=row.timestamp_utc,
            symbol=row.symbol,
            year=row.timestamp_utc.year,
            session=row.session,
            long_outcome_r=outcome.long_outcome_r,
            short_outcome_r=outcome.short_outcome_r,
            parent_selected=row.all_rules_pass,
            parent_direction=direction,
        )
        records.append(record)
        exit_reasons[outcome.exit_reason] = exit_reasons.get(outcome.exit_reason, 0) + 1

    policy = R3EligibilityPolicy(
        min_reference_coverage=proposed["eligibility"]["minimum_reference_coverage"],
        min_parent_percentile=proposed["eligibility"]["parent_percentile_threshold"],
        min_parent_n=proposed["eligibility"]["minimum_parent_n"],
        min_baseline_universe_n=proposed["eligibility"]["minimum_baseline_universe_n"],
        n_bootstrap=proposed["inference"]["bootstrap_replicates"],
        rng_seed=proposed["inference"]["bootstrap_seed"],
    )
    result = evaluate_parent_r3_1(records, policy=policy)
    controls = run_r3_1_controls(bootstrap_replicates=200)

    legs_path = OUT / "directional_reference_legs.jsonl"
    with legs_path.open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(canonical_json({
                "opportunity_cluster_id": row.opportunity_id,
                "timestamp_utc": row.timestamp_utc.isoformat().replace("+00:00", "Z"),
                "symbol": row.symbol,
                "year": row.year,
                "session": row.session,
                "REFERENCE_LEG_LONG": row.long_outcome_r,
                "REFERENCE_LEG_SHORT": row.short_outcome_r,
                "parent_selected": row.parent_selected,
                "parent_direction": row.parent_direction,
                "parent_outcome_r": row.parent_outcome_r,
            }) + "\n")

    # ALD V2 unexpectedly passes the corrected directional estimand.  Per the
    # continuation contract this forces an adversarial-audit block even though
    # the permanent synthetic controls certify.
    unexpected_parent_pass = result.verdict is R3EligibilityVerdict.PASS
    gate_trustworthy = (
        not unexpected_parent_pass
        and controls.certification == "PASS"
        and result.reference_coverage >= policy.min_reference_coverage
        and result.parent_outcome_uses_declared_direction
        and result.direction_legs_stored_separately
        and result.bootstrap_method == "CLUSTER_BOOTSTRAP"
    )
    evidence = {
        "schema_version": "FUNNEL_OPTIMIZER_V1_R3_1_STATISTICAL_CERTIFICATION",
        "status": "ADVERSARIAL_AUDIT_REQUIRED" if unexpected_parent_pass else "CERTIFIED_DEV_DIAGNOSTIC",
        "lineage": {
            "R2": r2["event_table"]["event_table_sha256"],
            "R3_original_artifact_sha256": sha256_file(ORIGINAL_R3),
            "R3_original_verdict": original_r3["r3_eligibility"]["verdict"],
            "R3_original_gate_status": "PARTIAL_PROVISIONAL_NOT_CERTIFIED",
            "original_pr23_head": ORIGINAL_PR23_HEAD,
            "supersedes": "R3 eligibility statistical certification only",
        },
        "directional_reference_table": {
            "path": legs_path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(legs_path),
            "rows": len(records),
            "direction_legs": 2 * sum(row.both_legs_evaluable for row in records),
            "legs_stored_separately": True,
            "exit_reason_counts": dict(sorted(exit_reasons.items())),
        },
        "r3_1_eligibility": asdict(result),
        "null_controls": asdict(controls),
        "certification": {
            "r3_null_control_certification": controls.certification,
            "r3_gate_trustworthy": "TRUE_FOR_DEV_DIAGNOSTIC_USE" if gate_trustworthy else False,
            "unexpected_ald_v2_pass": unexpected_parent_pass,
            "independent_adversarial_review_required": unexpected_parent_pass,
            "real_campaign_authorized": False,
            "child_optimization_run": False,
            "edge_verified_issued": False,
        },
        "governance": {
            "data_role": "DEVELOPMENT_ONLY",
            "oos_accessed": False,
            "holdout_accessed": False,
            "broker_mutation": False,
            "reference_direction_authorized": False,
            "owner_policy_status": "PROVISIONAL_NOT_AUTHORIZED",
        },
        "frozen_ald_v2": {"sha256": sha256_file(FROZEN_ALD), "unchanged": True},
        "r2_reproduction": {
            "rows": r2_reproduction["rows"],
            "event_table_sha256": r2_reproduction["event_table_sha256"],
            "match": True,
        },
        "proposed_policy_sha256": sha256_file(POLICY_PATH),
    }
    evidence["evidence_sha256"] = sha256_json(evidence)
    path = OUT / "acceptance_evidence.json"
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "artifact": path.relative_to(ROOT).as_posix(),
        "result": asdict(result),
        "controls": asdict(controls),
        "r3_gate_trustworthy": evidence["certification"]["r3_gate_trustworthy"],
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
