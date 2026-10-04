"""V0.6 NATURAL TARGET + RUNNER POLICY — unit tests (Phase 17)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.derive import aggregate_bars
from ag_edgelab.data.fx_histdata_2017 import PARTITIONS, derive_fx_timeframe
from ag_edgelab.universal.campaign import make_synthetic_fx_bars
from ag_edgelab.universal.direction import Direction
from ag_edgelab.universal.fx_dev_campaign import (CONFIRMATION_WINDOW_BARS,
                                                  OUTCOME_HORIZON_BARS,
                                                  STOP_LOOKBACK_BARS,
                                                  run_fx_symbol_campaign)
from ag_edgelab.universal.targets import EntryGeometry, FIXED_R_TARGETS
from ag_edgelab.universal.trigger_v0_4 import enrich_symbol
from ag_edgelab.universal import target_v0_5 as tv5
from ag_edgelab.universal import target_policy_v0_6 as tp6
from ag_edgelab.universal.target_policy_v0_6 import (
    AUTHORITATIVE_V0_5_SHA, Objective, POLICY_IDS, PolicyEntry, SUPERSEDED_V0_5_SHA,
    _be_runner, build_policy_entries, entry_policy_rows, evaluate_all,
    paired_delta, policy_outcome)

UTC = timezone.utc
T0 = datetime(2017, 1, 2, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]
ART6 = ROOT / "data" / "artifacts" / "universal_funnel_v0_6_target_policy"
ART5 = ROOT / "data" / "artifacts" / "universal_funnel_v0_5_target"


def _bar(i: int, h: float, lo: float) -> MarketBar:
    mid = (h + lo) / 2.0
    return MarketBar(timestamp=T0 + timedelta(minutes=15 * i),
                     open=mid, high=h, low=lo, close=mid)


def mk_rec(**kw):
    """Minimal frozen-shaped tv5.EntryRecord for fabrication."""
    defaults = dict(
        symbol="EURUSD", obs_feed_index=0, entry_index=0, entry_time=T0,
        direction="BULL", session="LONDON", entry_price=1.0, stop_price=0.99,
        risk_distance=0.01, risk_distance_pips_or_points=100.0,
        pip_or_point_unit="PIP", mfe_r=1.0, mae_r=0.5, mfe_distance=0.01,
        mae_distance=0.005,
        fixed_reached={k: False for k in FIXED_R_TARGETS},
        time_to_r={k: None for k in FIXED_R_TARGETS},
        entry_class="STOP_BEFORE_1R",
        targets={f: None for f in tv5.NATURAL_FAMILIES},
        nearest_family=None, nearest_price=None, nearest_distance=None,
        nearest_target_r=None, nearest_reached=None, ladder=(),
        multi_objective=False, furthest_family=None, furthest_target_r=None,
        furthest_reached=None, second_target_r=None, second_reached=None,
        third_target_r=None, third_reached=None, is_t1=False, is_t2=False)
    defaults.update(kw)
    return tv5.EntryRecord(**defaults)


def mk_pe(first=None, second=None, furthest=None, stop_bar=None,
          fixed5_reached=False, fixed5_t=None, be=None, rec_kw=None):
    rec_kw = dict(rec_kw or {})
    if first is not None:
        rec_kw.setdefault("nearest_target_r", first.r)
        rec_kw.setdefault("nearest_reached", first.reached)
    fixed = {k: False for k in FIXED_R_TARGETS}
    fixed[5] = fixed5_reached
    rec_kw.setdefault("fixed_reached", fixed)
    tt = {k: None for k in FIXED_R_TARGETS}
    tt[5] = fixed5_t
    rec_kw.setdefault("time_to_r", tt)
    rec = mk_rec(**rec_kw)
    fixed5 = Objective("FIXED_5R_CEILING", 1.05, 5.0, fixed5_reached, fixed5_t)
    return PolicyEntry(base=rec, stop_bar=stop_bar, first=first, second=second,
                       furthest=furthest, fixed5=fixed5,
                       be_runner=be or {"SECOND": None, "FURTHEST": None,
                                        "FIXED5": None},
                       runner_mfe_r=None, runner_mae_r=None)


FIRST = Objective("NT01_NEXT_CONFIRMED_STRUCTURAL_SWING", 1.008, 0.8, True, 5)
SECOND = Objective("NT02_PREVIOUS_DAY_DIRECTIONAL_EXTREME", 1.02, 2.0, True, 12)


# ---------------------------------------------------------------------------
# authority + parent reproduction wiring
# ---------------------------------------------------------------------------

class TestAuthorityResolution:
    def test_resolver_establishes_b_over_a(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import run_target_policy_v0_6 as runner
        ok, res = runner.resolve_v0_5_authority()
        assert ok
        assert res["AUTHORITATIVE_V0_5_SHA"] == AUTHORITATIVE_V0_5_SHA
        assert res["SUPERSEDES"] == SUPERSEDED_V0_5_SHA
        assert res["supersession_evidence"]["b_descends_from_a"]
        assert res["contract_a_hash"] != res["contract_b_hash"]

    def test_pins_match_authoritative_v0_5_artifacts(self):
        f = json.load(open(ART5 / "final_report.json"))
        assert f["entry_n"] == {"D01": 3183, "T1": 379}
        pq = f["primary_target_quantiles"]["D01"]
        assert round(pq["P25"], 3) == 0.150
        assert round(pq["P50"], 3) == 0.402
        assert round(pq["P75"], 3) == 0.891
        assert round(f["furthest_target_quantiles"]["T1"]["P50"], 3) == 2.967

    def test_v0_6_parent_reproduction_artifact_green(self):
        pr = json.load(open(ART6 / "parent_reproduction.json"))
        assert pr["all_match"] is True
        assert pr["authoritative_v0_5_sha"] == AUTHORITATIVE_V0_5_SHA


# ---------------------------------------------------------------------------
# partial + runner accounting
# ---------------------------------------------------------------------------

class TestPolicyAccounting:
    def test_control_outcomes(self):
        pe = mk_pe(first=FIRST, stop_bar=30,
                   rec_kw={"fixed_reached": {1: True, 2: True, 3: False,
                                             4: False, 5: False}})
        assert policy_outcome(pe, "C0_2R") == {"status": "FULL_TARGET",
                                               "structural_r": 2.0}
        assert policy_outcome(pe, "C0_5R") == {"status": "STOPPED",
                                               "structural_r": -1.0}

    def test_c1_full_exit_at_first(self):
        pe = mk_pe(first=FIRST, stop_bar=30)
        out = policy_outcome(pe, "C1")
        assert out["status"] == "FULL_TARGET"
        assert out["structural_r"] == pytest.approx(0.8)

    @pytest.mark.parametrize("f,expected", [(25, 0.25 * 0.8 + 0.75 * 2.0),
                                            (50, 0.50 * 0.8 + 0.50 * 2.0),
                                            (75, 0.75 * 0.8 + 0.25 * 2.0)])
    def test_partial_plus_runner_target_math(self, f, expected):
        pe = mk_pe(first=FIRST, second=SECOND, stop_bar=None)
        out = policy_outcome(pe, f"C2_F{f}_R0")
        assert out["status"] == "PARTIAL_PLUS_RUNNER_TARGET"
        assert out["structural_r"] == pytest.approx(expected)

    def test_partial_plus_runner_stopped_math(self):
        second = Objective(SECOND.family, SECOND.price, 2.0, False, None)
        pe = mk_pe(first=FIRST, second=second, stop_bar=40)
        out = policy_outcome(pe, "C2_F50_R0")
        assert out["status"] == "PARTIAL_PLUS_RUNNER_STOPPED"
        assert out["structural_r"] == pytest.approx(0.5 * 0.8 - 0.5)

    def test_runner_open_is_null_not_loss(self):
        second = Objective(SECOND.family, SECOND.price, 2.0, False, None)
        pe = mk_pe(first=FIRST, second=second, stop_bar=None)
        out = policy_outcome(pe, "C2_F50_R0")
        assert out["status"] == "PARTIAL_RUNNER_OPEN"
        assert out["structural_r"] is None

    def test_no_runner_credit_without_realized_first(self):
        # first objective NOT reached; a 'reached-looking' runner objective
        # can never pay: runner begins only after the first is realized
        first = Objective(FIRST.family, FIRST.price, 0.8, False, None)
        second = Objective(SECOND.family, SECOND.price, 2.0, False, None)
        pe = mk_pe(first=first, second=second, stop_bar=7)
        out = policy_outcome(pe, "C2_F50_R0")
        assert out["status"] == "STOPPED_BEFORE_FIRST"
        assert out["structural_r"] == -1.0

    def test_unavailable_objective_is_not_applicable(self):
        pe = mk_pe(first=None)
        for pid in ("C1", "C2_F50_R0", "C3_F50_R0", "C4_F50_R0"):
            out = policy_outcome(pe, pid)
            assert out["status"].startswith("NOT_APPLICABLE")
            assert out["structural_r"] is None
        # C2 with first but no second objective
        pe2 = mk_pe(first=FIRST, second=None)
        assert policy_outcome(pe2, "C2_F50_R0")["status"] == \
            "NOT_APPLICABLE_NO_RUNNER_OBJECTIVE"

    def test_c4_not_applicable_when_first_beyond_ceiling(self):
        first = Objective(FIRST.family, 1.06, 6.0, True, 9)
        pe = mk_pe(first=first)
        assert policy_outcome(pe, "C4_F50_R0")["status"] == \
            "NOT_APPLICABLE_NO_RUNNER_OBJECTIVE"


# ---------------------------------------------------------------------------
# R0 vs R1 separation (PHASE 8)
# ---------------------------------------------------------------------------

class TestBreakEvenSeparation:
    GEO = EntryGeometry(Direction.BULL, 1.0, 0.99)

    def test_be_counted_first_and_families_diverge(self):
        # OBJ1 hit bar 2; bar 3 revisits entry (BE) WITHOUT hitting original
        # SL; bar 5 would hit OBJ2. R1 exits at BE; R0 rides to OBJ2.
        forward = [_bar(1, 1.005, 0.995),
                   _bar(2, 1.009, 0.998),            # OBJ1 1.008 hit (t=2)
                   _bar(3, 1.004, 0.9995),           # touches entry, not SL
                   _bar(4, 1.006, 1.001),
                   _bar(5, 1.021, 1.002)]            # OBJ2 1.02 hit
        first = Objective(FIRST.family, 1.008, 0.8, True, 2)
        second = Objective(SECOND.family, 1.02, 2.0, True, 5)
        kind, t = _be_runner(forward, self.GEO, first.t_bar, second)
        assert (kind, t) == ("BE", 3)
        pe = mk_pe(first=first, second=second, stop_bar=None,
                   be={"SECOND": (kind, t), "FURTHEST": None, "FIXED5": None})
        r0 = policy_outcome(pe, "C2_F50_R0")
        r1 = policy_outcome(pe, "C2_F50_R1")
        assert r0["status"] == "PARTIAL_PLUS_RUNNER_TARGET"
        assert r0["structural_r"] == pytest.approx(0.5 * 0.8 + 0.5 * 2.0)
        assert r1["status"] == "PARTIAL_PLUS_RUNNER_BREAKEVEN"
        assert r1["structural_r"] == pytest.approx(0.5 * 0.8)   # runner pays 0

    def test_same_bar_first_and_runner_target_pays_runner(self):
        forward = [_bar(1, 1.025, 0.998)]            # OBJ1+OBJ2 same bar
        second = Objective(SECOND.family, 1.02, 2.0, True, 1)
        kind, t = _be_runner(forward, self.GEO, 1, second)
        assert (kind, t) == ("TARGET", 1)

    def test_be_runner_open_when_nothing_hit(self):
        forward = [_bar(i, 1.012, 1.001) for i in range(1, 6)]
        second = Objective(SECOND.family, 1.02, 2.0, False, None)
        assert _be_runner(forward, self.GEO, 1, second) == ("OPEN", None)


# ---------------------------------------------------------------------------
# pathwise comparison (PHASE 10)
# ---------------------------------------------------------------------------

class TestPathwise:
    def test_paired_delta_same_entries_both_resolved(self):
        pes = []
        for i in range(3):
            fixed = {1: True, 2: i < 2, 3: False, 4: False, 5: False}
            pes.append(mk_pe(first=FIRST, stop_bar=None if i == 2 else 30,
                             rec_kw={"obs_feed_index": i,
                                     "fixed_reached": fixed}))
        out = {pe.entry_id: {pid: policy_outcome(pe, pid)
                             for pid in POLICY_IDS} for pe in pes}
        d = paired_delta(pes, out, "C1", "C0_2R")
        # entry 2: C0_2R FULL(+2) ... C1 FULL(+0.8): both resolved for i<2;
        # i==2: C0_2R unresolved (no stop, not reached)? fixed2 False &
        # stop None -> UNRESOLVED -> pair excluded
        assert d["pair_n"] == 2
        assert d["mean_delta_r"] == pytest.approx(0.8 - 2.0)

    def test_outcome_grid_covers_all_policies(self):
        pe = mk_pe(first=FIRST, second=SECOND)
        out = evaluate_all([pe])
        assert set(out[pe.entry_id]) == set(POLICY_IDS)


# ---------------------------------------------------------------------------
# frozen upstream + governance artifacts
# ---------------------------------------------------------------------------

class TestFrozenAndGovernance:
    def test_upstream_constants_unchanged(self):
        assert STOP_LOOKBACK_BARS == 12
        assert CONFIRMATION_WINDOW_BARS == 16
        assert OUTCOME_HORIZON_BARS == 96
        assert tuple(FIXED_R_TARGETS) == (1, 2, 3, 4, 5)

    def test_oos_partition_untouched(self):
        start, end = PARTITIONS["DEVELOPMENT"]
        assert start.isoformat().startswith("2017-01-01")
        assert end.isoformat().startswith("2017-09-01")

    def test_economics_fail_closed(self):
        auth = json.load(open(ART6 / "economic_authority.json"))
        assert auth["EXIT_CONTRACT_COMPLETE"] == "NO"
        assert auth["FRICTION_AUTHORITY_COMPLETE"] == "NO"
        assert auth["REALIZED_ECONOMICS_RUN"] == "NO"
        res = json.load(open(ART6 / "economic_results.json"))
        assert res["REALIZED_ECONOMICS_RUN"] == "NO"

    def test_final_guards_and_determinism(self):
        f = json.load(open(ART6 / "final_report.json"))
        g = f["guards"]
        assert not any([g["sl_changed"], g["entry_changed"],
                        g["trigger_changed"], g["location_changed"],
                        g["confirmation_changed"], g["oos_opened"],
                        g["holdout_touched"], g["v0_7_created"],
                        g["partial_percentage_optimized"],
                        g["policy_promoted"]])
        det = json.load(open(ART6 / "determinism_report.json"))
        assert det["byte_identical"] is True


# ---------------------------------------------------------------------------
# synthetic end-to-end: ordering, population identity, serialization
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def synth():
    m5 = make_synthetic_fx_bars(days=60, seed=11)
    m15, _ = aggregate_bars(m5, "M5", "M15")
    frames = {"M15": m15}
    for tf in ("H1", "H4", "D1"):
        frames[tf], _ = derive_fx_timeframe(m15, tf, "SYNTH")
    campaign = run_fx_symbol_campaign(frames, "SYNTH",
                                      m15[0].timestamp, m15[-1].timestamp)
    enriched = enrich_symbol(frames, campaign, m15[0].timestamp,
                             m15[-1].timestamp)
    records = tv5.build_entry_records(frames, campaign, enriched)
    return frames, records, build_policy_entries(frames, records)


class TestSynthEndToEnd:
    def test_causal_ordering_of_objectives(self, synth):
        _, _, pes = synth
        for pe in pes:
            if pe.second is not None and pe.second.reached:
                assert pe.first.reached
                assert pe.second.t_bar >= pe.first.t_bar
            if pe.furthest is not None and pe.furthest.reached \
                    and pe.first is not None:
                assert pe.first.reached

    def test_population_identity(self, synth):
        _, records, pes = synth
        assert len(pes) == len(records)
        assert [pe.base.obs_feed_index for pe in pes] == \
            [r.obs_feed_index for r in records]
        assert sum(pe.base.is_t1 for pe in pes) == sum(r.is_t1 for r in records)

    def test_stop_bar_consistent_with_frozen_reach(self, synth):
        _, _, pes = synth
        for pe in pes:
            for k in FIXED_R_TARGETS:
                t = pe.base.time_to_r[k]
                if t is not None and pe.stop_bar is not None:
                    assert t < pe.stop_bar      # credit only before the stop

    def test_outcomes_depend_only_on_window(self, synth):
        frames, records, pes = synth
        pe = pes[len(pes) // 2]
        rec = pe.base
        cutoff = rec.entry_index + 1 + OUTCOME_HORIZON_BARS
        mutated = {**frames, "M15": tuple(
            b if i < cutoff else
            MarketBar(timestamp=b.timestamp, open=b.open * 1.1,
                      high=b.high * 1.1, low=b.low * 1.1, close=b.close * 1.1)
            for i, b in enumerate(frames["M15"]))}
        pe2 = build_policy_entries(mutated, [rec])[0]
        for pid in POLICY_IDS:
            assert policy_outcome(pe, pid) == policy_outcome(pe2, pid)

    def test_deterministic_serialization_and_rerun(self, synth):
        frames, records, pes = synth
        out1 = evaluate_all(pes)
        out2 = evaluate_all(build_policy_entries(frames, records))
        assert json.dumps(entry_policy_rows(pes, out1), sort_keys=True,
                          default=str) == \
            json.dumps(entry_policy_rows(pes, out2), sort_keys=True,
                       default=str)
