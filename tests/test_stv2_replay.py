from __future__ import annotations

"""Focused tests: fill semantics, partial-exit accounting, same-bar policy.

Geometry: box H=1.1010, L=1.0980, R0=0.00075, EQ=1.0995 (EURUSD-like).
B LONG: limit entry L=1.0980, stop 1.09725, TP1 (75%) 1.0408 -> wait:
targets are computed from R=0.00075: TP1 = L + 4R = 1.0980+0.0030 = 1.1010,
runner = L + 5R = 1.0980+0.00375 = 1.10175.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from ag_edgelab.campaigns.session_trade_v2.adapter import adapt_decision
from ag_edgelab.campaigns.session_trade_v2.frozen import Candle, Decision, evaluate
from ag_edgelab.campaigns.session_trade_v2.replay import CampaignReplayEngine
from ag_edgelab.campaigns.session_trade_v2.windows import session_window
from ag_edgelab.contracts.market import MarketBar

UTC = timezone.utc
H, L = 1.1010, 1.0980
R0 = 0.25 * (H - L)
EQ = (H + L) / 2
TD = date(2017, 6, 15)


def m15(ts, o, h, l, c):
    return MarketBar(timestamp=ts, open=o, high=h, low=l, close=c)


def ref_candles():
    t0 = datetime(2017, 6, 14, 22, 0, tzinfo=UTC)
    return (
        Candle(time=t0, open=1.1000, high=H, low=L, close=1.1000),
        Candle(time=t0 + timedelta(minutes=15), open=1.1000, high=1.1005, low=1.0985, close=1.1000),
    )


def trade_candle(hour, o, h, l, c, minute=0):
    return Candle(time=datetime(2017, 6, 15, hour, minute, tzinfo=UTC), open=o, high=h, low=l, close=c)


def b_long_decision():
    return evaluate("EURUSD", "ASIAN_LONDON", ref_candles(),
                    [trade_candle(6, 1.0985, 1.0990, L, 1.0990)])


def a_long_decision():
    return evaluate("EURUSD", "ASIAN_LONDON", ref_candles(),
                    [trade_candle(6, 1.0985, 1.0990, 1.0975, 1.0982)])


def window_bars(start: datetime, count: int):
    """`count` flat continuation bars, the first AT `start` (bar-open time)."""
    bars = []
    price = 1.1000
    for i in range(count):
        ts = start + timedelta(minutes=15 * i)
        bars.append(m15(ts, price, price + 0.0002, price - 0.0002, price))
    return tuple(bars)


def bars_after(ts: datetime, count: int):
    """Continuation bars strictly after `ts` (no duplicate timestamps)."""
    return window_bars(ts + timedelta(minutes=15), count)


def replay(decision, symbol, session, extra_bars, trading_date=TD):
    ev = adapt_decision(symbol, session_window(session, trading_date), decision,
                        trading_date.isoformat())
    assert ev.intent is not None, f"expected an intent, got {ev.outcome}/{ev.reason}"
    bars = (extra_bars,)
    engine = CampaignReplayEngine({symbol: extra_bars})
    return engine.execute_one(ev.intent, ev.intent_metadata)


# 17. next-executable-price behavior for A ------------------------------------------

def test_a_market_entry_fills_at_next_bar_open_not_signal_close():
    d = a_long_decision()
    # signal candle: 06:00 (open time), closes 06:15 at 1.0982
    signal_close = datetime(2017, 6, 15, 6, 15, tzinfo=UTC)
    next_bar = m15(signal_close, 1.0985, 1.0988, 1.0980, 1.0984)  # opens at 1.0985
    after = bars_after(signal_close, 20)
    trade = replay(d, "EURUSD", "ASIAN_LONDON", (next_bar,) + after)
    assert trade.filled
    assert trade.entry_price == pytest.approx(1.0985)   # next bar OPEN
    assert trade.entry_price != pytest.approx(1.0982)   # NOT the signal close
    assert trade.entry_time == signal_close


# 18. no same-bar lookahead -----------------------------------------------------------

def test_a_entry_cannot_fill_on_the_signal_bar_itself():
    d = a_long_decision()  # signal candle 06:00 closes 06:15
    # bars START at the signal candle itself: replay must skip it
    signal_bar = m15(datetime(2017, 6, 15, 6, 0, tzinfo=UTC), 1.0985, 1.0990, 1.0975, 1.0982)
    next_bar = m15(datetime(2017, 6, 15, 6, 15, tzinfo=UTC), 1.0983, 1.0986, 1.0980, 1.0984)
    after = bars_after(datetime(2017, 6, 15, 6, 15, tzinfo=UTC), 20)
    trade = replay(d, "EURUSD", "ASIAN_LONDON", (signal_bar, next_bar) + after)
    assert trade.entry_time == datetime(2017, 6, 15, 6, 15, tzinfo=UTC)


def test_b_limit_cannot_fill_on_the_signal_candle():
    d = b_long_decision()  # signal candle 06:00 touches L and closes 06:15
    # the limit at L was touched DURING the signal candle, but the decision
    # only exists at the candle close -> no fill on the signal bar
    signal_bar = m15(datetime(2017, 6, 15, 6, 0, tzinfo=UTC), 1.0985, 1.0990, L, 1.0990)
    # all later bars stay above L -> never fills
    after = bars_after(datetime(2017, 6, 15, 6, 15, tzinfo=UTC), 12)
    trade = replay(d, "EURUSD", "ASIAN_LONDON", (signal_bar,) + after)
    assert trade.status == "EXPIRED"
    assert trade.entry_price is None


# 15. limit signal but unfilled --------------------------------------------------------

def test_b_limit_unfilled_expires_not_a_loss():
    d = b_long_decision()
    signal_close = datetime(2017, 6, 15, 6, 15, tzinfo=UTC)
    # 11 workable bars (06:15..08:45), all above the limit L
    bars = window_bars(signal_close, 11)
    trade = replay(d, "EURUSD", "ASIAN_LONDON", bars)
    assert trade.status == "EXPIRED"
    assert trade.gross_r is None or trade.gross_r == 0
    assert trade.filled is False


def test_b_limit_unfilled_when_touch_occurs_after_expiry():
    d = b_long_decision()
    signal_close = datetime(2017, 6, 15, 6, 15, tzinfo=UTC)
    # 11 workable bars above L, then the 12th (09:00, outside the trade
    # window) plunges through L -> must still NOT fill
    bars = list(window_bars(signal_close, 11))
    late = m15(datetime(2017, 6, 15, 9, 0, tzinfo=UTC), 1.0970, 1.0975, 1.0960, 1.0965)
    trade = replay(d, "EURUSD", "ASIAN_LONDON", tuple(bars) + (late,))
    assert trade.status == "EXPIRED"


def test_b_limit_fills_when_touched_within_window():
    d = b_long_decision()
    signal_close = datetime(2017, 6, 15, 6, 15, tzinfo=UTC)
    bars = list(window_bars(signal_close, 11))
    # second workable bar dips into L
    bars[1] = m15(bars[1].timestamp, 1.0990, 1.0996, L - 0.0001, 1.0995)
    after = bars_after(bars[-1].timestamp, 30)
    trade = replay(d, "EURUSD", "ASIAN_LONDON", tuple(bars) + after)
    assert trade.filled
    assert trade.entry_price == pytest.approx(L)
    assert trade.entry_time == bars[1].timestamp


# 16. fill expiry counting --------------------------------------------------------------

def test_expired_and_unfilled_are_distinct_statuses():
    d = b_long_decision()
    # never-workable: signal on the final trade-window candle (08:45)
    late_signal = evaluate("EURUSD", "ASIAN_LONDON", ref_candles(),
                           [trade_candle(8, 1.0985, 1.0990, L, 1.0990, minute=45)])
    assert late_signal.setup == "B_RANGE_REJECTION"
    ev = adapt_decision("EURUSD", session_window("ASIAN_LONDON", TD), late_signal, TD.isoformat())
    assert ev.intent is None            # no working bars remain in the window
    assert ev.intent_metadata["never_workable"] is True
    assert ev.workable_limit_bars == 0


# 19. partial 4R accounting --------------------------------------------------------------

def test_tp1_partial_books_75_percent_at_4r():
    d = b_long_decision()  # entry L, stop L-R0, TP1 = L+4R0 = 1.1010
    signal_close = datetime(2017, 6, 15, 6, 15, tzinfo=UTC)
    bars = list(window_bars(signal_close, 11))
    bars[0] = m15(bars[0].timestamp, 1.0990, 1.0995, 1.0985, 1.0995)
    # fill bar (06:15): dips to L (fill) but stays below TP1
    bars[0] = m15(bars[0].timestamp, 1.0990, 1.0995, L, 1.0995)
    # next bar (06:30): rallies through TP1 to 1.1015 (past 4R), closes below 5R
    bars[1] = m15(bars[1].timestamp, 1.0995, 1.1015, 1.0990, 1.1005)
    # then price collapses to breakeven entry -> runner exits at BE
    bars[2] = m15(bars[2].timestamp, 1.1005, 1.1008, L - 0.0002, 1.0985)
    after = bars_after(bars[-1].timestamp, 30)
    trade = replay(d, "EURUSD", "ASIAN_LONDON", tuple(bars) + after)
    assert trade.status == "FILLED_CLOSED"
    assert trade.tp1_4r_hit is True
    assert trade.runner_breakeven is True
    # gross = 0.75*4R + 0.25*0R = 3.0R
    assert trade.gross_r == pytest.approx(3.0, abs=1e-9)
    assert trade.exit_reason == "STOP"


# 20. runner breakeven accounting ---------------------------------------------------------

def test_runner_breakeven_after_tp1_when_both_be_and_5r_in_same_bar():
    d = b_long_decision()
    signal_close = datetime(2017, 6, 15, 6, 15, tzinfo=UTC)
    bars = list(window_bars(signal_close, 11))
    bars[0] = m15(bars[0].timestamp, 1.0990, 1.0995, L, 1.0995)      # fill
    bars[1] = m15(bars[1].timestamp, 1.0995, 1.1015, 1.0990, 1.1005)  # TP1 4R hit
    # next bar touches BOTH breakeven (L) and the 5R target (1.10175):
    # conservative policy must resolve to breakeven, not the favorable 5R
    bars[2] = m15(bars[2].timestamp, 1.1005, L + 5 * R0 + 1e-9, L - 0.0001, 1.0985)
    after = bars_after(bars[-1].timestamp, 30)
    trade = replay(d, "EURUSD", "ASIAN_LONDON", tuple(bars) + after)
    assert trade.runner_breakeven is True
    assert trade.runner_5r_hit is False
    assert trade.gross_r == pytest.approx(3.0, abs=1e-9)
    assert trade.same_bar_ambiguities >= 1   # BE vs 5R ambiguity counted


# 21. full 4.25R winner accounting ----------------------------------------------------------

def test_full_winner_books_4_25_r():
    d = b_long_decision()
    signal_close = datetime(2017, 6, 15, 6, 15, tzinfo=UTC)
    bars = list(window_bars(signal_close, 11))
    bars[0] = m15(bars[0].timestamp, 1.0990, 1.0995, L, 1.0995)               # fill
    bars[1] = m15(bars[1].timestamp, 1.0995, 1.1012, 1.0990, 1.1011)          # TP1 only
    bars[2] = m15(bars[2].timestamp, 1.1011, L + 5 * R0 + 0.0002, 1.1009, 1.1016)  # 5R runner
    after = bars_after(bars[-1].timestamp, 30)
    trade = replay(d, "EURUSD", "ASIAN_LONDON", tuple(bars) + after)
    assert trade.exit_reason == "TARGETS_COMPLETE"
    assert trade.tp1_4r_hit and trade.runner_5r_hit
    assert trade.gross_r == pytest.approx(0.75 * 4.0 + 0.25 * 5.0, abs=1e-9)  # 4.25R


def test_full_stop_loss_books_minus_1r():
    d = b_long_decision()
    signal_close = datetime(2017, 6, 15, 6, 15, tzinfo=UTC)
    bars = list(window_bars(signal_close, 11))
    bars[0] = m15(bars[0].timestamp, 1.0990, 1.0995, L, 1.0995)   # fill
    bars[1] = m15(bars[1].timestamp, 1.0990, 1.0992, L - R0 - 0.0005, 1.0973)  # stop
    after = bars_after(bars[-1].timestamp, 30)
    trade = replay(d, "EURUSD", "ASIAN_LONDON", tuple(bars) + after)
    assert trade.exit_reason == "STOP"
    assert trade.gross_r == pytest.approx(-1.0, abs=1e-9)


# same-bar stop-vs-target conservative policy ----------------------------------------------

def test_same_bar_stop_and_tp1_resolves_to_stop_and_counts_ambiguity():
    d = b_long_decision()
    signal_close = datetime(2017, 6, 15, 6, 15, tzinfo=UTC)
    bars = list(window_bars(signal_close, 11))
    bars[0] = m15(bars[0].timestamp, 1.0990, 1.0995, L, 1.0995)   # fill
    # one bar spans BOTH the stop (L-R0) and TP1 (L+4R0): stop wins
    bars[1] = m15(bars[1].timestamp, 1.0990, L + 4 * R0 + 0.0001, L - R0 - 0.0001, 1.0980)
    after = bars_after(bars[-1].timestamp, 30)
    trade = replay(d, "EURUSD", "ASIAN_LONDON", tuple(bars) + after)
    assert trade.exit_reason == "STOP"
    assert trade.gross_r == pytest.approx(-1.0, abs=1e-9)
    assert trade.same_bar_ambiguities == 1


def test_limit_fill_bar_target_touch_is_suppressed_and_counted():
    d = b_long_decision()
    signal_close = datetime(2017, 6, 15, 6, 15, tzinfo=UTC)
    bars = list(window_bars(signal_close, 11))
    # fill bar touches L AND would have reached TP1 (L+4R0): the fill instant
    # is unknown, so the target touch cannot be assumed -> suppressed
    bars[0] = m15(bars[0].timestamp, 1.1012, L + 4 * R0 + 0.0002, L, 1.0995)
    after = bars_after(bars[-1].timestamp, 30)
    trade = replay(d, "EURUSD", "ASIAN_LONDON", tuple(bars) + after)
    assert trade.filled
    assert trade.entry_time == bars[0].timestamp
    assert trade.tp1_4r_hit is False                 # suppressed on the fill bar
    assert trade.same_bar_ambiguities == 1


def test_stop_on_limit_fill_bar_is_deterministic_worst_case():
    d = b_long_decision()
    signal_close = datetime(2017, 6, 15, 6, 15, tzinfo=UTC)
    bars = list(window_bars(signal_close, 11))
    # fill bar plunges through the stop: stop-out on the fill bar
    bars[0] = m15(bars[0].timestamp, 1.0990, 1.0992, L - R0 - 0.001, 1.0970)
    after = bars_after(bars[-1].timestamp, 30)
    trade = replay(d, "EURUSD", "ASIAN_LONDON", tuple(bars) + after)
    assert trade.status == "FILLED_CLOSED"
    assert trade.exit_reason == "STOP"
    assert trade.gross_r == pytest.approx(-1.0, abs=1e-9)


def test_open_at_end_is_censored_not_counted_as_closed():
    d = b_long_decision()
    signal_close = datetime(2017, 6, 15, 6, 15, tzinfo=UTC)
    bars = list(window_bars(signal_close, 3))
    bars[0] = m15(bars[0].timestamp, 1.0990, 1.0995, L, 1.0995)  # fill, no resolution
    trade = replay(d, "EURUSD", "ASIAN_LONDON", tuple(bars))
    assert trade.status == "FILLED_OPEN_AT_END"
    assert trade.closed is False
