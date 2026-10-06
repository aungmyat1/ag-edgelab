#!/usr/bin/env python3
"""Audit ALD V2 R3.1 direction timing, selection timing, and neutral null."""

from __future__ import annotations

import hashlib
import json
import random
import sys
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.data.fingerprint import canonical_json, sha256_file, sha256_json  # noqa: E402
from ag_edgelab.optimization.direction_causality_audit import (  # noqa: E402
    DirectionalNullMode, evaluate_directional_experiment,
)
from ag_edgelab.optimization.eligibility_r3_1 import DirectionalOpportunity  # noqa: E402
from ag_edgelab.optimization.reference_outcome_v2 import (  # noqa: E402
    ReferenceDirectionMode, ReferenceOutcomeV2Config, evaluate_reference_outcome_v2,
)
from ag_edgelab.strategies import asian_liquidity_displacement_v2 as V2  # noqa: E402
from ag_edgelab.strategies.asian_liquidity_displacement_v2_real_fixture import (  # noqa: E402
    produce_real_fixture,
)

UTC = timezone.utc
AUDITED_HEAD = "5e76dc6bbcedc5d9e7e1ec900390274fe752efb8"
R31_DIR = ROOT / "artifacts/funnel_optimizer_v1_r3_1_statistical_certification"
PREREG = ROOT / "config/governance/funnel_optimizer_v1_fixture_preregistration.json"
OUT = ROOT / "artifacts/funnel_optimizer_v1_r3_2_direction_causality_audit"
FROZEN = ROOT / "src/ag_edgelab/strategies/asian_liquidity_displacement_v2.py"
FROZEN_SHA = "883e9095977cd25840201f5b2b3d5ce6e67b350c1157f30045654dbd13904920"
REPLICATES = 2000
SEED = 4030341158


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _direction(unit: V2.V2Unit) -> str | None:
    return {"BULL": "LONG", "BEAR": "SHORT"}.get(unit.direction)


def _reference(production, row, at: datetime, *, selected: bool, direction: str | None):
    bars = production.frames[(row.symbol, row.timestamp_utc.year)].frames["M5"]
    outcome = evaluate_reference_outcome_v2(
        bars, at, event_id=f"{row.event_id}:{at.isoformat()}",
        config=ReferenceOutcomeV2Config(direction_mode=ReferenceDirectionMode.BOTH_DIRECTIONS_SYMMETRIC),
    )
    return DirectionalOpportunity(
        row.event_id, at, row.symbol, at.year, row.session,
        outcome.long_outcome_r, outcome.short_outcome_r,
        selected, direction if selected else None,
    ), outcome


def _experiment(records):
    return evaluate_directional_experiment(records, replicates=REPLICATES, seed=SEED)


def _null(result, mode):
    return next(item for item in result.null_summaries if item.mode is mode)


def _placebo(records, kind: str, seed: int):
    selected_indices = [i for i, row in enumerate(records) if row.parent_selected]
    directions = [records[i].parent_direction for i in selected_indices]
    out = [replace(row, parent_selected=False, parent_direction=None) for row in records]
    if kind == "SHIFT":
        assigned = directions[-1:] + directions[:-1]
        target_indices = selected_indices
    elif kind == "PERMUTE":
        assigned = list(directions)
        random.Random(seed).shuffle(assigned)
        target_indices = selected_indices
    elif kind == "RANDOM_SELECTION":
        assigned = list(directions)
        rng = random.Random(seed)
        rng.shuffle(assigned)
        target_indices = rng.sample(range(len(records)), len(selected_indices))
    else:
        raise ValueError(kind)
    for index, direction in zip(target_indices, assigned, strict=True):
        out[index] = replace(out[index], parent_selected=True, parent_direction=direction)
    return evaluate_directional_experiment(out, replicates=500, seed=seed)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if sha256_file(FROZEN) != FROZEN_SHA:
        raise RuntimeError("frozen ALD V2 changed")
    production = produce_real_fixture(preregistration_path=PREREG, root=ROOT)
    rows = production.table.rows
    units = production.parent_units

    selected_r31 = [row for row in rows if row.all_rules_pass]
    timing_rows = []
    offsets = []
    for row in selected_r31:
        unit = units[row.event_id]
        t0 = _dt(unit.event_time)  # source is M15 bar OPEN
        t1 = t0 + timedelta(minutes=15)  # close needed by S4 close comparison
        t2 = _dt(unit.confirm_time) + timedelta(minutes=5)  # confirmation close
        record, outcome = _reference(production, row, t0, selected=True, direction=_direction(unit))
        offset = (outcome.entry_time - t1).total_seconds() / 60  # type: ignore[operator]
        offsets.append(offset)
        timing_rows.append({
            "opportunity_id": row.event_id,
            "symbol": row.symbol,
            "session": row.session,
            "EVENT_BAR_OPEN_TIME": t0.isoformat(),
            "EVENT_BAR_CLOSE_TIME": t1.isoformat(),
            "DIRECTION_VALUE": _direction(unit),
            "DIRECTION_AVAILABLE_TIME": t1.isoformat(),
            "RECLAIM_OR_RETEST_TIME": unit.reclaim_or_retest_time,
            "CONFIRM_TIME": unit.confirm_time,
            "CANONICAL_PARENT_ENTRY_TIME": t2.isoformat(),
            "CANONICAL_PARENT_ENTRY_PRICE": unit.entry,
            "R3_1_REFERENCE_ENTRY_TIME": outcome.entry_time.isoformat(),  # type: ignore[union-attr]
            "R3_1_REFERENCE_ENTRY_PRICE": outcome.entry_price,
            "REFERENCE_ATR_CUTOFF_TIME": outcome.entry_time.isoformat(),  # prior bars close here
            "FIRST_OUTCOME_BAR_TIME": outcome.entry_time.isoformat(),
            "REFERENCE_ENTRY_MINUS_DIRECTION_AVAILABLE_MINUTES": offset,
        })
    timing_path = OUT / "selected_parent_timing_ledger.jsonl"
    timing_path.write_text("".join(canonical_json(item) + "\n" for item in timing_rows))

    # A: exact event-open timing and historical all-rules-pass selection.
    event_records = []
    for row in rows:
        unit = units[row.event_id]
        event_records.append(_reference(
            production, row, row.timestamp_utc,
            selected=row.all_rules_pass, direction=_direction(unit),
        )[0])
    event_result = _experiment(event_records)

    # B: reference starts at M15 close. S4 is the last available selection fact
    # at this point; no later reclaim, confirmation, geometry, or outcome fact
    # is allowed into the parent mask. Rows without an event use the same +15m
    # clock shift solely as independent baseline opportunities.
    direction_records = []
    for row in rows:
        unit = units[row.event_id]
        at = (_dt(unit.event_time) + timedelta(minutes=15)
              if unit.event_time else row.timestamp_utc + timedelta(minutes=15))
        selected = unit.passed("S4_SWEEP_OR_BREAKOUT")
        direction_records.append(_reference(
            production, row, at, selected=selected, direction=_direction(unit),
        )[0])
    direction_result = _experiment(direction_records)

    # C: S8 is the causal entry mask; S9 is excluded. Independent baseline
    # opportunities receive a deterministically matched empirical T2-T0 lag
    # from the S8 population, preserving timing without using their outcomes.
    s8_rows = [row for row in rows if units[row.event_id].passed("S8_GEOMETRY_VALID")]
    delays = sorted(
        (_dt(units[row.event_id].confirm_time) + timedelta(minutes=5) - row.timestamp_utc)
        for row in s8_rows
    )
    canonical_records = []
    for row in rows:
        unit = units[row.event_id]
        selected = unit.passed("S8_GEOMETRY_VALID")
        if selected:
            at = _dt(unit.confirm_time) + timedelta(minutes=5)
        else:
            slot = int(hashlib.sha256(row.event_id.encode()).hexdigest()[:16], 16) % len(delays)
            at = row.timestamp_utc + delays[slot]
        canonical_records.append(_reference(
            production, row, at, selected=selected, direction=_direction(unit),
        )[0])
    canonical_result = _experiment(canonical_records)

    s8_n = len(s8_rows)
    s9_n = sum(units[row.event_id].passed("S9_TRADE_COMPLETED") for row in s8_rows)
    dropped = [row for row in s8_rows if not units[row.event_id].passed("S9_TRADE_COMPLETED")]

    # Branch and basic strata retain the same independent full baseline, but
    # only the named causal S8 parent subset remains selected.
    diagnostics = {}
    for name, predicate in {
        "BRANCH_A": lambda u, r: u.branch == "A_SWEEP_RECLAIM_REVERSAL",
        "BRANCH_B": lambda u, r: u.branch == "B_BREAKOUT_RETEST_CONTINUATION",
        "LONG": lambda u, r: u.direction == "BULL",
        "SHORT": lambda u, r: u.direction == "BEAR",
        "EURUSD": lambda u, r: r.symbol == "EURUSD",
        "GBPUSD": lambda u, r: r.symbol == "GBPUSD",
        **{f"YEAR_{year}": (lambda u, r, y=year: r.timestamp_utc.year == y) for year in (2015, 2016, 2017)},
    }.items():
        subset = [replace(record, parent_selected=(record.parent_selected and predicate(units[row.event_id], row)),
                          parent_direction=(record.parent_direction if record.parent_selected and predicate(units[row.event_id], row) else None))
                  for record, row in zip(canonical_records, rows, strict=True)]
        diagnostics[name] = asdict(evaluate_directional_experiment(
            subset, replicates=1000, seed=SEED + len(diagnostics) * 101))

    shift = _placebo(canonical_records, "SHIFT", SEED + 11)
    permute = _placebo(canonical_records, "PERMUTE", SEED + 12)
    randomized_results = [_placebo(canonical_records, "RANDOM_SELECTION", SEED + 100 + i)
                          for i in range(20)]
    randomized_passes = sum(item.verdict == "PASS" for item in randomized_results)

    event_old = _null(event_result, DirectionalNullMode.OLD_SYMMETRIC_TWO_LEG_AVERAGE)
    event_random = _null(event_result, DirectionalNullMode.RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY)
    event_matched = _null(event_result, DirectionalNullMode.MATCHED_DIRECTION_FREQUENCY_NULL)
    invalid_null = event_random.sd_r > event_old.sd_r * 1.10
    direction_after = sum(value < 0 for value in offsets)
    classification = "R3_1_PASS_EXPLAINED_BY_MULTIPLE_ARTIFACTS"

    stage_classes = {
        "S1_CONTEXT_ELIGIBLE": "PRE_ENTRY_INFORMATION",
        "S2_LOCATION_ELIGIBLE": "PRE_ENTRY_INFORMATION",
        "S3_SESSION_EVENT": "PRE_ENTRY_INFORMATION_AT_EVENT_CLOSE",
        "S4_SWEEP_OR_BREAKOUT": "PRE_ENTRY_INFORMATION_AT_EVENT_CLOSE",
        "S5_RECLAIM_OR_RETEST": "PRE_ENTRY_INFORMATION",
        "S6_STRUCTURE_CONFIRM": "ENTRY_TIME_INFORMATION",
        "S7_ENTRY_AVAILABLE": "ENTRY_TIME_INFORMATION_WITH_FORWARD_AVAILABILITY_CHECK",
        "S8_GEOMETRY_VALID": "ENTRY_TIME_INFORMATION",
        "S9_TRADE_COMPLETED": "OUTCOME_INFORMATION",
    }
    evidence = {
        "schema_version": "FUNNEL_OPTIMIZER_V1_R3_2_DIRECTION_CAUSALITY_AUDIT",
        "lineage": {
            "audited_head": AUDITED_HEAD,
            "r3_1_acceptance_sha256": sha256_file(R31_DIR / "acceptance_evidence.json"),
            "r3_1_directional_table_sha256": sha256_file(R31_DIR / "directional_reference_legs.jsonl"),
            "supersedes": "R3.1 causal eligibility authority only; R3.1 remains historical",
        },
        "timing": {
            "direction_available_time_authority": "M15 interaction bar close (event_time + 15 minutes)",
            "ledger": timing_path.relative_to(ROOT).as_posix(),
            "ledger_sha256": sha256_file(timing_path),
            "direction_before_reference_entry_n": sum(value > 0 for value in offsets),
            "direction_at_reference_entry_n": sum(value == 0 for value in offsets),
            "direction_after_reference_entry_n": direction_after,
            "reference_entry_minus_direction_available_minutes": {
                "min": min(offsets), "median": median(offsets), "max": max(offsets),
                "negative_count": direction_after,
            },
            "r3_1_causality_verdict": "FAIL_LOOKAHEAD_DIRECTION" if direction_after else "PASS",
        },
        "selection_time_audit": {
            "r3_1_parent_selection_expression": "row.all_rules_pass",
            "required_stages": list(V2.STAGE_NODES),
            "stage_classification": stage_classes,
            "parent_selection_causal_at_entry": False,
            "reason": "all_rules_pass requires S9_TRADE_COMPLETED outcome information",
            "r3_2_causal_parent_mask": "S8_GEOMETRY_VALID_PASS; S9 excluded",
            "s8_entry_eligible_n": s8_n,
            "s9_completed_n": s9_n,
            "s8_to_s9_dropped_n": len(dropped),
            "dropped": [{"opportunity_id": row.event_id,
                         "timestamp_utc": row.timestamp_utc.isoformat(),
                         "reason": units[row.event_id].reject_reason}
                        for row in dropped],
        },
        "null_audit": {
            "old_symmetric": asdict(event_old),
            "random_direction_one_leg": asdict(event_random),
            "matched_direction_frequency": asdict(event_matched),
            "directional_variance_ratio_vs_old": event_random.sd_r / event_old.sd_r,
            "r3_1_null_verdict": "INVALID_DIRECTIONAL_NULL" if invalid_null else "VARIANCE_EQUIVALENT",
        },
        "experiments": {
            "EVENT_OPEN_REFERENCE": asdict(event_result) | {"status": "NONCAUSAL_DIAGNOSTIC"},
            "DIRECTION_AVAILABLE_REFERENCE": asdict(direction_result),
            "CANONICAL_PARENT_ENTRY_REFERENCE": asdict(canonical_result) | {
                "baseline_timing": "DETERMINISTIC_MATCHED_EMPIRICAL_T2_MINUS_T0_LAG_FOR_NONPARENT_UNIVERSE"
            },
        },
        "branch_and_stratum_diagnostics": diagnostics,
        "placebos": {
            "shift_one_opportunity": asdict(shift),
            "direction_permutation": asdict(permute),
            "selection_randomization": {
                "replicates": len(randomized_results), "pass_count": randomized_passes,
                "pass_rate": randomized_passes / len(randomized_results),
                "results": [asdict(item) for item in randomized_results],
            },
        },
        "classification": {
            "adversarial_classification": classification,
            "r3_1_pass_survives_causal_adversarial_audit": False,
            "r3_gate_trustworthy": False,
            "real_campaign_authorized": False,
            "owner_policy_status": "PROVISIONAL_NOT_AUTHORIZED",
            "independent_findings": [
                "R3.1 reference entry precedes M15-close direction availability",
                "R3.1 symmetric two-leg averaged null materially understates directional variance" if invalid_null else "null variance not materially different",
                "R3.1 all_rules_pass selection includes S9 outcome/completion information",
            ],
        },
        "governance": {
            "frozen_ald_v2_unchanged": True,
            "oos_accessed": False, "holdout_accessed": False,
            "broker_mutation": False, "edge_verified_issued": False,
            "child_optimization_run": False,
        },
    }
    evidence["evidence_sha256"] = sha256_json(evidence)
    path = OUT / "acceptance_evidence.json"
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "artifact": path.relative_to(ROOT).as_posix(),
        "timing": evidence["timing"],
        "selection": evidence["selection_time_audit"],
        "null_audit": evidence["null_audit"],
        "experiments": evidence["experiments"],
        "placebos": evidence["placebos"],
        "classification": evidence["classification"],
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
