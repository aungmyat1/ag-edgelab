from __future__ import annotations

"""Deterministic campaign replay for SESSION_TRADE_V2 proposals.

This engine reuses the frozen semantics of
``ag_edgelab.engines.reference.replay.ReferenceReplayEngine``:

* same-bar stop/target ambiguity resolves to the STOP (conservative);
* stop changes triggered by a target take effect only after that bar;
* MARKET intents fill at the open of the first bar at/after ``created_at``
  (next-executable-price; the decision only exists after the signal candle
  closes, so no intra-bar lookahead price is used);
* LIMIT intents fill only when the bar range touches the limit price.

Campaign-specific frozen additions (documented, conservative, deterministic):

* LIMIT fill bar: targets are NOT evaluated on the bar that fills a limit
  order, because the fill instant inside the bar is unknown and a target
  touch may have preceded the fill (path ambiguity).  The stop IS evaluated
  on the fill bar (worst case).  Suppressed target touches are counted as
  same-bar ambiguity events.
* ``expire_after_bars`` bounds the working life of LIMIT orders (trade
  window end); a signal that never fills is UNFILLED/EXPIRED, never a loss.
* Every resolved trade records leg-level diagnostics (4R partial, 5R runner,
  runner breakeven), holding time and same-bar ambiguity counts.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from ag_edgelab.contracts.intent import OrderIntent, OrderType, Side, Target
from ag_edgelab.contracts.market import MarketBar


@dataclass(frozen=True)
class CampaignTrade:
    """One replayed proposal with full deterministic diagnostics."""

    trade_id: str
    candidate_id: str
    instrument: str
    setup: str
    session: str
    trading_date: str
    direction: str
    order_type: str
    status: str                 # FILLED_CLOSED | FILLED_OPEN_AT_END | UNFILLED | EXPIRED
    signal_time: datetime | None
    entry_time: datetime | None = None
    entry_price: float | None = None
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    risk_distance: float | None = None
    gross_r: float | None = None
    tp1_4r_hit: bool = False
    runner_5r_hit: bool = False
    runner_breakeven: bool = False
    runner_open_at_end: bool = False
    same_bar_ambiguities: int = 0
    bars_held: int = 0
    engine_name: str = "STV2_CAMPAIGN_REPLAY"
    engine_version: str = "1.0.0"

    @property
    def filled(self) -> bool:
        return self.status in ("FILLED_CLOSED", "FILLED_OPEN_AT_END")

    @property
    def closed(self) -> bool:
        return self.status == "FILLED_CLOSED"

    @property
    def holding_seconds(self) -> float | None:
        if self.entry_time is None or self.exit_time is None:
            return None
        return (self.exit_time - self.entry_time).total_seconds()


@dataclass(frozen=True)
class _ReplayOutcome:
    status: str
    entry_time: datetime | None = None
    entry_price: float | None = None
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    gross_r: float | None = None
    tp1_hit: bool = False
    runner_5r: bool = False
    runner_be: bool = False
    runner_open: bool = False
    ambiguities: int = 0
    bars_held: int = 0


def _stop_hit(side: Side, stop: float, bar: MarketBar) -> bool:
    return bar.low <= stop if side == Side.LONG else bar.high >= stop


def _target_hit(side: Side, price: float, bar: MarketBar) -> bool:
    return bar.high >= price if side == Side.LONG else bar.low <= price


def _r(entry: float, stop: float, side: Side, exit_price: float) -> float:
    risk = abs(entry - stop)
    if risk <= 0:
        raise ValueError("entry and stop imply zero risk")
    signed = exit_price - entry if side == Side.LONG else entry - exit_price
    return signed / risk


class CampaignReplayEngine:
    """Reference-replay semantics plus the campaign's frozen conservative rules."""

    name = "STV2_CAMPAIGN_REPLAY"
    version = "1.0.0"

    def __init__(self, bars: Mapping[str, tuple[MarketBar, ...]]):
        # Same ordering guarantee as the frozen reference engine.
        self._bars = {
            symbol: tuple(sorted(rows, key=lambda b: b.timestamp))
            for symbol, rows in bars.items()
        }

    def execute(self, pairs: tuple[tuple[OrderIntent, Mapping], ...]) -> tuple[CampaignTrade, ...]:
        return tuple(self.execute_one(intent, metadata) for intent, metadata in pairs)

    def execute_one(self, intent: OrderIntent, metadata: Mapping | None = None) -> CampaignTrade:
        meta = dict(metadata or {})
        meta.setdefault("direction", intent.side.value)
        outcome = self._replay(intent)
        return CampaignTrade(
            trade_id=intent.candidate_id,
            candidate_id=intent.candidate_id,
            instrument=intent.instrument,
            setup=meta["setup"],
            session=meta["session"],
            trading_date=meta["trading_date"],
            direction=meta["direction"],
            order_type=intent.order_type.value,
            status=outcome.status,
            signal_time=meta.get("signal_time"),
            entry_time=outcome.entry_time,
            entry_price=outcome.entry_price,
            exit_time=outcome.exit_time,
            exit_price=outcome.exit_price,
            exit_reason=outcome.exit_reason,
            risk_distance=meta.get("risk_distance"),
            gross_r=outcome.gross_r,
            tp1_4r_hit=outcome.tp1_hit,
            runner_5r_hit=outcome.runner_5r,
            runner_breakeven=outcome.runner_be,
            runner_open_at_end=outcome.runner_open,
            same_bar_ambiguities=outcome.ambiguities,
            bars_held=outcome.bars_held,
            engine_name=self.name,
            engine_version=self.version,
        )

    def _replay(self, intent: OrderIntent) -> _ReplayOutcome:
        bars = tuple(
            b for b in self._bars.get(intent.instrument, ()) if b.timestamp >= intent.created_at
        )
        is_limit = intent.order_type == OrderType.LIMIT
        if intent.entry_price is None and is_limit:
            raise ValueError("LIMIT intents require entry_price")

        if not bars:
            # A LIMIT with no working bars left in the window has expired;
            # a MARKET with no subsequent bar could not be executed.
            return _ReplayOutcome("EXPIRED" if is_limit else "UNFILLED")

        # ---- entry scan -------------------------------------------------
        entry_price: float | None = None
        entry_time: datetime | None = None
        fill_bar_index: int | None = None
        bars_seen = 0
        for index, bar in enumerate(bars):
            bars_seen += 1
            if is_limit:
                if intent.expire_after_bars is not None and bars_seen > intent.expire_after_bars:
                    break
                if bar.low <= intent.entry_price <= bar.high:
                    entry_price = float(intent.entry_price)
                    entry_time = bar.timestamp
                    fill_bar_index = index
                    break
            else:  # MARKET: next-executable price = first bar open at/after created_at
                entry_price = float(bar.open)
                entry_time = bar.timestamp
                fill_bar_index = index
                break

        if fill_bar_index is None or entry_price is None or entry_time is None:
            return _ReplayOutcome("EXPIRED" if is_limit else "UNFILLED")

        # ---- exit management --------------------------------------------
        remaining = 1.0
        realized_r = 0.0
        hit_targets: set[int] = set()
        active_stop = intent.stop_price
        ambiguities = 0
        bars_held = 0
        tp1_hit = False
        runner_5r = False
        runner_be = False
        runner_open = False
        last_bar = bars[fill_bar_index]

        for bar in bars[fill_bar_index:]:
            bars_held += 1
            last_bar = bar
            is_fill_bar = bar.timestamp == entry_time

            # 1) stop first (conservative same-bar policy)
            if _stop_hit(intent.side, active_stop, bar):
                r_mult = _r(entry_price, intent.stop_price, intent.side, active_stop)
                realized_r += remaining * r_mult
                # ambiguity: an unhit target was also reachable in this bar
                unhit_in_bar = any(
                    idx not in hit_targets and _target_hit(intent.side, t.price, bar)
                    for idx, t in enumerate(intent.targets)
                )
                if unhit_in_bar:
                    ambiguities += 1
                if remaining < 1.0 - 1e-12 and abs(active_stop - entry_price) < 1e-12:
                    runner_be = True
                return _ReplayOutcome(
                    "FILLED_CLOSED", entry_time, entry_price, bar.timestamp, active_stop,
                    "STOP", realized_r, tp1_hit, runner_5r, runner_be, runner_open,
                    ambiguities, bars_held,
                )

            # 2) targets (suppressed on a LIMIT fill bar: fill instant unknown)
            if is_fill_bar and is_limit:
                suppressed = any(
                    idx not in hit_targets and _target_hit(intent.side, t.price, bar)
                    for idx, t in enumerate(intent.targets)
                )
                if suppressed:
                    ambiguities += 1
            else:
                move_to_entry = False
                for idx, target in enumerate(intent.targets):
                    if idx in hit_targets:
                        continue
                    if _target_hit(intent.side, target.price, bar):
                        realized_r += target.allocation * _r(
                            entry_price, intent.stop_price, intent.side, target.price
                        )
                        remaining -= target.allocation
                        hit_targets.add(idx)
                        if idx == 0:
                            tp1_hit = True
                        if idx == len(intent.targets) - 1:
                            runner_5r = True
                        move_to_entry = move_to_entry or target.move_stop_to_entry
                if move_to_entry and remaining > 1e-12:
                    # takes effect only after this bar has been resolved
                    active_stop = entry_price
                if remaining <= 1e-12:
                    return _ReplayOutcome(
                        "FILLED_CLOSED", entry_time, entry_price, bar.timestamp, bar.close,
                        "TARGETS_COMPLETE", realized_r, tp1_hit, runner_5r, runner_be,
                        runner_open, ambiguities, bars_held,
                    )

        # unresolved at end of available data (partition boundary)
        if remaining < 1.0 - 1e-12:
            runner_open = True
        return _ReplayOutcome(
            "FILLED_OPEN_AT_END", entry_time, entry_price, last_bar.timestamp, last_bar.close,
            "DATA_END", realized_r, tp1_hit, runner_5r, runner_be, runner_open,
            ambiguities, bars_held,
        )


def targets_4r_5r(entry: float, stop: float, side: Side) -> tuple[Target, Target]:
    """A/B management legs: 75% at 4R (then BE), 25% at 5R."""
    risk = abs(entry - stop)
    sign = 1.0 if side == Side.LONG else -1.0
    return (
        Target(price=entry + sign * 4.0 * risk, allocation=0.75, move_stop_to_entry=True),
        Target(price=entry + sign * 5.0 * risk, allocation=0.25, move_stop_to_entry=False),
    )
