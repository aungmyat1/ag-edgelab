"""Independent verifier for the TARGET_POLICY_C3_V1 sealed structural OOS
run (V0.6.2 mission).

This module NEVER imports the candidate builder
(ag_edgelab.universal.candidate_c3_v1) and never imports the OOS runner.
It reconstructs the OOS evaluation from RAW BARS only:

  1. loads the pinned raw zips itself, re-verifies their sha256 identities,
     re-slices the authorized OOS partition (never the sealed holdout);
  2. re-executes the FROZEN entry authority chain (V0.3 campaign + V0.4
     enrichment + V0.5 records + V0.6 policy entries) to reconstruct the
     candidate population and objective identities;
  3. re-derives every traded outcome with the frozen independent verifier's
     own bar-scan implementation (c3_v1_verifier.derive_trade_outcome);
  4. validates every accounting identity on the serialized OOS ledger
     (reusing the frozen row validator with the authorized OOS window);
  5. recomputes all structural metrics and the preregistered verdict from
     its own reconstruction and compares with the reported artifacts.

Independence boundary (documented, not hidden): the ENTRY authority (D01
direction/location/confirmation/entry/SL and the V0.5 causal target
construction) is the frozen candidate definition itself, so this verifier
re-executes those frozen modules from raw bars — a reproduction, not a
re-implementation. The EXIT/outcome authority (bar scan, accounting,
metrics, verdict) is this module's own / the frozen verifier's own
implementation.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from ag_edgelab.data.fx_histdata_2017 import (
    PINNED_SOURCE_SHA256, SYMBOLS, aggregate_m15, derive_fx_timeframe,
    load_histdata_m1, quality_gate_m1, slice_partition, verify_source_identity)
from ag_edgelab.universal import target_v0_5 as tv5
from ag_edgelab.universal import target_policy_v0_6 as tp6
from ag_edgelab.universal.fx_dev_campaign import run_fx_symbol_campaign
from ag_edgelab.universal.trigger_v0_4 import enrich_symbol
from ag_edgelab.universal import c3_v1_oos_metrics as om
from ag_edgelab.verification import c3_v1_verifier as vf

OOS_ROLE = "OOS"
HORIZON_BARS = 96
LEDGER_NAME = "oos_ledger.jsonl"
ACCOUNTING_NAME = "oos_accounting.json"
METRICS_NAME = "oos_metrics.json"
VERDICT_NAME = "oos_verdict.json"
PREREG_NAME = "oos_preregistration.json"
CONTRACT_NAME = "canonical_contract.json"


# ---------------------------------------------------------------------------
# Reconstruction from raw bars
# ---------------------------------------------------------------------------

def reconstruct_oos(zip_dir: Path) -> dict:
    """Independently reconstruct the OOS population + frames + policy
    entries from the pinned raw zips (frozen authority chain)."""
    from ag_edgelab.data.fx_histdata_2017 import PARTITIONS
    oos_start, oos_end = PARTITIONS[OOS_ROLE]
    frames_by_symbol: dict[str, dict] = {}
    records_by_symbol: dict[str, tuple] = {}
    policy_entries: list = []
    dataset: dict[str, dict] = {}
    for symbol in SYMBOLS:
        zip_path = Path(zip_dir) / f"HISTDATA_COM_ASCII_{symbol}_M1_2017.zip"
        source_sha = verify_source_identity(zip_path, symbol)
        m1 = load_histdata_m1(zip_path)
        quality_gate_m1(m1, symbol)
        m15 = aggregate_m15(slice_partition(m1, OOS_ROLE))
        frames = {"M15": m15}
        for tf in ("H1", "H4", "D1"):
            frames[tf], _ = derive_fx_timeframe(m15, tf, symbol)
        campaign = run_fx_symbol_campaign(frames, symbol, oos_start, oos_end)
        enriched = enrich_symbol(frames, campaign, oos_start, oos_end)
        records = tv5.build_entry_records(frames, campaign, enriched)
        entries = tp6.build_policy_entries(frames, records)
        frames_by_symbol[symbol] = frames
        records_by_symbol[symbol] = records
        policy_entries.extend(entries)
        stamps = [b.timestamp for b in m15]
        dataset[symbol] = {
            "source_sha256": source_sha,
            "pinned_sha256": PINNED_SOURCE_SHA256[symbol],
            "identity_verified": source_sha == PINNED_SOURCE_SHA256[symbol],
            "m15_n": len(m15),
            "first_bar": stamps[0].isoformat() if stamps else None,
            "last_bar": stamps[-1].isoformat() if stamps else None,
            "all_bars_inside_oos_window":
                all(oos_start <= t < oos_end for t in stamps),
        }
    return {"frames_by_symbol": frames_by_symbol,
            "records_by_symbol": records_by_symbol,
            "policy_entries": policy_entries,
            "dataset": dataset}


# ---------------------------------------------------------------------------
# Ledger comparison (population + objective identities)
# ---------------------------------------------------------------------------

def _objective_identity(obj: Mapping | None) -> tuple | None:
    if obj is None:
        return None
    return (obj["family"], obj["price"], obj["target_r"], obj["created_time"])


def compare_population(reconstruction: dict, rows: Sequence[dict]) -> list[str]:
    """Every ledger row must match the independent reconstruction exactly
    (population identity + objective identities)."""
    failures: list[str] = []
    by_id: dict[str, Any] = {}
    for pe in reconstruction["policy_entries"]:
        rec = pe.base
        by_id[pe.entry_id] = pe
    ledger_ids = {row["entry_id"] for row in rows}
    if ledger_ids != set(by_id):
        missing = sorted(set(by_id) - ledger_ids)[:5]
        extra = sorted(ledger_ids - set(by_id))[:5]
        failures.append(
            f"population identity: reconstruction has {len(by_id)} entries, "
            f"ledger has {len(rows)}; missing from ledger {missing}; "
            f"extra in ledger {extra}")
        return failures
    for row in rows:
        pe = by_id[row["entry_id"]]
        rec = pe.base
        rid = row["entry_id"]
        if row["symbol"] != rec.symbol:
            failures.append(f"{rid}: symbol mismatch")
        if row["entry_time"] != rec.entry_time.isoformat():
            failures.append(f"{rid}: entry_time mismatch")
        if row["entry_price"] != rec.entry_price \
                or row["stop_price"] != rec.stop_price:
            failures.append(f"{rid}: entry/stop price mismatch")
        if row["direction"] != rec.direction:
            failures.append(f"{rid}: direction mismatch")
        if bool(row.get("is_t1")) != bool(rec.is_t1):
            failures.append(f"{rid}: is_t1 mismatch")
        first = rec.targets[rec.nearest_family] if rec.nearest_family else None
        expected_first = None if first is None else {
            "family": first.family, "price": first.price,
            "target_r": first.target_r,
            "created_time": first.created_time.isoformat()}
        if _objective_identity(row.get("first_objective")) != \
                _objective_identity(expected_first):
            failures.append(f"{rid}: first objective identity mismatch")
        runner_family = rec.furthest_family \
            if (rec.furthest_family is not None
                and rec.furthest_target_r is not None
                and rec.nearest_target_r is not None
                and rec.furthest_target_r > rec.nearest_target_r) else None
        expected_runner = None
        if runner_family is not None and first is not None:
            t = rec.targets[runner_family]
            expected_runner = {"family": t.family, "price": t.price,
                               "target_r": t.target_r,
                               "created_time": t.created_time.isoformat()}
        if _objective_identity(row.get("runner_objective")) != \
                _objective_identity(expected_runner):
            failures.append(f"{rid}: runner objective identity mismatch")
        rungs = om.normalize_rungs([[r, reached]
                                    for _f, _p, r, reached in rec.ladder])
        if row.get("ladder_rungs") != rungs:
            failures.append(f"{rid}: ladder rungs mismatch")
        if row.get("fixed_reached") != {k: bool(v) for k, v
                                        in rec.fixed_reached.items()}:
            failures.append(f"{rid}: fixed_reached mismatch")
    return failures


# ---------------------------------------------------------------------------
# Deep outcome re-derivation from raw OOS bars
# ---------------------------------------------------------------------------

def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def deep_replay(reconstruction: dict, rows: Sequence[dict]) -> list[str]:
    failures: list[str] = []
    frames_by_symbol = reconstruction["frames_by_symbol"]
    for row in rows:
        if row["status"] not in om.TRADED_STATUSES:
            if row["status"] not in om.NOT_APPLICABLE_STATUSES + \
                    (om.CENSORED_STATUS,):
                failures.append(f"{row['entry_id']}: unknown status "
                                f"{row['status']!r}")
            continue
        bars = frames_by_symbol[row["symbol"]]["M15"]
        entry_ts = _parse_ts(row["entry_time"]) - timedelta(minutes=15)
        idx = vf._bar_index(bars, entry_ts)
        if idx is None:
            failures.append(f"{row['entry_id']}: entry bar not found in "
                            "reconstructed bars")
            continue
        window = bars[idx + 1: idx + 1 + HORIZON_BARS]
        status, first_leg, runner_leg, horizon_close = vf.derive_trade_outcome(
            window, direction=row["direction"],
            entry_price=row["entry_price"], stop_price=row["stop_price"],
            first_price=None if row["first_objective"] is None
            else row["first_objective"]["price"],
            runner_price=None if row["runner_objective"] is None
            else row["runner_objective"]["price"],
            horizon_bars=HORIZON_BARS)
        if status != row["status"]:
            failures.append(f"{row['entry_id']}: status {row['status']} != "
                            f"independent {status}")
            continue
        if not math.isclose(horizon_close, row["horizon_close"],
                            rel_tol=0.0, abs_tol=1e-12):
            failures.append(f"{row['entry_id']}: horizon close differs")
        for leg_name, got, exp in (("first", row["first_leg"], first_leg),
                                   ("runner", row["runner_leg"], runner_leg)):
            if got["exit_bar"] != exp[0] or got["exit_reason"] != exp[2] \
                    or not math.isclose(got["exit_price"], exp[1],
                                        rel_tol=0.0, abs_tol=1e-12) \
                    or not math.isclose(got["leg_r"], exp[3],
                                        rel_tol=0.0, abs_tol=1e-12):
                failures.append(f"{row['entry_id']}: {leg_name} leg "
                                f"{got} != independent {exp}")
    return failures


# ---------------------------------------------------------------------------
# OOS bundle verification
# ---------------------------------------------------------------------------

def verify_oos_bundle(bundle_dir: Path | str, zip_dir: Path | str,
                      pinned_contract_sha256: str) -> dict:
    bundle = Path(bundle_dir)
    checks: dict[str, dict] = {}
    failures: list[str] = []

    def record(name: str, ok: bool, detail: str = "", info: str = "") -> bool:
        checks[name] = {"passed": bool(ok),
                        "detail": (detail if not ok else info)}
        if not ok:
            failures.append(f"{name}: {detail}" if detail else name)
        return ok

    from ag_edgelab.data.fx_histdata_2017 import PARTITIONS
    oos_start, oos_end = PARTITIONS[OOS_ROLE]
    dev_start, dev_end = PARTITIONS["DEVELOPMENT"]

    # ---- 1. frozen candidate identity (contract copy == mission pin)
    contract_bytes = (bundle / CONTRACT_NAME).read_bytes()
    contract_sha = vf.sha256_bytes(contract_bytes)
    record("candidate_identity", contract_sha == pinned_contract_sha256,
           f"contract copy {contract_sha[:16]}… != pinned "
           f"{pinned_contract_sha256[:16]}…")
    contract = json.loads(contract_bytes.decode("utf-8"))
    record("contract_path_b_bytes",
           vf.canonical_serialize(contract).encode("utf-8") == contract_bytes,
           "canonical re-serialization differs from contract file bytes")

    # ---- 2. preregistration integrity + pre-open binding
    prereg_bytes = (bundle / PREREG_NAME).read_bytes()
    prereg = json.loads(prereg_bytes.decode("utf-8"))
    prereg_sha = vf.sha256_bytes(prereg_bytes)
    companion = (bundle / "oos_preregistration.sha256").read_text(
        encoding="utf-8").strip()
    record("preregistration_integrity",
           companion == prereg_sha
           and prereg.get("candidate_sha256") == pinned_contract_sha256
           and prereg.get("dataset_role") == OOS_ROLE,
           f"companion {companion[:16]}… vs file {prereg_sha[:16]}…; "
           "candidate pin or dataset role wrong")

    # ---- 3. ledger rows + OOS window discipline
    rows = [json.loads(line) for line in
            (bundle / LEDGER_NAME).read_text(encoding="utf-8").splitlines()
            if line]
    window_fail: list[str] = []
    for row in rows:
        entry_time = _parse_ts(row["entry_time"])
        if not (oos_start <= entry_time < oos_end):
            window_fail.append(f"{row['entry_id']}: entry outside OOS window")
        if row.get("window_last_bar_time"):
            last = _parse_ts(row["window_last_bar_time"])
            if last > oos_end:
                window_fail.append(
                    f"{row['entry_id']}: outcome window crosses the OOS/"
                    "holdout boundary")
        if dev_start <= entry_time < dev_end:
            window_fail.append(f"{row['entry_id']}: entry inside DEV window")
    record("oos_window_discipline", not window_fail,
           "; ".join(window_fail[:5]) if window_fail else "",
           info=f"{len(rows)} rows inside "
                f"[{oos_start.isoformat()}, {oos_end.isoformat()})")

    ids = [r.get("entry_id") for r in rows]
    record("unique_entry_ids", len(ids) == len(set(ids)),
           "duplicate entry ids")

    # ---- 4. independent reconstruction from raw bars
    reconstruction = reconstruct_oos(Path(zip_dir))
    dataset = reconstruction["dataset"]
    record("dataset_identity",
           all(v["identity_verified"] and v["all_bars_inside_oos_window"]
               for v in dataset.values()),
           "raw dataset identity or OOS window violation")
    pop_failures = compare_population(reconstruction, rows)
    record("population_reconstruction", not pop_failures,
           "; ".join(pop_failures[:5]) if pop_failures else "",
           info=(f"{len(rows)} entries reconstructed from raw bars "
                 "(identity, geometry, objectives, ladders, fixed reach)"))

    # ---- 5. accounting identities (frozen row validator, OOS window)
    patched = dict(contract)
    patched["dataset_partitions"] = {
        "DEVELOPMENT": [oos_start.isoformat(), oos_end.isoformat()]}
    row_failures = vf.validate_ledger_rows(rows, patched)
    record("row_accounting_and_causality", not row_failures,
           "; ".join(row_failures[:5]) if row_failures else "")

    # ---- 6. deep outcome re-derivation from raw OOS bars
    deep_failures = deep_replay(reconstruction, rows)
    traded_n = sum(1 for r in rows if r["status"] in om.TRADED_STATUSES)
    record("deep_replay_independent", not deep_failures,
           "; ".join(deep_failures[:5]) if deep_failures else "",
           info=f"{traded_n} traded outcomes re-derived bar-by-bar")

    # ---- 7. accounting artifact aggregates
    try:
        accounting = json.loads(
            (bundle / ACCOUNTING_NAME).read_text(encoding="utf-8"))
        aggregates = vf.recompute_aggregates(rows)
        agg_fail = []
        for key in ("population_n", "traded_n", "not_applicable_n",
                    "censored_n", "status_counts", "censored_entry_ids"):
            if accounting.get(key) != aggregates[key]:
                agg_fail.append(f"{key}: {accounting.get(key)!r} != "
                                f"{aggregates[key]!r}")
        if not math.isclose((accounting.get("gross_r_sum") or 0.0),
                            aggregates["gross_r_sum"],
                            rel_tol=0.0, abs_tol=1e-9):
            agg_fail.append("gross_r_sum")
        if accounting.get("dataset_role") != OOS_ROLE:
            agg_fail.append(f"dataset_role {accounting.get('dataset_role')!r}")
        if accounting.get("unresolved_runner_n") != 0:
            agg_fail.append("unresolved_runner_n != 0")
        if accounting.get("net_economics_claimed") is not False:
            agg_fail.append("net economics claimed")
        record("accounting_aggregates", not agg_fail,
               "; ".join(agg_fail) if agg_fail else "")
    except (OSError, json.JSONDecodeError) as exc:
        record("accounting_aggregates", False, f"unreadable: {exc}")

    # ---- 8. metrics + verdict recomputation from the reconstruction
    try:
        evidence = om.evidence_from_pipeline(
            reconstruction["records_by_symbol"], rows)
        metrics = om.compute_metrics(evidence)
        reported = json.loads(
            (bundle / METRICS_NAME).read_text(encoding="utf-8"))
        metric_fail = _compare_metrics(metrics, reported)
        record("metrics_reproduction", not metric_fail,
               "; ".join(metric_fail) if metric_fail else "",
               info="all pooled + per-symbol metrics recomputed from the "
                    "independent reconstruction")

        dev_refs = prereg["dev_references"]
        verdict = om.evaluate_verdict(metrics, dev_refs,
                                      prereg.get("thresholds")
                                      or om.THRESHOLDS)
        reported_verdict = json.loads(
            (bundle / VERDICT_NAME).read_text(encoding="utf-8"))
        verdict_fail = []
        if reported_verdict.get("FINAL_VERDICT") != verdict["FINAL_VERDICT"]:
            verdict_fail.append(
                f"final verdict {reported_verdict.get('FINAL_VERDICT')} != "
                f"independent {verdict['FINAL_VERDICT']}")
        for symbol in SYMBOLS:
            got = reported_verdict.get("by_symbol", {}).get(symbol, {})
            if got.get("verdict") != verdict["by_symbol"][symbol]["verdict"]:
                verdict_fail.append(
                    f"{symbol}: {got.get('verdict')} != "
                    f"{verdict['by_symbol'][symbol]['verdict']}")
        record("verdict_reproduction", not verdict_fail,
               "; ".join(verdict_fail) if verdict_fail else "")
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        record("metrics_reproduction", False, f"unreadable: {exc}")
        record("verdict_reproduction", False, f"unreadable: {exc}")

    return {"ok": not failures, "failures": failures, "checks": checks,
            "preregistration_sha256": prereg_sha,
            "dataset": dataset}


def _close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-9)
    return a == b


def _compare_metrics(recomputed: dict, reported: dict) -> list[str]:
    failures = []
    keys = list(recomputed["pooled"])
    for key in keys:
        if key not in reported.get("pooled", {}):
            failures.append(f"pooled.{key} missing")
        elif not _close(recomputed["pooled"][key], reported["pooled"][key]):
            failures.append(f"pooled.{key}: {reported['pooled'][key]!r} != "
                            f"{recomputed['pooled'][key]!r}")
    for symbol in SYMBOLS:
        for key in keys:
            got = reported.get("by_symbol", {}).get(symbol, {}).get(key)
            exp = recomputed["by_symbol"][symbol][key]
            if not _close(exp, got):
                failures.append(f"{symbol}.{key}: {got!r} != {exp!r}")
    return failures
