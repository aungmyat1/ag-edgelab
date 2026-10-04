"""V0.6.2 — SEALED STRUCTURAL OOS VERIFICATION of TARGET_POLICY_C3_V1.

STRUCTURAL OOS ONLY. NO ECONOMIC CLAIM. NO RETUNING. NO SECOND OOS ATTEMPT.

Modes:

  --validate-dev-only (pre-open validation, reads DEVELOPMENT only):
      re-runs the frozen pipeline on the DEV partition through THIS
      script's replay/metrics code path and requires the computed metrics
      to reproduce the preregistered DEV references exactly. No OOS bar
      is read in this mode.

  default (the sealed OOS run):
      phase 2  — single authorized OOS partition open (pinned zips,
                 2017-09-01..2017-12-01, holdout never sliced) +
                 no-overlap verification;
      phase 3  — the frozen candidate reproduced exactly (D01 trigger,
                 50/50, first = nearest causal objective, runner =
                 furthest causal objective, R0 original SL, 96 M15 bars,
                 last completed M15 close horizon exit, STOP_FIRST);
      phase 4  — structural metrics;
      phase 5  — DEV <-> OOS generalization deltas (pooled + per symbol);
      phase 6  — runner hypothesis + preregistered frozen controls
                 (C0_2R, C0_5R only);
      phase 9  — causality audit on OOS (created_time <= entry_time,
                 truncation + future-mutation invariance);
      phase 7  — the PREREGISTERED verdict (thresholds frozen in
                 oos_preregistration.json before the OOS open);
      phase 10 — independent reproduction from raw OOS bars by
                 ag_edgelab.verification.c3_v1_oos_verifier;
      phase 8  — economic firewall (no net metrics; EDGE_VERIFIED=FALSE).

The OOS partition is opened for exactly one sealed evaluation: the
determinism double-pass and the independent verifier reconstruction are
part of the same sealed run. No result is inspected before the verdict is
computed, and nothing is retuned afterwards.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.contracts.market import MarketBar  # noqa: E402
from ag_edgelab.data.derive import TIMEFRAME_MINUTES  # noqa: E402
from ag_edgelab.data.fingerprint import sha256_json  # noqa: E402
from ag_edgelab.data.fx_histdata_2017 import (  # noqa: E402
    PARTITIONS, PINNED_SOURCE_SHA256, SYMBOLS, aggregate_m15,
    bars_closed_at, derive_fx_timeframe, load_histdata_m1, quality_gate_m1,
    slice_partition, verify_source_identity)
from ag_edgelab.universal import c3_v1_oos_metrics as om  # noqa: E402
from ag_edgelab.universal import candidate_c3_v1 as cand  # noqa: E402
from ag_edgelab.universal import target_policy_v0_6 as tp6  # noqa: E402
from ag_edgelab.universal import target_v0_5 as tv5  # noqa: E402
from ag_edgelab.universal.direction import Direction  # noqa: E402
from ag_edgelab.universal.fx_dev_campaign import run_fx_symbol_campaign  # noqa: E402
from ag_edgelab.universal.targets import EntryGeometry  # noqa: E402
from ag_edgelab.universal.trigger_v0_4 import enrich_symbol  # noqa: E402
from ag_edgelab.verification import c3_v1_oos_verifier as oosv  # noqa: E402
from ag_edgelab.verification import c3_v1_verifier as vf  # noqa: E402

MISSION_PIN = "5a485308841d1c5d2096e348665ef3f9b1f689c1ed4ce4b30385eeaf2c828112"
DEV_BUNDLE = ROOT / "data" / "artifacts" / "target_policy_c3_v1"
OUT_DIR = ROOT / "data" / "artifacts" / "target_policy_c3_v1_oos"
ZIP_DIR = ROOT / "data" / "external" / "histdata_fx_2017"
OOS_ROLE = "OOS"
OOS_ID_PREFIX = "OOS:"
AUDIT_SAMPLES_PER_SYMBOL = 4
HORIZON_BARS = 96

MISSION_SOURCE_FILES = (
    "src/ag_edgelab/universal/c3_v1_oos_metrics.py",
    "src/ag_edgelab/verification/c3_v1_oos_verifier.py",
    "scripts/preregister_oos_c3_v1.py",
    "scripts/run_oos_structural_c3_v1.py",
    "tests/test_oos_c3_v1.py",
)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stop(code: str) -> None:
    print(f"STOP = {code}", file=sys.stderr)
    raise SystemExit(2)


# ---------------------------------------------------------------------------
# Frozen pipeline, partition-parameterized (phase 3)
# ---------------------------------------------------------------------------

def compute_partition(zip_dir: Path, role: str) -> dict:
    """The frozen V0.3-V0.6 pipeline on the requested authorized partition.
    No parameter depends on the data; `role` only selects the slice."""
    start, end = PARTITIONS[role]
    records_by_symbol: dict[str, tuple] = {}
    frames_by_symbol: dict[str, dict] = {}
    policy_entries: list = []
    dataset: dict[str, dict] = {}
    for symbol in SYMBOLS:
        zip_path = Path(zip_dir) / f"HISTDATA_COM_ASCII_{symbol}_M1_2017.zip"
        source_sha = verify_source_identity(zip_path, symbol)
        m1 = load_histdata_m1(zip_path)
        quality_gate_m1(m1, symbol)
        m15 = aggregate_m15(slice_partition(m1, role))
        frames = {"M15": m15}
        for tf in ("H1", "H4", "D1"):
            frames[tf], _ = derive_fx_timeframe(m15, tf, symbol)
        campaign = run_fx_symbol_campaign(frames, symbol, start, end)
        enriched = enrich_symbol(frames, campaign, start, end)
        records = tv5.build_entry_records(frames, campaign, enriched)
        entries = tp6.build_policy_entries(frames, records)
        records_by_symbol[symbol] = records
        frames_by_symbol[symbol] = frames
        policy_entries.extend(entries)
        stamps = [b.timestamp for b in m15]
        dataset[symbol] = {
            "source_sha256": source_sha,
            "pinned_sha256": PINNED_SOURCE_SHA256[symbol],
            "identity_verified": source_sha == PINNED_SOURCE_SHA256[symbol],
            "m15_n": len(m15),
            "first_bar_open": stamps[0].isoformat(),
            "last_bar_open": stamps[-1].isoformat(),
            "all_bars_inside_partition": all(start <= t < end for t in stamps),
        }
    return {"role": role,
            "records_by_symbol": records_by_symbol,
            "frames_by_symbol": frames_by_symbol,
            "entries": policy_entries, "dataset": dataset,
            "partition": (start, end)}


# ---------------------------------------------------------------------------
# Candidate replay (identical frozen semantics for any partition)
# ---------------------------------------------------------------------------

def replay_candidate(computed: dict, id_prefix: str) -> tuple[list[dict], dict]:
    """Replay the frozen C3 candidate on the computed population with
    complete termination. `id_prefix` namespaces entry ids per partition
    (OOS ids are prefixed so they can never collide with DEV ids)."""
    part_start, part_end = computed["partition"]
    rows: list[dict] = []
    diag = {"causality_violations": 0, "censored": [], "status_counts": {},
            "runner_gating_violations": 0, "window_violations": 0}
    for pe in computed["entries"]:
        rec = pe.base
        m15 = computed["frames_by_symbol"][rec.symbol]["M15"]
        forward = m15[rec.entry_index + 1:
                      rec.entry_index + 1 + HORIZON_BARS]
        first = pe.first
        furthest = pe.furthest if rec.furthest_target_r is not None else None
        runner_ok = (first is not None and furthest is not None
                     and furthest.r > first.r)

        first_obj = None
        runner_obj = None
        if first is not None:
            t = rec.targets[first.family]
            first_obj = {"family": first.family, "price": first.price,
                         "target_r": first.r,
                         "created_time": t.created_time.isoformat()}
            if t.created_time > rec.entry_time:
                diag["causality_violations"] += 1
        if runner_ok:
            t = rec.targets[furthest.family]
            runner_obj = {"family": furthest.family, "price": furthest.price,
                          "target_r": furthest.r,
                          "created_time": t.created_time.isoformat()}
            if t.created_time > rec.entry_time:
                diag["causality_violations"] += 1

        if first_obj is None:
            status = "NOT_APPLICABLE_NO_OBJECTIVE"
        elif runner_obj is None:
            status = "NOT_APPLICABLE_NO_RUNNER_OBJECTIVE"
        else:
            status = None

        resolution = None
        if status is None:
            resolution = cand.resolve_trade(
                forward, direction=rec.direction,
                entry_price=rec.entry_price, stop_price=rec.stop_price,
                first_price=first_obj["price"], first_r=first_obj["target_r"],
                runner_price=runner_obj["price"],
                runner_r=runner_obj["target_r"])
            status = resolution.status
            if resolution.censored:
                diag["censored"].append(id_prefix + pe.entry_id)

        window_last = None
        horizon_close = None
        if len(forward) >= HORIZON_BARS:
            last_bar = forward[HORIZON_BARS - 1]
            window_last = (last_bar.timestamp
                           + timedelta(minutes=15)).isoformat()
            if not (part_start < datetime.fromisoformat(window_last)
                    <= part_end):
                diag["window_violations"] += 1
            horizon_close = resolution.horizon_close if resolution else \
                last_bar.close

        first_leg = None
        runner_leg = None
        gross = None
        if resolution is not None and not resolution.censored:
            first_leg = {"pct": resolution.first_leg.pct,
                         "exit_bar": resolution.first_leg.exit_bar,
                         "exit_price": resolution.first_leg.exit_price,
                         "exit_reason": resolution.first_leg.exit_reason,
                         "leg_r": resolution.first_leg.leg_r}
            runner_leg = {"pct": resolution.runner_leg.pct,
                          "exit_bar": resolution.runner_leg.exit_bar,
                          "exit_price": resolution.runner_leg.exit_price,
                          "exit_reason": resolution.runner_leg.exit_reason,
                          "leg_r": resolution.runner_leg.leg_r}
            gross = resolution.gross_trade_r
            if runner_leg["exit_reason"] == "RUNNER_TARGET" \
                    and runner_leg["exit_bar"] < first_leg["exit_bar"]:
                diag["runner_gating_violations"] += 1

        rows.append({
            "entry_id": id_prefix + pe.entry_id,
            "symbol": rec.symbol,
            "entry_time": rec.entry_time.isoformat(),
            "direction": rec.direction,
            "session": rec.session,
            "is_t1": bool(rec.is_t1),
            "entry_price": rec.entry_price,
            "stop_price": rec.stop_price,
            "risk_distance": rec.risk_distance,
            "first_objective": first_obj,
            "runner_objective": runner_obj,
            "ladder_rungs": om.normalize_rungs(
                [[r, reached] for _f, _p, r, reached in rec.ladder]),
            "fixed_reached": {str(k): bool(v)
                              for k, v in rec.fixed_reached.items()},
            "status": status,
            "first_leg": first_leg,
            "runner_leg": runner_leg,
            "gross_trade_r": gross,
            "net_trade_r": None,
            "friction_status": "UNAVAILABLE_NO_REPOSITORY_AUTHORITY",
            "horizon_close": horizon_close,
            "stop_bar": pe.stop_bar,
            "window_last_bar_time": window_last,
            "censored": bool(resolution.censored) if resolution else False,
        })
        diag["status_counts"][status] = diag["status_counts"].get(status, 0) + 1
    return rows, diag


def build_accounting(rows: list[dict], diag: dict, role: str) -> dict:
    traded = [r for r in rows if r["status"] in om.TRADED_STATUSES]
    gross = [r["gross_trade_r"] for r in traded]
    censored_ids = sorted(r["entry_id"] for r in rows if r["censored"])
    unresolved = [r["entry_id"] for r in traded
                  if r["first_leg"] is None or r["runner_leg"] is None
                  or r["gross_trade_r"] is None]
    start, end = PARTITIONS[role]
    return {
        "candidate_id": cand.CANDIDATE_ID,
        "candidate_version": cand.CANDIDATE_VERSION,
        "dataset_role": role,
        "dataset_window": [start.isoformat(), end.isoformat()],
        "symbols": list(SYMBOLS),
        "population_n": len(rows),
        "t1_subset_n": sum(1 for r in rows if r["is_t1"]),
        "traded_n": len(traded),
        "not_applicable_n": sum(1 for r in rows
                                if r["status"] in om.NOT_APPLICABLE_STATUSES),
        "censored_n": len(censored_ids),
        "censored_entry_ids": censored_ids,
        "unresolved_runner_n": len(unresolved),
        "unresolved_entry_ids": unresolved,
        "status_counts": dict(sorted(diag["status_counts"].items())),
        "gross_r_sum": sum(gross) if gross else 0.0,
        "gross_r_mean": (sum(gross) / len(gross)) if gross else None,
        "contract_horizon_bars": HORIZON_BARS,
        "friction_authority_complete": False,
        "net_economics_claimed": False,
    }


# ---------------------------------------------------------------------------
# Causality audit (phase 9)
# ---------------------------------------------------------------------------

def _mutate_after(bars, timeframe, as_of):
    span = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
    return tuple(
        b if b.timestamp + span <= as_of else
        MarketBar(timestamp=b.timestamp, open=b.open * 1.1, high=b.high * 1.1,
                  low=b.low * 1.1, close=b.close * 1.1)
        for b in bars)


def causality_audit(computed: dict, rows: list[dict], diag: dict) -> dict:
    part_start, part_end = computed["partition"]
    audit = {
        "objective_causality_all_rows": {
            "checked": len(rows),
            "violations": diag["causality_violations"],
            "rule": "objective.created_time <= entry_time for every "
                    "first/runner objective (no future target)"},
        "runner_gating_all_rows": {
            "violations": diag["runner_gating_violations"],
            "rule": "runner payoff bar >= first-objective payoff bar"},
        "window_inside_partition": {
            "violations": diag["window_violations"],
            "partition": [part_start.isoformat(), part_end.isoformat()],
            "rule": "every outcome window closes inside the evaluated "
                    "partition; the sealed holdout is never read"},
        "invariants": [
            "natural target selection unchanged under post-entry mutation "
            "(x1.1) and truncation across M15/H4/D1",
            "entry, SL, first/runner target identity, fraction, horizon are "
            "independent of any post-entry-bar mutation",
            "no future objective substitution (created_time <= entry_time)",
        ],
        "samples": [],
    }
    by_symbol: dict[str, list] = {}
    for pe in computed["entries"]:
        by_symbol.setdefault(pe.base.symbol, []).append(pe)
    for symbol in SYMBOLS:
        entries = by_symbol.get(symbol, [])
        frames = computed["frames_by_symbol"][symbol]
        step = max(1, len(entries) // (AUDIT_SAMPLES_PER_SYMBOL + 1))
        for pe in entries[step::step][:AUDIT_SAMPLES_PER_SYMBOL]:
            rec = pe.base
            geometry = EntryGeometry(Direction(rec.direction), rec.entry_price,
                                     rec.stop_price)
            expected = {f: (t.price, t.created_time.isoformat())
                        for f, t in rec.targets.items() if t is not None}
            variants = {}
            for name in ("truncated", "mutated"):
                vframes = {}
                for tf in ("M15", "H4", "D1"):
                    if name == "truncated":
                        vframes[tf] = bars_closed_at(frames[tf], tf,
                                                     rec.entry_time)
                    else:
                        vframes[tf] = _mutate_after(frames[tf], tf,
                                                    rec.entry_time)
                vctx = tv5.build_symbol_context(vframes)
                cands = tv5._natural_candidates(vctx, geometry, rec.entry_time)
                variants[name] = {f: (c[0], c[1].isoformat())
                                  for f, c in cands.items() if c is not None}
            audit["samples"].append({
                "symbol": symbol,
                "entry_time": rec.entry_time.isoformat(),
                "truncation_invariant": variants["truncated"] == expected,
                "future_mutation_invariant": variants["mutated"] == expected,
            })
    audit["selection_invariance_all_passed"] = all(
        s["truncation_invariant"] and s["future_mutation_invariant"]
        for s in audit["samples"])
    audit["all_passed"] = (
        diag["causality_violations"] == 0
        and diag["runner_gating_violations"] == 0
        and diag["window_violations"] == 0
        and audit["selection_invariance_all_passed"])
    return audit


# ---------------------------------------------------------------------------
# Frozen controls (phase 6; C0_2R / C0_5R only)
# ---------------------------------------------------------------------------

def frozen_controls(computed: dict) -> dict:
    entries = computed["entries"]
    outcomes = tp6.evaluate_all(entries)

    def block(rows):
        return {
            "vs_C0_2R": tp6.paired_delta(rows, outcomes, "C3_F50_R0", "C0_2R"),
            "vs_C0_5R": tp6.paired_delta(rows, outcomes, "C3_F50_R0", "C0_5R"),
        }

    return {
        "rule": "C3_F50_R0 vs the preregistered V0.6 focal controls only "
                "(C0_2R, C0_5R; V0.6 registry semantics, resolved pairs); "
                "no new policy family, no fraction grid, no target search",
        "pooled": block(entries),
        "by_symbol": {s: block([pe for pe in entries
                                if pe.base.symbol == s]) for s in SYMBOLS},
    }


def runner_hypothesis(metrics: dict, controls: dict, prereg: dict) -> dict:
    pooled = metrics["pooled"]
    return {
        "hypothesis": "after reaching the first causal objective, a "
                      "meaningful subset of trades continues sufficiently "
                      "far for the frozen runner architecture to remain "
                      "structurally useful",
        "P_SECOND_GIVEN_FIRST": pooled["P_SECOND_GIVEN_FIRST"],
        "RUNNER_EXTENDED_REACH": pooled["RUNNER_EXTENDED_REACH"],
        "runner_contribution_r": pooled["RUNNER_CONTRIBUTION_R"],
        "runner_target_contribution_r":
            pooled["RUNNER_TARGET_CONTRIBUTION_R"],
        "runner_loss_contribution_r": pooled["RUNNER_LOSS_CONTRIBUTION_R"],
        "runner_horizon_close_contribution_r":
            pooled["RUNNER_HORIZON_CLOSE_CONTRIBUTION_R"],
        "first_leg_contribution_r": pooled["FIRST_LEG_CONTRIBUTION_R"],
        "runner_outcome_counts": {
            "RUNNER_TARGET_N": pooled["RUNNER_TARGET_N"],
            "RUNNER_STOP_N": pooled["RUNNER_STOP_N"],
            "RUNNER_HORIZON_N": pooled["RUNNER_HORIZON_N"]},
        "controls": controls,
        "dev_pinned_controls":
            prereg["frozen_controls_phase6"]["dev_pinned"],
    }


# ---------------------------------------------------------------------------
# One full evaluation materialization (determinism unit)
# ---------------------------------------------------------------------------

def _materialize(computed: dict, prereg: dict, id_prefix: str) -> dict[str, bytes]:
    rows, diag = replay_candidate(computed, id_prefix)
    accounting = build_accounting(rows, diag, computed["role"])
    evidence = om.evidence_from_pipeline(
        computed["records_by_symbol"], rows, id_prefix=id_prefix)
    metrics = om.compute_metrics(evidence)
    comparison = om.compare_dev_oos(metrics, prereg["dev_references"])
    controls = frozen_controls(computed)
    hypothesis = runner_hypothesis(metrics, controls, prereg)
    return {
        "oos_ledger.jsonl": "".join(
            json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
            for r in rows).encode("utf-8"),
        "oos_accounting.json":
            vf.canonical_serialize(accounting).encode("utf-8") + b"\n",
        "oos_metrics.json":
            vf.canonical_serialize(metrics).encode("utf-8") + b"\n",
        "dev_oos_comparison.json":
            vf.canonical_serialize(comparison).encode("utf-8") + b"\n",
        "runner_hypothesis.json":
            vf.canonical_serialize(hypothesis).encode("utf-8") + b"\n",
    }


# ---------------------------------------------------------------------------
# Pre-open validation (DEV only; no OOS bar is read)
# ---------------------------------------------------------------------------

def validate_dev(prereg: dict) -> dict:
    print("PRE-OPEN VALIDATION — frozen pipeline on DEVELOPMENT (no OOS read)")
    computed = compute_partition(ZIP_DIR, "DEVELOPMENT")
    rows, diag = replay_candidate(computed, id_prefix="")
    evidence = om.evidence_from_pipeline(
        computed["records_by_symbol"], rows, id_prefix="")
    metrics = om.compute_metrics(evidence)
    dev_refs = prereg["dev_references"]
    failures = []

    def close(a, b) -> bool:
        if a is None or b is None:
            return a is None and b is None
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(float(a) - float(b)) <= 1e-9
        return a == b

    scopes = [("pooled", metrics["pooled"], dev_refs["pooled"])] + [
        (s, metrics["by_symbol"][s], dev_refs["by_symbol"][s])
        for s in SYMBOLS]
    for scope, got, want in scopes:
        for key, expected in want.items():
            if not close(got.get(key), expected):
                failures.append(f"{scope}.{key}: pipeline {got.get(key)!r} "
                                f"!= prereg {expected!r}")
    if failures:
        for line in failures[:10]:
            print(f"  MISMATCH {line}")
        _stop("DEV_VALIDATION_FAILED")
    print(f"  all pooled + per-symbol metrics reproduce the preregistered "
          f"DEV references ({len(dev_refs['pooled'])} metrics x 5 scopes)")
    return {"validated": True,
            "metrics_checked": len(dev_refs["pooled"]) * 5,
            "failures": 0}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    argv = sys.argv[1:]
    validate_only = "--validate-dev-only" in argv
    reverify_only = "--reverify-only" in argv

    # ---- gate: preregistration integrity + candidate identity
    prereg_bytes = (OUT_DIR / "oos_preregistration.json").read_bytes()
    prereg = json.loads(prereg_bytes.decode("utf-8"))
    prereg_sha = hashlib.sha256(prereg_bytes).hexdigest()
    companion = (OUT_DIR / "oos_preregistration.sha256").read_text(
        encoding="utf-8").strip()
    committed = subprocess.run(
        ["git", "show",
         "HEAD:data/artifacts/target_policy_c3_v1_oos/"
         "oos_preregistration.json"],
        cwd=ROOT, check=True, capture_output=True).stdout
    if prereg_sha != companion \
            or hashlib.sha256(committed).hexdigest() != prereg_sha:
        _stop("PREREGISTRATION_INTEGRITY")
    if prereg["frozen_candidate"]["candidate_sha256"] != MISSION_PIN:
        _stop("CANDIDATE_IDENTITY_MISMATCH")
    if hashlib.sha256(
            (DEV_BUNDLE / "canonical_contract.json").read_bytes()
            ).hexdigest() != MISSION_PIN:
        _stop("CANDIDATE_IDENTITY_MISMATCH")
    print(f"  preregistration verified: {prereg_sha}")
    print(f"  candidate identity verified: {MISSION_PIN}")

    if validate_only:
        validate_dev(prereg)
        print("PRE-OPEN VALIDATION COMPLETE — OOS NOT OPENED")
        return 0

    if reverify_only:
        return reverify(prereg, prereg_sha)

    # ================================================= the sealed OOS open
    print("PHASE 2 — SINGLE OOS DATA OPEN (authorized partition)")
    oos_start, oos_end = PARTITIONS[OOS_ROLE]
    dev_start, dev_end = PARTITIONS["DEVELOPMENT"]
    print(f"  OOS window: [{oos_start.isoformat()}, {oos_end.isoformat()})")
    print(f"  sealed holdout (never read): "
          f"[{PARTITIONS['SEALED_HOLDOUT'][0].isoformat()}, "
          f"{PARTITIONS['SEALED_HOLDOUT'][1].isoformat()})")
    if not (dev_end <= oos_start < oos_end):
        _stop("DATASET_ROLE_CONTAMINATION")

    print("PHASE 3 — REPRODUCE FROZEN PIPELINE (double pass, determinism)")
    computed_1 = compute_partition(ZIP_DIR, OOS_ROLE)
    pass_1 = _materialize(computed_1, prereg, OOS_ID_PREFIX)
    computed_2 = compute_partition(ZIP_DIR, OOS_ROLE)
    pass_2 = _materialize(computed_2, prereg, OOS_ID_PREFIX)
    determinism = {
        "run_1_sha256": {k: hashlib.sha256(v).hexdigest()
                         for k, v in sorted(pass_1.items())},
        "run_2_sha256": {k: hashlib.sha256(v).hexdigest()
                         for k, v in sorted(pass_2.items())},
        "byte_identical": pass_1 == pass_2,
        "scope": "two full independent computations of the frozen pipeline "
                 "on the authorized OOS partition (population, replay "
                 "ledger, accounting, metrics, comparison, controls)",
    }
    if not determinism["byte_identical"]:
        print("STATUS=NONDETERMINISTIC", file=sys.stderr)
        return 3
    print("  determinism: byte-identical double pass")

    # contamination / overlap verification on the opened partition
    dataset = computed_1["dataset"]
    for symbol, info in dataset.items():
        if not info["identity_verified"] or not info["all_bars_inside_partition"]:
            _stop("DATASET_ROLE_CONTAMINATION")
    ledger_rows, diag = replay_candidate(computed_1, OOS_ID_PREFIX)
    for row in ledger_rows:
        entry_time = datetime.fromisoformat(row["entry_time"])
        if not (oos_start <= entry_time < oos_end) \
                or (dev_start <= entry_time < dev_end):
            _stop("DATASET_ROLE_CONTAMINATION")
    print(f"  dataset identities verified; no DEV/OOS overlap "
          f"({len(ledger_rows)} OOS entries, all inside the OOS window)")

    print("PHASE 4 — STRUCTURAL METRICS")
    evidence = om.evidence_from_pipeline(
        computed_1["records_by_symbol"], ledger_rows, id_prefix=OOS_ID_PREFIX)
    metrics = om.compute_metrics(evidence)
    accounting = build_accounting(ledger_rows, diag, OOS_ROLE)
    pooled = metrics["pooled"]
    print(f"  ENTRY_N={pooled['ENTRY_N']} TRADED_N={pooled['TRADED_N']} "
          f"FIRST_OBJECTIVE_REACH={pooled['FIRST_OBJECTIVE_REACHED_PCT']:.4f} "
          f"P_SECOND_GIVEN_FIRST={pooled['P_SECOND_GIVEN_FIRST']:.4f} "
          f"RUNNER_EXTENDED_REACH={pooled['RUNNER_EXTENDED_REACH']:.4f}")
    print(f"  MEAN_STRUCTURAL_R={pooled['MEAN_STRUCTURAL_R']:.6f} "
          f"MEDIAN={pooled['MEDIAN_STRUCTURAL_R']:.6f} "
          f"GROSS={pooled['GROSS_STRUCTURAL_R']:.4f} "
          f"MAX_DD={pooled['MAX_STRUCTURAL_DRAWDOWN_R']:.4f}")

    print("PHASE 5 — DEV <-> OOS GENERALIZATION")
    dev_refs = prereg["dev_references"]
    comparison = om.compare_dev_oos(metrics, dev_refs)
    for symbol in SYMBOLS:
        d = comparison["by_symbol"][symbol]["FIRST_OBJECTIVE_REACHED_PCT"]
        m = comparison["by_symbol"][symbol]["MEAN_STRUCTURAL_R"]
        print(f"  {symbol}: dFirstReach={d['delta']:+.2f}pp "
              f"dMeanR={m['delta']:+.6f}")

    print("PHASE 6 — RUNNER HYPOTHESIS (frozen controls only)")
    controls = frozen_controls(computed_1)
    print(f"  runner contribution R={pooled['RUNNER_CONTRIBUTION_R']:.4f} "
          f"(target {pooled['RUNNER_TARGET_CONTRIBUTION_R']:.4f}, "
          f"loss {pooled['RUNNER_LOSS_CONTRIBUTION_R']:.4f}, "
          f"horizon {pooled['RUNNER_HORIZON_CLOSE_CONTRIBUTION_R']:.4f})")
    dev_pin_2r = prereg["frozen_controls_phase6"]["dev_pinned"][
        "C3_F50_R0_vs_C0_2R"]
    print(f"  vs C0_2R: mean paired delta "
          f"{controls['pooled']['vs_C0_2R']['mean_delta_r']:+.6f} "
          f"({controls['pooled']['vs_C0_2R']['pair_n']} pairs) | DEV pinned "
          f"{dev_pin_2r['mean_delta_r']:+.6f}")

    print("PHASE 9 — CAUSALITY (OOS)")
    causality = causality_audit(computed_1, ledger_rows, diag)
    if not causality["all_passed"]:
        print("STATUS=CAUSALITY_AUDIT_FAILED", file=sys.stderr)
        return 4
    print(f"  causality: 0 violations, "
          f"{len(causality['samples'])}/{len(causality['samples'])} "
          f"selection-invariance samples pass")

    print("PHASE 7 — PREREGISTERED VERDICT")
    verdict = om.evaluate_verdict(metrics, dev_refs,
                                  prereg.get("thresholds") or om.THRESHOLDS)
    for symbol in SYMBOLS:
        res = verdict["by_symbol"][symbol]
        print(f"  {symbol}: {res['verdict']} (traded {res['traded_n']})")
    print(f"  pooled: {verdict['pooled']['verdict']}")
    print(f"  FINAL (pre-verification): {verdict['FINAL_VERDICT']} — "
          f"{verdict['FINAL_VERDICT_NAME']}")

    print("PHASE 10 — INDEPENDENT REPRODUCTION (raw OOS bars)")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in pass_1.items():
        (OUT_DIR / name).write_bytes(payload)
    (OUT_DIR / "causality_audit.json").write_bytes(
        vf.canonical_serialize(causality).encode("utf-8") + b"\n")
    (OUT_DIR / "determinism_report.json").write_bytes(
        vf.canonical_serialize(determinism).encode("utf-8") + b"\n")
    (OUT_DIR / "oos_verdict.json").write_bytes(
        vf.canonical_serialize(verdict).encode("utf-8") + b"\n")
    shutil.copyfile(DEV_BUNDLE / "canonical_contract.json",
                    OUT_DIR / "canonical_contract.json")

    independent = oosv.verify_oos_bundle(OUT_DIR, ZIP_DIR, MISSION_PIN)
    (OUT_DIR / "independent_verification.json").write_bytes(
        vf.canonical_serialize(independent).encode("utf-8") + b"\n")
    for name, check in sorted(independent["checks"].items()):
        line = f"  {'PASS' if check['passed'] else 'FAIL'}  {name}"
        if not check["passed"] and check["detail"]:
            line += f" — {check['detail']}"
        print(line)
    independent_ok = independent["ok"]

    # -------------------------------------------------- E conditions + final
    return _finalize(
        prereg=prereg, prereg_sha=prereg_sha, metrics=metrics,
        comparison=comparison, verdict=verdict, controls=controls,
        accounting=accounting, causality=causality, determinism=determinism,
        independent_ok=independent_ok, contamination_ok=True, notes=None)


def _finalize(*, prereg: dict, prereg_sha: str, metrics: dict,
              comparison: dict, verdict: dict, controls: dict,
              accounting: dict, causality: dict, determinism: dict,
              independent_ok: bool, contamination_ok: bool,
              notes: str | None) -> int:
    pooled = metrics["pooled"]
    oos_start, oos_end = PARTITIONS[OOS_ROLE]
    e_conditions = {
        "candidate_identity": True,          # gated above (else STOP)
        "preregistration_integrity": True,   # gated above (else STOP)
        "dataset_role_contamination": contamination_ok,
        "causality": causality["all_passed"],
        "independent_reproduction": independent_ok,
        "determinism": determinism["byte_identical"],
        "unresolved_runner": accounting["unresolved_runner_n"] == 0,
        "censoring_accounting": (
            accounting["censored_n"] == len(accounting["censored_entry_ids"])
            and accounting["traded_n"] + accounting["not_applicable_n"]
            + accounting["censored_n"] == accounting["population_n"]),
    }
    verification_valid = all(e_conditions.values())
    final_verdict = verdict["FINAL_VERDICT"] if verification_valid else "E"

    implementation_sha = sha256_json({
        rel: _sha256_file(ROOT / rel) for rel in sorted(MISSION_SOURCE_FILES)})

    status_by_verdict = {
        "A": ("STRUCTURAL_OOS_COMPLETE",
              "FREEZE_OOS_RESULT_AND_SEEK_FRICTION_AUTHORITY"),
        "B": ("STRUCTURAL_OOS_COMPLETE",
              "FREEZE_OOS_RESULT_AND_SEEK_FRICTION_AUTHORITY"),
        "C": ("STRUCTURAL_GENERALIZATION_FAILED", "STOP_CANDIDATE"),
        "D": ("INSUFFICIENT_OOS_SAMPLE",
              "COLLECT_MORE_PREDECLARED_OOS_EVIDENCE"),
        "E": ("VERIFICATION_INVALID", "STOP_CANDIDATE"),
    }
    status, next_step = status_by_verdict[final_verdict]

    final_report = {
        "IMPLEMENTATION_SHA": implementation_sha,
        "TREE_SHA": "git tree of the OOS results commit (reported in the "
                    "mission return; a file cannot contain its own tree "
                    "hash)",
        "CANDIDATE_ID": cand.CANDIDATE_ID,
        "CANDIDATE_SHA256": MISSION_PIN,
        "CANDIDATE_IDENTITY_VERIFIED": "YES",
        "OOS_PREREGISTRATION_SHA256": prereg_sha,
        "OOS_DATASET_ID": prereg["dataset"]["dataset_id"],
        "OOS_DATASET_SHA256": {s: PINNED_SOURCE_SHA256[s] for s in SYMBOLS},
        "OOS_WINDOW": f"[{oos_start.isoformat()}, {oos_end.isoformat()})",
        "DEV_OOS_OVERLAP": "NONE",
        "ENTRY_N": pooled["ENTRY_N"],
        "FIRST_OBJECTIVE_REACH": pooled["FIRST_OBJECTIVE_REACHED_PCT"],
        "P_SECOND_GIVEN_FIRST": pooled["P_SECOND_GIVEN_FIRST"],
        "RUNNER_EXTENDED_REACH": pooled["RUNNER_EXTENDED_REACH"],
        "1R_CAPABILITY": pooled["R1_CAPABILITY"],
        "2R_CAPABILITY": pooled["R2_CAPABILITY"],
        "3R_CAPABILITY": pooled["R3_CAPABILITY"],
        "4R_CAPABILITY": pooled["R4_CAPABILITY"],
        "5R_CAPABILITY": pooled["R5_CAPABILITY"],
        "NATURAL_TARGET_MEDIAN_R": pooled["NATURAL_TARGET_MEDIAN_R"],
        "GROSS_STRUCTURAL_R": pooled["GROSS_STRUCTURAL_R"],
        "MEAN_STRUCTURAL_R": pooled["MEAN_STRUCTURAL_R"],
        "MEDIAN_STRUCTURAL_R": pooled["MEDIAN_STRUCTURAL_R"],
        "MAX_STRUCTURAL_DRAWDOWN_R": pooled["MAX_STRUCTURAL_DRAWDOWN_R"],
        "UNRESOLVED_RUNNER_N": accounting["unresolved_runner_n"],
        "RIGHT_CENSORED_N": accounting["censored_n"],
        "CAUSALITY": "PASS" if causality["all_passed"] else "FAIL",
        "INDEPENDENT_REPRODUCTION": "PASS" if independent_ok else "FAIL",
        "DETERMINISM": "PASS" if determinism["byte_identical"] else "FAIL",
        "FRICTION_AUTHORITY_COMPLETE": "NO",
        "ECONOMIC_METRICS": "NOT_ESTIMABLE_NO_FRICTION_AUTHORITY",
        "EDGE_VERIFIED": "FALSE",
        "OOS_STRUCTURAL_VERDICT": final_verdict,
        "OOS_STRUCTURAL_VERDICT_NAME": om.VERDICT_NAMES[final_verdict],
        "STRATEGY_RULES_CHANGED": "NO",
        "ENTRY_CHANGED": "NO",
        "SL_CHANGED": "NO",
        "TARGET_CHANGED": "NO",
        "HOLDOUT_TOUCHED": "NO",
        "EXECUTION_CAPABILITY_ADDED": "NO",
        "STATUS": status,
        "NEXT": next_step,
    }
    if notes:
        final_report["VERIFICATION_NOTES"] = notes
    for symbol in SYMBOLS:
        symbol_verdict = verdict["by_symbol"][symbol]["verdict"]
        final_report[f"{symbol}_VERDICT"] = (
            "D" if symbol_verdict == "D_SUBSAMPLED" else symbol_verdict)
    final_report["POOLED_GENERALIZATION"] = verdict["pooled"]["verdict"]

    covered = ["oos_ledger.jsonl", "oos_accounting.json", "oos_metrics.json",
               "dev_oos_comparison.json", "runner_hypothesis.json",
               "causality_audit.json", "determinism_report.json",
               "oos_verdict.json"]
    entries = [{"artifact": name, "sha256": _sha256_file(OUT_DIR / name)}
               for name in sorted(covered)]
    (OUT_DIR / "artifact_manifest.json").write_bytes(
        vf.canonical_serialize(entries).encode("utf-8") + b"\n")

    (OUT_DIR / "final_report.json").write_bytes(
        vf.canonical_serialize(final_report).encode("utf-8") + b"\n")
    (OUT_DIR / "final_report.md").write_text(
        _render_markdown(final_report, metrics, comparison, verdict,
                         controls, prereg),
        encoding="utf-8")

    print(json.dumps(final_report, indent=2, sort_keys=True, default=str))
    print(f"STATUS={status}")
    print(f"OOS_STRUCTURAL_VERDICT={final_verdict}")
    return 0


SEALED_EVIDENCE_FILES = [
    "oos_ledger.jsonl", "oos_accounting.json", "oos_metrics.json",
    "dev_oos_comparison.json", "runner_hypothesis.json",
    "causality_audit.json", "determinism_report.json", "oos_verdict.json",
    "canonical_contract.json"]


def reverify(prereg: dict, prereg_sha: str) -> int:
    """Re-execute ONLY phase-10 verification against the sealed artifacts.

    Purpose (V0.6.2 incident): the initial sealed run reported E because the
    verifier's preregistration_integrity check read the candidate pin and
    dataset role at the wrong JSON nesting level — a tooling bug in the
    CHECK, not an integrity failure (the runner's startup gate had already
    verified companion==file==committed prereg and pin==mission pin BEFORE
    the OOS open). This mode re-runs verification with the fixed check. The
    evaluation is NOT recomputed: the sealed evidence files must be
    byte-identical to the sealed-evaluation commit, else STOP.
    """
    print("RE-VERIFICATION ONLY — sealed evaluation artifacts NOT recomputed")
    for name in SEALED_EVIDENCE_FILES:
        committed = subprocess.run(
            ["git", "show",
             f"HEAD:data/artifacts/target_policy_c3_v1_oos/{name}"],
            cwd=ROOT, check=True, capture_output=True).stdout
        if committed != (OUT_DIR / name).read_bytes():
            _stop("SEALED_ARTIFACT_MODIFIED")
    print(f"  {len(SEALED_EVIDENCE_FILES)} sealed evidence files "
          f"byte-identical to the sealed-evaluation commit (HEAD)")

    metrics = json.loads(
        (OUT_DIR / "oos_metrics.json").read_text(encoding="utf-8"))
    comparison = json.loads(
        (OUT_DIR / "dev_oos_comparison.json").read_text(encoding="utf-8"))
    hypothesis = json.loads(
        (OUT_DIR / "runner_hypothesis.json").read_text(encoding="utf-8"))
    verdict = json.loads(
        (OUT_DIR / "oos_verdict.json").read_text(encoding="utf-8"))
    accounting = json.loads(
        (OUT_DIR / "oos_accounting.json").read_text(encoding="utf-8"))
    causality = json.loads(
        (OUT_DIR / "causality_audit.json").read_text(encoding="utf-8"))
    determinism = json.loads(
        (OUT_DIR / "determinism_report.json").read_text(encoding="utf-8"))
    controls = hypothesis["controls"]

    print("PHASE 10 (re-run) — INDEPENDENT REPRODUCTION "
          "(raw OOS bars; fixed prereg check)")
    independent = oosv.verify_oos_bundle(OUT_DIR, ZIP_DIR, MISSION_PIN)
    (OUT_DIR / "independent_verification.json").write_bytes(
        vf.canonical_serialize(independent).encode("utf-8") + b"\n")
    for name, check in sorted(independent["checks"].items()):
        line = f"  {'PASS' if check['passed'] else 'FAIL'}  {name}"
        if not check["passed"] and check["detail"]:
            line += f" — {check['detail']}"
        print(line)
    contamination_ok = (
        independent["checks"]["oos_window_discipline"]["passed"]
        and independent["checks"]["dataset_identity"]["passed"])

    notes = (
        "Initial sealed run (sealed-evaluation commit, phase 10 of the same "
        "single authorized OOS open) reported verdict E because the "
        "verifier's preregistration_integrity check read the candidate pin "
        "and dataset role at the wrong JSON nesting level — a tooling bug "
        "in the check itself, not an integrity failure. The runner's "
        "startup gate had already verified companion==file==git-committed "
        "preregistration and embedded pin==mission pin BEFORE the OOS "
        "partition was opened, and the printed check detail showed "
        "companion==file. The check was fixed "
        "(check_preregistration_integrity, unit-tested) and phase-10 "
        "verification re-executed. The evaluation artifacts (ledger, "
        "accounting, metrics, comparison, controls, hypothesis, verdict, "
        "causality, determinism) are byte-identical to the "
        "sealed-evaluation commit (asserted at reverify startup). No "
        "evaluation was recomputed, no parameter, rule, or threshold was "
        "changed, and no second evaluation attempt was made. This is the "
        "same sealed run's verification step, completed.")
    return _finalize(
        prereg=prereg, prereg_sha=prereg_sha, metrics=metrics,
        comparison=comparison, verdict=verdict, controls=controls,
        accounting=accounting, causality=causality, determinism=determinism,
        independent_ok=independent["ok"], contamination_ok=contamination_ok,
        notes=notes)


def _render_markdown(report, metrics, comparison, verdict, controls,
                     prereg) -> str:
    lines = [
        "# V0.6.2 — SEALED STRUCTURAL OOS VERIFICATION — TARGET_POLICY_C3_V1",
        "",
        "STRUCTURAL OOS ONLY · NO ECONOMIC CLAIM · NO RETUNING · "
        "NO SECOND OOS ATTEMPT",
        "",
        "## REQUIRED RETURN",
        "",
    ]
    for key, value in report.items():
        lines.append(f"{key} = {value}")
    lines += [
        "",
        "## OOS structural metrics (pooled)",
        "",
    ]
    for key, value in metrics["pooled"].items():
        lines.append(f"- {key} = {value}")
    lines += [
        "",
        "## DEV -> OOS deltas (pooled; negative = OOS weaker)",
        "",
    ]
    for key, block in comparison["pooled"].items():
        if block["delta"] is not None:
            unit = "pp" if block.get("delta_pp") else "R"
            lines.append(f"- {key}: DEV {block['dev']:.6f} -> OOS "
                         f"{block['oos']:.6f} "
                         f"(delta {block['delta']:+.4f} {unit})")
    lines += [
        "",
        "## Per-symbol verdicts",
        "",
    ]
    for symbol in SYMBOLS:
        res = verdict["by_symbol"][symbol]
        lines.append(f"- {symbol}: {res['verdict']} (traded {res['traded_n']})")
    lines += [
        "",
        "## Runner hypothesis (phase 6, frozen controls only)",
        "",
        f"- P_SECOND_GIVEN_FIRST = "
        f"{metrics['pooled']['P_SECOND_GIVEN_FIRST']}",
        f"- RUNNER_EXTENDED_REACH = "
        f"{metrics['pooled']['RUNNER_EXTENDED_REACH']}",
        f"- runner contribution to structural R = "
        f"{metrics['pooled']['RUNNER_CONTRIBUTION_R']:.4f} "
        f"(target {metrics['pooled']['RUNNER_TARGET_CONTRIBUTION_R']:.4f}, "
        f"loss {metrics['pooled']['RUNNER_LOSS_CONTRIBUTION_R']:.4f}, "
        f"horizon-close "
        f"{metrics['pooled']['RUNNER_HORIZON_CLOSE_CONTRIBUTION_R']:.4f})",
    ]
    for control, block in controls["pooled"].items():
        dev_pin = prereg["frozen_controls_phase6"]["dev_pinned"][
            "C3_F50_R0_" + control]
        lines.append(
            f"- {control}: OOS mean paired delta "
            f"{block['mean_delta_r']:+.6f} over {block['pair_n']} pairs "
            f"(DEV pinned {dev_pin['mean_delta_r']:+.6f} over "
            f"{dev_pin['pair_n']} pairs)")
    lines += [
        "",
        "## Notes",
        "",
        "- The OOS partition was opened ONCE for this sealed evaluation "
        "(2017-09-01..2017-12-01, pinned HistData identities verified); "
        "the sealed holdout was never sliced or read.",
        "- The verdict thresholds were preregistered and committed "
        "(oos_preregistration.json) BEFORE the OOS partition was opened; "
        "the preregistration hash is bound into this report.",
        "- All metrics are GROSS STRUCTURAL quantities with complete "
        "termination; NO friction, NO net-R, NO profitability claim "
        "(FRICTION_AUTHORITY_COMPLETE = NO).",
        "- No retuning occurred after the result: fraction, trigger, "
        "targets, SL, horizon, collision policy and sessions are exactly "
        "the frozen candidate's.",
        "- TREE_SHA is the git tree of the OOS results commit (a file "
        "cannot contain its own tree hash); see the mission return.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
