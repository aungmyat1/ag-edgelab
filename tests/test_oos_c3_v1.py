"""V0.6.2 — OOS structural verification test fixture (no raw data needed).

Covers: metric definitions on synthetic evidence, the preregistered
verdict rules (A/B/C/D boundaries, symbol caps, subsample floors),
rung normalization, drawdown, and DEV-frozen evidence extraction
consistency requirements.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ag_edgelab.universal import c3_v1_oos_metrics as om


def _row(entry_id, symbol, status, *, rungs=((1.0, True), (2.0, True)),
         first_reached=None, runner_reason="RUNNER_TARGET", gross=0.5,
         entry_time="2017-10-02T10:45:00+00:00", fixed=None, is_t1=False):
    first_reached = status in om.FIRST_REACHED_STATUSES \
        if first_reached is None else first_reached
    first_leg = None
    runner_leg = None
    if status in om.TRADED_STATUSES:
        first_leg = {"pct": 0.5, "exit_bar": 2, "exit_price": 110.0,
                     "exit_reason": "FIRST_OBJECTIVE"
                     if first_reached else "SL",
                     "leg_r": 0.5 if first_reached else -0.5}
        runner_leg = {"pct": 0.5, "exit_bar": 5,
                      "exit_price": 120.0 if runner_reason == "RUNNER_TARGET"
                      else (90.0 if runner_reason == "SL" else 103.0),
                      "exit_reason": runner_reason,
                      "leg_r": 1.0 if runner_reason == "RUNNER_TARGET"
                      else (-0.5 if runner_reason == "SL" else 0.15)}
    return {
        "entry_id": entry_id, "symbol": symbol, "entry_time": entry_time,
        "direction": "BULL", "is_t1": is_t1, "entry_price": 100.0,
        "stop_price": 90.0,
        "rungs": [list(r) for r in rungs],
        "fixed_reached": fixed if fixed is not None
        else {"1": True, "2": False, "3": False, "4": False, "5": False},
        "status": status, "first_leg": first_leg, "runner_leg": runner_leg,
        "gross_trade_r": gross if status in om.TRADED_STATUSES else None,
    }


def _population(symbol="EURUSD", n_first_reached=6, n_total=10):
    rows = []
    for i in range(n_first_reached):        # first reached; runner varies
        reason = ("RUNNER_TARGET" if i % 2 == 0 else
                  ("SL" if i % 3 == 1 else "HORIZON_CLOSE"))
        rows.append(_row(f"{symbol}:{i}", symbol, "FIRST_PLUS_RUNNER_TARGET"
                         if reason == "RUNNER_TARGET"
                         else ("FIRST_PLUS_RUNNER_STOP"
                               if reason == "SL"
                               else "FIRST_PLUS_RUNNER_HORIZON"),
                         runner_reason=reason))
    for i in range(n_total - n_first_reached):
        rows.append(_row(f"{symbol}:9{i}", symbol,
                         "STOPPED_BEFORE_FIRST",
                         rungs=((1.0, False), (2.0, False))))
    return rows


# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

def test_first_objective_reach_and_continuation_metrics():
    evidence = _population(n_first_reached=6, n_total=10)
    m = om._metric_block(evidence)
    assert m["ENTRY_N"] == 10 and m["TRADED_N"] == 10
    assert m["FIRST_OBJECTIVE_REACHED_N"] == 6
    assert m["FIRST_OBJECTIVE_REACHED_PCT"] == pytest.approx(0.6)
    # runner extended reach: 3 of the 6 first-reached hit the runner target
    assert m["RUNNER_EXTENDED_REACH"] == pytest.approx(3 / 6)
    # P(second|first): rung[1].reached is True for first-reached rows here
    assert m["P_SECOND_GIVEN_FIRST"] == pytest.approx(1.0)
    assert m["R1_CAPABILITY"] == pytest.approx(1.0)
    assert m["R5_CAPABILITY"] == pytest.approx(0.0)


def test_not_applicable_rows_are_excluded_from_traded_basis():
    rows = _population(n_first_reached=2, n_total=4)
    rows.append(_row("EURUSD:NA1", "EURUSD",
                     "NOT_APPLICABLE_NO_RUNNER_OBJECTIVE",
                     rungs=((1.0, True),)))
    rows.append(_row("EURUSD:NA2", "EURUSD", "NOT_APPLICABLE_NO_OBJECTIVE",
                     rungs=()))
    m = om._metric_block(rows)
    assert m["ENTRY_N"] == 6
    assert m["TRADED_N"] == 4
    assert m["NOT_APPLICABLE_N"] == 2
    assert m["FIRST_OBJECTIVE_AVAILABLE_N"] == 5      # NA2 has no ladder
    assert m["SECOND_OBJECTIVE_AVAILABLE_N"] == 4     # NA1 has one level
    assert m["FURTHEST_OBJECTIVE_AVAILABLE_N"] == 4   # == traded
    # natural target quantiles include NA1's single rung (full population)
    assert m["NATURAL_TARGET_MEDIAN_R"] == pytest.approx(1.0)
    assert m["RIGHT_CENSORED_N"] == 0


def test_drawdown_definition():
    rows = []
    for i, gross in enumerate([1.0, -0.5, -0.5, 2.0, -3.0]):
        rows.append(_row(f"EURUSD:{i}", "EURUSD", "FIRST_PLUS_RUNNER_TARGET",
                         gross=gross,
                         entry_time=f"2017-10-0{i + 1}T10:45:00+00:00"))
    m = om._metric_block(rows)
    # cumulative: 1.0, 0.5, 0.0, 2.0, -1.0 -> max dd = 2.0 - (-1.0) = 3.0
    assert m["MAX_STRUCTURAL_DRAWDOWN_R"] == pytest.approx(3.0)
    assert m["GROSS_STRUCTURAL_R"] == pytest.approx(-1.0)
    assert m["MEAN_STRUCTURAL_R"] == pytest.approx(-0.2)


def test_runner_contributions_split_by_exit_reason():
    rows = [
        _row("EURUSD:0", "EURUSD", "FIRST_PLUS_RUNNER_TARGET",
             runner_reason="RUNNER_TARGET"),
        _row("EURUSD:1", "EURUSD", "FIRST_PLUS_RUNNER_STOP",
             runner_reason="SL"),
        _row("EURUSD:2", "EURUSD", "FIRST_PLUS_RUNNER_HORIZON",
             runner_reason="HORIZON_CLOSE"),
    ]
    m = om._metric_block(rows)
    assert m["RUNNER_TARGET_N"] == 1 and m["RUNNER_STOP_N"] == 1 \
        and m["RUNNER_HORIZON_N"] == 1
    assert m["RUNNER_TARGET_CONTRIBUTION_R"] == pytest.approx(1.0)
    assert m["RUNNER_LOSS_CONTRIBUTION_R"] == pytest.approx(-0.5)
    assert m["RUNNER_HORIZON_CLOSE_CONTRIBUTION_R"] == pytest.approx(0.15)
    assert m["RUNNER_CONTRIBUTION_R"] == pytest.approx(0.65)
    assert m["FIRST_LEG_CONTRIBUTION_R"] == pytest.approx(1.5)


def test_normalize_rungs_dedupes_shared_levels():
    rungs = [(2.0, True), (1.0, False), (2.0, False), (1.5, True)]
    assert om.normalize_rungs(rungs) == [[1.0, False], [1.5, True], [2.0, True]]


# ---------------------------------------------------------------------------
# Preregistered verdict rules
# ---------------------------------------------------------------------------

def _refs(first_pct=0.6, p_second=0.6, runner_reach=0.4, mean_r=0.06):
    def block():
        return {"FIRST_OBJECTIVE_REACHED_PCT": first_pct,
                "P_SECOND_GIVEN_FIRST": p_second,
                "RUNNER_EXTENDED_REACH": runner_reach,
                "MEAN_STRUCTURAL_R": mean_r}
    return {"pooled": block(),
            "by_symbol": {s: block() for s in om.SYMBOLS}}


def _oos(first_pct=0.6, p_second=0.6, runner_reach=0.4, mean_r=0.06,
         traded=500):
    def block(n):
        return {"FIRST_OBJECTIVE_REACHED_PCT": first_pct,
                "P_SECOND_GIVEN_FIRST": p_second,
                "RUNNER_EXTENDED_REACH": runner_reach,
                "MEAN_STRUCTURAL_R": mean_r, "TRADED_N": n}
    return {"pooled": block(traded),
            "by_symbol": {s: block(traded // 4) for s in om.SYMBOLS}}


def test_verdict_a_when_deltas_within_tolerance():
    verdict = om.evaluate_verdict(_oos(mean_r=0.04), _refs())
    assert verdict["FINAL_VERDICT"] == "A"
    assert all(v["verdict"] == "A" for v in verdict["by_symbol"].values())


def test_verdict_b_on_weakening_pp_delta():
    # first-objective reach drops 12pp -> weaken (B), not fail
    verdict = om.evaluate_verdict(_oos(first_pct=0.48), _refs())
    assert verdict["FINAL_VERDICT"] == "B"


def test_verdict_c_on_fail_pp_delta():
    # continuation collapses 25pp -> fail (C)
    verdict = om.evaluate_verdict(_oos(p_second=0.35), _refs())
    assert verdict["FINAL_VERDICT"] == "C"


def test_verdict_c_on_nonpositive_mean():
    verdict = om.evaluate_verdict(_oos(mean_r=0.0), _refs())
    assert verdict["FINAL_VERDICT"] == "C"


def test_verdict_b_on_mean_below_half_retention():
    # mean 0.02 < 0.5 * 0.06 but > 0 -> B
    verdict = om.evaluate_verdict(_oos(mean_r=0.02), _refs())
    assert verdict["FINAL_VERDICT"] == "B"


def test_failed_symbol_not_hidden_by_pooled():
    oos = _oos(mean_r=0.05)
    oos["by_symbol"]["XAUUSD"]["FIRST_OBJECTIVE_REACHED_PCT"] = 0.30  # -30pp
    verdict = om.evaluate_verdict(oos, _refs())
    assert verdict["by_symbol"]["XAUUSD"]["verdict"] == "C"
    assert verdict["FINAL_VERDICT"] == "C"


def test_insufficient_pooled_sample_is_d():
    verdict = om.evaluate_verdict(_oos(traded=299), _refs())
    assert verdict["FINAL_VERDICT"] == "D"


def test_two_subsampled_symbols_force_d():
    oos = _oos(traded=500)
    oos["by_symbol"]["USDJPY"]["TRADED_N"] = 39
    oos["by_symbol"]["XAUUSD"]["TRADED_N"] = 20
    verdict = om.evaluate_verdict(oos, _refs())
    assert verdict["FINAL_VERDICT"] == "D"
    assert verdict["by_symbol"]["USDJPY"]["verdict"] == "D_SUBSAMPLED"


def test_single_subsampled_symbol_caps_final_at_b():
    oos = _oos()
    oos["by_symbol"]["XAUUSD"]["TRADED_N"] = 10
    verdict = om.evaluate_verdict(oos, _refs())
    assert verdict["FINAL_VERDICT"] == "B"
    assert verdict["by_symbol"]["XAUUSD"]["verdict"] == "D_SUBSAMPLED"


# ---------------------------------------------------------------------------
# DEV frozen evidence extraction (uses the committed DEV artifacts)
# ---------------------------------------------------------------------------

DEV_BUNDLE = Path(__file__).resolve().parents[1] / "data" / "artifacts" / \
    "target_policy_c3_v1"
V06 = Path(__file__).resolve().parents[1] / "data" / "artifacts" / \
    "universal_funnel_v0_6_target_policy"


@pytest.mark.skipif(not (DEV_BUNDLE / "dev_resolution_ledger.jsonl").exists(),
                    reason="frozen DEV bundle not present")
def test_dev_frozen_evidence_reproduces_pinned_dev_references():
    evidence = om.evidence_from_dev_frozen(
        DEV_BUNDLE / "dev_resolution_ledger.jsonl",
        V06 / "entry_policy_ledger.jsonl",
        V06 / "objective_sequence_ledger.jsonl")
    assert len(evidence) == 3183
    m = om.compute_metrics(evidence)
    pooled = m["pooled"]
    assert pooled["ENTRY_N"] == 3183
    assert pooled["TRADED_N"] == 3092
    assert pooled["FIRST_OBJECTIVE_REACHED_PCT"] == pytest.approx(
        2109 / 3092)
    assert pooled["RUNNER_EXTENDED_REACH"] == pytest.approx(870 / 2109)
    assert round(pooled["NATURAL_TARGET_MEDIAN_R"], 3) == 0.402
    assert pooled["UNRESOLVED_RUNNER_N"] == 0
    assert pooled["RIGHT_CENSORED_N"] == 0
    # T1 subset pinned
    assert pooled["ENTRY_N"] - sum(
        1 for e in evidence if e["is_t1"]) >= 0


@pytest.mark.skipif(not (DEV_BUNDLE / "dev_resolution_ledger.jsonl").exists(),
                    reason="frozen DEV bundle not present")
def test_dev_frozen_evidence_ladder_consistency():
    evidence = om.evidence_from_dev_frozen(
        DEV_BUNDLE / "dev_resolution_ledger.jsonl",
        V06 / "entry_policy_ledger.jsonl",
        V06 / "objective_sequence_ledger.jsonl")
    for e in evidence:
        if e["status"] in om.TRADED_STATUSES:
            assert len(e["rungs"]) >= 2
            assert e["rungs"][-1][0] > e["rungs"][0][0]
        if e["status"] == "NOT_APPLICABLE_NO_RUNNER_OBJECTIVE":
            assert len(e["rungs"]) <= 1


# ---------------------------------------------------------------------------
# Comparison structure
# ---------------------------------------------------------------------------

def test_compare_dev_oos_uses_pp_for_rates_and_r_for_levels():
    oos = om.compute_metrics(_population())
    dev = om.compute_metrics(_population())
    comparison = om.compare_dev_oos(oos, dev)
    assert comparison["pooled"]["FIRST_OBJECTIVE_REACHED_PCT"]["delta"] == \
        pytest.approx(0.0)
    assert comparison["pooled"]["FIRST_OBJECTIVE_REACHED_PCT"]["delta_pp"] \
        is True
    assert comparison["pooled"]["MEAN_STRUCTURAL_R"].get("delta_pp") is None
    assert set(comparison["by_symbol"]) == set(om.SYMBOLS)


def test_preregistered_thresholds_are_frozen_values():
    assert om.THRESHOLDS["POOLED_MIN_TRADED_N"] == 300
    assert om.THRESHOLDS["SYMBOL_MIN_TRADED_N"] == 40
    assert om.THRESHOLDS["WEAKEN_DELTA_PP"] == 10.0
    assert om.THRESHOLDS["FAIL_DELTA_PP"] == 20.0
    assert om.THRESHOLDS["MEAN_RETENTION_FOR_A"] == 0.5
    assert om.THRESHOLDS["MEAN_SURVIVE_FLOOR_R"] == 0.0
    assert om.THRESHOLDS["GATING_PP_METRICS"] == (
        "FIRST_OBJECTIVE_REACHED_PCT", "P_SECOND_GIVEN_FIRST",
        "RUNNER_EXTENDED_REACH")


def test_verdict_json_roundtrip_stability():
    # the verdict structure must survive canonical serialization (the
    # independent verifier re-loads and re-evaluates it)
    verdict = om.evaluate_verdict(_oos(), _refs())
    payload = json.loads(json.dumps(verdict))
    again = om.evaluate_verdict(_oos(), _refs(),
                                payload["thresholds"])
    assert again["FINAL_VERDICT"] == verdict["FINAL_VERDICT"]
