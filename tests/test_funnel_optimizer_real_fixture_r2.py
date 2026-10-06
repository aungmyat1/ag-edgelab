"""Real DEVELOPMENT fixture contracts for Funnel Optimizer V1 R2.

Raw FX archives are intentionally gitignored.  These integration tests skip in
a clean checkout without the registered materialization and run in the governed
fixture environment without opening OOS or holdout rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ag_edgelab.contracts.dataset import DatasetRole
from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import sha256_file
from ag_edgelab.data.fx_histdata_multiyear import NonDevelopmentAccessError
from ag_edgelab.optimization.funnel_optimizer import (RandomBaselineConfig, RuleState,
                                                       structural_parent_eligibility)
from ag_edgelab.strategies import asian_liquidity_displacement_v2 as V2
from ag_edgelab.strategies.asian_liquidity_displacement_v2_real_fixture import (
    REFERENCE_MODEL_ID, fixed_reference_2r_v1, load_development_frames,
    produce_real_fixture, production_summary)

ROOT = Path(__file__).parents[1]
PREREGISTRATION = ROOT / "config/governance/funnel_optimizer_v1_fixture_preregistration.json"
FROZEN_ALD_V2_SHA256 = "883e9095977cd25840201f5b2b3d5ce6e67b350c1157f30045654dbd13904920"


def _raw_fixture_present() -> bool:
    import json
    config = json.loads(PREREGISTRATION.read_text())
    return all((ROOT / item["path"]).is_file() for item in config["materialization"]["files"])


pytestmark = pytest.mark.skipif(not _raw_fixture_present(),
                                reason="registered raw Funnel Optimizer FX fixture is not materialized")


@pytest.fixture(scope="module")
def production():
    return produce_real_fixture(preregistration_path=PREREGISTRATION, root=ROOT)


def test_frozen_ald_v2_bytes_unchanged_for_real_fixture():
    assert sha256_file(ROOT / "src/ag_edgelab/strategies/asian_liquidity_displacement_v2.py") == FROZEN_ALD_V2_SHA256


def test_real_fact_producer_agrees_with_frozen_parent_on_every_shared_stage(production):
    # Re-run frozen parent logic over the already-built DEVELOPMENT frames;
    # compare independently produced parent units to relaxed fact cells.
    independent = {}
    for (symbol, year), bundle in production.frames.items():
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = datetime(year, 9, 1, tzinfo=timezone.utc)
        for parent in V2.replay_symbol(dict(bundle.frames), symbol, start, end):
            independent[f"{parent.candidate_id}|REAL_FIXTURE_R2"] = parent
    assert set(independent) == set(production.parent_units)
    for row in production.table.rows:
        parent = independent[row.event_id]
        for stage, cell in row.rule_cells.items():
            if stage in parent.stages:
                assert cell.state is (RuleState.PASS if parent.stages[stage] else RuleState.FAIL)
            else:
                assert cell.state is RuleState.NOT_EVALUABLE


def test_real_fixture_has_nonzero_tristate_and_reference_outcomes(production):
    summary = production_summary(production)
    assert summary["rows"] > 0
    assert summary["rule_cells"]["PASS"] > 0
    assert summary["rule_cells"]["FAIL"] > 0
    assert summary["rule_cells"]["NOT_EVALUABLE"] > 0
    assert summary["reference_outcome_rows"] > 0
    assert summary["not_evaluable_outcomes"] > 0


def test_reference_rows_carry_fixed_2r_provenance_not_actual_trade_outcomes(production):
    evaluable = [row for row in production.table.rows if row.reference_outcome_r is not None]
    assert evaluable
    for row in evaluable:
        assert row.reference_entry_price is not None
        assert row.reference_stop_price is not None
        assert row.reference_target_price is not None
        assert row.reference_exit_reason in {"TARGET_2R", "STOP", "TIMEOUT"}
        assert row.reference_target_price != row.reference_entry_price
    rejected = next(row for row in production.table.rows
                    if not row.actual_trade and row.reference_outcome_r is not None)
    assert rejected.actual_outcome_r is None


def test_fixed_reference_ambiguous_intrabar_fails_closed():
    t = datetime(2016, 1, 4, 7, tzinfo=timezone.utc)
    unit = V2.V2Unit(symbol="EURUSD", day="2016-01-04", session="ASIAN_LONDON", candidate_id="AMB")
    unit.stages["S7_ENTRY_AVAILABLE"] = True
    unit.direction, unit.entry, unit.stop = "BULL", 1.0000, 0.9990
    unit.confirm_time = t.isoformat()
    # The next M5 bar touches both the 2R target (1.0020) and stop; no
    # sub-M5 ordering authority is connected, so a favorable choice is banned.
    m5 = (MarketBar(timestamp=t + timedelta(minutes=5), open=1.0, high=1.0021,
                    low=0.9989, close=1.0),)
    first = fixed_reference_2r_v1(unit, m5)
    second = fixed_reference_2r_v1(unit, m5)
    assert first == second
    assert first.outcome_r is None
    assert first.exit_reason == "NOT_EVALUABLE"
    assert first.ambiguity_code == "AMBIGUOUS_INTRABAR"


def test_matched_1000_baselines_are_seed_deterministic_on_real_fixture(production):
    config = RandomBaselineConfig(count=1000, seed=981273645, authority_id="TEST_OWNER_POLICY_R2")
    first = structural_parent_eligibility(production.table, baseline=config)
    second = structural_parent_eligibility(production.table, baseline=config)
    assert len(first.matched_baseline_expectancies_r) == 1000
    assert first.matched_baseline_expectancies_r == second.matched_baseline_expectancies_r
    assert first.baseline_mean_expectancy_r == second.baseline_mean_expectancy_r


def test_oos_and_holdout_roles_refused_before_real_fixture_read():
    import json
    item = json.loads(PREREGISTRATION.read_text())["materialization"]["files"][0]
    kwargs = dict(zip_path=ROOT / item["path"], symbol=item["symbol"], year=item["year"],
                  expected_sha256=item["sha256"])
    with pytest.raises(NonDevelopmentAccessError):
        load_development_frames(**kwargs, role=DatasetRole.OOS)
    with pytest.raises(NonDevelopmentAccessError):
        load_development_frames(**kwargs, role=DatasetRole.SEALED_OOS)
