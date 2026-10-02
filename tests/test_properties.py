from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, strategies as st

from ag_edgelab.contracts.funnel import FunnelStage, RuleResult
from ag_edgelab.contracts.market import EvaluationContext, MarketBar
from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.funnels.runner import FunnelRunner, StageDefinition, StageMode


@given(st.dictionaries(st.text(min_size=1, max_size=8), st.integers(), max_size=12))
def test_canonical_hash_is_mapping_order_independent(mapping):
    reversed_items = dict(reversed(list(mapping.items())))
    assert sha256_json(mapping) == sha256_json(reversed_items)


@given(st.integers(min_value=1, max_value=86400))
def test_any_future_bar_is_rejected(offset_seconds):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    future = MarketBar(
        timestamp=now + timedelta(seconds=offset_seconds),
        open=1.0, high=1.1, low=0.9, close=1.0,
    )
    with pytest.raises(ValueError, match="future bar"):
        EvaluationContext(instrument="EURUSD", as_of=now, bars={"M1": (future,)})


class CountingRule:
    def __init__(self, index, passed, calls):
        self.rule_id = f"r{index}"
        self.rule_version = "1"
        self.rule_hash = "a" * 64
        self._passed = passed
        self._calls = calls

    def evaluate(self, context):
        self._calls.append(self.rule_id)
        return RuleResult(
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            rule_hash=self.rule_hash,
            passed=self._passed,
            evaluated_at=context.as_of,
            failure_reason=None if self._passed else "FAIL",
            rejection_code=None if self._passed else "RULE_FAIL",
        )


@given(st.lists(st.booleans(), min_size=1, max_size=12))
def test_sequence_never_evaluates_after_first_failure(outcomes):
    calls = []
    rules = tuple(CountingRule(i, value, calls) for i, value in enumerate(outcomes))
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    FunnelRunner().evaluate_stage(
        candidate_id="C",
        definition=StageDefinition(FunnelStage.TRIGGER, rules, StageMode.SEQUENCE),
        context=EvaluationContext(instrument="EURUSD", as_of=now),
    )
    expected = len(outcomes)
    if False in outcomes:
        expected = outcomes.index(False) + 1
    assert len(calls) == expected
