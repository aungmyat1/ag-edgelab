from __future__ import annotations

"""UTC session-window geometry for SESSION_TRADE_V2.

Contract (frozen, UTC, no DST adjustments)::

    ASIAN_LONDON    reference [D-1 22:00, D 06:00)   32 M15 bars
                    trade     [D   06:00, D 09:00)   12 M15 bars
    LONDON_NEWYORK  reference [D   06:00, D 11:00)   20 M15 bars
                    trade     [D   11:00, D 14:00)   12 M15 bars

``MarketBar.timestamp`` is the bar OPEN time (the convention used by the
upstream ``Candle.time`` fixtures).  Windows are half-open: the 06:00 candle
is NOT part of the Asian reference box.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from ag_edgelab.contracts.market import MarketBar

UTC = timezone.utc
M15 = timedelta(minutes=15)

SESSIONS: tuple[str, ...] = ("ASIAN_LONDON", "LONDON_NEWYORK")
SYMBOLS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")
BRANCHES: tuple[str, ...] = ("A_SWEEP_REENTRY", "B_RANGE_REJECTION", "C_TREND_EXPANSION")

REFERENCE_BAR_COUNT = {"ASIAN_LONDON": 32, "LONDON_NEWYORK": 20}
TRADE_BAR_COUNT = 12  # 3h of M15


@dataclass(frozen=True)
class SessionWindow:
    session: str
    trading_date: date
    reference_start: datetime
    reference_end: datetime
    trade_start: datetime
    trade_end: datetime

    @property
    def reference_bars_expected(self) -> int:
        return REFERENCE_BAR_COUNT[self.session]


def session_window(session: str, trading_date: date) -> SessionWindow:
    """Return the half-open UTC windows for one session on one trading date."""
    if session == "ASIAN_LONDON":
        # The reference session crosses midnight: for trading date D the
        # reference starts on D-1 at 22:00 UTC.
        d0 = datetime.combine(trading_date - timedelta(days=1), time(22, 0), tzinfo=UTC)
        d1 = datetime.combine(trading_date, time(6, 0), tzinfo=UTC)
        t0 = d1
        t1 = datetime.combine(trading_date, time(9, 0), tzinfo=UTC)
    elif session == "LONDON_NEWYORK":
        d0 = datetime.combine(trading_date, time(6, 0), tzinfo=UTC)
        d1 = datetime.combine(trading_date, time(11, 0), tzinfo=UTC)
        t0 = d1
        t1 = datetime.combine(trading_date, time(14, 0), tzinfo=UTC)
    else:
        raise ValueError(f"unsupported session: {session}")
    return SessionWindow(session, trading_date, d0, d1, t0, t1)


def expected_bar_times(start: datetime, end: datetime) -> tuple[datetime, ...]:
    """The exact M15 bar-open timestamps of the half-open window [start, end)."""
    times = []
    cursor = start
    while cursor < end:
        times.append(cursor)
        cursor += M15
    return tuple(times)


def slice_window(bars: tuple[MarketBar, ...], start: datetime, end: datetime) -> tuple[MarketBar, ...]:
    """Bars whose OPEN time lies in the half-open window [start, end)."""
    return tuple(b for b in bars if start <= b.timestamp < end)


@dataclass(frozen=True)
class WindowSlice:
    """Fully validated reference/trade candle sets for one session evaluation.

    ``valid`` is False when any completeness gate failed; ``reason`` carries the
    deterministic rejection code (never silently skipped).
    """

    session: str
    trading_date: date
    valid: bool
    reason: str | None
    reference_bars: tuple[MarketBar, ...]
    trade_bars: tuple[MarketBar, ...]

    @property
    def reference_count(self) -> int:
        return len(self.reference_bars)

    @property
    def trade_count(self) -> int:
        return len(self.trade_bars)


def build_window_slice(
    session: str,
    trading_date: date,
    bars: tuple[MarketBar, ...],
) -> WindowSlice:
    """Slice and completeness-gate one session cycle.

    Gates (fail closed to DATA_INVALID, never silently skipped):
      * reference window must contain EXACTLY the expected 32/20 M15 bars;
      * trade window must contain EXACTLY the expected 12 M15 bars;
      * no duplicate timestamps, strictly increasing order, valid OHLC
        (guaranteed by ``MarketBar`` validation at load time).
    """
    win = session_window(session, trading_date)
    reference = slice_window(bars, win.reference_start, win.reference_end)
    trade = slice_window(bars, win.trade_start, win.trade_end)

    if len(reference) != REFERENCE_BAR_COUNT[session]:
        return WindowSlice(
            session, trading_date, False,
            f"DATA_INVALID_REFERENCE_INCOMPLETE_{len(reference)}_OF_{REFERENCE_BAR_COUNT[session]}",
            reference, trade,
        )
    if len(trade) != TRADE_BAR_COUNT:
        return WindowSlice(
            session, trading_date, False,
            f"DATA_INVALID_TRADE_WINDOW_INCOMPLETE_{len(trade)}_OF_{TRADE_BAR_COUNT}",
            reference, trade,
        )
    stamps = [b.timestamp for b in reference + trade]
    if len(set(stamps)) != len(stamps) or stamps != sorted(stamps):
        return WindowSlice(session, trading_date, False, "DATA_INVALID_DUPLICATE_OR_UNSORTED", reference, trade)
    return WindowSlice(session, trading_date, True, None, reference, trade)
