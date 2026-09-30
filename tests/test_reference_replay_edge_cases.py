from datetime import datetime, timedelta, timezone

from ag_edgelab.contracts.intent import OrderIntent, OrderType, Side, Target
from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.contracts.trade import ExecutionStatus, ExitReason
from ag_edgelab.engines.reference.replay import ReferenceReplayEngine


def bar(ts, o, h, l, c):
    return MarketBar(timestamp=ts, open=o, high=h, low=l, close=c)


def test_short_stop_order_activates_then_hits_target():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = (
        bar(t, 1.1000, 1.1005, 1.0985, 1.0995),
        bar(t + timedelta(minutes=1), 1.0995, 1.1005, 1.0965, 1.0970),
    )
    engine = ReferenceReplayEngine({"EURUSD": rows})
    intent = OrderIntent(
        candidate_id="S1", instrument="EURUSD", created_at=t, side=Side.SHORT,
        order_type=OrderType.STOP, entry_price=1.0990, stop_price=1.1010,
        targets=(Target(price=1.0970, allocation=1.0),),
    )
    result = engine.execute_one(intent)
    assert result.entry_time == t
    assert result.status == ExecutionStatus.CLOSED
    assert result.exit_reason == ExitReason.TARGETS_COMPLETE
    assert round(result.gross_r or 0.0, 9) == 1.0


def test_open_at_data_end_preserves_realized_partial_target_r():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = (bar(t, 1.1000, 1.1110, 1.0950, 1.1050),)
    engine = ReferenceReplayEngine({"EURUSD": rows})
    intent = OrderIntent(
        candidate_id="P1", instrument="EURUSD", created_at=t, side=Side.LONG,
        order_type=OrderType.MARKET, entry_price=1.1000, stop_price=1.0900,
        targets=(Target(price=1.1100, allocation=0.5), Target(price=1.1200, allocation=0.5)),
    )
    result = engine.execute_one(intent)
    assert result.status == ExecutionStatus.OPEN_AT_END
    assert result.exit_reason == ExitReason.DATA_END
    assert round(result.gross_r or 0.0, 9) == 0.5
    assert result.remaining_allocation == 0.5


def test_limit_expiry_counts_only_bars_at_or_after_creation():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = (
        bar(t - timedelta(minutes=1), 1.0900, 1.0910, 1.0890, 1.0900),
        bar(t, 1.1000, 1.1010, 1.0990, 1.1000),
        bar(t + timedelta(minutes=1), 1.1000, 1.1010, 1.0990, 1.1000),
        bar(t + timedelta(minutes=2), 1.0900, 1.0910, 1.0890, 1.0900),
    )
    engine = ReferenceReplayEngine({"EURUSD": rows})
    intent = OrderIntent(
        candidate_id="E1", instrument="EURUSD", created_at=t, side=Side.LONG,
        order_type=OrderType.LIMIT, entry_price=1.0900, stop_price=1.0800,
        targets=(Target(price=1.1100, allocation=1.0),), expire_after_bars=2,
    )
    assert engine.execute_one(intent).status == ExecutionStatus.NO_FILL
