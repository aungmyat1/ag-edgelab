from __future__ import annotations

"""Focused tests: UTC session windows, midnight-crossing assignment, bar counts."""

from datetime import date, datetime, timedelta, timezone

import pytest

from ag_edgelab.campaigns.session_trade_v2.dataset import evaluable_trading_dates, partition_bounds
from ag_edgelab.campaigns.session_trade_v2.windows import (
    REFERENCE_BAR_COUNT,
    TRADE_BAR_COUNT,
    build_window_slice,
    expected_bar_times,
    session_window,
)
from ag_edgelab.contracts.market import MarketBar

UTC = timezone.utc


def bar(ts, o, h, l, c):
    return MarketBar(timestamp=ts, open=o, high=h, low=l, close=c)


def grid(start: datetime, count: int, price=1.0):
    """`count` consecutive M15 bars starting at `start` (open time)."""
    return tuple(
        bar(start + timedelta(minutes=15 * i), price, price, price, price)
        for i in range(count)
    )


# 2. Asian session midnight assignment ---------------------------------------------

def test_asian_london_reference_crosses_midnight_to_previous_day():
    win = session_window("ASIAN_LONDON", date(2017, 6, 14))
    assert win.reference_start == datetime(2017, 6, 13, 22, 0, tzinfo=UTC)
    assert win.reference_end == datetime(2017, 6, 14, 6, 0, tzinfo=UTC)
    assert win.trade_start == datetime(2017, 6, 14, 6, 0, tzinfo=UTC)
    assert win.trade_end == datetime(2017, 6, 14, 9, 0, tzinfo=UTC)


def test_asian_reference_is_half_open_0600_candle_excluded():
    d = date(2017, 6, 14)
    win = session_window("ASIAN_LONDON", d)
    times = expected_bar_times(win.reference_start, win.reference_end)
    assert times[0] == datetime(2017, 6, 13, 22, 0, tzinfo=UTC)
    assert times[-1] == datetime(2017, 6, 14, 5, 45, tzinfo=UTC)   # last reference bar
    assert datetime(2017, 6, 14, 6, 0, tzinfo=UTC) not in times    # 06:00 NOT in the box
    assert datetime(2017, 6, 14, 5, 45, tzinfo=UTC) in times


def test_london_newyork_windows():
    win = session_window("LONDON_NEWYORK", date(2017, 6, 14))
    assert win.reference_start == datetime(2017, 6, 14, 6, 0, tzinfo=UTC)
    assert win.reference_end == datetime(2017, 6, 14, 11, 0, tzinfo=UTC)
    assert win.trade_start == datetime(2017, 6, 14, 11, 0, tzinfo=UTC)
    assert win.trade_end == datetime(2017, 6, 14, 14, 0, tzinfo=UTC)


# 3. exact 32-bar Asian reference completeness --------------------------------------

def test_asian_reference_expects_exactly_32_bars():
    assert REFERENCE_BAR_COUNT["ASIAN_LONDON"] == 32
    win = session_window("ASIAN_LONDON", date(2017, 3, 1))
    assert len(expected_bar_times(win.reference_start, win.reference_end)) == 32


# 4. exact 20-bar London reference completeness -------------------------------------

def test_london_reference_expects_exactly_20_bars():
    assert REFERENCE_BAR_COUNT["LONDON_NEWYORK"] == 20
    win = session_window("LONDON_NEWYORK", date(2017, 3, 1))
    assert len(expected_bar_times(win.reference_start, win.reference_end)) == 20


def test_trade_windows_expect_12_bars():
    for session in ("ASIAN_LONDON", "LONDON_NEWYORK"):
        win = session_window(session, date(2017, 3, 1))
        assert len(expected_bar_times(win.trade_start, win.trade_end)) == TRADE_BAR_COUNT == 12


def test_complete_session_slice_is_valid():
    d = date(2017, 6, 14)
    asian = session_window("ASIAN_LONDON", d)
    bars = grid(asian.reference_start, 32 + 12)  # ref (22:00-06:00) + trade (06:00-09:00)
    result = build_window_slice("ASIAN_LONDON", d, bars)
    assert result.valid is True
    assert result.reference_count == 32
    assert result.trade_count == 12


def test_missing_reference_bar_is_data_invalid_not_silently_skipped():
    d = date(2017, 6, 14)
    asian = session_window("ASIAN_LONDON", d)
    bars = list(grid(asian.reference_start, 44))
    del bars[5]  # hole inside the reference window
    result = build_window_slice("ASIAN_LONDON", d, tuple(bars))
    assert result.valid is False
    assert result.reason == "DATA_INVALID_REFERENCE_INCOMPLETE_31_OF_32"


def test_missing_trade_bar_is_data_invalid():
    d = date(2017, 6, 14)
    asian = session_window("ASIAN_LONDON", d)
    bars = list(grid(asian.reference_start, 44))
    del bars[35]  # hole inside the trade window
    result = build_window_slice("ASIAN_LONDON", d, tuple(bars))
    assert result.valid is False
    assert result.reason.startswith("DATA_INVALID_TRADE_WINDOW_INCOMPLETE")


def test_gold_style_winter_asian_break_is_data_invalid():
    # XAUUSD winter: 22:00-23:00 UTC is the OTC maintenance break -> four
    # reference bars missing -> the session must fail closed.
    d = date(2017, 1, 11)  # US winter time
    asian = session_window("ASIAN_LONDON", d)
    bars = list(grid(asian.reference_start, 44))
    # remove the 22:00, 22:15, 22:30, 22:45 bars
    bars = [b for b in bars if b.timestamp.hour != 22]
    result = build_window_slice("ASIAN_LONDON", d, tuple(bars))
    assert result.valid is False
    assert "28_OF_32" in result.reason


# 25. both session cycles / partition date logic ------------------------------------

def test_evaluable_dates_never_straddle_partition_boundaries():
    bounds = partition_bounds("DEVELOPMENT")
    dates = evaluable_trading_dates(bounds)
    assert dates[0] == date(2017, 1, 2)   # Asian ref needs Jan 1 22:00
    assert dates[-1] == date(2017, 8, 31)  # LN trade ends 14:00 same day
    for d in dates:
        assert datetime.combine(d - timedelta(days=1), datetime.min.time(), tzinfo=UTC).replace(
            hour=22
        ) >= bounds[0]
        assert datetime.combine(d, datetime.min.time(), tzinfo=UTC).replace(hour=14) <= bounds[1]


def test_oos_dates_do_not_overlap_dev_dates():
    dev = evaluable_trading_dates(partition_bounds("DEVELOPMENT"))
    oos = evaluable_trading_dates(partition_bounds("OOS"))
    assert set(dev).isdisjoint(set(oos))
    assert oos[0] == date(2017, 9, 2)
    assert oos[-1] == date(2017, 11, 30)
