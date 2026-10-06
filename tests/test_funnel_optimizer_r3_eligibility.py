"""Permanent R3 gate and null-control suite."""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.optimization.eligibility_r3 import (
    R3EligibilityPolicy, R3EligibilityVerdict, evaluate_parent_r3,
)
from ag_edgelab.optimization.reference_outcome_v2 import (
    ReferenceDirectionMode, ReferenceOutcomeV2Config, evaluate_reference_outcome_v2,
)

POLICY = R3EligibilityPolicy(n_bootstrap=600, rng_seed=730031)
ROOT = Path(__file__).parents[1]


def _noise_universe(n: int = 1000) -> list[float]:
    rng = random.Random(99117)
    return [rng.choice((-1.0, 0.5, 0.5)) for _ in range(n)]


def test_subsample_null_parent_is_not_eligible():
    outcomes = _noise_universe()
    chosen = set(random.Random(11).sample(range(len(outcomes)), 900))
    result = evaluate_parent_r3(outcomes, [i in chosen for i in range(len(outcomes))], policy=POLICY)
    assert result.verdict is R3EligibilityVerdict.FAIL
    assert result.baseline_universe_not_subset_of_parent is True
    assert result.n_baseline_universe >= result.n_parent


def test_random_rule_parent_false_pass_rate_is_compatible_with_significance():
    outcomes = _noise_universe()
    pass_count = 0
    replicates = 40
    for seed in range(replicates):
        rng = random.Random(f"null-parent:{seed}")
        selected = [rng.random() < .25 for _ in outcomes]
        policy = R3EligibilityPolicy(n_bootstrap=300, rng_seed=8000 + seed)
        pass_count += evaluate_parent_r3(outcomes, selected, policy=policy).verdict is R3EligibilityVerdict.PASS
    assert pass_count / replicates <= .10


def test_planted_signal_parent_passes():
    outcomes = _noise_universe()
    # The positive control intentionally plants selection information.  This is
    # a gate control, not a proposed strategy or an optimization campaign.
    selected = [value == 0.5 and index % 2 == 0 for index, value in enumerate(outcomes)]
    result = evaluate_parent_r3(outcomes, selected, policy=POLICY)
    assert result.verdict is R3EligibilityVerdict.PASS
    assert result.parent_percentile >= .95
    assert result.delta_bootstrap_ci95_low_r > 0


def test_low_reference_coverage_parent_blocks_exactly():
    outcomes: list[float | None] = [0.5] * 12 + [None] * 88
    result = evaluate_parent_r3(outcomes, [True] * 100, policy=POLICY)
    assert result.verdict is R3EligibilityVerdict.BLOCKED_INSUFFICIENT_REFERENCE_COVERAGE


def test_baseline_cannot_collapse_to_parent_selected_rows():
    outcomes = _noise_universe(200)
    selected = [i < 100 for i in range(200)]
    result = evaluate_parent_r3(outcomes, selected, policy=POLICY)
    assert result.n_baseline_universe == 200
    assert result.n_parent == 100
    assert result.baseline_universe_not_subset_of_parent


def test_reference_v2_is_causal_symmetric_and_strategy_independent():
    start = datetime(2017, 2, 1, tzinfo=timezone.utc)
    bars = []
    price = 1.0
    for i in range(100):
        close = price + (0.001 if i % 3 else -0.0005)
        bars.append(MarketBar(timestamp=start + timedelta(minutes=5 * i), open=price,
                              high=max(price, close) + .0003,
                              low=min(price, close) - .0003, close=close))
        price = close
    config = ReferenceOutcomeV2Config(direction_mode=ReferenceDirectionMode.BOTH_DIRECTIONS_SYMMETRIC)
    first = evaluate_reference_outcome_v2(bars, bars[20].timestamp, event_id="A", config=config)
    second = evaluate_reference_outcome_v2(bars, bars[20].timestamp, event_id="A", config=config)
    assert first == second
    assert first.outcome_r is None  # symmetric legs must not collapse before inference
    assert first.long_outcome_r is not None
    assert first.short_outcome_r is not None
    # Mutating future data beyond the frozen horizon cannot alter the result.
    extra = MarketBar(timestamp=bars[-1].timestamp + timedelta(minutes=5), open=9, high=10, low=8, close=9)
    assert evaluate_reference_outcome_v2(bars + [extra], bars[20].timestamp,
                                         event_id="A", config=config) == first


def test_direction_enum_supports_all_declared_modes_without_authorizing_trend():
    assert {mode.value for mode in ReferenceDirectionMode} == {
        "RANDOM_DIRECTION", "BOTH_DIRECTIONS_SYMMETRIC", "SIMPLE_TREND_DIRECTION"
    }
    assert ReferenceOutcomeV2Config().direction_authorized is False


def test_r3_acceptance_is_append_only_and_supersedes_only_eligibility_authority():
    r2 = json.loads((ROOT / "artifacts/funnel_optimizer_v1_real_fixture_r2/real_fixture_acceptance_evidence.json").read_text())
    r3 = json.loads((ROOT / "artifacts/funnel_optimizer_v1_r3_gate_repair/acceptance_evidence.json").read_text())
    assert r2["eligibility"]["verdict"] == "STRUCTURAL_ELIGIBILITY_PASS"
    assert r2["event_table"]["event_table_sha256"] == "61827905eb50d36b4e7da978639cfdf0e4584d1917bb706807da421cfcf12357"
    assert r3["historical_r2"]["event_hash"] == r2["event_table"]["event_table_sha256"]
    assert r3["historical_r2"]["eligibility_verdict"] == r2["eligibility"]["verdict"]
    assert r3["authority"]["r3_supersedes_r2_eligibility_authority"] is True
    assert r3["authority"]["real_campaign_authorized"] is False
    assert r3["authority"]["child_optimization_run"] is False


def test_r3_evidence_records_independent_universe_and_permanent_controls():
    r3 = json.loads((ROOT / "artifacts/funnel_optimizer_v1_r3_gate_repair/acceptance_evidence.json").read_text())
    gate = r3["r3_eligibility"]
    assert gate["n_baseline_universe"] >= gate["n_parent"]
    assert gate["baseline_universe_not_subset_of_parent"] is True
    assert r3["null_controls"]["SUBSAMPLE_NULL_PARENT"] == "FAIL"
    assert r3["null_controls"]["PLANTED_SIGNAL_PARENT"] == "PASS"
    assert r3["null_controls"]["LOW_REFERENCE_COVERAGE_PARENT"] == "BLOCKED_INSUFFICIENT_REFERENCE_COVERAGE"
