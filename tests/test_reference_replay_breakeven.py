from datetime import datetime, timedelta, timezone

from ag_edgelab.contracts.intent import OrderIntent, OrderType, Side, Target
from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.contracts.trade import ExitReason
from ag_edgelab.engines.reference.replay import ReferenceReplayEngine


def bar(ts, o, h, l, c):
    return MarketBar(timestamp=ts, open=o, high=h, low=l, close=c)


def test_tp1_can_move_remaining_stop_to_breakeven():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = (
        bar(t, 100, 111, 99, 110),
        bar(t + timedelta(minutes=5), 110, 111, 99, 100),
    )
    engine = ReferenceReplayEngine({"BTCUSDT": rows})
    intent = OrderIntent(
        candidate_id="BTC1",
        instrument="BTCUSDT",
        created_at=t,
        side=Side.LONG,
        order_type=OrderType.MARKET,
        entry_price=100,
        stop_price=90,
        targets=(
            Target(price=110, allocation=0.5, move_stop_to_entry=True),
            Target(price=120, allocation=0.5),
        ),
    )
    result = engine.execute_one(intent)
    assert result.exit_reason == ExitReason.STOP
    assert result.exit_price == 100
    assert round(result.gross_r or 0.0, 9) == 0.5
