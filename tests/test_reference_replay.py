from datetime import datetime, timedelta, timezone

from ag_edgelab.contracts.intent import OrderIntent, OrderType, Side, Target
from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.contracts.trade import ExecutionStatus, ExitReason
from ag_edgelab.engines.reference.replay import ReferenceReplayEngine


def bar(ts, o, h, l, c):
    return MarketBar(timestamp=ts, open=o, high=h, low=l, close=c)


def test_reference_replay_resolves_stop_before_target_on_ambiguous_bar():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    engine = ReferenceReplayEngine({"EURUSD": (bar(t, 1.10, 1.13, 1.08, 1.11),)})
    intent = OrderIntent(
        candidate_id="C1", instrument="EURUSD", created_at=t, side=Side.LONG,
        order_type=OrderType.MARKET, entry_price=1.10, stop_price=1.09,
        targets=(Target(price=1.12, allocation=1.0),),
    )
    result = engine.execute_one(intent)
    assert result.status == ExecutionStatus.CLOSED
    assert result.exit_reason == ExitReason.STOP
    assert round(result.gross_r or 0, 9) == -1.0


def test_reference_replay_weighted_targets_compute_r():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = (
        bar(t, 1.10, 1.111, 1.095, 1.105),
        bar(t + timedelta(minutes=1), 1.105, 1.121, 1.104, 1.12),
    )
    engine = ReferenceReplayEngine({"EURUSD": rows})
    intent = OrderIntent(
        candidate_id="C2", instrument="EURUSD", created_at=t, side=Side.LONG,
        order_type=OrderType.MARKET, entry_price=1.10, stop_price=1.09,
        targets=(Target(price=1.11, allocation=0.5), Target(price=1.12, allocation=0.5)),
    )
    result = engine.execute_one(intent)
    assert result.exit_reason == ExitReason.TARGETS_COMPLETE
    assert round(result.gross_r or 0, 9) == 1.5


def test_unfilled_limit_expires():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = tuple(bar(t + timedelta(minutes=i), 1.10, 1.11, 1.10, 1.105) for i in range(3))
    engine = ReferenceReplayEngine({"EURUSD": rows})
    intent = OrderIntent(
        candidate_id="C3", instrument="EURUSD", created_at=t, side=Side.LONG,
        order_type=OrderType.LIMIT, entry_price=1.09, stop_price=1.08,
        targets=(Target(price=1.11, allocation=1.0),), expire_after_bars=2,
    )
    assert engine.execute_one(intent).status == ExecutionStatus.NO_FILL
