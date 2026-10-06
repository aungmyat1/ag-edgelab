#!/usr/bin/env python3
"""R3 causal policy freeze R1: mask audit, baseline timing sensitivity, verdict chain.

This is POLICY INFRASTRUCTURE, not candidate optimization:

* the frozen ALD V2 strategy is hash-verified, never rerun with new parameters;
* only the DEVELOPMENT fixture partition is read (OOS/holdout stay closed);
* the parent population is fixed by CAUSAL_ENTRY_GEOMETRY_MASK_V1, whose
  geometry is DERIVED from bars closed at or before T2 (never from the
  S7-populated unit fields) and is audited against the stored S8 geometry;
* the three baseline T2 timing policies are compared WITHOUT tuning any of
  them — this is the PHASE B6 policy sensitivity analysis the owner must
  resolve before authorizing the final policy.

Outputs ``artifacts/funnel_optimizer_v1_r3_causal_policy_freeze/``:
* ``causal_mask_audit.json``       — CAUSAL_ENTRY_GEOMETRY_MASK_V1 audit
* ``baseline_timing_sensitivity.json`` — the three-policy sensitivity table
* ``verdict_chain.json``           — hash-linked verdict records
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.data.fingerprint import canonical_json, sha256_file, sha256_json  # noqa: E402
from ag_edgelab.optimization.baseline_timing_policy import (  # noqa: E402
    DEFAULT_FIXED_DELAY_FROM_T1_MINUTES, DEFAULT_MIN_STRATUM_PARENT_N,
    StratifiedDelayPools, empirical_matched_delay, fixed_causal_delay_from_t1,
)
from ag_edgelab.optimization.causal_entry_mask import (  # noqa: E402
    CAUSAL_MASK_ID, causal_mask_for_v2_unit, derive_causal_geometry,
)
from ag_edgelab.optimization.causal_time import t2_decision_time  # noqa: E402
from ag_edgelab.optimization.direction_causality_audit import (  # noqa: E402
    evaluate_directional_experiment,
)
from ag_edgelab.optimization.directional_null_policy import (  # noqa: E402
    NULL_MASTER_SEED, NULL_REPLICATES,
)
from ag_edgelab.optimization.eligibility_r3_1 import DirectionalOpportunity  # noqa: E402
from ag_edgelab.optimization.execution_semantics import (  # noqa: E402
    FROZEN_EXECUTION_SEMANTICS, execution_semantics_hash,
)
from ag_edgelab.optimization.reference_outcome_v2 import (  # noqa: E402
    ReferenceDirectionMode, ReferenceOutcomeV2Config, evaluate_reference_outcome_v2,
)
from ag_edgelab.optimization.verdict_record import (  # noqa: E402
    VerdictRecord, chain_manifest,
)
from ag_edgelab.strategies import asian_liquidity_displacement_v2 as V2  # noqa: E402
from ag_edgelab.strategies.asian_liquidity_displacement_v2_real_fixture import (  # noqa: E402
    produce_real_fixture,
)

UTC = timezone.utc

POLICY_FREEZE_BASE = "252059ec84e76562e8ecb7115311f42bb62eac41"
PREREG = ROOT / "config/governance/funnel_optimizer_v1_fixture_preregistration.json"
POLICY_PROPOSAL = ROOT / "config/governance/funnel_optimizer_r3_causal_policy_proposal.json"
FROZEN = ROOT / "src/ag_edgelab/strategies/asian_liquidity_displacement_v2.py"
FROZEN_SHA = "883e9095977cd25840201f5b2b3d5ce6e67b350c1157f30045654dbd13904920"
OUT = ROOT / "artifacts/funnel_optimizer_v1_r3_causal_policy_freeze"

# PHASE B6 policy C preregistered clock: one fixed delay from T1 that does
# not depend on whether the opportunity later qualifies.  120 minutes is a
# round, scale-free constant chosen WITHOUT consulting any outcome statistic
# under any of the compared policies; it is a policy parameter the owner may
# revise (decision R3_OD_05).
FIXED_CAUSAL_DELAY_FROM_T1_MINUTES = DEFAULT_FIXED_DELAY_FROM_T1_MINUTES
STRATIFIED_MIN_STRATUM_PARENT_N = DEFAULT_MIN_STRATUM_PARENT_N


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _direction(unit: V2.V2Unit) -> str | None:
    return {"BULL": "LONG", "BEAR": "SHORT"}.get(unit.direction)


def _bars_for(production, row):
    frames = production.frames[(row.symbol, row.timestamp_utc.year)].frames
    return frames["M5"], frames["M15"], frames["H1"]


def _mask(production, row):
    m5, m15, h1 = _bars_for(production, row)
    return causal_mask_for_v2_unit(production.parent_units[row.event_id],
                                   m5=m5, m15=m15, h1=h1)


def _reference(production, row, at: datetime, *, selected: bool, direction: str | None):
    bars = production.frames[(row.symbol, row.timestamp_utc.year)].frames["M5"]
    outcome = evaluate_reference_outcome_v2(
        bars, at, event_id=f"{row.event_id}:{at.isoformat()}",
        config=ReferenceOutcomeV2Config(
            direction_mode=ReferenceDirectionMode.BOTH_DIRECTIONS_SYMMETRIC),
    )
    return DirectionalOpportunity(
        row.event_id, at, row.symbol, at.year, row.session,
        outcome.long_outcome_r, outcome.short_outcome_r,
        selected, direction if selected else None,
    )


def _experiment(records):
    return evaluate_directional_experiment(
        records, replicates=NULL_REPLICATES, seed=NULL_MASTER_SEED)


def _policy_row(name: str, result, parent_n: int) -> dict[str, object]:
    return {
        "BASELINE_TIMING_POLICY": name,
        "PARENT_N": parent_n,
        "REFERENCE_COVERAGE": result.reference_coverage,
        "BASELINE_MEAN_R": result.null_mean_r,
        "PARENT_EXPECTANCY_R": result.parent_expectancy_r,
        "PARENT_PERCENTILE": result.parent_percentile,
        "SELECTION_DELTA_R": result.selection_delta_r,
        "DELTA_CI95": [result.delta_cluster_ci95_low_r, result.delta_cluster_ci95_high_r],
        "VERDICT": result.verdict,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if sha256_file(FROZEN) != FROZEN_SHA:
        raise RuntimeError("frozen ALD V2 changed; refusing to continue")

    proposal = json.loads(POLICY_PROPOSAL.read_text())
    policy_hash = proposal["POLICY_HASH"]

    production = produce_real_fixture(preregistration_path=PREREG, root=ROOT)
    rows = production.table.rows
    units = production.parent_units

    # ------------------------------------------------------------------
    # PHASE B2 — CAUSAL_ENTRY_GEOMETRY_MASK_V1 audit
    # ------------------------------------------------------------------
    mask_results = {row.event_id: _mask(production, row) for row in rows}
    mask_eligible = [row for row in rows if mask_results[row.event_id].eligible]
    s8_rows = [row for row in rows if units[row.event_id].passed("S8_GEOMETRY_VALID")]
    s9_of_s8 = sum(units[row.event_id].passed("S9_TRADE_COMPLETED") for row in s8_rows)
    mask_only = [row for row in mask_eligible
                 if not units[row.event_id].passed("S8_GEOMETRY_VALID")]
    s8_only = [row for row in s8_rows if not mask_results[row.event_id].eligible]

    # Confirmed units whose S7 failed only for missing forward bars: the
    # boundary case the causal mask must NOT penalize.
    confirmed = [row for row in rows if units[row.event_id].passed("S6_STRUCTURE_CONFIRM")]
    boundary = [row for row in confirmed
                if units[row.event_id].reject_reason == "NO_FORWARD_BARS"]

    # Derived-vs-stored geometry equivalence over every S8-passing unit:
    # the causal derivation must reproduce the frozen replay's stored
    # geometry exactly, proving the mask reads no S7/S8-gated information.
    geometry_checked = geometry_match = 0
    geometry_mismatches: list[str] = []
    for row in s8_rows:
        unit = units[row.event_id]
        m5, m15, h1 = _bars_for(production, row)
        derived = derive_causal_geometry(unit, m5=m5, m15=m15, h1=h1)
        geometry_checked += 1
        if (derived.entry == unit.entry and derived.stop == unit.stop
                and derived.target == unit.target):
            geometry_match += 1
        else:
            geometry_mismatches.append(row.event_id)

    parent_ids = {row.event_id for row in mask_eligible}
    parent_rows = [
        (row.event_id, row.symbol, row.session, row.timestamp_utc.year,
         _dt(units[row.event_id].confirm_time) + timedelta(minutes=5) - row.timestamp_utc)
        for row in mask_eligible
    ]
    parent_t2_lags = sorted(lag for *_, lag in parent_rows)

    mask_audit = {
        "schema_version": "R3_CAUSAL_POLICY_FREEZE_MASK_AUDIT_V1",
        "CAUSAL_MASK_ID": CAUSAL_MASK_ID,
        "policy_freeze_base": POLICY_FREEZE_BASE,
        "policy_hash": policy_hash,
        "decision_ts_rule": "T2_CONFIRMATION_M5_CLOSE",
        "geometry_source": "DERIVED_FROM_BARS_CLOSED_AT_OR_BEFORE_T2 (S7-populated unit fields are never read)",
        "forbidden_inputs": [
            "FUTURE_BAR_EXISTENCE", "RIGHT_CENSOR_STATUS", "S9_COMPLETION",
            "MFE", "MAE", "REALIZED_OUTCOME", "FUTURE_FILL_KNOWLEDGE",
            "POST_ENTRY_OUTCOME_AVAILABILITY",
        ],
        "population_n": len(rows),
        "confirmed_n": len(confirmed),
        "boundary_no_forward_bars_n": len(boundary),
        "mask_eligible_n": len(mask_eligible),
        "s8_pass_n": len(s8_rows),
        "s9_completed_of_s8_n": s9_of_s8,
        "mask_eligible_but_s8_fail_n": len(mask_only),
        "mask_eligible_but_s8_fail_reasons": sorted(
            {units[row.event_id].reject_reason for row in mask_only}),
        "s8_pass_but_mask_fail_n": len(s8_only),
        "s8_pass_but_mask_fail_reasons": sorted(
            {mask_results[row.event_id].reason_code for row in s8_only}),
        "derived_vs_stored_geometry": {
            "checked_n": geometry_checked,
            "match_n": geometry_match,
            "mismatch_ids": geometry_mismatches[:20],
        },
        "frozen_ald_v2_sha256": FROZEN_SHA,
        "event_table_sha256": production.table.sha256,
    }
    (OUT / "causal_mask_audit.json").write_text(
        json.dumps(mask_audit, indent=2, sort_keys=True) + "\n")

    if s8_only:
        raise RuntimeError(
            "CAUSAL mask disagrees with historical S8 geometry on "
            f"{len(s8_only)} rows; investigate before freezing")
    if geometry_mismatches:
        raise RuntimeError(
            f"derived causal geometry mismatched stored S8 geometry on "
            f"{len(geometry_mismatches)} rows; investigate before freezing")

    # ------------------------------------------------------------------
    # PHASE B6 — baseline T2 timing policy sensitivity analysis
    # ------------------------------------------------------------------
    def reference_at(row, at, selected: bool):
        return _reference(production, row, at, selected=selected,
                          direction=_direction(units[row.event_id]))

    # Policy A — EMPIRICAL_MATCHED_DELAY (R3.2 diagnostic semantics)
    records_a = []
    for row in rows:
        if row.event_id in parent_ids:
            at = t2_decision_time(_dt(units[row.event_id].confirm_time))
            records_a.append(reference_at(row, at, True))
        else:
            at = empirical_matched_delay(row.event_id, row.timestamp_utc, parent_t2_lags)
            records_a.append(reference_at(row, at, False))
    result_a = _experiment(records_a)

    # Policy B — STRATIFIED_EMPIRICAL_MATCHED_DELAY: symbol + session, with
    # year subdivision PER (symbol, session, year) stratum holding at least
    # STRATIFIED_MIN_STRATUM_PARENT_N parents; sub-threshold years fall
    # back to the (symbol, session) pool.
    pools = StratifiedDelayPools.build(
        parent_rows, min_stratum_parent_n=STRATIFIED_MIN_STRATUM_PARENT_N)
    records_b = []
    for row in rows:
        if row.event_id in parent_ids:
            at = t2_decision_time(_dt(units[row.event_id].confirm_time))
            records_b.append(reference_at(row, at, True))
        else:
            at = pools.delay(row.event_id, row.timestamp_utc, row.symbol,
                             row.session, row.timestamp_utc.year)
            records_b.append(reference_at(row, at, False))
    result_b = _experiment(records_b)

    # Policy C — FIXED_CAUSAL_DELAY_FROM_T1 (preregistered constant clock)
    records_c = []
    for row in rows:
        unit = units[row.event_id]
        if row.event_id in parent_ids:
            at = t2_decision_time(_dt(unit.confirm_time))
            records_c.append(reference_at(row, at, True))
        else:
            t1 = (_dt(unit.event_time) + timedelta(minutes=15)
                  if unit.event_time else row.timestamp_utc + timedelta(minutes=15))
            at = fixed_causal_delay_from_t1(
                t1, minutes=FIXED_CAUSAL_DELAY_FROM_T1_MINUTES)
            records_c.append(reference_at(row, at, False))
    result_c = _experiment(records_c)

    rows_out = [
        _policy_row("EMPIRICAL_MATCHED_DELAY", result_a, len(mask_eligible)),
        _policy_row("STRATIFIED_EMPIRICAL_MATCHED_DELAY", result_b, len(mask_eligible)),
        _policy_row("FIXED_CAUSAL_DELAY_FROM_T1", result_c, len(mask_eligible)),
    ]
    verdicts = {item["VERDICT"] for item in rows_out}
    sensitivity = "ROBUST" if len(verdicts) == 1 else "POLICY_SENSITIVE"

    sensitivity_doc = {
        "schema_version": "R3_BASELINE_T2_TIMING_SENSITIVITY_V1",
        "policy_freeze_base": POLICY_FREEZE_BASE,
        "policy_hash": policy_hash,
        "ANALYSIS_CLASS": "POLICY_SENSITIVITY_ANALYSIS_NOT_CANDIDATE_OPTIMIZATION",
        "parent_mask": CAUSAL_MASK_ID,
        "primary_null": "RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY",
        "robustness_null": "MATCHED_DIRECTION_FREQUENCY_NULL",
        "null_replicates": NULL_REPLICATES,
        "null_seed": NULL_MASTER_SEED,
        "fixed_delay_from_t1_minutes": FIXED_CAUSAL_DELAY_FROM_T1_MINUTES,
        "fixed_delay_preregistration_note": (
            "120 minutes is a round, scale-free constant preregistered without "
            "consulting outcome statistics under any compared policy; the owner "
            "may revise it as part of decision R3_OD_05"),
        "stratified_min_stratum_parent_n": STRATIFIED_MIN_STRATUM_PARENT_N,
        "stratified_year_eligibility": (
            "per (symbol, session, year) stratum independently; sub-threshold "
            "years fall back to the (symbol, session) pool"),
        "stratified_year_pools": sorted(
            f"{sym}/{sess}/{year}" for (sym, sess, year) in pools.year_pools),
        "policies": rows_out,
        "BASELINE_TIMING_SENSITIVITY": sensitivity,
        "BASELINE_T2_TIMING_POLICY_STATUS": "UNRESOLVED_OWNER_DECISION",
        "candidate_optimization_performed": False,
        "ald_v2_strategy_parameters_changed": False,
        "ald_v2_disposition": "DEV_REJECTED_CAUSAL_SELECTION / ARCHIVE_NO_V2_2",
        "governance": {
            "oos_accessed": False,
            "holdout_accessed": False,
            "broker_mutation": False,
            "edge_verified_issued": False,
            "gen3_optimization_run": False,
            "real_campaign_authorized": False,
        },
    }
    (OUT / "baseline_timing_sensitivity.json").write_text(
        json.dumps(sensitivity_doc, indent=2, sort_keys=True) + "\n")

    # ------------------------------------------------------------------
    # PHASE B9 — hash-linked verdict chain
    # ------------------------------------------------------------------
    materialization = json.loads(PREREG.read_text())["materialization"]
    dataset_hash = str(materialization["dataset_sha256"])
    code_modules = sorted([
        "src/ag_edgelab/optimization/causal_time.py",
        "src/ag_edgelab/optimization/causal_entry_mask.py",
        "src/ag_edgelab/optimization/causal_normalization.py",
        "src/ag_edgelab/optimization/directional_null_policy.py",
        "src/ag_edgelab/optimization/execution_semantics.py",
        "src/ag_edgelab/optimization/verdict_record.py",
        "src/ag_edgelab/optimization/baseline_timing_policy.py",
    ])
    policy_code_sha = sha256_json({
        "modules": {name: sha256_file(ROOT / name) for name in code_modules}})

    r32_audit_record = VerdictRecord(
        verdict_id="R3_2_DIRECTION_CAUSALITY_AUDIT",
        dataset_hash=dataset_hash,
        candidate_contract_hash=FROZEN_SHA,
        engine_code_sha=FROZEN_SHA,
        event_table_hash=sha256_file(
            ROOT / "artifacts/funnel_optimizer_v1_r3_2_direction_causality_audit"
            "/acceptance_evidence.json"),
        verdict="R3_1_PASS_EXPLAINED_BY_MULTIPLE_ARTIFACTS",
        notes={"authority": "PR #23 R3.2 audit; historical, hash-pinned"},
    )
    freeze_record = VerdictRecord(
        verdict_id="R3_CAUSAL_POLICY_FREEZE_R1",
        policy_hash=policy_hash,
        dataset_hash=dataset_hash,
        candidate_contract_hash=FROZEN_SHA,
        engine_code_sha=policy_code_sha,
        event_table_hash=production.table.sha256,
        verdict=f"POLICY_PROPOSED_OWNER_UNRESOLVED_BASELINE_TIMING:"
                f"{sensitivity}",
        parent_verdict_id=r32_audit_record.verdict_id,
        parent_verdict_record_hash=r32_audit_record.verdict_record_hash,
        notes={
            "execution_semantics_hash": execution_semantics_hash(FROZEN_EXECUTION_SEMANTICS),
            "owner_r3_policy_authorized": "false",
            "real_campaign_authorized": "false",
        },
    )
    chain = chain_manifest([r32_audit_record, freeze_record])
    (OUT / "verdict_chain.json").write_text(
        json.dumps(chain, indent=2, sort_keys=True) + "\n")

    # ------------------------------------------------------------------
    # GEN3 disclosure binding (PHASE B11)
    # ------------------------------------------------------------------
    disclosure = {
        "HAS_GEN3_DEV_PERFORMANCE_ALREADY_BEEN_OBSERVED": False,
        "GEN3_PRE_POLICY_EXPOSURE": False,
        "GEN3_PERFORMANCE_EXECUTED_THIS_MISSION": False,
        "evidence": "docs/GEN3_PRE_POLICY_EXPOSURE_DISCLOSURE.md",
    }

    summary = {
        "POLICY_FREEZE_BASE": POLICY_FREEZE_BASE,
        "POLICY_HASH": policy_hash,
        "CAUSAL_MASK_ID": CAUSAL_MASK_ID,
        "mask_eligible_n": len(mask_eligible),
        "boundary_no_forward_bars_n": len(boundary),
        "derived_vs_stored_geometry_match": f"{geometry_match}/{geometry_checked}",
        "s8_pass_n": len(s8_rows),
        "BASELINE_TIMING_SENSITIVITY": sensitivity,
        "policies": {item["BASELINE_TIMING_POLICY"]: item["VERDICT"]
                     for item in rows_out},
        "VERDICT_RECORD_HASH": freeze_record.verdict_record_hash,
        "GEN3": disclosure,
        "frozen_ald_v2_sha256_unchanged": True,
        "artifacts": [
            "artifacts/funnel_optimizer_v1_r3_causal_policy_freeze/causal_mask_audit.json",
            "artifacts/funnel_optimizer_v1_r3_causal_policy_freeze/baseline_timing_sensitivity.json",
            "artifacts/funnel_optimizer_v1_r3_causal_policy_freeze/verdict_chain.json",
        ],
    }
    (OUT / "freeze_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
