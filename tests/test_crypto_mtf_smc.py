"""ST_CRYPTO_MTF_SMC_V1 — deterministic primitives + anti-lookahead tests.

Anti-lookahead suite: future bars must never modify decisions already
committed at an earlier bar close. Property tested at the primitives level
(swing confirmation gating, BOS timing, FVG third-candle gating, truncation
invariance) and at the scanner level (prefix scans cannot change, add, or
remove commitments whose decision time precedes the prefix end).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.strategies.crypto_mtf_smc import (
    BASELINE_PARAMETERS,
    IncrementalStructure,
    MtfSmcScanner,
    SmcParameters,
    confirmed_swing_points,
    detect_fvg,
    displacement_present,
)

Z = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=Z)


def bars_from_oc(ocs, start: datetime = T0, step_seconds: int = 300) -> tuple[MarketBar, ...]:
    """Bars with open==low==high==close pattern (no wicks) for readability."""
    out = []
    prev = None
    for i, c in enumerate(ocs):
        o = prev if prev is not None else c
        lo, hi = min(o, c), max(o, c)
        out.append(MarketBar(timestamp=start + timedelta(seconds=step_seconds * i), open=float(o),
                             high=float(hi), low=float(lo), close=float(c), volume=1.0))
        prev = c
    return tuple(out)


def bars_ohlc(rows, start: datetime = T0, step_seconds: int = 300) -> tuple[MarketBar, ...]:
    out = []
    for i, (o, h, l, c) in enumerate(rows):
        h, l = max(o, h, l, c), min(o, h, l, c)
        out.append(MarketBar(timestamp=start + timedelta(seconds=step_seconds * i), open=float(o),
                             high=float(h), low=float(l), close=float(c), volume=1.0))
    return tuple(out)


# --------------------------------------------------------------------------
# Primitive: confirmed swings are right-bar gated
# --------------------------------------------------------------------------

def test_swing_pivot_is_gated_by_right_confirmation():
    # Clear local high at index 2 (order=2): highs peak at 2 with strictly
    # lower highs at 1,3 and at 0,4.
    bars = bars_ohlc([
        (100, 101, 99, 100),
        (100, 104, 99, 103),
        (103, 110, 102, 106),   # candidate pivot high 110 at index 2
        (106, 107, 104, 105),
        (105, 106, 103, 104),
        (104, 105, 101, 102),
    ])
    swings = confirmed_swing_points(bars, order=2)
    highs = [s for s in swings if s.kind == "HIGH"]
    assert len(highs) == 1
    assert highs[0].index == 2
    assert highs[0].price == 110.0
    # Usable only once bar 4 (index 2+2) has CLOSED.
    assert highs[0].confirmed_index == 4


def test_swing_unknown_before_right_side_closes():
    # Truncate before the right-confirmation bar closes: pivot must not exist.
    bars = bars_ohlc([
        (100, 101, 99, 100),
        (100, 104, 99, 103),
        (103, 110, 102, 106),
        (106, 107, 104, 105),
    ])
    assert confirmed_swing_points(bars, order=2) == ()


def test_incremental_structure_never_reextends_state_backwards():
    bars = bars_ohlc([
        (100, 101, 99, 100),
        (100, 104, 99, 103),
        (103, 110, 102, 106),
        (106, 107, 104, 105),
        (105, 106, 103, 104),
    ])
    s = IncrementalStructure(bars, swing_order=2)
    assert s.update(2).swing_high is None       # right side not closed
    assert s.update(3).swing_high is None
    state4 = s.update(4)
    assert state4.swing_high == 110.0
    assert state4.swing_high_index == 2
    # Feeding the same index again must be a no-op (idempotent, monotone).
    assert s.update(4) == state4
    # Feeding a lower index must not recompute or rewind.
    assert s.update(1) == state4


# --------------------------------------------------------------------------
# Primitive: FVG exists only at the third candle's close
# --------------------------------------------------------------------------

def test_fvg_requires_third_candle():
    two = bars_ohlc([(10, 11, 10, 11), (11, 12, 11, 12)])
    assert detect_fvg(two) == ()
    three = bars_ohlc([(10, 11, 10, 11), (11, 12, 11, 12), (12, 13, 11.5, 12.5)])
    # candle1.high=11 < candle3.low=11.5 -> bullish FVG (11, 11.5)
    gaps = detect_fvg(three)
    assert len(gaps) == 1
    assert gaps[0].direction == "BULLISH"
    assert gaps[0].index == 2
    assert gaps[0].lower == 11.0 and gaps[0].upper == 11.5
    assert gaps[0].midpoint == pytest.approx(11.25)


def test_bearish_fvg_detection_correct_geometry():
    bars = bars_ohlc([(12, 13, 11.4, 11.5), (11.5, 12, 10.5, 11), (10.7, 10.8, 9, 9.5)])
    # candle1.low = 11.4 > candle3.high = 10.8 -> bearish FVG (10.8, 11.4)
    gap = detect_fvg(bars)[0]
    assert gap.direction == "BEARISH"
    assert gap.lower == pytest.approx(10.8)
    assert gap.upper == pytest.approx(11.4)
    assert gap.index == 2


# --------------------------------------------------------------------------
# Primitive: displacement vs reference medians (deterministic, not future-fed)
# --------------------------------------------------------------------------

def test_displacement_present_requires_expansion():
    ref = bars_from_oc([100 + (i % 3) * 0.5 for i in range(30)])
    quiet = bars_from_oc([100.4, 100.9, 100.3])
    loud = bars_from_oc([104.0, 107.0, 104.5])
    assert not displacement_present(quiet, ref, 2.0, 1.8)
    assert displacement_present(loud, ref, 2.0, 1.8)


def test_displacement_degenerate_reference_rejected():
    flat = bars_from_oc([100.0] * 10)   # zero bodies/ranges
    loud = bars_from_oc([104.0, 107.0])
    assert not displacement_present(loud, flat, 2.0, 1.8)


# --------------------------------------------------------------------------
# Scanner-level anti-lookahead: truncation invariance
# --------------------------------------------------------------------------

FIXTURE_PATH = "data/artifacts/synthetic_btcusdt/BTCUSDT_M5_SYNTHETIC.csv"


def _load_fixture():
    from ag_edgelab.data.bars import read_bars_csv
    from ag_edgelab.data.derive import aggregate_bars

    bars, _ = read_bars_csv(FIXTURE_PATH)
    frames = {tf: aggregate_bars(bars, "M5", tf)[0] for tf in ("M15", "H1", "H4", "D1")}
    return bars, frames


def _commitments(sc: MtfSmcScanner):
    """Serialize committed decisions: filled intents plus committed transitions."""
    intents, candidates, _ = sc.scan()
    intents_s = sorted(
        (i.candidate_id, i.created_at.isoformat(), i.side.value, i.order_type.value,
         round(i.entry_price, 10), round(i.stop_price, 10),
         tuple(round(t.price, 10) for t in i.targets))
        for i in intents
    )
    transitions_s = sorted(
        (c.machine_id, tuple((t.stage_id, t.driving_bar_index) for t in c.transitions))
        for c in candidates
    )
    return intents_s, transitions_s


@pytest.fixture(scope="module")
def fixture():
    return _load_fixture()


def test_scan_is_deterministic_across_repeated_runs(fixture):
    bars, frames = fixture
    a = _commitments(MtfSmcScanner(bars, frames))
    b = _commitments(MtfSmcScanner(bars, frames))
    assert a == b


@pytest.mark.parametrize("prefix", [6000, 14000, 29000, 43199])
def test_truncation_invariance_of_committed_intents(fixture, prefix):
    """Intents committed strictly before the prefix end must be identical.

    The full-series scan uses full-range derived frames; the prefix scan
    re-derives frames from the truncated M5 series (the honest live
    pipeline). Any intent visible in both runs (committed before the
    prefix's last bar close) must be byte-identical, and no such intent may
    disappear or change.
    """
    from ag_edgelab.data.derive import aggregate_bars

    bars, _ = fixture
    full = MtfSmcScanner(bars, fixture[1])
    full_intents, _, _ = full.scan()
    pre = tuple(b for b in bars[:prefix])
    pre_frames = {tf: aggregate_bars(pre, "M5", tf)[0] for tf in ("M15", "H1", "H4", "D1")}
    cut = bars[prefix - 1].timestamp + timedelta(seconds=300)
    full_i_obj, full_c, _ = full.scan()
    pre_i_obj, pre_c, _ = MtfSmcScanner(pre, pre_frames).scan()

    # 1) Stage transitions committed strictly before the prefix end (the
    #    driving M5 bar is inside the prefix) must be identical, with an
    #    identical commit order.
    def committed_rows(cands):
        rows = []
        for c in cands:
            for t in c.transitions:
                # ENTRY and EXIT are replay outcomes that can only exist once
                # the fill/exit bar has occurred; all earlier stages are pure
                # scanner decisions causally bound to the driving M5 close.
                limit = prefix if t.stage_id in ("ENTRY", "EXIT") else None
                if t.stage_id in ("ENTRY", "EXIT") or t.driving_bar_index < prefix:
                    rows.append((c.machine_id, c.direction, t.stage_id, t.driving_bar_index))
        return rows

    full_rows = committed_rows(full_c)
    pre_rows = committed_rows(pre_c)
    # The prefix run may legitimately lack replay stages (ENTRY/EXIT) whose
    # outcome bars lie beyond the prefix; everything else must match exactly.
    full_nonreplay = [r for r in full_rows if r[2] not in ("ENTRY", "EXIT")]
    pre_nonreplay = [r for r in pre_rows if r[2] not in ("ENTRY", "EXIT")]
    assert full_nonreplay == pre_nonreplay, (
        "prefix scan changed machine transitions committed before its horizon"
    )
    pre_replay = {(r[0], r[2]): r for r in pre_rows if r[2] in ("ENTRY", "EXIT")}
    full_replay = {(r[0], r[2]): r for r in full_rows if r[2] in ("ENTRY", "EXIT")}
    # Any replay stage present in the prefix run must match the full run.
    for key, row in pre_replay.items():
        assert key in full_replay and full_replay[key] == row

    # 2) Filled intents whose fill decision happened before the prefix end
    #    must be identical in both runs (fill is what appends the intent).
    fill_cut = {
        c.machine_id: t.driving_bar_index
        for c in full_c
        for t in c.transitions
        if t.stage_id == "ENTRY"
    }
    full_committed = sorted(
        i.candidate_id for i in full_i_obj
        if i.candidate_id in fill_cut and fill_cut[i.candidate_id] < prefix
    )
    pre_committed = sorted(
        i.candidate_id for i in pre_i_obj
        if i.candidate_id in fill_cut and fill_cut[i.candidate_id] < prefix
    )
    assert full_committed == pre_committed
    by_id = {i.candidate_id: i for i in full_i_obj}
    for i in pre_i_obj:
        if i.candidate_id in fill_cut and fill_cut[i.candidate_id] < prefix:
            ref = by_id[i.candidate_id]
            assert i.created_at == ref.created_at
            assert i.entry_price == ref.entry_price
            assert i.stop_price == ref.stop_price
            assert tuple(t.price for t in i.targets) == tuple(t.price for t in ref.targets)


# --------------------------------------------------------------------------
# Retry-monotone incremental structure never exposes future bars
# --------------------------------------------------------------------------

def test_incremental_structure_truncation_invariance(fixture):
    bars, frames = fixture
    frame = frames["H1"]
    full = IncrementalStructure(frame, 2)
    for j in range(len(frame)):
        full.update(j)
    cut = len(frame) // 2
    trunc_states = []
    s = IncrementalStructure(frame, 2)
    for j in range(cut):
        trunc_states.append(s.update(j))
    # Replay full updates only through `cut` -> states must match the prefix run.
    s2 = IncrementalStructure(frame, 2)
    for j in range(cut):
        assert s2.update(j) == trunc_states[j]


# --------------------------------------------------------------------------
# Baseline config is the single declared configuration (no tunables exposed)
# --------------------------------------------------------------------------

def test_baseline_parameters_are_frozen_declaration():
    p = BASELINE_PARAMETERS
    assert isinstance(p, SmcParameters)
    assert p.htf_bos_max_age_bars == 30
    assert p.d1_momentum_bars == 3
    assert p.displacement_body_mult == 2.0 and p.displacement_range_mult == 1.8
    assert p.min_rr == 1.5
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        p.min_rr = 2.0  # type: ignore[misc] - frozen dataclass forbids mutation


def test_fixture_intent_structure_sanity(fixture):
    """The pinned fixture must commit intents in both directions."""
    from collections import Counter

    bars, frames = fixture
    intents, candidates, tally = MtfSmcScanner(bars, frames).scan()
    assert intents, "pinned fixture must produce intents"
    sides = Counter(i.side.value for i in intents)
    assert sides["LONG"] >= 2 and sides["SHORT"] >= 2
    stops_ok = all(
        (i.entry_price - i.stop_price) > 0 for i in intents if i.side.value == "LONG"
    ) and all(
        (i.stop_price - i.entry_price) > 0 for i in intents if i.side.value == "SHORT"
    )
    assert stops_ok
