"""MISSION 3B-A — engine, governance gate, funnel and determinism tests.

Phases 12 (determinism) and 13 (adversarial). Synthetic fixtures only; no
market corpus is read and no real registry is consulted.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from ag_edgelab.data.fingerprint import canonical_json
from ag_edgelab.governance import v2_1_data_authorization as GATE
from ag_edgelab.strategies import asian_liquidity_displacement_v2_1 as V
from ag_edgelab.strategies import v2_1_engine as E
from ag_edgelab.strategies import v2_1_funnel as F
from tests.fixtures_v2_1 import (
    SYNTHETIC_POLICY,
    bar,
    bars_a_success,
    build_scenarios,
    forward_bear_target,
    opp,
    run_synthetic_engine,
)

UTC = timezone.utc


def all_trades() -> list[dict]:
    rows: list[dict] = []
    for s in build_scenarios():
        engine, _ = run_synthetic_engine(s)
        rows += engine.trade_ledger()
    return rows


# ===========================================================================
# PHASE 12 — determinism
# ===========================================================================

def _full_pass() -> dict:
    trades, transitions, events = [], [], []
    for s in build_scenarios():
        engine, _ = run_synthetic_engine(s)
        trades += engine.trade_ledger()
        transitions += engine.transition_ledger()
        events += engine.event_ledger()
    return {"events": events, "trades": trades, "transitions": transitions,
            "funnel": F.funnel_by_dimension(trades),
            "robustness": F.robustness_report(trades)}


def test_two_synthetic_runs_are_canonical_hash_identical():
    h1 = hashlib.sha256(canonical_json(_full_pass()).encode()).hexdigest()
    h2 = hashlib.sha256(canonical_json(_full_pass()).encode()).hexdigest()
    assert h1 == h2


@pytest.mark.parametrize("section", ["events", "trades", "transitions",
                                     "funnel", "robustness"])
def test_each_ledger_section_is_independently_deterministic(section):
    a, b = _full_pass()[section], _full_pass()[section]
    assert canonical_json(a) == canonical_json(b)


def test_engine_ledger_hash_is_stable():
    e1, _ = run_synthetic_engine(build_scenarios()[0])
    e2, _ = run_synthetic_engine(build_scenarios()[0])
    assert e1.ledger_hash() == e2.ledger_hash()


def test_bootstrap_is_seeded_and_reproducible():
    trades = all_trades()
    assert F._bootstrap(trades) == F._bootstrap(trades)


# ===========================================================================
# PHASE 13 — adversarial: temporal isolation
# ===========================================================================

def test_future_mutation_isolation_later_bars_cannot_change_earlier_states():
    """Mutating bars after the entry must not move any transition."""
    base = opp(bars_a_success(), forward=forward_bear_target())
    mutated_bars = bars_a_success()
    mutated_bars[5] = bar(5, 100.45, 999.0, 0.5, 900.0)   # absurd future bar
    mutated = opp(mutated_bars, forward=forward_bear_target())

    e1 = E.V21Engine(SYNTHETIC_POLICY, allow_synthetic=True)
    e2 = E.V21Engine(SYNTHETIC_POLICY, allow_synthetic=True)
    mss = lambda i: i == 4  # noqa: E731
    never = lambda i: False  # noqa: E731
    t1 = e1.evaluate(base, mss_confirmed_at=mss, continuation_confirmed_at=never)
    t2 = e2.evaluate(mutated, mss_confirmed_at=mss, continuation_confirmed_at=never)

    assert e1.transition_ledger() == e2.transition_ledger()
    assert (t1.entry_price, t1.stop_price) == (t2.entry_price, t2.stop_price)


def test_every_transition_records_the_mandated_attribution_fields():
    engine, _ = run_synthetic_engine(build_scenarios()[0])
    required = {"event_id", "symbol", "trading_date", "session", "branch",
                "boundary", "from_state", "to_state", "decision_timestamp",
                "source_bar_timestamp", "reason_code"}
    rows = engine.transition_ledger()
    assert rows
    for row in rows:
        assert required <= set(row)
        assert row["reason_code"] and row["reason_code"] != "UNSPECIFIED"
        assert row["decision_timestamp"] > row["source_bar_timestamp"]


def test_decision_timestamp_is_the_bar_close_not_the_bar_open():
    engine, _ = run_synthetic_engine(build_scenarios()[0])
    row = engine.transition_ledger()[0]
    src = datetime.fromisoformat(row["source_bar_timestamp"])
    dec = datetime.fromisoformat(row["decision_timestamp"])
    assert dec - src == timedelta(minutes=5)


# ===========================================================================
# PHASE 13 — adversarial: outcome engine
# ===========================================================================

def test_same_bar_collision_resolves_to_the_stop():
    """Bar touches both. Frozen STOP_FIRST policy must choose the stop."""
    both = [bar(0, 100.0, 103.0, 98.0, 100.0)]
    out = E.evaluate_outcome(both, bull=True, entry=100.0, stop=99.0, target=102.0)
    assert out["outcome"] == E.OUTCOME_STOP
    assert out["realised_r"] == -1.0
    assert out["same_bar_collision"] is True


def test_optimistic_sequencing_is_not_available():
    import inspect
    src = inspect.getsource(E.evaluate_outcome)
    assert "hit_stop" in src
    assert src.index("if hit_stop") < src.index("if hit_tp"), \
        "the stop must be evaluated before the target"


def test_natural_target_reached_is_recorded():
    fwd = [bar(0, 100.0, 100.5, 99.8, 100.2), bar(1, 100.2, 102.5, 100.1, 102.4)]
    out = E.evaluate_outcome(fwd, bull=True, entry=100.0, stop=99.0, target=102.0)
    assert out["outcome"] == E.OUTCOME_NATURAL_TARGET
    assert out["realised_r"] == pytest.approx(2.0)


def test_unresolved_when_no_forward_bars_exist():
    out = E.evaluate_outcome([], bull=True, entry=100.0, stop=99.0, target=102.0)
    assert out["outcome"] == E.OUTCOME_UNRESOLVED
    assert out["realised_r"] is None


def test_outcome_horizon_is_respected():
    long = [bar(i, 100.0, 100.4, 99.8, 100.1)
            for i in range(V.OUTCOME_HORIZON_M5_BARS + 50)]
    out = E.evaluate_outcome(long, bull=True, entry=100.0, stop=99.0, target=102.0)
    assert out["bars_held"] == V.OUTCOME_HORIZON_M5_BARS
    assert out["outcome"] == E.OUTCOME_SESSION_EXPIRED


def test_fixed_r_flags_are_diagnostic_and_monotone():
    fwd = [bar(0, 100.0, 103.6, 99.9, 103.5)]
    out = E.evaluate_outcome(fwd, bull=True, entry=100.0, stop=99.0, target=110.0)
    reached = out["reached"]
    assert reached["1R"] and reached["2R"] and reached["3R"]
    assert not reached["5R"]


# ===========================================================================
# PHASE 13 — adversarial: geometry and targets
# ===========================================================================

def test_missing_target_yields_invalid_geometry_not_a_manufactured_r():
    o = opp(bars_a_success())
    from ag_edgelab.strategies.symbol_metadata import metadata_for
    policy = SYNTHETIC_POLICY
    # bear trade sitting BELOW every candidate level -> nothing is "beyond"
    geom = E.compute_geometry(o, policy, entry=96.0, stop=97.0,
                              entry_timestamp=o.bars[-1].timestamp,
                              bull=False, meta=metadata_for("USDJPY"))
    assert geom["ok"] is False
    assert geom["reason"] in ("NO_NATURAL_TARGET", "NATURAL_R_BELOW_FLOOR")
    assert "target" not in geom


def test_future_target_leakage_raises():
    now = datetime(2016, 3, 1, 8, 0, tzinfo=UTC)
    future = V.TargetCandidate(authority="OPPOSITE_SESSION_BOUNDARY",
                               level=102.0, known_at=now + timedelta(minutes=5))
    with pytest.raises(ValueError, match="future leakage"):
        V.resolve_natural_target([future], entry_price=100.0, stop_price=99.0,
                                 entry_timestamp=now, direction_is_bull=True)


def test_invalid_geometry_when_stop_is_on_the_wrong_side():
    from ag_edgelab.strategies.symbol_metadata import metadata_for
    o = opp(bars_a_success())
    geom = E.compute_geometry(o, SYNTHETIC_POLICY, entry=100.0, stop=101.0,
                              entry_timestamp=o.bars[-1].timestamp,
                              bull=True, meta=metadata_for("USDJPY"))
    assert geom == {"ok": False, "reason": "GEOMETRY_STOP_WRONG_SIDE"}


def test_zero_risk_geometry_is_refused():
    from ag_edgelab.strategies.symbol_metadata import metadata_for
    o = opp(bars_a_success())
    geom = E.compute_geometry(o, SYNTHETIC_POLICY, entry=100.0, stop=100.0,
                              entry_timestamp=o.bars[-1].timestamp,
                              bull=True, meta=metadata_for("USDJPY"))
    assert geom["ok"] is False and geom["reason"] == "GEOMETRY_RISK_NON_POSITIVE"


def test_boundary_equality_is_not_a_breach():
    """Touching the boundary exactly is not 'strictly beyond' it."""
    from ag_edgelab.strategies.symbol_metadata import metadata_for
    meta = metadata_for("USDJPY")
    flat = [bar(i, 100.9, 101.0, 100.8, 100.9) for i in range(6)]
    res = V.run_branch_a(flat, boundary=101.0, boundary_side="HIGH",
                         reference_range=2.0, meta=meta,
                         mss_confirmed_at=lambda i: True)
    assert res.invalidation_reason == "NO_SWEEP"


# ===========================================================================
# PHASE 13 — adversarial: symbol precision
# ===========================================================================

@pytest.mark.parametrize("symbol,tick", [("EURUSD", 0.00001), ("GBPUSD", 0.00001),
                                         ("USDJPY", 0.001), ("XAUUSD", 0.01)])
def test_symbol_precision_governs_the_sweep_floor(symbol, tick):
    from ag_edgelab.strategies.symbol_metadata import metadata_for
    meta = metadata_for(symbol)
    assert meta.tick_size == tick
    sub = tick * 0.1
    bars = [bar(0, 100.9, 101.0 + sub, 100.8, 100.9)] + \
           [bar(i, 100.9, 100.95, 100.8, 100.85) for i in range(1, 6)]
    res = V.run_branch_a(bars, boundary=101.0, boundary_side="HIGH",
                         reference_range=2.0, meta=meta,
                         mss_confirmed_at=lambda i: True)
    assert res.invalidation_reason == "NO_SWEEP", \
        f"{symbol}: a sub-tick graze must not register as a sweep"


def test_jpy_and_gold_are_not_governed_by_a_eurusd_constant():
    from ag_edgelab.strategies.symbol_metadata import metadata_for
    eur, jpy, xau = (metadata_for(s) for s in ("EURUSD", "USDJPY", "XAUUSD"))
    assert jpy.tick_size == eur.tick_size * 100
    assert xau.tick_size == eur.tick_size * 1000
    graze = 0.00005                     # half a JPY tick... but 5 EURUSD ticks
    assert eur.at_least_one_tick(graze)
    assert not jpy.at_least_one_tick(graze)
    assert not xau.at_least_one_tick(graze)


# ===========================================================================
# PHASE 13 — adversarial: event governance
# ===========================================================================

@pytest.mark.parametrize("scenario", build_scenarios(), ids=lambda s: s.name)
def test_every_mandated_governance_case_behaves(scenario):
    engine, _ = run_synthetic_engine(scenario)
    assert engine.registry.accepted_n <= len(scenario.opportunities)
    for rec in engine.event_ledger():
        assert len(rec["HANDOVERS"]) <= V.HANDOVER_MAX


def test_duplicate_event_is_suppressed_not_traded_twice():
    scenario = next(s for s in build_scenarios()
                    if s.name == "DUPLICATE_REPEATED_CANDLE")
    engine, _ = run_synthetic_engine(scenario)
    assert engine.registry.accepted_n == 1
    assert engine.registry.suppressed_n == 1


def test_handover_exhaustion_stops_the_search():
    scenario = next(s for s in build_scenarios()
                    if s.name == "A_FAILS_THEN_B_HANDOVER")
    engine, _ = run_synthetic_engine(scenario)
    handovers = [h for r in engine.event_ledger() for h in r["HANDOVERS"]]
    assert len(handovers) == 1 == V.HANDOVER_MAX


def test_opposite_boundary_is_a_separate_lock_key():
    scenario = next(s for s in build_scenarios()
                    if s.name == "DUPLICATE_BOUNDARY_TOUCH")
    engine, _ = run_synthetic_engine(scenario)
    assert engine.registry.accepted_n == 2
    assert engine.registry.suppressed_n == 0


def test_session_rollover_is_a_fresh_lock_key():
    scenario = next(s for s in build_scenarios() if s.name == "SESSION_ROLLOVER")
    engine, _ = run_synthetic_engine(scenario)
    assert engine.registry.accepted_n == 2


def test_session_expiry_prevents_an_entry_after_the_window():
    """Bars end before confirmation can occur -> no entry, recorded reason."""
    short = opp(bars_a_success()[:3])
    engine = E.V21Engine(SYNTHETIC_POLICY, allow_synthetic=True)
    tr = engine.evaluate(short, mss_confirmed_at=lambda i: i == 4,
                         continuation_confirmed_at=lambda i: False)
    assert tr.stages.get("ENTRY_AVAILABLE") is False
    assert tr.reject_reason == "MSS_TIMEOUT"


# ===========================================================================
# PHASE 13 — adversarial: contract ambiguity refusal
# ===========================================================================

def test_engine_refuses_a_policy_that_does_not_resolve_every_ambiguity():
    with pytest.raises(E.ContractAmbiguityError):
        E.ReplayPolicy(
            provenance=E.SYNTHETIC_PROVENANCE,
            enumerate_opportunities=lambda *a, **k: (),
            context_eligible=lambda o: (True, "PASS"),
            location_eligible=lambda o: (True, "PASS"),
            select_initial_branch=lambda o: V.Branch.A.value,
            prior_day_levels=lambda o, **k: [],
            swing_liquidity_levels=lambda o, **k: [],
            resolves_ambiguities=("AMB_1_OPPORTUNITY_UNIT",),
        )


def test_synthetic_policy_may_not_drive_a_real_replay():
    with pytest.raises(E.PolicyProvenanceError):
        E.V21Engine(SYNTHETIC_POLICY)          # allow_synthetic defaults False


def test_ambiguities_are_enumerated_with_an_owner_question():
    assert len(E.CONTRACT_AMBIGUITIES) == 4
    for a in E.CONTRACT_AMBIGUITIES:
        assert a["question_for_owner"].endswith("?") or "Define" in a["question_for_owner"]
        assert a["hook"] and a["why_it_matters"]


# ===========================================================================
# PHASE 13 — adversarial: data authorization gate
# ===========================================================================

def base_request(**over) -> GATE.DataRequest:
    kw = dict(symbols=("EURUSD", "XAUUSD"),
              symbol_years=(("EURUSD", 2016), ("XAUUSD", 2016)),
              date_range=("2016-01-01", "2016-09-01"),
              role="DEVELOPMENT",
              contract_hash="CONTRACT_X",
              preregistration_hash="PREREG_X",
              dataset_binding_hash="BINDING_X",
              policy_provenance=E.OWNER_RESOLVED_PROVENANCE)
    kw.update(over)
    return GATE.DataRequest(**kw)


def test_clean_development_request_is_authorized():
    out = GATE.authorize(base_request(), GATE.mock_governance_state())
    assert out["verdict"] == GATE.AUTHORIZED_DEVELOPMENT and out["authorized"]


def test_contaminated_symbol_year_is_denied():
    req = base_request(symbols=("EURUSD", "GBPUSD"),
                       symbol_years=(("EURUSD", 2016), ("GBPUSD", 2016)))
    out = GATE.authorize(req, GATE.mock_governance_state())
    assert out["verdict"] == GATE.DENIED_CONTAMINATED


def test_oos_overlap_is_denied():
    out = GATE.authorize(base_request(date_range=("2016-01-01", "2016-10-01")),
                         GATE.mock_governance_state())
    assert out["verdict"] == GATE.DENIED_OOS


def test_holdout_overlap_is_denied_and_outranks_oos():
    out = GATE.authorize(base_request(date_range=("2016-01-01", "2016-12-15")),
                         GATE.mock_governance_state())
    assert out["verdict"] == GATE.DENIED_HOLDOUT


@pytest.mark.parametrize("field", ["contract_hash", "preregistration_hash",
                                   "dataset_binding_hash"])
def test_identity_mismatch_is_denied(field):
    out = GATE.authorize(base_request(**{field: "WRONG"}),
                         GATE.mock_governance_state())
    assert out["verdict"] == GATE.DENIED_IDENTITY_MISMATCH


def test_unpermitted_symbol_year_is_unknown_exposure():
    req = base_request(symbols=("EURUSD",), symbol_years=(("EURUSD", 1999),))
    out = GATE.authorize(req, GATE.mock_governance_state())
    assert out["verdict"] == GATE.DENIED_UNKNOWN_EXPOSURE


def test_unknown_role_is_unknown_exposure():
    out = GATE.authorize(base_request(role="PRODUCTION"),
                         GATE.mock_governance_state())
    assert out["verdict"] == GATE.DENIED_UNKNOWN_EXPOSURE


def test_synthetic_policy_is_denied_against_a_real_partition():
    out = GATE.authorize(base_request(policy_provenance=E.SYNTHETIC_PROVENANCE),
                         GATE.mock_governance_state())
    assert out["verdict"] == GATE.DENIED_UNKNOWN_EXPOSURE


def test_gate_emits_exactly_one_verdict_from_the_closed_set():
    out = GATE.authorize(base_request(), GATE.mock_governance_state())
    assert out["verdict"] in GATE.VERDICTS
    assert out["verdict_hash"]


def test_gate_is_pure_and_reads_no_dataset():
    import inspect
    src = inspect.getsource(GATE)
    for forbidden in ("open(", "read_text", "Path(", "requests", "load_manifest"):
        assert forbidden not in src, f"gate must not perform I/O: {forbidden}"


# ===========================================================================
# PHASE 13 — adversarial: friction
# ===========================================================================

def test_unknown_friction_is_never_zero_in_the_engine_path():
    claim = V.economic_claim()
    assert all(claim[k] == "UNKNOWN" for k in ("spread", "slippage",
                                               "commission", "swap"))
    assert claim["ECONOMIC_EDGE"] == "NOT_ESTIMABLE"


def test_scenario_friction_cannot_verify_edge():
    assert V.can_scenario_friction_verify_edge() is False


def test_no_friction_number_enters_the_outcome_engine():
    import inspect
    src = inspect.getsource(E.evaluate_outcome)
    for token in ("spread", "commission", "slippage", "swap"):
        assert token not in src


# ===========================================================================
# PHASE 7 — funnel instrumentation
# ===========================================================================

def test_funnel_table_reports_n_and_next_stage_percent():
    rows = F.funnel_table(all_trades())
    assert [r["stage"] for r in rows] == list(F.REPORTED_STAGES)
    for r in rows:
        assert set(r) >= {"stage", "N", "NEXT_STAGE_PERCENT",
                          "PCT_OF_PREVIOUS_STAGE", "PCT_OF_OPPORTUNITIES"}


def test_funnel_is_monotone_non_increasing():
    rows = F.funnel_table(all_trades())
    ns = [r["N"] for r in rows]
    assert ns == sorted(ns, reverse=True)


def test_every_required_reporting_dimension_is_present():
    report = F.funnel_by_dimension(all_trades())
    for dim in F.REPORT_DIMENSIONS:
        assert dim in report


def test_branch_report_flags_but_never_deletes_a_branch():
    rep = F.branch_report(all_trades())
    assert set(rep) == {b.value for b in V.Branch}
    for body in rep.values():
        assert body["state"] in ("BRANCH_POWERED", "BRANCH_UNDERPOWERED")
        assert "never deleted" in body["deletion_policy"]


def test_session_windows_are_the_frozen_clocks():
    assert V.SESSION_PAIRS["ASIAN_LONDON"] == V.LONDON_ENTRY_UTC == (7, 10)
    assert V.SESSION_PAIRS["LONDON_NEWYORK"] == V.NEW_YORK_ENTRY_UTC == (12, 15)
    assert V.REFERENCE_WINDOW_UTC == (0, 6)


# ===========================================================================
# PHASE 9 — robustness engine
# ===========================================================================

def test_robustness_is_not_reached_below_the_sample_floor():
    rep = F.robustness_report(all_trades())
    assert rep["PRE_OOS_RESULT"] == "NOT_REACHED"
    assert rep["reason"] == "DEV_REJECTED_INSUFFICIENT_SAMPLE"
    assert all(a["state"] == "NOT_RUN_INSUFFICIENT_SAMPLE"
               for a in rep["axes"].values())


def test_all_ten_axes_exist():
    assert len(F.ROBUSTNESS_AXES) == 10
    for axis in ("POOLED_EXPECTANCY", "BOOTSTRAP", "YEAR_STABILITY",
                 "SYMBOL_STABILITY", "SESSION_STABILITY", "BRANCH_STABILITY",
                 "REGIME_STABILITY", "TAIL_DEPENDENCE", "TARGET_CAPABILITY",
                 "PARAMETER_NEIGHBORHOOD"):
        assert axis in F.ROBUSTNESS_AXES


def test_parameter_neighborhood_never_silently_passes():
    axis = F.parameter_neighborhood_axis()
    assert axis["state"] == "NOT_APPLICABLE"
    assert axis["counts_toward_pass"] is False
    assert axis["state"] != "PASS"


def test_sample_floor_is_the_unchanged_v1_value_and_cannot_be_relaxed():
    gate = F.sample_gate(all_trades())
    assert gate["SAMPLE_FLOOR"] == 100
    assert gate["relaxation_after_results"] == "FORBIDDEN"


def test_robustness_thresholds_are_declared_unchanged():
    rep = F.robustness_report(all_trades())
    assert rep["thresholds_unchanged"] is True


# ===========================================================================
# Mission invariants
# ===========================================================================

def test_no_real_historical_replay_artifact_was_produced():
    from pathlib import Path
    out = Path("data/artifacts/gen2_ald_v2_1")
    forbidden = {"final_report.json", "v1_vs_v2.json", "pre_oos_gate_result.json",
                 "trade_ledger.jsonl.gz", "candidate_ledger.jsonl.gz"}
    if out.exists():
        assert not ({p.name for p in out.iterdir()} & forbidden)


def test_frozen_contract_hash_is_unchanged_by_this_mission():
    assert V.contract_hash() == \
        "2c5cfa8c1608cbed20d66606292bb90c6049310665afc59ee5079ce86bbb86d9"
