"""REAL adversarial audit for the TARGET_POLICY_C3_V1 frozen bundle.

Every attack (A1..A10) performs an actual mutation on a COPY of the frozen
bundle, then runs the INDEPENDENT verifier (c3_v1_verifier) with the TRUE
published pinned contract hash. Nothing here is hard-coded to pass: each
attack must genuinely produce a rejection, or the audit records FAIL.

Where meaningful, a second "semantic layer" verification is run with the
ATTACKER's own contract hash (simulating a forged publication): the
semantic checks (causality, population pinning, accounting, frozen facts,
friction derivation) must still catch the substitution.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from ag_edgelab.verification import c3_v1_verifier as vf

LEDGER = "dev_resolution_ledger.jsonl"
CONTRACT = "canonical_contract.json"
ACCOUNTING = "dev_accounting.json"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _pinned_hash(bundle: Path) -> str:
    return vf.sha256_bytes((bundle / CONTRACT).read_bytes())


def _load_rows(bundle: Path) -> list[dict]:
    return [json.loads(line) for line in
            (bundle / LEDGER).read_text(encoding="utf-8").splitlines() if line]


def _write_rows(bundle: Path, rows: list[dict]) -> None:
    (bundle / LEDGER).write_text(
        "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
                for r in rows), encoding="utf-8")


def _load_contract(bundle: Path) -> dict:
    return json.loads((bundle / CONTRACT).read_text(encoding="utf-8"))


def _write_contract(bundle: Path, contract: dict) -> str:
    content = vf.canonical_serialize(contract).encode("utf-8")
    (bundle / CONTRACT).write_bytes(content)
    return vf.sha256_bytes(content)


def _rewrite_manifest(bundle: Path) -> str:
    return vf.write_manifest(bundle)


def _fresh_copy(bundle: Path) -> Path:
    tmp = tempfile.mkdtemp(prefix="c3_attack_")
    copy = Path(tmp) / "bundle"
    shutil.copytree(bundle, copy)
    return copy


def _verify(bundle: Path, pinned: str, deep_bars=None) -> dict:
    return vf.verify_bundle(bundle, pinned, deep_bars=deep_bars)


def _semantic_layer(bundle: Path, deep_bars=None) -> dict:
    """Verify with the attacker's own (forged) pin: only semantic checks
    can catch the substitution here."""
    return _verify(bundle, _pinned_hash(bundle), deep_bars=deep_bars)


def _record(attack_id: str, name: str, mutation: str, expected: str,
            actual: dict, semantic: dict | None = None) -> dict:
    rejected = not actual["ok"]
    if semantic is not None:
        rejected = rejected and (not semantic["ok"])
    return {
        "attack_id": attack_id,
        "name": name,
        "ATTACK_EXECUTED": "YES",
        "MUTATION": mutation,
        "EXPECTED": expected,
        "ACTUAL": {
            "verifier_rejected": not actual["ok"],
            "failed_checks": actual["failures"][:8],
            "passed_checks": sorted(k for k, v in actual["checks"].items()
                                    if v["passed"]),
        },
        "SEMANTIC_LAYER": None if semantic is None else {
            "attacker_pin_rejected": not semantic["ok"],
            "failed_checks": semantic["failures"][:8],
        },
        "VERDICT": "PASS" if rejected else "FAIL",
    }


def _first_row(rows: list[dict], status: str) -> dict:
    for row in rows:
        if row["status"] == status:
            return row
    raise AssertionError(f"no row with status {status}")


# ---------------------------------------------------------------------------
# A1 — FUTURE_TARGET_SUBSTITUTION
# ---------------------------------------------------------------------------

def attack_a1(bundle: Path, pinned: str, deep_bars=None) -> dict:
    copy = _fresh_copy(bundle)
    rows = _load_rows(copy)
    row = dict(_first_row(rows, "FIRST_PLUS_RUNNER_TARGET"))
    entry_time = row["entry_time"]
    # fabricate a future-created runner target (created AFTER entry)
    fake_price = round(row["entry_price"] * (1.10 if row["direction"] == "BULL"
                                             else 0.90), 6)
    from datetime import datetime
    created = (datetime.fromisoformat(entry_time) + timedelta(days=2)).isoformat()
    row["runner_objective"] = {
        "family": "NT01_NEXT_CONFIRMED_STRUCTURAL_SWING",
        "price": fake_price,
        "target_r": 10.0,
        "created_time": created,
    }
    # strong attacker: make the leg internally consistent with the fake target
    row["runner_leg"] = {
        "pct": 0.5, "exit_bar": row["runner_leg"]["exit_bar"],
        "exit_price": fake_price, "exit_reason": "RUNNER_TARGET",
        "leg_r": 0.5 * 10.0,
    }
    row["gross_trade_r"] = row["first_leg"]["leg_r"] + row["runner_leg"]["leg_r"]
    rows = [row if r["entry_id"] == row["entry_id"] else r for r in rows]
    _write_rows(copy, rows)
    _rewrite_manifest(copy)
    # strongest attacker: rebind the manifest hash inside the contract too
    contract = _load_contract(copy)
    contract["dev_evidence_manifest_sha256"] = vf.manifest_hash(
        vf.build_manifest_entries(copy))
    _write_contract(copy, contract)
    actual = _verify(copy, pinned, deep_bars)
    semantic = _semantic_layer(copy, deep_bars)
    shutil.rmtree(copy.parent)
    return _record(
        "A1", "FUTURE_TARGET_SUBSTITUTION",
        f"row {row['entry_id']}: runner objective replaced with a "
        f"future-created target (created_time {created} > entry_time "
        f"{entry_time}); ledger, manifest and contract binding rewritten",
        "verifier must reject: pinned contract hash mismatch AND causal "
        "created_time <= entry_time violation",
        actual, semantic)


# ---------------------------------------------------------------------------
# A2 — FRACTION_SUBSTITUTION
# ---------------------------------------------------------------------------

def attack_a2(bundle: Path, pinned: str, deep_bars=None) -> dict:
    copy = _fresh_copy(bundle)
    contract = _load_contract(copy)
    contract["first_objective_pct"] = 75
    contract["runner_pct"] = 25
    mutated_hash = _write_contract(copy, contract)
    rows = _load_rows(copy)
    for row in rows:
        for leg_name in ("first_leg", "runner_leg"):
            leg = row.get(leg_name)
            if leg is not None:
                # strong attacker: recompute leg R consistently at 75/25
                scale = 1.5 if leg_name == "first_leg" else 0.5
                leg["pct"] = 0.75 if leg_name == "first_leg" else 0.25
                leg["leg_r"] = leg["leg_r"] * scale
        if row.get("gross_trade_r") is not None:
            row["gross_trade_r"] = (row["first_leg"]["leg_r"]
                                    + row["runner_leg"]["leg_r"])
    _write_rows(copy, rows)
    _rewrite_manifest(copy)
    contract = _load_contract(copy)
    contract["dev_evidence_manifest_sha256"] = vf.manifest_hash(
        vf.build_manifest_entries(copy))
    _write_contract(copy, contract)
    actual = _verify(copy, pinned, deep_bars)
    semantic = _semantic_layer(copy, deep_bars)
    shutil.rmtree(copy.parent)
    record = _record(
        "A2", "FRACTION_SUBSTITUTION",
        "contract fractions 50/50 -> 75/25; all ledger leg fractions "
        "rewritten; manifest + contract binding rewritten",
        "candidate identity (canonical hash) must CHANGE and the original "
        "verifier (pinned 50/50 hash) must reject",
        actual, semantic)
    record["IDENTITY_CHANGE"] = {
        "frozen_hash": pinned,
        "mutated_hash": mutated_hash,
        "changed": mutated_hash != pinned,
    }
    if not record["IDENTITY_CHANGE"]["changed"]:
        record["VERDICT"] = "FAIL"
    return record


# ---------------------------------------------------------------------------
# A3 — RUNNER_STOP_SUBSTITUTION
# ---------------------------------------------------------------------------

def attack_a3(bundle: Path, pinned: str, deep_bars=None) -> dict:
    copy = _fresh_copy(bundle)
    contract = _load_contract(copy)
    contract["runner_stop_policy"] = "R1_BREAKEVEN_AFTER_FIRST_OBJECTIVE"
    _write_contract(copy, contract)
    rows = _load_rows(copy)
    row = dict(_first_row(rows, "FIRST_PLUS_RUNNER_STOP"))
    # attacker moves the runner stop to break-even: runner exits at entry
    row["runner_leg"] = {
        "pct": 0.5, "exit_bar": row["runner_leg"]["exit_bar"],
        "exit_price": row["entry_price"], "exit_reason": "BE",
        "leg_r": 0.0,
    }
    row["gross_trade_r"] = row["first_leg"]["leg_r"] + 0.0
    rows = [row if r["entry_id"] == row["entry_id"] else r for r in rows]
    _write_rows(copy, rows)
    _rewrite_manifest(copy)
    contract = _load_contract(copy)
    contract["dev_evidence_manifest_sha256"] = vf.manifest_hash(
        vf.build_manifest_entries(copy))
    _write_contract(copy, contract)
    actual = _verify(copy, pinned, deep_bars)
    semantic = _semantic_layer(copy, deep_bars)
    shutil.rmtree(copy.parent)
    return _record(
        "A3", "RUNNER_STOP_SUBSTITUTION",
        f"runner_stop_policy R0 -> R1 break-even; row {row['entry_id']} "
        "runner leg rewritten to a break-even exit at entry price",
        "verifier must reject: pinned hash mismatch, runner-stop frozen "
        "fact, unknown exit reason, leg/geometry inconsistency",
        actual, semantic)


# ---------------------------------------------------------------------------
# A4 — HORIZON_SUBSTITUTION
# ---------------------------------------------------------------------------

def attack_a4(bundle: Path, pinned: str, deep_bars=None) -> dict:
    copy = _fresh_copy(bundle)
    contract = _load_contract(copy)
    contract["research_horizon"] = 48
    contract["horizon_exit_price_authority"] = (
        "M15_OPEN_OF_FIRST_BAR_AFTER_HORIZON (mutated)")
    _write_contract(copy, contract)
    rows = _load_rows(copy)
    row = dict(_first_row(rows, "FIRST_PLUS_RUNNER_HORIZON"))
    row["runner_leg"]["exit_bar"] = 48
    rows = [row if r["entry_id"] == row["entry_id"] else r for r in rows]
    _write_rows(copy, rows)
    _rewrite_manifest(copy)
    contract = _load_contract(copy)
    contract["dev_evidence_manifest_sha256"] = vf.manifest_hash(
        vf.build_manifest_entries(copy))
    _write_contract(copy, contract)
    actual = _verify(copy, pinned, deep_bars)
    semantic = _semantic_layer(copy, deep_bars)
    shutil.rmtree(copy.parent)
    return _record(
        "A4", "HORIZON_SUBSTITUTION",
        "research_horizon 96 -> 48 M15 bars; horizon exit price authority "
        "mutated to an open-price fill; a horizon-exit row moved to bar 48",
        "verifier must reject: pinned hash mismatch, horizon frozen fact "
        "(96 M15_BARS from ENTRY_BAR_CLOSE_TIME), exit-bar consistency",
        actual, semantic)


# ---------------------------------------------------------------------------
# A5 — FRICTION_SUBSTITUTION
# ---------------------------------------------------------------------------

def attack_a5(bundle: Path, pinned: str, deep_bars=None) -> dict:
    copy = _fresh_copy(bundle)
    contract = _load_contract(copy)
    # strongest attacker: invent a spread value, store it under a NEW
    # content address, rebind the contract, and claim authority complete
    table = json.loads((copy / "evidence" / f'{contract["friction_table_hash"]}.json').read_text())
    table["EURUSD"]["spread"] = 0.00012
    table["EURUSD"]["provenance"] = "invented by attacker"
    content = vf.canonical_serialize(table).encode("utf-8")
    new_hash = vf.sha256_bytes(content)
    (copy / "evidence" / f"{new_hash}.json").write_bytes(content)
    contract["friction_table_hash"] = new_hash
    contract["friction_authority_complete_derived"] = True
    _write_contract(copy, contract)
    _rewrite_manifest(copy)
    contract = _load_contract(copy)
    contract["dev_evidence_manifest_sha256"] = vf.manifest_hash(
        vf.build_manifest_entries(copy))
    _write_contract(copy, contract)
    actual = _verify(copy, pinned, deep_bars)
    semantic = _semantic_layer(copy, deep_bars)
    shutil.rmtree(copy.parent)
    return _record(
        "A5", "FRICTION_SUBSTITUTION",
        "friction table EURUSD spread UNAVAILABLE -> 0.00012 (invented "
        "value) under a new content address; contract rebound; "
        "friction_authority_complete_derived forced to true",
        "verifier must reject: pinned hash mismatch AND the derived "
        "friction-authority check must refuse a table without "
        "repository-pinned provenance",
        actual, semantic)


# ---------------------------------------------------------------------------
# A6 — TARGET_FAMILY_SUBSTITUTION
# ---------------------------------------------------------------------------

def attack_a6(bundle: Path, pinned: str, deep_bars=None) -> dict:
    copy = _fresh_copy(bundle)
    contract = _load_contract(copy)
    # replace the runner target-family authority with the fail-closed NT05
    policy = json.loads(
        (copy / "evidence" / f'{contract["runner_target_policy_hash"]}.json').read_text())
    policy["runner_target_policy_id"] = "NT05_NEXT_VALID_ORDER_BLOCK"
    policy["rule"] = "runner exits at the next causal order block (mutated)"
    content = vf.canonical_serialize(policy).encode("utf-8")
    new_hash = vf.sha256_bytes(content)
    (copy / "evidence" / f"{new_hash}.json").write_bytes(content)
    contract["runner_target_policy_id"] = "NT05_NEXT_VALID_ORDER_BLOCK"
    contract["runner_target_policy_hash"] = new_hash
    contract["target_family_contracts"]["NT05_NEXT_VALID_ORDER_BLOCK"][
        "status"] = "CONTRACT_COMPLETE"
    _write_contract(copy, contract)
    rows = _load_rows(copy)
    row = dict(_first_row(rows, "FIRST_PLUS_RUNNER_TARGET"))
    row["runner_objective"]["family"] = "NT05_NEXT_VALID_ORDER_BLOCK"
    rows = [row if r["entry_id"] == row["entry_id"] else r for r in rows]
    _write_rows(copy, rows)
    _rewrite_manifest(copy)
    contract = _load_contract(copy)
    contract["dev_evidence_manifest_sha256"] = vf.manifest_hash(
        vf.build_manifest_entries(copy))
    _write_contract(copy, contract)
    actual = _verify(copy, pinned, deep_bars)
    semantic = _semantic_layer(copy, deep_bars)
    shutil.rmtree(copy.parent)
    return _record(
        "A6", "TARGET_FAMILY_SUBSTITUTION",
        "runner target-family authority replaced with NT05 order block "
        "(declared CONTRACT_COMPLETE by the attacker); a ledger row's "
        "runner objective family swapped to NT05",
        "verifier must reject: pinned hash mismatch, runner policy frozen "
        "fact, NT05 must remain fail-closed TARGET_FAMILY_CONTRACT_INCOMPLETE",
        actual, semantic)


# ---------------------------------------------------------------------------
# A7 — POPULATION_SUBSTITUTION
# ---------------------------------------------------------------------------

def attack_a7(bundle: Path, pinned: str, deep_bars=None) -> dict:
    copy = _fresh_copy(bundle)
    rows = _load_rows(copy)
    t1_rows = [r for r in rows if r.get("is_t1")]
    _write_rows(copy, t1_rows)
    accounting = json.loads((copy / ACCOUNTING).read_text(encoding="utf-8"))
    accounting["population_n"] = len(t1_rows)
    accounting["status_counts"] = vf.recompute_aggregates(t1_rows)["status_counts"]
    (copy / ACCOUNTING).write_text(
        vf.canonical_serialize(accounting), encoding="utf-8")
    _rewrite_manifest(copy)
    contract = _load_contract(copy)
    contract["dev_evidence_manifest_sha256"] = vf.manifest_hash(
        vf.build_manifest_entries(copy))
    _write_contract(copy, contract)
    actual = _verify(copy, pinned, deep_bars)
    semantic = _semantic_layer(copy, deep_bars)
    shutil.rmtree(copy.parent)
    return _record(
        "A7", "POPULATION_SUBSTITUTION",
        f"D01 population ({len(rows)} rows) replaced with the T1 entry "
        f"population ({len(t1_rows)} rows); accounting + manifest + "
        "contract binding rewritten",
        "verifier must reject: pinned hash mismatch AND population pin "
        f"(D01 ENTRY_N must be {vf.EXPECTED_POPULATION_N})",
        actual, semantic)


# ---------------------------------------------------------------------------
# A8 — DATASET_ROLE_SUBSTITUTION
# ---------------------------------------------------------------------------

def attack_a8(bundle: Path, pinned: str, deep_bars=None) -> dict:
    copy = _fresh_copy(bundle)
    # (1) role mismatch in the accounting artifact
    accounting = json.loads((copy / ACCOUNTING).read_text(encoding="utf-8"))
    accounting["dataset_role"] = "OOS"
    accounting["dataset_window"] = ["2017-09-01T00:00:00+00:00",
                                    "2017-12-01T00:00:00+00:00"]
    (copy / ACCOUNTING).write_text(
        vf.canonical_serialize(accounting), encoding="utf-8")
    # (2) a ledger row moved into the OOS window
    rows = _load_rows(copy)
    row = dict(rows[0])
    row["entry_time"] = "2017-09-15T10:45:00+00:00"
    rows = [row if r["entry_id"] == row["entry_id"] else r for r in rows]
    _write_rows(copy, rows)
    _rewrite_manifest(copy)
    contract = _load_contract(copy)
    contract["dev_evidence_manifest_sha256"] = vf.manifest_hash(
        vf.build_manifest_entries(copy))
    _write_contract(copy, contract)
    actual = _verify(copy, pinned, deep_bars)
    semantic = _semantic_layer(copy, deep_bars)
    shutil.rmtree(copy.parent)
    return _record(
        "A8", "DATASET_ROLE_SUBSTITUTION",
        "dev_accounting dataset_role DEVELOPMENT -> OOS with the OOS "
        "window; a ledger row entry_time moved to 2017-09-15 (inside OOS); "
        "manifest + contract binding rewritten",
        "verifier must reject: pinned hash mismatch, role must remain "
        "DEVELOPMENT, every row must lie inside the DEV partition",
        actual, semantic)


# ---------------------------------------------------------------------------
# A9 — CENSORING_MANIPULATION
# ---------------------------------------------------------------------------

def attack_a9(bundle: Path, pinned: str, deep_bars=None) -> dict:
    copy = _fresh_copy(bundle)
    rows = _load_rows(copy)
    # silently drop an unresolved/right-censorable trade (horizon exit)
    victims = [r for r in rows if r["status"] in
               ("FIRST_PLUS_RUNNER_HORIZON", "HORIZON_BEFORE_FIRST")]
    if not victims:
        victims = [r for r in rows if r["status"] in vf.TRADED_STATUSES]
    victim = victims[0]
    rows = [r for r in rows if r["entry_id"] != victim["entry_id"]]
    _write_rows(copy, rows)
    accounting = json.loads((copy / ACCOUNTING).read_text(encoding="utf-8"))
    agg = vf.recompute_aggregates(rows)
    accounting["population_n"] = agg["population_n"]
    accounting["traded_n"] = agg["traded_n"]
    accounting["status_counts"] = agg["status_counts"]
    accounting["gross_r_sum"] = agg["gross_r_sum"]
    (copy / ACCOUNTING).write_text(
        vf.canonical_serialize(accounting), encoding="utf-8")
    _rewrite_manifest(copy)
    contract = _load_contract(copy)
    contract["dev_evidence_manifest_sha256"] = vf.manifest_hash(
        vf.build_manifest_entries(copy))
    _write_contract(copy, contract)
    actual = _verify(copy, pinned, deep_bars)
    semantic = _semantic_layer(copy, deep_bars)
    shutil.rmtree(copy.parent)
    return _record(
        "A9", "CENSORING_MANIPULATION",
        f"row {victim['entry_id']} (status {victim['status']}) silently "
        "dropped from the ledger; accounting aggregates, manifest and "
        "contract binding rewritten to hide the drop",
        "verifier must reject: pinned hash mismatch AND population pin "
        "(row count must equal the pinned D01 population)",
        actual, semantic)


# ---------------------------------------------------------------------------
# A10 — COLLISION_POLICY_SUBSTITUTION
# ---------------------------------------------------------------------------

def attack_a10(bundle: Path, pinned: str, deep_bars=None) -> dict:
    copy = _fresh_copy(bundle)
    contract = _load_contract(copy)
    policy = json.loads(
        (copy / "evidence" / f'{contract["collision_policy_hash"]}.json').read_text())
    policy["collision_policy_id"] = "SAME_BAR_TARGET_FIRST_MUTATED"
    policy["rule"] = ("within any single M15 bar, if the SL and a target "
                      "are both touched, the TARGET is counted first "
                      "(mutated)")
    content = vf.canonical_serialize(policy).encode("utf-8")
    new_hash = vf.sha256_bytes(content)
    (copy / "evidence" / f"{new_hash}.json").write_bytes(content)
    contract["same_bar_collision_policy"] = "TARGET_FIRST_WHEN_BOTH_TOUCHED"
    contract["collision_policy_hash"] = new_hash
    _write_contract(copy, contract)
    # flip a same-bar collision trade: claim the first objective paid in
    # the stop bar (target-first semantics)
    rows = _load_rows(copy)
    row = dict(_first_row(rows, "STOPPED_BEFORE_FIRST"))
    stop_bar = row["first_leg"]["exit_bar"]
    row["first_leg"] = {
        "pct": 0.5, "exit_bar": stop_bar,
        "exit_price": row["first_objective"]["price"],
        "exit_reason": "FIRST_OBJECTIVE",
        "leg_r": 0.5 * row["first_objective"]["target_r"],
    }
    row["runner_leg"] = {
        "pct": 0.5, "exit_bar": stop_bar,
        "exit_price": row["first_objective"]["price"],
        "exit_reason": "FIRST_OBJECTIVE",
        "leg_r": 0.5 * row["first_objective"]["target_r"],
    }
    row["status"] = "FIRST_PLUS_RUNNER_TARGET"
    row["gross_trade_r"] = row["first_leg"]["leg_r"] + row["runner_leg"]["leg_r"]
    rows = [row if r["entry_id"] == row["entry_id"] else r for r in rows]
    _write_rows(copy, rows)
    _rewrite_manifest(copy)
    contract = _load_contract(copy)
    contract["dev_evidence_manifest_sha256"] = vf.manifest_hash(
        vf.build_manifest_entries(copy))
    _write_contract(copy, contract)
    actual = _verify(copy, pinned, deep_bars)
    semantic = _semantic_layer(copy, deep_bars)
    shutil.rmtree(copy.parent)
    return _record(
        "A10", "COLLISION_POLICY_SUBSTITUTION",
        "same-bar collision rule stop-first -> target-first (new content "
        "address); a STOPPED_BEFORE_FIRST row flipped to a target payoff "
        "in the stop bar under the mutated ordering",
        "verifier must reject: pinned hash mismatch, collision frozen "
        "fact, evidence semantics (stop-first rule), leg/status coherence",
        actual, semantic)


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

ATTACKS = (
    ("A1", attack_a1), ("A2", attack_a2), ("A3", attack_a3),
    ("A4", attack_a4), ("A5", attack_a5), ("A6", attack_a6),
    ("A7", attack_a7), ("A8", attack_a8), ("A9", attack_a9),
    ("A10", attack_a10),
)


def run_all_attacks(bundle_dir: Path | str, deep_bars=None) -> dict:
    bundle = Path(bundle_dir)
    pinned = _pinned_hash(bundle)
    results = []
    for _attack_id, fn in ATTACKS:
        results.append(fn(bundle, pinned, deep_bars))
    executed = sum(1 for r in results if r["ATTACK_EXECUTED"] == "YES")
    passed = sum(1 for r in results if r["VERDICT"] == "PASS")
    failed = sum(1 for r in results if r["VERDICT"] == "FAIL")
    return {
        "pinned_contract_sha256": pinned,
        "attacks": results,
        "ATTACKS_EXECUTED": executed,
        "ATTACKS_PASSED": passed,
        "ATTACKS_FAILED": failed,
        "ALL_PASSED": failed == 0 and executed == len(ATTACKS),
    }
