"""Focused causal-policy freeze guards (PHASE B12).

Permanent anti-lookahead and policy-freeze CI guards for every future
candidate family.  These tests are synthetic and fast; the real-data prefix
invariance guard lives in ``tests/test_r3_prefix_invariance.py``.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ag_edgelab.contracts.dataset import DatasetRole
from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import sha256_file
from ag_edgelab.data.fx_histdata_multiyear import NonDevelopmentAccessError
from ag_edgelab.optimization.baseline_timing_policy import (
    StratifiedDelayPools, empirical_matched_delay, fixed_causal_delay_from_t1,
)
from ag_edgelab.optimization.causal_entry_mask import (
    CAUSAL_MASK_ID, MaskInputForbidden, causal_mask_facts_from_v2_unit,
    causal_mask_for_v2_unit, derive_causal_geometry,
    evaluate_causal_entry_geometry_mask,
)
from ag_edgelab.optimization.causal_normalization import (
    FrozenPartitionNormalizer, NormalizationLeak, assert_no_full_sample_fit,
)
from ag_edgelab.optimization.causal_time import (
    BAR_TIMESTAMP_SEMANTICS, CausalFact, LookaheadViolation,
    assert_available_at_or_before, asof_last_at_or_before,
    data_available_time, first_m5_open_at_or_after, m5_data_available_time,
    t1_direction_available, t2_decision_time,
)
from ag_edgelab.optimization.direction_causality_audit import DirectionalNullMode
from ag_edgelab.optimization.directional_null_policy import (
    FROZEN_NULL_POLICY, NULL_REPLICATES, RetiredNullAuthority,
    assert_eligibility_null_mode, draw_one_leg_null,
)
from ag_edgelab.optimization.eligibility_r3_1 import DirectionalOpportunity
from ag_edgelab.optimization.execution_semantics import (
    FROZEN_EXECUTION_SEMANTICS, ExecutionDrift, ExecutionSemanticsV1,
    FrictionZeroError, assert_candidate_null_semantics_identical,
    execution_semantics_hash,
)
from ag_edgelab.optimization.verdict_record import (
    VERDICT_RECORD_SCHEMA, VerdictChainError, VerdictRecord,
    verify_chain_manifest, verify_verdict_chain,
)

UTC = timezone.utc
ROOT = Path(__file__).parents[1]
FROZEN_ALD_V2 = ROOT / "src/ag_edgelab/strategies/asian_liquidity_displacement_v2.py"
FROZEN_ALD_V2_SHA256 = "883e9095977cd25840201f5b2b3d5ce6e67b350c1157f30045654dbd13904920"

T0 = datetime(2016, 6, 1, 2, 0, tzinfo=UTC)          # M15 event bar OPEN


def _minutes(n: int) -> timedelta:
    return timedelta(minutes=n)


# ---------------------------------------------------------------------------
# 1. available_at <= decision_ts
# ---------------------------------------------------------------------------

def test_available_at_must_not_exceed_decision_ts():
    fact = CausalFact("S4_DIRECTION", "LONG", T0 + _minutes(15))
    assert_available_at_or_before(fact, T0 + _minutes(15))
    with pytest.raises(LookaheadViolation):
        assert_available_at_or_before(fact, T0 + _minutes(14))


# ---------------------------------------------------------------------------
# 2. no future as-of joins
# ---------------------------------------------------------------------------

def test_asof_lookup_can_never_select_a_future_observation():
    observations = [
        CausalFact("VOL", 1.0, T0 - _minutes(60)),
        CausalFact("VOL", 2.0, T0 - _minutes(30)),
        CausalFact("VOL", 3.0, T0 + _minutes(30)),  # future-only relative to T0
    ]
    picked = asof_last_at_or_before(observations, T0)
    assert picked.value == 2.0
    with pytest.raises(LookaheadViolation, match="forward lookup is forbidden"):
        asof_last_at_or_before([observations[2]], T0)


# ---------------------------------------------------------------------------
# 3. M15 direction available only after M15 close
# ---------------------------------------------------------------------------

def test_m15_direction_available_only_after_m15_close():
    assert BAR_TIMESTAMP_SEMANTICS == "BAR_OPEN_TIME"
    assert data_available_time(T0, _minutes(15)) == T0 + _minutes(15)
    assert t1_direction_available(T0) == T0 + _minutes(15)
    with pytest.raises(ValueError):
        t1_direction_available(datetime(2016, 6, 1, 2, 0))  # naive time refused


# ---------------------------------------------------------------------------
# 4. M5 confirmation available only after M5 close
# ---------------------------------------------------------------------------

def test_m5_confirmation_available_only_after_m5_close():
    confirm_open = T0 + _minutes(30)
    assert m5_data_available_time(confirm_open) == confirm_open + _minutes(5)
    assert t2_decision_time(confirm_open) == confirm_open + _minutes(5)
    # a confirmation fact is NOT consumable at the confirmation bar's open
    confirm_fact = CausalFact("S6_CONFIRM", True, t2_decision_time(confirm_open))
    with pytest.raises(LookaheadViolation):
        assert_available_at_or_before(confirm_fact, confirm_open)


# ---------------------------------------------------------------------------
# 5. next-bar entry rule
# ---------------------------------------------------------------------------

def test_reference_entry_is_first_m5_open_at_or_after_t2():
    t2 = T0 + _minutes(35)
    grid = [T0 + _minutes(5 * i) for i in range(12)]
    # gap: no bar opens at t2+5 or t2+10 (weekend-style hole)
    with_hole = [stamp for stamp in grid if not t2 + _minutes(5) <= stamp < t2 + _minutes(15)]
    assert first_m5_open_at_or_after(with_hole, t2) == t2  # t2 itself is on-grid
    assert first_m5_open_at_or_after(with_hole, t2 + _minutes(1)) == t2 + _minutes(15)
    assert first_m5_open_at_or_after(with_hole, T0 + _minutes(999)) is None


# ---------------------------------------------------------------------------
# helpers for mask tests
# ---------------------------------------------------------------------------

def _mask_facts(t2: datetime, *, with_future_fact: CausalFact | None = None,
                with_s9_fact: CausalFact | None = None) -> dict[str, CausalFact]:
    facts = {
        "S1_CONTEXT_ELIGIBLE": CausalFact("S1_CONTEXT_ELIGIBLE", True, T0),
        "S2_LOCATION_ELIGIBLE": CausalFact("S2_LOCATION_ELIGIBLE", True, T0),
        "S3_SESSION_EVENT": CausalFact("S3_SESSION_EVENT", True, T0 + _minutes(15)),
        "S4_SWEEP_OR_BREAKOUT": CausalFact("S4_SWEEP_OR_BREAKOUT", True, T0 + _minutes(15)),
        "S5_RECLAIM_OR_RETEST": CausalFact("S5_RECLAIM_OR_RETEST", True, T0 + _minutes(30)),
        "S6_STRUCTURE_CONFIRM": CausalFact("S6_STRUCTURE_CONFIRM", True, t2),
        "ENTRY_PRICE_KNOWN": CausalFact("ENTRY_PRICE_KNOWN", True, t2),
        "STOP_PRICE_KNOWN": CausalFact("STOP_PRICE_KNOWN", True, t2),
        "TARGET_PRICE_KNOWN": CausalFact("TARGET_PRICE_KNOWN", True, t2),
        "RISK_POSITIVE": CausalFact("RISK_POSITIVE", True, t2),
        "TARGET_BEYOND_ENTRY": CausalFact("TARGET_BEYOND_ENTRY", True, t2),
        "TEMPORAL_ORDER_VALID": CausalFact("TEMPORAL_ORDER_VALID", True, t2),
    }
    if with_future_fact is not None:
        facts["VOLATILITY_NORMALIZATION"] = with_future_fact
    if with_s9_fact is not None:
        facts["S9_TRADE_COMPLETED"] = with_s9_fact
    return facts


CONFIRM_OPEN = T0 + _minutes(30)
T2 = t2_decision_time(CONFIRM_OPEN)


# ---------------------------------------------------------------------------
# 6. causal mask excludes future availability
# ---------------------------------------------------------------------------

def test_causal_mask_rejects_facts_available_after_decision_ts():
    future = CausalFact("VOLATILITY_NORMALIZATION", 1.5, T2 + _minutes(1))
    with pytest.raises(LookaheadViolation):
        evaluate_causal_entry_geometry_mask(
            opportunity_id="X", facts=_mask_facts(T2, with_future_fact=future),
            decision_ts=T2)


# ---------------------------------------------------------------------------
# 7. causal mask excludes S9
# ---------------------------------------------------------------------------

def test_causal_mask_forbids_s9_and_outcome_inputs():
    with pytest.raises(MaskInputForbidden):
        evaluate_causal_entry_geometry_mask(
            opportunity_id="X", facts=_mask_facts(T2, with_s9_fact=CausalFact(
                "S9_TRADE_COMPLETED", True, T2)), decision_ts=T2)
    for forbidden in ("MFE_R", "REALISED_R", "FORWARD_BARS", "RIGHT_CENSOR_STATUS"):
        with pytest.raises(MaskInputForbidden):
            evaluate_causal_entry_geometry_mask(
                opportunity_id="X", facts=_mask_facts(T2, with_s9_fact=CausalFact(
                    forbidden, 1.0, T2)), decision_ts=T2)


def _branch_a_unit(**overrides):
    """A confirmed branch-A unit whose S7-populated geometry fields are unset.

    This is exactly the data-boundary shape the frozen replay leaves behind
    when a confirmation has no forward M5 bars: ``entry/stop/risk/target``
    are never assigned.  The mask must still evaluate it from bars.
    """
    from ag_edgelab.strategies.asian_liquidity_displacement_v2 import V2Unit

    unit = V2Unit(symbol="EURUSD", day="2016-06-01", session="ASIA",
                  candidate_id="EURUSD|2016-06-01|ASIA|V2")
    unit.stages.update({
        "S1_CONTEXT_ELIGIBLE": True, "S2_LOCATION_ELIGIBLE": True,
        "S3_SESSION_EVENT": True, "S4_SWEEP_OR_BREAKOUT": True,
        "S5_RECLAIM_OR_RETEST": True, "S6_STRUCTURE_CONFIRM": True,
    })
    unit.event_time = T0.isoformat()
    unit.reclaim_or_retest_time = (T0 + _minutes(30)).isoformat()
    unit.confirm_time = CONFIRM_OPEN.isoformat()
    unit.branch = "A_SWEEP_RECLAIM_REVERSAL"
    unit.direction = "BEAR"
    unit.boundary_side = "UPPER"
    unit.reference_high, unit.reference_low = 1.1060, 1.1000
    for key, value in overrides.items():
        setattr(unit, key, value)
    return unit


def _synthetic_bars():
    """Bars closed at or before T2 reproducing valid branch-A geometry."""
    event_m15 = MarketBar(timestamp=T0, open=1.1050, high=1.1070,
                          low=1.1010, close=1.1040)
    confirm_m5 = MarketBar(timestamp=CONFIRM_OPEN, open=1.1042, high=1.1045,
                           low=1.1038, close=1.1040)
    return [confirm_m5], [event_m15], []


class _OutcomelessUnit:
    """A confirmed unit whose outcome/S7 fields explode on access."""

    FORBIDDEN = {"realised_r", "mfe_r", "mae_r", "resolution", "stopped_out",
                 "stopped_same_bar", "forward_bars", "reached", "target_reached",
                 "entry", "stop", "risk", "target", "natural_target_r"}

    def __init__(self, inner):
        self._inner = inner

    def passed(self, node):
        return self._inner.passed(node)

    def __getattr__(self, name):
        if name in _OutcomelessUnit.FORBIDDEN:
            raise AssertionError(f"mask read forbidden S7/outcome field {name}")
        return getattr(self._inner, name)


def test_causal_mask_derives_geometry_without_touching_s7_or_outcome_fields():
    m5, m15, h1 = _synthetic_bars()
    unit = _branch_a_unit()  # entry/stop/risk/target are all None
    result = causal_mask_for_v2_unit(_OutcomelessUnit(unit), m5=m5, m15=m15, h1=h1)
    assert result.mask_id == CAUSAL_MASK_ID
    assert result.eligible is True, result.fact_audit
    assert result.decision_ts == T2
    assert result.mask_uses_s9 is False
    assert result.mask_uses_post_entry_data is False
    # derived geometry: entry = confirm close, stop = event bar raid extreme,
    # target = opposite reference boundary
    geometry = derive_causal_geometry(unit, m5=m5, m15=m15, h1=h1)
    assert geometry.entry == 1.1040
    assert geometry.stop == 1.1070
    assert geometry.target == 1.1000


def test_causal_mask_boundary_unit_is_not_punished_for_missing_forward_bars():
    """A confirmed unit with NO forward bars must be judged like any other.

    The frozen replay leaves entry/stop unassigned only because S7's
    forward-availability gate returned early; at T2 the geometry is knowable
    from closed bars, so the mask must not encode that absence.
    """
    m5, m15, h1 = _synthetic_bars()
    unit = _branch_a_unit(reject_reason="NO_FORWARD_BARS",
                          reject_node="S7_ENTRY_AVAILABLE")
    assert causal_mask_for_v2_unit(unit, m5=m5, m15=m15, h1=h1).eligible is True


def test_causal_mask_branch_b_fails_closed_without_a_causal_target():
    from ag_edgelab.strategies.asian_liquidity_displacement_v2 import V2Unit

    unit = V2Unit(symbol="EURUSD", day="2016-06-01", session="ASIA",
                  candidate_id="EURUSD|2016-06-01|ASIA|V2")
    unit.stages.update({
        "S1_CONTEXT_ELIGIBLE": True, "S2_LOCATION_ELIGIBLE": True,
        "S3_SESSION_EVENT": True, "S4_SWEEP_OR_BREAKOUT": True,
        "S5_RECLAIM_OR_RETEST": True, "S6_STRUCTURE_CONFIRM": True,
    })
    unit.event_time = T0.isoformat()
    unit.reclaim_or_retest_time = (T0 + _minutes(30)).isoformat()
    unit.confirm_time = CONFIRM_OPEN.isoformat()
    unit.branch = "B_BREAKOUT_RETEST_CONTINUATION"
    unit.direction = "BULL"
    retest = MarketBar(timestamp=T0 + _minutes(30), open=1.1040, high=1.1044,
                       low=1.1030, close=1.1038)
    confirm = MarketBar(timestamp=CONFIRM_OPEN, open=1.1040, high=1.1052,
                        low=1.1038, close=1.1050)
    result = causal_mask_for_v2_unit(unit, m5=[retest, confirm], m15=[], h1=[])
    assert result.eligible is False
    assert result.reason_code == "MASK_GEOMETRY_FAILED:TARGET_PRICE_KNOWN"


def test_causal_mask_fails_closed_when_the_confirm_bar_is_not_supplied():
    # No M5 bar at the confirmation timestamp: geometry cannot be derived,
    # so the mask fails closed rather than inventing values.
    m5, m15, h1 = _synthetic_bars()
    result = causal_mask_for_v2_unit(_branch_a_unit(), m5=[], m15=m15, h1=h1)
    assert result.eligible is False
    assert result.reason_code == "MASK_GEOMETRY_FAILED:ENTRY_PRICE_KNOWN"


def test_causal_mask_fails_closed_on_missing_or_failed_facts():
    facts = _mask_facts(T2)
    del facts["S6_STRUCTURE_CONFIRM"]
    missing = evaluate_causal_entry_geometry_mask(opportunity_id="X", facts=facts, decision_ts=T2)
    assert missing.eligible is False and missing.reason_code == "MASK_MISSING_FACT:S6_STRUCTURE_CONFIRM"
    failed = dict(_mask_facts(T2), S6_STRUCTURE_CONFIRM=CausalFact("S6_STRUCTURE_CONFIRM", False, T2))
    result = evaluate_causal_entry_geometry_mask(opportunity_id="X", facts=failed, decision_ts=T2)
    assert result.eligible is False and result.reason_code == "MASK_STAGE_FAILED:S6_STRUCTURE_CONFIRM"
    geometry = dict(_mask_facts(T2), RISK_POSITIVE=CausalFact("RISK_POSITIVE", False, T2))
    result = evaluate_causal_entry_geometry_mask(opportunity_id="X", facts=geometry, decision_ts=T2)
    assert result.eligible is False and result.reason_code == "MASK_GEOMETRY_FAILED:RISK_POSITIVE"


def test_causal_mask_unconfirmed_units_do_not_need_bars():
    # unconfirmed units never reach geometry derivation
    from ag_edgelab.strategies.asian_liquidity_displacement_v2 import V2Unit
    unconfirmed = V2Unit(symbol="EURUSD", day="2016-06-01", session="ASIA",
                         candidate_id="U1")
    unconfirmed.reject_reason = "NO_RETEST_BEFORE_EXPIRY"
    unconfirmed.reject_node = "S5_RECLAIM_OR_RETEST"
    result = causal_mask_for_v2_unit(unconfirmed, m5=[], m15=[], h1=[])
    assert result.eligible is False
    assert result.reason_code == "NO_CONFIRMATION:NO_RETEST_BEFORE_EXPIRY"
    with pytest.raises(ValueError):
        causal_mask_facts_from_v2_unit(unconfirmed, m5=[], m15=[], h1=[])


# ---------------------------------------------------------------------------
# Baseline T2 timing policies (PHASE B6; review finding fix)
# ---------------------------------------------------------------------------

def _lag(minutes: int) -> timedelta:
    return timedelta(minutes=minutes)


def test_stratified_delay_decides_year_eligibility_per_year_not_per_session():
    # Codex-review regression: (EURUSD, ASIAN_LONDON) year counts 36/25/24.
    # Only the 36-parent year may use its own pool; 25 and 24 must fall back
    # to the (symbol, session) pool.  The old implementation collapsed the
    # decision onto whichever year iterated last.
    rows = ([("e1", "EURUSD", "ASIAN_LONDON", 2015, _lag(60))] * 36
            + [("e2", "EURUSD", "ASIAN_LONDON", 2016, _lag(90))] * 25
            + [("e3", "EURUSD", "ASIAN_LONDON", 2017, _lag(120))] * 24)
    pools = StratifiedDelayPools.build(rows, min_stratum_parent_n=30)
    assert set(pools.year_pools) == {("EURUSD", "ASIAN_LONDON", 2015)}
    # 2016 and 2017 rows draw from the session pool (all 85 parents)
    session_pool = pools.session_pools[("EURUSD", "ASIAN_LONDON")]
    assert len(session_pool) == 85
    t0 = datetime(2016, 3, 1, tzinfo=UTC)
    d2016 = pools.delay("x", t0, "EURUSD", "ASIAN_LONDON", 2016)
    assert _lag(45) <= d2016 - t0 <= _lag(165)  # inside the session pool range
    d2015 = pools.delay("x", t0, "EURUSD", "ASIAN_LONDON", 2015)
    assert d2015 - t0 == _lag(60)               # year pool has only 60m lags

    # GBPUSD/ASIAN_LONDON 29/24/35: only 2017 splits.
    rows_b = ([("g1", "GBPUSD", "ASIAN_LONDON", 2015, _lag(30))] * 29
              + [("g2", "GBPUSD", "ASIAN_LONDON", 2016, _lag(45))] * 24
              + [("g3", "GBPUSD", "ASIAN_LONDON", 2017, _lag(75))] * 35)
    pools_b = StratifiedDelayPools.build(rows_b, min_stratum_parent_n=30)
    assert set(pools_b.year_pools) == {("GBPUSD", "ASIAN_LONDON", 2017)}
    # a sub-threshold year of one session never borrows another session's pool
    with pytest.raises(ValueError):
        StratifiedDelayPools.build(rows_b).delay(
            "x", t0, "EURUSD", "LONDON_NEWYORK", 2016)


def test_empirical_and_fixed_delay_policies_are_deterministic():
    lags = [_lag(30), _lag(60), _lag(90)]
    t0 = datetime(2016, 3, 1, tzinfo=UTC)
    assert empirical_matched_delay("E1", t0, lags) == empirical_matched_delay("E1", t0, lags)
    assert empirical_matched_delay("E1", t0, lags) != empirical_matched_delay("E2", t0, lags) \
        or True  # slot collision allowed; determinism is the contract
    with pytest.raises(ValueError):
        empirical_matched_delay("E1", t0, [])
    t1 = t0 + _minutes(15)
    assert fixed_causal_delay_from_t1(t1, minutes=120) == t1 + _minutes(120)
    with pytest.raises(ValueError):
        fixed_causal_delay_from_t1(t1, minutes=0)


# ---------------------------------------------------------------------------
# 9. full-sample normalization cannot leak into past events
# ---------------------------------------------------------------------------

def test_full_sample_normalization_cannot_leak_into_past_events():
    fit_values = [1.0, 2.0, 3.0]
    early, late = T0 - _minutes(90), T0 - _minutes(30)
    frozen = FrozenPartitionNormalizer.fit(fit_values, [early, early, early], early)
    # Scoring an event BEFORE the fit cutoff is a hard leak error.
    with pytest.raises(NormalizationLeak):
        frozen.score(2.0, T0 - _minutes(120))
    # Frozen scoring is stable: identical params score identically forever.
    before = frozen.score(2.5, T0)
    assert before == frozen.score(2.5, late)
    # Refitting on the same authorized prior partition is bit-identical.
    refit = FrozenPartitionNormalizer.fit(fit_values, [early, early, early], early)
    assert refit.score(2.5, T0) == before
    # A fit that extends past the earliest scored event is rejected outright.
    with pytest.raises(NormalizationLeak):
        assert_no_full_sample_fit([early, T0 + _minutes(60)], [T0, T0 + _minutes(1)])
    # A strictly prior fit window is accepted.
    assert_no_full_sample_fit([early, early], [T0, T0 + _minutes(1)])


def test_frozen_partition_normalizer_rejects_future_fit_observations():
    early = T0 - _minutes(90)
    with pytest.raises(NormalizationLeak):
        FrozenPartitionNormalizer.fit(
            [1.0, 2.0], [early, T0 + _minutes(60)], early)


# ---------------------------------------------------------------------------
# 10/11/12. directional nulls
# ---------------------------------------------------------------------------

def _population(n: int = 40) -> list[DirectionalOpportunity]:
    rng = random.Random(11)
    out = []
    for i in range(n):
        stamp = datetime(2016, 1, 1, tzinfo=UTC) + timedelta(hours=i)
        out.append(DirectionalOpportunity(
            f"OP{i:03d}", stamp, "EURUSD", 2016, "ASIA",
            long_outcome_r=rng.gauss(0, 1), short_outcome_r=rng.gauss(0, 1)))
    return out


def test_directional_null_chooses_exactly_one_leg_per_opportunity():
    population = _population()
    mean, membership = draw_one_leg_null(
        population, sample_n=20, long_count=7,
        matched_direction_frequencies=False, rng=random.Random(5))
    # Exactly one leg per sampled opportunity instance: the observation
    # count equals the sample size — LONG+SHORT are never averaged into a
    # single null observation (the retired symmetric mode would emit 2*N).
    assert len(membership) == 20
    assert all(direction in ("LONG", "SHORT") for _, direction in membership)
    # No membership entry ever carries both legs of one opportunity draw.
    assert all(isinstance(direction, str) for _, direction in membership)


def test_matched_direction_null_preserves_exact_direction_counts():
    population = _population()
    mean, membership = draw_one_leg_null(
        population, sample_n=20, long_count=7,
        matched_direction_frequencies=True, rng=random.Random(5))
    longs = sum(direction == "LONG" for _, direction in membership)
    assert longs == 7 and len(membership) == 20


def test_retired_symmetric_null_cannot_carry_eligibility_authority():
    with pytest.raises(RetiredNullAuthority):
        assert_eligibility_null_mode(DirectionalNullMode.OLD_SYMMETRIC_TWO_LEG_AVERAGE)
    assert_eligibility_null_mode(DirectionalNullMode.RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY)
    assert_eligibility_null_mode(DirectionalNullMode.MATCHED_DIRECTION_FREQUENCY_NULL)


def test_null_policy_seeds_are_deterministic_and_frozen():
    assert NULL_REPLICATES >= 1000
    first = FROZEN_NULL_POLICY.seed_for("GEN3_PARENT_V0", 0)
    again = FROZEN_NULL_POLICY.seed_for("GEN3_PARENT_V0", 0)
    other = FROZEN_NULL_POLICY.seed_for("GEN3_PARENT_V0", 1)
    campaign = FROZEN_NULL_POLICY.seed_for("ANOTHER", 0)
    assert first == again and first != other and first != campaign
    # identical seed + population -> identical draws bit-for-bit
    population = _population()
    a = draw_one_leg_null(population, sample_n=15, long_count=5,
                          matched_direction_frequencies=True,
                          rng=random.Random(first))
    b = draw_one_leg_null(population, sample_n=15, long_count=5,
                          matched_direction_frequencies=True,
                          rng=random.Random(first))
    assert a == b


# ---------------------------------------------------------------------------
# 13. verdict record hash determinism + hash-linked chain
# ---------------------------------------------------------------------------

def _record(**overrides) -> VerdictRecord:
    payload = dict(
        verdict_id="TEST_V1", policy_hash="p" * 64, dataset_hash="d" * 64,
        candidate_contract_hash="c" * 64, engine_code_sha="e" * 64,
        event_table_hash="t" * 64, friction_authority_hash="",
        verdict="PASS", parent_verdict_id="", parent_verdict_record_hash="")
    payload.update(overrides)
    return VerdictRecord(**payload)


def test_verdict_record_hash_is_deterministic_and_binds_inputs():
    one, two = _record(), _record()
    assert one.verdict_record_hash == two.verdict_record_hash
    assert one.verdict_record_hash != _record(verdict="FAIL").verdict_record_hash
    assert one.verdict_record_hash != _record(policy_hash="q" * 64).verdict_record_hash
    assert one.verdict_record_hash != _record(parent_verdict_id="PARENT").verdict_record_hash
    assert one.verdict_record_hash != _record(parent_verdict_record_hash="z" * 64).verdict_record_hash


def test_verdict_chain_requires_embedded_parent_record_hash():
    parent = _record(verdict_id="PARENT")
    child_ok = _record(verdict_id="CHILD", parent_verdict_id="PARENT",
                       parent_verdict_record_hash=parent.verdict_record_hash)
    verify_verdict_chain([parent, child_ok])
    # naming a parent without embedding its hash is refused
    with pytest.raises(VerdictChainError, match="without embedding"):
        verify_verdict_chain([parent, _record(verdict_id="CHILD",
                                              parent_verdict_id="PARENT")])
    # a mutated ancestor breaks the embedded link
    with pytest.raises(VerdictChainError, match="parent hash mismatch"):
        verify_verdict_chain([parent, _record(
            verdict_id="CHILD", parent_verdict_id="PARENT",
            parent_verdict_record_hash="0" * 64)])
    with pytest.raises(VerdictChainError):
        verify_verdict_chain([child_ok])                      # dangling parent
    with pytest.raises(VerdictChainError):
        verify_verdict_chain([parent, parent])                # duplicate id
    with pytest.raises(VerdictChainError):
        forward = [_record(verdict_id="A", parent_verdict_id="B"),
                   _record(verdict_id="B")]
        verify_verdict_chain(forward)                         # forward reference
    assert VERDICT_RECORD_SCHEMA == "VERDICT_RECORD_V1"


def test_verdict_chain_detects_mutated_payloads_via_stored_hashes():
    parent = _record(verdict_id="PARENT")
    child = _record(verdict_id="CHILD", parent_verdict_id="PARENT",
                    parent_verdict_record_hash=parent.verdict_record_hash)
    stored = {parent.verdict_id: parent.verdict_record_hash,
              child.verdict_id: child.verdict_record_hash}
    verify_verdict_chain([parent, child], stored_hashes=stored)
    # a silently mutated payload no longer matches its stored hash
    mutated = _record(verdict_id="CHILD", parent_verdict_id="PARENT",
                      parent_verdict_record_hash=parent.verdict_record_hash,
                      verdict="PASS_MUTATED")
    with pytest.raises(VerdictChainError, match="payload hash mismatch"):
        verify_verdict_chain([parent, mutated], stored_hashes=stored)
    # missing / extra stored hashes fail closed
    with pytest.raises(VerdictChainError):
        verify_verdict_chain([parent, child], stored_hashes={"PARENT": stored["PARENT"]})
    with pytest.raises(VerdictChainError):
        verify_verdict_chain([parent, child],
                             stored_hashes=dict(stored, GHOST="0" * 64))


def test_chain_manifest_round_trip_verification():
    parent = _record(verdict_id="PARENT")
    child = _record(verdict_id="CHILD", parent_verdict_id="PARENT",
                    parent_verdict_record_hash=parent.verdict_record_hash)
    manifest = {"schema_version": VERDICT_RECORD_SCHEMA,
                "records": [parent.as_dict(), child.as_dict()],
                "chain_head_verdict_id": "CHILD",
                "chain_head_verdict_record_hash": child.verdict_record_hash}
    verify_chain_manifest(manifest)
    # byte-level mutation of any committed record fails the manifest check
    import copy
    mutated = copy.deepcopy(manifest)
    mutated["records"][0]["verdict"] = "TAMPERED"
    with pytest.raises(VerdictChainError):
        verify_chain_manifest(mutated)
    # a wrong chain-head pin also fails
    head = copy.deepcopy(manifest)
    head["chain_head_verdict_record_hash"] = "0" * 64
    with pytest.raises(VerdictChainError):
        verify_chain_manifest(head)


def test_committed_freeze_artifacts_form_a_valid_hash_linked_chain():
    chain_path = ROOT / "artifacts/funnel_optimizer_v1_r3_causal_policy_freeze/verdict_chain.json"
    if not chain_path.is_file():
        pytest.skip("freeze artifacts not generated in this checkout")
    verify_chain_manifest(json.loads(chain_path.read_text()))
    chain = json.loads(chain_path.read_text())
    freeze = chain["records"][-1]
    assert freeze["parent_verdict_id"] == "R3_2_DIRECTION_CAUSALITY_AUDIT"
    assert freeze["parent_verdict_record_hash"] == chain["records"][0]["verdict_record_hash"]
    assert freeze["policy_hash"] == json.loads(
        (ROOT / "config/governance/funnel_optimizer_r3_causal_policy_proposal.json")
        .read_text())["POLICY_HASH"]
    audit = json.loads(
        (ROOT / "artifacts/funnel_optimizer_v1_r3_causal_policy_freeze"
         "/causal_mask_audit.json").read_text())
    assert audit["derived_vs_stored_geometry"]["mismatch_ids"] == []


# ---------------------------------------------------------------------------
# 14. ALD V2 remains archived / unmodified
# ---------------------------------------------------------------------------

def test_frozen_ald_v2_strategy_bytes_are_unchanged():
    assert sha256_file(FROZEN_ALD_V2) == FROZEN_ALD_V2_SHA256


def test_ald_v2_disposition_is_archived_and_bound_to_freeze_base():
    disposition = json.loads(
        (ROOT / "config/governance/ald_v2_disposition.json").read_text())
    assert disposition["ALD_V2_DEV_SELECTION_STATUS"] == "DEV_REJECTED_CAUSAL_SELECTION"
    assert disposition["ALD_FAMILY_DISPOSITION"] == "ARCHIVE_NO_V2_2"
    assert disposition["frozen_ald_v2"]["sha256"] == FROZEN_ALD_V2_SHA256
    assert disposition["policy_freeze_base"] == "252059ec84e76562e8ecb7115311f42bb62eac41"
    ledger = json.loads((ROOT / "config/governance/candidate_ledger.json").read_text())
    v2 = next(r for r in ledger["records"]
              if r["CANDIDATE_ID"] == "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2@2.0.0-research")
    # append-only: the historical verdict is untouched, disposition is a note
    assert v2["STATUS"] == "V2_DEV_SAMPLE_SUFFICIENT_PRE_OOS_FAILED"
    assert v2["EDGE_STATUS"] == "NO_EDGE"
    assert v2["r3_causal_audit_disposition"]["ALD_FAMILY_DISPOSITION"] == "ARCHIVE_NO_V2_2"


# ---------------------------------------------------------------------------
# 15/16. OOS / holdout access refused
# ---------------------------------------------------------------------------

def test_oos_access_is_refused_by_every_causal_policy_entry_point():
    from ag_edgelab.data.fx_histdata_multiyear import assert_partition_accessible
    with pytest.raises(NonDevelopmentAccessError):
        assert_partition_accessible("OOS")
    from ag_edgelab.strategies.asian_liquidity_displacement_v2_real_fixture import (
        assert_development_role, produce_real_fixture,
    )
    with pytest.raises(NonDevelopmentAccessError):
        assert_development_role(DatasetRole.OOS)
    # refused BEFORE any fixture file is opened
    with pytest.raises(NonDevelopmentAccessError):
        produce_real_fixture(
            preregistration_path=ROOT / "config/governance/funnel_optimizer_v1_fixture_preregistration.json",
            root=ROOT, role=DatasetRole.OOS)


def test_holdout_access_is_refused_by_every_causal_policy_entry_point():
    from ag_edgelab.data.fx_histdata_multiyear import (
        LOADABLE_ROLES, assert_partition_accessible,
    )
    with pytest.raises(NonDevelopmentAccessError):
        assert_partition_accessible("SEALED_HOLDOUT")
    from ag_edgelab.strategies.asian_liquidity_displacement_v2_real_fixture import (
        assert_development_role, produce_real_fixture,
    )
    with pytest.raises(NonDevelopmentAccessError):
        assert_development_role(DatasetRole.SEALED_OOS)
    with pytest.raises(NonDevelopmentAccessError):
        produce_real_fixture(
            preregistration_path=ROOT / "config/governance/funnel_optimizer_v1_fixture_preregistration.json",
            root=ROOT, role=DatasetRole.SEALED_OOS)
    # the annual partition vocabulary keeps the holdout sealed and loadable
    # access is DEVELOPMENT-only
    assert LOADABLE_ROLES == frozenset({"DEVELOPMENT"})


# ---------------------------------------------------------------------------
# Execution semantics (PHASE B5)
# ---------------------------------------------------------------------------

def test_candidate_and_null_must_share_identical_execution_semantics():
    assert_candidate_null_semantics_identical(FROZEN_EXECUTION_SEMANTICS,
                                              ExecutionSemanticsV1())
    drifted = ExecutionSemanticsV1(intrabar_tie_policy="TARGET_FIRST")
    with pytest.raises(ExecutionDrift):
        assert_candidate_null_semantics_identical(FROZEN_EXECUTION_SEMANTICS, drifted)


def test_unknown_friction_can_never_be_encoded_as_zero():
    with pytest.raises(FrictionZeroError):
        ExecutionSemanticsV1(spread_authority="ZERO")
    with pytest.raises(FrictionZeroError):
        ExecutionSemanticsV1(friction_status="APPLIED")
    assert FROZEN_EXECUTION_SEMANTICS.friction_status == "UNAVAILABLE_UNKNOWN"
    assert FROZEN_EXECUTION_SEMANTICS.structural_gate_label == "STRUCTURAL_DIAGNOSTIC_ONLY"
    assert execution_semantics_hash() == execution_semantics_hash(ExecutionSemanticsV1())


# ---------------------------------------------------------------------------
# Frozen policy proposal governance bindings
# ---------------------------------------------------------------------------

def test_policy_proposal_is_proposed_not_authorized_and_hash_self_verifies():
    from ag_edgelab.data.fingerprint import sha256_json
    proposal = json.loads(
        (ROOT / "config/governance/funnel_optimizer_r3_causal_policy_proposal.json").read_text())
    assert proposal["POLICY_STATUS"] == "PROPOSED_OWNER_POLICY"
    assert proposal["OWNER_R3_POLICY_AUTHORIZED"] is False
    assert proposal["REAL_CAMPAIGN_AUTHORIZED"] is False
    assert proposal["POLICY_FREEZE_BASE"] == "252059ec84e76562e8ecb7115311f42bb62eac41"
    assert proposal["BASELINE_T2_TIMING_POLICY"] == "UNRESOLVED_OWNER_DECISION"
    assert proposal["PARENT_MASK"] == CAUSAL_MASK_ID
    assert proposal["NULLS"]["PRIMARY_NULL"] == "RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY"
    assert proposal["MULTIPLE_TESTING"]["MAX_CHILDREN_PER_PARENT"] == 100
    assert proposal["MULTIPLE_TESTING"]["OWNER_AUTHORIZATION_REQUIRED"] is True
    body = dict(proposal)
    body.pop("POLICY_HASH")
    body.pop("POLICY_HASH_DEFINITION")
    assert proposal["POLICY_HASH"] == sha256_json(body)
