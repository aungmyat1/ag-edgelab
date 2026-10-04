"""Universal diagnostic campaign — ONE shared core for FX and CRYPTO.

Walks a DEVELOPMENT M5 series on a deterministic grid and, per candidate:

  FUNNEL 1  MTF structural direction (D1/H4/H1) + preregistered location
  FUNNEL 2  lower-timeframe confirmation (M15/M5 MSS/BOS/sweep), with
            COUNTER_DIRECTION candidates recorded, never silently dropped
  FUNNEL 3  MFE/MAE, fixed 1R..5R reachability, natural-target families

Market-specific behavior enters ONLY through the MarketProfile: FX attaches
session context; crypto records time-of-day as diagnostic metadata that
never gates anything. Research/diagnostic only — no execution.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.derive import TIMEFRAME_MINUTES, aggregate_bars
from ag_edgelab.universal.confirmation import (ConfirmationEvent, ConfirmationPrimitive,
                                               SetupAlignment, classify_alignment,
                                               structure_shift_events)
from ag_edgelab.universal.direction import (Direction, DirectionMode, combined_direction,
                                            ma_direction, mtf_direction, structural_direction)
from ag_edgelab.universal.hypotheses import PA_HYPOTHESES
from ag_edgelab.universal.location import (LocationFamily, evidence_at_price, liquidity_levels,
                                           premium_discount, premium_discount_supports,
                                           structural_levels, supply_demand_zones)
from ag_edgelab.universal.matrix import (CAPABILITY_BASIS, MatrixCandidate, MatrixStage,
                                         StageDiagnostic, build_matrix)
from ag_edgelab.universal.profile import MarketProfile, MarketType, SessionBehavior
from ag_edgelab.universal.report import (ConfirmationSection, EconomicsSection,
                                         FunnelDiagnosticReportV3, SESSION_CONTEXT_NOT_APPLICABLE,
                                         TargetSection, TriggerSection)
from ag_edgelab.universal.root_cause import RootCauseInputs, RootCauseResult, diagnose
from ag_edgelab.universal.sessions import (FxSession, active_sessions, compute_session_snapshots,
                                           crypto_time_metadata)
from ag_edgelab.universal.targets import (EntryGeometry, FIXED_R_TARGETS, NaturalTargetFamily,
                                          compute_excursions, fvg_target, next_swing_target,
                                          opposing_zone_target, pdh_pdl_target)

Z = timezone.utc

# Preregistered campaign constants (frozen; never searched).
CANDIDATE_STRIDE_M5 = 48          # one observation every 4 hours
WARMUP_M5 = 288 * 7               # one week of M5 before the first candidate
CONFIRMATION_WINDOW_M5 = 48       # confirmation must appear within 4 hours
OUTCOME_HORIZON_M5 = 288          # 24 hours of outcome measurement
STOP_LOOKBACK_M5 = 12             # diagnostic stop = extreme of last 12 M5 bars
DESIRED_TARGET_R = 3.0            # frozen fixed target examined by root cause
SWING_ORDER = 2
LOCATION_FAMILIES = (LocationFamily.STRUCTURAL_LEVEL, LocationFamily.SUPPLY_DEMAND,
                     LocationFamily.LIQUIDITY_LEVEL)


@dataclass(frozen=True)
class CampaignCandidate:
    candidate_id: str
    observed_at: datetime
    direction: Direction
    directions_by_tf: dict
    ma_direction: Direction
    directions_by_mode: dict           # DirectionMode -> Direction
    location_pass: bool
    location_families_hit: tuple[str, ...]
    premium_discount_state: str | None
    hypothesis_pass: dict              # PA id -> bool
    alignment: SetupAlignment          # of the found confirmation event
    confirmation: ConfirmationEvent | None
    entered: bool
    entry_geometry: EntryGeometry | None
    diagnostic_mfe_r: float | None
    diagnostic_mae_r: float | None
    entry_mfe_r: float | None
    entry_mae_r: float | None
    fixed_reached: dict                # k -> bool (entry geometry)
    natural_targets: dict              # family -> target_r
    time_metadata: dict                # diagnostic only; never gates


@dataclass(frozen=True)
class CampaignResult:
    profile: MarketProfile
    strategy_id: str
    candidates: tuple[CampaignCandidate, ...]
    matrix: tuple[StageDiagnostic, ...]
    root_cause: RootCauseResult
    report: FunnelDiagnosticReportV3
    direction_population_n: int
    confirmed_population_n: int
    ma_mode_directions: dict            # mode -> {BULL/BEAR/NEUTRAL: n}


def _cut_index(frame: tuple[MarketBar, ...], minutes: int, close_time: datetime) -> int:
    """Index of the last frame bar fully CLOSED at or before close_time; -1 if none."""
    idx = -1
    for i, bar in enumerate(frame):
        if bar.timestamp + timedelta(minutes=minutes) <= close_time:
            idx = i
        else:
            break
    return idx


def run_campaign(
    m5_bars: tuple[MarketBar, ...],
    profile: MarketProfile,
    strategy_id: str,
    dataset_role: str = "DEVELOPMENT",
) -> CampaignResult:
    if dataset_role != "DEVELOPMENT":
        raise ValueError("the universal diagnostic campaign accepts DEVELOPMENT data only")
    is_crypto = profile.market_type == MarketType.CRYPTO
    is_fx = profile.market_type == MarketType.FX

    frames: dict[str, tuple[MarketBar, ...]] = {}
    for tf in ("M15", "H1", "H4", "D1"):
        frames[tf], _ = aggregate_bars(m5_bars, "M5", tf)

    m5_events = structure_shift_events(m5_bars, "M5", SWING_ORDER)
    events_by_index: dict[int, list[ConfirmationEvent]] = {}
    for event in m5_events:
        events_by_index.setdefault(event.index, []).append(event)

    candidates: list[CampaignCandidate] = []
    last_index = len(m5_bars) - OUTCOME_HORIZON_M5 - CONFIRMATION_WINDOW_M5 - 1
    ma_mode_counts = {mode.value: {d.value: 0 for d in Direction} for mode in DirectionMode}

    for i in range(WARMUP_M5, max(WARMUP_M5, last_index), CANDIDATE_STRIDE_M5):
        bar = m5_bars[i]
        close_time = bar.timestamp + timedelta(minutes=5)
        price = bar.close

        # ----- FUNNEL 1: direction (D1/H4/H1 structure + MA50/200 on H1) ----
        cut: dict[str, int] = {tf: _cut_index(frames[tf], TIMEFRAME_MINUTES[tf], close_time)
                               for tf in frames}
        tf_states = {}
        for tf in ("D1", "H4", "H1"):
            if cut[tf] >= 0:
                tf_states[tf] = structural_direction(frames[tf], tf, SWING_ORDER, asof_index=cut[tf])
        if len(tf_states) < 3:
            continue
        values = {s.direction for s in tf_states.values()}
        if Direction.BULL in values and Direction.BEAR in values:
            composite = Direction.NEUTRAL
        elif Direction.BULL in values:
            composite = Direction.BULL
        elif Direction.BEAR in values:
            composite = Direction.BEAR
        else:
            composite = Direction.NEUTRAL

        h1_closes = [b.close for b in frames["H1"][: cut["H1"] + 1]]
        ma_state = ma_direction(h1_closes)
        directions_by_mode = {
            mode.value: combined_direction(composite, ma_state.direction, mode).value
            for mode in DirectionMode
        }
        for mode, value in directions_by_mode.items():
            ma_mode_counts[mode][value] += 1

        # ----- FUNNEL 1: location (H4 evidence at current price) ------------
        h4_idx = cut["H4"]
        h4 = frames["H4"]
        struct_ev = structural_levels(h4, "H4", SWING_ORDER, asof_index=h4_idx)
        sd_ev = supply_demand_zones(h4, "H4", asof_index=h4_idx)
        liq_ev = liquidity_levels(h4, "H4", SWING_ORDER, asof_index=h4_idx)
        pd_state = premium_discount(h4, "H4", price, SWING_ORDER, asof_index=h4_idx)
        all_ev = struct_ev + sd_ev + liq_ev
        hits = evidence_at_price(all_ev, price, composite, families=LOCATION_FAMILIES)
        pd_hit = premium_discount_supports(pd_state, composite)
        families_hit = tuple(sorted({e.family.value for e in hits}
                                    | ({"PREMIUM_DISCOUNT"} if pd_hit else set())))
        location_pass = bool(families_hit)

        # ----- preregistered hypothesis evaluation (PA01..PA07 only) --------
        family_pass = {
            LocationFamily.STRUCTURAL_LEVEL: any(e.family == LocationFamily.STRUCTURAL_LEVEL for e in hits),
            LocationFamily.SUPPLY_DEMAND: any(e.family == LocationFamily.SUPPLY_DEMAND for e in hits),
            LocationFamily.LIQUIDITY_LEVEL: any(e.family == LocationFamily.LIQUIDITY_LEVEL for e in hits),
            LocationFamily.PREMIUM_DISCOUNT: pd_hit,
        }
        hypothesis_pass: dict[str, bool] = {}
        for hyp in PA_HYPOTHESES:
            direction_value = Direction(directions_by_mode[hyp.direction_mode.value])
            ok = direction_value != Direction.NEUTRAL
            if ok and hyp.location_families:
                ok = any(family_pass.get(f, False) for f in hyp.location_families)
            if ok and hyp.requires_liquidity_context:
                ok = family_pass[LocationFamily.LIQUIDITY_LEVEL]
            hypothesis_pass[hyp.hypothesis_id] = ok

        # ----- FUNNEL 2: confirmation (M5 MSS/BOS within the window) --------
        confirmation: ConfirmationEvent | None = None
        alignment = SetupAlignment.NEUTRAL
        for j in range(i + 1, min(i + 1 + CONFIRMATION_WINDOW_M5, len(m5_bars))):
            for event in events_by_index.get(j, ()):
                if event.primitive in (ConfirmationPrimitive.MSS, ConfirmationPrimitive.BOS):
                    confirmation = event
                    alignment = classify_alignment(composite, event.direction)
                    break
            if confirmation is not None:
                break
        confirmed_aligned = confirmation is not None and alignment == SetupAlignment.ALIGNED

        # ----- diagnostic geometry (shared capability basis) -----------------
        lo = min(b.low for b in m5_bars[max(0, i - STOP_LOOKBACK_M5 + 1): i + 1])
        hi = max(b.high for b in m5_bars[max(0, i - STOP_LOOKBACK_M5 + 1): i + 1])
        diag_dir = composite if composite != Direction.NEUTRAL else Direction.BULL
        diag_stop = lo if diag_dir == Direction.BULL else hi
        diag_mfe = diag_mae = None
        if abs(price - diag_stop) > 0:
            diag = compute_excursions(m5_bars[i + 1: i + 1 + OUTCOME_HORIZON_M5],
                                      EntryGeometry(diag_dir, price, diag_stop), OUTCOME_HORIZON_M5)
            diag_mfe, diag_mae = diag.mfe_r, diag.mae_r

        # ----- FUNNEL 3: entry geometry + outcome for confirmed candidates ---
        entered = False
        geometry: EntryGeometry | None = None
        entry_mfe = entry_mae = None
        fixed_reached: dict[int, bool] = {k: False for k in FIXED_R_TARGETS}
        natural: dict[str, float] = {}
        if confirmed_aligned:
            e_idx = confirmation.index
            entry_price = m5_bars[e_idx].close
            window = m5_bars[max(0, e_idx - STOP_LOOKBACK_M5 + 1): e_idx + 1]
            stop = min(b.low for b in window) if composite == Direction.BULL \
                else max(b.high for b in window)
            if abs(entry_price - stop) > 0:
                geometry = EntryGeometry(composite, entry_price, stop)
                entered = True
                outcome = compute_excursions(m5_bars[e_idx + 1: e_idx + 1 + OUTCOME_HORIZON_M5],
                                             geometry, OUTCOME_HORIZON_M5)
                entry_mfe, entry_mae = outcome.mfe_r, outcome.mae_r
                fixed_reached = outcome.fixed_target_reached
                # Natural-target families (diagnostic only; target never replaced).
                swing = next_swing_target(h4, geometry, SWING_ORDER, asof_index=h4_idx)
                if swing:
                    natural[NaturalTargetFamily.NEXT_SWING.value] = swing.target_r
                opposing = opposing_zone_target(sd_ev, geometry, LocationFamily.SUPPLY_DEMAND,
                                                NaturalTargetFamily.OPPOSING_SUPPLY_DEMAND)
                if opposing:
                    natural[NaturalTargetFamily.OPPOSING_SUPPLY_DEMAND.value] = opposing.target_r
                pool = opposing_zone_target(liq_ev, geometry, LocationFamily.LIQUIDITY_LEVEL,
                                            NaturalTargetFamily.LIQUIDITY_POOL)
                if pool:
                    natural[NaturalTargetFamily.LIQUIDITY_POOL.value] = pool.target_r
                gap = fvg_target(h4, geometry, asof_index=h4_idx)
                if gap:
                    natural[NaturalTargetFamily.FVG_IMBALANCE.value] = gap.target_r
                # PDH/PDL: FX natural family; for crypto it fails closed unless
                # a future strategy preregisters it (it has not).
                pd_target = pdh_pdl_target(frames["D1"][: cut["D1"] + 1], geometry,
                                           is_crypto=is_crypto, preregistered_for_crypto=False)
                if pd_target:
                    natural[NaturalTargetFamily.PDH_PDL.value] = pd_target.target_r

        # ----- market-specific metadata (never a gate for crypto) -----------
        if is_crypto:
            time_metadata = crypto_time_metadata(close_time)
        elif is_fx and profile.session_behavior != SessionBehavior.NOT_APPLICABLE:
            time_metadata = {"active_sessions": [s.value for s in active_sessions(close_time)]}
        else:
            time_metadata = {}

        candidates.append(CampaignCandidate(
            candidate_id=f"{strategy_id}-{i:06d}",
            observed_at=close_time,
            direction=composite,
            directions_by_tf={tf: s.direction.value for tf, s in tf_states.items()},
            ma_direction=ma_state.direction,
            directions_by_mode=directions_by_mode,
            location_pass=location_pass,
            location_families_hit=families_hit,
            premium_discount_state=None if pd_state is None else pd_state.state,
            hypothesis_pass=hypothesis_pass,
            alignment=alignment,
            confirmation=confirmation,
            entered=entered,
            entry_geometry=geometry,
            diagnostic_mfe_r=diag_mfe,
            diagnostic_mae_r=diag_mae,
            entry_mfe_r=entry_mfe,
            entry_mae_r=entry_mae,
            fixed_reached=fixed_reached,
            natural_targets=natural,
            time_metadata=time_metadata,
        ))

    # ------------------------- diagnostic matrix ----------------------------
    matrix_candidates = []
    for c in candidates:
        direction_ok = c.direction != Direction.NEUTRAL
        stage_pass = {
            MatrixStage.TRIGGER_DIRECTION: direction_ok,
            MatrixStage.TRIGGER_LOCATION: direction_ok and c.location_pass,
            MatrixStage.CONFIRMATION_SETUP: direction_ok and c.location_pass
                and c.alignment == SetupAlignment.ALIGNED,
            MatrixStage.ENTRY: direction_ok and c.location_pass and c.entered,
        }
        for k in FIXED_R_TARGETS:
            stage_pass[MatrixStage(f"R{k}")] = stage_pass[MatrixStage.ENTRY] and c.fixed_reached.get(k, False)
        matrix_candidates.append(MatrixCandidate(
            candidate_id=c.candidate_id, stage_pass=stage_pass,
            mfe_r=c.diagnostic_mfe_r, capability_basis=CAPABILITY_BASIS,
            attributes={"alignment": c.alignment.value}))
    matrix = build_matrix(matrix_candidates)

    # ------------------------- root cause -----------------------------------
    by_stage = {row.stage: row for row in matrix}
    trigger_row = by_stage[MatrixStage.TRIGGER_LOCATION]
    confirm_row = by_stage[MatrixStage.CONFIRMATION_SETUP]
    entered_candidates = [c for c in candidates if c.entered]
    desired_k = int(DESIRED_TARGET_R)
    desired_reach = (sum(1 for c in entered_candidates if c.fixed_reached.get(desired_k, False))
                     / len(entered_candidates)) if entered_candidates else None
    natural_values = [v for c in entered_candidates for v in c.natural_targets.values()]
    inputs = RootCauseInputs(
        trigger_n=trigger_row.pass_n,
        trigger_capability=trigger_row.capability_after_pass,
        confirmed_n=confirm_row.pass_n,
        confirmed_capability=confirm_row.capability_after_pass,
        desired_target_r=DESIRED_TARGET_R,
        desired_target_reach=desired_reach,
        natural_target_median_r=median(natural_values) if natural_values else None,
        capability_basis=CAPABILITY_BASIS,
        comparable=trigger_row.comparable,
    )
    root_cause = diagnose(inputs, CAPABILITY_BASIS)

    # ------------------------- session context ------------------------------
    session_context: dict[str, Any] | str
    if is_crypto:
        session_context = SESSION_CONTEXT_NOT_APPLICABLE
    else:
        snapshots = {s.value: compute_session_snapshots(m5_bars, s) for s in FxSession}
        session_context = {
            "behavior": profile.session_behavior.value,
            "definitions_source": "sessions.SESSION_DEFINITIONS (PREREGISTERED_UPA_V0_3)",
            "session_days": {name: len(rows) for name, rows in snapshots.items()},
            "asian_sweep_days": sum(1 for s in snapshots["ASIAN"]
                                    if s.swept_previous_high or s.swept_previous_low),
            "london_ny_overlap_utc": [13, 16],
        }

    # ------------------------- report ---------------------------------------
    aligned_n = sum(1 for c in candidates if c.alignment == SetupAlignment.ALIGNED)
    counter_n = sum(1 for c in candidates if c.alignment == SetupAlignment.COUNTER_DIRECTION)
    report = FunnelDiagnosticReportV3(
        strategy_id=strategy_id,
        market_type=profile.market_type,
        session_behavior=profile.session_behavior,
        trigger=TriggerSection(
            direction={
                "population_n": len(candidates),
                "non_neutral_n": by_stage[MatrixStage.TRIGGER_DIRECTION].pass_n,
                "by_mode": ma_mode_counts,
            },
            location={
                "pass_n": trigger_row.pass_n,
                "families": [f.value for f in LOCATION_FAMILIES] + ["PREMIUM_DISCOUNT"],
                "capability_after_pass": trigger_row.capability_after_pass,
                "uplift_pp": trigger_row.uplift_pp,
            }),
        confirmation=ConfirmationSection(
            setup={
                "primitives": ["MSS", "BOS", "LIQUIDITY_SWEEP"],
                "aligned_n": aligned_n,
                "counter_direction_n": counter_n,
                "counter_recorded_not_rejected": True,
            },
            entry={
                "entered_n": len(entered_candidates),
                "capability_after_pass": confirm_row.capability_after_pass,
                "uplift_pp": confirm_row.uplift_pp,
            }),
        target=TargetSection(
            capability={
                f"reach_{k}R": (sum(1 for c in entered_candidates if c.fixed_reached.get(k, False))
                                / len(entered_candidates)) if entered_candidates else None
                for k in FIXED_R_TARGETS
            },
            natural_target={
                "median_target_r": median(natural_values) if natural_values else None,
                "families_observed": sorted({f for c in entered_candidates
                                             for f in c.natural_targets}),
                "fixed_target_preserved": True,
            }),
        economics=EconomicsSection(
            authoritative=False,
            note="DEVELOPMENT diagnostic on non-authoritative data; realized economics "
                 "are not claimed (no execution, no edge verdict)."),
        session_context=session_context,
        matrix=matrix,
        root_cause=root_cause,
        dataset_role="DEVELOPMENT",
        notes=("Research/diagnostic infrastructure only; no trades created or executed.",),
    )

    return CampaignResult(
        profile=profile, strategy_id=strategy_id, candidates=tuple(candidates),
        matrix=matrix, root_cause=root_cause, report=report,
        direction_population_n=by_stage[MatrixStage.TRIGGER_DIRECTION].pass_n,
        confirmed_population_n=confirm_row.pass_n,
        ma_mode_directions=ma_mode_counts)


# ---------------------------------------------------------------------------
# Deterministic synthetic FX DEVELOPMENT bars (labelled SYNTHETIC; no fetch)
# ---------------------------------------------------------------------------

def make_synthetic_fx_bars(days: int = 40, seed: int = 20261004,
                           start: datetime | None = None) -> tuple[MarketBar, ...]:
    """Seeded EURUSD-like M5 random walk with drift cycles — NOT market data.

    Exists because the repository holds no FX dataset and the mission forbids
    fetching new external data; every artifact derived from these bars is
    labelled SYNTHETIC / non-authoritative.
    """
    rng = random.Random(seed)
    start = start or datetime(2026, 2, 2, tzinfo=Z)
    bars: list[MarketBar] = []
    price = 1.1000
    ts = start
    for i in range(days * 288):
        cycle = (i // (288 * 5)) % 3
        drift = 0.000006 if cycle == 0 else (-0.000006 if cycle == 1 else 0.0)
        step = rng.gauss(drift, 0.00022)
        o = price
        c = max(0.9, o + step)
        wick = abs(rng.gauss(0, 0.00012))
        bars.append(MarketBar(timestamp=ts, open=round(o, 5),
                              high=round(max(o, c) + wick, 5),
                              low=round(min(o, c) - wick, 5),
                              close=round(c, 5), volume=1.0))
        price = c
        ts += timedelta(minutes=5)
    return tuple(bars)
