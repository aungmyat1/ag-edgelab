from datetime import datetime, timedelta, timezone

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.derive import (
    FLOOR_OPEN,
    UTC,
    aggregate_bars,
    closed_derived_bars,
    derive_timeframe,
    floor_open,
    verify_lineage,
)

Z = timezone.utc
T0 = datetime(2026, 6, 1, tzinfo=Z)


def _mk(ts, o, h, l, c, v=1.0):
    return MarketBar(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


def _series(n, start=T0, step_minutes=5, base=100.0):
    return tuple(
        _mk(start + timedelta(minutes=step_minutes * i), base + i, base + i + 2, base + i - 2, base + i + 1)
        for i in range(n)
    )


def test_floor_open_aligns_to_utc_midnight():
    ts = datetime(2026, 6, 1, 13, 47, tzinfo=Z)
    assert floor_open(ts, 15) == datetime(2026, 6, 1, 13, 45, tzinfo=Z)
    assert floor_open(ts, 240) == datetime(2026, 6, 1, 12, 0, tzinfo=Z)
    assert floor_open(ts, 1440) == datetime(2026, 6, 1, 0, 0, tzinfo=Z)


def test_aggregate_bars_buckets_ohlc_and_volume():
    src = _series(6)
    bars, audit = aggregate_bars(src, "M5", "M15")
    assert len(bars) == 2
    first = bars[0]
    assert first.timestamp == T0
    assert first.open == src[0].open
    assert first.high == max(b.high for b in src[:3])
    assert first.low == min(b.low for b in src[:3])
    assert first.close == src[2].close
    assert first.volume == 3.0
    assert all(a.complete for a in audit)


def test_incomplete_bucket_is_not_emitted_and_is_documented():
    src = _series(4)  # second M15 bucket has only one M5 bar
    bars, audit = aggregate_bars(src, "M5", "M15")
    assert len(bars) == 1
    assert [a.complete for a in audit] == [True, False]
    # no forward fill: the missing timestamps are simply absent


def test_derive_timeframe_records_lineage_and_verifies():
    src = _series(24)
    bars, lineage, audit = derive_timeframe(src, "M5", "H4", source_dataset_hash="ab" * 32)
    assert lineage.source_timeframe == "M5"
    assert lineage.output_timeframe == "H4"
    assert lineage.timezone == UTC
    assert lineage.boundary_convention == FLOOR_OPEN
    assert len(lineage.output_hash) == 64
    assert verify_lineage(lineage, bars)
    assert lineage.source_dataset_hash == "ab" * 32


def test_closed_derived_bars_never_exposes_forming_bucket():
    src = _series(40)
    # asof inside the middle of an H1 bucket: only fully closed H1 bars appear
    asof = T0 + timedelta(minutes=95)
    closed = closed_derived_bars(src, "M5", "H1", asof)
    assert closed
    assert all(b.timestamp + timedelta(hours=1) <= asof for b in closed)
    assert closed[-1].timestamp == T0  # only the first hour closed by 01:35


def test_closed_derived_bars_contains_no_future_source_bars():
    src = _series(600)
    asof = src[400].timestamp
    closed = closed_derived_bars(src, "M5", "H4", asof)
    assert closed
    last_close = closed[-1].timestamp + timedelta(hours=4)
    assert last_close <= asof
    # every source slot of the last closed bucket precedes asof
    assert all(s.timestamp < asof for s in src if s.timestamp < last_close)


def test_derived_timeframes_from_gapless_source_line_up():
    src = _series(2 * 288)  # two full days of M5
    m15, _, _ = derive_timeframe(src, "M5", "M15", "s" * 64)
    h1, _, _ = derive_timeframe(src, "M5", "H1", "s" * 64)
    h4, _, _ = derive_timeframe(src, "M5", "H4", "s" * 64)
    d1, _, _ = derive_timeframe(src, "M5", "D1", "s" * 64)
    assert (len(m15), len(h1), len(h4), len(d1)) == (192, 48, 12, 2)
    assert d1[0].timestamp == h4[0].timestamp
    assert d1[0].high >= h4[0].high  # daily envelope covers the first H4 bucket


def test_derivation_is_deterministic():
    src = _series(300)
    a = derive_timeframe(src, "M5", "H1", "s" * 64)[1].output_hash
    b = derive_timeframe(src, "M5", "H1", "s" * 64)[1].output_hash
    assert a == b
