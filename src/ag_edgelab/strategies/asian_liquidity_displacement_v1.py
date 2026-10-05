"""ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1 — GENERATION 2 research candidate.

STATUS: RESEARCH_CANDIDATE / DEVELOPMENT_ONLY / EDGE_VERIFIED = False.

This module translates ONE preregistered hypothesis into deterministic,
closed-bar rules.  It contains NO execution capability: no broker adapter,
no order sending, no EA import.  It never reads the OOS or SEALED_HOLDOUT
partitions — the only dataset accessor it uses is the DEVELOPMENT slice of
the PR #10 HistData 2017 authority.

Hypothesis (frozen V1, not optimized in this mission):

    higher-timeframe direction
      -> Asian liquidity sweep
      -> reclaim (close back inside the Asian range)
      -> displacement
      -> MSS/BOS
      -> fresh FVG
      -> causal retracement entry
      -> structural target

Timeframe authority
    D1  macro context      (structural direction)
    H4  macro context      (non-opposing gate + premium/discount)
    H1  internal flow      (structural direction + liquidity objectives)
    M15 setup / structure  (Asian range, sweep, reclaim, displacement, MSS)
    M5  entry refinement   (fresh FVG, causal retracement entry)

Every primitive reused here is an ACCEPTED EdgeLab V1 primitive:
    ag_edgelab.universal.direction.structural_direction   (confirmed swings)
    ag_edgelab.universal.confirmation.structure_shift_events (MSS/BOS)
    ag_edgelab.universal.location.premium_discount / liquidity_levels
    ag_edgelab.strategies.crypto_mtf_smc.detect_fvg       (strict 3-candle)
    ag_edgelab.universal.targets.compute_excursions       (1R..5R / MFE / MAE)

The ONLY new numeric contract introduced by this mission is the frozen V1
displacement rule ``body / candle_range >= 0.70`` plus the preregistered
session/temporal envelope below.  Nothing in this file may be re-tuned in
response to observed DEV results (search policy, mission section 10).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import canonical_json, sha256_json
from ag_edgelab.data.bars import dumps_bars
from ag_edgelab.data.fx_histdata_2017 import (
    PARTITIONS,
    PINNED_SOURCE_SHA256,
    SYMBOLS,
    WINDOW_END,
    WINDOW_START,
    aggregate_m15,
    assert_partition_accessible,
    bars_closed_at,
    derive_fx_timeframe,
    load_histdata_m1,
    partition_bounds,
    quality_gate_m1,
    verify_source_identity,
)
from ag_edgelab.strategies.crypto_mtf_smc import detect_fvg
from ag_edgelab.universal.confirmation import structure_shift_events
from ag_edgelab.universal.direction import Direction, structural_direction
from ag_edgelab.universal.location import (
    LocationSide,
    liquidity_levels,
    premium_discount,
)
from ag_edgelab.universal.targets import EntryGeometry, compute_excursions
from ag_edgelab.verification.regimes import classify_market_state

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Identity (mission section 1) — must not reuse any historical identity
# ---------------------------------------------------------------------------

CANDIDATE_FAMILY_ID = "ASIAN_LIQUIDITY_DISPLACEMENT"
STRATEGY_ID = "ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1"
STRATEGY_VERSION = "1.0.0-research"
STRATEGY_STATUS = "RESEARCH_CANDIDATE"
EDGE_VERIFIED = False
VERIFIER_VERSION = "EDGELAB_SYSTEM_READINESS_V1"

FORBIDDEN_IDENTITY_REUSE: tuple[str, ...] = (
    "ST_ASIAN_SWEEP_5R_V1",
    "SESSION_TRADE_V2",
    "ST_MTF_CONTROL_SHIFT_V1",
    "ST_MTF_CONTROL_SHIFT_V2",
    "ST_MTF_CONTROL_SHIFT_V3",
    "TARGET_POLICY_C3_V1",
)

SYMBOL_UNIVERSE: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")
TIMEFRAMES: tuple[str, ...] = ("D1", "H4", "H1", "M15", "M5")

# ---------------------------------------------------------------------------
# SESSION CONTRACT (mission section 4) — preregistered BEFORE any result
# ---------------------------------------------------------------------------

ASIAN_REFERENCE_UTC: tuple[int, int] = (0, 6)       # 00:00 <= UTC < 06:00
LONDON_ENTRY_UTC: tuple[int, int] = (7, 10)         # 07:00 <= UTC < 10:00
NEW_YORK_ENTRY_UTC: tuple[int, int] = (12, 15)      # 12:00 <= UTC < 15:00

SESSION_PAIRS: dict[str, tuple[int, int]] = {
    # Asian reference liquidity -> London entry window.
    "ASIAN_LONDON": LONDON_ENTRY_UTC,
    # Asian reference liquidity -> New York entry window (post-London).
    "LONDON_NEWYORK": NEW_YORK_ENTRY_UTC,
}

SESSION_CONTRACT_NOTE = (
    "Both evaluated session pairs use the SAME Asian reference range "
    "(00:00-06:00 UTC) as the liquidity object, because the hypothesis is "
    "Asian-liquidity displacement. The pair label names the ENTRY window: "
    "ASIAN_LONDON = London entry window 07:00-10:00 UTC, LONDON_NEWYORK = "
    "New York entry window 12:00-15:00 UTC. Windows are frozen and are "
    "NEVER widened in response to observed results."
)

# ---------------------------------------------------------------------------
# FROZEN V1 PARAMETERS (mission sections 5-7) — no optimization in this sprint
# ---------------------------------------------------------------------------

DISPLACEMENT_BODY_RANGE_MIN = 0.70   # frozen V1 hypothesis — NOT optimized
SWING_ORDER_D1 = 2
SWING_ORDER_H4 = 2
SWING_ORDER_H1 = 2
SWING_ORDER_M15 = 2
MIN_ASIAN_M15_BARS = 16              # of 24 possible 00:00-06:00 M15 buckets
M5_MINUTES_REQUIRED = 4              # of 5 (80% coverage); buckets never filled
WARMUP_DAYS = 21                     # context warm-up inside the DEV partition
FVG_MAX_AGE_M5_BARS = 12             # "fresh": formed <= 12 M5 bars after MSS
RETRACE_MAX_AGE_M5_BARS = 24         # causal retrace must occur <= 24 M5 bars
OUTCOME_HORIZON_M5_BARS = 288        # 24 traded hours, measured on M5
OPPORTUNITY_STOP_LOOKBACK_M15 = 12   # diagnostic opportunity-basis stop
OPPORTUNITY_HORIZON_M15 = 96         # diagnostic opportunity-basis horizon
FIXED_R_TARGETS: tuple[int, ...] = (1, 2, 3, 4, 5)

SAME_BAR_COLLISION_POLICY = "STOP_FIRST_FAIL_CLOSED_V0_3"
CENSORING_POLICY = (
    "RIGHT_CENSORED_DATA_BOUNDARY_EXPLICIT — a candidate whose 288-M5-bar "
    "outcome window is truncated by the DEVELOPMENT partition end is "
    "RIGHT_CENSORED: excluded from target-capability denominators, counted "
    "in the population, never imputed. The OOS partition is NEVER read to "
    "complete an outcome window."
)
ENTRY_FILL_POLICY = (
    "LIMIT_AT_FVG_PROXIMAL_EDGE_ON_FIRST_CAUSAL_TOUCH — fill price is the "
    "proximal FVG edge (upper edge for LONG, lower edge for SHORT) on the "
    "first M5 bar that trades into the gap strictly after the gap's third "
    "candle closes. Outcome measurement starts at the NEXT M5 bar; if the "
    "fill bar itself also trades through the structural stop the candidate "
    "is recorded STOPPED_SAME_BAR = -1R (fail-closed)."
)
STOP_CONTRACT_NOTE = (
    "Structural stop ONLY: LONG SL = sweep bar low, SHORT SL = sweep bar "
    "high. No pip/point buffer is added. Execution/spread buffering belongs "
    "to the friction layer, which has no authority in this mission."
)

# ---------------------------------------------------------------------------
# Funnel node vocabulary
# ---------------------------------------------------------------------------

TRIGGER_NODES: tuple[str, ...] = (
    "T1_ASIAN_REFERENCE_VALID",
    "T2_DIRECTION_DECIDED",
    "T3_DIRECTION_NON_NEUTRAL",
    "T4_ASIAN_SWEEP",
    "T5_CLOSE_BACK_INSIDE",
)
CONFIRMATION_NODES: tuple[str, ...] = (
    "C1_DISPLACEMENT",
    "C2_MSS_BOS",
    "C3_FRESH_FVG",
    "C4_FVG_RETRACE_AVAILABLE",
    "C5_GEOMETRY_VALID",
    "C6_ENTRY_AVAILABLE",
)
OUTCOME_NODES: tuple[str, ...] = ("O1_1R", "O2_2R", "O3_3R", "O4_4R", "O5_5R")

REJECT_REASONS: tuple[str, ...] = (
    "ASIAN_REFERENCE_INSUFFICIENT_BARS",
    "ASIAN_RANGE_DEGENERATE",
    "ENTRY_WINDOW_NO_BARS",
    "DIRECTION_UNDECIDABLE",
    "DIRECTION_NEUTRAL",
    "NO_ASIAN_SWEEP_ON_DIRECTION_SIDE",
    "NO_CLOSE_BACK_INSIDE",
    "NO_DISPLACEMENT_BODY_RATIO",
    "NO_MSS_BOS_AFTER_DISPLACEMENT",
    "NO_FRESH_FVG_AFTER_MSS",
    "NO_CAUSAL_RETRACE_INTO_FVG",
    "RETRACE_INVALIDATED_BY_STOP_FIRST",
    "GEOMETRY_RISK_NON_POSITIVE",
    "GEOMETRY_TP1_NOT_BEYOND_ENTRY",
    "GEOMETRY_TEMPORAL_ORDER_INVALID",
    "RIGHT_CENSORED_DATA_BOUNDARY",
    "PASS",
)


# ---------------------------------------------------------------------------
# Dataset layer — DEVELOPMENT ONLY, same M1 lineage, declared M5 extension
# ---------------------------------------------------------------------------

def aggregate_m5(m1_bars: tuple[MarketBar, ...]) -> tuple[MarketBar, ...]:
    """Aggregate M1 -> M5 under a declared >= 4/5 coverage rule (no fills).

    DECLARED EXTENSION (not silent): the PR #10 authority froze M1 -> M15 at
    >= 13/15 minutes.  This mission requires an M5 entry-refinement frame
    from the SAME normalized M1 lineage; the coverage rule is preregistered
    here as >= 4 of 5 traded minutes per UTC bucket.  Under-covered buckets
    are MISSING bars and are never forward-filled.
    """
    buckets: dict[datetime, list[MarketBar]] = {}
    for bar in m1_bars:
        minute = (bar.timestamp.minute // 5) * 5
        key = bar.timestamp.replace(minute=minute, second=0, microsecond=0)
        buckets.setdefault(key, []).append(bar)
    out: list[MarketBar] = []
    for key in sorted(buckets):
        minutes = sorted(buckets[key], key=lambda b: b.timestamp)
        if len(minutes) < M5_MINUTES_REQUIRED:
            continue
        out.append(MarketBar(
            timestamp=key,
            open=minutes[0].open,
            high=max(b.high for b in minutes),
            low=min(b.low for b in minutes),
            close=minutes[-1].close,
        ))
    return tuple(out)


def _bars_hash(bars: tuple[MarketBar, ...]) -> str:
    return hashlib.sha256(dumps_bars(bars).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SymbolDataset:
    symbol: str
    source_sha256: str
    frames: dict[str, tuple[MarketBar, ...]]
    quality: dict
    frame_hashes: dict[str, str]


def load_development_dataset(zip_path: Path, symbol: str) -> SymbolDataset:
    """Verify identity, load M1, gate quality, build all frames, slice DEV.

    The holdout accessor fails closed and the OOS partition is never
    requested: this function only ever slices role=DEVELOPMENT.
    """
    assert_partition_accessible("DEVELOPMENT")
    source_sha = verify_source_identity(zip_path, symbol)
    m1 = load_histdata_m1(zip_path)
    quality = quality_gate_m1(m1, symbol)

    m1_window = tuple(b for b in m1 if WINDOW_START <= b.timestamp < WINDOW_END)
    m15_full = aggregate_m15(m1_window)
    m5_full = aggregate_m5(m1_window)

    frames_full: dict[str, tuple[MarketBar, ...]] = {"M15": m15_full, "M5": m5_full}
    for tf in ("H1", "H4", "D1"):
        frames_full[tf], _ = derive_fx_timeframe(m15_full, tf, symbol)

    dev_start, dev_end = partition_bounds("DEVELOPMENT")
    frames = {tf: tuple(b for b in rows if dev_start <= b.timestamp < dev_end)
              for tf, rows in frames_full.items()}
    frame_hashes = {tf: _bars_hash(rows) for tf, rows in sorted(frames.items())}
    quality.update({
        "symbol": symbol,
        "source_sha256": source_sha,
        "dataset_role": "DEVELOPMENT",
        "partition_utc": [dev_start.isoformat(), dev_end.isoformat()],
        "bars": {tf: len(rows) for tf, rows in sorted(frames.items())},
        "first_m15": frames["M15"][0].timestamp.isoformat() if frames["M15"] else None,
        "last_m15": frames["M15"][-1].timestamp.isoformat() if frames["M15"] else None,
        "m15_rule": ">= 13/15 M1 minutes per bucket (PR#10 frozen); no forward fill",
        "m5_rule": f">= {M5_MINUTES_REQUIRED}/5 M1 minutes per bucket (declared); no forward fill",
        "timezone_rule": "source America/New_York (DST) normalized to UTC before any logic",
    })
    return SymbolDataset(symbol=symbol, source_sha256=source_sha, frames=frames,
                         quality=quality, frame_hashes=frame_hashes)


# ---------------------------------------------------------------------------
# Candidate record
# ---------------------------------------------------------------------------

@dataclass
class CandidateUnit:
    symbol: str
    day: str
    session: str
    candidate_id: str

    # trigger evidence (recorded individually — never an opaque score)
    d1_structure: str = "UNAVAILABLE"
    h4_structure: str = "UNAVAILABLE"
    h1_flow: str = "UNAVAILABLE"
    premium_discount_state: str = "UNAVAILABLE"
    prev_day_context: str = "UNAVAILABLE"
    liquidity_context_above: int = 0
    liquidity_context_below: int = 0
    direction: str = "NEUTRAL"

    asian_high: float | None = None
    asian_low: float | None = None
    asian_bars: int = 0
    entry_window_bars: int = 0

    # funnel stage flags
    stages: dict[str, bool] = field(default_factory=dict)
    reject_reason: str = "PASS"
    reject_node: str | None = None

    # confirmation geometry
    sweep_time: str | None = None
    reclaim_time: str | None = None
    displacement_time: str | None = None
    displacement_body_ratio: float | None = None
    mss_time: str | None = None
    mss_primitive: str | None = None
    fvg_time: str | None = None
    entry_time: str | None = None
    same_bar_reclaim_displacement: bool = False
    same_bar_displacement_mss: bool = False

    entry: float | None = None
    stop: float | None = None
    risk: float | None = None
    tp1: float | None = None
    tp1_r: float | None = None
    tp2: float | None = None
    tp2_r: float | None = None
    natural_target_r: float | None = None

    # outcome
    mfe_r: float | None = None
    mae_r: float | None = None
    reached: dict[str, bool] = field(default_factory=dict)
    stopped_out: bool | None = None
    stopped_same_bar: bool = False
    forward_bars: int = 0
    resolution: str | None = None
    management_r: float | None = None
    management_exit: float | None = None

    horizon_r: float | None = None

    # temporal diagnostics (mission section 8 TEMPORAL_INCOMPATIBILITY)
    window_m15_bars: int = 0
    m15_bars_after_sweep: int | None = None
    m15_bars_after_reclaim: int | None = None
    m15_bars_after_displacement: int | None = None
    m5_bars_after_mss: int | None = None

    # regime / calendar strata (frozen classifier; strata are not gates)
    regime: str = "UNAVAILABLE"
    quarter: str = ""

    # opportunity-basis diagnostic (frozen observation policy)
    opp_mfe_r: float | None = None
    opp_mae_r: float | None = None

    def passed(self, node: str) -> bool:
        return bool(self.stages.get(node))


OBSERVATION_POLICY_ID = (
    "OPP_BASIS_ALD_V1__anchor=last_closed_M15_at_entry_window_open;"
    f"risk={OPPORTUNITY_STOP_LOOKBACK_M15}_bar_opposite_extreme;"
    f"horizon={OPPORTUNITY_HORIZON_M15}_M15_bars;collision=STOP_FIRST"
)


# ---------------------------------------------------------------------------
# Deterministic rule helpers
# ---------------------------------------------------------------------------

def body_range_ratio(bar: MarketBar) -> float | None:
    rng = bar.high - bar.low
    if rng <= 0:
        return None
    return abs(bar.close - bar.open) / rng


def is_displacement(bar: MarketBar, direction: Direction,
                    threshold: float = DISPLACEMENT_BODY_RANGE_MIN) -> tuple[bool, float | None]:
    """Frozen V1 displacement: body/range >= 0.70 AND body on the thesis side.

    ``threshold`` exists solely so the preregistered NON-SELECTING
    parameter-neighborhood robustness diagnostic can be computed. The V1
    contract value is DISPLACEMENT_BODY_RANGE_MIN and is never changed by
    an observed result.
    """
    ratio = body_range_ratio(bar)
    if ratio is None:
        return False, None
    if ratio < threshold:
        return False, ratio
    if direction == Direction.BULL and bar.close <= bar.open:
        return False, ratio
    if direction == Direction.BEAR and bar.close >= bar.open:
        return False, ratio
    return True, ratio


def _window_indices(bars: tuple[MarketBar, ...], start: datetime, end: datetime) -> tuple[int, ...]:
    return tuple(i for i, b in enumerate(bars) if start <= b.timestamp < end)


def _prev_day_context(d1_closed: tuple[MarketBar, ...], price: float) -> str:
    if not d1_closed:
        return "UNAVAILABLE"
    prev = d1_closed[-1]
    if price > prev.high:
        return "ABOVE_PDH"
    if price < prev.low:
        return "BELOW_PDL"
    return "INSIDE_PREV_DAY_RANGE"


def decide_direction(d1: str, h4: str, h1: str) -> Direction:
    """TRIG_DIR_ALD_V1 — explicit boolean logic over named components.

    BULL  iff D1 structure BULL and H4 structure not BEAR and H1 flow BULL.
    BEAR  iff D1 structure BEAR and H4 structure not BULL and H1 flow BEAR.
    else  NEUTRAL.
    """
    if d1 == Direction.BULL.value and h4 != Direction.BEAR.value and h1 == Direction.BULL.value:
        return Direction.BULL
    if d1 == Direction.BEAR.value and h4 != Direction.BULL.value and h1 == Direction.BEAR.value:
        return Direction.BEAR
    return Direction.NEUTRAL


# ---------------------------------------------------------------------------
# Replay — one deterministic pass per (symbol, UTC day, session pair)
# ---------------------------------------------------------------------------

def replay_symbol(dataset: SymbolDataset,
                  displacement_min: float = DISPLACEMENT_BODY_RANGE_MIN) -> list[CandidateUnit]:
    frames = dataset.frames
    m15, m5 = frames["M15"], frames["M5"]
    h1, h4, d1 = frames["H1"], frames["H4"], frames["D1"]
    if not m15 or not m5:
        return []

    # MSS/BOS events on M15 are computed ONCE over the DEV series; each event
    # is indexed at the bar on whose CLOSE it became knowable (causal).
    shift_events = structure_shift_events(m15, "M15", swing_order=SWING_ORDER_M15)
    shifts_by_index: dict[int, list] = {}
    for ev in shift_events:
        shifts_by_index.setdefault(ev.index, []).append(ev)

    # Strict 3-candle FVGs on M5, usable only from the third candle's close.
    fvgs = detect_fvg(m5)
    fvgs_by_index: dict[int, list] = {}
    for gap in fvgs:
        fvgs_by_index.setdefault(gap.index, []).append(gap)

    dev_start, dev_end = partition_bounds("DEVELOPMENT")
    first_day = (m15[0].timestamp + timedelta(days=WARMUP_DAYS)).date()
    last_day = m15[-1].timestamp.date()

    units: list[CandidateUnit] = []
    day = first_day
    while day <= last_day:
        base = datetime(day.year, day.month, day.day, tzinfo=UTC)
        a_start = base + timedelta(hours=ASIAN_REFERENCE_UTC[0])
        a_end = base + timedelta(hours=ASIAN_REFERENCE_UTC[1])
        asian_idx = _window_indices(m15, a_start, a_end)
        asian_bars = len(asian_idx)
        asian_high = max(m15[i].high for i in asian_idx) if asian_idx else None
        asian_low = min(m15[i].low for i in asian_idx) if asian_idx else None

        for session, (ws, we) in sorted(SESSION_PAIRS.items()):
            w_start = base + timedelta(hours=ws)
            w_end = base + timedelta(hours=we)
            unit = CandidateUnit(
                symbol=dataset.symbol, day=day.isoformat(), session=session,
                candidate_id=f"{dataset.symbol}|{day.isoformat()}|{session}",
                asian_high=asian_high, asian_low=asian_low, asian_bars=asian_bars,
            )
            units.append(unit)
            unit.quarter = f"{day.year}Q{(day.month - 1) // 3 + 1}"
            _evaluate_unit(unit, dataset, m15, m5, h1, h4, d1,
                           shifts_by_index, fvgs_by_index, w_start, w_end, dev_end,
                           displacement_min)
        day = day + timedelta(days=1)
    return units


def _fail(unit: CandidateUnit, node: str, reason: str) -> None:
    unit.stages[node] = False
    unit.reject_node = node
    unit.reject_reason = reason


def _evaluate_unit(
    unit: CandidateUnit,
    dataset: SymbolDataset,
    m15: tuple[MarketBar, ...],
    m5: tuple[MarketBar, ...],
    h1: tuple[MarketBar, ...],
    h4: tuple[MarketBar, ...],
    d1: tuple[MarketBar, ...],
    shifts_by_index: dict[int, list],
    fvgs_by_index: dict[int, list],
    w_start: datetime,
    w_end: datetime,
    dev_end: datetime,
    displacement_min: float = DISPLACEMENT_BODY_RANGE_MIN,
) -> None:
    # ---------------- TRIGGER 1: Asian reference validity -----------------
    if unit.asian_bars < MIN_ASIAN_M15_BARS or unit.asian_high is None or unit.asian_low is None:
        _fail(unit, "T1_ASIAN_REFERENCE_VALID", "ASIAN_REFERENCE_INSUFFICIENT_BARS")
        return
    if unit.asian_high <= unit.asian_low:
        _fail(unit, "T1_ASIAN_REFERENCE_VALID", "ASIAN_RANGE_DEGENERATE")
        return
    win_idx = _window_indices(m15, w_start, w_end)
    unit.entry_window_bars = len(win_idx)
    unit.window_m15_bars = len(win_idx)
    if not win_idx:
        _fail(unit, "T1_ASIAN_REFERENCE_VALID", "ENTRY_WINDOW_NO_BARS")
        return
    unit.stages["T1_ASIAN_REFERENCE_VALID"] = True

    # ---------------- TRIGGER 2: direction decided (as of window open) ----
    d1_closed = bars_closed_at(d1, "D1", w_start)
    h4_closed = bars_closed_at(h4, "H4", w_start)
    h1_closed = bars_closed_at(h1, "H1", w_start)
    m15_closed = bars_closed_at(m15, "M15", w_start)
    if not (d1_closed and h4_closed and h1_closed and m15_closed):
        _fail(unit, "T2_DIRECTION_DECIDED", "DIRECTION_UNDECIDABLE")
        return
    price = m15_closed[-1].close

    unit.d1_structure = structural_direction(d1_closed, "D1", SWING_ORDER_D1).direction.value
    unit.h4_structure = structural_direction(h4_closed, "H4", SWING_ORDER_H4).direction.value
    unit.h1_flow = structural_direction(h1_closed, "H1", SWING_ORDER_H1).direction.value
    pd_state = premium_discount(h4_closed, "H4", price, SWING_ORDER_H4)
    unit.premium_discount_state = pd_state.state if pd_state else "UNAVAILABLE"
    unit.prev_day_context = _prev_day_context(d1_closed, price)
    unit.regime = classify_market_state(d1_closed[-1])
    liq = liquidity_levels(h1_closed, "H1", SWING_ORDER_H1)
    unit.liquidity_context_above = sum(1 for z in liq if z.side == LocationSide.RESISTANCE and z.zone_low > price)
    unit.liquidity_context_below = sum(1 for z in liq if z.side == LocationSide.SUPPORT and z.zone_high < price)
    unit.stages["T2_DIRECTION_DECIDED"] = True

    direction = decide_direction(unit.d1_structure, unit.h4_structure, unit.h1_flow)
    unit.direction = direction.value

    # Opportunity-basis diagnostic observation (frozen policy, trigger-time
    # geometry); computed for every unit with a decided direction so that
    # funnel value attribution has a common comparison basis.
    if direction != Direction.NEUTRAL:
        anchor_i = len(m15_closed) - 1
        lo_i = max(0, anchor_i - OPPORTUNITY_STOP_LOOKBACK_M15 + 1)
        ref = m15[lo_i: anchor_i + 1]
        if ref:
            opp_stop = min(b.low for b in ref) if direction == Direction.BULL else max(b.high for b in ref)
            if abs(price - opp_stop) > 0:
                geo = EntryGeometry(direction=direction, entry=price, stop=opp_stop)
                fwd = m15[anchor_i + 1: anchor_i + 1 + OPPORTUNITY_HORIZON_M15]
                exc = compute_excursions(tuple(fwd), geo, OPPORTUNITY_HORIZON_M15)
                unit.opp_mfe_r, unit.opp_mae_r = exc.mfe_r, exc.mae_r

    # ---------------- TRIGGER 3: direction non-neutral --------------------
    if direction == Direction.NEUTRAL:
        _fail(unit, "T3_DIRECTION_NON_NEUTRAL", "DIRECTION_NEUTRAL")
        return
    unit.stages["T3_DIRECTION_NON_NEUTRAL"] = True

    # ---------------- TRIGGER 4: Asian sweep on the OPPOSITE side ---------
    # Direction must NOT equal the sweep side: a BULL thesis sweeps the Asian
    # LOW (sell-side liquidity); a BEAR thesis sweeps the Asian HIGH.
    sweep_i: int | None = None
    for i in win_idx:
        bar = m15[i]
        if direction == Direction.BULL and bar.low < unit.asian_low:
            sweep_i = i
            break
        if direction == Direction.BEAR and bar.high > unit.asian_high:
            sweep_i = i
            break
    if sweep_i is None:
        _fail(unit, "T4_ASIAN_SWEEP", "NO_ASIAN_SWEEP_ON_DIRECTION_SIDE")
        return
    unit.stages["T4_ASIAN_SWEEP"] = True
    unit.sweep_time = m15[sweep_i].timestamp.isoformat()
    unit.m15_bars_after_sweep = sum(1 for i in win_idx if i > sweep_i)

    # ---------------- TRIGGER 5: close back INSIDE the Asian range --------
    reclaim_i: int | None = None
    for i in win_idx:
        if i < sweep_i:
            continue
        c = m15[i].close
        if unit.asian_low < c < unit.asian_high:
            reclaim_i = i
            break
    if reclaim_i is None:
        _fail(unit, "T5_CLOSE_BACK_INSIDE", "NO_CLOSE_BACK_INSIDE")
        return
    unit.stages["T5_CLOSE_BACK_INSIDE"] = True
    unit.reclaim_time = m15[reclaim_i].timestamp.isoformat()
    unit.m15_bars_after_reclaim = sum(1 for i in win_idx if i > reclaim_i)

    # ---------------- CONFIRMATION 1: displacement ------------------------
    disp_i: int | None = None
    for i in win_idx:
        if i < reclaim_i:
            continue
        ok, ratio = is_displacement(m15[i], direction, displacement_min)
        if ok:
            disp_i, unit.displacement_body_ratio = i, ratio
            break
    if disp_i is None:
        _fail(unit, "C1_DISPLACEMENT", "NO_DISPLACEMENT_BODY_RATIO")
        return
    unit.stages["C1_DISPLACEMENT"] = True
    unit.displacement_time = m15[disp_i].timestamp.isoformat()
    unit.same_bar_reclaim_displacement = disp_i == reclaim_i
    unit.m15_bars_after_displacement = sum(1 for i in win_idx if i > disp_i)

    # ---------------- CONFIRMATION 2: MSS / BOS ---------------------------
    mss_i: int | None = None
    mss_primitive: str | None = None
    for i in win_idx:
        if i < disp_i:
            continue
        for ev in shifts_by_index.get(i, ()):
            if ev.direction == direction:
                mss_i, mss_primitive = i, ev.primitive.value
                break
        if mss_i is not None:
            break
    if mss_i is None:
        _fail(unit, "C2_MSS_BOS", "NO_MSS_BOS_AFTER_DISPLACEMENT")
        return
    unit.stages["C2_MSS_BOS"] = True
    unit.mss_time = m15[mss_i].timestamp.isoformat()
    unit.mss_primitive = mss_primitive
    unit.same_bar_displacement_mss = mss_i == disp_i

    # ---------------- CONFIRMATION 3: fresh FVG on M5 ---------------------
    mss_close_time = m15[mss_i].timestamp + timedelta(minutes=15)
    unit.m5_bars_after_mss = len(_window_indices(m5, m15[mss_i].timestamp + timedelta(minutes=15), w_end))
    want = "BULLISH" if direction == Direction.BULL else "BEARISH"
    fvg = None
    fvg_i: int | None = None
    m5_window = _window_indices(m5, mss_close_time, w_end)
    for count, j in enumerate(m5_window):
        if count >= FVG_MAX_AGE_M5_BARS:
            break
        for gap in fvgs_by_index.get(j, ()):
            if gap.direction == want:
                fvg, fvg_i = gap, j
                break
        if fvg is not None:
            break
    if fvg is None or fvg_i is None:
        _fail(unit, "C3_FRESH_FVG", "NO_FRESH_FVG_AFTER_MSS")
        return
    unit.stages["C3_FRESH_FVG"] = True
    unit.fvg_time = m5[fvg_i].timestamp.isoformat()

    # ---------------- CONFIRMATION 4: causal retracement into the FVG -----
    stop_price = m15[sweep_i].low if direction == Direction.BULL else m15[sweep_i].high
    entry_price = fvg.upper if direction == Direction.BULL else fvg.lower
    entry_i: int | None = None
    invalidated = False
    for count, j in enumerate(_window_indices(m5, m5[fvg_i].timestamp + timedelta(minutes=5), w_end)):
        if count >= RETRACE_MAX_AGE_M5_BARS:
            break
        bar = m5[j]
        if direction == Direction.BULL:
            if bar.low <= stop_price:
                invalidated = True
                break
            if bar.low <= entry_price:
                entry_i = j
                break
        else:
            if bar.high >= stop_price:
                invalidated = True
                break
            if bar.high >= entry_price:
                entry_i = j
                break
    if entry_i is None:
        _fail(unit, "C4_FVG_RETRACE_AVAILABLE",
              "RETRACE_INVALIDATED_BY_STOP_FIRST" if invalidated else "NO_CAUSAL_RETRACE_INTO_FVG")
        return
    unit.stages["C4_FVG_RETRACE_AVAILABLE"] = True
    unit.entry_time = m5[entry_i].timestamp.isoformat()

    # ---------------- CONFIRMATION 5: geometry validity -------------------
    risk = abs(entry_price - stop_price)
    if risk <= 0:
        _fail(unit, "C5_GEOMETRY_VALID", "GEOMETRY_RISK_NON_POSITIVE")
        return
    tp1 = unit.asian_high if direction == Direction.BULL else unit.asian_low
    beyond = (tp1 > entry_price) if direction == Direction.BULL else (tp1 < entry_price)
    if not beyond:
        unit.entry, unit.stop, unit.risk = entry_price, stop_price, risk
        _fail(unit, "C5_GEOMETRY_VALID", "GEOMETRY_TP1_NOT_BEYOND_ENTRY")
        return
    times = [m15[sweep_i].timestamp, m15[reclaim_i].timestamp, m15[disp_i].timestamp,
             m15[mss_i].timestamp, m5[fvg_i].timestamp, m5[entry_i].timestamp]
    if any(times[k] > times[k + 1] for k in range(len(times) - 1)):
        _fail(unit, "C5_GEOMETRY_VALID", "GEOMETRY_TEMPORAL_ORDER_INVALID")
        return
    unit.stages["C5_GEOMETRY_VALID"] = True
    unit.entry, unit.stop, unit.risk = entry_price, stop_price, risk
    unit.tp1, unit.tp1_r = tp1, abs(tp1 - entry_price) / risk

    # TP2 = nearest valid H1 liquidity objective beyond TP1 (closed H1 only).
    h1_at_entry = bars_closed_at(h1, "H1", m5[entry_i].timestamp + timedelta(minutes=5))
    if h1_at_entry:
        zones = liquidity_levels(h1_at_entry, "H1", SWING_ORDER_H1)
        if direction == Direction.BULL:
            cand = [z.zone_low for z in zones if z.side == LocationSide.RESISTANCE and z.zone_low > tp1]
            tp2 = min(cand) if cand else None
        else:
            cand = [z.zone_high for z in zones if z.side == LocationSide.SUPPORT and z.zone_high < tp1]
            tp2 = max(cand) if cand else None
        if tp2 is not None:
            unit.tp2, unit.tp2_r = tp2, abs(tp2 - entry_price) / risk
    unit.natural_target_r = unit.tp2_r if unit.tp2_r is not None else unit.tp1_r

    # ---------------- CONFIRMATION 6: entry available & measurable --------
    forward = m5[entry_i + 1: entry_i + 1 + OUTCOME_HORIZON_M5_BARS]
    unit.forward_bars = len(forward)
    entry_bar = m5[entry_i]
    same_bar_stop = (entry_bar.low <= stop_price) if direction == Direction.BULL \
        else (entry_bar.high >= stop_price)
    unit.stopped_same_bar = bool(same_bar_stop)

    if not same_bar_stop and len(forward) < OUTCOME_HORIZON_M5_BARS:
        # Determine whether the truncated window already resolved the trade.
        geo = EntryGeometry(direction=direction, entry=entry_price, stop=stop_price)
        probe = compute_excursions(tuple(forward), geo, OUTCOME_HORIZON_M5_BARS)
        resolved = probe.stopped_out or probe.fixed_target_reached[5]
        if not resolved:
            _fail(unit, "C6_ENTRY_AVAILABLE", "RIGHT_CENSORED_DATA_BOUNDARY")
            return
    unit.stages["C6_ENTRY_AVAILABLE"] = True
    unit.reject_reason = "PASS"

    # ---------------- OUTCOME: 1R..5R capability, MFE/MAE ------------------
    geo = EntryGeometry(direction=direction, entry=entry_price, stop=stop_price)
    if same_bar_stop:
        unit.mfe_r, unit.mae_r = 0.0, 1.0
        unit.reached = {f"{k}R": False for k in FIXED_R_TARGETS}
        unit.stopped_out = True
        unit.resolution = "STOPPED_SAME_BAR"
        unit.management_r, unit.management_exit = -1.0, stop_price
        unit.horizon_r = -1.0
    else:
        exc = compute_excursions(tuple(forward), geo, OUTCOME_HORIZON_M5_BARS)
        unit.mfe_r, unit.mae_r = exc.mfe_r, exc.mae_r
        unit.reached = {f"{k}R": bool(v) for k, v in sorted(exc.fixed_target_reached.items())}
        unit.stopped_out = exc.stopped_out
        unit.resolution = "STOPPED_OUT" if exc.stopped_out else (
            "TARGET_5R" if exc.fixed_target_reached[5] else "HORIZON")
        unit.management_r, unit.management_exit = _management_50_50(
            forward, direction, entry_price, stop_price, unit.tp1, unit.tp2)
        if forward:
            last = forward[-1].close
            unit.horizon_r = ((last - entry_price) / risk if direction == Direction.BULL
                              else (entry_price - last) / risk)

    for k in FIXED_R_TARGETS:
        node = f"O{k}_{k}R"
        unit.stages[node] = bool(unit.reached.get(f"{k}R"))
        if not unit.stages[node]:
            break


def _management_50_50(
    forward: Sequence[MarketBar], direction: Direction, entry: float, stop: float,
    tp1: float | None, tp2: float | None,
) -> tuple[float, float]:
    """Diagnostic management: 50% at TP1, 50% toward TP2 (original SL retained).

    Same-bar collision rule: STOP FIRST (fail-closed). Structural R only —
    no friction is applied anywhere (no friction authority exists).
    """
    risk = abs(entry - stop)
    first_done = False
    realized = 0.0
    for bar in forward:
        if direction == Direction.BULL:
            hit_stop = bar.low <= stop
            hit_tp1 = tp1 is not None and bar.high >= tp1
            hit_tp2 = tp2 is not None and bar.high >= tp2
        else:
            hit_stop = bar.high >= stop
            hit_tp1 = tp1 is not None and bar.low <= tp1
            hit_tp2 = tp2 is not None and bar.low <= tp2
        if hit_stop:
            return (realized - 0.5, stop) if first_done else (-1.0, stop)
        if not first_done and hit_tp1:
            first_done = True
            realized = 0.5 * (abs(tp1 - entry) / risk)
            if hit_tp2 and tp2 is not None:
                return realized + 0.5 * (abs(tp2 - entry) / risk), tp2
            continue
        if first_done and hit_tp2 and tp2 is not None:
            return realized + 0.5 * (abs(tp2 - entry) / risk), tp2
    last = forward[-1].close if forward else entry
    open_r = (last - entry) / risk if direction == Direction.BULL else (entry - last) / risk
    if first_done:
        return realized + 0.5 * open_r, last
    return open_r, last


# ---------------------------------------------------------------------------
# Contract hashes (mission section 12)
# ---------------------------------------------------------------------------

def _src_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def trigger_contract() -> dict:
    return {
        "contract_id": "TRIG_ALD_V1",
        "rule_id": "TRIG_DIR_ALD_V1",
        "direction_components": {
            "macro_structure": "D1 structural_direction (confirmed swings, order 2)",
            "macro_context": "H4 structural_direction (must not oppose)",
            "internal_flow": "H1 structural_direction (must confirm)",
        },
        "recorded_but_non_gating": [
            "H4 premium/discount state",
            "previous-day high/low context",
            "H1 liquidity pool counts above/below price",
        ],
        "composite_rule": (
            "BULL iff D1==BULL and H4!=BEAR and H1==BULL; "
            "BEAR iff D1==BEAR and H4!=BULL and H1==BEAR; else NEUTRAL"
        ),
        "no_opaque_score": True,
        "sweep_side_rule": "direction MUST NOT equal sweep side: BULL sweeps the Asian LOW, BEAR the Asian HIGH",
        "primary_trigger": [
            "direction non-neutral",
            "Asian liquidity swept on the opposite side",
            "M15 close back inside the Asian range",
        ],
        "decision_anchor": "entry window open (UTC); only bars CLOSED at or before the anchor are readable",
        "swing_orders": {"D1": SWING_ORDER_D1, "H4": SWING_ORDER_H4, "H1": SWING_ORDER_H1},
    }


def confirmation_contract() -> dict:
    return {
        "contract_id": "CONF_ALD_V1",
        "sequence": ["SWEEP", "CLOSE_BACK_INSIDE", "DISPLACEMENT", "MSS_BOS",
                     "FRESH_FVG", "FVG_RETRACE_AVAILABLE"],
        "sweep": "M15 bar trades beyond the Asian boundary on the non-direction side",
        "close_back_inside": "first M15 bar at or after the sweep whose CLOSE is strictly inside the Asian range",
        "displacement": {
            "rule": "body / candle_range >= 0.70 AND body polarity matches the thesis",
            "threshold": DISPLACEMENT_BODY_RANGE_MIN,
            "frozen": True,
            "optimized_in_this_mission": False,
            "timeframe": "M15",
        },
        "mss_bos": {
            "primitive": "ag_edgelab.universal.confirmation.structure_shift_events",
            "timeframe": "M15",
            "swing_order": SWING_ORDER_M15,
            "rule": "first direction-matched MSS or BOS at or after the displacement bar",
        },
        "fresh_fvg": {
            "primitive": "ag_edgelab.strategies.crypto_mtf_smc.detect_fvg (strict 3-candle imbalance)",
            "timeframe": "M5",
            "freshness": f"third candle closes strictly after the MSS bar close and within {FVG_MAX_AGE_M5_BARS} M5 bars",
        },
        "retrace": {
            "rule": "first causal M5 touch of the FVG strictly after the gap's third candle closes",
            "max_age_m5_bars": RETRACE_MAX_AGE_M5_BARS,
            "backfilled_entry": "FORBIDDEN",
            "invalidation": "if the structural stop is touched before the FVG, the candidate is rejected",
        },
        "temporal_envelope": "every funnel event INCLUDING the entry fill must occur inside the session entry window",
    }


def entry_contract() -> dict:
    return {"contract_id": "ENTRY_ALD_V1", "fill_policy": ENTRY_FILL_POLICY,
            "collision_policy": SAME_BAR_COLLISION_POLICY,
            "outcome_anchor": "M5 bar AFTER the fill bar"}


def sl_contract() -> dict:
    return {"contract_id": "SL_ALD_V1", "long": "SL = sweep bar LOW", "short": "SL = sweep bar HIGH",
            "buffer_points": 0, "buffer_pips": 0, "note": STOP_CONTRACT_NOTE}


def target_contract() -> dict:
    return {
        "contract_id": "TARGET_ALD_V1",
        "fixed_r_measured": list(FIXED_R_TARGETS),
        "tp1": "opposite Asian range boundary",
        "tp2": "nearest valid H1 liquidity objective strictly beyond TP1 (closed H1 bars only)",
        "natural_target_r": "TP2_R when available, else TP1_R",
        "management_diagnostic": "50% at TP1, 50% toward TP2, original structural SL retained by the runner",
        "fixed_5r_as_sole_authority": False,
        "economic_claim": "FORBIDDEN — no friction authority exists (structural R only)",
        "horizon_m5_bars": OUTCOME_HORIZON_M5_BARS,
        "censoring_policy": CENSORING_POLICY,
    }


def session_contract() -> dict:
    return {
        "contract_id": "SESSION_ALD_V1",
        "asian_reference_utc": {"start_hour": ASIAN_REFERENCE_UTC[0], "end_hour": ASIAN_REFERENCE_UTC[1]},
        "london_entry_utc": {"start_hour": LONDON_ENTRY_UTC[0], "end_hour": LONDON_ENTRY_UTC[1]},
        "new_york_entry_utc": {"start_hour": NEW_YORK_ENTRY_UTC[0], "end_hour": NEW_YORK_ENTRY_UTC[1]},
        "evaluated_pairs": sorted(SESSION_PAIRS),
        "pooled": True,
        "min_asian_m15_bars": MIN_ASIAN_M15_BARS,
        "widening_allowed": False,
        "note": SESSION_CONTRACT_NOTE,
    }


def parameter_contract() -> dict:
    return {
        "DISPLACEMENT_BODY_RANGE_MIN": DISPLACEMENT_BODY_RANGE_MIN,
        "SWING_ORDER_D1": SWING_ORDER_D1, "SWING_ORDER_H4": SWING_ORDER_H4,
        "SWING_ORDER_H1": SWING_ORDER_H1, "SWING_ORDER_M15": SWING_ORDER_M15,
        "MIN_ASIAN_M15_BARS": MIN_ASIAN_M15_BARS, "M5_MINUTES_REQUIRED": M5_MINUTES_REQUIRED,
        "WARMUP_DAYS": WARMUP_DAYS, "FVG_MAX_AGE_M5_BARS": FVG_MAX_AGE_M5_BARS,
        "RETRACE_MAX_AGE_M5_BARS": RETRACE_MAX_AGE_M5_BARS,
        "OUTCOME_HORIZON_M5_BARS": OUTCOME_HORIZON_M5_BARS,
        "OPPORTUNITY_STOP_LOOKBACK_M15": OPPORTUNITY_STOP_LOOKBACK_M15,
        "OPPORTUNITY_HORIZON_M15": OPPORTUNITY_HORIZON_M15,
    }


def friction_contract() -> dict:
    """Fail-closed: no measured friction authority exists for FX 2017."""
    return {
        "contract_id": "FRICTION_ALD_V1_ABSENT_FAIL_CLOSED",
        "FRICTION_EDGE_VERIFICATION_READY": "NO",
        "spread": "UNAVAILABLE", "commission": "UNAVAILABLE",
        "slippage": "UNAVAILABLE", "swap": "UNAVAILABLE", "funding": "NOT_APPLICABLE",
        "substitution_forbidden": ["generic_spread", "7_usd_per_lot", "fixed_slippage", "industry_defaults"],
        "consequence": "ECONOMIC_METRICS = NOT_ESTIMABLE_NO_FRICTION_AUTHORITY; structural R only",
        "authority_gap_record": "config/governance/friction_authority_gap.json",
    }


def strategy_contract() -> dict:
    return {
        "candidate_family_id": CANDIDATE_FAMILY_ID,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "status": STRATEGY_STATUS,
        "edge_verified": EDGE_VERIFIED,
        "symbol_universe": list(SYMBOL_UNIVERSE),
        "timeframes": list(TIMEFRAMES),
        "asset_class": "FX",
        "identity_reuse_forbidden": list(FORBIDDEN_IDENTITY_REUSE),
        "trigger_contract": trigger_contract(),
        "confirmation_contract": confirmation_contract(),
        "entry_contract": entry_contract(),
        "sl_contract": sl_contract(),
        "target_contract": target_contract(),
        "session_contract": session_contract(),
        "parameters": parameter_contract(),
        "friction_contract": friction_contract(),
        "funnel_nodes": {"TRIGGER": list(TRIGGER_NODES), "CONFIRMATION": list(CONFIRMATION_NODES),
                         "OUTCOME": list(OUTCOME_NODES)},
        "rejection_vocabulary": list(REJECT_REASONS),
        "observation_policy_id": OBSERVATION_POLICY_ID,
        "execution_capability": "NONE — no broker adapter, no order sending, no EA import",
        "dataset_authority": "HISTDATA_ASCII_M1_2017_PR10_PINNED",
        "dataset_role": "DEVELOPMENT",
        "pinned_source_sha256": dict(sorted(PINNED_SOURCE_SHA256.items())),
        "development_partition_utc": [PARTITIONS["DEVELOPMENT"][0].isoformat(),
                                      PARTITIONS["DEVELOPMENT"][1].isoformat()],
    }


def contract_hashes() -> dict[str, str]:
    return {
        "strategy_code_hash": _src_hash(),
        "parameter_hash": sha256_json(parameter_contract()),
        "trigger_contract_hash": sha256_json(trigger_contract()),
        "confirmation_contract_hash": sha256_json(confirmation_contract()),
        "entry_contract_hash": sha256_json(entry_contract()),
        "sl_contract_hash": sha256_json(sl_contract()),
        "target_contract_hash": sha256_json(target_contract()),
        "session_contract_hash": sha256_json(session_contract()),
        "friction_contract_hash": sha256_json(friction_contract()),
        "strategy_contract_hash": sha256_json(strategy_contract()),
    }


STRATEGY_HASH = sha256_json(strategy_contract())
