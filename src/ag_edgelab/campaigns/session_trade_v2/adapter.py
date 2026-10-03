from __future__ import annotations

"""Deterministic adapter: frozen SESSION_TRADE_V2 decisions -> EdgeLab order intents.

The upstream engine owns all trading rules (priority A -> B -> C, sweep
geometry, stop protection, entry prices, 4R/5R target prices).  This adapter
only binds those decisions to EdgeLab's ``OrderIntent`` execution semantics:

* A_SWEEP_REENTRY (MARKET): the decision exists only after the qualifying
  candle closes, so ``created_at`` = signal candle close time and the replay
  fills at the next executable bar OPEN (no intra-bar lookahead price).
* B_RANGE_REJECTION / C_TREND_EXPANSION (LIMIT): the limit works from the
  signal candle close until the END of the trade window; it then EXPIRES.
  An unfilled limit is never converted to a market entry.
* C runner management: the upstream spec defines the runner as "trail behind
  confirmed M15 swings, 5R cap" but does not define swing confirmation
  deterministically.  Per the campaign contract we therefore do NOT improvise
  a trail: C is replayed with the frozen ``C_FIXED_EXIT_PROXY`` — 75% at the
  source-emitted 4R price, 25% at the source-emitted 5R price, original stop
  throughout (the spec states no breakeven move for C).  C cells are
  DIAGNOSTIC-ONLY and can never be authoritative verification evidence.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from ag_edgelab.campaigns.session_trade_v2.frozen import Candle, Decision
from ag_edgelab.campaigns.session_trade_v2.replay import targets_4r_5r
from ag_edgelab.campaigns.session_trade_v2.windows import SessionWindow, expected_bar_times
from ag_edgelab.contracts.intent import OrderIntent, OrderType, Side, Target

C_PROXY_LABEL = "C_FIXED_EXIT_PROXY"


@dataclass(frozen=True)
class SessionEvaluation:
    """One symbol/session/date evaluation outcome with provenance."""

    symbol: str
    session: str
    trading_date: str
    outcome: str                  # SIGNAL | NO_TRADE | DATA_INVALID
    reason: str | None
    decision: Decision | None
    intent: OrderIntent | None
    intent_metadata: dict | None
    workable_limit_bars: int | None = None

    @property
    def signal(self) -> bool:
        return self.outcome == "SIGNAL"

    @property
    def setup(self) -> str | None:
        return self.decision.setup if self.decision else None


def to_candles(bars) -> tuple[Candle, ...]:
    """Convert EdgeLab MarketBar tuples to the frozen engine's Candle type."""
    return tuple(Candle(time=b.timestamp, open=b.open, high=b.high, low=b.low, close=b.close) for b in bars)


def _management_targets(decision: Decision) -> tuple[Target, ...]:
    if decision.setup == "C_TREND_EXPANSION":
        # Frozen diagnostic proxy: source-emitted 4R/5R prices, original stop
        # retained for both legs (no breakeven rule exists for C).
        return (
            Target(price=decision.target_4r, allocation=0.75, move_stop_to_entry=False),
            Target(price=decision.target_5r, allocation=0.25, move_stop_to_entry=False),
        )
    # A/B: 75% at 4R then stop -> breakeven; 25% runner at 5R.
    return targets_4r_5r(decision.entry, decision.stop_loss, Side(decision.direction))


def adapt_decision(
    symbol: str,
    window: SessionWindow,
    decision: Decision,
    trading_date_str: str,
) -> SessionEvaluation:
    """Bind one frozen-engine decision to EdgeLab order semantics."""
    if decision.status != "SIGNAL":
        return SessionEvaluation(
            symbol, window.session, trading_date_str, "NO_TRADE", decision.reason_code,
            decision, None, None,
        )

    signal_close = decision.signal_timestamp + timedelta(minutes=15)
    is_market = decision.entry_order_type == "MARKET"
    workable = len(expected_bar_times(signal_close, window.trade_end))

    meta = {
        "setup": decision.setup,
        "session": window.session,
        "trading_date": trading_date_str,
        "direction": decision.direction,
        "signal_time": decision.signal_timestamp,
        "risk_distance": decision.risk_distance,
        "management": C_PROXY_LABEL if decision.setup == "C_TREND_EXPANSION" else decision.management,
        "box_high": decision.box_high,
        "box_low": decision.box_low,
        "box_mid": decision.box_mid,
    }

    if not is_market and workable == 0:
        # Limit signal generated on the final trade-window candle: the order
        # would only start working after the window closed -> expired unfilled.
        return SessionEvaluation(
            symbol, window.session, trading_date_str, "SIGNAL", decision.reason_code,
            decision, None, {**meta, "never_workable": True}, workable_limit_bars=0,
        )

    intent = OrderIntent(
        candidate_id=(
            f"STV2|{symbol}|{window.session}|{trading_date_str}|{decision.setup}"
        ),
        instrument=symbol,
        created_at=signal_close,
        side=Side(decision.direction),
        order_type=OrderType.MARKET if is_market else OrderType.LIMIT,
        entry_price=None if is_market else decision.entry,
        stop_price=decision.stop_loss,
        targets=_management_targets(decision),
        expire_after_bars=None if is_market else workable,
    )
    return SessionEvaluation(
        symbol, window.session, trading_date_str, "SIGNAL", decision.reason_code,
        decision, intent, meta, workable_limit_bars=(workable if not is_market else None),
    )


def signal_close_time(decision: Decision) -> datetime:
    """Close time of the qualifying signal candle (decision evidence time)."""
    return decision.signal_timestamp + timedelta(minutes=15)
