"""Universal Funnel V0.6 — NATURAL TARGET + RUNNER POLICY RESEARCH.

Parent: authoritative V0.5 (65ba0ed…, TARGET_MODEL_DIAGNOSTICS_V1 @
0.3.0-research). Question: does a CAUSAL natural-target (+ runner) exit
policy improve structural target delivery relative to the frozen fixed-R
ladder — on the SAME entries, without touching anything upstream?

FROZEN: direction, location, confirmation, entry, SL, sessions, dataset,
fill semantics, causal target definitions (V0.5 contracts reused verbatim).

Policy candidates (preregistered BEFORE results; diagnostic only):
  C0_kR  : control — exit 100% at the frozen fixed kR level (k = 1..5; the
           frozen funnel carries the whole ladder, so every level is a
           control variant; no k is "selected");
  C1     : exit 100% at FIRST_VALID_CAUSAL_OBJECTIVE;
  C2     : partial f at FIRST + runner to SECOND_VALID_CAUSAL_OBJECTIVE;
  C3     : partial f at FIRST + runner to FURTHEST_VALID_CAUSAL_OBJECTIVE;
  C4     : partial f at FIRST + runner to the frozen fixed-R ceiling (5R).
  f grid : 25/75, 50/50, 75/25 — sensitivity only, never a selection.
  Runner families: R0 keeps the original frozen SL; R1 moves the runner
  stop to entry AFTER the first objective is realized (NEW EXIT HYPOTHESIS,
  never mixed with R0).

Structural accounting only (no friction, no horizon-forced exits): an
outcome that does not deterministically resolve inside the frozen 96-bar
window is NULL (UNRESOLVED/RUNNER_OPEN), never imputed. Realized economics
require EXIT_CONTRACT_COMPLETE and FRICTION_AUTHORITY_COMPLETE — both fail
closed in this repository (no committed frozen TP for C0 as a single exit,
no horizon-exit price authority, no pinned FX friction scenario values).

Stop/target collisions keep the frozen fail-closed rule: stop FIRST.
The runner starts ONLY after the first objective is actually reached —
no hypothetical runner credit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Sequence

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.universal.direction import Direction
from ag_edgelab.universal.fx_dev_campaign import OUTCOME_HORIZON_BARS
from ag_edgelab.universal.targets import EntryGeometry, FIXED_R_TARGETS
from ag_edgelab.universal import target_v0_5 as tv5

EXPERIMENT_ID = "TARGET_POLICY_NATURAL_RUNNER_V1"
EXPERIMENT_VERSION = "0.1.0-research"
AUTHORITATIVE_V0_5_SHA = "65ba0ed763048307a499734ebe5b9a22e3f3103c"
AUTHORITATIVE_V0_5_TREE = "9fc02cb22d6dcdd25b24cfce3bf398ea047f4ddd"
SUPERSEDED_V0_5_SHA = "e5b38b875c1167ee19b24e246ecd5b879869ff16"

FRACTIONS = (25, 50, 75)              # partial % at OBJ1 (grid, not a search)
RUNNER_FAMILIES = ("R0", "R1")        # R0 original SL; R1 break-even (separate)
FIXED_CEILING_R = 5                   # frozen deep ladder level (never tuned)
MIN_PAIR_N = 100                      # paired comparisons need >= 100 pairs
MATERIAL_PP = 5.0                     # cross-population material shift (pp)
RUNNER_CONTINUATION = tv5.RUNNER_CONTINUATION   # 0.35 (frozen from V0.5)

CONTROL_IDS = tuple(f"C0_{k}R" for k in FIXED_R_TARGETS)
FOCAL_CONTROLS = ("C0_2R", "C0_5R")   # preregistered focal controls for pairing


def _policy_ids() -> tuple[str, ...]:
    ids = list(CONTROL_IDS) + ["C1"]
    for fam in ("C2", "C3", "C4"):
        for f in FRACTIONS:
            for rf in RUNNER_FAMILIES:
                ids.append(f"{fam}_F{f}_{rf}")
    return tuple(ids)


POLICY_IDS = _policy_ids()

POLICY_CONTRACTS = {
    "controls": {f"C0_{k}R": f"exit 100% at the frozen fixed {k}R level; "
                             f"stop first; unresolved window => NULL"
                 for k in FIXED_R_TARGETS},
    "C1": "exit 100% at FIRST_VALID_CAUSAL_OBJECTIVE (V0.5 primary rule); "
          "NOT_APPLICABLE when no causal objective exists at entry",
    "C2": "partial f% at FIRST objective + runner (100-f)% to SECOND "
          "objective; NOT_APPLICABLE when no second objective exists",
    "C3": "partial f% at FIRST objective + runner to FURTHEST objective; "
          "NOT_APPLICABLE when the ladder has a single objective",
    "C4": "partial f% at FIRST objective + runner to the frozen fixed 5R "
          "ceiling; NOT_APPLICABLE when FIRST objective R >= 5",
    "fractions": {f: f"{f}% exit at first objective, {100 - f}% runner"
                  for f in FRACTIONS},
    "fraction_rule": "3-point preregistered sensitivity grid; no percentage "
                     "is promoted from DEV",
    "runner_rule": "runner begins ONLY after the first objective is actually "
                   "reached (no hypothetical credit); same-bar first+runner "
                   "objective touch pays the runner objective (monotone path "
                   "through the nearer level under the frozen stop-first scan)",
    "R0": "runner retains the original frozen SL (full -1R on the runner "
          "fraction if stopped after the partial)",
    "R1": "NEW EXIT HYPOTHESIS: runner stop moves to entry (break-even) "
          "from the bar AFTER first-objective realization; BE counted FIRST "
          "within a bar (fail-closed); no spread adjustment (no authority)",
    "unresolved": "no stop/target resolution inside the frozen 96-bar window "
                  "=> structural outcome NULL (UNRESOLVED/RUNNER_OPEN), never "
                  "imputed, never a loss",
}

TARGET_POLICY_REGISTRY_SHA256 = sha256_json({
    "experiment_id": EXPERIMENT_ID, "version": EXPERIMENT_VERSION,
    "authoritative_v0_5": AUTHORITATIVE_V0_5_SHA,
    "policies": POLICY_CONTRACTS, "policy_ids": POLICY_IDS,
    "focal_controls": FOCAL_CONTROLS,
    "thresholds": {"min_pair_n": MIN_PAIR_N, "material_pp": MATERIAL_PP,
                   "runner_continuation": RUNNER_CONTINUATION,
                   "fixed_ceiling_r": FIXED_CEILING_R},
    "frozen_upstream": ["direction", "location", "confirmation", "entry",
                        "SL", "sessions", "dataset", "fill semantics",
                        "V0.5 causal target contracts"],
})


# ---------------------------------------------------------------------------
# Per-entry policy inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Objective:
    family: str
    price: float
    r: float
    reached: bool
    t_bar: int | None                 # 1-based forward offset when reached


@dataclass(frozen=True)
class PolicyEntry:
    base: tv5.EntryRecord
    stop_bar: int | None              # first forward bar hitting the frozen SL
    first: Objective | None
    second: Objective | None
    furthest: Objective | None
    fixed5: Objective                 # frozen 5R ceiling (always defined)
    be_runner: dict                   # runner key -> ("TARGET"|"BE"|"OPEN", t|None)
    runner_mfe_r: float | None        # after first-objective bar, R0 window
    runner_mae_r: float | None

    @property
    def entry_id(self) -> str:
        return f"{self.base.symbol}:{self.base.obs_feed_index}"


def _stop_bar(forward: Sequence[MarketBar], geometry: EntryGeometry) -> int | None:
    for offset, bar in enumerate(forward[:OUTCOME_HORIZON_BARS]):
        hit = bar.low <= geometry.stop if geometry.direction == Direction.BULL \
            else bar.high >= geometry.stop
        if hit:
            return offset + 1
    return None


def _be_runner(forward: Sequence[MarketBar], geometry: EntryGeometry,
               t1: int, target: Objective) -> tuple[str, int | None]:
    """R1 runner outcome: BE stop (at entry) counted FIRST from the bar AFTER
    the first-objective bar; same-bar first+target touch pays the target."""
    if target.reached and target.t_bar is not None and target.t_bar <= t1:
        return ("TARGET", t1)
    bull = geometry.direction == Direction.BULL
    for offset in range(t1, min(len(forward), OUTCOME_HORIZON_BARS)):
        bar = forward[offset]          # offset is 0-based; bar t = offset+1 > t1
        hit_be = bar.low <= geometry.entry if bull else bar.high >= geometry.entry
        hit_target = bar.high >= target.price if bull else bar.low <= target.price
        if hit_be:                     # fail-closed: BE counted FIRST
            return ("BE", offset + 1)
        if hit_target:
            return ("TARGET", offset + 1)
    return ("OPEN", None)


def _runner_excursions(forward: Sequence[MarketBar], geometry: EntryGeometry,
                       t1: int, stop_bar: int | None) -> tuple[float, float]:
    """Runner-window MFE/MAE in R (vs entry), bars strictly after the first
    objective bar, strictly before the stop bar (frozen stop-first rule)."""
    risk = geometry.risk
    bull = geometry.direction == Direction.BULL
    end = min(len(forward), OUTCOME_HORIZON_BARS,
              (stop_bar - 1) if stop_bar is not None else OUTCOME_HORIZON_BARS)
    mfe = 0.0
    mae = 0.0
    for offset in range(t1, end):
        bar = forward[offset]
        if bull:
            mfe = max(mfe, (bar.high - geometry.entry) / risk)
            mae = max(mae, (geometry.entry - bar.low) / risk)
        else:
            mfe = max(mfe, (geometry.entry - bar.low) / risk)
            mae = max(mae, (bar.high - geometry.entry) / risk)
    return mfe, mae


def _objective_from(rec: tv5.EntryRecord, family: str | None) -> Objective | None:
    if family is None:
        return None
    t = rec.targets[family]
    return Objective(family=family, price=t.price, r=t.target_r,
                     reached=t.reached_before_sl, t_bar=t.time_to_target_bars)


def _ladder_family_at(rec: tv5.EntryRecord, r_value: float | None) -> str | None:
    if r_value is None:
        return None
    for family, _price, r, _reached in rec.ladder:
        if r == r_value:
            return family
    return None


def build_policy_entries(frames: dict,
                         records: Sequence[tv5.EntryRecord]) -> tuple[PolicyEntry, ...]:
    m15 = frames["M15"]
    out: list[PolicyEntry] = []
    for rec in records:
        geometry = EntryGeometry(Direction(rec.direction), rec.entry_price,
                                 rec.stop_price)
        forward = m15[rec.entry_index + 1: rec.entry_index + 1 + OUTCOME_HORIZON_BARS]
        stop_bar = _stop_bar(forward, geometry)
        first = _objective_from(rec, rec.nearest_family)
        second = _objective_from(rec, _ladder_family_at(rec, rec.second_target_r))
        furthest = _objective_from(rec, rec.furthest_family) \
            if rec.furthest_target_r is not None else None
        bull = geometry.direction == Direction.BULL
        price5 = geometry.entry + (5 * geometry.risk if bull else -5 * geometry.risk)
        fixed5 = Objective(family="FIXED_5R_CEILING", price=price5, r=5.0,
                           reached=bool(rec.fixed_reached.get(5, False)),
                           t_bar=rec.time_to_r[5])
        # sanity: a farther objective can never be reached without the nearer
        for obj in (second, furthest):
            if obj is not None and obj.reached and first is not None:
                assert first.reached, "causal ordering violated"
        be = {}
        runner_mfe = runner_mae = None
        if first is not None and first.reached:
            t1 = first.t_bar
            for key, target in (("SECOND", second), ("FURTHEST", furthest),
                                ("FIXED5", fixed5)):
                be[key] = _be_runner(forward, geometry, t1, target) \
                    if target is not None else None
            runner_mfe, runner_mae = _runner_excursions(forward, geometry, t1,
                                                        stop_bar)
        else:
            be = {"SECOND": None, "FURTHEST": None, "FIXED5": None}
        out.append(PolicyEntry(base=rec, stop_bar=stop_bar, first=first,
                               second=second, furthest=furthest, fixed5=fixed5,
                               be_runner=be, runner_mfe_r=runner_mfe,
                               runner_mae_r=runner_mae))
    return tuple(out)


# ---------------------------------------------------------------------------
# Policy evaluation (pure, deterministic)
# ---------------------------------------------------------------------------

RESOLVED = "RESOLVED"


def _runner_target(pe: PolicyEntry, family: str) -> Objective | None:
    if family == "C2":
        return pe.second
    if family == "C3":
        # runner must be strictly beyond the first objective
        if pe.furthest is not None and pe.first is not None \
                and pe.furthest.r > pe.first.r:
            return pe.furthest
        return None
    if family == "C4":
        if pe.first is not None and pe.first.r < FIXED_CEILING_R:
            return pe.fixed5
        return None
    raise ValueError(family)


_BE_KEY = {"C2": "SECOND", "C3": "FURTHEST", "C4": "FIXED5"}


def policy_outcome(pe: PolicyEntry, policy_id: str) -> dict:
    """-> {status, structural_r | None}. NULL is never a loss."""
    if policy_id.startswith("C0_"):
        k = int(policy_id[3])
        if pe.base.fixed_reached.get(k, False):
            return {"status": "FULL_TARGET", "structural_r": float(k)}
        if pe.stop_bar is not None:
            return {"status": "STOPPED", "structural_r": -1.0}
        return {"status": "UNRESOLVED_WINDOW", "structural_r": None}

    if pe.first is None:
        return {"status": "NOT_APPLICABLE_NO_OBJECTIVE", "structural_r": None}

    if policy_id == "C1":
        if pe.first.reached:
            return {"status": "FULL_TARGET", "structural_r": pe.first.r}
        if pe.stop_bar is not None:
            return {"status": "STOPPED", "structural_r": -1.0}
        return {"status": "UNRESOLVED_WINDOW", "structural_r": None}

    fam, frac_token, runner_family = policy_id.split("_")
    f = int(frac_token[1:]) / 100.0
    target = _runner_target(pe, fam)
    if target is None:
        return {"status": "NOT_APPLICABLE_NO_RUNNER_OBJECTIVE",
                "structural_r": None}
    if not pe.first.reached:
        if pe.stop_bar is not None:
            return {"status": "STOPPED_BEFORE_FIRST", "structural_r": -1.0}
        return {"status": "UNRESOLVED_WINDOW", "structural_r": None}

    locked = f * pe.first.r
    if runner_family == "R0":
        if target.reached:
            return {"status": "PARTIAL_PLUS_RUNNER_TARGET",
                    "structural_r": locked + (1 - f) * target.r}
        if pe.stop_bar is not None:
            return {"status": "PARTIAL_PLUS_RUNNER_STOPPED",
                    "structural_r": locked - (1 - f) * 1.0}
        return {"status": "PARTIAL_RUNNER_OPEN", "structural_r": None}
    # R1 break-even hypothesis (separate family, never mixed with R0)
    be = pe.be_runner[_BE_KEY[fam]]
    if be is None:
        return {"status": "NOT_APPLICABLE_NO_RUNNER_OBJECTIVE",
                "structural_r": None}
    kind, _t = be
    if kind == "TARGET":
        return {"status": "PARTIAL_PLUS_RUNNER_TARGET",
                "structural_r": locked + (1 - f) * target.r}
    if kind == "BE":
        return {"status": "PARTIAL_PLUS_RUNNER_BREAKEVEN",
                "structural_r": locked}
    return {"status": "PARTIAL_RUNNER_OPEN", "structural_r": None}


def evaluate_all(entries: Sequence[PolicyEntry]) -> dict:
    """entry_id -> {policy_id -> outcome}."""
    return {pe.entry_id: {pid: policy_outcome(pe, pid) for pid in POLICY_IDS}
            for pe in entries}


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------

def _mean(vals):
    vals = list(vals)
    return sum(vals) / len(vals) if vals else None


def policy_summary(entries: Sequence[PolicyEntry], outcomes: dict) -> dict:
    out = {}
    for pid in POLICY_IDS:
        rows = [outcomes[pe.entry_id][pid] for pe in entries]
        statuses = {}
        for row in rows:
            statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        resolved = [row["structural_r"] for row in rows
                    if row["structural_r"] is not None]
        applicable = [row for row in rows
                      if not row["status"].startswith("NOT_APPLICABLE")]
        out[pid] = {
            "entry_n": len(rows),
            "applicable_n": len(applicable),
            "resolved_n": len(resolved),
            "resolved_pct_of_applicable":
                (len(resolved) / len(applicable)) if applicable else None,
            "status_counts": statuses,
            "mean_structural_r": _mean(resolved),
            "median_structural_r": tv5._quantile(sorted(resolved), 0.5)
            if resolved else None,
            "structural_r_quantiles": tv5.quantile_block(resolved),
        }
    return out


def paired_delta(entries: Sequence[PolicyEntry], outcomes: dict,
                 policy_a: str, policy_b: str) -> dict:
    """a minus b on the SAME entries, both resolved (pathwise isolation)."""
    deltas = []
    for pe in entries:
        ra = outcomes[pe.entry_id][policy_a]["structural_r"]
        rb = outcomes[pe.entry_id][policy_b]["structural_r"]
        if ra is not None and rb is not None:
            deltas.append(ra - rb)
    return {"policy": policy_a, "control": policy_b,
            "pair_n": len(deltas),
            "mean_delta_r": _mean(deltas),
            "median_delta_r": tv5._quantile(sorted(deltas), 0.5)
            if deltas else None,
            "pct_pairs_positive": (sum(1 for d in deltas if d > 0) / len(deltas))
            if deltas else None,
            "meets_pair_floor": len(deltas) >= MIN_PAIR_N}


def pathwise_comparison(entries: Sequence[PolicyEntry], outcomes: dict) -> dict:
    diagnostics = [pid for pid in POLICY_IDS if not pid.startswith("C0_")]
    rows = []
    for pid in diagnostics:
        for control in FOCAL_CONTROLS:
            rows.append(paired_delta(entries, outcomes, pid, control))
        if pid != "C1":
            rows.append(paired_delta(entries, outcomes, pid, "C1"))
    return {"same_entry_pathwise": True,
            "focal_controls": FOCAL_CONTROLS,
            "pairs": rows}


def runner_report(entries: Sequence[PolicyEntry]) -> dict:
    with_first = [pe for pe in entries if pe.first is not None]
    first_hit = [pe for pe in with_first if pe.first.reached]
    with_second = [pe for pe in first_hit if pe.second is not None]
    second_hit = [pe for pe in with_second if pe.second.reached]
    third_candidates = [pe for pe in second_hit
                        if pe.base.third_target_r is not None]
    third_hit = [pe for pe in third_candidates if pe.base.third_reached]
    ext_candidates = [pe for pe in first_hit if pe.furthest is not None
                      and pe.furthest.r > pe.first.r]
    ext_hit = [pe for pe in ext_candidates if pe.furthest.reached]
    stopped_after = [pe for pe in first_hit
                     if pe.stop_bar is not None and pe.stop_bar > pe.first.t_bar]
    t_first_second = [float(pe.second.t_bar - pe.first.t_bar)
                      for pe in second_hit]
    t_second_ext = [float(pe.furthest.t_bar - pe.second.t_bar)
                    for pe in second_hit
                    if pe.furthest is not None and pe.furthest.reached
                    and pe.furthest.r > pe.second.r]
    pct = lambda a, b: (len(a) / len(b)) if b else None
    return {
        "runner_rule": "runner begins ONLY after the first objective is "
                       "actually reached; no hypothetical credit",
        "first_reached_n": len(first_hit),
        "P_SECOND_GIVEN_FIRST": pct(second_hit, with_second),
        "P_THIRD_GIVEN_SECOND": pct(third_hit, third_candidates),
        "runner_mfe_r_quantiles": tv5.quantile_block(
            [pe.runner_mfe_r for pe in first_hit if pe.runner_mfe_r is not None]),
        "runner_mae_r_quantiles": tv5.quantile_block(
            [pe.runner_mae_r for pe in first_hit if pe.runner_mae_r is not None]),
        "runner_stop_rate": pct(stopped_after, first_hit),
        "runner_second_objective_rate": pct(second_hit, with_second),
        "runner_extended_objective_rate": pct(ext_hit, ext_candidates),
        "time_first_to_second_bars": tv5.quantile_block(t_first_second),
        "time_second_to_extended_bars": tv5.quantile_block(t_second_ext),
        "be_runner_outcomes": {
            key: {kind: sum(1 for pe in first_hit
                            if pe.be_runner.get(key) is not None
                            and pe.be_runner[key][0] == kind)
                  for kind in ("TARGET", "BE", "OPEN")}
            for key in ("SECOND", "FURTHEST", "FIXED5")},
    }


# ---------------------------------------------------------------------------
# Stratifications
# ---------------------------------------------------------------------------

REPRESENTATIVES = ("C1", "C2_F50_R0", "C3_F50_R0", "C4_F50_R0")


def risk_quartiles(entries: Sequence[PolicyEntry]) -> dict:
    """entry_id -> quartile label (within-symbol frozen-population quartiles)."""
    by_symbol: dict[str, list[PolicyEntry]] = {}
    for pe in entries:
        by_symbol.setdefault(pe.base.symbol, []).append(pe)
    label = {}
    for symbol, rows in by_symbol.items():
        risks = sorted(pe.base.risk_distance for pe in rows)
        cuts = [tv5._quantile(risks, q) for q in (0.25, 0.5, 0.75)]
        for pe in rows:
            r = pe.base.risk_distance
            label[pe.entry_id] = "Q1" if r <= cuts[0] else \
                "Q2" if r <= cuts[1] else "Q3" if r <= cuts[2] else "Q4"
    return label


def quartile_analysis(entries: Sequence[PolicyEntry], outcomes: dict) -> dict:
    labels = risk_quartiles(entries)
    out = {"rule": "within-symbol risk-distance quartiles of the frozen entry "
                   "population; SL unchanged",
           "representatives": REPRESENTATIVES,
           "quartiles": {}}
    pooled_flags = []
    for q in ("Q1", "Q2", "Q3", "Q4"):
        sub = [pe for pe in entries if labels[pe.entry_id] == q]
        out["quartiles"][q] = {
            "entry_n": len(sub),
            "first_objective_reach_pct": _mean(
                [1.0 if pe.first is not None and pe.first.reached else 0.0
                 for pe in sub if pe.first is not None]),
            "paired": {pid: {c: paired_delta(sub, outcomes, pid, c)
                             for c in FOCAL_CONTROLS}
                       for pid in REPRESENTATIVES}}
    # preregistered flag: advantage exists pooled but is confined to Q1/Q2
    for pid in REPRESENTATIVES:
        for c in FOCAL_CONTROLS:
            pooled = paired_delta(entries, outcomes, pid, c)
            if not pooled["meets_pair_floor"] or pooled["mean_delta_r"] is None \
                    or pooled["mean_delta_r"] <= 0:
                continue
            qd = {q: out["quartiles"][q]["paired"][pid][c] for q in
                  ("Q1", "Q2", "Q3", "Q4")}
            confined = all(
                qd[q]["mean_delta_r"] is not None and qd[q]["mean_delta_r"] <= 0
                for q in ("Q3", "Q4")) and any(
                qd[q]["mean_delta_r"] is not None and qd[q]["mean_delta_r"] > 0
                for q in ("Q1", "Q2"))
            pooled_flags.append({"policy": pid, "control": c,
                                 "advantage_confined_to_q1_q2": confined})
    depends = bool(pooled_flags) and all(f["advantage_confined_to_q1_q2"]
                                         for f in pooled_flags)
    out["positive_pooled_comparisons"] = pooled_flags
    out["TARGET_POLICY_DEPENDS_ON_SL_GEOMETRY"] = \
        "YES" if depends else ("NO" if pooled_flags else "NO_POOLED_ADVANTAGE")
    return out


def session_stratification(entries: Sequence[PolicyEntry], outcomes: dict) -> dict:
    sessions = ("ASIAN", "LONDON", "LONDON_NEWYORK_OVERLAP", "NEW_YORK",
                "OFF_SESSION")
    out = {"rule": "frozen V0.3 session labels; diagnostic strata only",
           "crypto_note": "SESSION_GATING = NOT_APPLICABLE for future crypto "
                          "reuse; engine stays asset-neutral",
           "sessions": {}}
    for s in sessions:
        sub = [pe for pe in entries if pe.base.session == s]
        out["sessions"][s] = {
            "entry_n": len(sub),
            "first_objective_reach_pct": _mean(
                [1.0 if pe.first is not None and pe.first.reached else 0.0
                 for pe in sub if pe.first is not None]),
            "paired_c1_vs_controls": {c: paired_delta(sub, outcomes, "C1", c)
                                      for c in FOCAL_CONTROLS}}
    return out


# ---------------------------------------------------------------------------
# Preregistered decision rules (PHASE 14)
# ---------------------------------------------------------------------------

def _beats(entries, outcomes, pid, control) -> bool:
    d = paired_delta(entries, outcomes, pid, control)
    return bool(d["meets_pair_floor"] and d["mean_delta_r"] is not None
                and d["mean_delta_r"] > 0)


def decision(entries: Sequence[PolicyEntry], outcomes: dict,
             runner_rep: dict, quartiles: dict,
             other_population_p21: float | None,
             own_p21: float | None) -> dict:
    """Preregistered A..G evaluation for ONE population (no pooling)."""
    c1_beats_all = all(_beats(entries, outcomes, "C1", c0) for c0 in CONTROL_IDS)
    runner_family_wins = {}
    for fam in ("C2", "C3", "C4"):
        ok = True
        for f in FRACTIONS:
            pid = f"{fam}_F{f}_R0"
            if not all(_beats(entries, outcomes, pid, c0) for c0 in CONTROL_IDS) \
                    or not _beats(entries, outcomes, pid, "C1"):
                ok = False
                break
        runner_family_wins[fam] = ok
    any_runner_wins = any(runner_family_wins.values())
    p21 = runner_rep["P_SECOND_GIVEN_FIRST"]
    runner_never_beats_c1 = all(
        not _beats(entries, outcomes, f"{fam}_F{f}_R0", "C1")
        for fam in ("C2", "C3", "C4") for f in FRACTIONS)
    floors_met = len(entries) >= tv5.MIN_STRATUM_N

    cases = {
        "A_FIXED_TARGET_MODEL_INFERIOR": c1_beats_all or any_runner_wins,
        "B_NATURAL_SINGLE_TARGET_SUPPORTED_FOR_FURTHER_TESTING": c1_beats_all,
        "C_NATURAL_TARGET_PLUS_RUNNER_SUPPORTED_FOR_FURTHER_TESTING":
            any_runner_wins,
        "D_RUNNER_CONTINUATION_TOO_WEAK":
            (p21 is not None and p21 < RUNNER_CONTINUATION)
            or runner_never_beats_c1,
        "E_TARGET_POLICY_DEPENDS_ON_SL_GEOMETRY":
            quartiles["TARGET_POLICY_DEPENDS_ON_SL_GEOMETRY"] == "YES",
        "F_T1_DIRECTION_FILTER_HARMS_RUNNER_CONTINUATION":
            (own_p21 is not None and other_population_p21 is not None
             and (other_population_p21 - own_p21) * 100.0 >= MATERIAL_PP),
        "G_INSUFFICIENT_EVIDENCE": not floors_met,
    }
    precedence = ["C_NATURAL_TARGET_PLUS_RUNNER_SUPPORTED_FOR_FURTHER_TESTING",
                  "B_NATURAL_SINGLE_TARGET_SUPPORTED_FOR_FURTHER_TESTING",
                  "D_RUNNER_CONTINUATION_TOO_WEAK",
                  "F_T1_DIRECTION_FILTER_HARMS_RUNNER_CONTINUATION",
                  "E_TARGET_POLICY_DEPENDS_ON_SL_GEOMETRY"]
    if not floors_met:
        primary = "G_INSUFFICIENT_EVIDENCE"
    else:
        primary = next((name for name in precedence if cases[name]),
                       "G_INSUFFICIENT_EVIDENCE")
    secondary = [name for name, hit in cases.items()
                 if hit and name != primary and name != "G_INSUFFICIENT_EVIDENCE"]
    return {"cases": cases, "runner_family_wins": runner_family_wins,
            "precedence": precedence,
            "PRIMARY_DIAGNOSIS": primary, "SECONDARY_DIAGNOSES": secondary,
            "no_candidate_edge_verified": True,
            "no_candidate_promoted_to_production": True}


# ---------------------------------------------------------------------------
# Ledgers (JSONL rows)
# ---------------------------------------------------------------------------

def entry_policy_rows(entries: Sequence[PolicyEntry], outcomes: dict) -> list[dict]:
    rows = []
    for pe in entries:
        rows.append({
            "entry_id": pe.entry_id, "symbol": pe.base.symbol,
            "direction": pe.base.direction, "session": pe.base.session,
            "entry_time": pe.base.entry_time.isoformat(),
            "is_t1": pe.base.is_t1,
            "risk_distance_price": pe.base.risk_distance,
            "stop_bar": pe.stop_bar,
            "first_objective": None if pe.first is None else
            {"family": pe.first.family, "R": pe.first.r,
             "reached": pe.first.reached, "t_bar": pe.first.t_bar},
            "policies": outcomes[pe.entry_id],
        })
    return rows


def objective_sequence_rows(entries: Sequence[PolicyEntry]) -> list[dict]:
    rows = []
    for pe in entries:
        rec = pe.base
        seq = []
        for family, price, r, reached in rec.ladder:
            t = rec.targets[family]
            seq.append({
                "family": family, "price": price, "R": r,
                "created_time": t.created_time.isoformat(),
                "reached": reached,
                "reached_time": (rec.entry_time
                                 + timedelta(minutes=15 * t.time_to_target_bars)
                                 ).isoformat() if t.time_to_target_bars else None,
                "SL_before_target": t.invalidated_by_stop,
                "MFE_before_target_R": t.mfe_before_target_r,
                "MAE_before_target_R": t.mae_before_target_r,
            })
        rows.append({"entry_id": pe.entry_id, "symbol": rec.symbol,
                     "direction": rec.direction,
                     "entry_time": rec.entry_time.isoformat(),
                     "is_t1": rec.is_t1,
                     "objective_sequence": seq})
    return rows
