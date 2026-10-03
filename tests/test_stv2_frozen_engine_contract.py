from __future__ import annotations

"""Focused tests: the frozen upstream contract, exercised through the adapter.

Geometry fixture (EURUSD-like):
    H = 1.1010, L = 1.0980, A = 0.0030, R0 = 0.25*A = 0.00075, EQ = 1.0995
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from ag_edgelab.campaigns.session_trade_v2.adapter import adapt_decision, to_candles
from ag_edgelab.campaigns.session_trade_v2.frozen import Candle, evaluate
from ag_edgelab.campaigns.session_trade_v2.windows import session_window
from ag_edgelab.contracts.intent import OrderType

UTC = timezone.utc
H, L = 1.1010, 1.0980
A = H - L
R0 = 0.25 * A
EQ = (H + L) / 2


def ref_candles(start_hour=22):
    """Two reference candles spanning the box."""
    t0 = datetime(2017, 6, 14, start_hour, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=15)
    return (
        Candle(time=t0, open=1.1000, high=H, low=L, close=1.1000),
        Candle(time=t1, open=1.1000, high=1.1005, low=1.0985, close=1.1000),
    )


def trade_candle(hour, o, h, l, c, minute=0):
    return Candle(time=datetime(2017, 6, 15, hour, minute, tzinfo=UTC),
                  open=o, high=h, low=l, close=c)


def adapt(symbol, session, decision, trading_date):
    return adapt_decision(symbol, session_window(session, trading_date), decision,
                          trading_date.isoformat())


TD = date(2017, 6, 15)


# 5. A long sweep --------------------------------------------------------------------

def test_a_long_sweep_market_long():
    # sweeps below L (low 1.0975 < L) and closes back above L (1.0982)
    d = evaluate("EURUSD", "ASIAN_LONDON", ref_candles(),
                 [trade_candle(6, 1.0985, 1.0990, 1.0975, 1.0982)])
    assert d.status == "SIGNAL"
    assert d.setup == "A_SWEEP_REENTRY"
    assert d.direction == "LONG"
    assert d.entry_order_type == "MARKET"
    assert d.entry == pytest.approx(1.0982)
    assert d.stop_loss == pytest.approx(1.0982 - R0)
    assert d.stop_loss < 1.0975  # stop protects the swept wick
    assert d.risk_distance == pytest.approx(R0)
    ev = adapt("EURUSD", "ASIAN_LONDON", d, TD)
    assert ev.intent is not None
    assert ev.intent.order_type == OrderType.MARKET
    assert ev.intent.entry_price is None  # next-executable price, not the close


# 6. A short sweep -------------------------------------------------------------------

def test_a_short_sweep_market_short():
    d = evaluate("EURUSD", "ASIAN_LONDON", ref_candles(),
                 [trade_candle(6, 1.1005, 1.1015, 1.1000, 1.1009)])
    assert d.status == "SIGNAL"
    assert d.setup == "A_SWEEP_REENTRY"
    assert d.direction == "SHORT"
    assert d.entry == pytest.approx(1.1009)
    assert d.stop_loss == pytest.approx(1.1009 + R0)
    assert d.stop_loss > 1.1015


# 7. dual-side sweep fail-closed ------------------------------------------------------

def test_dual_side_sweep_fails_closed_and_is_terminal():
    d = evaluate("GBPUSD", "ASIAN_LONDON", ref_candles(),
                 [trade_candle(6, 1.1000, 1.1020, 1.0970, 1.0995),
                  trade_candle(6, 1.0985, 1.0990, 1.0975, 1.0982, minute=15)])
    assert d.status == "NO_TRADE"
    assert d.reason_code == "AMBIGUOUS_DUAL_SIDE_SWEEP"
    # terminal: a later valid sweep candle must not rescue the session
    assert d.signal_timestamp.hour == 6 and d.signal_timestamp.minute == 0


# 8. sweep stop protects extreme ------------------------------------------------------

def test_sweep_stop_must_protect_extreme_and_is_terminal():
    # sweep closes 1.0981 -> stop 1.09735; wick low 1.09740 >= stop? no:
    # low 1.0973 is BELOW the stop -> stop does not protect -> NO_TRADE
    d = evaluate("EURUSD", "ASIAN_LONDON", ref_candles(),
                 [trade_candle(6, 1.0985, 1.0990, 1.0973, 1.0981),
                  trade_candle(6, 1.0985, 1.0990, 1.0975, 1.0982, minute=15)])
    assert d.status == "NO_TRADE"
    assert d.reason_code == "SWEEP_STOP_DOES_NOT_PROTECT_EXTREME"


def test_sweep_stop_inside_extreme_rejects_even_if_later_candle_valid():
    d = evaluate("EURUSD", "LONDON_NEWYORK", ref_candles(),
                 [trade_candle(11, 1.0985, 1.0990, 1.0973, 1.0981),
                  trade_candle(11, 1.0985, 1.0990, 1.0975, 1.0982, minute=15)])
    assert d.status == "NO_TRADE"
    assert d.reason_code == "SWEEP_STOP_DOES_NOT_PROTECT_EXTREME"


# 9. B long rejection -----------------------------------------------------------------

def test_b_long_rejection_boundary_limit():
    # touches L exactly and closes inside the box; no A setup exists
    d = evaluate("EURUSD", "ASIAN_LONDON", ref_candles(),
                 [trade_candle(6, 1.0985, 1.0990, L, 1.0990)])
    assert d.status == "SIGNAL"
    assert d.setup == "B_RANGE_REJECTION"
    assert d.direction == "LONG"
    assert d.entry_order_type == "LIMIT"
    assert d.entry == pytest.approx(L)
    assert d.stop_loss == pytest.approx(L - R0)
    ev = adapt("EURUSD", "ASIAN_LONDON", d, TD)
    assert ev.intent.entry_price == pytest.approx(L)
    assert ev.intent.expire_after_bars is not None and ev.intent.expire_after_bars > 0


# 10. B short rejection ---------------------------------------------------------------

def test_b_short_rejection_boundary_limit():
    d = evaluate("EURUSD", "ASIAN_LONDON", ref_candles(),
                 [trade_candle(6, 1.1005, H, 1.1000, 1.0998)])
    assert d.status == "SIGNAL"
    assert d.setup == "B_RANGE_REJECTION"
    assert d.direction == "SHORT"
    assert d.entry == pytest.approx(H)
    assert d.stop_loss == pytest.approx(H + R0)


# 11. dual rejection fail-closed ------------------------------------------------------

def test_dual_boundary_rejection_fails_closed():
    # touches both boundaries and closes inside -> ambiguous
    d = evaluate("USDJPY", "LONDON_NEWYORK", ref_candles(),
                 [trade_candle(11, 1.1000, H, L, 1.0995)])
    assert d.status == "NO_TRADE"
    assert d.reason_code == "AMBIGUOUS_DUAL_BOUNDARY_REJECTION"


# 12. C long expansion ----------------------------------------------------------------

def test_c_long_expansion_equilibrium_limit():
    # whole body above H: open 1.1012, close 1.1020 (body_low 1.1012 > H)
    d = evaluate("EURUSD", "ASIAN_LONDON", ref_candles(),
                 [trade_candle(6, 1.1012, 1.1022, 1.1011, 1.1020)])
    assert d.status == "SIGNAL"
    assert d.setup == "C_TREND_EXPANSION"
    assert d.direction == "LONG"
    assert d.entry_order_type == "LIMIT"
    assert d.entry == pytest.approx(EQ)          # EQ, never a broken-boundary retest
    assert d.stop_loss == pytest.approx(EQ - R0)
    ev = adapt("EURUSD", "ASIAN_LONDON", d, TD)
    # C is replayed only as the clearly labeled fixed-exit proxy
    assert ev.intent_metadata["management"] == "C_FIXED_EXIT_PROXY"


# 13. C short expansion ---------------------------------------------------------------

def test_c_short_expansion_equilibrium_limit():
    d = evaluate("EURUSD", "LONDON_NEWYORK", ref_candles(),
                 [trade_candle(11, 1.0978, 1.0979, 1.0968, 1.0970)])
    assert d.status == "SIGNAL"
    assert d.setup == "C_TREND_EXPANSION"
    assert d.direction == "SHORT"
    assert d.entry == pytest.approx(EQ)
    assert d.stop_loss == pytest.approx(EQ + R0)


# 14. branch priority A > B > C --------------------------------------------------------

def test_priority_a_beats_b_even_when_b_candle_is_earlier():
    # candle 1 qualifies for B (touch low, close inside);
    # candle 2 qualifies for A (sweep low, close back above)
    d = evaluate("EURUSD", "ASIAN_LONDON", ref_candles(),
                 [trade_candle(6, 1.0985, 1.0990, L, 1.0990),
                  trade_candle(6, 1.0985, 1.0990, 1.0975, 1.0982, minute=15)])
    assert d.status == "SIGNAL"
    assert d.setup == "A_SWEEP_REENTRY"
    assert d.entry == pytest.approx(1.0982)


def test_priority_b_beats_c_even_when_c_candle_is_earlier():
    # candle 1 qualifies for C (body above H);
    # candle 2 qualifies for B (touch high, close inside); no A anywhere
    d = evaluate("EURUSD", "ASIAN_LONDON", ref_candles(),
                 [trade_candle(6, 1.1012, 1.1022, 1.1011, 1.1020),
                  trade_candle(6, 1.1005, H, 1.1000, 1.0998, minute=15)])
    assert d.status == "SIGNAL"
    assert d.setup == "B_RANGE_REJECTION"
    assert d.entry == pytest.approx(H)


def test_priority_a_beats_c():
    d = evaluate("EURUSD", "LONDON_NEWYORK", ref_candles(),
                 [trade_candle(11, 1.1012, 1.1022, 1.1011, 1.1020),
                  trade_candle(11, 1.1005, 1.1015, 1.1000, 1.1009, minute=15)])
    assert d.setup == "A_SWEEP_REENTRY"
    assert d.direction == "SHORT"


def test_no_qualifying_setup_reason():
    d = evaluate("EURUSD", "ASIAN_LONDON", ref_candles(),
                 [trade_candle(6, 1.1000, 1.1005, 1.0995, 1.1000)])
    assert d.status == "NO_TRADE"
    assert d.reason_code == "NO_QUALIFYING_SETUP"


# 23/24/25. symbol and session coverage through the frozen engine ----------------------

@pytest.mark.parametrize("symbol", ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"])
@pytest.mark.parametrize("session", ["ASIAN_LONDON", "LONDON_NEWYORK"])
def test_supported_matrix_all_symbols_both_sessions(symbol, session):
    d = evaluate(symbol, session, ref_candles(), [trade_candle(6, 1.1000, 1.1005, 1.0995, 1.1000)])
    assert d.status == "NO_TRADE"
    assert d.strategy_id == "SESSION_TRADE_V2"
    assert d.strategy_version == "2.0.0"


def test_to_candles_preserves_ohlc():
    from ag_edgelab.contracts.market import MarketBar
    ts = datetime(2017, 6, 14, 22, 0, tzinfo=UTC)
    bars = (MarketBar(timestamp=ts, open=1.1, high=1.2, low=1.0, close=1.15),)
    candle = to_candles(bars)[0]
    assert candle.time == ts and candle.open == 1.1 and candle.high == 1.2
    assert candle.low == 1.0 and candle.close == 1.15
    assert candle.body_high == 1.15 and candle.body_low == 1.1
