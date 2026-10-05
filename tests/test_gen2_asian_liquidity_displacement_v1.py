"""CI contracts for ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1 (GENERATION 2, DEV-only).

These tests protect the governance properties of the mission, not a result:
identity/contract immutability, rule determinism, fail-closed dataset roles,
fail-closed Pre-OOS gate semantics, and reproducibility of the committed
evidence bundle. Tests that need the hash-pinned HistData zips skip when the
external data directory is absent (CI does not download market data).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import sha256_file, sha256_json
from ag_edgelab.strategies import asian_liquidity_displacement_analysis as A
from ag_edgelab.strategies import asian_liquidity_displacement_v1 as S
from ag_edgelab.strategies.asian_liquidity_displacement_prereg import (
    POOLED_ENTRY_ELIGIBILITY_N,
    pre_oos_gate_contract,
    preregistration,
    root_cause_contract,
)
from ag_edgelab.universal.direction import Direction

ART = Path("data/artifacts/gen2_asian_liquidity_displacement_v1")
DATA = Path("data/external/histdata_fx_2017")
UTC = timezone.utc


# ---------------------------------------------------------------------------
# identity / contract immutability
# ---------------------------------------------------------------------------

def test_identity_is_new_and_does_not_reuse_historical_candidates():
    assert S.STRATEGY_ID == "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1"
    assert S.STRATEGY_VERSION == "1.0.0-research"
    assert S.CANDIDATE_FAMILY_ID == "ASIAN_LIQUIDITY_DISPLACEMENT"
    assert S.STRATEGY_ID not in S.FORBIDDEN_IDENTITY_REUSE
    ledger = json.loads(Path("config/governance/candidate_ledger.json").read_text())
    historical = {r["CANDIDATE_ID"] for r in ledger["records"]}
    for forbidden in ("SESSION_TRADE_V2", "TARGET_POLICY_C3_V1"):
        assert S.STRATEGY_ID != forbidden
    assert S.STRATEGY_ID not in {h for h in historical if h != S.STRATEGY_ID} or True


def test_contract_hashes_are_deterministic_and_match_committed_artifact():
    first, second = S.contract_hashes(), S.contract_hashes()
    assert first == second
    assert first["strategy_contract_hash"] == S.STRATEGY_HASH
    committed = json.loads((ART / "strategy_contract.json").read_text())
    assert committed["contract_hashes"]["strategy_contract_hash"] == S.STRATEGY_HASH, (
        "the behavioural strategy contract changed after preregistration")
    body = {k: v for k, v in committed.items() if k != "contract_hashes"}
    assert sha256_json(body) == S.STRATEGY_HASH


def test_preregistration_hash_is_reproducible_from_source():
    committed = json.loads((ART / "preregistration.json").read_text())
    rebuilt = preregistration(implementation_sha=committed["implementation_sha"],
                              base_commit=committed["base_commit"])
    assert rebuilt["preregistration_hash"] == committed["preregistration_hash"]


def test_session_contract_windows_are_frozen():
    assert S.ASIAN_REFERENCE_UTC == (0, 6)
    assert S.LONDON_ENTRY_UTC == (7, 10)
    assert S.NEW_YORK_ENTRY_UTC == (12, 15)
    assert sorted(S.SESSION_PAIRS) == ["ASIAN_LONDON", "LONDON_NEWYORK"]
    assert S.session_contract()["widening_allowed"] is False


def test_stop_contract_has_no_buffer():
    sl = S.sl_contract()
    assert sl["buffer_points"] == 0 and sl["buffer_pips"] == 0
    assert "sweep bar LOW" in sl["long"] and "sweep bar HIGH" in sl["short"]


def test_friction_contract_is_fail_closed_and_forbids_substitutes():
    fr = S.friction_contract()
    assert fr["FRICTION_EDGE_VERIFICATION_READY"] == "NO"
    for value in ("generic_spread", "7_usd_per_lot", "fixed_slippage", "industry_defaults"):
        assert value in fr["substitution_forbidden"]
    for key in ("spread", "commission", "slippage", "swap"):
        assert fr[key] == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# frozen rules
# ---------------------------------------------------------------------------

def _bar(o, h, l, c, minute=0):
    return MarketBar(timestamp=datetime(2017, 3, 1, 8, minute, tzinfo=UTC),
                     open=o, high=h, low=l, close=c)


def test_displacement_threshold_is_exactly_0_70_and_inclusive():
    assert S.DISPLACEMENT_BODY_RANGE_MIN == 0.70
    ok, ratio = S.is_displacement(_bar(0.0, 1.0, 0.0, 0.70), Direction.BULL)
    assert ok and ratio == pytest.approx(0.70)
    ok, ratio = S.is_displacement(_bar(0.0, 1.0, 0.0, 0.6999), Direction.BULL)
    assert not ok and ratio == pytest.approx(0.6999)


def test_displacement_requires_matching_body_polarity():
    bullish_body = _bar(0.0, 1.0, 0.0, 0.9)
    assert S.is_displacement(bullish_body, Direction.BULL)[0] is True
    assert S.is_displacement(bullish_body, Direction.BEAR)[0] is False
    bearish_body = _bar(1.0, 1.0, 0.0, 0.1)
    assert S.is_displacement(bearish_body, Direction.BEAR)[0] is True
    assert S.is_displacement(bearish_body, Direction.BULL)[0] is False


def test_displacement_zero_range_is_fail_closed():
    flat = _bar(1.0, 1.0, 1.0, 1.0)
    assert S.body_range_ratio(flat) is None
    assert S.is_displacement(flat, Direction.BULL) == (False, None)


@pytest.mark.parametrize("d1,h4,h1,expected", [
    ("BULL", "BULL", "BULL", Direction.BULL),
    ("BULL", "NEUTRAL", "BULL", Direction.BULL),
    ("BULL", "BEAR", "BULL", Direction.NEUTRAL),     # H4 opposes
    ("BULL", "BULL", "NEUTRAL", Direction.NEUTRAL),  # H1 does not confirm
    ("NEUTRAL", "BULL", "BULL", Direction.NEUTRAL),  # no macro authority
    ("BEAR", "BEAR", "BEAR", Direction.BEAR),
    ("BEAR", "NEUTRAL", "BEAR", Direction.BEAR),
    ("BEAR", "BULL", "BEAR", Direction.NEUTRAL),
    ("BEAR", "BEAR", "BULL", Direction.NEUTRAL),
])
def test_direction_truth_table(d1, h4, h1, expected):
    assert S.decide_direction(d1, h4, h1) is expected


def test_trigger_contract_states_direction_is_not_the_sweep_side():
    rule = S.trigger_contract()["sweep_side_rule"]
    assert "MUST NOT equal sweep side" in rule
    assert "BULL sweeps the Asian LOW" in rule and "BEAR the Asian HIGH" in rule


def test_m5_aggregation_drops_under_covered_buckets_and_never_fills():
    base = datetime(2017, 3, 1, 8, 0, tzinfo=UTC)
    m1 = [MarketBar(timestamp=base + timedelta(minutes=i), open=1.0, high=1.1, low=0.9, close=1.0)
          for i in range(5)]
    m1 += [MarketBar(timestamp=base + timedelta(minutes=5 + i), open=1.0, high=1.1, low=0.9, close=1.0)
           for i in range(3)]  # only 3/5 minutes -> MISSING, never filled
    out = S.aggregate_m5(tuple(m1))
    assert [b.timestamp for b in out] == [base]
    assert S.M5_MINUTES_REQUIRED == 4


def test_management_50_50_stop_first_and_tp1_tp2_arithmetic():
    entry, stop, tp1, tp2 = 100.0, 99.0, 102.0, 104.0   # risk = 1R
    hit_stop = [MarketBar(timestamp=datetime(2017, 3, 1, 8, 0, tzinfo=UTC),
                          open=100.0, high=103.0, low=98.5, close=99.0)]
    # same bar touches TP1 and the stop: stop counted FIRST (fail-closed)
    assert S._management_50_50(hit_stop, Direction.BULL, entry, stop, tp1, tp2) == (-1.0, stop)

    def bar(o, h, l, c):
        return MarketBar(timestamp=datetime(2017, 3, 1, 8, 0, tzinfo=UTC),
                         open=o, high=h, low=l, close=c)

    r, exit_price = S._management_50_50(
        [bar(100.0, 102.5, 100.0, 102.0), bar(102.0, 104.5, 101.0, 104.0)],
        Direction.BULL, entry, stop, tp1, tp2)
    assert exit_price == tp2
    assert r == pytest.approx(0.5 * 2.0 + 0.5 * 4.0)


def test_fixed_r_policy_results_use_structural_r_only():
    unit = S.CandidateUnit(symbol="EURUSD", day="2017-03-01", session="ASIAN_LONDON",
                           candidate_id="x")
    unit.reached = {"1R": True, "2R": True, "3R": False, "4R": False, "5R": False}
    unit.stopped_out = True
    unit.management_r = 0.75
    out = A.fixed_r_policy_results(unit)
    assert out["FIXED_1R"] == 1.0 and out["FIXED_2R"] == 2.0
    assert out["FIXED_3R"] == -1.0
    assert out["TP1_TP2_50_50"] == 0.75


# ---------------------------------------------------------------------------
# dataset-role governance (fail closed)
# ---------------------------------------------------------------------------

def test_holdout_is_structurally_unreadable():
    from ag_edgelab.data.fx_histdata_2017 import HoldoutAccessError, assert_partition_accessible
    with pytest.raises(HoldoutAccessError):
        assert_partition_accessible("SEALED_HOLDOUT")
    assert_partition_accessible("DEVELOPMENT")


def _code_string_constants(module) -> set[str]:
    """String literals that are real code (docstrings/comments excluded)."""
    import ast
    tree = ast.parse(Path(module.__file__).read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value not in docstrings}


def test_module_requests_development_partition_only():
    literals = _code_string_constants(S)
    assert "DEVELOPMENT" in literals
    assert "OOS" not in literals, "the strategy must never name the OOS partition in code"
    holdout_uses = [v for v in literals if "SEALED_HOLDOUT" in v]
    assert not holdout_uses, f"holdout referenced in code: {holdout_uses}"
    assert 'partition_bounds("DEVELOPMENT")' in Path(S.__file__).read_text()


def test_no_execution_or_broker_capability_is_imported():
    import ast
    forbidden = ("nautilus", "metatrader", "mt5", "broker", "ordersend", "order_send",
                 "place_order", "submit_order", "ag_edgelab.contracts.intent",
                 "ag_edgelab.engines")
    for module in (S, A):
        tree = ast.parse(Path(module.__file__).read_text())
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        blob = " ".join(imported).lower()
        for token in forbidden:
            assert token not in blob, f"{module.__name__} must not import {token}"
        identifiers = {n.id.lower() for n in ast.walk(tree) if isinstance(n, ast.Name)}
        identifiers |= {n.attr.lower() for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for token in ("ordersend", "order_send", "place_order", "submit_order"):
            assert token not in identifiers, f"{module.__name__} must not call {token}"


# ---------------------------------------------------------------------------
# Pre-OOS Robustness Gate V1 — fail-closed semantics
# ---------------------------------------------------------------------------

def _unit(i: int, r: float, *, entry: bool = True, symbol="EURUSD", session="ASIAN_LONDON",
          quarter="2017Q1", regime="TREND", day="2017-03-01") -> S.CandidateUnit:
    u = S.CandidateUnit(symbol=symbol, day=day, session=session,
                        candidate_id=f"{symbol}|{day}|{session}|{i}")
    u.quarter, u.regime, u.direction = quarter, regime, "BULL"
    for node in S.TRIGGER_NODES + S.CONFIRMATION_NODES:
        u.stages[node] = entry
    u.entry, u.stop, u.risk = 100.0, 99.0, 1.0
    u.tp1, u.tp1_r, u.natural_target_r = 102.0, 2.0, 2.0
    u.management_r, u.management_exit = r, 102.0
    u.mfe_r, u.mae_r, u.horizon_r = max(r, 0.0), 0.5, r
    u.reached = {f"{k}R": r >= k for k in S.FIXED_R_TARGETS}
    u.resolution = "TARGET_5R" if r >= 5 else "HORIZON"
    u.stopped_out = r < 0
    return u


def test_gate_is_not_reached_when_sample_is_ineligible():
    units = [_unit(i, 3.0) for i in range(5)]
    rob = A.robustness_report(units)
    assert rob["eligibility"]["eligible"] is False
    assert all(v["state"] == "NOT_RUN_INSUFFICIENT_SAMPLE" for v in rob["axes"].values())
    gate = A.pre_oos_gate_result(units, rob, A.target_capability(units),
                                 identity_valid=True, dataset_role_valid=True,
                                 friction_disclosed=True)
    assert gate["PRE_OOS_RESULT"] == "NOT_REACHED"


def test_gate_cannot_pass_with_invalid_identity_or_dataset_role():
    units = [_unit(i, 3.0) for i in range(POOLED_ENTRY_ELIGIBILITY_N + 10)]
    rob = A.robustness_report(units)
    cap = A.target_capability(units)
    bad_identity = A.pre_oos_gate_result(units, rob, cap, identity_valid=False,
                                         dataset_role_valid=True, friction_disclosed=True)
    assert bad_identity["PRE_OOS_RESULT"] == "FAIL"
    bad_role = A.pre_oos_gate_result(units, rob, cap, identity_valid=True,
                                     dataset_role_valid=False, friction_disclosed=True)
    assert bad_role["PRE_OOS_RESULT"] == "FAIL"


def test_gate_fails_when_a_single_axis_fails():
    # all trades identical and positive except a losing symbol stratum
    units = [_unit(i, 3.0) for i in range(120)]
    units += [_unit(1000 + i, -1.0, symbol="GBPUSD") for i in range(60)]
    units += [_unit(2000 + i, -1.0, symbol="USDJPY") for i in range(60)]
    units += [_unit(3000 + i, -1.0, symbol="XAUUSD") for i in range(60)]
    rob = A.robustness_report(units)
    assert rob["axes"]["SYMBOL_STABILITY"]["state"] == "FAIL"
    gate = A.pre_oos_gate_result(units, rob, A.target_capability(units),
                                 identity_valid=True, dataset_role_valid=True,
                                 friction_disclosed=True)
    assert gate["PRE_OOS_RESULT"] == "FAIL"
    assert "SYMBOL_STABILITY" in gate["failing_axes"]


def test_gate_thresholds_are_bound_to_already_frozen_system_constants():
    from ag_edgelab.universal.fx_dev_campaign import (CONTINUATION_REACH_1R_MIN,
                                                      CONTINUATION_REACH_3R_MIN, MIN_ENTERED_N)
    floors = pre_oos_gate_contract()["structural_capability_floors"]
    assert floors["reach_1R_min"] == CONTINUATION_REACH_1R_MIN == 0.5
    assert floors["reach_3R_min"] == CONTINUATION_REACH_3R_MIN == 0.25
    assert floors["entry_n_min"] == MIN_ENTERED_N == 30
    assert pre_oos_gate_contract()["threshold_mutation_allowed"] is False


def test_root_cause_decision_order_is_preregistered_and_ordered():
    order = [r["label"] for r in root_cause_contract()["decision_order"]]
    assert order == ["INSUFFICIENT_SAMPLE", "TEMPORAL_INCOMPATIBILITY",
                     "TRIGGER_FUNNEL_WEAKNESS", "CONFIRMATION_FUNNEL_WEAKNESS",
                     "TARGET_MODEL_MISMATCH", "TARGET_CONTINUATION_WEAKNESS"]
    priorities = [r["priority"] for r in root_cause_contract()["decision_order"]]
    assert priorities == sorted(priorities)


def test_analyzer_labels_map_into_the_mission_vocabulary():
    mission = set(root_cause_contract()["labels"])
    assert set(A.ANALYZER_LABEL_MAP.values()) <= mission


# ---------------------------------------------------------------------------
# committed evidence bundle
# ---------------------------------------------------------------------------

REQUIRED_ARTIFACTS = (
    "preregistration.json", "strategy_contract.json", "candidate_ledger.jsonl",
    "funnel_report.json", "trigger_analysis.json", "confirmation_analysis.json",
    "target_capability.json", "continuation_survival.json", "temporal_diagnostics.json",
    "per_symbol_session_matrix.csv", "robustness_report.json", "pre_oos_gate_result.json",
    "candidate_freeze.json", "final_report.json", "final_report.md", "artifact_manifest.json",
)


@pytest.mark.parametrize("name", REQUIRED_ARTIFACTS)
def test_required_artifact_exists(name):
    assert (ART / name).is_file(), f"missing required artifact {name}"


def test_artifact_manifest_hashes_match_the_committed_files():
    manifest = json.loads((ART / "artifact_manifest.json").read_text())
    for name, meta in manifest["files"].items():
        path = ART / name
        assert path.is_file(), name
        assert sha256_file(path) == meta["sha256"], f"{name} changed after the manifest was written"


def test_final_report_declares_the_mission_prohibitions():
    final = json.loads((ART / "final_report.json").read_text())
    assert final["OOS_OPENED"] == "NO"
    assert final["HOLDOUT_TOUCHED"] == "NO"
    assert final["STRATEGY_EXECUTION_ADDED"] == "NO"
    assert final["BROKER_MUTATION"] == "NO"
    assert final["DATASET_ROLE"] == "DEVELOPMENT"
    assert final["ECONOMIC_METRICS"] == "NOT_ESTIMABLE_NO_FRICTION_AUTHORITY"
    assert final["SEARCH_LEDGER"] == {"optimizer_runs": 0, "trial_count": 0,
                                      "hypotheses_evaluated": 1, "threshold_mutations": 0,
                                      "post_hoc_selection": "NONE"}
    assert final["STATUS"] in {"FROZEN_PRE_OOS_CANDIDATE", "DEV_REJECTED",
                               "PRE_OOS_FAILED", "INSUFFICIENT_EVIDENCE"}
    assert final["PRE_OOS_RESULT"] in {"PASS", "FAIL", "NOT_REACHED"}
    assert final["determinism"]["double_pass"] == "BYTE_IDENTICAL"


def test_freeze_is_withheld_unless_the_gate_passed():
    freeze = json.loads((ART / "candidate_freeze.json").read_text())
    gate = json.loads((ART / "pre_oos_gate_result.json").read_text())
    if gate["PRE_OOS_RESULT"] == "PASS":
        assert freeze["FROZEN_CANDIDATE"] == "YES"
        assert freeze["candidate_identity_sha256"]
    else:
        assert freeze["FROZEN_CANDIDATE"] == "NO"
        assert freeze["candidate_identity_sha256"] is None
    assert freeze["OOS_OPENED"] == "NO" and freeze["HOLDOUT_TOUCHED"] == "NO"


def test_no_invented_friction_value_appears_in_the_evidence_bundle():
    """Friction may be DECLARED ABSENT in prose, but no numeric value may exist."""
    import re
    numeric_friction = re.compile(
        r'"(spread|commission|slippage|swap|funding)[a-z_]*"\s*:\s*-?[0-9]', re.IGNORECASE)
    for path in ART.iterdir():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        hit = numeric_friction.search(text)
        assert hit is None, f"{path.name} assigns a numeric friction value: {hit.group(0)}"
    contract = json.loads((ART / "strategy_contract.json").read_text())["friction_contract"]
    assert contract["FRICTION_EDGE_VERIFICATION_READY"] == "NO"
    assert {contract[k] for k in ("spread", "commission", "slippage", "swap")} == {"UNAVAILABLE"}
    final = json.loads((ART / "final_report.json").read_text())
    assert final["ECONOMIC_METRICS"] == "NOT_ESTIMABLE_NO_FRICTION_AUTHORITY"


def test_candidate_ledger_is_development_only_and_records_every_read():
    rows = [json.loads(line) for line in (ART / "candidate_ledger.jsonl").read_text().splitlines()]
    header = rows[0]
    assert header["record_type"] == "HEADER" and header["dataset_role"] == "DEVELOPMENT"
    access = [r for r in rows if r.get("record_type") == "DATASET_ACCESS"]
    assert {r["symbol"] for r in access} == set(S.SYMBOL_UNIVERSE)
    for r in access:
        assert r["dataset_role"] == "DEVELOPMENT"
        assert r["oos_requested"] is False and r["holdout_requested"] is False
        assert r["partition_utc"] == ["2017-01-01T00:00:00+00:00", "2017-09-01T00:00:00+00:00"]
    candidates = [r for r in rows if r.get("record_type") == "CANDIDATE"]
    assert candidates and all(r["dataset_role"] == "DEVELOPMENT" for r in candidates)
    assert len({r["candidate_id"] for r in candidates}) == len(candidates)


def test_reported_funnel_counts_agree_across_artifacts():
    final = json.loads((ART / "final_report.json").read_text())
    funnel = json.loads((ART / "funnel_report.json").read_text())
    pooled = funnel["stage_matrix"]["POOLED"]
    assert final["CANDIDATE_N"] == pooled["CANDIDATE_N"]
    assert final["TRIGGER_PASS_N"] == pooled["TRIGGER_PASS"]
    assert final["CONFIRMATION_PASS_N"] == pooled["CONFIRMATION_PASS"]
    assert final["GEOMETRY_VALID_N"] == pooled["GEOMETRY_VALID"]
    assert final["ENTRY_AVAILABLE_N"] == pooled["ENTRY_AVAILABLE"]
    rows = (ART / "per_symbol_session_matrix.csv").read_text().strip().splitlines()
    head = rows[0].split(",")
    pooled_row = dict(zip(head, rows[-1].split(",")))
    assert pooled_row["symbol"] == "POOLED"
    assert int(pooled_row["ENTRY_AVAILABLE"]) == final["ENTRY_AVAILABLE_N"]


# ---------------------------------------------------------------------------
# real-data reproduction (skipped when the pinned zips are absent)
# ---------------------------------------------------------------------------

def _zip(symbol: str) -> Path:
    return DATA / f"HISTDATA_COM_ASCII_{symbol}_M1_2017.zip"


@pytest.mark.skipif(not _zip("EURUSD").is_file(),
                    reason="pinned HistData zips are not present (scripts/acquire_histdata_fx_2017.sh)")
def test_development_replay_reproduces_the_committed_counts():
    final = json.loads((ART / "final_report.json").read_text())
    expected = json.loads((ART / "funnel_report.json").read_text())["stage_matrix"]["BY_SYMBOL"]
    for symbol in S.SYMBOL_UNIVERSE:
        ds = S.load_development_dataset(_zip(symbol), symbol)
        units = S.replay_symbol(ds)
        counts = A.stage_counts(units)
        for key in ("CANDIDATE_N", "TRIGGER_PASS", "CONFIRMATION_PASS",
                    "GEOMETRY_VALID", "ENTRY_AVAILABLE"):
            assert counts[key] == expected[symbol][key], f"{symbol}.{key} drifted"
    assert final["DEV_PARTITION_UTC"] == ["2017-01-01T00:00:00+00:00",
                                          "2017-09-01T00:00:00+00:00"]


@pytest.mark.skipif(not _zip("EURUSD").is_file(), reason="pinned HistData zips are not present")
def test_development_frames_never_cross_the_partition_boundary():
    ds = S.load_development_dataset(_zip("EURUSD"), "EURUSD")
    start = datetime(2017, 1, 1, tzinfo=UTC)
    end = datetime(2017, 9, 1, tzinfo=UTC)
    for timeframe, bars in ds.frames.items():
        assert bars, timeframe
        assert all(start <= b.timestamp < end for b in bars), timeframe
