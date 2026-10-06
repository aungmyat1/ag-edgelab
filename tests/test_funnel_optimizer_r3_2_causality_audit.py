"""Permanent adversarial timing and directional-null guards for R3.2."""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.optimization.direction_causality_audit import (
    DirectionalNullMode, assert_causal_reference_entry, directional_null_draw,
    m15_direction_available_time,
)
from ag_edgelab.optimization.eligibility_r3_1 import DirectionalOpportunity
from ag_edgelab.optimization.reference_outcome_v2 import evaluate_reference_outcome_v2

UTC = timezone.utc
ROOT = Path(__file__).parents[1]
ARTIFACT = ROOT / "artifacts/funnel_optimizer_v1_r3_2_direction_causality_audit"


def _opportunity(index: int) -> DirectionalOpportunity:
    t = datetime(2016, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    return DirectionalOpportunity(f"O{index}", t, "EURUSD", 2016, "TEST",
                                  float(index % 3 - 1), float((index + 1) % 3 - 1))


def test_m15_direction_availability_cannot_precede_close():
    opened = datetime(2016, 4, 5, 7, 30, tzinfo=UTC)
    assert m15_direction_available_time(opened) == opened + timedelta(minutes=15)


def test_reference_entry_guard_rejects_pre_direction_entry():
    opened = datetime(2016, 4, 5, 7, 30, tzinfo=UTC)
    available = m15_direction_available_time(opened)
    with pytest.raises(ValueError, match="precedes direction"):
        assert_causal_reference_entry(available, opened)
    assert_causal_reference_entry(available, available)


def test_atr_uses_only_bars_closed_before_reference_entry():
    start = datetime(2016, 2, 1, tzinfo=UTC)
    bars = [MarketBar(timestamp=start + timedelta(minutes=5 * i), open=1 + i * .001,
                      high=1.002 + i * .001, low=.998 + i * .001,
                      close=1.001 + i * .001)
            for i in range(100)]
    entry = bars[20].timestamp
    original = evaluate_reference_outcome_v2(bars, entry, event_id="ATR")
    changed = list(bars)
    changed[20] = MarketBar(timestamp=entry, open=bars[20].open,
                            high=bars[20].high + 1, low=bars[20].low - 1,
                            close=bars[20].close)
    audited = evaluate_reference_outcome_v2(changed, entry, event_id="ATR")
    assert original.atr == audited.atr


def test_random_directional_null_samples_exactly_one_leg_per_cluster_draw():
    rows = [_opportunity(i) for i in range(30)]
    _, membership = directional_null_draw(
        rows, sample_n=20, long_count=10,
        mode=DirectionalNullMode.RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY,
        rng=random.Random(17),
    )
    assert len(membership) == 20
    assert all(direction in {"LONG", "SHORT"} for _, direction in membership)


def test_matched_direction_null_preserves_exact_direction_counts():
    rows = [_opportunity(i) for i in range(30)]
    _, membership = directional_null_draw(
        rows, sample_n=20, long_count=13,
        mode=DirectionalNullMode.MATCHED_DIRECTION_FREQUENCY_NULL,
        rng=random.Random(18),
    )
    assert sum(direction == "LONG" for _, direction in membership) == 13
    assert sum(direction == "SHORT" for _, direction in membership) == 7


def test_directional_null_has_nonzero_and_materially_larger_variance():
    evidence = json.loads((ARTIFACT / "acceptance_evidence.json").read_text())
    audit = evidence["null_audit"]
    assert audit["random_direction_one_leg"]["sd_r"] > 0
    assert audit["random_direction_one_leg"]["sd_r"] > audit["old_symmetric"]["sd_r"] * 1.10
    assert audit["r3_1_null_verdict"] == "INVALID_DIRECTIONAL_NULL"


def test_event_direction_and_canonical_entry_times_are_distinct():
    rows = [json.loads(line) for line in (ARTIFACT / "selected_parent_timing_ledger.jsonl").read_text().splitlines()]
    assert len(rows) == 294
    for row in rows:
        t0 = datetime.fromisoformat(row["EVENT_BAR_OPEN_TIME"])
        t1 = datetime.fromisoformat(row["DIRECTION_AVAILABLE_TIME"])
        t2 = datetime.fromisoformat(row["CANONICAL_PARENT_ENTRY_TIME"])
        assert t0 < t1 < t2


def test_causal_parent_mask_excludes_outcome_stage():
    evidence = json.loads((ARTIFACT / "acceptance_evidence.json").read_text())
    selection = evidence["selection_time_audit"]
    assert selection["r3_1_parent_selection_expression"] == "row.all_rules_pass"
    assert selection["stage_classification"]["S9_TRADE_COMPLETED"] == "OUTCOME_INFORMATION"
    assert selection["r3_2_causal_parent_mask"] == "S8_GEOMETRY_VALID_PASS; S9 excluded"
    assert selection["parent_selection_causal_at_entry"] is False


def test_placebos_do_not_inherit_parent_pass():
    evidence = json.loads((ARTIFACT / "acceptance_evidence.json").read_text())
    placebos = evidence["placebos"]
    assert placebos["shift_one_opportunity"]["verdict"] == "FAIL"
    assert placebos["direction_permutation"]["verdict"] == "FAIL"
    assert placebos["selection_randomization"]["pass_count"] <= 2


def test_r3_2_lineage_is_append_only_and_revokes_r3_1_causal_authority():
    evidence = json.loads((ARTIFACT / "acceptance_evidence.json").read_text())
    assert evidence["lineage"]["audited_head"] == "5e76dc6bbcedc5d9e7e1ec900390274fe752efb8"
    assert evidence["lineage"]["supersedes"] == "R3.1 causal eligibility authority only; R3.1 remains historical"
    assert evidence["classification"]["adversarial_classification"] == "R3_1_PASS_EXPLAINED_BY_MULTIPLE_ARTIFACTS"
    assert evidence["classification"]["r3_gate_trustworthy"] is False
    assert evidence["governance"]["edge_verified_issued"] is False
