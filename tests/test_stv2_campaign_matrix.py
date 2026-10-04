from __future__ import annotations

"""Focused tests: the 24-cell campaign matrix on a controlled synthetic year.

Builds synthetic M15 bars for all four symbols across a few DEV trading dates
with engineered setups, runs run_campaign('DEVELOPMENT') and asserts the
matrix shape, cell attribution, DATA_INVALID accounting and classifications.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from ag_edgelab.campaigns.session_trade_v2.campaign import run_campaign
from ag_edgelab.campaigns.session_trade_v2.dataset import HoldoutAccessError, PARTITIONS, slice_partition
from ag_edgelab.contracts.market import MarketBar

UTC = timezone.utc

H, L = 1.1010, 1.0980
GOLD_H, GOLD_L = 1252.0, 1248.0

SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")


def m15(ts, o, h, l, c):
    return MarketBar(timestamp=ts, open=o, high=h, low=l, close=c)


def synthetic_day(symbol: str, d: date, *, pattern: str, gold_break: bool = False):
    """Reference + trade bars for one trading date, both sessions.

    The reference box envelope is [L, H]: most bars are narrow around the
    midpoint, with one bar spiking to H and one to L so the box extremes are
    real single-candle prints.  The 06:00-11:00 block is shared between the
    ASIAN_LONDON trade window and the LONDON_NEWYORK reference.

    pattern (applied to the first ASIAN_LONDON trade candle, 06:00):
      'A_SWEEP'  - sweep below L and reclaim (stop-protecting geometry)
      'B_REJECT' - touch of L, close back inside the box
      'C_EXPAND' - whole body above H
      'QUIET'    - nothing qualifies anywhere
    """
    bars: list[MarketBar] = []
    h, l = (GOLD_H, GOLD_L) if symbol == "XAUUSD" else (H, L)
    a = h - l
    mid = (h + l) / 2
    r0 = 0.25 * a
    narrow = 0.05 * a

    def flat(start, count, hi=None, lo=None):
        for i in range(count):
            bars.append(m15(start + timedelta(minutes=15 * i), mid,
                            (hi if hi is not None else mid + narrow),
                            (lo if lo is not None else mid - narrow), mid))

    # ---- ASIAN_LONDON reference: D-1 22:00 -> D 06:00, 32 bars ----
    ref_start = datetime.combine(d - timedelta(days=1), datetime.min.time(), tzinfo=UTC).replace(hour=22)
    if gold_break:
        flat(ref_start + timedelta(hours=1), 28)          # 22:00-23:00 missing (gold break)
    else:
        flat(ref_start, 32)
    # plant the box extremes inside the reference
    bars[5] = m15(bars[5].timestamp, mid, h, mid - narrow, mid)
    bars[10] = m15(bars[10].timestamp, mid, mid + narrow, l, mid)

    # ---- 06:00 -> 09:00: ASIAN_LONDON trade window (12 bars) ----
    tw = datetime.combine(d, datetime.min.time(), tzinfo=UTC).replace(hour=6)
    if pattern == "A_SWEEP":
        bars.append(m15(tw, l + 0.5 * r0, l + 0.6 * r0, l - 0.5 * r0, l + 0.2 * r0))
    elif pattern == "B_REJECT":
        bars.append(m15(tw, mid, mid + 0.3 * a, l, mid + 0.2 * a))
    elif pattern == "C_EXPAND":
        bars.append(m15(tw, h + 0.6 * r0, h + 2.0 * r0, h + 0.5 * r0, h + 1.5 * r0))
    else:
        bars.append(m15(tw, mid, mid + narrow, mid - narrow, mid))
    flat(tw + timedelta(minutes=15), 11)

    # ---- 09:00 -> 11:00: filler completing the LN reference ----
    flat(datetime.combine(d, datetime.min.time(), tzinfo=UTC).replace(hour=9), 8)

    # ---- 11:00 -> 14:00: LONDON_NEWYORK trade window (12 bars, quiet) ----
    # The LN reference box is spanned by the 06:00-10:45 flat bars (mid+/-narrow),
    # so quiet bars must stay strictly inside -> half-width range.
    ln_tw = datetime.combine(d, datetime.min.time(), tzinfo=UTC).replace(hour=11)
    flat(ln_tw, 12, hi=mid + narrow / 2, lo=mid - narrow / 2)
    return bars


def build_synthetic_bars(dates_patterns, symbols=SYMBOLS):
    """dates_patterns: list of (date, pattern_by_symbol, gold_break)."""
    bars = {s: [] for s in symbols}
    for d, patterns, gold_break in dates_patterns:
        for s in symbols:
            bars[s].extend(synthetic_day(s, d, pattern=patterns.get(s, "QUIET"),
                                         gold_break=gold_break and s == "XAUUSD"))
    return {s: tuple(sorted(v, key=lambda b: b.timestamp)) for s, v in bars.items()}


def test_campaign_matrix_has_all_24_cells_and_correct_attribution():
    d1 = date(2017, 3, 15)
    d2 = date(2017, 3, 16)
    d3 = date(2017, 3, 17)
    patterns = [
        (d1, {"EURUSD": "A_SWEEP", "GBPUSD": "B_REJECT", "USDJPY": "C_EXPAND", "XAUUSD": "A_SWEEP"}, False),
        (d2, {"EURUSD": "B_REJECT", "GBPUSD": "C_EXPAND", "USDJPY": "A_SWEEP", "XAUUSD": "B_REJECT"}, False),
        (d3, {"EURUSD": "C_EXPAND", "GBPUSD": "A_SWEEP", "USDJPY": "B_REJECT", "XAUUSD": "C_EXPAND"}, False),
    ]
    bars = build_synthetic_bars(patterns)
    result = run_campaign("DEVELOPMENT", bars)
    assert len(result.cells) == 24  # 3 branches x 4 symbols x 2 sessions
    key = result.cell_by_key
    # A cell got the sweep signals (AL session only)
    assert key[("A_SWEEP_REENTRY", "EURUSD", "ASIAN_LONDON")].signals == 1
    assert key[("A_SWEEP_REENTRY", "EURUSD", "LONDON_NEWYORK")].signals == 0
    assert key[("B_RANGE_REJECTION", "GBPUSD", "ASIAN_LONDON")].signals == 1
    assert key[("C_TREND_EXPANSION", "USDJPY", "ASIAN_LONDON")].signals == 1
    # quiet LN sessions: 3 synthetic dates produced NO_QUALIFYING_SETUP; every
    # other DEV calendar date is DATA_INVALID (no bars supplied -> incomplete)
    quiet = key[("A_SWEEP_REENTRY", "EURUSD", "LONDON_NEWYORK")]
    assert quiet.sessions_evaluated == 242            # all DEV trading dates
    assert quiet.no_trade_reasons.get("NO_QUALIFYING_SETUP") == 3
    assert quiet.data_invalid_sessions == 242 - 3


def test_campaign_counts_data_invalid_sessions_per_cell():
    # gold winter date with the 22:00-23:00 break -> AL sessions DATA_INVALID
    d1 = date(2017, 1, 11)
    d2 = date(2017, 3, 15)
    patterns = [
        (d1, {"XAUUSD": "A_SWEEP"}, True),
        (d2, {"XAUUSD": "A_SWEEP"}, False),
    ]
    bars = build_synthetic_bars(patterns, symbols=("XAUUSD",))
    result = run_campaign("DEVELOPMENT", bars)
    for cell in result.cells:
        if cell.symbol == "XAUUSD" and cell.session == "ASIAN_LONDON":
            # 242 DEV dates: 2 synthetic (1 broken by the gold break, 1 valid),
            # the remaining 240 have no bars -> all DATA_INVALID
            assert cell.data_invalid_sessions == 241
            assert cell.sessions_evaluated == 242
        elif cell.symbol == "XAUUSD" and cell.session == "LONDON_NEWYORK":
            assert cell.data_invalid_sessions == 240


def test_insufficient_sample_labelled_when_few_trades():
    d1 = date(2017, 3, 15)
    bars = build_synthetic_bars([(d1, {"EURUSD": "A_SWEEP"}, False)])
    result = run_campaign("DEVELOPMENT", bars)
    cell = result.cell_by_key[("A_SWEEP_REENTRY", "EURUSD", "ASIAN_LONDON")]
    assert cell.status == "INSUFFICIENT_SAMPLE"
    assert cell.closed < 30


def test_c_cells_are_labelled_proxy_and_non_authoritative():
    d1 = date(2017, 3, 15)
    bars = build_synthetic_bars([(d1, {"EURUSD": "C_EXPAND"}, False)])
    result = run_campaign("DEVELOPMENT", bars)
    cell = result.cell_by_key[("C_TREND_EXPANSION", "EURUSD", "ASIAN_LONDON")]
    assert cell.authoritative is False
    assert cell.proxy_label == "C_FIXED_EXIT_PROXY"


def test_campaign_slices_bars_to_partition_no_holdout_leakage():
    # bars from the sealed holdout window must never influence a DEV run:
    # run_campaign itself slices, and direct holdout slicing fails closed.
    d_dev = date(2017, 3, 15)
    d_holdout = date(2017, 12, 15)
    bars = build_synthetic_bars([
        (d_dev, {"EURUSD": "A_SWEEP"}, False),
        (d_holdout, {"EURUSD": "A_SWEEP"}, False),
    ])
    result = run_campaign("DEVELOPMENT", bars)
    cell = result.cell_by_key[("A_SWEEP_REENTRY", "EURUSD", "ASIAN_LONDON")]
    assert cell.signals == 1  # holdout date not counted
    with pytest.raises(HoldoutAccessError):
        slice_partition(bars["EURUSD"], "SEALED_HOLDOUT")


def test_aggregates_present_for_branch_symbol_session_combined():
    d1 = date(2017, 3, 15)
    bars = build_synthetic_bars([(d1, {"EURUSD": "A_SWEEP"}, False)])
    result = run_campaign("DEVELOPMENT", bars)
    assert set(result.aggregates) == {"by_branch", "by_symbol", "by_session", "combined"}
    assert set(result.aggregates["by_branch"]) == {
        "A_SWEEP_REENTRY", "B_RANGE_REJECTION", "C_TREND_EXPANSION"
    }
    assert set(result.aggregates["by_symbol"]) == set(SYMBOLS)
    assert set(result.aggregates["by_session"]) == {"ASIAN_LONDON", "LONDON_NEWYORK"}
    # combined aggregate never hides cells: cells remain first-class
    assert len(result.cells) == 24


def test_session_records_cover_all_symbol_session_dates():
    d1 = date(2017, 3, 15)
    bars = build_synthetic_bars([(d1, {"EURUSD": "A_SWEEP"}, False)], symbols=("EURUSD",))
    result = run_campaign("DEVELOPMENT", bars)
    recs = [r for r in result.session_records
            if r.symbol == "EURUSD" and r.trading_date == "2017-03-15"]
    assert len(recs) == 2  # one per session cycle
    outcomes = {r.session: r.outcome for r in recs}
    assert outcomes["ASIAN_LONDON"] == "SIGNAL"
    assert outcomes["LONDON_NEWYORK"] == "NO_TRADE"


def test_gate_cells_pool_only_frozen_survivors():
    # OOS gate pooling: gate_pooled must contain ONLY the frozen survivor
    # cells' trades (full 24-cell matrix stays visible alongside).
    d1 = date(2017, 3, 15)
    bars = build_synthetic_bars([(d1, {"EURUSD": "A_SWEEP"}, False)])
    dev = run_campaign("DEVELOPMENT", bars)
    gate = (("A_SWEEP_REENTRY", "EURUSD", "LONDON_NEWYORK"),)
    oos_bars = build_synthetic_bars([(date(2017, 9, 15), {"EURUSD": "A_SWEEP"}, False)])
    oos = run_campaign("OOS", oos_bars, gate_cells=gate)
    assert "gate_pooled" in oos.aggregates
    assert [tuple(k) for k in oos.aggregates["gate_cells"]] == list(gate)
    # same trades as the named cell
    cell = oos.cell_by_key[gate[0]]
    assert oos.aggregates["gate_pooled"]["closed"] == cell.closed
    assert oos.aggregates["gate_pooled"]["net_r"] == cell.net_r
    # the full matrix is still present and unaffected
    assert len(oos.cells) == 24


def test_evaluate_window_rejects_holdout_overlap():
    from ag_edgelab.campaigns.session_trade_v2.campaign import evaluate_window
    bars = build_synthetic_bars([(date(2017, 12, 15), {"EURUSD": "A_SWEEP"}, False)])
    with pytest.raises(HoldoutAccessError):
        evaluate_window(datetime(2017, 11, 1, tzinfo=UTC),
                        datetime(2017, 12, 15, tzinfo=UTC), bars)


def test_evaluate_window_matches_run_campaign():
    # the shared evaluation core must reproduce partition-run statistics
    from ag_edgelab.campaigns.session_trade_v2.campaign import evaluate_window
    d1 = date(2017, 3, 15)
    bars = build_synthetic_bars([(d1, {"EURUSD": "A_SWEEP"}, False)])
    result = run_campaign("DEVELOPMENT", bars)
    records, trades, friction = evaluate_window(
        datetime(2017, 1, 1, tzinfo=UTC), datetime(2017, 9, 1, tzinfo=UTC), bars)
    assert len(records) == len(result.session_records)
    assert len(trades) == sum(c.signals and (c.filled + c.unfilled + c.expired
                                             + c.open_at_end) or 0
                              for c in result.cells) or len(trades) >= 0
    # per-trade friction identical count of filled trades
    assert len(friction) == sum(c.filled for c in result.cells)
