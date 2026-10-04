"""V0.6.2 — PHASE 0 (pre-open authority gate) + PHASE 1 (preregistration)
for the sealed structural OOS verification of TARGET_POLICY_C3_V1.

This script reads NO OOS market data. It:

  0. gates the mission: frozen candidate hash == mission pin; independent
     contract verifier re-run on the frozen DEV bundle; all 10 adversarial
     attacks re-executed and passing; OOS_STRUCTURAL_READY=YES and
     OOS_ECONOMIC_READY=NO; DEV artifacts immutable vs git; clean tree;
     HEAD/tree recorded;
  1. computes the frozen DEV reference metrics from the COMMITTED DEV
     artifacts (never re-running DEV research), sanity-checks them against
     the pinned V0.4/V0.5/V0.6 published values, and writes
     oos_preregistration.json — including the exact A/B/C/D verdict
     thresholds — BEFORE the OOS partition is opened.

The companion oos_preregistration.sha256 file is written next to it; both
are committed before the OOS run so git history proves the ordering.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.universal import c3_v1_oos_metrics as om  # noqa: E402
from ag_edgelab.verification import c3_v1_adversarial as adv  # noqa: E402
from ag_edgelab.verification import c3_v1_verifier as vf  # noqa: E402

MISSION_PIN = "5a485308841d1c5d2096e348665ef3f9b1f689c1ed4ce4b30385eeaf2c828112"
PRE_OOS_IMPLEMENTATION = "bf6d4f3"
DEV_BUNDLE = ROOT / "data" / "artifacts" / "target_policy_c3_v1"
V06_DIR = ROOT / "data" / "artifacts" / "universal_funnel_v0_6_target_policy"
OUT_DIR = ROOT / "data" / "artifacts" / "target_policy_c3_v1_oos"

# pinned published values the DEV references must reproduce (sanity gates)
V05_PINNED_QUANTILES = {"P25": 0.150, "P50": 0.402, "P75": 0.891}
V04_PINNED_FIXED_REACH = {"R1_CAPABILITY": 0.49262, "R2_CAPABILITY": 0.30317,
                          "R3_CAPABILITY": 0.20013, "R4_CAPABILITY": 0.13761,
                          "R5_CAPABILITY": 0.09519}
V06_PINNED_RUNNER_EXTENDED = 0.412518      # runner_results.json D01
V06_PINNED_CONTROL_DELTAS = {              # pathwise_policy_comparison.json D01
    "C3_F50_R0_vs_C0_2R": {"mean_delta_r": 0.043811591516849685,
                           "pair_n": 2573},
    "C3_F50_R0_vs_C0_5R": {"mean_delta_r": 0.058311736836952816,
                           "pair_n": 2301},
}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def _stop(code: str) -> None:
    print(f"STOP = {code}", file=sys.stderr)
    raise SystemExit(2)


def main() -> int:
    created_at = datetime.now(timezone.utc)
    print("PHASE 0 — PRE-OPEN AUTHORITY GATE")

    # 0.1 clean tracked state + HEAD/tree evidence
    # (untracked NEW mission tooling files are expected; any modification
    #  or deletion of a TRACKED file — including every frozen artifact —
    #  fails the gate)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                            capture_output=True, text=True).stdout.splitlines()
    tracked_changes = [line for line in status
                       if line and not line.startswith("??")]
    if tracked_changes:
        print("\n".join(tracked_changes))
        _stop("DIRTY_WORKING_TREE")
    head = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    if not head.startswith(PRE_OOS_IMPLEMENTATION):
        _stop("PRE_OOS_IMPLEMENTATION_MISMATCH")
    print(f"  HEAD = {head}")
    print(f"  TREE = {tree}")

    # 0.2 frozen candidate identity
    contract_path = DEV_BUNDLE / "canonical_contract.json"
    contract_sha = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    if contract_sha != MISSION_PIN:
        print(f"  frozen {contract_sha}")
        print(f"  pinned  {MISSION_PIN}")
        _stop("CANDIDATE_IDENTITY_MISMATCH")
    print(f"  candidate identity verified: {contract_sha}")

    # 0.3 re-run the independent contract verifier on the frozen DEV bundle
    verdict = vf.verify_bundle(DEV_BUNDLE, MISSION_PIN)
    failed = sorted(k for k, v in verdict["checks"].items() if not v["passed"])
    if not verdict["ok"]:
        print(f"  verifier failures: {failed}")
        _stop("INDEPENDENT_VERIFIER_FAILED")
    print(f"  independent verifier: {len(verdict['checks'])} checks PASS")

    # 0.4 re-run all adversarial attacks
    attacks = adv.run_all_attacks(DEV_BUNDLE)
    for attack in attacks["attacks"]:
        print(f"  {attack['attack_id']:<4} {attack['name']:<32} "
              f"{attack['VERDICT']}")
    if not attacks["ALL_PASSED"] or attacks["ATTACKS_EXECUTED"] != 10:
        _stop("ADVERSARIAL_AUDIT_FAILED")

    # 0.5 readiness flags from the frozen freeze report
    freeze = json.loads((DEV_BUNDLE / "freeze_report.json").read_text(
        encoding="utf-8"))
    if freeze.get("OOS_STRUCTURAL_READY") is not True:
        _stop("OOS_STRUCTURAL_READY_NOT_YES")
    if freeze.get("OOS_ECONOMIC_READY") is not False:
        _stop("OOS_ECONOMIC_READY_NOT_NO")
    if freeze.get("FRICTION_AUTHORITY_COMPLETE") is not False:
        _stop("FRICTION_AUTHORITY_NOT_FAIL_CLOSED")
    print("  OOS_STRUCTURAL_READY=YES · OOS_ECONOMIC_READY=NO · "
          "FRICTION_AUTHORITY_COMPLETE=NO")

    # 0.6 DEV artifacts immutable vs git history
    dev_diff = subprocess.run(
        ["git", "diff", "HEAD", "--", "data/artifacts/target_policy_c3_v1"],
        cwd=ROOT, capture_output=True, text=True).stdout.strip()
    v06_diff = subprocess.run(
        ["git", "diff", "8d132355c0138068fd79a2fb22c9c0f38f295a80", "HEAD",
         "--", "data/artifacts/universal_funnel_v0_6_target_policy"],
        cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dev_diff or v06_diff:
        _stop("DEV_ARTIFACTS_MUTATED")
    print("  DEV artifacts immutable (vs HEAD and vs V0.6 parent 8d13235)")

    # ------------------------------------------------ PHASE 1: DEV references
    print("PHASE 1 — PREREGISTER OOS VERDICT (before any OOS access)")
    evidence = om.evidence_from_dev_frozen(
        DEV_BUNDLE / "dev_resolution_ledger.jsonl",
        V06_DIR / "entry_policy_ledger.jsonl",
        V06_DIR / "objective_sequence_ledger.jsonl")
    dev_refs = om.compute_metrics(evidence)
    pooled = dev_refs["pooled"]

    # sanity: DEV references reproduce the pinned published values
    for key, want in V05_PINNED_QUANTILES.items():
        metric = {"P25": "NATURAL_TARGET_P25_R", "P50": "NATURAL_TARGET_MEDIAN_R",
                  "P75": "NATURAL_TARGET_P75_R"}[key]
        if round(pooled[metric], 3) != want:
            print(f"  {metric} = {pooled[metric]} != pinned {want}")
            _stop("DEV_REFERENCE_REPRODUCTION_FAILED")
    if round(pooled["RUNNER_EXTENDED_REACH"], 6) != V06_PINNED_RUNNER_EXTENDED:
        print(f"  RUNNER_EXTENDED_REACH = {pooled['RUNNER_EXTENDED_REACH']} "
              f"!= pinned {V06_PINNED_RUNNER_EXTENDED}")
        _stop("DEV_REFERENCE_REPRODUCTION_FAILED")
    for key, want in V04_PINNED_FIXED_REACH.items():
        if round(pooled[key], 5) != want:
            print(f"  {key} = {pooled[key]} != pinned {want}")
            _stop("DEV_REFERENCE_REPRODUCTION_FAILED")
    print("  DEV references reproduce pinned V0.4/V0.5/V0.6 values")

    contract = json.loads((DEV_BUNDLE / "canonical_contract.json").read_text(
        encoding="utf-8"))
    prereg = {
        "preregistration_id": "OOS_STRUCTURAL_C3_V1_PREREG_V1",
        "created_at": created_at.isoformat(),
        "recorded_head": head,
        "recorded_tree": tree,
        "pre_oos_implementation": PRE_OOS_IMPLEMENTATION,
        "frozen_candidate": {
            "candidate_id": contract["candidate_id"],
            "version": contract["version"],
            "candidate_sha256": MISSION_PIN,
            "parent_sha": contract["parent_sha"],
            "first_objective_pct": contract["first_objective_pct"],
            "runner_pct": contract["runner_pct"],
            "research_horizon_bars": contract["research_horizon"],
            "horizon_timeframe": contract["horizon_timeframe"],
            "horizon_anchor": contract["horizon_anchor"],
            "horizon_exit_price_authority":
                contract["horizon_exit_price_authority"],
            "same_bar_collision_policy": contract["same_bar_collision_policy"],
            "collision_policy_hash": contract["collision_policy_hash"],
            "runner_stop_policy": contract["runner_stop_policy"],
            "censoring_policy": contract["censoring_policy"],
            "trigger_authority_hash": contract["trigger_authority_hash"],
            "first_target_policy_hash": contract["first_target_policy_hash"],
            "runner_target_policy_hash": contract["runner_target_policy_hash"],
            "fraction_selection_authority":
                contract["fraction_selection_authority"],
        },
        "dataset": {
            "authority": "HISTDATA_ASCII_M1_2017_PR10_PINNED",
            "dataset_id": "HISTDATA_ASCII_M1_2017_PR10_PINNED_OOS_PARTITION",
            "dataset_role": "OOS",
            "symbols": list(om.SYMBOLS),
            "pinned_source_sha256": contract["dataset_pinned_sha256"],
            "oos_window": ["2017-09-01T00:00:00+00:00",
                           "2017-12-01T00:00:00+00:00"],
            "dev_window": ["2017-01-01T00:00:00+00:00",
                           "2017-09-01T00:00:00+00:00"],
            "sealed_holdout_window": ["2017-12-01T00:00:00+00:00",
                                      "2018-01-01T00:00:00+00:00"],
            "overlap_rule": "OOS and DEVELOPMENT windows are disjoint "
                            "half-open intervals; the SEALED_HOLDOUT is "
                            "never sliced or read by any stage",
            "warmup_rule": "frozen V0.3 campaign semantics: 21-day warm-up "
                           "INSIDE the evaluated partition; full 96-bar "
                           "outcome windows required inside the partition",
        },
        "authorities": {
            "entry_authority": "D01_FROZEN_CONTROL (V0.3 campaign chain: "
                               "hourly observation grid, D01 H4 structure "
                               "direction, location ALIGNED, first aligned "
                               "MSS/BOS within 16 bars, entry at "
                               "confirmation close)",
            "sl_authority": "opposite extreme of the last 12 M15 bars "
                            "including the entry bar (frozen V0.3)",
            "target_authority": "V0.5 causal natural-target contracts "
                                "(NT01-NT04 runnable; NT05 fail-closed), "
                                "registry "
                                f"{contract['v0_5_target_registry_sha256']}",
            "first_target": "FIRST_VALID_CAUSAL_OBJECTIVE_AT_ENTRY (nearest "
                            "positive directionally-valid causal objective)",
            "runner_target": "FURTHEST_VALID_CAUSAL_OBJECTIVE_AT_ENTRY "
                             "(strictly beyond the first objective)",
            "horizon": "96 M15 bars from entry bar close; exit at the last "
                       "completed M15 bar close",
            "collision": "STOP_FIRST within every bar (frozen V0.3 "
                         "fail-closed rule)",
            "censoring": contract["censoring_policy"],
            "sessions": contract["session_authority_id"],
        },
        "metric_definitions": {
            "bases": "ENTRY_N = all OOS D01 campaign entries; TRADED_N = "
                     "C3-applicable (first objective exists AND runner "
                     "objective strictly beyond); capabilities and natural-"
                     "target quantiles use the FULL entry population",
            "FIRST_OBJECTIVE_REACHED_PCT": "traded rows whose first leg "
                                           "exits at FIRST_OBJECTIVE / "
                                           "TRADED_N",
            "P_SECOND_GIVEN_FIRST": "among traded rows with the first "
                                    "objective reached, the fraction whose "
                                    "SECOND distinct ladder level was "
                                    "reached before the SL",
            "RUNNER_EXTENDED_REACH": "among traded rows with the first "
                                     "objective reached, the fraction whose "
                                     "runner leg exits at RUNNER_TARGET",
            "Rk_CAPABILITY": "fraction of ALL entries reaching the fixed "
                             "kR level before the frozen SL inside the "
                             "96-bar window (k = 1..5)",
            "NATURAL_TARGET_P25/MEDIAN/P75_R": "quantiles of the first "
                                               "(nearest) causal objective "
                                               "R over entries with a "
                                               "non-empty ladder",
            "GROSS_STRUCTURAL_R": "sum of gross_trade_r over traded "
                                  "(complete termination; NO friction)",
            "MAX_STRUCTURAL_DRAWDOWN_R": "max peak-to-trough decline of "
                                         "cumulative gross R over traded "
                                         "rows ordered by (entry_time, "
                                         "entry_id), running max "
                                         "initialized at 0",
            "UNRESOLVED_RUNNER_N": "traded rows without complete two-leg "
                                   "resolution (must be 0)",
            "RIGHT_CENSORED_N": "windows truncated by the partition "
                                "boundary (RIGHT_CENSORED_DATA_BOUNDARY)",
        },
        "thresholds": om.THRESHOLDS,
        "verdict_semantics": {
            "A": om.VERDICT_NAMES["A"], "B": om.VERDICT_NAMES["B"],
            "C": om.VERDICT_NAMES["C"], "D": om.VERDICT_NAMES["D"],
            "E": om.VERDICT_NAMES["E"],
        },
        "frozen_controls_phase6": {
            "rule": "C3_F50_R0 compared ONLY against the preregistered "
                    "V0.6 focal controls C0_2R and C0_5R on resolved pairs "
                    "(V0.6 registry semantics); no new policy family, no "
                    "fraction grid, no target search",
            "dev_pinned": V06_PINNED_CONTROL_DELTAS,
        },
        "dev_references": dev_refs,
        "economic_firewall": {
            "FRICTION_AUTHORITY_COMPLETE": "NO",
            "ECONOMIC_METRICS": "NOT_ESTIMABLE_NO_FRICTION_AUTHORITY",
            "EDGE_VERIFIED": "FALSE",
            "rule": "no NET_R, net expectancy, net PF, economic win rate, "
                    "economic Sharpe, profitability or EDGE_VERIFIED claim "
                    "may be produced from this OOS run",
        },
        "no_retuning": [
            "no fraction change (50/50 stays; 25/75 and 75/25 forbidden)",
            "no D01 -> T1 switch",
            "no target-family change",
            "no horizon change",
            "no SL change",
            "no collision-policy change",
            "no session change",
            "no alternative OOS candidate run",
        ],
        "single_attempt": "the authorized OOS partition is opened for ONE "
                          "sealed evaluation (determinism double-pass and "
                          "independent verifier reconstruction included in "
                          "the same sealed run); NO SECOND OOS ATTEMPT",
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = (vf.canonical_serialize(prereg) + "\n").encode("utf-8")
    (OUT_DIR / "oos_preregistration.json").write_bytes(payload)
    prereg_sha = hashlib.sha256(payload).hexdigest()
    (OUT_DIR / "oos_preregistration.sha256").write_text(prereg_sha + "\n",
                                                        encoding="utf-8")
    print(f"  wrote oos_preregistration.json")
    print(f"  OOS_PREREGISTRATION_SHA256 = {prereg_sha}")

    print("\nDEV reference summary (pooled):")
    for key in ("ENTRY_N", "TRADED_N", "FIRST_OBJECTIVE_REACHED_PCT",
                "P_SECOND_GIVEN_FIRST", "RUNNER_EXTENDED_REACH",
                "NATURAL_TARGET_MEDIAN_R", "MEAN_STRUCTURAL_R",
                "MEDIAN_STRUCTURAL_R", "MAX_STRUCTURAL_DRAWDOWN_R"):
        print(f"  {key} = {pooled[key]}")
    print("\nPHASE 0 + PHASE 1 COMPLETE — OOS NOT YET OPENED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
