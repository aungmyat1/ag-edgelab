from __future__ import annotations

"""Focused tests: frozen friction authority + M1->M15 dataset pipeline.

Friction: round-turn (not per-leg) cost accounting, inverse-risk R scaling,
USDJPY USD-commission conversion, gold-specific (non-pip) costs, fail-closed
on unknown symbol / non-positive risk, the EdgeLab stress-grid transform, and
evidence provenance strings.

Dataset: the >=13/15 M15 rule, first/last-minute OHLC semantics, bucket
independence, America/New_York -> UTC normalization including the DST
spring-forward offset change, duplicate and OHLC-violation fail-closed gates,
and the source-hash-bearing quality report.
"""

import hashlib
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ag_edgelab.campaigns.session_trade_v2 import friction as fr
from ag_edgelab.campaigns.session_trade_v2 import dataset as ds
from ag_edgelab.friction.model import apply_normalized_r_stress
from ag_edgelab.contracts.market import MarketBar

UTC = timezone.utc
M15 = timedelta(minutes=15)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def m1(ts, o=1.05, h=1.06, l=1.04, c=1.05):
    return MarketBar(timestamp=ts, open=o, high=h, low=l, close=c)


def row(ts, o, h, l, c):
    """HistData ASCII row: wall-clock America/New_York."""
    return f"{ts:%Y%m%d %H%M%S};{o:.5f};{h:.5f};{l:.5f};{c:.5f};0\n"


def write_zip(path: Path, rows):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("DAT_ASCII_EURUSD_M1_2017.csv", "".join(rows))
    return path


def ny(year, month, day, hour, minute=0):
    """Wall-clock datetime in America/New_York (what the file encodes)."""
    from zoneinfo import ZoneInfo
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("America/New_York"))


# ---------------------------------------------------------------------------
# friction: round-turn accounting
# ---------------------------------------------------------------------------

def test_all_four_symbols_have_frozen_friction_with_evidence():
    for symbol in ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD"):
        model = fr.SYMBOL_FRICTION[symbol]
        assert model.symbol == symbol
        assert model.evidence and len(model.evidence) > 40
        assert model.round_turn_cost(1.0) > 0


def test_cost_is_round_turn_not_per_leg():
    # A 75/25 partial exit crosses the spread once per unit round turn: the
    # per-unit RT cost must NOT be multiplied by the number of exit legs.
    model = fr.SYMBOL_FRICTION["EURUSD"]
    rt = model.round_turn_cost(1.1000)
    assert rt == pytest.approx(model.spread_rt + model.slippage_rt + 7.0 / 100_000.0)
    # and in R: identical for one trade regardless of leg structure
    assert fr.friction_r("EURUSD", 1.1000, 0.00075) == pytest.approx(rt / 0.00075)


def test_friction_r_scales_inversely_with_risk():
    half = fr.friction_r("EURUSD", 1.1000, 0.00075)
    full = fr.friction_r("EURUSD", 1.1000, 0.00150)
    assert full == pytest.approx(half / 2)


def test_usdjpy_commission_converted_from_usd():
    # $7/lot RT on 100k USD notional at price 112.00 JPY/USD
    model = fr.SYMBOL_FRICTION["USDJPY"]
    commission_price = 7.0 * 112.00 / 100_000.0
    expected = 0.4 * 0.01 + commission_price + 2 * 0.1 * 0.01
    assert model.round_turn_cost(112.00) == pytest.approx(expected)


def test_xauusd_uses_gold_specific_costs_not_fx_pips():
    model = fr.SYMBOL_FRICTION["XAUUSD"]
    assert model.spread_rt == pytest.approx(0.30)     # measured p95-basis $/oz
    assert model.slippage_rt == pytest.approx(0.10)   # $0.05/oz per side
    # commission $7/lot on a 100 oz lot -> $0.07/oz
    assert model.round_turn_cost(1250.0) == pytest.approx(0.30 + 0.07 + 0.10)
    # against a $2.25 risk (0.25 * $9 range) friction is ~0.21R
    assert fr.friction_r("XAUUSD", 1250.0, 2.25) == pytest.approx((0.30 + 0.07 + 0.10) / 2.25)


def test_unknown_symbol_fails_closed():
    with pytest.raises(fr.FrictionUnqualified):
        fr.friction_r("AUDCAD", 1.0, 0.001)


@pytest.mark.parametrize("risk", [0.0, -0.001])
def test_non_positive_risk_fails_closed(risk):
    with pytest.raises(fr.FrictionUnqualified):
        fr.friction_r("EURUSD", 1.10, risk)


def test_stress_grid_matches_edgelab_transform():
    net, cost = 0.8, 0.15
    for m in fr.STRESS_MULTIPLIERS:
        assert fr.stressed_net_r(net, cost, m) == pytest.approx(apply_normalized_r_stress(net, cost, m))
    # 1.0x preserves the baseline net exactly; extra stress only removes R
    assert fr.stressed_net_r(net, cost, 1.0) == pytest.approx(net)
    assert fr.stressed_net_r(net, cost, 1.5) == pytest.approx(net - 0.5 * cost)
    assert fr.stressed_net_r(net, cost, 1.5) < fr.stressed_net_r(net, cost, 1.25) < net


def test_scenario_view_sums_to_flat_friction():
    scen = fr.friction_scenario_r("EURUSD", 1.1000, 0.00075)
    assert "EURUSD" in scen.scenario_id
    assert scen.total_cost_r == pytest.approx(fr.friction_r("EURUSD", 1.1000, 0.00075))


# ---------------------------------------------------------------------------
# dataset: M1 -> M15 aggregation
# ---------------------------------------------------------------------------

def test_m15_requires_13_of_15_minutes():
    t0 = datetime(2017, 6, 15, 6, 0, tzinfo=UTC)
    thirteen = [m1(t0 + timedelta(minutes=i)) for i in range(13)]
    out = ds.aggregate_m15(tuple(thirteen))
    assert len(out) == 1 and out[0].timestamp == t0
    twelve = [m1(t0 + timedelta(minutes=i)) for i in range(12)]
    assert ds.aggregate_m15(tuple(twelve)) == ()


def test_m15_ohlc_first_and_last_minute_semantics():
    t0 = datetime(2017, 6, 15, 6, 0, tzinfo=UTC)
    minutes = []
    for i in range(13):
        p = 1.0 + i * 0.01
        minutes.append(m1(t0 + timedelta(minutes=i), o=p, h=1.02 + i * 0.01,
                          l=0.98 + i * 0.01, c=p))
    # feed shuffled: aggregation must sort by timestamp first
    import random
    shuffled = list(minutes)
    random.Random(7).shuffle(shuffled)
    out = ds.aggregate_m15(tuple(shuffled))
    assert len(out) == 1
    bar = out[0]
    assert bar.open == pytest.approx(1.0)            # FIRST traded minute's open
    assert bar.close == pytest.approx(1.12)          # LAST traded minute's close
    assert bar.high == pytest.approx(1.02 + 12 * 0.01)
    assert bar.low == pytest.approx(0.98)


def test_m15_buckets_are_independent():
    t0 = datetime(2017, 6, 15, 6, 0, tzinfo=UTC)
    a = [m1(t0 + timedelta(minutes=i), o=1.0, h=1.1, l=0.9, c=1.0) for i in range(15)]
    b = [m1(t0 + M15 + timedelta(minutes=i), o=2.0, h=2.1, l=1.9, c=2.0) for i in range(15)]
    out = ds.aggregate_m15(tuple(a + b))
    assert len(out) == 2
    assert out[0].high == pytest.approx(1.1)
    assert out[1].high == pytest.approx(2.1)  # no bleed between buckets


def test_missing_bucket_is_absent_never_filled():
    # 06:00 bucket full, 06:15 bucket absent, 06:30 bucket full
    t0 = datetime(2017, 6, 15, 6, 0, tzinfo=UTC)
    a = [m1(t0 + timedelta(minutes=i)) for i in range(15)]
    c = [m1(t0 + 2 * M15 + timedelta(minutes=i)) for i in range(15)]
    out = ds.aggregate_m15(tuple(a + c))
    assert [b.timestamp for b in out] == [t0, t0 + 2 * M15]


# ---------------------------------------------------------------------------
# dataset: loading from HistData zips
# ---------------------------------------------------------------------------

def test_ny_to_utc_normalization(tmp_path):
    # 09:00 New York on 2017-01-03 is EST (UTC-5) -> 14:00 UTC
    zp = write_zip(tmp_path / "a.zip", [row(ny(2017, 1, 3, 9, 0), 1.05000, 1.06000, 1.04000, 1.05000)])
    bars = ds.load_histdata_m1(zp, "EURUSD")
    assert len(bars) == 1
    assert bars[0].timestamp == datetime(2017, 1, 3, 14, 0, tzinfo=UTC)


def test_dst_spring_forward_offset_change(tmp_path):
    # 2017-03-10 is EST (UTC-5); 2017-03-13 is EDT (UTC-4): the same NY
    # wall-clock hour maps to different UTC hours across the transition.
    rows = [
        row(ny(2017, 3, 10, 9, 0), 1.0, 1.1, 0.9, 1.0),
        row(ny(2017, 3, 13, 9, 0), 1.0, 1.1, 0.9, 1.0),
    ]
    zp = write_zip(tmp_path / "b.zip", rows)
    bars = ds.load_histdata_m1(zp, "EURUSD")
    assert [b.timestamp.hour for b in bars] == [14, 13]


def _full_bucket_rows(ny_start, n=15):
    return [row(ny_start + timedelta(minutes=i), 1.0, 1.1, 0.9, 1.0) for i in range(n)]


def test_duplicate_timestamps_fail_closed(tmp_path):
    r = row(ny(2017, 1, 3, 9, 0), 1.0, 1.1, 0.9, 1.0)
    zp = write_zip(tmp_path / "c.zip", [r, r])
    with pytest.raises(ValueError, match="duplicate"):
        ds.build_symbol_dataset(zp, "EURUSD")


def test_ohlc_violation_fails_closed(tmp_path):
    rows = _full_bucket_rows(ny(2017, 1, 3, 9, 0))
    head = rows[0].split(";")[0]
    rows[0] = head + ";1.05000;1.04000;1.06000;1.05000;0\n"  # high < open -> invalid
    zp = write_zip(tmp_path / "d.zip", rows)
    with pytest.raises(ValueError, match="OHLC"):
        ds.build_symbol_dataset(zp, "EURUSD")


def test_quality_report_carries_source_hash(tmp_path):
    rows = _full_bucket_rows(ny(2017, 1, 3, 9, 0)) + _full_bucket_rows(ny(2017, 1, 3, 9, 15))
    zp = write_zip(tmp_path / "e.zip", rows)
    m15, report = ds.build_symbol_dataset(zp, "EURUSD")
    assert report.source_sha256 == hashlib.sha256(zp.read_bytes()).hexdigest()
    assert report.symbol == "EURUSD"
    assert report.m1_rows == 30
    assert report.m1_duplicate_timestamps == 0
    assert report.m1_ohlc_violations == 0
    assert report.m15_bars == 2
    assert report.m15_buckets_with_lt13_minutes == 0
    assert m15[0].timestamp == datetime(2017, 1, 3, 14, 0, tzinfo=UTC)


def test_window_filter_excludes_2018_bars(tmp_path):
    # 2017-12-31 20:00 NY = 2018-01-01 01:00 UTC -> outside the 2017 window
    rows = _full_bucket_rows(ny(2017, 1, 3, 9, 0)) + _full_bucket_rows(ny(2017, 12, 31, 20, 0))
    zp = write_zip(tmp_path / "f.zip", rows)
    m15, report = ds.build_symbol_dataset(zp, "EURUSD")
    assert report.m15_bars == 1
    assert all(datetime(2017, 1, 1, tzinfo=UTC) <= b.timestamp < datetime(2018, 1, 1, tzinfo=UTC)
               for b in m15)


# ---------------------------------------------------------------------------
# dataset: partitions
# ---------------------------------------------------------------------------

def test_partitions_are_disjoint_and_chronological():
    dev, oos, hold = (ds.PARTITIONS[k] for k in ("DEVELOPMENT", "OOS", "SEALED_HOLDOUT"))
    assert dev[1] == oos[0] and oos[1] == hold[0]
    assert dev[0] < dev[1] < hold[1]


def test_holdout_slice_fails_closed():
    bars = (m1(datetime(2017, 12, 15, 12, 0, tzinfo=UTC)),)
    with pytest.raises(ds.HoldoutAccessError):
        ds.slice_partition(bars, "SEALED_HOLDOUT")
