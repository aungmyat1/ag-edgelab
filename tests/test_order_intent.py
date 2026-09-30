from datetime import datetime, timezone

import pytest

from ag_edgelab.contracts.intent import OrderIntent, OrderType, Side, Target


def test_long_geometry_and_allocations():
    order = OrderIntent(
        candidate_id="C1",
        instrument="EURUSD",
        created_at=datetime.now(timezone.utc),
        side=Side.LONG,
        order_type=OrderType.LIMIT,
        entry_price=1.10,
        stop_price=1.09,
        targets=(Target(price=1.12, allocation=0.5), Target(price=1.13, allocation=0.5)),
    )
    assert order.stop_price < order.entry_price


def test_rejects_bad_allocations():
    with pytest.raises(ValueError, match="sum to 1.0"):
        OrderIntent(
            candidate_id="C1",
            instrument="EURUSD",
            created_at=datetime.now(timezone.utc),
            side=Side.LONG,
            order_type=OrderType.LIMIT,
            entry_price=1.10,
            stop_price=1.09,
            targets=(Target(price=1.12, allocation=0.7),),
        )
