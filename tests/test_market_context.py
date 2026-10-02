from datetime import datetime, timedelta, timezone

import pytest

from ag_edgelab.contracts.market import EvaluationContext, MarketBar


def bar(ts):
    return MarketBar(timestamp=ts, open=1.0, high=1.2, low=0.9, close=1.1)


def test_context_rejects_future_bar():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="future bar"):
        EvaluationContext(instrument="EURUSD", as_of=now, bars={"M1": (bar(now + timedelta(minutes=1)),)})


def test_context_accepts_history_at_or_before_as_of():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ctx = EvaluationContext(instrument="EURUSD", as_of=now, bars={"M1": (bar(now - timedelta(minutes=1)), bar(now))})
    assert len(ctx.bars["M1"]) == 2
