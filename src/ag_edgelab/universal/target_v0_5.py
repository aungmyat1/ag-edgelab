"""Universal Funnel V0.5 — TARGET MODEL DIAGNOSTICS (frozen upstream).

EXPERIMENT: TARGET_MODEL_DIAGNOSTICS_V1, parent 09ddc4d… (V0.4,
TRIGGER_RESEARCH_COMPLETE). Question: is the frozen fixed-R target model
mismatched with the causal natural market objective?

Everything upstream is FROZEN — D01/T1/T2, structure, premium/discount,
H1 flow, location, confirmation, entry geometry, SL geometry, sessions,
dataset lineage. This module only MEASURES target geometry:

  * entry populations are the frozen V0.3 campaign entries (D01) and their
    T1 sub-population (V0.4 policy states); every recomputed entry must
    reproduce the frozen MFE/MAE/fixed-reach fields exactly or the build
    fails loudly;
  * natural target families NT01..NT05 are selected STRICTLY from
    information available at entry time (TARGET_CREATED_TIME <= ENTRY_TIME,
    enforced structurally via closed-bar cuts and asserted per target);
  * stop/target collisions follow the frozen V0.3 fail-closed rule:
    the stop is counted FIRST;
  * NO TP change, no SL change, no parameter search, no per-stratum TP —
    classification thresholds below are preregistered diagnostics only.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.strategies.crypto_mtf_smc import confirmed_swing_points, detect_fvg
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
# Experiment identity + preregistered thresholds (fixed BEFORE evaluation)
# ---------------------------------------------------------------------------

EXPERIMENT_ID = "TARGET_MODEL_DIAGNOSTICS_V1"
EXPERIMENT_VERSION = "0.2.0-research"   # A-J governance hardening amendment
PARENT_SHA = "09ddc4d0f90eb1bf4ffbe00780e959d947177b6a"
PARENT_TREE = "ffa60fd6157c1af78e18f1b0f21cbd147abc4271"

# --- preregistered thresholds (frozen before evaluation; amendment A-J
# --- supersedes the 0.1.0 absolute-R tolerance with a ratio tolerance) ------
TARGET_FIT_TOLERANCE_PCT = 5.0  # ratio = FIXED_R / NATURAL_R; NEAR iff 0.95..1.05
                                # diagnostic comparison only — NOT a profit,
                                # execution, or edge threshold
DETERIORATION_PP = 5.0        # earliest chain element >= 5pp below its predecessor
SUPPORT_LOW = 0.25            # P(natural >= kR) below this => geometry does not support k
REALIZE_LOW = 0.25            # P(reach kR | natural >= kR) below this => continuation fails
REALIZE_MIN_N = 20            # fail-closed evidence floor: the REALIZE (continuation)
                              # leg is asserted only with >= 20 supported entries;
                              # below the floor it is UNMEASURABLE, never asserted
MEDIAN_MISMATCH_R = 3.0       # corroborating context ONLY — a low nearest-P50 is
                              # never by itself a TARGET_MODEL_MISMATCH diagnosis
MISMATCH_BEYOND_PCT = 0.60    # mismatch leg 2: fixed target beyond the natural
                              # objective in >= 60% of measurable entries (at 2R,
                              # the most conservative fixed level)
NATURAL_REACHABLE_LOW = 0.40  # mismatch leg 3: nearest causal objective itself is
                              # reached before SL in >= 40% of available entries
MIN_STRATUM_N = 100           # entries needed before a stratum diagnosis is issued
FAMILY_INSUFFICIENT_PCT = 0.50  # nearest-objective availability below this => family gap
ASYMMETRY_MEDIAN_R = 0.5      # BULL/BEAR nearest P50 gap for direction dependence
ASYMMETRY_REACH_PP = 5.0      # or 2R reach gap in percentage points
SL_INTERACTION_RATIO = 2.0    # Q1/Q4 nearest-median ratio (within-symbol risk quartiles)
RAW_COSCALING_RHO = 0.5       # SL/target interaction asserted only when raw target
                              # distance does NOT co-scale with risk distance
                              # (pooled within-symbol rank spearman < 0.5) — the
                              # normalized quartile gradient alone is mechanically
                              # coupled through the R denominator
MIN_CORR_N = 30               # correlations reported only when statistically supported
TAIL_SHIFT_R = 0.5            # D01 vs T1 upper-tail shift considered meaningful

# pip authority: fail-closed — only symbols with an authoritative pip size get
# pip-denominated distances; XAUUSD has no pip authority here => NULL, never 0.
PIP_SIZE = {"EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01}


NATURAL_FAMILIES = ("NT01_NEXT_SWING", "NT02_PDH_PDL", "NT03_LIQUIDITY",
                    "NT04_OPPOSING_SUPPLY_DEMAND", "NT05_FVG_IMBALANCE")
NEAREST_OBJECTIVE_RULE = ("per entry, the PRIMARY natural objective is the NEAREST "
                          "available family target (minimum TARGET_R across "
                          "NT01..NT05 valid at entry) — the first causal obstacle; "
                          "preregistered, never searched")
ENTRY_CLASSES = ("STOP_BEFORE_1R", "1R_ONLY", "2R_ONLY", "3R_ONLY", "4R_ONLY",
                 "5R_REACHED")
LIQUIDITY_RECENT_SWINGS = 6   # frozen V0.3 liquidity basis (last <= 6 confirmed swings)

TARGET_V0_5_REGISTRY_SHA256 = sha256_json({
    "experiment_id": EXPERIMENT_ID, "version": EXPERIMENT_VERSION,
    "parent_sha": PARENT_SHA,
    "families": NATURAL_FAMILIES,
    "nearest_objective_rule": NEAREST_OBJECTIVE_RULE,
    "collision_rule": "stop counted FIRST (frozen V0.3 fail-closed rule)",
    "amendment": "A-J governance hardening (owner directive, 2026-10-04): "
                 "ratio fit tolerance 5%, per-family persistence, eligibility-"
                 "gated nearest causal objective, objective ladder + reach "
                 "sequence, raw-distance geometry, coupling-labelled "
                 "correlations, refined root-cause evidence requirements; "
                 "supersedes the 0.1.0 absolute-R tolerance run entirely",
    "thresholds": {
        "target_fit_tolerance_pct": TARGET_FIT_TOLERANCE_PCT,
        "deterioration_pp": DETERIORATION_PP,
        "support_low": SUPPORT_LOW, "realize_low": REALIZE_LOW,
        "realize_min_n": REALIZE_MIN_N,
        "median_mismatch_r_corroborating_only": MEDIAN_MISMATCH_R,
        "mismatch_beyond_pct": MISMATCH_BEYOND_PCT,
        "natural_reachable_low": NATURAL_REACHABLE_LOW,
        "min_stratum_n": MIN_STRATUM_N,
        "family_insufficient_pct": FAMILY_INSUFFICIENT_PCT,
        "asymmetry_median_r": ASYMMETRY_MEDIAN_R,
        "asymmetry_reach_pp": ASYMMETRY_REACH_PP,
        "sl_interaction_ratio": SL_INTERACTION_RATIO,
        "raw_coscaling_rho": RAW_COSCALING_RHO,
        "min_corr_n": MIN_CORR_N,
        "tail_shift_r": TAIL_SHIFT_R,
        "pip_size_authority": PIP_SIZE,
    },
    "forbidden": ["TP change", "SL change", "parameter search",
                  "per-symbol/direction/session TP"],
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


SELECTION_REASON = "NEAREST_VALID_CAUSAL_OBJECTIVE"


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
    risk_distance_pips: float | None     # only where pip authority exists
    mfe_r: float
    mae_r: float
    mfe_distance: float                  # raw price MFE distance
    mae_distance: float                  # raw price MAE distance
    fixed_reached: dict
    time_to_r: dict                      # k -> bars after entry (int) | None
    entry_class: str
    targets: dict                        # family -> NaturalTargetRecord | None
    # NEAREST_CAUSAL_OBJECTIVE (eligibility-gated; diagnostic summary only)
    nearest_family: str | None
    nearest_price: float | None
    nearest_distance: float | None
    nearest_target_r: float | None
    nearest_reached: bool | None
    # full objective ladder, ascending by TARGET_R: (family, price, r, reached)
    ladder: tuple
    multi_objective: bool                # >= 2 distinct objective levels
    # MAX_CAUSAL_OBJECTIVE_AVAILABLE
    max_family: str | None
    max_target_r: float | None
    max_reached: bool | None
    # reach sequence (FIRST = nearest; SECOND = next strictly-farther level;
    # EXTENDED = max level when >= 3 distinct levels exist)
    second_target_r: float | None
    second_reached: bool | None
    extended_target_r: float | None
    extended_reached: bool | None
    is_t1: bool
    is_t2: bool


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
    """(reached_before_sl, invalidated_by_stop, beyond_window) — stop first."""
    for bar in forward[:OUTCOME_HORIZON_BARS]:
        if geometry.direction == Direction.BULL:
            hit_stop = bar.low <= geometry.stop
            hit_target = bar.high >= target_price
        else:
            hit_stop = bar.high >= geometry.stop
            hit_target = bar.low <= target_price
        if hit_stop:                      # frozen fail-closed collision rule
            return False, True, False
        if hit_target:
            return True, False, False
    return False, False, True


@dataclass(frozen=True)
class _SymbolContext:
    h4_highs: tuple                       # (price, confirmed_index) ascending by confirm
    h4_lows: tuple
    sd_zones: tuple                       # (created_index, side, lo, hi)
    fvgs: tuple                           # FairValueGap (index = third candle)
    close_h4: list
    close_d1: list
    h4: tuple
    d1: tuple


def build_symbol_context(frames: dict) -> _SymbolContext:
    h4, d1 = frames["H4"], frames["D1"]
    swings = confirmed_swing_points(h4, 2)
    highs = tuple((s.price, s.confirmed_index) for s in swings if s.kind == "HIGH")
    lows = tuple((s.price, s.confirmed_index) for s in swings if s.kind == "LOW")
    return _SymbolContext(
        h4_highs=highs, h4_lows=lows,
        sd_zones=tuple(_precompute_sd_zones(h4)),
        fvgs=detect_fvg(h4),
        close_h4=_cut_series(h4, 240), close_d1=_cut_series(d1, 1440),
        h4=h4, d1=d1)


def _natural_candidates(ctx: _SymbolContext, geometry: EntryGeometry,
                        entry_time: datetime) -> dict:
    """Family -> (price, created_time) using ONLY information at entry time."""
    c_h4 = bisect_right(ctx.close_h4, entry_time) - 1
    c_d1 = bisect_right(ctx.close_d1, entry_time) - 1
    bull = geometry.direction == Direction.BULL
    out: dict[str, tuple[float, datetime] | None] = {f: None for f in NATURAL_FAMILIES}
    if c_h4 < 0:
        return out

    def h4_time(index: int) -> datetime:
        return ctx.h4[index].timestamp + timedelta(minutes=240)

    swings = ctx.h4_highs if bull else ctx.h4_lows
    visible = [(p, ci) for p, ci in swings if ci <= c_h4]
    beyond = [(p, ci) for p, ci in visible
              if (p > geometry.entry) == bull and p != geometry.entry]
    # NT01: most recent confirmed opposing swing beyond entry (frozen V0.3 rule)
    if beyond:
        price, ci = beyond[-1]
        out["NT01_NEXT_SWING"] = (price, h4_time(ci))
    # NT03: nearest among the last <=6 confirmed swings (frozen liquidity basis)
    recent = visible[-LIQUIDITY_RECENT_SWINGS:]
    recent_beyond = [(p, ci) for p, ci in recent
                     if (p > geometry.entry) == bull and p != geometry.entry]
    if recent_beyond:
        price, ci = min(recent_beyond) if bull else max(recent_beyond)
        out["NT03_LIQUIDITY"] = (price, h4_time(ci))
    # NT02: directionally appropriate previous-day high/low
    if c_d1 >= 0:
        prev = ctx.d1[c_d1]
        price = prev.high if bull else prev.low
        if (price > geometry.entry) if bull else (price < geometry.entry):
            out["NT02_PDH_PDL"] = (price, prev.timestamp + timedelta(minutes=1440))
    # NT04: nearest opposing supply/demand zone edge beyond entry
    opposing_side = "RESISTANCE" if bull else "SUPPORT"
    zone_edges = []
    for created, side, lo, hi in ctx.sd_zones:
        if created <= c_h4 and side == opposing_side:
            edge = lo if bull else hi
            if (edge > geometry.entry) if bull else (edge < geometry.entry):
                zone_edges.append((edge, created))
    if zone_edges:
        edge, created = min(zone_edges) if bull else max(zone_edges)
        out["NT04_OPPOSING_SUPPLY_DEMAND"] = (edge, h4_time(created))
    # NT05: nearest opposing FVG midpoint beyond entry
    gap_dir = "BEARISH" if bull else "BULLISH"
    mids = [(g.midpoint, g.index) for g in ctx.fvgs
            if g.index <= c_h4 and g.direction == gap_dir
            and ((g.midpoint > geometry.entry) if bull else (g.midpoint < geometry.entry))]
    if mids:
        mid, idx = min(mids) if bull else max(mids)
        out["NT05_FVG_IMBALANCE"] = (mid, h4_time(idx))
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
            reached, invalidated, beyond = _target_reachability_impl(
                forward, geometry, price)
            targets[family] = NaturalTargetRecord(
                family=family, price=price, distance=distance, target_r=r,
                bucket=classify_target_r(r),
                created_time=created, entry_time=entry_time,
                reached_before_sl=reached, invalidated_by_stop=invalidated,
                beyond_window=beyond)

        # full objective ladder (ascending by TARGET_R; families kept visible)
        ladder = tuple(sorted(
            ((t.family, t.price, t.target_r, t.reached_before_sl)
             for t in targets.values() if t is not None),
            key=lambda row: (row[2], row[0])))
        distinct_levels = sorted({row[2] for row in ladder})
        multi_objective = len(distinct_levels) >= 2

        # NEAREST_CAUSAL_OBJECTIVE: among eligible targets, smallest positive
        # distance from entry (== min positive TARGET_R under the frozen SL)
        if ladder:
            n_family, n_price, n_r, n_reached = ladder[0]
            nearest = targets[n_family]
            nearest_distance = nearest.distance
        else:
            n_family = n_price = n_r = n_reached = nearest_distance = None
        # MAX_CAUSAL_OBJECTIVE_AVAILABLE
        if ladder:
            x_family, _, x_r, x_reached = ladder[-1]
        else:
            x_family = x_r = x_reached = None
        # SECOND = next strictly-farther distinct level after FIRST
        second_r = second_reached = None
        if ladder and len(distinct_levels) >= 2:
            for fam2, _, r2, reached2 in ladder:
                if r2 > ladder[0][2]:
                    second_r, second_reached = r2, reached2
                    break
        # EXTENDED = max level, defined only when >= 3 distinct levels exist
        extended_r = extended_reached = None
        if len(distinct_levels) >= 3:
            extended_r, extended_reached = x_r, x_reached

        en = en_by_index[obs.feed_index]
        pip = PIP_SIZE.get(campaign.symbol)
        records.append(EntryRecord(
            symbol=campaign.symbol, obs_feed_index=obs.feed_index, entry_index=e_idx,
            entry_time=entry_time, direction=direction.value,
            session=session_label(entry_time),
            entry_price=entry_price, stop_price=stop, risk_distance=geometry.risk,
            risk_distance_pips=(geometry.risk / pip) if pip else None,
            mfe_r=obs.entry_mfe_r, mae_r=obs.entry_mae_r,
            mfe_distance=obs.entry_mfe_r * geometry.risk,
            mae_distance=obs.entry_mae_r * geometry.risk,
            fixed_reached=dict(obs.fixed_reached), time_to_r=time_to,
            entry_class=_entry_class(obs.fixed_reached), targets=targets,
            nearest_family=n_family, nearest_price=n_price,
            nearest_distance=nearest_distance, nearest_target_r=n_r,
            nearest_reached=n_reached,
            ladder=ladder, multi_objective=multi_objective,
            max_family=x_family, max_target_r=x_r, max_reached=x_reached,
            second_target_r=second_r, second_reached=second_reached,
            extended_target_r=extended_r, extended_reached=extended_reached,
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
    out = {}
    n = len(entries)
    for family in NATURAL_FAMILIES:
        avail = [e.targets[family] for e in entries if e.targets[family] is not None]
        reached = sum(1 for t in avail if t.reached_before_sl)
        invalidated = sum(1 for t in avail if t.invalidated_by_stop)
        beyond = sum(1 for t in avail if t.beyond_window)
        out[family] = {
            "INPUT_N": n,
            "TARGET_AVAILABLE_N": len(avail),
            "TARGET_AVAILABLE_PCT": (len(avail) / n) if n else None,
            "TARGET_REACHED_BEFORE_SL_N": reached,
            "TARGET_REACHED_PCT": (reached / len(avail)) if avail else None,
            "TARGET_NOT_REACHED_N": len(avail) - reached,
            "TARGET_INVALIDATED_N": invalidated,
            "TARGET_BEYOND_WINDOW_N": beyond,
            "target_r_quantiles": quantile_block([t.target_r for t in avail]),
            "bucket_histogram": {b: sum(1 for t in avail if t.bucket == b)
                                 for b in TARGET_R_BUCKETS},
        }
    nearest = [e.nearest_target_r for e in entries if e.nearest_target_r is not None]
    out["NEAREST_OBJECTIVE"] = {
        "rule": NEAREST_OBJECTIVE_RULE,
        "INPUT_N": n,
        "TARGET_AVAILABLE_N": len(nearest),
        "TARGET_AVAILABLE_PCT": (len(nearest) / n) if n else None,
        "family_share": {f: sum(1 for e in entries if e.nearest_family == f)
                         for f in NATURAL_FAMILIES},
        "target_r_quantiles": quantile_block(nearest),
        "bucket_histogram": {b: sum(1 for e in entries if e.nearest_target_r is not None
                                    and classify_target_r(e.nearest_target_r) == b)
                             for b in TARGET_R_BUCKETS},
    }
    return out


def fit_class_for(k: int, natural_r: float | None) -> tuple[str | None, str | None]:
    """Preregistered ratio rule (TARGET_FIT_TOLERANCE_PCT = 5.0):
    ratio = FIXED_TARGET_R / NATURAL_TARGET_R; BELOW < 0.95, NEAR 0.95..1.05,
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


def fit_classification(entries: Sequence[EntryRecord], k: int) -> dict:
    below = near = above = null_n = 0
    for e in entries:
        cls, _reason = fit_class_for(k, e.nearest_target_r)
        if cls is None:
            null_n += 1
        elif cls == "FIXED_TARGET_BELOW_NATURAL":
            below += 1          # fixed target sits BELOW the natural objective
        elif cls == "FIXED_TARGET_ABOVE_NATURAL":
            above += 1          # fixed target overshoots the natural objective
        else:
            near += 1
    measurable = below + near + above
    pct = (lambda x: x / measurable if measurable else None)
    return {"fixed_level": f"{k}R",
            "tolerance_pct": TARGET_FIT_TOLERANCE_PCT,
            "tolerance_semantics": "diagnostic comparison only; not a profit, "
                                   "execution, or edge threshold",
            "FIXED_TARGET_BELOW_NATURAL_N": below,
            "FIXED_TARGET_NEAR_NATURAL_N": near,
            "FIXED_TARGET_ABOVE_NATURAL_N": above,
            "NULL_N": null_n,
            "null_reason": "INVALID_OR_UNAVAILABLE_NATURAL_TARGET",
            "pct_below_natural": pct(below),
            "pct_near_natural": pct(near),
            "pct_beyond_natural": pct(above)}


def target_fit_curve(entries: Sequence[EntryRecord]) -> dict:
    return {f"{k}R": fit_classification(entries, k) for k in FIXED_R_TARGETS}


def level_diagnostic(entries: Sequence[EntryRecord], k: int) -> dict:
    """SUPPORT_k = P(natural >= kR); REALIZE_k = P(reach kR | natural >= kR);
    LEAK_k = P(reach kR | natural < kR)."""
    with_nat = [e for e in entries if e.nearest_target_r is not None]
    ge = [e for e in with_nat if e.nearest_target_r >= k]
    lt = [e for e in with_nat if e.nearest_target_r < k]
    reach = lambda rows: (sum(1 for e in rows if e.fixed_reached.get(k, False)) / len(rows)) \
        if rows else None
    return {"level": f"{k}R",
            "natural_ge_level_n": len(ge),
            "SUPPORT_pct": (len(ge) / len(with_nat)) if with_nat else None,
            "REALIZE_when_supported_pct": reach(ge),
            "reach_when_not_supported_pct": reach(lt),
            "support_low_threshold": SUPPORT_LOW,
            "realize_low_threshold": REALIZE_LOW,
            "realize_min_n": REALIZE_MIN_N,
            "realize_measurable": len(ge) >= REALIZE_MIN_N}


def level_verdict(diag: dict, *, apply_realize_floor: bool = True) -> str:
    """Geometry/continuation verdict for one fixed level.

    The continuation (REALIZE) leg is asserted only above the preregistered
    REALIZE_MIN_N evidence floor; `apply_realize_floor=False` exposes the raw
    rule output for transparency (never used as the published verdict).
    """
    support, realize = diag["SUPPORT_pct"], diag["REALIZE_when_supported_pct"]
    if support is None:
        return "INSUFFICIENT_EVIDENCE"
    geometry = support < SUPPORT_LOW
    measurable = realize is not None and \
        (not apply_realize_floor or diag["natural_ge_level_n"] >= REALIZE_MIN_N)
    continuation = measurable and realize < REALIZE_LOW
    if geometry and continuation:
        return "BOTH"
    if geometry:
        return "TARGET_GEOMETRY_MISMATCH"
    if continuation:
        return "CONTINUATION_FAILURE"
    if not measurable:
        return "INSUFFICIENT_EVIDENCE"
    return "NEITHER"


def distribution_comparison(d01_entries, t1_entries) -> dict:
    dq = quantile_block([e.nearest_target_r for e in d01_entries
                         if e.nearest_target_r is not None])
    tq = quantile_block([e.nearest_target_r for e in t1_entries
                         if e.nearest_target_r is not None])
    deltas = {p: (tq[p] - dq[p]) if tq[p] is not None and dq[p] is not None else None
              for p in ("P10", "P25", "P50", "P75", "P90")}
    upper = [deltas["P75"], deltas["P90"]]
    meaningful = any(d is not None and d >= TAIL_SHIFT_R for d in upper)
    return {"D01": dq, "T1": tq, "deltas_t1_minus_d01": deltas,
            "tail_shift_threshold_r": TAIL_SHIFT_R,
            "upper_tail_meaningfully_improved": bool(meaningful),
            "answer": ("T1 meaningfully improved the upper target tail"
                       if meaningful else
                       "T1 shifted the distribution only modestly; the upper tail "
                       "(P75/P90) did not improve by the preregistered threshold")}


# ---------------------------------------------------------------------------
# Correlations (G) — descriptive only; Pearson/Spearman where supported
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
    # name -> (x getter, y getter); raw price scales differ per symbol, so
    # Pearson/Spearman are computed WITHIN symbol; the pooled statistic is a
    # Spearman over within-symbol normalized ranks (scale-free).
    "RISK_VS_TARGET_R": lambda e: (e.risk_distance, e.nearest_target_r),
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
    out["RISK_VS_TARGET_R"]["label"] = "MECHANICALLY_COUPLED_DIAGNOSTIC"
    out["RISK_VS_TARGET_R"]["caution"] = (
        "NATURAL_TARGET_R = TARGET_DISTANCE / RISK_DISTANCE: the denominator "
        "couples this statistic to risk mechanically. Do NOT infer that a "
        "tight stop causes larger opportunity (or a wide stop smaller "
        "opportunity) from this value alone; interpret SL/target interaction "
        "from the raw-distance relationships and stratified distributions.")
    return out


# ---------------------------------------------------------------------------
# Objective ladder / reach sequence (D, E)
# ---------------------------------------------------------------------------

def objective_ladder_report(entries: Sequence[EntryRecord]) -> dict:
    n = len(entries)
    first = [e for e in entries if e.nearest_target_r is not None]
    second = [e for e in entries if e.second_target_r is not None]
    extended = [e for e in entries if e.extended_target_r is not None]
    multi_n = sum(1 for e in entries if e.multi_objective)
    first_reached = [e for e in first if e.nearest_reached]
    second_and_first_reached = [e for e in second if e.nearest_reached]
    pct = lambda num, rows: (num / len(rows)) if rows else None
    return {
        "note": "price need not stop permanently at the nearest objective; the "
                "full ladder is preserved per entry (FIRST / SECONDARY / "
                "EXTENDED objectives kept distinct)",
        "entry_n": n,
        "MULTI_OBJECTIVE_ENTRY_PCT": (multi_n / n) if n else None,
        "FIRST_OBJECTIVE_REACHED_PCT":
            pct(sum(1 for e in first if e.nearest_reached), first),
        "SECOND_OBJECTIVE_REACHED_PCT":
            pct(sum(1 for e in second if e.second_reached), second),
        "EXTENDED_OBJECTIVE_REACHED_PCT":
            pct(sum(1 for e in extended if e.extended_reached), extended),
        "P_SECOND_REACHED_GIVEN_FIRST_REACHED":
            pct(sum(1 for e in second_and_first_reached if e.second_reached),
                second_and_first_reached),
        "MAX_OBJECTIVE_REACHED_PCT":
            pct(sum(1 for e in first if e.max_reached), first),
        "nearest_r_quantiles": quantile_block(
            [e.nearest_target_r for e in first]),
        "max_causal_objective_r_quantiles": quantile_block(
            [e.max_target_r for e in entries if e.max_target_r is not None]),
    }


def sl_target_interaction(entries: Sequence[EntryRecord]) -> dict:
    """SL/target coupling diagnostics (frozen SL; nothing is re-stopped).

    Stratified evidence: within-symbol risk-distance quartiles (H).
    Raw evidence: risk vs raw target distance co-scaling (G).  The normalized
    Q1/Q4 gradient alone is mechanically coupled through the R denominator and
    is therefore NEVER sufficient: interaction is asserted only when the
    gradient is present AND raw target distance does not co-scale with risk.
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
            "median_natural_target_r": med([e.nearest_target_r for e in rows])
            if rows else None,
            "median_mfe_r": med([e.mfe_r for e in rows]) if rows else None,
            "median_mae_r": med([e.mae_r for e in rows]) if rows else None,
            "fixed_reach": {f"{k}R": (sum(1 for e in rows
                                          if e.fixed_reached.get(k, False)) / len(rows))
                            if rows else None for k in FIXED_R_TARGETS},
        }
    med_r = {q: table[q]["median_natural_target_r"] for q in table}
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
            "risk_quartile_target_analysis": table,
            "nearest_target_r_median_by_risk_quartile": med_r,
            "q1_over_q4_ratio": ratio,
            "q1_over_q4_ratio_label": "MECHANICALLY_COUPLED_DIAGNOSTIC "
                                      "(R denominator)",
            "preregistered_ratio_threshold": SL_INTERACTION_RATIO,
            "raw_coscaling_rho_threshold": RAW_COSCALING_RHO,
            "risk_vs_target_distance_rank_spearman": raw_rho,
            "correlations": coupling,
            "SL_TARGET_GEOMETRY_INTERACTION": interaction,
            "decision_rule": "YES iff Q1/Q4 nearest-median ratio >= 2.0 AND "
                             "pooled within-symbol rank spearman(risk, raw "
                             "target distance) < 0.5 (gradient not explained "
                             "by genuine raw co-scaling)",
            "quartile_rule_note": "quartiles are diagnostic strata only, never "
                                  "trading rules",
            "note": "SL remains frozen; no alternative SL tested in V0.5"}


def stratum_diagnosis(entries: Sequence[EntryRecord]) -> dict:
    """Per-stratum target state under the refined (amendment I) evidence rules.

    TARGET_MODEL_MISMATCH requires ALL THREE legs — never merely a low median:
      1. valid natural objectives frequently exist
         (nearest availability >= FAMILY_INSUFFICIENT_PCT);
      2. the fixed target frequently lies materially beyond those objectives
         (ratio-fit ABOVE share >= MISMATCH_BEYOND_PCT at 2R, the most
         conservative fixed level — monotone in k);
      3. the natural objective is itself reasonably reachable
         (nearest objective reached before SL >= NATURAL_REACHABLE_LOW).
    TARGET_CONTINUATION_WEAKNESS requires a level k in 2..5 where geometry
    supports the move (natural >= kR, n >= REALIZE_MIN_N) yet price commonly
    fails to continue (REALIZE_k < REALIZE_LOW), or entries commonly failing
    to reach even the nearest causally existing objective.
    """
    if len(entries) < MIN_STRATUM_N:
        return {"n": len(entries), "diagnosis": "INSUFFICIENT_EVIDENCE",
                "reason": f"n < {MIN_STRATUM_N}"}
    with_nat = [e for e in entries if e.nearest_target_r is not None]
    avail_pct = len(with_nat) / len(entries)
    if avail_pct < FAMILY_INSUFFICIENT_PCT:
        return {"n": len(entries), "diagnosis": "TARGET_FAMILY_INSUFFICIENT",
                "nearest_available_pct": avail_pct}

    fit2 = fit_classification(entries, 2)
    nearest_reached_pct = (sum(1 for e in with_nat if e.nearest_reached)
                           / len(with_nat)) if with_nat else None
    p50 = _quantile(sorted(e.nearest_target_r for e in with_nat), 0.5)

    mismatch_legs = {
        "leg1_objectives_frequently_exist": avail_pct >= FAMILY_INSUFFICIENT_PCT,
        "leg2_fixed_frequently_beyond":
            fit2["pct_beyond_natural"] is not None
            and fit2["pct_beyond_natural"] >= MISMATCH_BEYOND_PCT,
        "leg3_natural_objective_reachable":
            nearest_reached_pct is not None
            and nearest_reached_pct >= NATURAL_REACHABLE_LOW,
    }
    mismatch = all(mismatch_legs.values())

    levels = {}
    continuation_levels = []
    for k in (2, 3, 4, 5):
        d = level_diagnostic(entries, k)
        v = level_verdict(d)
        levels[f"{k}R"] = {"diagnostic": d, "verdict": v}
        if v in ("CONTINUATION_FAILURE", "BOTH"):
            continuation_levels.append(f"{k}R")
    nearest_commonly_unreached = (
        nearest_reached_pct is not None and len(with_nat) >= REALIZE_MIN_N
        and nearest_reached_pct < NATURAL_REACHABLE_LOW)
    continuation = bool(continuation_levels) or nearest_commonly_unreached

    if mismatch and continuation:
        label = "TARGET_MODEL_AND_CONTINUATION_WEAKNESS"
    elif mismatch:
        label = "TARGET_MODEL_MISMATCH"
    elif continuation:
        label = "TARGET_CONTINUATION_WEAKNESS"
    else:
        label = "NONE_DETECTED"
    return {"n": len(entries), "diagnosis": label,
            "nearest_available_pct": avail_pct,
            "nearest_reached_before_sl_pct": nearest_reached_pct,
            "nearest_p50_r": p50,
            "nearest_p50_r_role": "corroborating context only (never decisive)",
            "mismatch_evidence": {**mismatch_legs,
                                  "fit_2r_pct_beyond": fit2["pct_beyond_natural"],
                                  "thresholds": {
                                      "mismatch_beyond_pct": MISMATCH_BEYOND_PCT,
                                      "natural_reachable_low": NATURAL_REACHABLE_LOW,
                                      "family_insufficient_pct":
                                          FAMILY_INSUFFICIENT_PCT}},
            "continuation_evidence": {
                "levels_with_continuation_failure": continuation_levels,
                "nearest_objective_commonly_unreached": nearest_commonly_unreached,
                "level_detail": levels}}


def direction_asymmetry(bull: dict, bear: dict) -> dict:
    """bull/bear are stratum_diagnosis outputs plus reach data supplied by caller."""
    gap_median = None
    if bull.get("nearest_p50_r") is not None and bear.get("nearest_p50_r") is not None:
        gap_median = abs(bull["nearest_p50_r"] - bear["nearest_p50_r"])
    gap_reach = None
    if bull.get("reach_2r") is not None and bear.get("reach_2r") is not None:
        gap_reach = abs(bull["reach_2r"] - bear["reach_2r"]) * 100.0
    asymmetric = (gap_median is not None and gap_median > ASYMMETRY_MEDIAN_R) or \
                 (gap_reach is not None and gap_reach > ASYMMETRY_REACH_PP)
    return {"median_gap_r": gap_median, "reach_2r_gap_pp": gap_reach,
            "thresholds": {"median_r": ASYMMETRY_MEDIAN_R, "reach_pp": ASYMMETRY_REACH_PP},
            "TARGET_GEOMETRY_DIRECTION_DEPENDENT": bool(asymmetric),
            "no_direction_specific_tp_created": True}


def root_cause(pooled_diag: dict, symbol_diags: dict, asym: dict, sl: dict,
               d01_n: int) -> dict:
    allowed_next = {"TARGET_MODEL_MISMATCH": "PREREGISTER_NATURAL_TARGET_POLICY",
                    "TARGET_MODEL_AND_CONTINUATION_WEAKNESS":
                        "PREREGISTER_HYBRID_TARGET_POLICY",
                    "TARGET_CONTINUATION_WEAKNESS": "KEEP_FIXED_TARGET_RESEARCH",
                    "TARGET_FAMILY_INSUFFICIENT": "INSUFFICIENT_EVIDENCE",
                    "INSUFFICIENT_EVIDENCE": "INSUFFICIENT_EVIDENCE",
                    "NONE_DETECTED": "KEEP_FIXED_TARGET_RESEARCH"}
    primary = pooled_diag["diagnosis"]
    secondary = []
    pooled_label = primary
    for sym, d in symbol_diags.items():
        if d["diagnosis"] not in (pooled_label, "INSUFFICIENT_EVIDENCE"):
            secondary.append("TARGET_GEOMETRY_SYMBOL_DEPENDENT")
            break
    if asym["TARGET_GEOMETRY_DIRECTION_DEPENDENT"]:
        secondary.append("TARGET_GEOMETRY_DIRECTION_DEPENDENT")
    if sl["SL_TARGET_GEOMETRY_INTERACTION"] == "YES":
        secondary.append("SL_TARGET_GEOMETRY_INTERACTION")
    next_research = allowed_next[primary]
    if primary in ("TARGET_MODEL_MISMATCH", "TARGET_MODEL_AND_CONTINUATION_WEAKNESS") \
            and sl["SL_TARGET_GEOMETRY_INTERACTION"] == "YES" \
            and sl["q1_over_q4_ratio"] is not None \
            and sl["q1_over_q4_ratio"] >= 3.0:
        next_research = "TEST_SL_TARGET_INTERACTION"
    return {"primary": primary, "secondary": secondary,
            "next_recommended_research": next_research,
            "pooled_entry_n": d01_n,
            "mapping": allowed_next,
            "TARGET_MODEL_MISMATCH_EVIDENCE":
                pooled_diag.get("mismatch_evidence"),
            "TARGET_CONTINUATION_WEAKNESS_EVIDENCE": {
                k: v for k, v in
                (pooled_diag.get("continuation_evidence") or {}).items()
                if k != "level_detail"},
            "SL_TARGET_INTERACTION_EVIDENCE": {
                "interaction": sl["SL_TARGET_GEOMETRY_INTERACTION"],
                "q1_over_q4_ratio_mechanically_coupled": sl.get("q1_over_q4_ratio"),
                "risk_vs_target_distance_rank_spearman":
                    sl.get("risk_vs_target_distance_rank_spearman"),
                "decision_rule": sl.get("decision_rule")},
            "no_tp_changed": True, "no_sl_changed": True,
            "no_parameter_search": True}


# ---------------------------------------------------------------------------
# Per-entry persistence (B/C/D/E/F) — raw families never collapsed
# ---------------------------------------------------------------------------

def entry_ledger_rows(entries: Sequence[EntryRecord]) -> list[dict]:
    """Serializable per-entry ledger: every natural family persisted
    separately (never collapsed), the eligibility-gated nearest causal
    objective, the full objective ladder, the reach sequence, and raw
    price/pip distances alongside normalized R metrics."""
    rows: list[dict] = []
    for e in entries:
        pip = PIP_SIZE.get(e.symbol)
        fam: dict[str, dict] = {}
        for family in NATURAL_FAMILIES:
            t = e.targets.get(family)
            if t is None:
                fam[family] = {
                    "target_family": family, "target_available": False,
                    "target_price": None, "target_created_time": None,
                    "target_distance": None, "target_distance_pips": None,
                    "target_R": None, "target_reached_before_SL": None,
                    "target_invalidated_by_stop": None,
                    "target_beyond_window": None,
                    "null_reason": "NO_CAUSALLY_VALID_TARGET_AT_ENTRY"}
            else:
                fam[family] = {
                    "target_family": family, "target_available": True,
                    "target_price": t.price,
                    "target_created_time": t.created_time.isoformat(),
                    "target_distance": t.distance,
                    "target_distance_pips": (t.distance / pip) if pip else None,
                    "target_R": t.target_r,
                    "target_reached_before_SL": t.reached_before_sl,
                    "target_invalidated_by_stop": t.invalidated_by_stop,
                    "target_beyond_window": t.beyond_window}
        rows.append({
            "symbol": e.symbol, "entry_time": e.entry_time.isoformat(),
            "direction": e.direction, "session": e.session,
            "is_t1": e.is_t1, "is_t2": e.is_t2,
            "entry_price": e.entry_price, "stop_price": e.stop_price,
            "RISK_DISTANCE_PRICE": e.risk_distance,
            "RISK_DISTANCE_PIPS": e.risk_distance_pips,
            "MFE_DISTANCE_PRICE": e.mfe_distance,
            "MAE_DISTANCE_PRICE": e.mae_distance,
            "MFE_R": e.mfe_r, "MAE_R": e.mae_r,
            "fixed_reached": {f"{k}R": bool(e.fixed_reached.get(k, False))
                              for k in FIXED_R_TARGETS},
            "time_to_r_bars": {f"{k}R": e.time_to_r[k] for k in FIXED_R_TARGETS},
            "entry_class": e.entry_class,
            "targets": fam,
            "primary_target_family": e.nearest_family,
            "primary_target_price": e.nearest_price,
            "primary_target_distance": e.nearest_distance,
            "primary_target_R": e.nearest_target_r,
            "primary_target_reached_before_SL": e.nearest_reached,
            "selection_reason": SELECTION_REASON if e.nearest_family else None,
            "objective_ladder": [
                {"family": fam_name, "price": price, "target_R": r,
                 "reached_before_SL": reached}
                for fam_name, price, r, reached in e.ladder],
            "multi_objective": e.multi_objective,
            "MAX_CAUSAL_OBJECTIVE_FAMILY": e.max_family,
            "MAX_CAUSAL_OBJECTIVE_R": e.max_target_r,
            "max_objective_reached_before_SL": e.max_reached,
            "FIRST_TARGET_REACHED": e.nearest_reached,
            "SECOND_TARGET_R": e.second_target_r,
            "SECOND_TARGET_REACHED": e.second_reached,
            "EXTENDED_TARGET_R": e.extended_target_r,
            "EXTENDED_TARGET_REACHED": e.extended_reached,
        })
    return rows
