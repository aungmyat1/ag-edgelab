"""ST_CRYPTO_MTF_SMC_V1 — multi-timeframe SMC state machine (research skeleton).

Status: RESEARCH_CANDIDATE / EDGE_VERIFIED=FALSE. This is a deterministic
research skeleton per the mission: primitives + ordinal stage machine + a
single declared baseline configuration. NO grid search, NO optimization,
NO live/demo execution, NO edge claims.

Semantic authority (strategy terms straight from the mission definition):

  LONG:   HTF_ELIGIBLE -> H1_POI_ACTIVE -> M15_SSL_SWEEP ->
          M5_BULLISH_CHOCH -> M5_DISPLACEMENT -> M5_BULLISH_FVG ->
          FVG_RETEST -> ENTRY -> EXIT
  SHORT:  symmetric (M15_BSL_SWEEP and M5_BEARISH_CHOCH/BULLISH->bearish FVG).

Primitive semantics (mission-mandated):
  * Confirmed swing — fractal pivot of fixed order; usable only after the
    final right-side bar CLOSES (anti-lookahead).
  * BOS — close beyond the most recently confirmed opposing swing.
  * Liquidity sweep — bar exceeds a reference liquidity level but closes
    back on the origin side (SSL sweep for longs, BSL for shorts).
  * CHoCH — directional close beyond the opposing internal swing.
  * Displacement — a bar whose body and range expand vs the median of the
    reference window by declared multipliers.
  * FVG — three-candle fair-value gap; usable after the third candle closes.
  * FVG retest — a later trade touching the FVG zone after it formed.
  * Structural SL — beyond the sweep extreme plus a tick buffer.
  * Opposing-liquidity TP — the most recent confirmed opposing swing on the
    liquidity timeframe.

Anti-lookahead implementation:
  * All structure/TF state updates are fed *closed* bars only, in order, via
    IncrementalStructure (H1/H4/M15/M5). Derived higher TFs are revealed to
    the machine only once their bucket is fully closed (never partial).
  * The machine consumes only state committed at or before the current M5
    close index. Candidates record `observed_at` = close timestamp of the
    driving M5 bar; repeat scans over the same input are byte-identical.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from dataclasses import replace
from typing import Iterable, Sequence

from ag_edgelab.contracts.intent import OrderIntent, OrderType, Side, Target
from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.engines.reference.replay import ReferenceReplayEngine
from ag_edgelab.temporal.state_machine import TemporalStateMachine, TemporalStage

STRATEGY_ID = "ST_CRYPTO_MTF_SMC_V1"
STRATEGY_VERSION = "0.1.0-research"
STRATEGY_STATUS = "RESEARCH_CANDIDATE"
EDGE_VERIFIED = False

REQUIRED_TIMEFRAMES = ("D1", "H4", "H1", "M15", "M5")


class Stage(StrEnum):
    HTF_ELIGIBLE = "HTF_ELIGIBLE"
    H1_POI_ACTIVE = "H1_POI_ACTIVE"
    M15_SSL_SWEEP = "M15_SSL_SWEEP"
    M5_BULLISH_CHOCH = "M5_BULLISH_CHOCH"
    M5_DISPLACEMENT = "M5_DISPLACEMENT"
    M5_BULLISH_FVG = "M5_BULLISH_FVG"
    FVG_RETEST = "FVG_RETEST"
    ENTRY = "ENTRY"
    EXIT = "EXIT"


# Long ordering; short reuses the same sequence (sweep side and CHoCH side flip).
LONG_STAGES: tuple[TemporalStage, ...] = (
    TemporalStage(Stage.HTF_ELIGIBLE.value, max_bars_in_stage=2016),
    TemporalStage(Stage.H1_POI_ACTIVE.value, max_bars_in_stage=2016),
    TemporalStage(Stage.M15_SSL_SWEEP.value, max_bars_in_stage=2016),
    TemporalStage(Stage.M5_BULLISH_CHOCH.value, max_bars_in_stage=288),
    TemporalStage(Stage.M5_DISPLACEMENT.value, max_bars_in_stage=1),
    TemporalStage(Stage.M5_BULLISH_FVG.value, max_bars_in_stage=1),
    TemporalStage(Stage.FVG_RETEST.value, max_bars_in_stage=288),
    TemporalStage(Stage.ENTRY.value, max_bars_in_stage=10**9),
    TemporalStage(Stage.EXIT.value, max_bars_in_stage=10**9),
)


@dataclass(frozen=True)
class SmcParameters:
    """Single declared baseline configuration (no tuning performed)."""

    # Confirmed swing geometry (fractal order): left/right bars each side.
    h4_swing_order: int = 2
    h1_swing_order: int = 2
    m15_swing_order: int = 2
    m5_swing_order: int = 2
    # HTF eligibility: H4 bullish/bearish BOS must be this fresh (H4 bars).
    htf_bos_max_age_bars: int = 30
    # D1 context: 3-day momentum sign gate (0 = disabled not allowed; fixed 3).
    d1_momentum_bars: int = 3
    # H1 POI = last closed H1 candle of opposite colour before the most
    # recent H1 close that set a poi_lookback-H1-bar closing extreme.
    poi_lookback_h1: int = 48
    # Displacement: window bars body/range >= mult * median of ref window.
    displacement_body_mult: float = 2.0
    displacement_range_mult: float = 1.8
    displacement_reference_bars: int = 50
    # FVG retest entry and structural geometry.
    sl_buffer_ticks: int = 2
    min_rr: float = 1.5
    retest_expiry_bars: int = 288
    # Stage expiries (driving timeframe = M5) come from LONG_STAGES.
    stage_expiries: tuple[int, ...] = tuple(stage.max_bars_in_stage for stage in LONG_STAGES)


BASELINE_PARAMETERS = SmcParameters()


# --------------------------------------------------------------------------
# Deterministic primitives
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SwingPoint:
    index: int              # bar index of the pivot candle
    price: float
    kind: str               # "HIGH" | "LOW"
    confirmed_index: int    # pivot is usable from confirmed_index's close


def confirmed_swing_points(bars: tuple[MarketBar, ...], order: int) -> tuple[SwingPoint, ...]:
    """Fractal pivots confirmed only after `order` bars have closed to the right.

    A pivot at index i is unknowable before bar i+order closes; consumers may
    use it only at close indices >= confirmed_index.
    """
    swings: list[SwingPoint] = []
    for i in range(order, len(bars) - order):
        window = bars[i - order : i + order + 1]
        center = bars[i]
        if all(center.high >= b.high for b in window) and any(center.high > b.high for j, b in enumerate(window) if j != order):
            swings.append(SwingPoint(index=i, price=center.high, kind="HIGH", confirmed_index=i + order))
        if all(center.low <= b.low for b in window) and any(center.low < b.low for j, b in enumerate(window) if j != order):
            swings.append(SwingPoint(index=i, price=center.low, kind="LOW", confirmed_index=i + order))
    return tuple(swings)


def last_confirmed_swing(swings: tuple[SwingPoint, ...], kind: str, asof_index: int) -> SwingPoint | None:
    """Most recent swing of `kind` knowable at bar `asof_index`'s close."""
    result = None
    for swing in swings:
        if swing.confirmed_index > asof_index:
            break
        if swing.kind == kind:
            result = swing
    return result


@dataclass(frozen=True)
class FairValueGap:
    index: int           # index of the third candle; FVG usable from its close
    direction: str       # "BULLISH" | "BEARISH"
    lower: float
    upper: float
    midpoint: float


def detect_fvg(bars: tuple[MarketBar, ...], start: int = 2) -> tuple[FairValueGap, ...]:
    """Three-candle FVG. Usable only after the third candle (index) closes."""
    out: list[FairValueGap] = []
    for i in range(max(2, start), len(bars)):
        a, c = bars[i - 2], bars[i]
        if c.low > a.high:
            out.append(FairValueGap(index=i, direction="BULLISH", lower=a.high, upper=c.low, midpoint=(a.high + c.low) / 2))
        elif c.high < a.low:
            out.append(FairValueGap(index=i, direction="BEARISH", lower=c.high, upper=a.low, midpoint=(c.high + a.low) / 2))
    return tuple(out)


def displacement_present(
    window: tuple[MarketBar, ...],
    reference: tuple[MarketBar, ...],
    body_mult: float,
    range_mult: float,
) -> bool:
    """Any window bar with body and range expansion vs medians of reference."""
    if not window or not reference:
        return False
    bodies = sorted(abs(b.close - b.open) for b in reference)
    ranges = sorted(b.high - b.low for b in reference)
    med_body = bodies[len(bodies) // 2]
    med_range = ranges[len(ranges) // 2]
    if med_body <= 0 or med_range <= 0:
        return False
    for bar in window:
        if abs(bar.close - bar.open) >= body_mult * med_body and (bar.high - bar.low) >= range_mult * med_range:
            return True
    return False


@dataclass(frozen=True)
class StructureState:
    """BOS/bias tracker over one timeframe, fed closed bars sequentially."""

    bias: str = "NEUTRAL"          # "BULLISH" | "BEARISH" | "NEUTRAL"
    last_bullish_bos_index: int = -1
    last_bearish_bos_index: int = -1
    swing_high: float | None = None
    swing_low: float | None = None
    swing_high_index: int = -1
    swing_low_index: int = -1


class IncrementalStructure:
    """Closed-bar incremental structure: swings confirm with a right-bar delay."""

    def __init__(self, bars: tuple[MarketBar, ...], swing_order: int) -> None:
        self._bars = bars
        self._order = swing_order
        self._fed = -1
        self.state = StructureState()

    def update(self, index: int) -> StructureState:
        """
        Feed all closed bars up to and including `index` (must be monotone).
        Re-feeding an already-fed index is a no-op (idempotent), never rewinds.
        """
        bars = self._bars
        order = self._order
        if index <= self._fed:
            return self.state
        for j in range(self._fed + 1, index + 1):
            # Confirm pivots whose right side is now complete (bar j closes).
            p = j - order
            if p >= order:
                window = bars[p - order : p + order + 1]
                center = window[order]
                if all(center.high >= b.high for b in window) and any(
                    center.high > b.high for k, b in enumerate(window) if k != order
                ):
                    self.state = StructureState(
                        bias=self.state.bias,
                        last_bullish_bos_index=self.state.last_bullish_bos_index,
                        last_bearish_bos_index=self.state.last_bearish_bos_index,
                        swing_high=center.high,
                        swing_low=self.state.swing_low,
                        swing_high_index=p,
                        swing_low_index=self.state.swing_low_index,
                    )
                if all(center.low <= b.low for b in window) and any(
                    center.low < b.low for k, b in enumerate(window) if k != order
                ):
                    self.state = StructureState(
                        bias=self.state.bias,
                        last_bullish_bos_index=self.state.last_bullish_bos_index,
                        last_bearish_bos_index=self.state.last_bearish_bos_index,
                        swing_high=self.state.swing_high,
                        swing_low=center.low,
                        swing_high_index=self.state.swing_high_index,
                        swing_low_index=p,
                    )
            # BOS on close (both directions recorded; opposite-side BOS flips bias).
            if self.state.swing_high is not None and j != self.state.swing_high_index and bars[j].close > self.state.swing_high:
                self.state = StructureState(
                    bias="BULLISH",
                    last_bullish_bos_index=j,
                    last_bearish_bos_index=self.state.last_bearish_bos_index,
                    swing_high=self.state.swing_high,
                    swing_low=self.state.swing_low,
                    swing_high_index=self.state.swing_high_index,
                    swing_low_index=self.state.swing_low_index,
                )
            if self.state.swing_low is not None and j != self.state.swing_low_index and bars[j].close < self.state.swing_low:
                self.state = StructureState(
                    bias="BEARISH",
                    last_bullish_bos_index=self.state.last_bullish_bos_index,
                    last_bearish_bos_index=j,
                    swing_high=self.state.swing_high,
                    swing_low=self.state.swing_low,
                    swing_high_index=self.state.swing_high_index,
                    swing_low_index=self.state.swing_low_index,
                )
        self._fed = index
        return self.state


# --------------------------------------------------------------------------
# Dev backtest scanner (single declared baseline; no optimization)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CandidateLog:
    machine_id: str
    direction: str
    armed_at: datetime
    transitions: tuple
    status: str
    rejection_code: str | None
    intent: OrderIntent | None = None


class MtfSmcScanner:
    """Event scanner driving per-candidate temporal machines on closed bars."""

    def __init__(
        self,
        m5_bars: tuple[MarketBar, ...],
        frames: dict[str, tuple[MarketBar, ...]],
        params: SmcParameters = BASELINE_PARAMETERS,
        instrument: str = "BTCUSDT",
        tick_size: float = 0.1,
    ) -> None:
        self.m5 = m5_bars
        self.frames = frames
        self.params = params
        self.instrument = instrument
        self.tick = tick_size

    # --- incremental per-timeframe structure, mapped to M5 indices ---------

    def _tf_indices_by_m5(self, tf_bars: tuple[MarketBar, ...]) -> list[int]:
        """
        For each M5 index j, the latest CLOSED tf-bar index whose close time is
        <= the M5 bar's close. tf bars with the same open share the M5 close;
        only the fully-closed tf bar is reachable.
        """
        m5 = self.m5
        mapping = [-1] * len(m5)
        tf = 0
        for j, bar in enumerate(m5):
            m5_close = bar.timestamp + timedelta(minutes=5)
            while tf < len(tf_bars) and (tf_bars[tf].timestamp + self._tf_step(tf_bars)) <= m5_close:
                tf += 1
            mapping[j] = tf - 1
        return mapping

    @staticmethod
    def _tf_step(bars: tuple[MarketBar, ...]) -> timedelta:
        if len(bars) >= 2:
            return bars[1].timestamp - bars[0].timestamp
        # Fallback by naming convention (never used with real frames).
        return timedelta(minutes=1)

    def scan(self) -> tuple[tuple[OrderIntent, ...], tuple[CandidateLog, ...], dict[str, int]]:
        p = self.params
        m5 = self.m5

        # Incremental structure trackers per execution timeframe.
        struct: dict[str, IncrementalStructure] = {}
        for tf in ("M15", "H1", "H4"):
            struct[tf] = IncrementalStructure(self.frames[tf], getattr(p, f"{tf.lower()}_swing_order"))
        m5_struct = IncrementalStructure(m5, p.m5_swing_order)
        d1_closes: list[float] = []
        tf_to_m5 = {tf: self._tf_indices_by_m5(bs) for tf, bs in self.frames.items()}

        intents: list[OrderIntent] = []
        candidates: list[CandidateLog] = []
        rejections: dict[str, int] = {}

        serial = 0
        prev_h1_fed = -2
        pre_poi_long_active = False
        pre_poi_short_active = False
        pre_poi_low: float | None = None
        pre_poi_high: float | None = None

        # Direction state machine lane (one machine active at a time; first
        # come first served, deterministic bar scan).
        ribbon = None  # (machine, direction, sweep_extreme, sweep_index, htf_poi_ref)
        machine: TemporalStateMachine | None = None
        direction: str | None = None
        stage_context: dict[str, float | int | None] = {}
        pending_intent: OrderIntent | None = None   # committed at FVG touch; fill pending
        filled_price: float | None = None           # set when the pending intent fills

        def reject(code: str) -> None:
            nonlocal machine, direction, stage_context, pending_intent, filled_price
            machine.reject(code)
            candidates.append(
                CandidateLog(
                    machine_id=machine.machine_id,
                    direction=direction or "LONG",
                    armed_at=m5[0].timestamp if not candidates else m5[0].timestamp,
                    transitions=tuple(machine.transitions),
                    status=machine.status.value,
                    rejection_code=code,
                )
            )
            rejections[code] = rejections.get(code, 0) + 1
            machine = None
            direction = None
            stage_context = {}
            pending_intent = None
            filled_price = None

        def complete(intent: OrderIntent | None) -> None:
            nonlocal machine, direction, stage_context, pending_intent, filled_price
            # Status is COMPLETE already: EXIT is the final stage and
            # advance() set it. Record the candidate for the audit trail.
            candidates.append(
                CandidateLog(
                    machine_id=machine.machine_id,
                    direction=direction or "LONG",
                    armed_at=m5[0].timestamp if not candidates else m5[0].timestamp,
                    transitions=tuple(machine.transitions),
                    status=machine.status.value,
                    rejection_code=None,
                    intent=intent,
                )
            )
            machine = None
            direction = None
            stage_context = {}
            pending_intent = None
            filled_price = None

        for j, bar in enumerate(m5):
            close_j = bar.timestamp + timedelta(minutes=5)
            # POI availability computed from the last COMPLETED H1 close (the
            # pre_ snapshot from the previous loop step; recomputed below when
            # a new H1 bar closes before this M5 bar's close).
            poi_long_active = pre_poi_long_active
            poi_short_active = pre_poi_short_active
            poi_low, poi_high = pre_poi_low, pre_poi_high

            # Feed incremental per-TF structures with bars closed at close_j.
            fed: dict[str, int] = {}
            for tf in ("M15", "H1", "H4"):
                idx = tf_to_m5[tf][j]
                fed[tf] = idx
                struct[tf].update(idx)  # no-op if not yet closed
            m5_struct.update(j)  # M5 bar j is closed at this loop step by construction
            d1_idx = tf_to_m5["D1"][j]
            if d1_idx >= 0 and (j == 0 or tf_to_m5["D1"][j - 1] != d1_idx):
                d1_closes.append(self.frames["D1"][d1_idx].close)
            fed["D1"] = d1_idx

            # ---- POI bookkeeping (H1): rebuild when a NEW H1 bar has closed.
            # The pre_* snapshot is what arming sees this bar (strictly, a POI
            # derived from the last H1 close -- never from the open current H1).
            h1 = struct["H1"]
            h1_bars = self.frames["H1"]
            h1_now = h1._fed
            if h1_now > prev_h1_fed:
                pre_poi_long_active = False
                pre_poi_short_active = False
            if h1_now > prev_h1_fed and h1_now >= p.poi_lookback_h1:
                # Active H1 POI = the most recent opposite-colour closed candle
                # before the latest close that set a lookback-window closing
                # extreme. Recomputed deterministically from committed state.
                window = h1_bars[h1_now - p.poi_lookback_h1 + 1 : h1_now + 1]
                closes = [b.close for b in window]
                max_i = max(range(len(closes)), key=lambda i: closes[i])
                min_i = min(range(len(closes)), key=lambda i: closes[i])
                if max_i > min_i:  # bull run: POI below price — demand
                    for k in range(max_i - 1, -1, -1):
                        b = window[k]
                        if b.close < b.open:
                            pre_poi_long_active = True
                            pre_poi_low, pre_poi_high = b.low, b.high
                            break
                if min_i > max_i:
                    for k in range(min_i - 1, -1, -1):
                        b = window[k]
                        if b.close > b.open:
                            pre_poi_short_active = True
                            pre_poi_low, pre_poi_high = b.low, b.high
                            break
            prev_h1_fed = h1_now

            # ---- Candidate arming (HTF eligibility).
            if machine is None:
                htf = struct["H4"].state
                bias_ok_long = htf.bias == "BULLISH" and htf.last_bullish_bos_index >= 0 and (fed["H4"] - htf.last_bullish_bos_index) <= p.htf_bos_max_age_bars
                bias_ok_short = htf.bias == "BEARISH" and htf.last_bearish_bos_index >= 0 and (fed["H4"] - htf.last_bearish_bos_index) <= p.htf_bos_max_age_bars
                d1_ok_long = d1_ok_short = True
                if len(d1_closes) > p.d1_momentum_bars:
                    mom = d1_closes[-1] - d1_closes[-1 - p.d1_momentum_bars]
                    d1_ok_long = mom > 0
                    d1_ok_short = mom < 0

                cand_dir = None
                if bias_ok_long and d1_ok_long and poi_long_active:
                    cand_dir = "LONG"
                    active_poi_low, active_poi_high = poi_low, poi_high
                elif bias_ok_short and d1_ok_short and poi_short_active:
                    cand_dir = "SHORT"
                    active_poi_low, active_poi_high = poi_low, poi_high
                if cand_dir is not None:
                    serial += 1
                    machine = TemporalStateMachine(f"{STRATEGY_ID}-{serial:05d}", LONG_STAGES)
                    machine.arm(j)
                    direction = cand_dir
                    stage_context = {
                        "poi_low": active_poi_low,
                        "poi_high": active_poi_high,
                    }
                    machine.advance(Stage.HTF_ELIGIBLE.value, observed_at=close_j, driving_bar_index=j)

            # ---- Stage progression.
            if machine is not None:
                if machine.expire_check(j):
                    reject(machine.rejection_code)
                    continue

                # Causal fill/exit simulation for a committed (pending) intent.
                # Identical rules + order as ReferenceReplayEngine: limit fill
                # on touch with the fill bar included in exit processing;
                # stop checked before target every bar (conservative same-bar
                # SL/TP policy). Offline PnL replays with the same engine, so
                # scanner and runner agree exactly.
                if pending_intent is not None:
                    if filled_price is None:
                        if ReferenceReplayEngine._entry_touched(pending_intent, bar, pending_intent.entry_price):
                            filled_price = pending_intent.entry_price
                            machine.advance(Stage.ENTRY.value, observed_at=close_j, driving_bar_index=j)
                            intents.append(pending_intent)
                    if filled_price is not None:
                        side = pending_intent.side
                        stop = pending_intent.stop_price
                        target_price = pending_intent.targets[0].price
                        if ReferenceReplayEngine._stop_hit(side, stop, bar) or ReferenceReplayEngine._target_hit(pending_intent, bar, target_price):
                            machine.advance(Stage.EXIT.value, observed_at=close_j, driving_bar_index=j)
                            complete(pending_intent)
                            continue

                cur = machine.current_stage.stage_id if machine.current_stage else None

                if cur == Stage.H1_POI_ACTIVE.value:
                    # POI validity: latest H1 close must not void the zone.
                    zone_low, zone_high = stage_context["poi_low"], stage_context["poi_high"]
                    voided = bar.close < zone_low if direction == "LONG" else bar.close > zone_high
                    if voided:
                        reject("H1_POI_VOIDED")
                        continue
                    machine.advance(Stage.H1_POI_ACTIVE.value, observed_at=close_j, driving_bar_index=j)

                elif cur == Stage.M15_SSL_SWEEP.value:
                    m15 = struct["M15"].state
                    ref = m15.swing_low if direction == "LONG" else m15.swing_high
                    if ref is not None:
                        tf_bar = self.frames["M15"][fed["M15"]]
                        if fed["M15"] >= 0:
                            if direction == "LONG":
                                swept = tf_bar.low < ref and tf_bar.close > ref
                                if swept and tf_bar.low <= stage_context["poi_high"]:
                                    stage_context["sweep_extreme"] = tf_bar.low
                                    stage_context["sweep_index"] = j
                                    machine.advance(Stage.M15_SSL_SWEEP.value, observed_at=close_j, driving_bar_index=j)
                            else:
                                swept = tf_bar.high > ref and tf_bar.close < ref
                                if swept and tf_bar.high >= stage_context["poi_low"]:
                                    stage_context["sweep_extreme"] = tf_bar.high
                                    stage_context["sweep_index"] = j
                                    machine.advance(Stage.M15_SSL_SWEEP.value, observed_at=close_j, driving_bar_index=j)

                elif cur == Stage.M5_BULLISH_CHOCH.value:
                    m5s = m5_struct.state
                    want_close = (m5s.swing_high if direction == "LONG" else m5s.swing_low)
                    if want_close is not None:
                        choch = (bar.close > want_close) if direction == "LONG" else (bar.close < want_close)
                        if choch and j > stage_context["sweep_index"]:
                            # Displacement must exist across the impulse window
                            # between the sweep and this CHoCH bar.
                            ref_start = max(0, stage_context["sweep_index"] - p.displacement_reference_bars)
                            window = m5[stage_context["sweep_index"] : j + 1]
                            reference = m5[ref_start : stage_context["sweep_index"]]
                            if not displacement_present(tuple(window), tuple(reference), p.displacement_body_mult, p.displacement_range_mult):
                                reject("NO_DISPLACEMENT_IN_MOVE")
                                continue
                            machine.advance(Stage.M5_BULLISH_CHOCH.value, observed_at=close_j, driving_bar_index=j)
                            machine.advance(Stage.M5_DISPLACEMENT.value, observed_at=close_j, driving_bar_index=j)

                            # FVG must now exist within the displacement window
                            # ending at this bar.
                            want_dir = "BULLISH" if direction == "LONG" else "BEARISH"
                            fvgs = [g for g in detect_fvg(m5, start=max(2, stage_context["sweep_index"] + 1)) if g.index <= j and g.direction == want_dir]
                            if not fvgs:
                                reject("NO_FVG_IN_DISPLACEMENT")
                                continue
                            # Entry FVG = the FIRST direction-matched gap
                            # formed after the sweep (the engine gap).
                            latest = fvgs[0]
                            stage_context["fvg_lower"] = latest.lower
                            stage_context["fvg_upper"] = latest.upper
                            stage_context["fvg_index"] = latest.index
                            machine.advance(Stage.M5_BULLISH_FVG.value, observed_at=close_j, driving_bar_index=j)

                            # Entry at FVG midpoint; SL beyond the sweep extreme;
                            # TP at opposing liquidity (M15 confirmed swing).
                            entry = latest.midpoint
                            sl = (stage_context["sweep_extreme"] - p.sl_buffer_ticks * self.tick) if direction == "LONG" else (stage_context["sweep_extreme"] + p.sl_buffer_ticks * self.tick)
                            tp_ref = struct["M15"].state.swing_high if direction == "LONG" else struct["M15"].state.swing_low
                            if tp_ref is None:
                                reject("NO_OPPOSING_LIQUIDITY")
                                continue
                            if direction == "LONG" and tp_ref <= entry:
                                reject("TARGET_NOT_BEYOND_ENTRY")
                                continue
                            if direction == "SHORT" and tp_ref >= entry:
                                reject("TARGET_NOT_BEYOND_ENTRY")
                                continue
                            risk = abs(entry - sl)
                            rr = abs(tp_ref - entry) / risk if risk > 0 else 0.0
                            # Inclusive geometry sanity: SL must sit on the
                            # correct side of entry (zero-risk or inverted
                            # geometry is a rejection, never an exception).
                            if direction == "LONG" and sl >= entry:
                                reject("GEOMETRY_INVALID_SL_SIDE")
                                continue
                            if direction == "SHORT" and sl <= entry:
                                reject("GEOMETRY_INVALID_SL_SIDE")
                                continue
                            if risk <= 0:
                                reject("GEOMETRY_INVALID")
                                continue
                            if rr < p.min_rr:
                                reject("RR_BELOW_MIN")
                                continue
                            stage_context["entry"] = entry
                            stage_context["sl"] = sl
                            stage_context["tp"] = tp_ref

                elif cur == Stage.FVG_RETEST.value and pending_intent is None:
                    lo, hi = stage_context["fvg_lower"], stage_context["fvg_upper"]
                    if bar.low <= hi and bar.high >= lo:
                        machine.advance(Stage.FVG_RETEST.value, observed_at=close_j, driving_bar_index=j)
                        intent = OrderIntent(
                            candidate_id=machine.machine_id,
                            instrument=self.instrument,
                            created_at=close_j,
                            side=Side.LONG if direction == "LONG" else Side.SHORT,
                            order_type=OrderType.LIMIT,
                            entry_price=stage_context["entry"],
                            stop_price=stage_context["sl"],
                            targets=(Target(price=stage_context["tp"], allocation=1.0),),
                            expire_after_bars=p.retest_expiry_bars,
                        )
                        pending_intent = intent
                        continue

        # Flush any still-open machine deterministically. Machines with a
        # committed (filled) intent are not "rejected" — the intent stands and
        # the ledger classifies it as open-at-end; unfilled ones expire.
        if machine is not None:
            if pending_intent is not None and filled_price is not None:
                machine.reject("DATA_ENDED_open_position")
                candidates.append(
                    CandidateLog(
                        machine_id=machine.machine_id,
                        direction=direction or "LONG",
                        armed_at=armed_at,
                        transitions=tuple(machine.transitions),
                        status=machine.status.value,
                        rejection_code="DATA_ENDED_open_position",
                        intent=pending_intent,
                    )
                )
                rejections["DATA_ENDED_open_position"] = rejections.get("DATA_ENDED_open_position", 0) + 1
            else:
                reject("DATA_ENDED_unfilled")

        return tuple(intents), tuple(candidates), rejections
