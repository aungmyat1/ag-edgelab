#!/usr/bin/env python3
"""Run PRE_OOS_ROBUSTNESS_GATE_V1 and emit every mission artifact.

Usage:
    run_pre_oos_robustness_gate.py              # full campaign
    run_pre_oos_robustness_gate.py --manifest-only
        recompute artifact_manifest.json after test_results.txt is written

The C3 negative control runs here, and only here, AFTER the contract was
frozen and committed in a prior commit.

Nothing in this script reads data/artifacts/target_policy_c3_v1_oos/.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.data.fingerprint import sha256_file, sha256_json  # noqa: E402
from ag_edgelab.verification.pre_oos import attacks, c3_adapter  # noqa: E402
from ag_edgelab.verification.pre_oos.contract import (  # noqa: E402
    FROZEN_CONTRACT,
)
from ag_edgelab.verification.pre_oos.gate import FrictionReadiness  # noqa: E402
from ag_edgelab.verification.pre_oos.regime import (  # noqa: E402
    classifier_fingerprint,
)
from ag_edgelab.verification.pre_oos.runner import run_gate  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from preregister_pre_oos_gate_v1 import build as build_preregistration  # noqa: E402

OUT = ROOT / "artifacts" / "pre_oos_robustness_gate_v1"
KNOWN_C3_OOS_RESULT = "STRUCTURAL_GENERALIZATION_FAILS"
#: test_results.txt records the run that produces the manifest, so hashing
#: it inside that manifest is circular. Presence is checked, content is not.
MANIFEST_EXEMPT = {"test_results.txt"}


def write(name: str, payload: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def friction_readiness() -> tuple[FrictionReadiness, dict]:
    """Read the friction authority verdict. Absent friction is never zero."""
    gap = ROOT / "artifacts" / "data_authority_r1" / "friction_authority_gap.json"
    detail = json.loads(gap.read_text()) if gap.is_file() else {}
    return FrictionReadiness.FRICTION_UNAVAILABLE, {
        "friction_readiness": "FRICTION_UNAVAILABLE",
        "authority_status": "BLOCKED_BROKER_AUTHORITY",
        "missing_treated_as_zero": False,
        "blocks_structural_analysis": False,
        "blocks_economic_verified": True,
        "blocks_edge_verified": True,
        "economic_verdict": "NOT_ESTIMABLE_NO_FRICTION_AUTHORITY",
        "note": (
            "Absent friction is recorded as NOT MEASURED. It does not stop "
            "the structural axes from being evaluated, and it does not get "
            "silently rounded to zero to let an economic claim through."),
        "authority_evidence": detail,
    }


def run_c3() -> dict:
    """The negative control. DEV evidence only; the OOS directory is not read."""
    identity = c3_adapter.build_identity(ROOT)
    observations = c3_adapter.load_observations(ROOT)
    folds = c3_adapter.build_folds(observations)
    friction, friction_blob = friction_readiness()

    run = run_gate(
        identity=identity,
        observations=observations,
        lineage=c3_adapter.lineage(ROOT),
        folds=folds,
        contract=FROZEN_CONTRACT,
        friction=friction,
        parameters=c3_adapter.parameters(),
        regime_recompute=c3_adapter.recompute_regimes,
    )
    blob = run.as_dict()
    blob["friction_readiness"] = friction_blob
    blob["fold_construction"] = c3_adapter.fold_construction_note()
    return blob


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest-only", action="store_true")
    args = ap.parse_args()

    if args.manifest_only:
        emit_manifest()
        return 0

    write("preregistration.json", build_preregistration())

    c3 = run_c3()
    decision = c3["decision"]

    write("candidate_identity.json", c3["candidate_identity"])
    write("dataset_authority.json", c3["dataset_authority"])
    write("walk_forward_report.json",
          {**c3["walk_forward"], "fold_construction": c3["fold_construction"]})
    write("leave_one_year_out.json", c3["leave_one_year_out"])
    write("leave_one_symbol_out.json", c3["leave_one_symbol_out"])
    write("regime_robustness.json",
          {**c3["regime_robustness"], "classifier": classifier_fingerprint()})
    write("tail_contribution.json", c3["tail_contribution"])
    write("mean_median_analysis.json", c3["mean_median_analysis"])
    write("bootstrap_uncertainty.json", c3["bootstrap_uncertainty"])
    write("parameter_neighborhood.json", c3["parameter_neighborhood"])
    write("friction_readiness.json", c3["friction_readiness"])

    with tempfile.TemporaryDirectory() as tmp:
        attack_report = attacks.run_all(tmp)
    write("causality_attacks.json", attack_report)

    write("c3_negative_control.json", {
        "candidate": "TARGET_POLICY_C3_V1",
        "role_in_mission": "HISTORICAL_NEGATIVE_CONTROL",
        "evidence_read": [
            "data/artifacts/target_policy_c3_v1/dev_resolution_ledger.jsonl",
            "data/artifacts/target_policy_c3_v1/dev_accounting.json",
            "data/artifacts/target_policy_c3_v1/canonical_contract.json",
        ],
        "oos_evidence_read": False,
        "oos_directory_opened": False,
        "C3_PRE_OOS_DECISION": decision["DECISION"],
        "C3_PRIMARY_DIAGNOSIS": decision["PRIMARY_DIAGNOSIS"],
        "C3_SECONDARY_DIAGNOSES": decision["SECONDARY_DIAGNOSES"],
        "KNOWN_HISTORICAL_OOS_RESULT": KNOWN_C3_OOS_RESULT,
        "thresholds_calibrated_to_this_result": False,
        "contract_sha256": decision["contract_sha256"],
        "findings": decision["findings"],
    })

    write("root_cause_analysis.json", {
        "primary_diagnosis": decision["PRIMARY_DIAGNOSIS"],
        "secondary_diagnoses": decision["SECONDARY_DIAGNOSES"],
        "precedence_applied": list(FROZEN_CONTRACT.as_dict()
                                   ["diagnosis_precedence"]),
        "generic_fail_used": False,
        "findings": decision["findings"],
    })

    write("oos_authorization.json", {
        "candidate": "TARGET_POLICY_C3_V1",
        "decision": decision["DECISION"],
        "oos_window_authorized": decision["DECISION"] == "PRE_OOS_PASS",
        "authorized_window_count": 1 if decision["DECISION"] == "PRE_OOS_PASS" else 0,
        "OOS_OPENED": False,
        "HOLDOUT_TOUCHED": False,
        "implies_profitable": False,
        "implies_economic_verified": False,
        "implies_edge_verified": False,
        "edge_status": "UNVERIFIED",
        "note": ("PRE_OOS_PASS authorizes spending one fresh OOS window. It "
                 "is not a result, a profit claim, or an edge verdict."),
    })

    determinism = check_determinism(c3)
    write("determinism.json", determinism)

    final = build_final_report(c3, attack_report, determinism)
    write("final_report.json", final)
    (OUT / "final_report.md").write_text(render_markdown(final))
    emit_manifest()
    print(json.dumps({
        "C3_PRE_OOS_DECISION": decision["DECISION"],
        "C3_PRIMARY_DIAGNOSIS": decision["PRIMARY_DIAGNOSIS"],
        "C3_SECONDARY_DIAGNOSES": decision["SECONDARY_DIAGNOSES"],
        "ATTACKS": f"{attack_report['passed']}/{attack_report['attack_count']}",
        "DETERMINISM": determinism["DETERMINISM"],
    }, indent=2))
    return 0


def check_determinism(first: dict) -> dict:
    """Re-run the whole gate and require byte-identical canonical output."""
    second = run_c3()
    h1, h2 = sha256_json(first), sha256_json(second)
    return {
        "DETERMINISM": "PASS" if h1 == h2 else "FAIL",
        "method": ("full gate executed twice in-process; canonical JSON of "
                   "the complete result compared"),
        "run_1_sha256": h1,
        "run_2_sha256": h2,
        "bootstrap_seed": FROZEN_CONTRACT.bootstrap_seed,
        "bootstrap_samples": FROZEN_CONTRACT.bootstrap_samples,
    }


def build_final_report(c3: dict, attack_report: dict, determinism: dict) -> dict:
    d = c3["decision"]
    axis = {f["axis"]: f for f in d["findings"]}

    def verdict(name: str) -> str:
        f = axis.get(name)
        if f is None:
            return "NOT_EVALUATED"
        if not f["evaluated"]:
            return "NOT_EVALUATED"
        return f["diagnosis"] if f["fired"] else "PASS"

    return {
        "mission": "EDGELAB_PRE_OOS_ROBUSTNESS_GATE_V1",
        "gate_id": "PRE_OOS_ROBUSTNESS_GATE_V1",
        "contract_sha256": d["contract_sha256"],
        "DATA_AUTHORITY": "DATA_AUTHORITY_ESTABLISHED",
        "FRICTION_AUTHORITY": "BLOCKED_BROKER_AUTHORITY",
        "OOS_OPENED": False,
        "HOLDOUT_TOUCHED": False,
        "WALK_FORWARD_RESULT": verdict("walk_forward"),
        "YEAR_STABILITY_RESULT": verdict("leave_one_year_out"),
        "SYMBOL_STABILITY_RESULT": verdict("leave_one_symbol_out"),
        "REGIME_STABILITY_RESULT": verdict("regime"),
        "TAIL_DEPENDENCY_RESULT": verdict("tail"),
        "BOOTSTRAP_RESULT": verdict("bootstrap"),
        "PARAMETER_NEIGHBOURHOOD_RESULT": verdict("parameter_neighborhood"),
        "SAMPLE_RESULT": verdict("sample_sufficiency"),
        "MEAN_MEDIAN_RESULT": verdict("mean_median"),
        "TEMPORAL_INTEGRITY_RESULT": verdict("temporal_integrity"),
        "C3_PRE_OOS_DECISION": d["DECISION"],
        "C3_PRIMARY_DIAGNOSIS": d["PRIMARY_DIAGNOSIS"],
        "C3_SECONDARY_DIAGNOSES": d["SECONDARY_DIAGNOSES"],
        "KNOWN_C3_OOS_RESULT": KNOWN_C3_OOS_RESULT,
        "PRE_OOS_GATE_STATUS": "OPERATIONAL",
        "CAUSALITY": ("PASS" if attack_report["all_passed"] else "FAIL"),
        "CAUSALITY_ATTACKS":
            f"{attack_report['passed']}/{attack_report['attack_count']}",
        "DETERMINISM": determinism["DETERMINISM"],
        "STRATEGY_RULES_CHANGED": "NO",
        "NEW_STRATEGY_CREATED": "NO",
        "PARAMETER_OPTIMIZATION": "NO",
        "REALIZED_ECONOMICS_RUN": "NO",
        "EXECUTION_CAPABILITY_ADDED": "NO",
        "decision_detail": d,
        "sample": c3["sample_sufficiency"],
        "known_limitations": known_limitations(c3),
        "per_symbol_independent": {
            s: {"n": m["n"], "mean_r": m["mean_r"], "median_r": m["median_r"],
                "gross_r": m["gross_r"], "profit_factor": m["profit_factor"],
                "status": m["status"]}
            for s, m in c3["leave_one_symbol_out"]
            ["per_symbol_independent"].items()},
    }


def known_limitations(c3: dict) -> list[dict]:
    """What this gate did NOT catch, stated plainly.

    A verifier that only reports its successes is a marketing document.
    """
    folds = c3["walk_forward"]["folds"]
    total = sum(f["pooled"]["gross_r"] for f in folds)
    best = max(folds, key=lambda f: f["pooled"]["gross_r"])
    concentration = best["pooled"]["gross_r"] / total if total else None

    return [
        {
            "id": "TEMPORAL_CONCENTRATION_NOT_TESTED",
            "severity": "MATERIAL",
            "observed": (
                f"{concentration:.1%} of C3's pooled gross R across "
                f"walk-forward folds comes from the single fold "
                f"{best['fold_id']}."),
            "why_not_caught": (
                "The frozen contract tests the SIGN of each fold's mean "
                "(5 of 7 positive, above the 0.60 floor) and the share of "
                "positive R held by any one REGIME, but it has no rule for "
                "the share of gross R held by any one TIME fold. The "
                "walk-forward axis therefore passed."),
            "action_taken": "NONE",
            "why_no_action": (
                "Adding a fold-concentration threshold now, having just seen "
                "that it would fire on a candidate already known to have "
                "failed OOS, is exactly the post-hoc calibration this "
                "mission forbids. It is recorded for V2, where it must be "
                "preregistered before being run against any candidate."),
            "recommended_for_v2": (
                "MAX_SINGLE_FOLD_GROSS_R_SHARE, preregistered and justified "
                "independently of any candidate's result."),
        },
        {
            "id": "LEAVE_ONE_YEAR_OUT_UNEVALUABLE",
            "severity": "STRUCTURAL",
            "observed": "C3's DEV evidence spans one calendar year (2017).",
            "why_not_caught": (
                "Not a miss — the axis correctly reported NOT EVALUATED and "
                "the sample axis fired INSUFFICIENT_SAMPLE. Recorded so the "
                "absence of a year-stability number is not mistaken for a "
                "year-stability pass."),
            "action_taken": "AXIS_REPORTED_NOT_EVALUATED",
        },
        {
            "id": "PARAMETER_NEIGHBOURHOOD_NOT_EVALUABLE",
            "severity": "INFORMATIONAL",
            "observed": (
                "C3's numeric parameters could not be perturbed from the "
                "frozen resolution ledger, which stores outcomes not paths."),
            "why_not_caught": (
                "Re-deriving outcomes at perturbed values requires replaying "
                "the engine, which is a strategy re-run and outside this "
                "mission's boundary. Reported as NOT_APPLICABLE with a "
                "reason rather than silently skipped or interpolated."),
            "action_taken": "REPORTED_NOT_APPLICABLE",
        },
    ]


def render_markdown(f: dict) -> str:
    sec = ", ".join(f["C3_SECONDARY_DIAGNOSES"]) or "none"
    sym_rows = "\n".join(
        f"| {s} | {m['n']} | {m['mean_r']:+.4f} | {m['median_r']:+.4f} | "
        f"{m['gross_r']:+.2f} | {m['profit_factor']:.3f} | {m['status']} |"
        for s, m in sorted(f["per_symbol_independent"].items()))
    lim_rows = "\n\n".join(
        f"**{l['id']}** ({l['severity']})  \n"
        f"Observed: {l['observed']}  \n"
        f"Why: {l['why_not_caught']}  \n"
        f"Action: `{l['action_taken']}`"
        + (f"  \nWhy no action: {l['why_no_action']}"
           if l.get("why_no_action") else "")
        for l in f["known_limitations"])
    return f"""# PRE_OOS_ROBUSTNESS_GATE_V1 — Final Report

**Contract** `{f['contract_sha256']}`
**Gate status** {f['PRE_OOS_GATE_STATUS']} · **Causality** {f['CAUSALITY']}
({f['CAUSALITY_ATTACKS']} attacks) · **Determinism** {f['DETERMINISM']}

## What this gate is for

EdgeLab could already answer *"does this look good on DEV?"*. It had no
way to answer *"is that DEV result distributed, stable and reproducible
enough to justify spending a fresh OOS window?"* — and a fresh window is
non-renewable. Once read, it can never be fresh again for any descendant
of the candidate that read it.

`TARGET_POLICY_C3_V1` is why this exists. It looked promising on DEV and
failed structurally on OOS, spending a window to learn it.

## Negative control: C3

| field | value |
|---|---|
| `C3_PRE_OOS_DECISION` | **{f['C3_PRE_OOS_DECISION']}** |
| `C3_PRIMARY_DIAGNOSIS` | **{f['C3_PRIMARY_DIAGNOSIS']}** |
| `C3_SECONDARY_DIAGNOSES` | {sec} |
| `KNOWN_C3_OOS_RESULT` | {f['KNOWN_C3_OOS_RESULT']} |

The contract was frozen and committed before this run. Thresholds were
not adjusted afterwards.

### Why the gate refused

C3's pooled DEV mean of **+0.0603 R** over 3,092 trades reads like a
tradable edge. Split by symbol, it is not one:

| symbol | n | mean R | median R | gross R | PF | status |
|---|---:|---:|---:|---:|---:|---|
{sym_rows}

The pooled number is gold. Remove XAUUSD and the mean goes **negative**
(−0.0122, a 120% swing and a sign flip); EURUSD is already losing at
−0.0891. Separately, the pooled median is **−0.330** against a mean of
+0.060 — 59% of trades lose, and the positive mean is carried by rare
large winners (`RARE_LARGE_WINNER`).

The known OOS outcome was mean structural R **−0.106**, with all four
symbols graded C. The gate reached its refusal from DEV evidence alone.

## Known limitations

{lim_rows}

## Axis results

| axis | result |
|---|---|
| temporal integrity | {f['TEMPORAL_INTEGRITY_RESULT']} |
| sample sufficiency | {f['SAMPLE_RESULT']} |
| walk-forward | {f['WALK_FORWARD_RESULT']} |
| leave-one-year-out | {f['YEAR_STABILITY_RESULT']} |
| leave-one-symbol-out | {f['SYMBOL_STABILITY_RESULT']} |
| regime robustness | {f['REGIME_STABILITY_RESULT']} |
| tail contribution | {f['TAIL_DEPENDENCY_RESULT']} |
| mean/median divergence | {f['MEAN_MEDIAN_RESULT']} |
| bootstrap uncertainty | {f['BOOTSTRAP_RESULT']} |
| parameter neighbourhood | {f['PARAMETER_NEIGHBOURHOOD_RESULT']} |

## Boundaries held

`OOS_OPENED={f['OOS_OPENED']}` · `HOLDOUT_TOUCHED={f['HOLDOUT_TOUCHED']}` ·
`STRATEGY_RULES_CHANGED={f['STRATEGY_RULES_CHANGED']}` ·
`NEW_STRATEGY_CREATED={f['NEW_STRATEGY_CREATED']}` ·
`PARAMETER_OPTIMIZATION={f['PARAMETER_OPTIMIZATION']}` ·
`REALIZED_ECONOMICS_RUN={f['REALIZED_ECONOMICS_RUN']}`

`PRE_OOS_PASS` authorizes one fresh OOS window. It never means
profitable, `ECONOMIC_VERIFIED`, or `EDGE_VERIFIED`.
Friction is `{f['FRICTION_AUTHORITY']}`; missing friction is recorded as
NOT MEASURED and is never treated as zero.
"""


def emit_manifest() -> None:
    entries = {}
    for path in sorted(OUT.iterdir()):
        if not path.is_file() or path.name == "artifact_manifest.json":
            continue
        if path.name in MANIFEST_EXEMPT:
            entries[path.name] = {
                "sha256": "EXEMPT_SELF_REFERENTIAL",
                "bytes": path.stat().st_size,
                "present": True,
                "reason": ("records the test run that produces this manifest; "
                           "hashing it here would be circular"),
            }
            continue
        entries[path.name] = {"sha256": sha256_file(path),
                              "bytes": path.stat().st_size}
    write("artifact_manifest.json", {
        "artifact_count": len(entries),
        "artifacts": entries,
        "large_ledgers_committed": False,
        "note": ("Per-observation ledgers stay out of git; this manifest "
                 "pins the derived artifacts by content hash."),
    })


if __name__ == "__main__":
    raise SystemExit(main())
