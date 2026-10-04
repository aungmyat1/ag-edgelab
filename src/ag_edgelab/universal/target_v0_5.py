"""Universal Funnel V0.5 — CAUSAL TARGET MODEL DIAGNOSTICS (frozen upstream).

EXPERIMENT: TARGET_MODEL_DIAGNOSTICS_V1, parent 09ddc4d… (V0.4,
TRIGGER_RESEARCH_COMPLETE). Question: why did T1's direction improvement not
propagate into deep target capability — target model, continuation, or stop
geometry?

Everything upstream is FROZEN — D01/T1/T2, structure, premium/discount,
H1 flow, location, confirmation, entry geometry, SL geometry, sessions,
fill semantics, friction, fixed targets, dataset lineage. This module only
MEASURES target geometry:

  * entry populations are the frozen V0.3 campaign entries (P0 = D01) and
    their T1 sub-population (P1, V0.4 policy states); every recomputed entry
    must reproduce the frozen MFE/MAE/fixed-reach ledger exactly or the
    build fails loudly;
  * natural target families NT01..NT05 are selected STRICTLY from
    information available at entry time (TARGET_CREATED_TIME <= ENTRY_TIME,
    enforced structurally via closed-bar cuts and asserted per target);
    NT05 (order block) has NO deterministic detector in this repository and
    is therefore fail-closed: AVAILABLE=false,
    REASON=TARGET_FAMILY_CONTRACT_INCOMPLETE — never invented;
  * stop/target collisions follow the frozen V0.3 fail-closed rule:
    the stop is counted FIRST (same-bar collision => invalidated);
  * NO TP change, no SL change, no parameter search, no partial exits —
    classification thresholds below are preregistered diagnostics only.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.strategies.crypto_mtf_smc import confirmed_swing_points
from ag_edgelab.universal.confirmation import (ConfirmationPrimitive, SetupAlignment,
                                               classify_alignment, structure_shift_events)
from ag_edgelab.universal.direction import Direction
from ag_edgelab.universal.fx_dev_campaign import (CONFIRMATION_WINDOW_BARS,
                                                  OUTCOME_HORIZON_BARS,
                                                  STOP_LOOKBACK_BARS, SymbolCampaign,
                                                  _cut_series, _precompute_sd_zones)
from ag_edgelab.universal.targets import (EntryGeometry, FIXED_R_TARGETS,
                                          TARGET_R_BUCKETS, classify_target_r,
                                          compute_excursions, natural_target_r)
from ag_edgelab.universal.trigger_v0_4 import session_label

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Experiment identity + preregistered thresholds (frozen before evaluation)
# ---------------------------------------------------------------------------

EXPERIMENT_ID = "TARGET_MODEL_DIAGNOSTICS_V1"
EXPERIMENT_VERSION = "0.3.0-research"   # formal mission spec (NT03 session
                                        # liquidity, NT05 order block fail-closed,
                                        # ladder delivery, A-F classifier)
PARENT_SHA = "09ddc4d0f90eb1bf4ffbe00780e959d947177b6a"
PARENT_TREE = "ffa60fd6157c1af78e18f1b0f21cbd147abc4271"

TARGET_FIT_TOLERANCE_PCT = 5.0  # ratio = FIXED_R / NATURAL_R; NEAR iff 0.95..1.05
                                # diagnostic comparison only — NOT a profit,
                                # execution, or edge threshold
DETERIORATION_PP = 5.0        # earliest chain element >= 5pp below its predecessor
SUPPORT_LOW = 0.25            # objective-availability share considered "common"
REALIZE_LOW = 0.25            # objective delivery below this => delivery fails
REALIZE_MIN_N = 20            # fail-closed evidence floor for any conditional
                              # delivery claim; below it => UNMEASURABLE
MISMATCH_BEYOND_PCT = 0.60    # fixed target beyond natural geometry in >= 60%
NATURAL_REACHABLE_LOW = 0.40  # primary objective reached before SL >= 40%
FIRST_DELIVERY_STRONG = 0.60  # CASE D leg: first-objective delivery >= 60%
RUNNER_CONTINUATION = 0.35    # CASE D leg: P(SECOND | FIRST) >= 35%
MIN_STRATUM_N = 100           # entries needed before a stratum verdict is issued
FAMILY_INSUFFICIENT_PCT = 0.50  # primary availability below this => CASE F
MATERIAL_R = 0.25             # D01 vs T1 median shift considered material
MATERIAL_PP = 5.0             # D01 vs T1 delivery/continuation shift (pp)
SL_INTERACTION_RATIO = 2.0    # Q1/Q4 nearest-median ratio (within-symbol quartiles)
RAW_COSCALING_RHO = 0.5       # interaction asserted only when raw target distance
                              # does NOT co-scale with risk (rank spearman < 0.5)
MIN_CORR_N = 30               # correlations reported only when supported

# pips/points authority (documented units; never silently mixed):
#   EURUSD/GBPUSD pip=0.0001, USDJPY pip=0.01, XAUUSD has no pip — distances
#   are reported in PRICE_POINT units (1.0 USD), labelled as such.
PIP_OR_POINT = {"EURUSD": (0.0001, "PIP"), "GBPUSD": (0.0001, "PIP"),
                "USDJPY": (0.01, "PIP"), "XAUUSD": (1.0, "PRICE_POINT")}

NATURAL_FAMILIES = ("NT01_NEXT_CONFIRMED_STRUCTURAL_SWING",
                    "NT02_PREVIOUS_DAY_DIRECTIONAL_EXTREME",
                    "NT03_OPPOSITE_SESSION_LIQUIDITY",
                    "NT04_NEXT_VALID_SUPPLY_DEMAND_ZONE",
                    "NT05_NEXT_VALID_ORDER_BLOCK")

FAMILY_CONTRACTS = {
    "NT01_NEXT_CONFIRMED_STRUCTURAL_SWING": {
        "status": "CONTRACT_COMPLETE",
        "definition": "most recent H4 swing high/low opposing the trade "
                      "direction and beyond entry, confirmed (2-bar rule, "
                      "frozen crypto_mtf_smc.confirmed_swing_points) at or "
                      "before the H4 closed-bar cut at entry",
        "created_time": "close of the confirming H4 bar"},
    "NT02_PREVIOUS_DAY_DIRECTIONAL_EXTREME": {
        "status": "CONTRACT_COMPLETE",
        "definition": "previous D1 bar high (LONG) / low (SHORT) beyond "
                      "entry, from the frozen single-lineage D1 derivation",
        "created_time": "close of the previous D1 bar"},
    "NT03_OPPOSITE_SESSION_LIQUIDITY": {
        "status": "CONTRACT_COMPLETE",
        "definition": "directional extreme (high for LONG, low for SHORT) of "
                      "the most recent COMPLETED frozen session window "
                      "(V0.3 session authority: ASIAN 00-08, LONDON 08-13, "
                      "OVERLAP 13-16, NEW_YORK 16-21, OFF_SESSION 21-24 UTC) "
                      "beyond entry; composition of the frozen session "
                      "windows with the frozen SESSION_LEVEL location "
                      "contract (LOC_SESSION_PREV_HIGH/LOW_V1 semantics); "
                      "no new windows invented",
        "created_time": "end of that completed session window"},
    "NT04_NEXT_VALID_SUPPLY_DEMAND_ZONE": {
        "status": "CONTRACT_COMPLETE",
        "definition": "nearest opposing H4 supply/demand zone edge beyond "
                      "entry (frozen V0.3 _precompute_sd_zones), zone created "
                      "at or before the H4 closed-bar cut at entry",
        "created_time": "close of the zone-creating H4 bar"},
    "NT05_NEXT_VALID_ORDER_BLOCK": {
        "status": "TARGET_FAMILY_CONTRACT_INCOMPLETE",
        "definition": "NO deterministic causal order-block detector exists in "
                      "this repository (ORDER_BLOCK is an enum label only); "
                      "fail-closed: AVAILABLE=false for every entry, never "
                      "invented",
        "created_time": None},
}

RUNNABLE_FAMILIES = tuple(f for f in NATURAL_FAMILIES
                          if FAMILY_CONTRACTS[f]["status"] == "CONTRACT_COMPLETE")

PRIMARY_RULE = ("PRIMARY_NATURAL_TARGET = nearest positive directionally-valid "
                "causal objective (smallest positive price distance from entry "
                "== min positive TARGET_R under the frozen SL); every "
                "alternative objective preserved separately in the ladder")
SELECTION_REASON = "NEAREST_VALID_CAUSAL_OBJECTIVE"

ENTRY_CLASSES = ("STOP_BEFORE_1R", "1R_ONLY", "2R_ONLY", "3R_ONLY", "4R_ONLY",
                 "5R_REACHED")

SESSION_WINDOWS_UTC = ((0, 8, "ASIAN"), (8, 13, "LONDON"),
                       (13, 16, "LONDON_NEWYORK_OVERLAP"),
                       (16, 21, "NEW_YORK"), (21, 24, "OFF_SESSION"))

TARGET_V0_5_REGISTRY_SHA256 = sha256_json({
    "experiment_id": EXPERIMENT_ID, "version": EXPERIMENT_VERSION,
    "parent_sha": PARENT_SHA,
    "families": FAMILY_CONTRACTS,
    "primary_rule": PRIMARY_RULE,
    "collision_rule": "stop counted FIRST (frozen V0.3 fail-closed rule)",
    "thresholds": {
        "target_fit_tolerance_pct": TARGET_FIT_TOLERANCE_PCT,
        "deterioration_pp": DETERIORATION_PP,
        "support_low": SUPPORT_LOW, "realize_low": REALIZE_LOW,
        "realize_min_n": REALIZE_MIN_N,
        "mismatch_beyond_pct": MISMATCH_BEYOND_PCT,
        "natural_reachable_low": NATURAL_REACHABLE_LOW,
        "first_delivery_strong": FIRST_DELIVERY_STRONG,
        "runner_continuation": RUNNER_CONTINUATION,
        "min_stratum_n": MIN_STRATUM_N,
        "family_insufficient_pct": FAMILY_INSUFFICIENT_PCT,
        "material_r": MATERIAL_R, "material_pp": MATERIAL_PP,
        "sl_interaction_ratio": SL_INTERACTION_RATIO,
        "raw_coscaling_rho": RAW_COSCALING_RHO,
        "min_corr_n": MIN_CORR_N,
        "pip_or_point_authority": {s: {"size": v[0], "unit": v[1]}
                                   for s, v in PIP_OR_POINT.items()},
    },
    "forbidden": ["TP change", "SL change", "parameter search", "partial exits",
                  "per-symbol/direction/session TP", "untested rule imports"],
})


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NaturalTargetRecord:
    family: str
    price: float
    distance: float                      # raw |target - entry| price distance
    target_r: float
    bucket: str
    created_time: datetime
    entry_time: datetime
    reached_before_sl: bool
    invalidated_by_stop: bool
    beyond_window: bool
    time_to_target_bars: int | None      # 1-based forward-bar offset when reached
    mfe_before_target_r: float | None    # max favorable R strictly before hit bar
    mae_before_target_r: float | None    # max adverse R strictly before hit bar


@dataclass(frozen=True)
class EntryRecord:
    symbol: str
    obs_feed_index: int
    entry_index: int
    entry_time: datetime
    direction: str
    session: str
    entry_price: float
    stop_price: float
    risk_distance: float                 # raw price risk distance (frozen SL)
    risk_distance_pips_or_points: float | None
    pip_or_point_unit: str | None
    mfe_r: float
    mae_r: float
    mfe_distance: float                  # raw price MFE distance
    mae_distance: float                  # raw price MAE distance
    fixed_reached: dict
    time_to_r: dict                      # k -> bars after entry (int) | None
    entry_class: str
    targets: dict                        # family -> NaturalTargetRecord | None
    # PRIMARY_NATURAL_TARGET (eligibility-gated; diagnostic summary only)
    nearest_family: str | None
    nearest_price: float | None
    nearest_distance: float | None
    nearest_target_r: float | None
    nearest_reached: bool | None
    # full objective ladder, ascending by TARGET_R: (family, price, r, reached)
    ladder: tuple
    multi_objective: bool                # >= 2 distinct objective levels
    # FURTHEST_CAUSAL_OBJECTIVE
    furthest_family: str | None
    furthest_target_r: float | None
    furthest_reached: bool | None
    # reach sequence: SECOND/THIRD = next strictly-farther distinct levels
    second_target_r: float | None
    second_reached: bool | None
    third_target_r: float | None
    third_reached: bool | None
    is_t1: bool
    is_t2: bool

    def objective_at_least(self, k: float):
        """Nearest ladder objective with TARGET_R >= k -> (r, reached) | None."""
        for _family, _price, r, reached in self.ladder:
            if r >= k:
                return r, reached
        return None


# ---------------------------------------------------------------------------
# Entry reconstruction (must reproduce the frozen V0.3 outcomes exactly)
# ---------------------------------------------------------------------------

def _entry_class(fixed: dict) -> str:
    if not fixed.get(1, False):
        return "STOP_BEFORE_1R"
    if fixed.get(5, False):
        return "5R_REACHED"
    top = max(k for k in FIXED_R_TARGETS if fixed.get(k, False))
    return f"{top}R_ONLY"


def _time_to_targets(forward: Sequence[MarketBar], geometry: EntryGeometry) -> dict:
    """First bar offset (1-based) reaching each R level, mirroring the frozen
    compute_excursions semantics exactly: the stop is counted FIRST within a
    bar, and no level is credited on or after the stop bar."""
    risk = geometry.risk
    out: dict[int, int | None] = {k: None for k in FIXED_R_TARGETS}
    for offset, bar in enumerate(forward[:OUTCOME_HORIZON_BARS]):
        if geometry.direction == Direction.BULL:
            favorable = (bar.high - geometry.entry) / risk
            hit_stop = bar.low <= geometry.stop
        else:
            favorable = (geometry.entry - bar.low) / risk
            hit_stop = bar.high >= geometry.stop
        if hit_stop:
            break
        for k in FIXED_R_TARGETS:
            if out[k] is None and favorable >= k:
                out[k] = offset + 1
    return out


def _target_reachability_impl(forward, geometry, target_price):
    """(reached, invalidated_by_stop, beyond_window, time_to_bars,
    mfe_before_r, mae_before_r) — stop counted FIRST (same-bar collision
    fail-closed). MFE/MAE "before target" accumulate over forward bars
    STRICTLY before the hit bar (intra-bar ordering is unknowable: fail-closed,
    deterministic)."""
    risk = geometry.risk
    mfe = 0.0
    mae = 0.0
    for offset, bar in enumerate(forward[:OUTCOME_HORIZON_BARS]):
        if geometry.direction == Direction.BULL:
            hit_stop = bar.low <= geometry.stop
            hit_target = bar.high >= target_price
            favorable = (bar.high - geometry.entry) / risk
            adverse = (geometry.entry - bar.low) / risk
        else:
            hit_stop = bar.high >= geometry.stop
            hit_target = bar.low <= target_price
            favorable = (geometry.entry - bar.low) / risk
            adverse = (bar.high - geometry.entry) / risk
        if hit_stop:                      # frozen fail-closed collision rule
            return False, True, False, None, None, None
        if hit_target:
            return True, False, False, offset + 1, mfe, mae
        mfe = max(mfe, favorable)
        mae = max(mae, adverse)
    return False, False, True, None, None, None


def _session_levels(m15: Sequence[MarketBar]) -> tuple:
    """(window_end_utc, high, low, label) per completed frozen session window
    that contains at least one M15 bar, ascending by window end."""
    out: list[tuple[datetime, float, float, str]] = []
    current_key = None
    hi = lo = None

    def window_of(ts: datetime):
        hour = ts.astimezone(UTC).hour
        for start, end, label in SESSION_WINDOWS_UTC:
            if start <= hour < end:
                day = ts.astimezone(UTC).date()
                end_ts = datetime(day.year, day.month, day.day,
                                  tzinfo=UTC) + timedelta(hours=end)
                return (end_ts, label)
        raise AssertionError("hour outside frozen session windows")

    for bar in m15:
        key = window_of(bar.timestamp)
        if key != current_key:
            if current_key is not None:
                out.append((current_key[0], hi, lo, current_key[1]))
            current_key = key
            hi, lo = bar.high, bar.low
        else:
            hi = max(hi, bar.high)
            lo = min(lo, bar.low)
    if current_key is not None:
        out.append((current_key[0], hi, lo, current_key[1]))
    return tuple(out)


@dataclass(frozen=True)
class _SymbolContext:
    h4_highs: tuple                       # (price, confirmed_index) ascending by confirm
    h4_lows: tuple
    sd_zones: tuple                       # (created_index, side, lo, hi)
    close_h4: list
    close_d1: list
    h4: tuple
    d1: tuple
    session_levels: tuple                 # (window_end, high, low, label)
    session_ends: tuple                   # window ends only (for bisect)


def build_symbol_context(frames: dict) -> _SymbolContext:
    h4, d1 = frames["H4"], frames["D1"]
    swings = confirmed_swing_points(h4, 2)
    highs = tuple((s.price, s.confirmed_index) for s in swings if s.kind == "HIGH")
    lows = tuple((s.price, s.confirmed_index) for s in swings if s.kind == "LOW")
    levels = _session_levels(frames["M15"])
    return _SymbolContext(
        h4_highs=highs, h4_lows=lows,
        sd_zones=tuple(_precompute_sd_zones(h4)),
        close_h4=_cut_series(h4, 240), close_d1=_cut_series(d1, 1440),
        h4=h4, d1=d1,
        session_levels=levels,
        session_ends=tuple(lv[0] for lv in levels))


def _natural_candidates(ctx: _SymbolContext, geometry: EntryGeometry,
                        entry_time: datetime) -> dict:
    """Family -> (price, created_time) using ONLY information at entry time.

    NT05 has no deterministic repository contract and is ALWAYS None
    (TARGET_FAMILY_CONTRACT_INCOMPLETE) — never invented.
    """
    c_h4 = bisect_right(ctx.close_h4, entry_time) - 1
    c_d1 = bisect_right(ctx.close_d1, entry_time) - 1
    bull = geometry.direction == Direction.BULL
    out: dict[str, tuple[float, datetime] | None] = {f: None for f in NATURAL_FAMILIES}
    if c_h4 < 0:
        return out

    def h4_time(index: int) -> datetime:
        return ctx.h4[index].timestamp + timedelta(minutes=240)

    # NT01: most recent confirmed opposing swing beyond entry (frozen rule)
    swings = ctx.h4_highs if bull else ctx.h4_lows
    visible = [(p, ci) for p, ci in swings if ci <= c_h4]
    beyond = [(p, ci) for p, ci in visible
              if (p > geometry.entry) == bull and p != geometry.entry]
    if beyond:
        price, ci = beyond[-1]
        out["NT01_NEXT_CONFIRMED_STRUCTURAL_SWING"] = (price, h4_time(ci))
    # NT02: directionally appropriate previous-day high/low
    if c_d1 >= 0:
        prev = ctx.d1[c_d1]
        price = prev.high if bull else prev.low
        if (price > geometry.entry) if bull else (price < geometry.entry):
            out["NT02_PREVIOUS_DAY_DIRECTIONAL_EXTREME"] = (
                price, prev.timestamp + timedelta(minutes=1440))
    # NT03: directional extreme of the most recent COMPLETED session window
    c_sess = bisect_right(ctx.session_ends, entry_time) - 1
    if c_sess >= 0:
        end_ts, hi, lo, _label = ctx.session_levels[c_sess]
        price = hi if bull else lo
        if (price > geometry.entry) if bull else (price < geometry.entry):
            out["NT03_OPPOSITE_SESSION_LIQUIDITY"] = (price, end_ts)
    # NT04: nearest opposing supply/demand zone edge beyond entry
    opposing_side = "RESISTANCE" if bull else "SUPPORT"
    zone_edges = []
    for created, side, lo_z, hi_z in ctx.sd_zones:
        if created <= c_h4 and side == opposing_side:
            edge = lo_z if bull else hi_z
            if (edge > geometry.entry) if bull else (edge < geometry.entry):
                zone_edges.append((edge, created))
    if zone_edges:
        edge, created = min(zone_edges) if bull else max(zone_edges)
        out["NT04_NEXT_VALID_SUPPLY_DEMAND_ZONE"] = (edge, h4_time(created))
    # NT05: TARGET_FAMILY_CONTRACT_INCOMPLETE -> always unavailable
    return out


def build_entry_records(frames: dict, campaign: SymbolCampaign,
                        enriched: Sequence) -> tuple[EntryRecord, ...]:
    """Reconstruct every frozen entry, verify it reproduces the stored V0.3
    outcome exactly, and attach causal natural targets + timing diagnostics."""
    m15: tuple[MarketBar, ...] = frames["M15"]
    ctx = build_symbol_context(frames)
    events_by_index: dict[int, list] = {}
    for event in structure_shift_events(m15, "M15"):
        events_by_index.setdefault(event.index, []).append(event)
    en_by_index = {en.feed_index: en for en in enriched}

    records: list[EntryRecord] = []
    for obs in campaign.observations:
        if not obs.entered:
            continue
        direction = Direction(obs.primary_direction)
        # frozen entry event: FIRST MSS/BOS in the confirmation window
        e_idx = None
        first_event = None
        for j in range(obs.feed_index + 1,
                       min(obs.feed_index + 1 + CONFIRMATION_WINDOW_BARS, len(m15))):
            for event in events_by_index.get(j, ()):
                if event.primitive in (ConfirmationPrimitive.MSS, ConfirmationPrimitive.BOS):
                    first_event = event
                    e_idx = j
                    break
            if first_event is not None:
                break
        if first_event is None or \
                classify_alignment(direction, first_event.direction) != SetupAlignment.ALIGNED:
            raise AssertionError(
                f"{campaign.symbol}: frozen entry event not reproduced at obs "
                f"{obs.feed_index}")
        entry_price = m15[e_idx].close
        window = m15[max(0, e_idx - STOP_LOOKBACK_BARS + 1): e_idx + 1]
        stop = min(b.low for b in window) if direction == Direction.BULL \
            else max(b.high for b in window)
        geometry = EntryGeometry(direction, entry_price, stop)
        forward = m15[e_idx + 1: e_idx + 1 + OUTCOME_HORIZON_BARS]
        outcome = compute_excursions(forward, geometry, OUTCOME_HORIZON_BARS)
        if outcome.mfe_r != obs.entry_mfe_r or outcome.mae_r != obs.entry_mae_r \
                or outcome.fixed_target_reached != obs.fixed_reached:
            raise AssertionError(
                f"{campaign.symbol}: recomputed entry outcome diverges from the "
                f"frozen V0.3 ledger at obs {obs.feed_index}")

        time_to = _time_to_targets(forward, geometry)
        for k in FIXED_R_TARGETS:   # internal consistency with frozen reach flags
            if (time_to[k] is not None) != bool(obs.fixed_reached.get(k, False)):
                raise AssertionError(f"time_to_{k}R inconsistent with frozen reach")

        entry_time = m15[e_idx].timestamp + timedelta(minutes=15)
        candidates = _natural_candidates(ctx, geometry, entry_time)
        targets: dict[str, NaturalTargetRecord | None] = {}
        for family, cand in candidates.items():
            if cand is None:
                targets[family] = None
                continue
            price, created = cand
            # eligibility (fail-closed): existed at entry, intended direction,
            # beyond entry, finite, positive distance — else NOT a candidate.
            if created > entry_time:
                raise AssertionError(f"{family}: TARGET_CREATED_TIME > ENTRY_TIME")
            beyond_entry = (price > entry_price) if direction == Direction.BULL \
                else (price < entry_price)
            distance = abs(price - entry_price)
            r = natural_target_r(entry_price, stop, price)
            if not beyond_entry or not (distance > 0.0) or not isfinite(r) or r <= 0.0:
                raise AssertionError(f"{family}: ineligible candidate survived "
                                     f"construction (must be causal, directional, "
                                     f"beyond entry, finite)")
            reached, invalidated, beyond, t_bars, mfe_b, mae_b = \
                _target_reachability_impl(forward, geometry, price)
            targets[family] = NaturalTargetRecord(
                family=family, price=price, distance=distance, target_r=r,
                bucket=classify_target_r(r),
                created_time=created, entry_time=entry_time,
                reached_before_sl=reached, invalidated_by_stop=invalidated,
                beyond_window=beyond, time_to_target_bars=t_bars,
                mfe_before_target_r=mfe_b, mae_before_target_r=mae_b)

        # full objective ladder (ascending by TARGET_R; families kept visible)
        ladder = tuple(sorted(
            ((t.family, t.price, t.target_r, t.reached_before_sl)
             for t in targets.values() if t is not None),
            key=lambda row: (row[2], row[0])))
        distinct_levels = sorted({row[2] for row in ladder})
        multi_objective = len(distinct_levels) >= 2

        # PRIMARY_NATURAL_TARGET: smallest positive distance from entry
        if ladder:
            n_family, n_price, n_r, n_reached = ladder[0]
            nearest_distance = targets[n_family].distance
            x_family, _, x_r, x_reached = ladder[-1]
        else:
            n_family = n_price = n_r = n_reached = nearest_distance = None
            x_family = x_r = x_reached = None
        # SECOND/THIRD = next strictly-farther distinct levels after FIRST
        second_r = second_reached = third_r = third_reached = None
        if ladder:
            for fam2, _, r2, reached2 in ladder:
                if second_r is None and r2 > ladder[0][2]:
                    second_r, second_reached = r2, reached2
                elif second_r is not None and r2 > second_r:
                    third_r, third_reached = r2, reached2
                    break

        en = en_by_index[obs.feed_index]
        pip_size, pip_unit = PIP_OR_POINT.get(campaign.symbol, (None, None))
        records.append(EntryRecord(
            symbol=campaign.symbol, obs_feed_index=obs.feed_index, entry_index=e_idx,
            entry_time=entry_time, direction=direction.value,
            session=session_label(entry_time),
            entry_price=entry_price, stop_price=stop, risk_distance=geometry.risk,
            risk_distance_pips_or_points=(geometry.risk / pip_size)
            if pip_size else None,
            pip_or_point_unit=pip_unit,
            mfe_r=obs.entry_mfe_r, mae_r=obs.entry_mae_r,
            mfe_distance=obs.entry_mfe_r * geometry.risk,
            mae_distance=obs.entry_mae_r * geometry.risk,
            fixed_reached=dict(obs.fixed_reached), time_to_r=time_to,
            entry_class=_entry_class(obs.fixed_reached), targets=targets,
            nearest_family=n_family, nearest_price=n_price,
            nearest_distance=nearest_distance, nearest_target_r=n_r,
            nearest_reached=n_reached,
            ladder=ladder, multi_objective=multi_objective,
            furthest_family=x_family, furthest_target_r=x_r,
            furthest_reached=x_reached,
            second_target_r=second_r, second_reached=second_reached,
            third_target_r=third_r, third_reached=third_reached,
            is_t1=en.t1 != "NEUTRAL", is_t2=en.t2 != "NEUTRAL"))
    return tuple(records)


# ---------------------------------------------------------------------------
# Aggregations (all diagnostic; nothing selects a TP)
# ---------------------------------------------------------------------------

def _quantile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def quantile_block(values: Sequence[float]) -> dict:
    s = sorted(values)
    return {"n": len(s),
            "P10": _quantile(s, 0.10), "P25": _quantile(s, 0.25),
            "P50": _quantile(s, 0.50), "P75": _quantile(s, 0.75),
            "P90": _quantile(s, 0.90), "MAX": s[-1] if s else None}


def fixed_surface(entries: Sequence[EntryRecord]) -> dict:
    n = len(entries)
    counts = {k: sum(1 for e in entries if e.fixed_reached.get(k, False))
              for k in FIXED_R_TARGETS}
    classes = {c: sum(1 for e in entries if e.entry_class == c) for c in ENTRY_CLASSES}
    time_to = {}
    for k in FIXED_R_TARGETS:
        vals = [float(e.time_to_r[k]) for e in entries if e.time_to_r[k] is not None]
        time_to[f"time_to_{k}R_bars"] = quantile_block(vals)
    return {"entry_n": n,
            "reach": {f"{k}R": (counts[k] / n if n else None) for k in FIXED_R_TARGETS},
            "reach_n": {f"{k}R": counts[k] for k in FIXED_R_TARGETS},
            "entry_classes": classes,
            "time_to_targets": time_to}


def continuation_chain(entries: Sequence[EntryRecord]) -> dict:
    n = len(entries)
    counts = {k: sum(1 for e in entries if e.fixed_reached.get(k, False))
              for k in FIXED_R_TARGETS}
    p1 = counts[1] / n if n else None
    chain = {"P1": p1}
    labels = ["P1"]
    values = [p1]
    for a, b in ((1, 2), (2, 3), (3, 4), (4, 5)):
        v = (counts[b] / counts[a]) if counts[a] else None
        chain[f"P{b}_GIVEN_{a}"] = v
        labels.append(f"P{b}_GIVEN_{a}")
        values.append(v)
    cumulative = {f"P{k}": (counts[k] / n if n else None) for k in (2, 3, 4, 5)}
    earliest = None
    for i in range(1, len(values)):
        if values[i] is not None and values[i - 1] is not None and \
                values[i] <= values[i - 1] - DETERIORATION_PP / 100.0:
            earliest = labels[i]
            break
    return {"chain": chain, "cumulative": cumulative,
            "earliest_material_deterioration": earliest,
            "deterioration_rule_pp": DETERIORATION_PP,
            "no_trading_rule_derived": True}


def family_report(entries: Sequence[EntryRecord]) -> dict:
    """Per-family availability, delivery, timing, pre-target excursions (11)."""
    out = {}
    n = len(entries)
    for family in NATURAL_FAMILIES:
        if FAMILY_CONTRACTS[family]["status"] != "CONTRACT_COMPLETE":
            out[family] = {"AVAILABLE": False,
                           "REASON": "TARGET_FAMILY_CONTRACT_INCOMPLETE",
                           "INPUT_N": n, "AVAILABLE_N": 0, "AVAILABLE_PCT": None,
                           "REACHED_BEFORE_SL_N": None,
                           "REACHED_BEFORE_SL_PCT": None}
            continue
        avail = [e.targets[family] for e in entries if e.targets[family] is not None]
        reached = [t for t in avail if t.reached_before_sl]
        invalidated = sum(1 for t in avail if t.invalidated_by_stop)
        beyond = sum(1 for t in avail if t.beyond_window)
        tt = sorted(float(t.time_to_target_bars) for t in reached)
        out[family] = {
            "INPUT_N": n,
            "AVAILABLE_N": len(avail),
            "AVAILABLE_PCT": (len(avail) / n) if n else None,
            "REACHED_N": len(reached),
            "REACHED_PCT": (len(reached) / n) if n else None,
            "REACHED_BEFORE_SL_N": len(reached),
            "REACHED_BEFORE_SL_PCT": (len(reached) / len(avail)) if avail else None,
            "NOT_REACHED_N": len(avail) - len(reached),
            "INVALIDATED_BY_STOP_N": invalidated,
            "BEYOND_WINDOW_N": beyond,
            "TIME_TO_TARGET_BARS": {
                "P25": _quantile(tt, 0.25), "P50": _quantile(tt, 0.50),
                "P75": _quantile(tt, 0.75), "P90": _quantile(tt, 0.90)},
            "MFE_BEFORE_TARGET_R": quantile_block(
                [t.mfe_before_target_r for t in reached]),
            "MAE_BEFORE_TARGET_R": quantile_block(
                [t.mae_before_target_r for t in reached]),
            "target_r_quantiles": quantile_block([t.target_r for t in avail]),
            "bucket_histogram": {b: sum(1 for t in avail if t.bucket == b)
                                 for b in TARGET_R_BUCKETS},
        }
    nearest = [e.nearest_target_r for e in entries if e.nearest_target_r is not None]
    out["PRIMARY_NATURAL_TARGET"] = {
        "rule": PRIMARY_RULE,
        "INPUT_N": n,
        "AVAILABLE_N": len(nearest),
        "AVAILABLE_PCT": (len(nearest) / n) if n else None,
        "family_share": {f: sum(1 for e in entries if e.nearest_family == f)
                         for f in NATURAL_FAMILIES},
        "target_r_quantiles": quantile_block(nearest),
    }
    furthest = [e.furthest_target_r for e in entries
                if e.furthest_target_r is not None]
    out["FURTHEST_CAUSAL_OBJECTIVE"] = {
        "INPUT_N": n, "AVAILABLE_N": len(furthest),
        "AVAILABLE_PCT": (len(furthest) / n) if n else None,
        "family_share": {f: sum(1 for e in entries if e.furthest_family == f)
                         for f in NATURAL_FAMILIES},
        "target_r_quantiles": quantile_block(furthest),
    }
    return out


# ---------------------------------------------------------------------------
# Fixed-R vs natural geometry (9, 13)
# ---------------------------------------------------------------------------

def fit_class_for(k: int, natural_r: float | None) -> tuple[str | None, str | None]:
    """Preregistered ratio rule (TARGET_FIT_TOLERANCE_PCT = 5.0):
    ratio = FIXED_R / NATURAL_TARGET_R; BELOW < 0.95, NEAR 0.95..1.05,
    ABOVE > 1.05. Invalid/unavailable natural target => (None, reason)."""
    if natural_r is None or not isfinite(natural_r) or natural_r <= 0.0:
        return None, "INVALID_OR_UNAVAILABLE_NATURAL_TARGET"
    lo = 1.0 - TARGET_FIT_TOLERANCE_PCT / 100.0
    hi = 1.0 + TARGET_FIT_TOLERANCE_PCT / 100.0
    ratio = k / natural_r
    if ratio < lo:
        return "FIXED_TARGET_BELOW_NATURAL", None
    if ratio > hi:
        return "FIXED_TARGET_ABOVE_NATURAL", None
    return "FIXED_TARGET_NEAR_NATURAL", None


def fit_classification(entries: Sequence[EntryRecord], k: int,
                       against: str = "primary") -> dict:
    """Fixed level k vs the primary natural target (default) or vs the
    FURTHEST causal objective (against='furthest': ABOVE means the fixed
    level is beyond EVERY causal objective available at entry)."""
    getter = (lambda e: e.nearest_target_r) if against == "primary" else \
        (lambda e: e.furthest_target_r)
    below = near = above = null_n = 0
    for e in entries:
        cls, _reason = fit_class_for(k, getter(e))
        if cls is None:
            null_n += 1
        elif cls == "FIXED_TARGET_BELOW_NATURAL":
            below += 1
        elif cls == "FIXED_TARGET_ABOVE_NATURAL":
            above += 1
        else:
            near += 1
    measurable = below + near + above
    pct = (lambda x: x / measurable if measurable else None)
    n = len(entries)
    reach = (sum(1 for e in entries if e.fixed_reached.get(k, False)) / n) \
        if n else None
    return {"fixed_level": f"{k}R", "against": against,
            "tolerance_pct": TARGET_FIT_TOLERANCE_PCT,
            "BELOW_NATURAL_N": below, "NEAR_NATURAL_N": near,
            "ABOVE_NATURAL_N": above, "NULL_N": null_n,
            "null_reason": "INVALID_OR_UNAVAILABLE_NATURAL_TARGET",
            "BELOW_NATURAL_PCT": pct(below), "NEAR_NATURAL_PCT": pct(near),
            "ABOVE_NATURAL_PCT": pct(above),
            "actual_fixed_reach_pct": reach}


def fixed_vs_natural(entries: Sequence[EntryRecord]) -> dict:
    out = {"vs_primary": {f"{k}R": fit_classification(entries, k, "primary")
                          for k in FIXED_R_TARGETS},
           "vs_furthest": {f"{k}R": fit_classification(entries, k, "furthest")
                           for k in FIXED_R_TARGETS}}
    # 13: the three 5R questions, answered from the full ladder
    n = len(entries)
    with_ladder = [e for e in entries if e.ladder]
    beyond_all = [e for e in with_ladder
                  if fit_class_for(5, e.furthest_target_r)[0]
                  == "FIXED_TARGET_ABOVE_NATURAL"]
    ge5 = [e for e in with_ladder if e.objective_at_least(5) is not None]
    ge5_reached = [e for e in ge5 if e.objective_at_least(5)[1]]
    out["five_r_questions"] = {
        "5R_BEYOND_EVERY_CAUSAL_OBJECTIVE_PCT":
            (len(beyond_all) / len(with_ladder)) if with_ladder else None,
        "GE_5R_OBJECTIVE_EXISTS_PCT":
            (len(ge5) / len(with_ladder)) if with_ladder else None,
        "GE_5R_OBJECTIVE_REACHED_WHEN_EXISTS_PCT":
            (len(ge5_reached) / len(ge5)) if ge5 else None,
        "ge5_exists_n": len(ge5),
        "measurable_n": len(with_ladder), "entry_n": n,
        "realize_min_n": REALIZE_MIN_N,
        "measurable": len(ge5) >= REALIZE_MIN_N,
    }
    return out


def ladder_level_diagnostic(entries: Sequence[EntryRecord], k: int) -> dict:
    """Ladder-based (ANY family) availability and delivery of >= kR objectives."""
    with_ladder = [e for e in entries if e.ladder]
    ge = [(e, e.objective_at_least(k)) for e in with_ladder]
    ge = [(e, hit) for e, hit in ge if hit is not None]
    reached = [e for e, hit in ge if hit[1]]
    fixed_when = [e for e, _hit in ge if e.fixed_reached.get(k, False)]
    return {"level": f"{k}R",
            "OBJECTIVE_AVAILABLE_N": len(ge),
            "OBJECTIVE_AVAILABLE_PCT":
                (len(ge) / len(with_ladder)) if with_ladder else None,
            "OBJECTIVE_REACHED_WHEN_AVAILABLE_PCT":
                (len(reached) / len(ge)) if ge else None,
            "FIXED_REACH_WHEN_AVAILABLE_PCT":
                (len(fixed_when) / len(ge)) if ge else None,
            "realize_min_n": REALIZE_MIN_N,
            "measurable": len(ge) >= REALIZE_MIN_N}


# ---------------------------------------------------------------------------
# Multi-objective delivery (12)
# ---------------------------------------------------------------------------

def multi_objective_delivery(entries: Sequence[EntryRecord]) -> dict:
    with_obj = [e for e in entries if e.nearest_target_r is not None]
    one = [e for e in with_obj if not e.multi_objective]
    multi = [e for e in with_obj if e.multi_objective]
    first_reached = [e for e in with_obj if e.nearest_reached]
    with_second = [e for e in with_obj if e.second_target_r is not None]
    second_reached = [e for e in with_second if e.second_reached]
    with_third = [e for e in with_obj if e.third_target_r is not None]
    third_reached = [e for e in with_third if e.third_reached]
    sec_given_first = [e for e in with_second if e.nearest_reached]
    third_given_second = [e for e in with_third if e.second_reached]
    pct = lambda num, rows: (num / len(rows)) if rows else None
    out = {
        "ONE_OBJECTIVE_AVAILABLE_N": len(one),
        "MULTI_OBJECTIVE_AVAILABLE_N": len(multi),
        "MULTI_OBJECTIVE_AVAILABLE_PCT": pct(len(multi), with_obj),
        "FIRST_OBJECTIVE_REACHED_N": len(first_reached),
        "FIRST_OBJECTIVE_REACHED_PCT": pct(len(first_reached), with_obj),
        "SECOND_OBJECTIVE_REACHED_N": len(second_reached),
        "SECOND_OBJECTIVE_REACHED_PCT": pct(len(second_reached), with_second),
        "THIRD_OBJECTIVE_REACHED_N": len(third_reached),
        "THIRD_OBJECTIVE_REACHED_PCT": pct(len(third_reached), with_third),
        "P_SECOND_GIVEN_FIRST": pct(
            sum(1 for e in sec_given_first if e.second_reached), sec_given_first),
        "P_THIRD_GIVEN_SECOND": pct(
            sum(1 for e in third_given_second if e.third_reached),
            third_given_second),
        "note": "diagnostic geometry only; no partial exits implemented",
    }
    for k in (2, 3, 4, 5):
        out[f"P_{k}R_GIVEN_FIRST_OBJECTIVE"] = pct(
            sum(1 for e in first_reached if e.fixed_reached.get(k, False)),
            first_reached)
    return out


# ---------------------------------------------------------------------------
# Correlations + stop/target geometry (14)
# ---------------------------------------------------------------------------

def _pearson(xs: Sequence[float], ys: Sequence[float],
             min_n: int = MIN_CORR_N) -> float | None:
    n = len(xs)
    if n < min_n or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx == 0.0 or sy == 0.0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / (sx ** 0.5 * sy ** 0.5)


def _ranks(vals: Sequence[float]) -> list[float]:
    """Average-tie ranks (1-based)."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs: Sequence[float], ys: Sequence[float],
              min_n: int = MIN_CORR_N) -> float | None:
    if len(xs) < min_n:
        return None
    return _pearson(_ranks(xs), _ranks(ys), min_n=min_n)


_COUPLING_PAIRS = {
    # raw price scales differ per symbol: Pearson/Spearman are WITHIN symbol;
    # pooled statistic = Spearman over within-symbol normalized ranks.
    "RISK_VS_PRIMARY_TARGET_R": lambda e: (e.risk_distance, e.nearest_target_r),
    "RISK_VS_TARGET_DISTANCE": lambda e: (e.risk_distance, e.nearest_distance),
    "RISK_VS_MFE_DISTANCE": lambda e: (e.risk_distance, e.mfe_distance),
    "RISK_VS_MAE_DISTANCE": lambda e: (e.risk_distance, e.mae_distance),
}


def coupling_correlations(entries: Sequence[EntryRecord]) -> dict:
    by_symbol: dict[str, list[EntryRecord]] = {}
    for e in entries:
        by_symbol.setdefault(e.symbol, []).append(e)
    out: dict[str, dict] = {}
    for name, getter in _COUPLING_PAIRS.items():
        per_symbol = {}
        pooled_rx: list[float] = []
        pooled_ry: list[float] = []
        for symbol in sorted(by_symbol):
            data = [getter(e) for e in by_symbol[symbol]]
            data = [(x, y) for x, y in data if y is not None]
            xs = [d[0] for d in data]
            ys = [d[1] for d in data]
            per_symbol[symbol] = {"n": len(xs),
                                  "pearson": _pearson(xs, ys),
                                  "spearman": _spearman(xs, ys)}
            if len(xs) >= MIN_CORR_N:
                pooled_rx.extend(r / len(xs) for r in _ranks(xs))
                pooled_ry.extend(r / len(ys) for r in _ranks(ys))
        out[name] = {
            "per_symbol": per_symbol,
            "pooled_within_symbol_rank_spearman": _pearson(pooled_rx, pooled_ry),
            "pooled_pearson": None,
            "pooled_pearson_reason": "CROSS_SYMBOL_PRICE_SCALE_MIX",
            "min_corr_n": MIN_CORR_N,
        }
    out["RISK_VS_PRIMARY_TARGET_R"]["label"] = "MECHANICALLY_COUPLED_DIAGNOSTIC"
    out["RISK_VS_PRIMARY_TARGET_R"]["caution"] = (
        "NATURAL_TARGET_R = TARGET_DISTANCE / RISK_DISTANCE: the denominator "
        "couples this statistic to risk mechanically. Do NOT infer that a "
        "tight stop causes larger opportunity (or a wide stop smaller "
        "opportunity) from this value alone; interpret SL/target interaction "
        "from the raw-distance relationships and stratified distributions.")
    return out


def stop_target_geometry(entries: Sequence[EntryRecord]) -> dict:
    """Risk-distance quartiles vs natural target geometry + reach (SL frozen).

    ATR normalization: NO causal ATR authority exists in this repository ->
    risk_distance_ATR_normalized = NULL (never invented).
    """
    with_nat = [e for e in entries if e.nearest_target_r is not None]
    by_symbol: dict[str, list[EntryRecord]] = {}
    for e in with_nat:
        by_symbol.setdefault(e.symbol, []).append(e)
    quartiles: dict[str, list[EntryRecord]] = {"Q1": [], "Q2": [], "Q3": [], "Q4": []}
    for symbol, rows in by_symbol.items():
        risks = sorted(e.risk_distance for e in rows)
        cuts = [_quantile(risks, q) for q in (0.25, 0.5, 0.75)]
        for e in rows:
            if e.risk_distance <= cuts[0]:
                q = "Q1"
            elif e.risk_distance <= cuts[1]:
                q = "Q2"
            elif e.risk_distance <= cuts[2]:
                q = "Q3"
            else:
                q = "Q4"
            quartiles[q].append(e)

    def med(vals):
        return _quantile(sorted(vals), 0.5)

    table = {}
    for q, rows in quartiles.items():
        table[q] = {
            "entry_n": len(rows),
            "median_target_distance_price": med([e.nearest_distance for e in rows])
            if rows else None,
            "median_primary_target_r": med([e.nearest_target_r for e in rows])
            if rows else None,
            "median_mfe_r": med([e.mfe_r for e in rows]) if rows else None,
            "median_mae_r": med([e.mae_r for e in rows]) if rows else None,
            "first_objective_reached_pct":
                (sum(1 for e in rows if e.nearest_reached) / len(rows))
                if rows else None,
            "fixed_reach": {f"{k}R": (sum(1 for e in rows
                                          if e.fixed_reached.get(k, False)) / len(rows))
                            if rows else None for k in FIXED_R_TARGETS},
        }
    med_r = {q: table[q]["median_primary_target_r"] for q in table}
    ratio = (med_r["Q1"] / med_r["Q4"]) if med_r["Q1"] and med_r["Q4"] else None

    coupling = coupling_correlations(entries)
    raw_rho = coupling["RISK_VS_TARGET_DISTANCE"][
        "pooled_within_symbol_rank_spearman"]
    if ratio is None or raw_rho is None:
        interaction = "INSUFFICIENT_EVIDENCE"
    else:
        gradient = ratio >= SL_INTERACTION_RATIO
        coscaling_weak = raw_rho < RAW_COSCALING_RHO
        interaction = "YES" if (gradient and coscaling_weak) else "NO"
    return {"risk_quartiles_within_symbol": True,
            "quartiles_are_distribution_based": "within-symbol quantiles of the "
                                                "frozen entry population; no pip "
                                                "thresholds invented",
            "risk_distance_atr_normalized": None,
            "risk_distance_atr_reason": "NO_CAUSAL_ATR_AUTHORITY_IN_REPOSITORY",
            "risk_quartile_table": table,
            "primary_target_r_median_by_risk_quartile": med_r,
            "q1_over_q4_ratio": ratio,
            "q1_over_q4_ratio_label": "MECHANICALLY_COUPLED_DIAGNOSTIC "
                                      "(R denominator)",
            "preregistered_ratio_threshold": SL_INTERACTION_RATIO,
            "raw_coscaling_rho_threshold": RAW_COSCALING_RHO,
            "risk_vs_target_distance_rank_spearman": raw_rho,
            "correlations": coupling,
            "SL_TARGET_GEOMETRY_INTERACTION": interaction,
            "decision_rule": "YES iff Q1/Q4 primary-median ratio >= 2.0 AND "
                             "pooled within-symbol rank spearman(risk, raw "
                             "target distance) < 0.5 (gradient not explained "
                             "by genuine raw co-scaling)",
            "note": "SL remains frozen; no alternative SL tested in V0.5"}


# ---------------------------------------------------------------------------
# Population report + D01 vs T1 effect (15)
# ---------------------------------------------------------------------------

def population_target_report(entries: Sequence[EntryRecord]) -> dict:
    primary = [e.nearest_target_r for e in entries if e.nearest_target_r is not None]
    furthest = [e.furthest_target_r for e in entries
                if e.furthest_target_r is not None]
    return {
        "entry_n": len(entries),
        "primary_target_r_quantiles": quantile_block(primary),
        "furthest_target_r_quantiles": quantile_block(furthest),
        "primary_available_pct": (len(primary) / len(entries)) if entries else None,
        "fixed_surface": fixed_surface(entries),
        "continuation": continuation_chain(entries),
        "families": family_report(entries),
        "fixed_vs_natural": fixed_vs_natural(entries),
        "ladder_levels": {f"{k}R": ladder_level_diagnostic(entries, k)
                          for k in (2, 3, 4, 5)},
        "multi_objective_delivery": multi_objective_delivery(entries),
    }


def _effect(delta: float | None, threshold: float) -> str:
    if delta is None:
        return "INSUFFICIENT_EVIDENCE"
    if delta >= threshold:
        return "IMPROVED"
    if delta <= -threshold:
        return "DEGRADED"
    return "NEUTRAL"


def d01_vs_t1_effect(d01: dict, t1: dict) -> dict:
    """Preregistered A-E classification of the T1 target effect (15)."""
    def dd(path_a, path_b=None):
        a, b = d01, t1
        for key in path_a:
            a = a.get(key) if isinstance(a, dict) else None
            b = b.get(key) if isinstance(b, dict) else None
        if a is None or b is None:
            return None
        return b - a

    d_primary_p50 = dd(["primary_target_r_quantiles", "P50"])
    d_furthest_p50 = dd(["furthest_target_r_quantiles", "P50"])
    d_first = dd(["multi_objective_delivery", "FIRST_OBJECTIVE_REACHED_PCT"])
    d_second = dd(["multi_objective_delivery", "SECOND_OBJECTIVE_REACHED_PCT"])
    d_sec_given_first = dd(["multi_objective_delivery", "P_SECOND_GIVEN_FIRST"])
    deltas_fixed = {f"{k}R": dd(["fixed_surface", "reach", f"{k}R"])
                    for k in (2, 3, 4, 5)}

    geometry = _effect(max(filter(lambda v: v is not None,
                                  [d_primary_p50, d_furthest_p50]), default=None),
                       MATERIAL_R)
    if geometry == "IMPROVED" and any(
            v is not None and v <= -MATERIAL_R
            for v in (d_primary_p50, d_furthest_p50)):
        geometry = "MIXED"
    delivery = _effect(d_first * 100.0 if d_first is not None else None, MATERIAL_PP)
    deep = _effect(d_sec_given_first * 100.0 if d_sec_given_first is not None
                   else None, MATERIAL_PP)

    insufficient = t1.get("entry_n", 0) < MIN_STRATUM_N
    verdicts = []
    if insufficient:
        verdicts.append("E_INSUFFICIENT_EVIDENCE")
    else:
        if geometry == "IMPROVED":
            verdicts.append("A_IMPROVES_TARGET_GEOMETRY")
        if delivery == "IMPROVED":
            verdicts.append("B_IMPROVES_TARGET_DELIVERY")
        if deep == "DEGRADED":
            verdicts.append("D_DAMAGES_DEEP_CONTINUATION")
        if not verdicts:
            # V0.4 (parent, frozen) already established the direction
            # improvement; nothing target-side improved here.
            verdicts.append("C_ONLY_IMPROVES_INITIAL_DIRECTION")
    return {
        "deltas": {"primary_p50_r": d_primary_p50,
                   "furthest_p50_r": d_furthest_p50,
                   "first_objective_reach": d_first,
                   "second_objective_reach": d_second,
                   "p_second_given_first": d_sec_given_first,
                   "fixed_reach": deltas_fixed},
        "T1_TARGET_GEOMETRY_EFFECT": geometry,
        "T1_TARGET_DELIVERY_EFFECT": delivery,
        "T1_DEEP_CONTINUATION_EFFECT": deep,
        "verdicts": verdicts,
        "thresholds": {"material_r": MATERIAL_R, "material_pp": MATERIAL_PP,
                       "min_stratum_n": MIN_STRATUM_N},
        "direction_improvement_authority": "V0.4 parent (frozen): T1 separation "
                                           "+7.55pp vs D01 +2.04pp",
    }


# ---------------------------------------------------------------------------
# Root-cause classifier (17) — preregistered CASE A..F
# ---------------------------------------------------------------------------

def root_cause_cases(report: dict, sl: dict) -> dict:
    """Evaluate preregistered CASE A..F evidence on a population report."""
    n = report["entry_n"]
    avail = report["primary_available_pct"]
    mo = report["multi_objective_delivery"]
    first_reach = mo["FIRST_OBJECTIVE_REACHED_PCT"]
    p_second = mo["P_SECOND_GIVEN_FIRST"]
    five = report["fixed_vs_natural"]["five_r_questions"]
    vs_primary = report["fixed_vs_natural"]["vs_primary"]
    deep_above = {k: vs_primary[f"{k}R"]["ABOVE_NATURAL_PCT"] for k in (4, 5)}
    levels = report["ladder_levels"]

    if n < MIN_STRATUM_N:
        return {"cases": {}, "PRIMARY_DIAGNOSIS": "TARGET_FAMILY_INSUFFICIENT",
                "SECONDARY_DIAGNOSES": [],
                "reason": f"n={n} < MIN_STRATUM_N={MIN_STRATUM_N}"}
    if avail is None or avail < FAMILY_INSUFFICIENT_PCT:
        return {"cases": {}, "PRIMARY_DIAGNOSIS": "TARGET_FAMILY_INSUFFICIENT",
                "SECONDARY_DIAGNOSES": [],
                "reason": "primary objective availability below "
                          f"{FAMILY_INSUFFICIENT_PCT}"}

    case_a = (avail >= FAMILY_INSUFFICIENT_PCT
              and first_reach is not None
              and first_reach >= NATURAL_REACHABLE_LOW
              and all(v is not None and v >= MISMATCH_BEYOND_PCT
                      for v in deep_above.values())
              and five["5R_BEYOND_EVERY_CAUSAL_OBJECTIVE_PCT"] is not None
              and five["5R_BEYOND_EVERY_CAUSAL_OBJECTIVE_PCT"]
              >= MISMATCH_BEYOND_PCT)
    b_levels = []
    for k in (3, 4, 5):
        lv = levels[f"{k}R"]
        if lv["OBJECTIVE_AVAILABLE_PCT"] is not None \
                and lv["OBJECTIVE_AVAILABLE_PCT"] >= SUPPORT_LOW \
                and lv["measurable"] \
                and lv["OBJECTIVE_REACHED_WHEN_AVAILABLE_PCT"] is not None \
                and lv["OBJECTIVE_REACHED_WHEN_AVAILABLE_PCT"] < REALIZE_LOW:
            b_levels.append(f"{k}R")
    case_b = bool(b_levels)
    lv5 = levels["5R"]
    case_c = (lv5["OBJECTIVE_AVAILABLE_PCT"] is not None
              and lv5["OBJECTIVE_AVAILABLE_PCT"] >= SUPPORT_LOW
              and lv5["measurable"]
              and lv5["OBJECTIVE_REACHED_WHEN_AVAILABLE_PCT"] is not None
              and lv5["OBJECTIVE_REACHED_WHEN_AVAILABLE_PCT"] >= REALIZE_LOW)
    case_d = (first_reach is not None and first_reach >= FIRST_DELIVERY_STRONG
              and p_second is not None
              and mo["SECOND_OBJECTIVE_REACHED_N"] is not None
              and p_second >= RUNNER_CONTINUATION)
    case_e = sl["SL_TARGET_GEOMETRY_INTERACTION"] == "YES"

    cases = {
        "A_TARGET_MODEL_MISMATCH": {
            "true": case_a,
            "evidence": {"primary_available_pct": avail,
                         "first_objective_reached_pct": first_reach,
                         "fixed_4r_5r_above_primary_pct": deep_above,
                         "5r_beyond_every_objective_pct":
                             five["5R_BEYOND_EVERY_CAUSAL_OBJECTIVE_PCT"]}},
        "B_TARGET_CONTINUATION_WEAKNESS": {
            "true": case_b, "evidence": {"failing_levels": b_levels}},
        "C_FIXED_5R_SUPPORTED": {
            "true": case_c,
            "evidence": {"ge5_available_pct": lv5["OBJECTIVE_AVAILABLE_PCT"],
                         "ge5_delivery_pct":
                             lv5["OBJECTIVE_REACHED_WHEN_AVAILABLE_PCT"],
                         "measurable": lv5["measurable"]}},
        "D_PARTIAL_TARGET_PLUS_RUNNER_HYPOTHESIS": {
            "true": case_d,
            "evidence": {"first_objective_reached_pct": first_reach,
                         "p_second_given_first": p_second},
            "note": "DIAGNOSTIC ONLY — no partial exits implemented"},
        "E_SL_TARGET_GEOMETRY_INTERACTION": {
            "true": case_e,
            "evidence": {"q1_over_q4_ratio": sl["q1_over_q4_ratio"],
                         "raw_coscaling_rank_spearman":
                             sl["risk_vs_target_distance_rank_spearman"]}},
    }
    precedence = [("C_FIXED_5R_SUPPORTED", case_c),
                  ("A_TARGET_MODEL_MISMATCH", case_a),
                  ("B_TARGET_CONTINUATION_WEAKNESS", case_b),
                  ("D_PARTIAL_TARGET_PLUS_RUNNER_HYPOTHESIS", case_d),
                  ("E_SL_TARGET_GEOMETRY_INTERACTION", case_e)]
    primary = next((name for name, hit in precedence if hit),
                   "F_TARGET_FAMILY_INSUFFICIENT")
    secondary = [name for name, hit in precedence if hit and name != primary]
    next_map = {
        "C_FIXED_5R_SUPPORTED": "FIXED_R_TARGET_EXPERIMENT",
        "A_TARGET_MODEL_MISMATCH": "NATURAL_TARGET_EXPERIMENT",
        "B_TARGET_CONTINUATION_WEAKNESS": "TARGET_CONTINUATION_RESEARCH",
        "D_PARTIAL_TARGET_PLUS_RUNNER_HYPOTHESIS":
            "NATURAL_TARGET_PLUS_RUNNER_EXPERIMENT",
        "E_SL_TARGET_GEOMETRY_INTERACTION": "SL_TARGET_GEOMETRY_RESEARCH",
        "F_TARGET_FAMILY_INSUFFICIENT": "INSUFFICIENT_EVIDENCE",
    }
    next_funnel = next_map[primary]
    if primary == "A_TARGET_MODEL_MISMATCH" and case_d:
        next_funnel = "NATURAL_TARGET_PLUS_RUNNER_EXPERIMENT"
    return {"cases": cases,
            "precedence": [name for name, _ in precedence],
            "PRIMARY_DIAGNOSIS": primary,
            "SECONDARY_DIAGNOSES": secondary,
            "NEXT_FUNNEL_TO_TEST": next_funnel,
            "next_map": next_map,
            "no_tp_changed": True, "no_sl_changed": True,
            "no_partial_exits_implemented": True,
            "no_parameter_search": True}


# ---------------------------------------------------------------------------
# Per-entry persistence (6, 7) — JSONL rows; families never collapsed
# ---------------------------------------------------------------------------

def candidate_ledger_rows(entries: Sequence[EntryRecord]) -> list[dict]:
    """One row per (entry x family), including unavailable families."""
    rows: list[dict] = []
    for e in entries:
        pip_size, pip_unit = PIP_OR_POINT.get(e.symbol, (None, None))
        policies = ["D01"] + (["T1"] if e.is_t1 else []) \
            + (["T2"] if e.is_t2 else [])
        for family in NATURAL_FAMILIES:
            t = e.targets.get(family)
            base = {
                "candidate_id": f"{e.symbol}:{e.obs_feed_index}:{family}",
                "symbol": e.symbol, "policy": policies,
                "direction": e.direction,
                "entry_time": e.entry_time.isoformat(),
                "entry_price": e.entry_price,
                "stop_price": e.stop_price,
                "risk_distance_price": e.risk_distance,
                "risk_distance_pips_or_points": e.risk_distance_pips_or_points,
                "pip_or_point_unit": pip_unit,
                "target_family": family,
            }
            if t is None:
                reason = "TARGET_FAMILY_CONTRACT_INCOMPLETE" \
                    if FAMILY_CONTRACTS[family]["status"] != "CONTRACT_COMPLETE" \
                    else "NO_CAUSALLY_VALID_TARGET_AT_ENTRY"
                base.update({"available": False, "reason": reason,
                             "target_created_time": None, "target_price": None,
                             "target_distance_price": None, "target_R": None,
                             "causal_at_entry": None,
                             "reached_before_sl": None,
                             "time_to_target_bars": None})
            else:
                base.update({
                    "available": True, "reason": None,
                    "target_created_time": t.created_time.isoformat(),
                    "target_price": t.price,
                    "target_distance_price": t.distance,
                    "target_distance_pips_or_points":
                        (t.distance / pip_size) if pip_size else None,
                    "target_R": t.target_r,
                    "causal_at_entry": t.created_time <= e.entry_time,
                    "reached_before_sl": t.reached_before_sl,
                    "invalidated_by_stop": t.invalidated_by_stop,
                    "beyond_window": t.beyond_window,
                    "time_to_target_bars": t.time_to_target_bars,
                    "mfe_before_target_r": t.mfe_before_target_r,
                    "mae_before_target_r": t.mae_before_target_r})
            rows.append(base)
    return rows


def ladder_rows(entries: Sequence[EntryRecord]) -> list[dict]:
    """One row per entry: the ordered diagnostic target ladder."""
    rows: list[dict] = []
    for e in entries:
        rows.append({
            "ladder_id": f"{e.symbol}:{e.obs_feed_index}",
            "symbol": e.symbol, "direction": e.direction,
            "entry_time": e.entry_time.isoformat(),
            "is_t1": e.is_t1, "is_t2": e.is_t2,
            "target_ladder": [
                {"family": family, "price": price, "target_R": r,
                 "reached_before_sl": reached}
                for family, price, r, reached in e.ladder],
            "primary_target_family": e.nearest_family,
            "primary_target_R": e.nearest_target_r,
            "selection_reason": SELECTION_REASON if e.nearest_family else None,
            "furthest_target_family": e.furthest_family,
            "furthest_target_R": e.furthest_target_r,
            "multi_objective": e.multi_objective,
            "first_reached": e.nearest_reached,
            "second_target_R": e.second_target_r,
            "second_reached": e.second_reached,
            "third_target_R": e.third_target_r,
            "third_reached": e.third_reached,
        })
    return rows
