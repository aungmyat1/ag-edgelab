"""Universal Funnel V0.4 — TRIGGER RESEARCH (D01 vs T1 vs T2).

EXPERIMENT_ID = MTF_DIRECTION_TRIGGER_V1, parent = frozen V0.3 FX DEV result
(977f99c…, PRIMARY_DIAGNOSIS = TRIGGER_FUNNEL_WEAKNESS). This module tests
ONLY whether two preregistered trigger policies improve the weak direction
trigger and whether that improvement propagates into downstream target
capability. Nothing downstream of the trigger changes:

  * location rules, confirmation contracts, entry/SL geometry, 1R–5R and
    natural-target definitions are the frozen V0.3 implementations — every
    downstream outcome is read from the UNCHANGED V0.3 campaign engine
    (``run_fx_symbol_campaign``), never recomputed differently per policy;
  * every policy's non-NEUTRAL decision equals the H4 structural direction,
    so T1/T2 directional populations are strict sub-populations of D01 with
    identical downstream semantics (comparable by construction).

Causal state model (three concepts, never collapsed):
  MACRO DIRECTION  = H4 structure (BULL/BEAR/NEUTRAL)
  PHASE            = macro x H1 internal flow (continuation / pullback)
  LOCATION         = frozen H4 dealing-range EQ (DISCOUNT/PREMIUM/MIDRANGE)
Location never erases phase: H4 BULL + H1 BEAR + PREMIUM stays
macro=BULL, phase=BULL_PULLBACK, location=PREMIUM.

The +5pp separation threshold is a RESEARCH_DIAGNOSTIC_THRESHOLD only —
not an edge, profit, production, or deployment threshold.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Sequence

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.universal.confirmation import ConfirmationPrimitive, structure_shift_events
from ag_edgelab.universal.direction import Direction
from ag_edgelab.universal.fx_dev_campaign import (CONFIRMATION_WINDOW_BARS,
                                                  ENTRY_CONDITIONED_BASIS,
                                                  INCOMPARABLE_REASON,
                                                  OUTCOME_HORIZON_BARS, OBS_MINUTE,
                                                  OBS_WARMUP_DAYS, STOP_LOOKBACK_BARS,
                                                  FxObservation, SymbolCampaign,
                                                  _cut_series, _decided_mfe,
                                                  _opposite_mfe, build_series,
                                                  context_at, reach_share)
from ag_edgelab.universal.matrix import CAPABILITY_BASIS
from ag_edgelab.universal.targets import EntryGeometry, FIXED_R_TARGETS, compute_excursions

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Experiment identity (frozen)
# ---------------------------------------------------------------------------

EXPERIMENT_ID = "MTF_DIRECTION_TRIGGER_V1"
EXPERIMENT_VERSION = "0.1.0-research"
PARENT_SHA = "977f99c53b3952dacc684056b60e7e49d6145d30"
PARENT_TREE = "d2c374a57e9026497ac04dc5f28b4b6a587bf7aa"

# Preregistered thresholds — fixed BEFORE any T1/T2 target result is computed.
RESEARCH_DIAGNOSTIC_THRESHOLD_PP = 5.0   # label: RESEARCH_DIAGNOSTIC_THRESHOLD only
MATERIAL_DELTA_2R_PP = 5.0               # material target improvement needs BOTH:
MATERIAL_DELTA_3R_PP = 3.0               #   d2R >= +5pp AND d3R >= +3pp vs D01
MIN_POLICY_DIRECTIONAL_N = 200           # pooled floors, else RESULT TYPE D
MIN_POLICY_ENTERED_N = 100
REALIGN_WINDOW_H1_BARS = 60              # pullback realignment MEASUREMENT window
                                         # (diagnostic horizon, NOT a max-wait rule)
STABILITY_MIN_CELL_N = 50                # location/confirmation stability cell floor
CONFIRMATION_DEGRADE_PP = -5.0           # same-basis uplift <= -5pp => degrades
MA_ABLATION_SEPARATION_PP = 2.0          # MA must add >= +2pp separation AND not
                                         # reduce 2R capability to count as value
TARGET_SHIFT_BAND_PP = 2.0               # |d2R| <= 2pp => UNCHANGED distribution

PHASES = ("BULL_CONTINUATION", "BULL_PULLBACK", "BEAR_CONTINUATION",
          "BEAR_PULLBACK", "NEUTRAL")
POLICIES = ("D01", "T1", "T2")           # T2MA exists only as an ablation
LOCATION_LABELS = ("DISCOUNT", "PREMIUM", "MIDRANGE", "UNAVAILABLE")

POLICY_DEFINITIONS = {
    "D01": "frozen V0.3 baseline: H4 structural direction only (BULL on confirmed "
           "HH/HL, BEAR on confirmed LH/LL, else NEUTRAL)",
    "T1": "strict alignment: BUY iff H4=BULL AND H1 internal flow=BULL AND "
          "location=DISCOUNT; SELL iff H4=BEAR AND H1 internal flow=BEAR AND "
          "location=PREMIUM; else NEUTRAL",
    "T2": "phase-aware: BUY iff phase=BULL_CONTINUATION; SELL iff "
          "phase=BEAR_CONTINUATION; pullback phases remain explicit states "
          "(measured for causal H1 realignment), never auto-traded; else NEUTRAL",
    "T2_MA": "ablation only (NOT part of T1/T2): T2 direction kept only when "
             "H1 MA50/200 direction agrees; MA parameters not tuned",
}

TRIGGER_POLICY_REGISTRY_SHA256 = sha256_json({
    "experiment_id": EXPERIMENT_ID,
    "version": EXPERIMENT_VERSION,
    "parent_sha": PARENT_SHA,
    "policies": POLICY_DEFINITIONS,
    "phase_model": {
        "BULL_CONTINUATION": "H4 BULL + H1 flow BULL",
        "BULL_PULLBACK": "H4 BULL + H1 flow BEAR",
        "BEAR_CONTINUATION": "H4 BEAR + H1 flow BEAR",
        "BEAR_PULLBACK": "H4 BEAR + H1 flow BULL",
        "NEUTRAL": "H4 NEUTRAL (or H1 flow NEUTRAL -> no phase commitment)",
    },
    "location_source": "frozen V0.3 active H4 dealing range EQ (premium/discount)",
    "thresholds": {
        "research_diagnostic_threshold_pp": RESEARCH_DIAGNOSTIC_THRESHOLD_PP,
        "material_delta_2r_pp": MATERIAL_DELTA_2R_PP,
        "material_delta_3r_pp": MATERIAL_DELTA_3R_PP,
        "min_policy_directional_n": MIN_POLICY_DIRECTIONAL_N,
        "min_policy_entered_n": MIN_POLICY_ENTERED_N,
        "realign_window_h1_bars": REALIGN_WINDOW_H1_BARS,
    },
})


# ---------------------------------------------------------------------------
# Causal state model
# ---------------------------------------------------------------------------

def phase_of(h4: Direction, h1_flow: Direction) -> str:
    """PHASE = macro direction x H1 internal flow. Location plays no part."""
    if h4 == Direction.BULL:
        if h1_flow == Direction.BULL:
            return "BULL_CONTINUATION"
        if h1_flow == Direction.BEAR:
            return "BULL_PULLBACK"
        return "NEUTRAL"
    if h4 == Direction.BEAR:
        if h1_flow == Direction.BEAR:
            return "BEAR_CONTINUATION"
        if h1_flow == Direction.BULL:
            return "BEAR_PULLBACK"
        return "NEUTRAL"
    return "NEUTRAL"


def location_label(pd_state: str | None) -> str:
    """Frozen V0.3 EQ implementation, relabelled only (EQUILIBRIUM->MIDRANGE)."""
    if pd_state is None:
        return "UNAVAILABLE"
    return {"DISCOUNT": "DISCOUNT", "PREMIUM": "PREMIUM",
            "EQUILIBRIUM": "MIDRANGE"}[pd_state]


def t1_direction(h4: Direction, h1_flow: Direction, pd_state: str | None) -> Direction:
    if h4 == Direction.BULL and h1_flow == Direction.BULL and pd_state == "DISCOUNT":
        return Direction.BULL
    if h4 == Direction.BEAR and h1_flow == Direction.BEAR and pd_state == "PREMIUM":
        return Direction.BEAR
    return Direction.NEUTRAL


def t2_direction(phase: str) -> Direction:
    if phase == "BULL_CONTINUATION":
        return Direction.BULL
    if phase == "BEAR_CONTINUATION":
        return Direction.BEAR
    return Direction.NEUTRAL


def t2ma_direction(t2: Direction, ma: Direction) -> Direction:
    """Ablation only: keep T2 direction iff MA50/200 agrees."""
    return t2 if t2 != Direction.NEUTRAL and ma == t2 else Direction.NEUTRAL


def session_label(ts: datetime) -> str:
    """Stratification label from the frozen V0.3 session definitions.

    LONDON_NEWYORK_OVERLAP = 13:00-16:00 UTC takes precedence; sessions are
    diagnostic strata only, never trigger requirements.
    """
    hour = ts.astimezone(UTC).hour
    if 13 <= hour < 16:
        return "LONDON_NEWYORK_OVERLAP"
    if 8 <= hour < 13:
        return "LONDON"
    if 16 <= hour < 21:
        return "NEW_YORK"
    if 0 <= hour < 8:
        return "ASIAN"
    return "OFF_SESSION"


# ---------------------------------------------------------------------------
# Enrichment: policy states per frozen V0.3 observation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EnrichedObservation:
    feed_index: int
    observed_at: datetime
    symbol: str
    h4: str
    h1_flow: str
    phase: str
    pd_state: str | None
    location: str                  # DISCOUNT | PREMIUM | MIDRANGE | UNAVAILABLE
    ma: str
    t1: str
    t2: str
    t2ma: str
    session: str
    # pullback realignment diagnostics (None unless phase is a pullback)
    realign_measured: bool = False
    realigned: bool | None = None
    realign_delay_h1: int | None = None
    realign_direction: str | None = None
    realign_location: str | None = None
    realign_confirmation_available: bool | None = None
    realign_capability_mfe_r: float | None = None
    realign_censored: bool = False


@dataclass(frozen=True)
class JoinedObs:
    v3: FxObservation
    en: EnrichedObservation

    def direction(self, policy: str) -> str:
        if policy == "D01":
            return self.v3.primary_direction
        return {"T1": self.en.t1, "T2": self.en.t2, "T2_MA": self.en.t2ma}[policy]


def enrich_symbol(frames: dict, campaign: SymbolCampaign,
                  eval_start: datetime, eval_end: datetime) -> tuple[EnrichedObservation, ...]:
    """Walk the identical frozen observation grid and attach policy states.

    Fails loudly if the grid diverges from the frozen V0.3 campaign, if any
    policy direction disagrees with its structural authority (every decided
    policy direction must equal the H4/D01 direction), or if T1 diverges from
    the D08 motivating evidence it formalizes.
    """
    m15: tuple[MarketBar, ...] = frames["M15"]
    h1, h4, d1 = frames["H1"], frames["H4"], frames["D1"]
    bundle = build_series(frames)
    close_h1 = _cut_series(h1, 60)
    close_h4 = _cut_series(h4, 240)
    close_d1 = _cut_series(d1, 1440)
    m15_opens = [b.timestamp for b in m15]
    m15_events = structure_shift_events(m15, "M15")
    events_by_index: dict[int, list] = {}
    for event in m15_events:
        events_by_index.setdefault(event.index, []).append(event)

    warm_start = eval_start + timedelta(days=OBS_WARMUP_DAYS)
    last_index = len(m15) - OUTCOME_HORIZON_BARS - CONFIRMATION_WINDOW_BARS - 1

    out: list[EnrichedObservation] = []
    c_h1 = c_h4 = c_d1 = -1
    v3_iter = iter(campaign.observations)

    for i, bar in enumerate(m15):
        ts = bar.timestamp
        if ts.minute != OBS_MINUTE or ts < warm_start or ts >= eval_end or i > last_index:
            continue
        t = ts + timedelta(minutes=15)
        while c_h1 + 1 < len(h1) and close_h1[c_h1 + 1] <= t:
            c_h1 += 1
        while c_h4 + 1 < len(h4) and close_h4[c_h4 + 1] <= t:
            c_h4 += 1
        while c_d1 + 1 < len(d1) and close_d1[c_d1 + 1] <= t:
            c_d1 += 1
        if c_h1 < 0 or c_h4 < 0 or c_d1 < 0:
            continue

        v3 = next(v3_iter)
        if v3.feed_index != i:
            raise AssertionError(
                f"grid divergence from frozen V0.3 campaign at feed index {i} != {v3.feed_index}")

        price = bar.close
        ctx, extras = context_at(bundle, c_d1, c_h4, c_h1, price)
        if ctx.h4.value != v3.directions["D01"]:
            raise AssertionError(f"H4 direction mismatch vs frozen D01 at index {i}")
        phase = phase_of(ctx.h4, ctx.h1_flow)
        t1 = t1_direction(ctx.h4, ctx.h1_flow, extras["pd_state"])
        if t1.value != v3.directions["D08"]:
            raise AssertionError(f"T1 != D08 motivating evidence at index {i}")
        t2 = t2_direction(phase)
        t2ma = t2ma_direction(t2, ctx.ma)

        realign = {}
        if phase in ("BULL_PULLBACK", "BEAR_PULLBACK"):
            macro = Direction.BULL if phase == "BULL_PULLBACK" else Direction.BEAR
            realign = _measure_realignment(
                bundle=bundle, h1=h1, close_h1=close_h1, close_h4=close_h4,
                m15=m15, m15_opens=m15_opens, events_by_index=events_by_index,
                c_h1=c_h1, macro=macro)

        out.append(EnrichedObservation(
            feed_index=i, observed_at=t, symbol=campaign.symbol,
            h4=ctx.h4.value, h1_flow=ctx.h1_flow.value, phase=phase,
            pd_state=extras["pd_state"], location=location_label(extras["pd_state"]),
            ma=ctx.ma.value, t1=t1.value, t2=t2.value, t2ma=t2ma.value,
            session=session_label(t), **realign))

    if next(v3_iter, None) is not None:
        raise AssertionError("frozen V0.3 campaign has observations the grid walk missed")
    return tuple(out)


def _measure_realignment(*, bundle, h1, close_h1, close_h4, m15, m15_opens,
                         events_by_index, c_h1: int, macro: Direction) -> dict:
    """Diagnostic pullback realignment: first later completed H1 bar whose
    internal flow equals the macro direction, within the preregistered
    measurement window (not a trading wait rule)."""
    limit = min(c_h1 + REALIGN_WINDOW_H1_BARS, len(h1) - 1)
    realign_j = None
    for j in range(c_h1 + 1, limit + 1):
        if bundle.flow_h1.at(j) == macro:
            realign_j = j
            break
    censored = limit < c_h1 + REALIGN_WINDOW_H1_BARS and realign_j is None
    base = {"realign_measured": True, "realigned": realign_j is not None,
            "realign_censored": censored}
    if realign_j is None:
        return base

    t_r = close_h1[realign_j]
    c4 = bisect_right(close_h4, t_r) - 1
    price_r = h1[realign_j].close
    loc = "UNAVAILABLE"
    if c4 >= 0:
        range_high = bundle.s_h4.range_high[c4]
        range_low = bundle.s_h4.range_low[c4]
        if range_high is not None and range_low is not None and range_high > range_low:
            mid = (range_high + range_low) / 2.0
            loc = "DISCOUNT" if price_r < mid else ("PREMIUM" if price_r > mid else "MIDRANGE")

    i_r = bisect_left(m15_opens, t_r)
    conf_available = None
    capability = None
    if i_r < len(m15):
        conf_available = False
        for k in range(i_r, min(i_r + CONFIRMATION_WINDOW_BARS, len(m15))):
            for event in events_by_index.get(k, ()):
                if event.primitive in (ConfirmationPrimitive.MSS, ConfirmationPrimitive.BOS) \
                        and event.direction == macro:
                    conf_available = True
                    break
            if conf_available:
                break
        if i_r + OUTCOME_HORIZON_BARS < len(m15):
            entry_price = m15[i_r].close
            window = m15[max(0, i_r - STOP_LOOKBACK_BARS + 1): i_r + 1]
            stop = min(b.low for b in window) if macro == Direction.BULL \
                else max(b.high for b in window)
            if abs(entry_price - stop) > 0:
                capability = compute_excursions(
                    m15[i_r + 1: i_r + 1 + OUTCOME_HORIZON_BARS],
                    EntryGeometry(macro, entry_price, stop), OUTCOME_HORIZON_BARS).mfe_r

    base.update({"realign_delay_h1": realign_j - c_h1,
                 "realign_direction": macro.value,
                 "realign_location": loc,
                 "realign_confirmation_available": conf_available,
                 "realign_capability_mfe_r": capability})
    return base


def join_symbol(campaign: SymbolCampaign,
                enriched: Sequence[EnrichedObservation]) -> tuple[JoinedObs, ...]:
    if len(campaign.observations) != len(enriched):
        raise AssertionError("join cardinality mismatch")
    joined = []
    for v3, en in zip(campaign.observations, enriched):
        if v3.feed_index != en.feed_index:
            raise AssertionError("join feed-index mismatch")
        for decided in (en.t1, en.t2, en.t2ma):
            if decided != "NEUTRAL" and decided != v3.primary_direction:
                raise AssertionError(
                    "policy direction must equal the H4/D01 direction when decided")
        joined.append(JoinedObs(v3=v3, en=en))
    return tuple(joined)


# ---------------------------------------------------------------------------
# Per-policy metrics (downstream outcomes read from the frozen V0.3 fields)
# ---------------------------------------------------------------------------

def _quantile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def policy_metrics(joined: Sequence[JoinedObs], policy: str) -> dict:
    directional = [j for j in joined if j.direction(policy) != "NEUTRAL"]
    decided_vals = [_decided_mfe(j.v3, j.direction(policy)) for j in directional]
    opposite_vals = [_opposite_mfe(j.v3, j.direction(policy)) for j in directional]
    cap_decided = reach_share(decided_vals)
    cap_opposite = reach_share(opposite_vals)
    separation = None
    if cap_decided is not None and cap_opposite is not None:
        separation = round((cap_decided - cap_opposite) * 100.0, 2)

    loc_avail = [j for j in directional
                 if j.v3.location_state in ("ALIGNED", "MISMATCH_RECORDED")]
    loc_aligned = [j for j in directional if j.v3.location_state == "ALIGNED"]
    loc_mismatch = [j for j in directional if j.v3.location_state == "MISMATCH_RECORDED"]
    conf_avail = [j for j in loc_aligned if j.v3.confirmation_primitive is not None]
    confirmed = [j for j in loc_aligned if j.v3.confirmation_alignment == "ALIGNED"]
    unconfirmed = [j for j in loc_aligned if j.v3.confirmation_primitive is None]
    entered = [j for j in directional if j.v3.entered]

    n = len(entered)
    counts = {k: sum(1 for j in entered if j.v3.fixed_reached.get(k, False))
              for k in FIXED_R_TARGETS}
    fixed_reach = {f"{k}R": (counts[k] / n if n else None) for k in FIXED_R_TARGETS}
    survival = {}
    for a, b in ((1, 2), (2, 3), (3, 4), (4, 5)):
        survival[f"P{b}_GIVEN_{a}"] = (counts[b] / counts[a]) if counts[a] else None
    mfe = sorted(j.v3.entry_mfe_r for j in entered if j.v3.entry_mfe_r is not None)
    mae = sorted(j.v3.entry_mae_r for j in entered if j.v3.entry_mae_r is not None)
    naturals = sorted(v for j in entered for v in j.v3.natural_targets.values())

    def cap(rows):
        return reach_share([_decided_mfe(j.v3, j.direction(policy)) for j in rows])

    opp_aligned = cap(loc_aligned)
    conf_cap = cap(confirmed)
    conf_uplift = None
    if opp_aligned is not None and conf_cap is not None:
        conf_uplift = round((conf_cap - opp_aligned) * 100.0, 2)

    return {
        "policy": policy,
        "definition": POLICY_DEFINITIONS[policy],
        "capability_basis": CAPABILITY_BASIS,
        "directional_n": len(directional),
        "bull_n": sum(1 for j in directional if j.direction(policy) == "BULL"),
        "bear_n": sum(1 for j in directional if j.direction(policy) == "BEAR"),
        "capability_decided_direction": cap_decided,
        "capability_opposite_direction": cap_opposite,
        "separation_pp": separation,
        "funnel": {
            "DIRECTIONAL": len(directional),
            "LOCATION_AVAILABLE": len(loc_avail),
            "LOCATION_ALIGNED": len(loc_aligned),
            "LOCATION_MISMATCH_RECORDED": len(loc_mismatch),
            "CONFIRMATION_AVAILABLE": len(conf_avail),
            "ENTERED": n,
            **{f"R{k}": counts[k] for k in FIXED_R_TARGETS},
        },
        "location": {
            "aligned_n": len(loc_aligned), "aligned_capability": opp_aligned,
            "mismatch_n": len(loc_mismatch), "mismatch_capability": cap(loc_mismatch),
            "directional_capability": cap_decided,
        },
        "confirmation": {
            "opportunity_basis": CAPABILITY_BASIS,
            "opportunity_capability_location_aligned": opp_aligned,
            "confirmed_n": len(confirmed),
            "confirmed_subset_capability_same_basis": conf_cap,
            "unconfirmed_n": len(unconfirmed),
            "unconfirmed_capability_same_basis": cap(unconfirmed),
            "uplift_pp_same_basis": conf_uplift,
            "entry_conditioned_basis": ENTRY_CONDITIONED_BASIS,
            "entry_conditioned_capability": reach_share(
                [j.v3.entry_mfe_r for j in entered]),
            "entry_conditioned_uplift_vs_opportunity": None,
            "entry_conditioned_uplift_reason": INCOMPARABLE_REASON,
        },
        "entered_n": n,
        "fixed_reach": fixed_reach,
        "continuation_survival": survival,
        "mfe_r_median": median(mfe) if mfe else None,
        "mae_r_median": median(mae) if mae else None,
        "natural_target_n": len(naturals),
        "natural_target_r": {
            "P25": _quantile(naturals, 0.25), "P50": _quantile(naturals, 0.50),
            "P75": _quantile(naturals, 0.75), "P90": _quantile(naturals, 0.90),
        },
    }


def capability_deltas(policy_m: dict, d01_m: dict) -> dict:
    out = {}
    for k in FIXED_R_TARGETS:
        a, b = policy_m["fixed_reach"][f"{k}R"], d01_m["fixed_reach"][f"{k}R"]
        out[f"DELTA_{k}R_vs_D01_pp"] = round((a - b) * 100.0, 2) \
            if a is not None and b is not None else None
    a = policy_m["natural_target_r"]["P50"]
    b = d01_m["natural_target_r"]["P50"]
    out["DELTA_NATURAL_TARGET_MEDIAN_R"] = round(a - b, 4) \
        if a is not None and b is not None else None
    return out


def attrition(policy_m: dict, d01_m: dict) -> float | None:
    if not d01_m["directional_n"]:
        return None
    return round((1.0 - policy_m["directional_n"] / d01_m["directional_n"]) * 100.0, 2)


def target_distribution_shift(deltas: dict) -> str:
    d2 = deltas.get("DELTA_2R_vs_D01_pp")
    if d2 is None:
        return "NOT_MEASURABLE"
    if d2 > TARGET_SHIFT_BAND_PP:
        return "IMPROVED"
    if d2 < -TARGET_SHIFT_BAND_PP:
        return "DEGRADED"
    return "UNCHANGED"


# ---------------------------------------------------------------------------
# Acceptance interpretation (mission section 12; preregistered)
# ---------------------------------------------------------------------------

def interpret_policy(policy_m: dict, d01_m: dict) -> dict:
    deltas = capability_deltas(policy_m, d01_m)
    result = {"policy": policy_m["policy"], "deltas": deltas,
              "attrition_vs_d01_pct": attrition(policy_m, d01_m),
              "separation_pp": policy_m["separation_pp"],
              "research_diagnostic_threshold_pp": RESEARCH_DIAGNOSTIC_THRESHOLD_PP,
              "threshold_label": "RESEARCH_DIAGNOSTIC_THRESHOLD (not edge/profit/"
                                 "production/deployment)"}
    if policy_m["directional_n"] < MIN_POLICY_DIRECTIONAL_N \
            or policy_m["separation_pp"] is None:
        result.update(result_type="D", interpretation="INSUFFICIENT_EVIDENCE",
                      reason=f"directional n {policy_m['directional_n']} < "
                             f"{MIN_POLICY_DIRECTIONAL_N} or separation unmeasurable")
        return result
    sep_improves = policy_m["separation_pp"] >= RESEARCH_DIAGNOSTIC_THRESHOLD_PP
    if not sep_improves:
        result.update(result_type="C", interpretation="TRIGGER_HYPOTHESIS_NOT_SUPPORTED",
                      reason=f"separation {policy_m['separation_pp']}pp < "
                             f"{RESEARCH_DIAGNOSTIC_THRESHOLD_PP}pp diagnostic threshold")
        return result
    if policy_m["entered_n"] < MIN_POLICY_ENTERED_N:
        result.update(result_type="D", interpretation="INSUFFICIENT_EVIDENCE",
                      reason=f"separation improved but entered n {policy_m['entered_n']} "
                             f"< {MIN_POLICY_ENTERED_N}: target capability not comparably "
                             "measurable")
        return result
    d2, d3 = deltas["DELTA_2R_vs_D01_pp"], deltas["DELTA_3R_vs_D01_pp"]
    material = d2 is not None and d3 is not None and \
        d2 >= MATERIAL_DELTA_2R_PP and d3 >= MATERIAL_DELTA_3R_PP
    if material:
        result.update(result_type="A", interpretation="TRIGGER_HYPOTHESIS_SUPPORTED_ON_DEV",
                      reason=f"separation {policy_m['separation_pp']}pp >= threshold AND "
                             f"material target improvement (d2R {d2}pp, d3R {d3}pp)")
    else:
        result.update(result_type="B",
                      interpretation="TRIGGER_DIRECTION_IMPROVED_TARGET_NOT_IMPROVED",
                      reason=f"separation {policy_m['separation_pp']}pp >= threshold but "
                             f"target capability not materially improved "
                             f"(d2R {d2}pp < {MATERIAL_DELTA_2R_PP}pp "
                             f"or d3R {d3}pp < {MATERIAL_DELTA_3R_PP}pp)")
    return result


_RESULT_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}


def overall_interpretation(verdicts: dict) -> dict:
    """Preregistered mapping from per-policy result types to the mission verdict."""
    ordered = sorted(verdicts.values(),
                     key=lambda v: (_RESULT_RANK[v["result_type"]],
                                    -(v["separation_pp"] or -999.0)))
    best = ordered[0]
    next_map = {"A": "NONE", "B": "TARGET", "C": "TRIGGER", "D": "TRIGGER"}
    diagnosis_map = {
        "A": "TRIGGER_HYPOTHESIS_SUPPORTED_ON_DEV",
        "B": "TRIGGER_DIRECTION_IMPROVED_TARGET_NOT_IMPROVED",
        "C": "TRIGGER_FUNNEL_WEAKNESS_PERSISTS",
        "D": "INSUFFICIENT_EVIDENCE",
    }
    return {
        "best_policy": best["policy"],
        "best_result_type": best["result_type"],
        "primary_diagnosis": diagnosis_map[best["result_type"]],
        "next_funnel_to_test": next_map[best["result_type"]],
        "direction_improvement_propagates_downstream":
            "YES" if best["result_type"] == "A"
            else ("NO" if best["result_type"] == "B" else "NOT_APPLICABLE"),
        "note": "winner NOT chosen on separation alone; attrition and target-"
                "capability propagation are part of the verdict (mission sections 10-12)",
    }


# ---------------------------------------------------------------------------
# Pullback realignment + phase aggregation
# ---------------------------------------------------------------------------

def phase_distribution(enriched: Sequence[EnrichedObservation]) -> dict:
    counts = {p: 0 for p in PHASES}
    cross: dict[str, dict[str, int]] = {p: {loc: 0 for loc in LOCATION_LABELS}
                                        for p in PHASES}
    for en in enriched:
        counts[en.phase] += 1
        cross[en.phase][en.location] += 1
    return {"counts": counts, "phase_x_location": cross,
            "invariant": "location never erases phase; e.g. BULL_PULLBACK rows "
                         "exist at PREMIUM and DISCOUNT alike"}


def pullback_realignment_report(enriched: Sequence[EnrichedObservation]) -> dict:
    pullbacks = [en for en in enriched if en.realign_measured]
    realigned = [en for en in pullbacks if en.realigned]
    delays = sorted(en.realign_delay_h1 for en in realigned)
    locations: dict[str, int] = {}
    conf_yes = conf_no = 0
    caps = []
    for en in realigned:
        locations[en.realign_location or "UNAVAILABLE"] = \
            locations.get(en.realign_location or "UNAVAILABLE", 0) + 1
        if en.realign_confirmation_available is True:
            conf_yes += 1
        elif en.realign_confirmation_available is False:
            conf_no += 1
        if en.realign_capability_mfe_r is not None:
            caps.append(en.realign_capability_mfe_r)
    caps.sort()
    return {
        "PULLBACK_N": len(pullbacks),
        "PULLBACK_REALIGN_N": len(realigned),
        "PULLBACK_REALIGN_RATE": (len(realigned) / len(pullbacks)) if pullbacks else None,
        "censored_n": sum(1 for en in pullbacks if en.realign_censored),
        "measurement_window_h1_bars": REALIGN_WINDOW_H1_BARS,
        "window_note": "diagnostic measurement horizon only — NOT a maximum-wait "
                       "trading rule",
        "REALIGN_DELAY_H1_BARS": {
            "min": delays[0] if delays else None,
            "P25": _quantile([float(d) for d in delays], 0.25),
            "P50": _quantile([float(d) for d in delays], 0.50),
            "P75": _quantile([float(d) for d in delays], 0.75),
            "P90": _quantile([float(d) for d in delays], 0.90),
            "max": delays[-1] if delays else None,
        },
        "location_at_realignment": locations,
        "confirmation_available_after_realignment": {
            "yes": conf_yes, "no": conf_no,
            "unmeasured": len(realigned) - conf_yes - conf_no},
        "capability_after_realignment": {
            "measured_n": len(caps),
            "reach_2r_share": reach_share(caps),
            "mfe_r_median": _quantile(caps, 0.5),
        },
        "diagnostic_only": True,
    }


# ---------------------------------------------------------------------------
# Stability + ablation verdicts (preregistered rules)
# ---------------------------------------------------------------------------

def location_stability(per_policy: dict) -> dict:
    rows = {}
    evaluable, holds = [], []
    for policy, m in per_policy.items():
        loc = m["location"]
        rows[policy] = loc
        if loc["aligned_n"] >= STABILITY_MIN_CELL_N and \
                loc["mismatch_n"] >= STABILITY_MIN_CELL_N and \
                loc["aligned_capability"] is not None and \
                loc["mismatch_capability"] is not None:
            evaluable.append(policy)
            holds.append(loc["aligned_capability"] >= loc["mismatch_capability"])
    verdict = "INSUFFICIENT_EVIDENCE" if not evaluable else \
        ("YES" if all(holds) else "NO")
    return {"per_policy": rows, "evaluable_policies": evaluable,
            "cell_floor_n": STABILITY_MIN_CELL_N,
            "LOCATION_VALUE_STABLE": verdict,
            "note": "no location optimization performed (mission section 15)"}


def confirmation_stability(per_policy: dict) -> dict:
    rows, states = {}, {}
    for policy, m in per_policy.items():
        conf = m["confirmation"]
        rows[policy] = conf
        if conf["confirmed_n"] >= STABILITY_MIN_CELL_N and \
                conf["uplift_pp_same_basis"] is not None:
            if conf["uplift_pp_same_basis"] >= RESEARCH_DIAGNOSTIC_THRESHOLD_PP:
                states[policy] = "IMPROVES"
            elif conf["uplift_pp_same_basis"] <= CONFIRMATION_DEGRADE_PP:
                states[policy] = "DEGRADES"
            else:
                states[policy] = "UNCLEAR"
        else:
            states[policy] = "INSUFFICIENT_EVIDENCE"
    measurable = [s for s in states.values() if s != "INSUFFICIENT_EVIDENCE"]
    verdict = "INSUFFICIENT_EVIDENCE" if not measurable else \
        ("YES" if all(s == "IMPROVES" for s in measurable) else "NO")
    return {"per_policy_uplift": rows, "per_policy_state": states,
            "CONFIRMATION_VALUE_STABLE": verdict,
            "comparability": "uplift computed only inside the shared opportunity "
                             "basis; entry-conditioned capability reported separately "
                             "with uplift=null (" + INCOMPARABLE_REASON + ")"}


def ma_ablation(t2_m: dict, t2ma_m: dict) -> dict:
    sep_delta = None
    if t2_m["separation_pp"] is not None and t2ma_m["separation_pp"] is not None:
        sep_delta = round(t2ma_m["separation_pp"] - t2_m["separation_pp"], 2)
    cap_delta = None
    a, b = t2ma_m["fixed_reach"]["2R"], t2_m["fixed_reach"]["2R"]
    if a is not None and b is not None:
        cap_delta = round((a - b) * 100.0, 2)
    if t2ma_m["directional_n"] < MIN_POLICY_DIRECTIONAL_N or sep_delta is None:
        verdict = "INSUFFICIENT_EVIDENCE"
    elif sep_delta >= MA_ABLATION_SEPARATION_PP and (cap_delta is None or cap_delta >= 0):
        verdict = "YES"
    else:
        verdict = "NO"
    return {
        "t2": {k: t2_m[k] for k in ("directional_n", "separation_pp", "entered_n",
                                    "fixed_reach")},
        "t2_plus_ma": {k: t2ma_m[k] for k in ("directional_n", "separation_pp",
                                              "entered_n", "fixed_reach")},
        "population_change_n": t2ma_m["directional_n"] - t2_m["directional_n"],
        "separation_change_pp": sep_delta,
        "capability_2r_change_pp": cap_delta,
        "rule": f"YES iff separation gain >= +{MA_ABLATION_SEPARATION_PP}pp AND 2R "
                "capability not reduced, at preregistered population floors; "
                "MA50/200 parameters NOT tuned",
        "MA_ADDS_VALUE_BEYOND_STRUCTURE": verdict,
    }


def session_stratification(joined: Sequence[JoinedObs]) -> dict:
    sessions = ("ASIAN", "LONDON", "LONDON_NEWYORK_OVERLAP", "NEW_YORK", "OFF_SESSION")
    out: dict[str, dict] = {}
    for policy in ("D01", "T1", "T2"):
        out[policy] = {}
        for sess in sessions:
            rows = [j for j in joined
                    if j.en.session == sess and j.direction(policy) != "NEUTRAL"]
            decided = reach_share([_decided_mfe(j.v3, j.direction(policy)) for j in rows])
            opposite = reach_share([_opposite_mfe(j.v3, j.direction(policy)) for j in rows])
            out[policy][sess] = {
                "directional_n": len(rows),
                "capability_decided": decided,
                "separation_pp": round((decided - opposite) * 100.0, 2)
                if decided is not None and opposite is not None else None,
            }
    out["note"] = ("diagnostic stratification only — sessions are NEVER trigger "
                   "requirements; definitions are the frozen V0.3 preregistered "
                   "UTC windows (overlap 13:00-16:00)")
    return out
