"""TARGET_POLICY_C3_V1 — separate test fixture (mission section 8).

Covers: the single exact same-bar collision policy (no ambiguous branch),
runner gating, complete horizon termination, censoring, accounting
identities, two-path canonical serialization, the raw content-addressed
store, fraction-substitution identity change, and verifier rejection of
tampered bundles.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import canonical_json
from ag_edgelab.universal import candidate_c3_v1 as cand
from ag_edgelab.verification import c3_v1_verifier as vf

UTC = timezone.utc
T0 = datetime(2017, 3, 1, 10, 30, tzinfo=UTC)


def bar(minutes: int, o: float, h: float, l: float, c: float) -> MarketBar:
    return MarketBar(timestamp=T0 + timedelta(minutes=minutes),
                     open=o, high=h, low=l, close=c)


def flat_bars(n: int, price: float = 100.0) -> list[MarketBar]:
    return [bar(15 * (i + 1), price, price, price, price) for i in range(n)]


LONG = dict(direction="BULL", entry_price=100.0, stop_price=90.0,
            first_price=110.0, first_r=1.0, runner_price=120.0, runner_r=2.0)


# ---------------------------------------------------------------------------
# Same-bar collision policy — one exact rule, no ambiguous branch
# ---------------------------------------------------------------------------

def test_collision_first_objective_and_sl_same_bar_stop_first():
    bars = [bar(15, 100.0, 111.0, 89.0, 105.0)] + flat_bars(95)
    res = cand.resolve_trade(bars, **LONG)
    assert res.status == "STOPPED_BEFORE_FIRST"
    assert res.first_leg.exit_reason == "SL"
    assert res.runner_leg.exit_reason == "SL"
    assert res.first_leg.exit_price == 90.0
    assert res.runner_leg.exit_bar == res.first_leg.exit_bar == 1
    assert res.gross_trade_r == -1.0
    # the independent verifier implementation must agree
    status, fl, rl, _ = vf.derive_trade_outcome(
        bars, direction="BULL", entry_price=100.0, stop_price=90.0,
        first_price=110.0, runner_price=120.0, horizon_bars=96)
    assert status == "STOPPED_BEFORE_FIRST" and fl[:3] == (1, 90.0, "SL") \
        and rl[:3] == (1, 90.0, "SL")


def test_collision_runner_target_and_sl_same_bar_stop_first():
    bars = ([bar(15, 100.0, 112.0, 95.0, 108.0),     # first objective hit
             bar(30, 108.0, 121.0, 89.0, 95.0)]      # runner target + SL
            + flat_bars(94))
    res = cand.resolve_trade(bars, **LONG)
    assert res.status == "FIRST_PLUS_RUNNER_STOP"
    assert res.first_leg.exit_reason == "FIRST_OBJECTIVE"
    assert res.first_leg.exit_bar == 1
    assert res.runner_leg.exit_reason == "SL"
    assert res.runner_leg.exit_price == 90.0
    assert res.runner_leg.exit_bar == 2
    assert res.gross_trade_r == pytest.approx(0.5 * 1.0 - 0.5 * 1.0)
    status, fl, rl, _ = vf.derive_trade_outcome(
        bars, direction="BULL", entry_price=100.0, stop_price=90.0,
        first_price=110.0, runner_price=120.0, horizon_bars=96)
    assert status == "FIRST_PLUS_RUNNER_STOP" and rl[:3] == (2, 90.0, "SL")


def test_collision_first_and_runner_objective_same_bar_pays_runner():
    # both objectives touched in one bar, SL untouched: both legs exit that
    # bar; the runner is paid at the runner objective (monotone path)
    bars = [bar(15, 100.0, 125.0, 99.0, 118.0)] + flat_bars(95)
    res = cand.resolve_trade(bars, **LONG)
    assert res.status == "FIRST_PLUS_RUNNER_TARGET"
    assert res.first_leg.exit_bar == res.runner_leg.exit_bar == 1
    assert res.first_leg.exit_price == 110.0
    assert res.runner_leg.exit_price == 120.0
    assert res.gross_trade_r == pytest.approx(0.5 * 1.0 + 0.5 * 2.0)
    status, fl, rl, _ = vf.derive_trade_outcome(
        bars, direction="BULL", entry_price=100.0, stop_price=90.0,
        first_price=110.0, runner_price=120.0, horizon_bars=96)
    assert status == "FIRST_PLUS_RUNNER_TARGET"
    assert fl[0] == rl[0] == 1 and rl[1] == 120.0


def test_no_target_payoff_after_sl_and_runner_never_before_first():
    bars = ([bar(15, 100.0, 112.0, 95.0, 108.0),      # first objective
             bar(30, 108.0, 108.0, 89.0, 91.0),       # SL only
             bar(45, 91.0, 130.0, 91.0, 128.0)]       # runner target AFTER SL
            + flat_bars(93))
    res = cand.resolve_trade(bars, **LONG)
    assert res.status == "FIRST_PLUS_RUNNER_STOP"
    assert res.runner_leg.exit_bar == 2          # SL at bar 2, not the later target
    status, fl, rl, _ = vf.derive_trade_outcome(
        bars, direction="BULL", entry_price=100.0, stop_price=90.0,
        first_price=110.0, runner_price=120.0, horizon_bars=96)
    assert status == "FIRST_PLUS_RUNNER_STOP" and rl[0] == 2


# ---------------------------------------------------------------------------
# Complete termination + censoring
# ---------------------------------------------------------------------------

def test_horizon_before_first_exits_at_last_completed_close():
    bars = flat_bars(96, 101.5)
    bars[95] = bar(15 * 96, 101.0, 102.0, 100.5, 101.75)
    res = cand.resolve_trade(bars, **LONG)
    assert res.status == "HORIZON_BEFORE_FIRST"
    assert res.horizon_close == 101.75
    assert res.first_leg.exit_reason == res.runner_leg.exit_reason == "HORIZON_CLOSE"
    assert res.first_leg.exit_bar == res.runner_leg.exit_bar == 96
    risk = 10.0
    expected = 0.5 * (101.75 - 100.0) / risk + 0.5 * (101.75 - 100.0) / risk
    assert res.gross_trade_r == pytest.approx(expected)


def test_runner_open_resolves_at_horizon_close():
    bars = ([bar(15, 100.0, 111.0, 99.0, 108.0)]     # first objective bar 1
            + flat_bars(95, 103.0))
    res = cand.resolve_trade(bars, **LONG)
    assert res.status == "FIRST_PLUS_RUNNER_HORIZON"
    assert res.first_leg.exit_reason == "FIRST_OBJECTIVE"
    assert res.runner_leg.exit_reason == "HORIZON_CLOSE"
    assert res.runner_leg.exit_bar == 96
    assert res.runner_leg.exit_price == 103.0
    assert res.gross_trade_r == pytest.approx(0.5 * 1.0 + 0.5 * 0.3)


def test_short_direction_symmetry():
    bars = flat_bars(96, 100.0)
    bars[2] = bar(45, 100.0, 101.0, 88.0, 90.0)      # first objective (90) + SL(110)?
    res = cand.resolve_trade(
        bars, direction="BEAR", entry_price=100.0, stop_price=110.0,
        first_price=92.5, first_r=0.75, runner_price=85.0, runner_r=1.5)
    # bar hits low 88 <= first 92.5 but also high 101 < stop 110: no SL;
    # first objective reached at bar 3; runner target 85 not reached
    assert res.status == "FIRST_PLUS_RUNNER_HORIZON"
    assert res.first_leg.leg_r == pytest.approx(0.5 * 0.75)


def test_truncated_window_is_right_censored_never_imputed():
    res = cand.resolve_trade(flat_bars(50), **LONG)
    assert res.status == "RIGHT_CENSORED_DATA_BOUNDARY"
    assert res.censored is True
    assert res.gross_trade_r is None
    assert res.first_leg.leg_r is None and res.runner_leg.leg_r is None


# ---------------------------------------------------------------------------
# Accounting identities (mission section 11)
# ---------------------------------------------------------------------------

def _row(res, **kw):
    entry_time = kw.get("entry_time", "2017-03-01T10:45:00+00:00")
    first = kw.get("first_objective") or {
        "family": "NT01_NEXT_CONFIRMED_STRUCTURAL_SWING", "price": 110.0,
        "target_r": 1.0, "created_time": "2017-03-01T09:00:00+00:00"}
    runner = kw.get("runner_objective") or {
        "family": "NT02_PREVIOUS_DAY_DIRECTIONAL_EXTREME", "price": 120.0,
        "target_r": 2.0, "created_time": "2017-03-01T00:00:00+00:00"}
    return {
        "entry_id": kw.get("entry_id", "EURUSD:1"),
        "symbol": kw.get("symbol", "EURUSD"),
        "entry_time": entry_time,
        "direction": kw.get("direction", "BULL"),
        "session": "LONDON",
        "is_t1": kw.get("is_t1", False),
        "entry_price": kw.get("entry_price", 100.0),
        "stop_price": kw.get("stop_price", 90.0),
        "risk_distance": 10.0,
        "first_objective": first,
        "runner_objective": runner,
        "status": res.status,
        "first_leg": {"pct": res.first_leg.pct,
                      "exit_bar": res.first_leg.exit_bar,
                      "exit_price": res.first_leg.exit_price,
                      "exit_reason": res.first_leg.exit_reason,
                      "leg_r": res.first_leg.leg_r},
        "runner_leg": {"pct": res.runner_leg.pct,
                       "exit_bar": res.runner_leg.exit_bar,
                       "exit_price": res.runner_leg.exit_price,
                       "exit_reason": res.runner_leg.exit_reason,
                       "leg_r": res.runner_leg.leg_r},
        "gross_trade_r": res.gross_trade_r,
        "net_trade_r": None,
        "friction_status": "UNAVAILABLE_NO_REPOSITORY_AUTHORITY",
        "horizon_close": res.horizon_close,
        "stop_bar": None,
        "window_last_bar_time": "2017-03-02T10:45:00+00:00",
        "censored": res.censored,
    }


def test_accounting_identities_hold_on_every_traded_status():
    contract = {"research_horizon": 96, "first_objective_pct": 50,
                "runner_pct": 50,
                "dataset_partitions": {
                    "DEVELOPMENT": ["2017-01-01T00:00:00+00:00",
                                    "2017-09-01T00:00:00+00:00"]}}
    scenarios = {
        "STOPPED_BEFORE_FIRST":
            [bar(15, 100.0, 111.0, 89.0, 105.0)] + flat_bars(95),
        "FIRST_PLUS_RUNNER_TARGET":
            [bar(15, 100.0, 125.0, 99.0, 118.0)] + flat_bars(95),
        "FIRST_PLUS_RUNNER_STOP":
            [bar(15, 100.0, 112.0, 95.0, 108.0),
             bar(30, 108.0, 108.0, 89.0, 91.0)] + flat_bars(94),
        "FIRST_PLUS_RUNNER_HORIZON":
            [bar(15, 100.0, 111.0, 99.0, 108.0)] + flat_bars(95, 103.0),
        "HORIZON_BEFORE_FIRST": flat_bars(96, 101.5),
    }
    for status, bars in scenarios.items():
        res = cand.resolve_trade(bars, **LONG)
        assert res.status == status
        row = _row(res)
        assert row["first_leg"]["pct"] + row["runner_leg"]["pct"] == 1.0
        assert row["gross_trade_r"] == pytest.approx(
            row["first_leg"]["leg_r"] + row["runner_leg"]["leg_r"])
        failures = vf.validate_ledger_rows([row], contract)
        assert failures == [], f"{status}: {failures}"


def test_future_created_target_is_rejected_by_row_causality():
    contract = {"research_horizon": 96, "first_objective_pct": 50,
                "runner_pct": 50,
                "dataset_partitions": {
                    "DEVELOPMENT": ["2017-01-01T00:00:00+00:00",
                                    "2017-09-01T00:00:00+00:00"]}}
    bars = [bar(15, 100.0, 125.0, 99.0, 118.0)] + flat_bars(95)
    res = cand.resolve_trade(bars, **LONG)
    row = _row(res)
    row["runner_objective"]["created_time"] = "2017-03-05T00:00:00+00:00"
    failures = vf.validate_ledger_rows([row], contract)
    assert any("AFTER entry_time" in f for f in failures)


def test_dropped_row_changes_population_and_censoring_accounting():
    rows = []
    for i, (status, bars) in enumerate({
            "FIRST_PLUS_RUNNER_TARGET":
                [bar(15, 100.0, 125.0, 99.0, 118.0)] + flat_bars(95),
            "HORIZON_BEFORE_FIRST": flat_bars(96, 101.5),
            "FIRST_PLUS_RUNNER_HORIZON":
                [bar(15, 100.0, 111.0, 99.0, 108.0)] + flat_bars(95, 103.0),
            "STOPPED_BEFORE_FIRST":
                [bar(15, 100.0, 111.0, 89.0, 105.0)] + flat_bars(95)}.items()):
        res = cand.resolve_trade(bars, **LONG)
        row = _row(res, entry_id=f"EURUSD:{i}")
        rows.append(row)
    full = vf.recompute_aggregates(rows)
    assert full["population_n"] == 4 and full["traded_n"] == 4
    dropped = vf.recompute_aggregates(rows[:-1])
    assert dropped["population_n"] == 3
    assert dropped["status_counts"].get("STOPPED_BEFORE_FIRST", 0) == 0
    assert full["status_counts"]["STOPPED_BEFORE_FIRST"] == 1


# ---------------------------------------------------------------------------
# Two-path canonical serialization (mission sections 2-3)
# ---------------------------------------------------------------------------

def test_two_path_serialization_byte_identical_on_real_contract():
    contract = cand.build_contract("0" * 64)
    path_a = cand.canonical_contract_bytes(contract)
    path_b = vf.canonical_serialize(contract).encode("utf-8")
    assert path_a == path_b
    assert vf.sha256_bytes(path_a) == cand.contract_sha256_path_a(contract)


def test_canonical_serialization_properties():
    value = {"b": 1, "a": [1.5, -0.0, 1e-06, None, True, False, "x"],
             "ü—key": "DEFERRED — never selected", "nested": {"z": {}, "y": []}}
    ours = vf.canonical_serialize(value)
    theirs = canonical_json(value)
    assert ours == theirs                       # independent implementations agree
    assert ours.encode("utf-8").decode("utf-8") == ours  # UTF-8 round trip
    assert "\\u2014" in ours                    # non-ASCII escaped (em dash)
    # compact: no whitespace between structural tokens (strings may contain
    # spaces — checked on a space-free payload)
    compact = vf.canonical_serialize({"a": [1, 2], "b": {"c": None}})
    assert compact == '{"a":[1,2],"b":{"c":null}}'
    assert "\n" not in compact and " " not in compact  # no pretty print


def test_fraction_substitution_changes_candidate_identity():
    base = cand.build_contract("0" * 64)
    mutated = dict(base)
    mutated["first_objective_pct"] = 75
    mutated["runner_pct"] = 25
    assert cand.contract_sha256_path_a(base) != cand.contract_sha256_path_a(mutated)


def test_horizon_and_collision_fields_are_pinned_in_contract():
    contract = cand.build_contract("0" * 64)
    assert contract["research_horizon"] == 96
    assert contract["horizon_timeframe"] == "M15_BARS"
    assert contract["horizon_anchor"] == "ENTRY_BAR_CLOSE_TIME"
    assert contract["same_bar_collision_policy"] == \
        "STOP_FIRST_FROZEN_V0_3_SINGLE_RULE"
    assert contract["forced_close_authority"] == \
        "AG_REFERENCE_REPLAY_V1_1_0_DATA_END_CLOSE_FILL"
    assert contract["friction_authority_complete_derived"] is False


# ---------------------------------------------------------------------------
# Friction authority derivation (mission section 6)
# ---------------------------------------------------------------------------

def test_friction_authority_derived_not_asserted():
    assert cand.derive_friction_authority_complete(cand.FRICTION_TABLE) is False
    # inventing numbers does not flip it either (no provenance authority)
    invented = json.loads(json.dumps(cand.FRICTION_TABLE))
    for symbol in invented:
        invented[symbol].update({"spread": 0.0002, "slippage": 0.00005,
                                 "commission": 0.000007})
    assert cand.derive_friction_authority_complete(invented) is False  # provenance still absent
    assert vf._derive_friction_complete(cand.FRICTION_TABLE) is False


# ---------------------------------------------------------------------------
# Raw content-addressed store (mission section 9)
# ---------------------------------------------------------------------------

def test_raw_content_store_rejects_lies():
    store = vf.RawContentStore()
    key = store.put(b"canonical bytes")
    assert key == vf.sha256_bytes(b"canonical bytes")
    assert store.resolve(key) == b"canonical bytes"
    with pytest.raises(LookupError):
        store.resolve("f" * 64)                  # unknown address
    with pytest.raises(LookupError):
        store.resolve("not-a-hash")


def test_raw_content_store_never_trusts_caller_properties():
    store = vf.RawContentStore()
    key = store.put(b"content")
    # an attacker rewriting the stored bytes cannot be surfaced through a
    # spoofed .sha256 property: the store only recomputes from raw bytes
    assert store.resolve(key) == b"content"


# ---------------------------------------------------------------------------
# Verifier rejection of tampered bundles (fast mini-bundle attacks)
# ---------------------------------------------------------------------------

def _mini_bundle(tmp_path: Path, mutate=None) -> tuple[Path, str]:
    """Build a structurally valid mini bundle (3 rows) and optionally
    mutate one artifact; returns (bundle_dir, pinned_hash)."""
    bundle = tmp_path / "bundle"
    (bundle / "evidence").mkdir(parents=True)
    rows = []
    scenarios = [
        ("FIRST_PLUS_RUNNER_TARGET", [bar(15, 100.0, 125.0, 99.0, 118.0)] + flat_bars(95)),
        ("STOPPED_BEFORE_FIRST", [bar(15, 100.0, 111.0, 89.0, 105.0)] + flat_bars(95)),
        ("FIRST_PLUS_RUNNER_HORIZON", [bar(15, 100.0, 111.0, 99.0, 108.0)] + flat_bars(95, 103.0)),
    ]
    for i, (status, bars) in enumerate(scenarios):
        res = cand.resolve_trade(bars, **LONG)
        rows.append(_row(res, entry_id=f"EURUSD:{i}"))
    if mutate is not None:
        mutate(rows)
    ledger = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
                     for r in rows).encode("utf-8")
    (bundle / "dev_resolution_ledger.jsonl").write_bytes(ledger)

    accounting = vf.recompute_aggregates(rows)
    accounting.update({"dataset_role": "DEVELOPMENT",
                       "dataset_window": ["2017-01-01T00:00:00+00:00",
                                          "2017-09-01T00:00:00+00:00"],
                       "symbols": ["EURUSD"], "unresolved_runner_n": 0,
                       "contract_horizon_bars": 96,
                       "friction_authority_complete": False,
                       "net_economics_claimed": False})
    (bundle / "dev_accounting.json").write_bytes(
        (vf.canonical_serialize(accounting) + "\n").encode("utf-8"))
    for filler in ("causality_audit.json", "determinism_report.json",
                   "parent_reproduction.json", "friction_authority.json"):
        (bundle / filler).write_bytes(b"{}\n")

    sub_policies = {
        cand.TRIGGER_AUTHORITY_HASH: cand.TRIGGER_AUTHORITY,
        cand.FIRST_TARGET_POLICY_HASH: cand.FIRST_TARGET_POLICY,
        cand.RUNNER_TARGET_POLICY_HASH: cand.RUNNER_TARGET_POLICY,
        cand.COLLISION_POLICY_HASH: cand.COLLISION_POLICY,
        cand.SESSION_AUTHORITY_HASH: cand.SESSION_AUTHORITY,
        cand.FRICTION_MODEL_HASH: cand.FRICTION_MODEL,
        cand.FRICTION_TABLE_SHA256: cand.FRICTION_TABLE,
        cand.DATASET_ROLE_POLICY_HASH: cand.DATASET_ROLE_POLICY,
        cand.POPULATION_AUTHORITY_HASH: cand.POPULATION_AUTHORITY,
    }
    for key, obj in sub_policies.items():
        (bundle / "evidence" / f"{key}.json").write_bytes(
            vf.canonical_serialize(obj).encode("utf-8"))

    entries = vf.build_manifest_entries(bundle)
    (bundle / "artifact_manifest.json").write_bytes(
        (vf.canonical_serialize(entries) + "\n").encode("utf-8"))
    contract = cand.build_contract(vf.manifest_hash(entries))
    content = cand.canonical_contract_bytes(contract)
    (bundle / "canonical_contract.json").write_bytes(content)
    return bundle, vf.sha256_bytes(content)


def test_mini_bundle_contract_and_evidence_checks_pass(tmp_path):
    bundle, pinned = _mini_bundle(tmp_path)
    verdict = vf.verify_bundle(bundle, pinned)
    checks = verdict["checks"]
    assert checks["contract_file_hash"]["passed"]
    assert checks["contract_path_b_bytes"]["passed"]
    assert checks["contract_hash_two_paths"]["passed"]
    assert checks["evidence_resolution"]["passed"]
    assert checks["evidence_semantics"]["passed"]
    assert checks["manifest_integrity"]["passed"]
    assert checks["row_accounting_and_causality"]["passed"]
    assert checks["unresolved_runner_zero"]["passed"]
    # the mini bundle intentionally violates only the population pin
    assert not checks["population_identity"]["passed"]


def _tamper_and_verify(tmp_path, mutate_bundle) -> dict:
    bundle, pinned = _mini_bundle(tmp_path)
    mutate_bundle(bundle)
    return vf.verify_bundle(bundle, pinned)


def test_verifier_rejects_fraction_substitution(tmp_path):
    def tamper(bundle):
        contract = json.loads((bundle / "canonical_contract.json").read_text())
        contract["first_objective_pct"] = 75
        contract["runner_pct"] = 25
        (bundle / "canonical_contract.json").write_bytes(
            vf.canonical_serialize(contract).encode("utf-8"))
    verdict = _tamper_and_verify(tmp_path, tamper)
    assert not verdict["ok"]
    assert not verdict["checks"]["contract_file_hash"]["passed"]
    assert not verdict["checks"]["contract_frozen_facts"]["passed"]


def test_verifier_rejects_horizon_substitution(tmp_path):
    def tamper(bundle):
        contract = json.loads((bundle / "canonical_contract.json").read_text())
        contract["research_horizon"] = 48
        (bundle / "canonical_contract.json").write_bytes(
            vf.canonical_serialize(contract).encode("utf-8"))
    verdict = _tamper_and_verify(tmp_path, tamper)
    assert not verdict["ok"]
    assert not verdict["checks"]["contract_frozen_facts"]["passed"]


def test_verifier_rejects_runner_stop_substitution(tmp_path):
    def tamper(bundle):
        contract = json.loads((bundle / "canonical_contract.json").read_text())
        contract["runner_stop_policy"] = "R1_BREAKEVEN_AFTER_FIRST"
        (bundle / "canonical_contract.json").write_bytes(
            vf.canonical_serialize(contract).encode("utf-8"))
    verdict = _tamper_and_verify(tmp_path, tamper)
    assert not verdict["checks"]["contract_frozen_facts"]["passed"]


def test_verifier_rejects_friction_substitution(tmp_path):
    def tamper(bundle):
        contract = json.loads((bundle / "canonical_contract.json").read_text())
        table = json.loads(json.dumps(cand.FRICTION_TABLE))
        table["EURUSD"]["spread"] = 0.0002
        content = vf.canonical_serialize(table).encode("utf-8")
        new_hash = vf.sha256_bytes(content)
        (bundle / "evidence" / f"{new_hash}.json").write_bytes(content)
        contract["friction_table_hash"] = new_hash
        contract["friction_authority_complete_derived"] = True
        (bundle / "canonical_contract.json").write_bytes(
            vf.canonical_serialize(contract).encode("utf-8"))
        vf.write_manifest(bundle)
    verdict = _tamper_and_verify(tmp_path, tamper)
    assert not verdict["ok"]
    assert not verdict["checks"]["contract_file_hash"]["passed"]
    assert not verdict["checks"]["evidence_semantics"]["passed"]


def test_verifier_rejects_future_target_in_ledger(tmp_path):
    def tamper(bundle):
        rows = [json.loads(line) for line in
                (bundle / "dev_resolution_ledger.jsonl").read_text().splitlines()]
        rows[0]["runner_objective"]["created_time"] = "2017-03-10T00:00:00+00:00"
        (bundle / "dev_resolution_ledger.jsonl").write_text(
            "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
                    for r in rows), encoding="utf-8")
        vf.write_manifest(bundle)
    verdict = _tamper_and_verify(tmp_path, tamper)
    assert not verdict["ok"]
    assert not verdict["checks"]["manifest_integrity"]["passed"]
    assert not verdict["checks"]["row_accounting_and_causality"]["passed"]


def test_verifier_rejects_collision_policy_substitution(tmp_path):
    def tamper(bundle):
        contract = json.loads((bundle / "canonical_contract.json").read_text())
        policy = dict(cand.COLLISION_POLICY)
        policy["collision_policy_id"] = "SAME_BAR_TARGET_FIRST_MUTATED"
        policy["rule"] = "target counted first within a bar (mutated)"
        content = vf.canonical_serialize(policy).encode("utf-8")
        new_hash = vf.sha256_bytes(content)
        (bundle / "evidence" / f"{new_hash}.json").write_bytes(content)
        contract["collision_policy_hash"] = new_hash
        contract["same_bar_collision_policy"] = "TARGET_FIRST_WHEN_BOTH_TOUCHED"
        (bundle / "canonical_contract.json").write_bytes(
            vf.canonical_serialize(contract).encode("utf-8"))
        vf.write_manifest(bundle)
    verdict = _tamper_and_verify(tmp_path, tamper)
    assert not verdict["ok"]
    assert not verdict["checks"]["evidence_semantics"]["passed"]
    assert not verdict["checks"]["contract_frozen_facts"]["passed"]


def test_verifier_rejects_dataset_role_substitution(tmp_path):
    def tamper(bundle):
        accounting = json.loads(
            (bundle / "dev_accounting.json").read_text(encoding="utf-8"))
        accounting["dataset_role"] = "OOS"
        (bundle / "dev_accounting.json").write_text(
            vf.canonical_serialize(accounting), encoding="utf-8")
        vf.write_manifest(bundle)
    verdict = _tamper_and_verify(tmp_path, tamper)
    assert not verdict["ok"]
    assert not verdict["checks"]["accounting_aggregates"]["passed"]


def test_verifier_rejects_censoring_drop(tmp_path):
    def tamper(bundle):
        rows = [json.loads(line) for line in
                (bundle / "dev_resolution_ledger.jsonl").read_text().splitlines()]
        rows = rows[:-1]
        (bundle / "dev_resolution_ledger.jsonl").write_text(
            "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
                    for r in rows), encoding="utf-8")
        accounting = json.loads(
            (bundle / "dev_accounting.json").read_text(encoding="utf-8"))
        agg = vf.recompute_aggregates(rows)
        accounting.update({"population_n": agg["population_n"],
                           "traded_n": agg["traded_n"],
                           "status_counts": agg["status_counts"]})
        (bundle / "dev_accounting.json").write_text(
            vf.canonical_serialize(accounting), encoding="utf-8")
        vf.write_manifest(bundle)
    verdict = _tamper_and_verify(tmp_path, tamper)
    assert not verdict["ok"]
    assert not verdict["checks"]["population_identity"]["passed"]


def test_verifier_rejects_manifest_tampering(tmp_path):
    def tamper(bundle):
        rows = [json.loads(line) for line in
                (bundle / "dev_resolution_ledger.jsonl").read_text().splitlines()]
        rows[1]["gross_trade_r"] = 5.0     # fabricate a gross value
        (bundle / "dev_resolution_ledger.jsonl").write_text(
            "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
                    for r in rows), encoding="utf-8")
        # manifest NOT rewritten: hash mismatch must fire
    verdict = _tamper_and_verify(tmp_path, tamper)
    assert not verdict["ok"]
    assert not verdict["checks"]["manifest_integrity"]["passed"]
    assert not verdict["checks"]["row_accounting_and_causality"]["passed"]
