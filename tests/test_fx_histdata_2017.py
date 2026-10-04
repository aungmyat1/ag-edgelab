"""Recovered PR #10 FX data authority — synthetic fixture tests (always run)."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fx_histdata_2017 import (BlockedDataAuthority, HoldoutAccessError,
                                              PARTITIONS, PartitionError, aggregate_m15,
                                              bars_closed_at, derive_fx_timeframe,
                                              load_histdata_m1, partition_bounds,
                                              quality_gate_m1, slice_partition,
                                              verify_source_identity)

UTC = timezone.utc


def _mk_zip(tmp_path: Path, rows: list[str], name: str = "fx.zip") -> Path:
    buf = io.StringIO()
    buf.write("\n".join(rows))
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("DAT_ASCII_TEST_M1_2017.csv", buf.getvalue())
    return path


def _row(ts: str, o=1.0, h=1.1, lo=0.9, c=1.05) -> str:
    return f"{ts};{o};{h};{lo};{c};0"


class TestLoaderTimezone:
    def test_winter_est_is_utc_plus_5(self, tmp_path):
        # 2017-01-16 10:00 America/New_York (EST, UTC-5) -> 15:00 UTC
        zip_path = _mk_zip(tmp_path, [_row("20170116 100000")])
        bars = load_histdata_m1(zip_path)
        assert bars[0].timestamp == datetime(2017, 1, 16, 15, 0, tzinfo=UTC)

    def test_summer_edt_is_utc_plus_4(self, tmp_path):
        # 2017-07-17 10:00 America/New_York (EDT, UTC-4) -> 14:00 UTC
        zip_path = _mk_zip(tmp_path, [_row("20170717 100000")])
        bars = load_histdata_m1(zip_path)
        assert bars[0].timestamp == datetime(2017, 7, 17, 14, 0, tzinfo=UTC)

    def test_bars_sorted_and_utc_aware(self, tmp_path):
        zip_path = _mk_zip(tmp_path, [_row("20170116 100100"), _row("20170116 100000")])
        bars = load_histdata_m1(zip_path)
        assert [b.timestamp.minute for b in bars] == [0, 1]
        assert all(b.timestamp.tzinfo is not None for b in bars)


class TestQualityGates:
    def _bars(self, n=5):
        t0 = datetime(2017, 3, 1, tzinfo=UTC)
        return tuple(MarketBar(timestamp=t0 + timedelta(minutes=i),
                               open=1.0, high=1.1, low=0.9, close=1.0) for i in range(n))

    def test_clean_feed_passes(self):
        report = quality_gate_m1(self._bars(), "TEST")
        assert report["m1_duplicate_timestamps"] == 0 and report["m1_rows"] == 5

    def test_duplicate_timestamp_raises(self):
        bars = self._bars()
        with pytest.raises(ValueError, match="duplicate"):
            quality_gate_m1(bars + (bars[0],), "TEST")

    def test_ohlc_violation_raises(self):
        bad = MarketBar.model_construct(timestamp=datetime(2017, 3, 2, tzinfo=UTC),
                                        open=1.0, high=0.5, low=0.9, close=1.0)
        with pytest.raises(ValueError, match="OHLC"):
            quality_gate_m1(self._bars() + (bad,), "TEST")


class TestM15Rule:
    def _minutes(self, start: datetime, count: int):
        return [MarketBar(timestamp=start + timedelta(minutes=i),
                          open=1.0 + i, high=2.0 + i, low=0.5 + i, close=1.5 + i)
                for i in range(count)]

    def test_13_of_15_emits_and_12_drops(self):
        t0 = datetime(2017, 3, 1, 10, 0, tzinfo=UTC)
        full = self._minutes(t0, 13)                        # bucket 10:00 -> kept
        short = self._minutes(t0 + timedelta(minutes=15), 12)  # bucket 10:15 -> dropped
        out = aggregate_m15(tuple(full + short))
        assert [b.timestamp for b in out] == [t0]

    def test_never_forward_filled(self):
        t0 = datetime(2017, 3, 1, 10, 0, tzinfo=UTC)
        bars = self._minutes(t0, 15) + self._minutes(t0 + timedelta(minutes=30), 15)
        out = aggregate_m15(tuple(bars))
        # the 10:15 bucket is simply absent — no synthetic bar
        assert [b.timestamp for b in out] == [t0, t0 + timedelta(minutes=30)]

    def test_ohlc_uses_present_minutes_only(self):
        t0 = datetime(2017, 3, 1, 10, 0, tzinfo=UTC)
        out = aggregate_m15(tuple(self._minutes(t0, 15)))
        assert out[0].open == 1.0 and out[0].close == 1.5 + 14
        assert out[0].high == 2.0 + 14 and out[0].low == 0.5


class TestPartitions:
    def test_bounds(self):
        dev = partition_bounds("DEVELOPMENT")
        assert dev == (datetime(2017, 1, 1, tzinfo=UTC), datetime(2017, 9, 1, tzinfo=UTC))
        assert set(PARTITIONS) == {"DEVELOPMENT", "OOS", "SEALED_HOLDOUT"}

    def test_unknown_role_raises(self):
        with pytest.raises(PartitionError):
            partition_bounds("PRODUCTION")

    def test_holdout_fails_closed(self):
        with pytest.raises(HoldoutAccessError):
            slice_partition((), "SEALED_HOLDOUT")

    def test_dev_slice_half_open(self):
        bars = tuple(MarketBar(timestamp=t, open=1, high=1, low=1, close=1) for t in (
            datetime(2016, 12, 31, 23, 59, tzinfo=UTC),
            datetime(2017, 1, 1, tzinfo=UTC),
            datetime(2017, 8, 31, 23, 59, tzinfo=UTC),
            datetime(2017, 9, 1, tzinfo=UTC)))
        dev = slice_partition(bars, "DEVELOPMENT")
        assert [b.timestamp.year for b in dev] == [2017, 2017]
        assert dev[-1].timestamp == datetime(2017, 8, 31, 23, 59, tzinfo=UTC)


class TestIdentity:
    def test_mismatch_is_blocked_data_authority(self, tmp_path):
        path = tmp_path / "HISTDATA_COM_ASCII_EURUSD_M1_2017.zip"
        path.write_bytes(b"not the pinned bytes")
        with pytest.raises(BlockedDataAuthority, match="BLOCKED_DATA_AUTHORITY"):
            verify_source_identity(path, "EURUSD")

    def test_unknown_symbol_is_blocked(self, tmp_path):
        path = tmp_path / "x.zip"
        path.write_bytes(b"x")
        with pytest.raises(BlockedDataAuthority):
            verify_source_identity(path, "BTCUSD")


def _m15_run(start: datetime, count: int, gap_indices=()):
    bars = []
    for i in range(count):
        if i in gap_indices:
            continue
        bars.append(MarketBar(timestamp=start + timedelta(minutes=15 * i),
                              open=1.0, high=1.2 + 0.001 * i, low=0.8, close=1.1))
    return tuple(bars)


class TestMtfDerivation:
    def test_h1_coverage_rule_3_of_4(self):
        t0 = datetime(2017, 3, 1, 10, 0, tzinfo=UTC)
        # hour 10: 4/4 slots, hour 11: 3/4 (kept), hour 12: 2/4 (dropped)
        m15 = _m15_run(t0, 12, gap_indices=(5, 9, 10))
        h1, lineage = derive_fx_timeframe(m15, "H1", "TEST")
        assert [b.timestamp for b in h1] == [t0, t0 + timedelta(hours=1)]
        assert "no forward fill" in lineage.coverage_rule

    def test_d1_coverage_allows_72_of_96(self):
        t0 = datetime(2017, 3, 1, 0, 0, tzinfo=UTC)
        m15 = _m15_run(t0, 96, gap_indices=tuple(range(72, 96)))  # exactly 72 present
        d1, _ = derive_fx_timeframe(m15, "D1", "TEST")
        assert len(d1) == 1
        m15_short = _m15_run(t0, 96, gap_indices=tuple(range(71, 96)))  # 71 present
        d1_short, _ = derive_fx_timeframe(m15_short, "D1", "TEST")
        assert len(d1_short) == 0

    def test_lineage_hashes_deterministic_and_linked(self):
        t0 = datetime(2017, 3, 1, 0, 0, tzinfo=UTC)
        m15 = _m15_run(t0, 96)
        _, a = derive_fx_timeframe(m15, "H4", "TEST")
        _, b = derive_fx_timeframe(m15, "H4", "TEST")
        assert a.source_hash == b.source_hash and a.output_hash == b.output_hash
        assert a.source_timeframe == "M15"

    def test_unsupported_timeframe_rejected(self):
        with pytest.raises(ValueError):
            derive_fx_timeframe((), "W1", "TEST")


class TestAntiLookahead:
    def test_bars_closed_at_requires_full_close(self):
        t0 = datetime(2017, 3, 1, 0, 0, tzinfo=UTC)
        m15 = _m15_run(t0, 8)
        h1, _ = derive_fx_timeframe(m15, "H1", "TEST")
        # at 00:59 the 00:00 H1 bar is NOT closed
        assert bars_closed_at(h1, "H1", t0 + timedelta(minutes=59)) == ()
        assert len(bars_closed_at(h1, "H1", t0 + timedelta(hours=1))) == 1
        assert len(bars_closed_at(h1, "H1", t0 + timedelta(hours=2))) == 2
