from __future__ import annotations

from collections.abc import Mapping

from ag_edgelab.contracts.intent import OrderIntent, OrderType, Side
from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.contracts.trade import ExecutionResult, ExecutionStatus, ExitReason


class ReferenceReplayEngine:
    """Deterministic conservative OHLC reference replay.

    If a stop and target are both reachable in the same bar, stop wins because
    OHLC data does not establish intrabar order. Friction is applied later.
    """

    name = "AG_REFERENCE_REPLAY"
    version = "1.0.0"

    def __init__(self, bars: Mapping[str, tuple[MarketBar, ...]]):
        self._bars = {symbol: tuple(sorted(rows, key=lambda b: b.timestamp)) for symbol, rows in bars.items()}

    @staticmethod
    def _entry_touched(intent: OrderIntent, bar: MarketBar, entry: float) -> bool:
        if intent.order_type == OrderType.MARKET:
            return True
        if intent.order_type == OrderType.LIMIT:
            return bar.low <= entry <= bar.high
        return bar.high >= entry if intent.side == Side.LONG else bar.low <= entry

    @staticmethod
    def _stop_hit(intent: OrderIntent, bar: MarketBar) -> bool:
        return bar.low <= intent.stop_price if intent.side == Side.LONG else bar.high >= intent.stop_price

    @staticmethod
    def _target_hit(intent: OrderIntent, bar: MarketBar, price: float) -> bool:
        return bar.high >= price if intent.side == Side.LONG else bar.low <= price

    @staticmethod
    def _r(intent: OrderIntent, entry: float, exit_price: float) -> float:
        risk = abs(entry - intent.stop_price)
        if risk <= 0:
            raise ValueError("entry and stop imply zero risk")
        signed_move = exit_price - entry if intent.side == Side.LONG else entry - exit_price
        return signed_move / risk

    def execute(self, intents: tuple[OrderIntent, ...]) -> tuple[ExecutionResult, ...]:
        return tuple(self.execute_one(intent) for intent in intents)

    def execute_one(self, intent: OrderIntent) -> ExecutionResult:
        bars = tuple(b for b in self._bars.get(intent.instrument, ()) if b.timestamp >= intent.created_at)
        if not bars:
            return self._no_fill(intent)

        entry_price = intent.entry_price
        filled = False
        entry_time = None
        post_entry_bars: list[MarketBar] = []
        bars_seen = 0

        for bar in bars:
            if not filled:
                bars_seen += 1
                if intent.expire_after_bars is not None and bars_seen > intent.expire_after_bars:
                    break
                candidate_entry = bar.open if intent.order_type == OrderType.MARKET and entry_price is None else entry_price
                if candidate_entry is None:
                    raise ValueError("non-market orders require entry_price")
                if self._entry_touched(intent, bar, candidate_entry):
                    entry_price = float(candidate_entry)
                    entry_time = bar.timestamp
                    filled = True
                    post_entry_bars.append(bar)
            else:
                post_entry_bars.append(bar)

        if not filled or entry_price is None or entry_time is None:
            return self._no_fill(intent)

        remaining = 1.0
        realized_r = 0.0
        hit_targets: set[int] = set()
        last_bar = post_entry_bars[-1]

        for bar in post_entry_bars:
            if self._stop_hit(intent, bar):
                realized_r += remaining * self._r(intent, entry_price, intent.stop_price)
                return ExecutionResult(
                    candidate_id=intent.candidate_id, instrument=intent.instrument, side=intent.side,
                    status=ExecutionStatus.CLOSED, entry_time=entry_time, entry_price=entry_price,
                    exit_time=bar.timestamp, exit_price=intent.stop_price, exit_reason=ExitReason.STOP,
                    gross_r=realized_r, remaining_allocation=0.0,
                    engine_name=self.name, engine_version=self.version,
                )

            for idx, target in enumerate(intent.targets):
                if idx in hit_targets:
                    continue
                if self._target_hit(intent, bar, target.price):
                    realized_r += target.allocation * self._r(intent, entry_price, target.price)
                    remaining -= target.allocation
                    hit_targets.add(idx)

            if remaining <= 1e-12:
                return ExecutionResult(
                    candidate_id=intent.candidate_id, instrument=intent.instrument, side=intent.side,
                    status=ExecutionStatus.CLOSED, entry_time=entry_time, entry_price=entry_price,
                    exit_time=bar.timestamp, exit_price=bar.close, exit_reason=ExitReason.TARGETS_COMPLETE,
                    gross_r=realized_r, remaining_allocation=0.0,
                    engine_name=self.name, engine_version=self.version,
                )

        return ExecutionResult(
            candidate_id=intent.candidate_id, instrument=intent.instrument, side=intent.side,
            status=ExecutionStatus.OPEN_AT_END, entry_time=entry_time, entry_price=entry_price,
            exit_time=last_bar.timestamp, exit_price=last_bar.close, exit_reason=ExitReason.DATA_END,
            gross_r=realized_r, remaining_allocation=max(0.0, remaining),
            engine_name=self.name, engine_version=self.version,
        )

    def _no_fill(self, intent: OrderIntent) -> ExecutionResult:
        return ExecutionResult(
            candidate_id=intent.candidate_id, instrument=intent.instrument, side=intent.side,
            status=ExecutionStatus.NO_FILL, remaining_allocation=1.0,
            engine_name=self.name, engine_version=self.version,
        )
