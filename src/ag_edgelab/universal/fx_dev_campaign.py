"""Universal Funnel V0.3 — first authoritative FX DEVELOPMENT experiment.

Direction-first capability diagnosis on real HistData 2017 DEV data:

    RAW_OBSERVATIONS -> DIRECTION_DECIDED -> DIRECTION_NON_NEUTRAL
      -> LOCATION_AVAILABLE -> LOCATION_ALIGNED -> CONFIRMATION_AVAILABLE
      -> ENTRY_AVAILABLE -> 1R..5R

The V0.3 engines are reused unchanged; this module only orchestrates them
on the recovered M1 lineage. Capability semantics:

  * OPPORTUNITY basis — shared diagnostic geometry at OBSERVATION time
    (stop = 12-M15-bar opposite extreme), identical for every population;
    uplifts are computed ONLY inside this basis.
  * ENTRY_CONDITIONED basis — geometry at the confirmation bar; reported
    separately and NEVER compared to the opportunity basis as "uplift"
    (UPLIFT = null, REASON = INCOMPARABLE_CAPABILITY_SEMANTICS).

No optimization, no economics, no OOS, no holdout, no execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Sequence

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.universal.confirmation import (ConfirmationPrimitive, SetupAlignment,
                                               classify_alignment, engulfing_event,
                                               evening_star_event, morning_star_event,
                                               pin_bar_event, structure_shift_events)
from ag_edgelab.universal.direction import Direction
from ag_edgelab.universal.fx_direction import (DirectionContext, FlowSeries, MaSeries,
                                               MeanRangeSeries, StructuralSeries,
                                               evaluate_direction_hypotheses,
                                               DIRECTION_HYPOTHESES,
                                               PRIMARY_FUNNEL_HYPOTHESIS)
from ag_edgelab.universal.matrix import CAPABILITY_BASIS
from ag_edgelab.universal.targets import (EntryGeometry, FIXED_R_TARGETS, compute_excursions,
                                          natural_target_r)

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Preregistered campaign constants (frozen; never searched)
# ---------------------------------------------------------------------------

OBS_WARMUP_DAYS = 21              # context warm-up inside the DEV partition
OBS_MINUTE = 0                    # hourly observation grid (top of hour, UTC)
CONFIRMATION_WINDOW_BARS = 16     # 4 traded hours of M15 feed bars
OUTCOME_HORIZON_BARS = 96         # 24 traded hours of M15 feed bars
STOP_LOOKBACK_BARS = 12           # diagnostic/entry stop = opposite extreme
LEVEL_TOL_FRACTION = 0.25         # zone half-width = 0.25 * trailing mean range
EQUAL_TOL_FRACTION = 0.10         # equal highs/lows pool tolerance
SD_BODY_MULT = 2.0                # displacement body multiple (V0.3 contract)
DESIRED_TARGET_R = 3.0            # frozen fixed target examined by root cause

ENTRY_CONDITIONED_BASIS = "MFE_R_REACH_2.0R_ENTRY_CONDITIONED_GEOMETRY_V1"
INCOMPARABLE_REASON = "INCOMPARABLE_CAPABILITY_SEMANTICS"

# Root-cause thresholds (preregistered).
MIN_SEPARATION_PP = 5.0           # CASE A floor for useful direction separation
LOCATION_DROP_PP = 5.0            # CASE B: location selects badly
CONFIRMATION_DROP_PP = 10.0       # CASE C: confirmation destroys capability
CONTINUATION_REACH_3R_MIN = 0.25  # CASE D: continuation collapse floor
CONTINUATION_REACH_1R_MIN = 0.50  # CASE D requires healthy 1R first
MIN_DIRECTIONAL_N = 200           # pooled sample floors (else INSUFFICIENT)
MIN_ENTERED_N = 30

FUNNEL_STAGES = ("RAW_OBSERVATIONS", "DIRECTION_DECIDED", "DIRECTION_NON_NEUTRAL",
                 "LOCATION_AVAILABLE", "LOCATION_ALIGNED", "CONFIRMATION_AVAILABLE",
                 "ENTRY_AVAILABLE", "R1", "R2", "R3", "R4", "R5")


@dataclass(frozen=True)
class FxObservation:
    symbol: str
    feed_index: int
    observed_at: datetime
    price: float
    directions: dict                    # D01..D10 -> Direction value (str)
    mfe_long: float | None              # opportunity basis, long geometry
    mfe_short: float | None             # opportunity basis, short geometry
    primary_direction: str              # PRIMARY_FUNNEL_HYPOTHESIS decision
    location_state: str                 # ALIGNED | MISMATCH_RECORDED | UNAVAILABLE | NOT_EVALUATED
    location_families_hit: tuple
    confirmation_primitive: str | None
    confirmation_alignment: str | None  # ALIGNED | COUNTER_DIRECTION | NEUTRAL
    candle_primitives_in_window: tuple
    entered: bool
    entry_mfe_r: float | None
    entry_mae_r: float | None
    fixed_reached: dict                 # k -> bool
    natural_targets: dict               # family -> TARGET_R


@dataclass(frozen=True)
class SymbolCampaign:
    symbol: str
    raw_observations: int
    observations: tuple
    funnel: tuple                       # ({stage, n, pct_of_previous}, ...)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _decided_mfe(obs: FxObservation, direction: str) -> float | None:
    if direction == Direction.BULL.value:
        return obs.mfe_long
    if direction == Direction.BEAR.value:
        return obs.mfe_short
    return None


def _opposite_mfe(obs: FxObservation, direction: str) -> float | None:
    if direction == Direction.BULL.value:
        return obs.mfe_short
    if direction == Direction.BEAR.value:
        return obs.mfe_long
    return None


def reach_share(values: Sequence[float | None], threshold: float = 2.0) -> float | None:
    measured = [v for v in values if v is not None]
    if not measured:
        return None
    return sum(1 for v in measured if v >= threshold) / len(measured)


def _cut_series(frame: tuple[MarketBar, ...], minutes: int) -> "list[datetime]":
    return [b.timestamp + timedelta(minutes=minutes) for b in frame]


def _precompute_sd_zones(h4: tuple[MarketBar, ...]) -> list[tuple[int, str, float, float]]:
    """(created_index, side, lo, hi) demand/supply zones — V0.3 contract."""
    bodies = [abs(b.close - b.open) for b in h4]
    zones: list[tuple[int, str, float, float]] = []
    for i in range(20, len(h4)):
        window = sorted(bodies[i - 20: i])
        med = window[len(window) // 2]
        if med <= 0 or bodies[i] < SD_BODY_MULT * med:
            continue
        bar, origin = h4[i], h4[i - 1]
        if bar.close > bar.open and origin.close < origin.open:
            zones.append((i, "SUPPORT", origin.low, origin.high))
        elif bar.close < bar.open and origin.close > origin.open:
            zones.append((i, "RESISTANCE", origin.low, origin.high))
    return zones


# ---------------------------------------------------------------------------
# series bundle + observation context (shared by campaign AND causality audit)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SeriesBundle:
    s_h1: StructuralSeries
    s_h4: StructuralSeries
    s_d1: StructuralSeries
    flow_h1: FlowSeries
    ma_h1: MaSeries
    mr_h4: MeanRangeSeries
    sd_zones: tuple


def build_series(frames: dict) -> SeriesBundle:
    return SeriesBundle(
        s_h1=StructuralSeries(frames["H1"]), s_h4=StructuralSeries(frames["H4"]),
        s_d1=StructuralSeries(frames["D1"]), flow_h1=FlowSeries(frames["H1"]),
        ma_h1=MaSeries(frames["H1"]), mr_h4=MeanRangeSeries(frames["H4"]),
        sd_zones=tuple(_precompute_sd_zones(frames["H4"])))


def context_at(bundle: SeriesBundle, c_d1: int, c_h4: int, c_h1: int,
               price: float) -> tuple[DirectionContext, dict]:
    """DirectionContext + location extras at explicit closed-bar cuts."""
    tol = LEVEL_TOL_FRACTION * bundle.mr_h4.at(c_h4)
    eq_tol = EQUAL_TOL_FRACTION * bundle.mr_h4.at(c_h4)
    range_high, range_low = bundle.s_h4.range_high[c_h4], bundle.s_h4.range_low[c_h4]
    if range_high is not None and range_low is not None and range_high > range_low:
        mid = (range_high + range_low) / 2.0
        pd_state = "DISCOUNT" if price < mid else ("PREMIUM" if price > mid else "EQUILIBRIUM")
    else:
        pd_state = None
    recent_highs = bundle.s_h4.recent_highs(c_h4)
    recent_lows = bundle.s_h4.recent_lows(c_h4)
    liq_bull = any(abs(price - lo) <= tol for lo in recent_lows) or any(
        abs(a - b) <= eq_tol and abs(price - min(a, b)) <= tol
        for a, b in zip(recent_lows, recent_lows[1:]))
    liq_bear = any(abs(price - hi) <= tol for hi in recent_highs) or any(
        abs(a - b) <= eq_tol and abs(price - max(a, b)) <= tol
        for a, b in zip(recent_highs, recent_highs[1:]))
    ctx = DirectionContext(
        d1=bundle.s_d1.at(c_d1), h4=bundle.s_h4.at(c_h4), h1=bundle.s_h1.at(c_h1),
        premium_discount=pd_state, h1_flow=bundle.flow_h1.at(c_h1),
        liquidity_support_bull=liq_bull, liquidity_support_bear=liq_bear,
        ma=bundle.ma_h1.at(c_h1))
    extras = {"tol": tol, "eq_tol": eq_tol, "pd_state": pd_state,
              "range_high": range_high, "range_low": range_low,
              "recent_highs": recent_highs, "recent_lows": recent_lows}
    return ctx, extras


def decisions_from_truncated_frames(frames: dict, as_of: datetime, price: float) -> dict:
    """Independent recomputation for the causality audit: rebuild every series
    from frames truncated to bars CLOSED at or before `as_of` and evaluate all
    hypotheses at the final index. Equality with the streaming campaign value
    proves truncation/future-mutation invariance."""
    from ag_edgelab.data.fx_histdata_2017 import bars_closed_at
    truncated = {tf: bars_closed_at(frames[tf], tf, as_of) for tf in ("H1", "H4", "D1")}
    if any(len(v) == 0 for v in truncated.values()):
        raise ValueError("audit point before frame availability")
    bundle = build_series(truncated)
    ctx, _ = context_at(bundle, len(truncated["D1"]) - 1, len(truncated["H4"]) - 1,
                        len(truncated["H1"]) - 1, price)
    return {k: v.value for k, v in evaluate_direction_hypotheses(ctx).items()}


# ---------------------------------------------------------------------------
# per-symbol campaign
# ---------------------------------------------------------------------------

def run_fx_symbol_campaign(
    frames: dict, symbol: str, eval_start: datetime, eval_end: datetime,
) -> SymbolCampaign:
    """Run the direction-first funnel for one symbol on DEV frames only."""
    m15: tuple[MarketBar, ...] = frames["M15"]
    h1, h4, d1 = frames["H1"], frames["H4"], frames["D1"]

    bundle = build_series(frames)
    s_h4 = bundle.s_h4
    sd_zones = bundle.sd_zones

    m15_events = structure_shift_events(m15, "M15")
    events_by_index: dict[int, list] = {}
    for event in m15_events:
        events_by_index.setdefault(event.index, []).append(event)

    close_h1 = _cut_series(h1, 60)
    close_h4 = _cut_series(h4, 240)
    close_d1 = _cut_series(d1, 1440)

    warm_start = eval_start + timedelta(days=OBS_WARMUP_DAYS)
    last_index = len(m15) - OUTCOME_HORIZON_BARS - CONFIRMATION_WINDOW_BARS - 1

    observations: list[FxObservation] = []
    raw = 0
    c_h1 = c_h4 = c_d1 = -1

    for i, bar in enumerate(m15):
        ts = bar.timestamp
        if ts.minute != OBS_MINUTE or ts < warm_start or ts >= eval_end or i > last_index:
            continue
        raw += 1
        t = ts + timedelta(minutes=15)
        while c_h1 + 1 < len(h1) and close_h1[c_h1 + 1] <= t:
            c_h1 += 1
        while c_h4 + 1 < len(h4) and close_h4[c_h4 + 1] <= t:
            c_h4 += 1
        while c_d1 + 1 < len(d1) and close_d1[c_d1 + 1] <= t:
            c_d1 += 1
        if c_h1 < 0 or c_h4 < 0 or c_d1 < 0:
            continue  # not DECIDED: context frames not yet available

        price = bar.close
        ctx, extras = context_at(bundle, c_d1, c_h4, c_h1, price)
        tol = extras["tol"]
        pd_state = extras["pd_state"]
        range_high, range_low = extras["range_high"], extras["range_low"]
        recent_highs, recent_lows = extras["recent_highs"], extras["recent_lows"]
        directions = {k: v.value for k, v in evaluate_direction_hypotheses(ctx).items()}

        # -------- opportunity-basis diagnostics (both sides, same geometry rule)
        lo12 = min(b.low for b in m15[max(0, i - STOP_LOOKBACK_BARS + 1): i + 1])
        hi12 = max(b.high for b in m15[max(0, i - STOP_LOOKBACK_BARS + 1): i + 1])
        forward = m15[i + 1: i + 1 + OUTCOME_HORIZON_BARS]
        mfe_long = mfe_short = None
        if price - lo12 > 0:
            mfe_long = compute_excursions(forward, EntryGeometry(Direction.BULL, price, lo12),
                                          OUTCOME_HORIZON_BARS).mfe_r
        if hi12 - price > 0:
            mfe_short = compute_excursions(forward, EntryGeometry(Direction.BEAR, price, hi12),
                                           OUTCOME_HORIZON_BARS).mfe_r

        # -------- primary funnel chain (preregistered D01 authority) ----------
        primary = directions[PRIMARY_FUNNEL_HYPOTHESIS]
        location_state = "NOT_EVALUATED"
        families_hit: tuple = ()
        confirmation_primitive = None
        confirmation_alignment = None
        candle_hits: tuple = ()
        entered = False
        entry_mfe = entry_mae = None
        fixed_reached: dict[int, bool] = {k: False for k in FIXED_R_TARGETS}
        natural: dict[str, float] = {}

        if primary != Direction.NEUTRAL.value:
            support_zones: list[tuple[str, float, float]] = []
            resist_zones: list[tuple[str, float, float]] = []
            if range_low is not None:
                support_zones.append(("STRUCTURAL_LEVEL", range_low - tol, range_low + tol))
            if range_high is not None:
                resist_zones.append(("STRUCTURAL_LEVEL", range_high - tol, range_high + tol))
            for created, side, lo, hi in sd_zones:
                if created <= c_h4:
                    (support_zones if side == "SUPPORT" else resist_zones).append(
                        ("SUPPLY_DEMAND", lo, hi))
            for lo_price in recent_lows:
                support_zones.append(("LIQUIDITY_LEVEL", lo_price - tol, lo_price + tol))
            for hi_price in recent_highs:
                resist_zones.append(("LIQUIDITY_LEVEL", hi_price - tol, hi_price + tol))

            relevant = support_zones if primary == Direction.BULL.value else resist_zones
            available = bool(support_zones or resist_zones or pd_state is not None)
            hits = sorted({fam for fam, lo, hi in relevant if lo <= price <= hi})
            pd_aligned = (primary == Direction.BULL.value and pd_state == "DISCOUNT") or \
                         (primary == Direction.BEAR.value and pd_state == "PREMIUM")
            if pd_aligned:
                hits.append("PREMIUM_DISCOUNT")
            families_hit = tuple(hits)
            if not available:
                location_state = "UNAVAILABLE"
            elif hits:
                location_state = "ALIGNED"
            else:
                # midrange / opposing-location observation — recorded, not dropped
                location_state = "MISMATCH_RECORDED"

            # ---- confirmation scan (recorded for every directional obs) ------
            primary_dir = Direction(primary)
            first_event = None
            candles = set()
            for j in range(i + 1, min(i + 1 + CONFIRMATION_WINDOW_BARS, len(m15))):
                if first_event is None:
                    for event in events_by_index.get(j, ()):
                        if event.primitive in (ConfirmationPrimitive.MSS, ConfirmationPrimitive.BOS):
                            first_event = event
                            break
                for fn in (engulfing_event, pin_bar_event, morning_star_event, evening_star_event):
                    pattern = fn(m15, "M15", j)
                    if pattern is not None:
                        candles.add(pattern.primitive.value)
            candle_hits = tuple(sorted(candles))
            if first_event is not None:
                confirmation_primitive = first_event.primitive.value
                alignment = classify_alignment(primary_dir, first_event.direction)
                confirmation_alignment = alignment.value

                if location_state == "ALIGNED" and alignment == SetupAlignment.ALIGNED:
                    e_idx = first_event.index
                    entry_price = m15[e_idx].close
                    window = m15[max(0, e_idx - STOP_LOOKBACK_BARS + 1): e_idx + 1]
                    stop = min(b.low for b in window) if primary_dir == Direction.BULL \
                        else max(b.high for b in window)
                    if abs(entry_price - stop) > 0:
                        geometry = EntryGeometry(primary_dir, entry_price, stop)
                        outcome = compute_excursions(m15[e_idx + 1: e_idx + 1 + OUTCOME_HORIZON_BARS],
                                                     geometry, OUTCOME_HORIZON_BARS)
                        entered = True
                        entry_mfe, entry_mae = outcome.mfe_r, outcome.mae_r
                        fixed_reached = outcome.fixed_target_reached
                        # natural geometry: PDH/PDL + next confirmed H4 swing
                        prev_day = d1[c_d1]
                        pd_level = prev_day.high if primary_dir == Direction.BULL else prev_day.low
                        if (primary_dir == Direction.BULL and pd_level > entry_price) or \
                                (primary_dir == Direction.BEAR and pd_level < entry_price):
                            natural["PDH_PDL"] = natural_target_r(entry_price, stop, pd_level)
                        swings = recent_highs if primary_dir == Direction.BULL else recent_lows
                        beyond = [s for s in swings if (s > entry_price) == (primary_dir == Direction.BULL)]
                        if beyond:
                            natural["NEXT_SWING"] = natural_target_r(entry_price, stop, beyond[-1])

        observations.append(FxObservation(
            symbol=symbol, feed_index=i, observed_at=t, price=price,
            directions=directions, mfe_long=mfe_long, mfe_short=mfe_short,
            primary_direction=primary, location_state=location_state,
            location_families_hit=families_hit,
            confirmation_primitive=confirmation_primitive,
            confirmation_alignment=confirmation_alignment,
            candle_primitives_in_window=candle_hits,
            entered=entered, entry_mfe_r=entry_mfe, entry_mae_r=entry_mae,
            fixed_reached=fixed_reached, natural_targets=natural))

    funnel = build_funnel(observations, raw)
    return SymbolCampaign(symbol=symbol, raw_observations=raw,
                          observations=tuple(observations), funnel=funnel)


# ---------------------------------------------------------------------------
# funnel + comparisons + root cause
# ---------------------------------------------------------------------------

def build_funnel(observations: Sequence[FxObservation], raw: int) -> tuple:
    decided = list(observations)
    non_neutral = [o for o in decided if o.primary_direction != "NEUTRAL"]
    loc_avail = [o for o in non_neutral if o.location_state in ("ALIGNED", "MISMATCH_RECORDED")]
    loc_aligned = [o for o in loc_avail if o.location_state == "ALIGNED"]
    conf_avail = [o for o in loc_aligned if o.confirmation_primitive is not None]
    entered = [o for o in conf_avail if o.entered]
    counts = [raw, len(decided), len(non_neutral), len(loc_avail), len(loc_aligned),
              len(conf_avail), len(entered)]
    for k in FIXED_R_TARGETS:
        counts.append(sum(1 for o in entered if o.fixed_reached.get(k, False)))
    rows = []
    prev = None
    for stage, n in zip(FUNNEL_STAGES, counts):
        pct = None if prev in (None, 0) else round(n / prev * 100.0, 2)
        rows.append({"stage": stage, "n": n, "pct_of_previous": pct})
        prev = n
    return tuple(rows)


def hypothesis_comparison(observations: Sequence[FxObservation]) -> dict:
    """Per hypothesis: decision mix, decided vs opposite capability, BULL/BEAR."""
    out = {}
    for hyp in DIRECTION_HYPOTHESES:
        bull = [o for o in observations if o.directions.get(hyp) == "BULL"]
        bear = [o for o in observations if o.directions.get(hyp) == "BEAR"]
        neutral_n = sum(1 for o in observations if o.directions.get(hyp) == "NEUTRAL")
        decided = bull + bear
        decided_vals = [_decided_mfe(o, o.directions[hyp]) for o in decided]
        opposite_vals = [_opposite_mfe(o, o.directions[hyp]) for o in decided]
        cap_decided = reach_share(decided_vals)
        cap_opposite = reach_share(opposite_vals)
        separation = None
        if cap_decided is not None and cap_opposite is not None:
            separation = round((cap_decided - cap_opposite) * 100.0, 2)
        out[hyp] = {
            "description": DIRECTION_HYPOTHESES[hyp],
            "n_bull": len(bull), "n_bear": len(bear), "n_neutral": neutral_n,
            "capability_decided_direction": cap_decided,
            "capability_opposite_direction": cap_opposite,
            "separation_pp": separation,
            "capability_bull": reach_share([o.mfe_long for o in bull]),
            "capability_bear": reach_share([o.mfe_short for o in bear]),
            "capability_basis": CAPABILITY_BASIS,
            "sample_sufficient": len(decided) >= MIN_DIRECTIONAL_N,
        }
    return out


def required_comparisons(observations: Sequence[FxObservation]) -> dict:
    """Mission section 15 comparisons — all inside the OPPORTUNITY basis."""
    directional = [o for o in observations if o.primary_direction != "NEUTRAL"]
    bull = [o for o in directional if o.primary_direction == "BULL"]
    bear = [o for o in directional if o.primary_direction == "BEAR"]
    aligned_loc = [o for o in directional if o.location_state == "ALIGNED"]
    mismatch_loc = [o for o in directional if o.location_state == "MISMATCH_RECORDED"]
    with_event = [o for o in aligned_loc if o.confirmation_alignment is not None]
    conf_aligned = [o for o in with_event if o.confirmation_alignment == "ALIGNED"]
    conf_counter = [o for o in with_event if o.confirmation_alignment == "COUNTER_DIRECTION"]
    unconfirmed = [o for o in aligned_loc if o.confirmation_primitive is None]

    def cap(rows):
        return reach_share([_decided_mfe(o, o.primary_direction) for o in rows])

    return {
        "capability_basis": CAPABILITY_BASIS,
        "bull_vs_bear": {"bull_n": len(bull), "bull_capability": cap(bull),
                         "bear_n": len(bear), "bear_capability": cap(bear)},
        "direction_aligned_vs_counter_confirmation": {
            "aligned_n": len(conf_aligned), "aligned_capability": cap(conf_aligned),
            "counter_n": len(conf_counter), "counter_capability": cap(conf_counter),
            "note": "counter-direction events recorded, never silently rejected"},
        "location_aligned_vs_mismatch": {
            "aligned_n": len(aligned_loc), "aligned_capability": cap(aligned_loc),
            "mismatch_n": len(mismatch_loc), "mismatch_capability": cap(mismatch_loc),
            "note": "midrange/opposing-location observations recorded explicitly"},
        "confirmed_vs_comparable_unconfirmed": {
            "confirmed_n": len(conf_aligned), "confirmed_capability_obs_basis": cap(conf_aligned),
            "unconfirmed_n": len(unconfirmed), "unconfirmed_capability_obs_basis": cap(unconfirmed),
            "population_origin": "location-aligned observations; both measured at "
                                 "observation time under the shared diagnostic geometry"},
    }


def confirmation_value(observations: Sequence[FxObservation]) -> dict:
    """Section 9 fix: uplift only inside one capability basis."""
    directional = [o for o in observations if o.primary_direction != "NEUTRAL"]
    aligned_loc = [o for o in directional if o.location_state == "ALIGNED"]
    confirmed = [o for o in aligned_loc if o.confirmation_alignment == "ALIGNED"]
    entered = [o for o in observations if o.entered]

    def cap(rows):
        return reach_share([_decided_mfe(o, o.primary_direction) for o in rows])

    opportunity = cap(aligned_loc)
    confirmed_obs_basis = cap(confirmed)
    uplift_pp = None
    if opportunity is not None and confirmed_obs_basis is not None:
        uplift_pp = round((confirmed_obs_basis - opportunity) * 100.0, 2)
    return {
        "opportunity_basis": CAPABILITY_BASIS,
        "opportunity_capability_location_aligned": opportunity,
        "confirmed_subset_capability_same_basis": confirmed_obs_basis,
        "uplift_pp_same_basis": uplift_pp,
        "entry_conditioned_basis": ENTRY_CONDITIONED_BASIS,
        "entry_conditioned_capability": reach_share([o.entry_mfe_r for o in entered]),
        "entry_conditioned_uplift_vs_opportunity": None,
        "entry_conditioned_uplift_reason": INCOMPARABLE_REASON,
    }


def target_lab(observations: Sequence[FxObservation]) -> dict:
    entered = [o for o in observations if o.entered]
    n = len(entered)
    reach = {k: (sum(1 for o in entered if o.fixed_reached.get(k, False)) / n if n else None)
             for k in FIXED_R_TARGETS}
    counts = {k: sum(1 for o in entered if o.fixed_reached.get(k, False)) for k in FIXED_R_TARGETS}
    survival = {}
    for a, b in ((1, 2), (2, 3), (3, 4), (4, 5)):
        survival[f"P{b}_GIVEN_{a}"] = (counts[b] / counts[a]) if counts[a] else None
    naturals = sorted(v for o in entered for v in o.natural_targets.values())

    def quantile(q: float):
        if not naturals:
            return None
        pos = q * (len(naturals) - 1)
        lo = int(pos)
        hi = min(lo + 1, len(naturals) - 1)
        return naturals[lo] + (naturals[hi] - naturals[lo]) * (pos - lo)

    mfe = sorted(o.entry_mfe_r for o in entered if o.entry_mfe_r is not None)
    mae = sorted(o.entry_mae_r for o in entered if o.entry_mae_r is not None)
    return {
        "entered_n": n,
        "fixed_reach": {f"{k}R": reach[k] for k in FIXED_R_TARGETS},
        "mfe_r_median": median(mfe) if mfe else None,
        "mae_r_median": median(mae) if mae else None,
        "continuation_survival": survival,
        "natural_target_n": len(naturals),
        "natural_target_median_r": quantile(0.5),
        "natural_target_p25_r": quantile(0.25),
        "natural_target_p75_r": quantile(0.75),
        "natural_families": sorted({f for o in entered for f in o.natural_targets}),
        "fixed_targets_changed": False,
    }


def fx_root_cause(observations: Sequence[FxObservation], comparison: dict,
                  conf_value: dict, targets: dict) -> dict:
    """Mission section 12 precedence (A -> B -> C -> D -> E), fail-closed."""
    primary_stats = comparison[PRIMARY_FUNNEL_HYPOTHESIS] if PRIMARY_FUNNEL_HYPOTHESIS in comparison \
        else None
    directional_n = (primary_stats["n_bull"] + primary_stats["n_bear"]) if primary_stats else 0
    entered_n = targets["entered_n"]

    def result(case, primary, next_funnel, rationale, secondary=()):
        return {"case": case, "primary": primary, "secondary": list(secondary),
                "next_funnel_to_change": next_funnel, "rationale": rationale,
                "thresholds": {
                    "min_separation_pp": MIN_SEPARATION_PP,
                    "location_drop_pp": LOCATION_DROP_PP,
                    "confirmation_drop_pp": CONFIRMATION_DROP_PP,
                    "continuation_reach_3r_min": CONTINUATION_REACH_3R_MIN,
                    "desired_target_r": DESIRED_TARGET_R,
                }}

    if directional_n < MIN_DIRECTIONAL_N or primary_stats["separation_pp"] is None:
        return result("INSUFFICIENT", "INSUFFICIENT_EVIDENCE", "NONE",
                      f"directional population {directional_n} < {MIN_DIRECTIONAL_N} "
                      "or separation not measurable")

    separation = primary_stats["separation_pp"]
    direction_cap = primary_stats["capability_decided_direction"]

    # CASE A — direction does not separate.
    if separation < MIN_SEPARATION_PP:
        return result("A", "TRIGGER_FUNNEL_WEAKNESS", "TRIGGER",
                      f"primary hypothesis separation {separation}pp < {MIN_SEPARATION_PP}pp "
                      "— direction does not usefully separate future favorable movement")

    # CASE B — location selects badly inside the same basis (both numbers are
    # OPPORTUNITY-basis capabilities; comparable by construction).
    loc_cmp = conf_value["opportunity_capability_location_aligned"]
    if loc_cmp is None:
        return result("INSUFFICIENT", "INSUFFICIENT_EVIDENCE", "NONE",
                      "location-aligned capability not measurable")
    drop_pp = (direction_cap - loc_cmp) * 100.0
    if drop_pp >= LOCATION_DROP_PP:
        return result("B", "DIRECTION_LOCATION_MISMATCH", "LOCATION",
                      f"location-aligned capability {loc_cmp:.3f} is {drop_pp:.1f}pp below the "
                      f"directional baseline {direction_cap:.3f} (same basis)")

    # CASE C — confirmation destroys comparable capability.
    uplift = conf_value["uplift_pp_same_basis"]
    if uplift is None:
        return result("INSUFFICIENT", "INSUFFICIENT_EVIDENCE", "NONE",
                      "confirmed-subset capability not measurable in the shared basis")
    if uplift <= -CONFIRMATION_DROP_PP:
        return result("C", "CONFIRMATION_VALUE_DESTRUCTION", "CONFIRMATION",
                      f"confirmation uplift {uplift}pp <= -{CONFIRMATION_DROP_PP}pp in the "
                      "shared opportunity basis")

    if entered_n < MIN_ENTERED_N:
        return result("INSUFFICIENT", "INSUFFICIENT_EVIDENCE", "NONE",
                      f"entered population {entered_n} < {MIN_ENTERED_N} — target funnel not "
                      "comparably measurable")

    # CASE D — continuation collapses before the fixed target (not merely 5R low).
    reach1 = targets["fixed_reach"]["1R"]
    reach3 = targets["fixed_reach"]["3R"]
    secondary = []
    nat_median = targets["natural_target_median_r"]
    mismatch = nat_median is not None and nat_median < DESIRED_TARGET_R
    if reach1 is not None and reach3 is not None and \
            reach1 >= CONTINUATION_REACH_1R_MIN and reach3 < CONTINUATION_REACH_3R_MIN:
        if mismatch:
            secondary.append("TARGET_MODEL_MISMATCH")
        return result("D", "TARGET_CONTINUATION_WEAKNESS", "TARGET",
                      f"1R reach {reach1:.3f} healthy but 3R reach {reach3:.3f} < "
                      f"{CONTINUATION_REACH_3R_MIN} — continuation collapses before the "
                      "fixed target", secondary)

    # CASE E — natural geometry systematically below the fixed target.
    if mismatch:
        return result("E", "TARGET_MODEL_MISMATCH", "TARGET",
                      f"median natural target {nat_median:.2f}R < frozen fixed target "
                      f"{DESIRED_TARGET_R:.0f}R (fixed targets NOT changed by this diagnosis)")

    return result("NONE", "NO_DOMINANT_WEAKNESS", "NONE",
                  "no preregistered weakness threshold tripped")
