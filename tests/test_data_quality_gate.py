from datetime import datetime, timedelta, timezone

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.quality import QualityVerdict, audit_bars

Z = timezone.utc
T0 = datetime(2026, 6, 1, tzinfo=Z)


def _series(indices, base=100.0):
    return tuple(
        MarketBar(
            timestamp=T0 + timedelta(minutes=5 * i),
            open=base + i,
            high=base + i + 2,
            low=base + i - 2,
            close=base + i + 1,
            volume=1.0,
        )
        for i in indices
    )


def test_gapless_series_passes():
    report = audit_bars(_series(range(288)), "M5", symbol="BTCUSDT", venue="BYBIT")
    assert report.verdict == QualityVerdict.PASS
    assert report.missing_slots == 0
    assert report.gap_audit == "NO_GAPS"
    assert report.forward_filled is False


def test_missing_bars_are_documented_not_filled():
    indices = [i for i in range(288) if not (100 <= i < 110 or i == 200)]
    report = audit_bars(_series(indices), "M5", symbol="BTCUSDT", venue="BYBIT")
    assert report.verdict == QualityVerdict.PASS_WITH_DOCUMENTED_GAPS
    assert report.missing_slots == 11
    assert len(report.gap_records) == 2
    assert "11 missing slots" in report.gap_audit
    assert all(b.timestamp != T0 + timedelta(minutes=5 * 105) for b in _series(indices))


def test_duplicate_timestamps_fail():
    bars = list(_series(range(10)))
    bars.append(bars[-1])  # trailing duplicate of the last timestamp
    report = audit_bars(tuple(bars), "M5", symbol="BTCUSDT", venue="BYBIT")
    assert report.verdict == QualityVerdict.FAIL
    assert any(i.code == "DUPLICATE_TIMESTAMP" for i in report.issues)


def test_non_monotonic_fails():
    bars = list(_series(range(10)))
    bars[3], bars[4] = bars[4], bars[3]
    report = audit_bars(tuple(bars), "M5", symbol="BTCUSDT", venue="BYBIT")
    assert report.verdict == QualityVerdict.FAIL
    assert any(i.code == "NON_MONOTONIC_TIMESTAMP" for i in report.issues)


def test_nonpositive_price_fails():
    bars = list(_series(range(10)))
    bad = MarketBar(timestamp=bars[4].timestamp, open=0.0, high=2.0, low=0.0, close=1.0, volume=1.0)
    bars[4] = bad
    report = audit_bars(tuple(bars), "M5", symbol="BTCUSDT", venue="BYBIT")
    assert report.verdict == QualityVerdict.FAIL
    assert any(i.code == "NONPOSITIVE_PRICE" for i in report.issues)


def test_off_grid_timestamp_fails():
    bars = list(_series(range(10)))
    shifted = MarketBar(
        timestamp=bars[4].timestamp + timedelta(minutes=2),
        open=bars[4].open, high=bars[4].high, low=bars[4].low, close=bars[4].close, volume=1.0,
    )
    bars[4] = shifted
    report = audit_bars(tuple(bars), "M5", symbol="BTCUSDT", venue="BYBIT")
    assert report.verdict == QualityVerdict.FAIL
    assert any(i.code == "TIMEFRAME_MISALIGNED" for i in report.issues)


def test_coverage_shortfall_fails():
    report = audit_bars(
        _series(range(10)), "M5", symbol="BTCUSDT", venue="BYBIT",
        expected_start=T0 - timedelta(hours=2),
    )
    assert report.verdict == QualityVerdict.FAIL
    assert any(i.code == "COVERAGE_START_SHORTFALL" for i in report.issues)


def test_identity_recorded():
    report = audit_bars(_series(range(10)), "M5", symbol="BTCUSDT", venue="BYBIT")
    assert report.identity == {"symbol": "BTCUSDT", "venue": "BYBIT"}


def test_massive_gap_fails_gate():
    indices = list(range(50)) + list(range(2500, 2600))
    report = audit_bars(_series(indices), "M5", symbol="BTCUSDT", venue="BYBIT")
    assert report.verdict == QualityVerdict.FAIL
    assert any(i.code == "GAP_BUDGET_EXCEEDED" for i in report.issues)
