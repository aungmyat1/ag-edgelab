"""TARGET_POLICY_C3_V1 — cryptographically bound, deterministic frozen OOS
candidate (V0.6 -> FREEZE; DO NOT OPEN OOS).

Parent authority: V0.6 NATURAL TARGET + RUNNER POLICY RESEARCH complete at
8d132355c0138068fd79a2fb22c9c0f38f295a80 (tree 3d35e5f0cbf3b57089de1d99846ce244e2a7bcf1),
which froze the C3 runner-family contract (family C3, runner family R0,
fraction grid 25/50/75 intact, fraction selection DEFERRED — never selected
in DEV). This module turns that design into ONE exact, auditable candidate:

  * every behaviorally relevant field is pinned in a single canonical
    contract object (UTF-8, sorted keys, compact separators, stable numeric
    representation) whose sha256 is the candidate identity;
  * runner termination is COMPLETE: every admitted trade resolves inside the
    frozen 96-M15-bar research horizon (SL, first objective, runner target,
    runner SL, or horizon forced close at the last completed M15 bar close —
    the repository AG_REFERENCE_REPLAY v1.1.0 DATA_END close fill);
  * the same-bar collision rule is ONE exact policy (STOP FIRST, frozen V0.3
    fail-closed rule), replacing any ambiguous formulation;
  * friction authority is DERIVED from bound evidence, never a caller
    boolean: no pinned authoritative spread/commission/slippage values exist
    for EURUSD/GBPUSD/USDJPY/XAUUSD 2017 in this repository, so
    FRICTION_AUTHORITY_COMPLETE = NO (fail-closed; inventing values is
    forbidden per V0.6 economic_authority.json).

Structural accounting only: gross R identities are exact; NET economics are
NOT claimed (friction authority absent). No OOS, no holdout, no promotion.

Hash paths (mission section 3): PATH A uses this module +
ag_edgelab.data.fingerprint.canonical_json (the repository serialization
authority). PATH B is an INDEPENDENT from-scratch implementation in
ag_edgelab.verification.c3_v1_verifier (the verifier never imports this
module). The freeze requires byte-identical serialization and equal hashes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Sequence

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import canonical_json, sha256_json
from ag_edgelab.universal.fx_dev_campaign import (
    CONFIRMATION_WINDOW_BARS,
    OBS_MINUTE,
    OBS_WARMUP_DAYS,
    OUTCOME_HORIZON_BARS,
    STOP_LOOKBACK_BARS,
)
from ag_edgelab.universal.target_v0_5 import (
    FAMILY_CONTRACTS,
    SESSION_WINDOWS_UTC,
    TARGET_V0_5_REGISTRY_SHA256,
)
from ag_edgelab.universal.target_policy_v0_6 import (
    AUTHORITATIVE_V0_5_SHA,
    TARGET_POLICY_REGISTRY_SHA256,
)
from ag_edgelab.universal.trigger_v0_4 import (
    TRIGGER_POLICY_REGISTRY_SHA256,
    session_label,
)

# ---------------------------------------------------------------------------
# Frozen candidate identity
# ---------------------------------------------------------------------------

CANDIDATE_ID = "TARGET_POLICY_C3_V1"
CANDIDATE_VERSION = "1.0.0-frozen"
PARENT_SHA = "8d132355c0138068fd79a2fb22c9c0f38f295a80"
PARENT_TREE = "3d35e5f0cbf3b57089de1d99846ce244e2a7bcf1"
AUTHORITATIVE_V0_5_SHA256 = AUTHORITATIVE_V0_5_SHA          # 65ba0ed…
V0_6_REGISTRY_SHA256 = TARGET_POLICY_REGISTRY_SHA256        # 05255d26…

# The V0.6 freeze kept the fraction grid intact and explicitly DEFERRED any
# DEV-outcome-based selection ("no percentage is promoted from DEV"). To make
# ONE deterministic candidate the fraction is fixed here by a PREREGISTERED,
# EXOGENOUS convention — the midpoint of the frozen 25/50/75 grid — which is
# independent of every DEV result. Any deviation changes the canonical hash
# and must be rejected by the verifier (adversarial attack A2).
FIRST_OBJECTIVE_PCT = 50
RUNNER_PCT = 50
FROZEN_FRACTION_GRID = (25, 50, 75)
FRACTION_SELECTION_AUTHORITY = (
    "PREREGISTERED_GRID_MIDPOINT_50_50 — the midpoint of the frozen "
    "V0.6 25/50/75 sensitivity grid, fixed by convention BEFORE any OOS "
    "data and WITHOUT reference to DEV outcomes (V0.6 rule: 'no percentage "
    "is promoted from DEV'); the full-grid DEV sensitivity remains "
    "published in the V0.6 artifacts and is restated in the freeze report"
)

RESEARCH_HORIZON_BARS = OUTCOME_HORIZON_BARS                 # 96 (frozen V0.3)
HORIZON_UNIT = "M15_BARS"
HORIZON_ANCHOR = "ENTRY_BAR_CLOSE_TIME"
HORIZON_EXIT_PRICE_AUTHORITY = (
    "M15_CLOSE_OF_LAST_COMPLETED_BAR_AT_OR_BEFORE_HORIZON — the close of "
    "the 96th M15 bar after the entry bar (the last bar of the frozen V0.3 "
    "outcome window); identical to the repository AG_REFERENCE_REPLAY "
    "v1.1.0 DATA_END fill (exit_price = last completed bar close)"
)
FORCED_CLOSE_AUTHORITY = "AG_REFERENCE_REPLAY_V1_1_0_DATA_END_CLOSE_FILL"

RUNNER_STOP_POLICY = "R0_ORIGINAL_FROZEN_SL_RETAINED_BY_RUNNER_LEG"
TERMINATION_POLICY = (
    "COMPLETE_TERMINATION_WITHIN_RESEARCH_HORIZON — every admitted trade "
    "resolves exactly once inside the 96-M15-bar window: "
    "STOP_BEFORE_FIRST (SL touched before the first objective, including "
    "same-bar collision: stop first, whole position -1R) | "
    "FIRST_PLUS_RUNNER_TARGET (first leg at the first objective, runner "
    "leg at the furthest objective) | FIRST_PLUS_RUNNER_STOP (runner leg "
    "stopped at the original frozen SL) | FIRST_PLUS_RUNNER_HORIZON "
    "(runner leg force-closed at the last completed M15 bar close) | "
    "HORIZON_BEFORE_FIRST (neither SL nor first objective touched: whole "
    "position force-closed at the last completed M15 bar close). "
    "UNRESOLVED trades do not exist except explicit "
    "RIGHT_CENSORED_DATA_BOUNDARY rows (persisted, never imputed)"
)

# One exact same-bar collision rule (replaces the ambiguous
# FAIL_CLOSED_OR_CANONICAL_FILL formulation).
SAME_BAR_COLLISION_POLICY = "STOP_FIRST_FROZEN_V0_3_SINGLE_RULE"
COLLISION_AUTHORITY_ID = "V0_3_FAIL_CLOSED_COLLISION_RULE__AG_REFERENCE_REPLAY_V1_1_0"

CENSORING_POLICY = (
    "RIGHT_CENSORED_DATA_BOUNDARY_EXPLICIT — a trade whose frozen 96-bar "
    "outcome window is truncated by the dataset partition end is "
    "RIGHT_CENSORED_DATA_BOUNDARY: excluded from resolution and from "
    "economic metrics under this frozen policy, its entry_id persisted in "
    "the censoring list, and counted in population summaries; never "
    "imputed, never a loss, never silently dropped"
)

DATASET_ROLE = "DEVELOPMENT"
FRICTION_MODEL_ID = "FX_2017_FRICTION_AUTHORITY_ABSENT_FAIL_CLOSED_V1"
SESSION_AUTHORITY_ID = "SESSION_WINDOWS_UTC_V0_3_STRATIFICATION"

TRADED_STATUSES = ("STOPPED_BEFORE_FIRST", "FIRST_PLUS_RUNNER_TARGET",
                   "FIRST_PLUS_RUNNER_STOP", "FIRST_PLUS_RUNNER_HORIZON",
                   "HORIZON_BEFORE_FIRST")
NOT_APPLICABLE_STATUSES = ("NOT_APPLICABLE_NO_OBJECTIVE",
                           "NOT_APPLICABLE_NO_RUNNER_OBJECTIVE")
CENSORED_STATUS = "RIGHT_CENSORED_DATA_BOUNDARY"

# ---------------------------------------------------------------------------
# Canonical sub-policy authority objects (each content-addressed and bound
# into the canonical contract by its sha256)
# ---------------------------------------------------------------------------

TRIGGER_AUTHORITY = {
    "trigger_authority_id": "D01_PRIMARY_FUNNEL_ENTRY_RULE_V0_3",
    "population": "D01 control population (frozen V0.3 FX DEV campaign "
                  "entries; T1/T2 are research treatments, never pooled)",
    "d01_definition": "H4 market structure direction only (confirmed HH/HL "
                      "=> BULL, confirmed LH/LL => BEAR, else NEUTRAL)",
    "chain": (
        "hourly observation grid (top of the UTC hour) after a 21-day "
        "warm-up inside the DEVELOPMENT partition -> D01 direction "
        "non-neutral -> location ALIGNED (frozen V0.3 zone/level set "
        "including premium/discount) -> first ALIGNED MSS/BOS structure "
        "shift within the 16-bar confirmation window -> ENTRY at that "
        "confirmation bar's close -> SL = opposite extreme of the last 12 "
        "M15 bars including the entry bar (non-zero risk required) -> "
        "96-bar outcome window"
    ),
    "constants": {
        "obs_warmup_days": OBS_WARMUP_DAYS,
        "obs_minute": OBS_MINUTE,
        "confirmation_window_bars": CONFIRMATION_WINDOW_BARS,
        "outcome_horizon_bars": OUTCOME_HORIZON_BARS,
        "stop_lookback_bars": STOP_LOOKBACK_BARS,
    },
    "entry_fill": "confirmation-bar close (no spread adjustment: no "
                  "authoritative friction contract exists)",
    "bound_registries": {
        "v0_3_fx_dev_final_report_sha256":
            "5ff4ac36055240e27f605e4a79dd2889075b19a84806e914498ce6dc608e2fbc",
        "v0_4_trigger_policy_registry_sha256": TRIGGER_POLICY_REGISTRY_SHA256,
        "v0_5_target_registry_sha256": TARGET_V0_5_REGISTRY_SHA256,
        "v0_6_target_policy_registry_sha256": V0_6_REGISTRY_SHA256,
    },
}

FIRST_TARGET_POLICY = {
    "first_target_policy_id": "FIRST_VALID_CAUSAL_OBJECTIVE_V0_5",
    "rule": (
        "the first leg exits at the FIRST_VALID_CAUSAL_OBJECTIVE = the "
        "V0.5 PRIMARY_NATURAL_TARGET: the nearest positive directionally-"
        "valid causal objective (smallest positive price distance from "
        "entry == min positive TARGET_R under the frozen SL), selected "
        "strictly from information available at entry time "
        "(TARGET_CREATED_TIME <= ENTRY_TIME)"
    ),
    "selection_reason": "NEAREST_VALID_CAUSAL_OBJECTIVE",
    "authority_registry_sha256": TARGET_V0_5_REGISTRY_SHA256,
    "authority_commit": AUTHORITATIVE_V0_5_SHA256,
}

RUNNER_TARGET_POLICY = {
    "runner_target_policy_id": "FURTHEST_VALID_CAUSAL_OBJECTIVE_C3_V0_6",
    "rule": (
        "the runner leg runs to the FURTHEST_VALID_CAUSAL_OBJECTIVE = the "
        "top of the V0.5 causal objective ladder, and ONLY when it is "
        "strictly beyond the first objective (single-objective ladders are "
        "NOT_APPLICABLE_NO_RUNNER_OBJECTIVE: no trade)"
    ),
    "runner_gating": (
        "the runner exists ONLY after the first objective is actually "
        "reached; same-bar first+runner objective touch pays the runner "
        "objective (monotone path through the nearer level under the "
        "frozen stop-first scan); no hypothetical runner credit"
    ),
    "runner_stop": (
        "R0: the runner leg retains the original frozen SL for the whole "
        "trade (full -1R on the runner fraction if stopped)"
    ),
    "authority_registry_sha256": V0_6_REGISTRY_SHA256,
    "authority_commit": PARENT_SHA,
}

COLLISION_POLICY = {
    "collision_policy_id": "SAME_BAR_STOP_FIRST_FROZEN_V0_3",
    "rule": (
        "within any single M15 bar, if the frozen SL and any exit target "
        "are both touched, the STOP is counted FIRST (fail-closed: OHLC "
        "data does not establish intrabar order). This single rule covers "
        "SL-vs-first-objective, SL-vs-runner-target, and any combination; "
        "no ambiguous branch exists"
    ),
    "same_bar_first_and_runner_objective": (
        "when the first objective and the runner objective are both "
        "touched in one bar and the SL is not touched, BOTH legs exit in "
        "that bar — the first leg at the first-objective price, the runner "
        "leg at the runner-objective price"
    ),
    "authority": (
        "frozen V0.3 fail-closed collision rule "
        "(ag_edgelab.universal.target_v0_5._target_reachability_impl: "
        "'stop counted FIRST (same-bar collision fail-closed)') and "
        "AG_REFERENCE_REPLAY v1.1.0 ('If a stop and target are both "
        "reachable in the same bar, stop wins because OHLC data does not "
        "establish intrabar order')"
    ),
    "replaces": "FAIL_CLOSED_OR_CANONICAL_FILL (ambiguous) — superseded by "
                "this one exact policy",
}

def _session_samples() -> dict:
    """Derive sample labels through the frozen labelling function itself."""
    from datetime import datetime, timezone
    samples = {}
    for hour, minute in ((0, 30), (9, 0), (14, 0), (17, 0), (22, 0)):
        ts = datetime(2017, 3, 1, hour, minute, tzinfo=timezone.utc)
        samples[f"{hour:02d}:{minute:02d}"] = session_label(ts)
    return samples


SESSION_AUTHORITY = {
    "session_authority_id": SESSION_AUTHORITY_ID,
    "windows_utc": [
        {"start_hour": s, "end_hour": e, "label": label}
        for s, e, label in SESSION_WINDOWS_UTC
    ],
    "precedence": "LONDON_NEWYORK_OVERLAP (13-16 UTC) takes precedence over "
                  "LONDON/NEW_YORK",
    "role": "diagnostic stratification only; never a trigger or validity "
            "requirement",
    "labelling_function": "ag_edgelab.universal.trigger_v0_4.session_label "
                          "(frozen V0.3 session definitions)",
    "sample_labels": _session_samples(),
}


# Friction: the repository contains a PARAMETRIC friction contract only
# (ag_edgelab.friction.model.FrictionScenario). No pinned authoritative
# spread/commission/slippage values exist for EURUSD/GBPUSD/USDJPY/XAUUSD
# 2017 (V0.6 economic_authority.json fail-closed; inventing values is
# forbidden). The table below is therefore EXPLICITLY UNAVAILABLE per
# symbol and per cost slot, hash-bound so that any substitution
# (adversarial attack A5) changes FRICTION_TABLE_SHA256 and is rejected.
SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")
_UNAVAILABLE = "UNAVAILABLE_NO_REPOSITORY_AUTHORITY"
_UNPRICED = "UNPRICED_NO_AUTHORITY"
FRICTION_PROVENANCE = (
    "ag_edgelab.friction.FrictionScenario is a parametric contract; the "
    "repository pins no authoritative spread/commission/slippage values "
    "for EURUSD/GBPUSD/USDJPY/XAUUSD 2017 (V0.6 "
    "data/artifacts/universal_funnel_v0_6_target_policy/"
    "economic_authority.json: 'inventing values is forbidden'); net "
    "economics fail closed"
)

FRICTION_TABLE = {
    symbol: {
        "spread": _UNAVAILABLE,
        "slippage": _UNAVAILABLE,
        "commission": _UNAVAILABLE,
        "entry_treatment": _UNPRICED,
        "partial_close_cost": _UNPRICED,
        "runner_close_cost": _UNPRICED,
        "forced_horizon_close_cost": _UNPRICED,
        "provenance": FRICTION_PROVENANCE,
    }
    for symbol in SYMBOLS
}


def derive_friction_authority_complete(table: dict) -> bool:
    """FRICTION_AUTHORITY_COMPLETE is DERIVED from bound table content.

    A value is authoritative only if it is a pinned non-negative number
    with non-empty provenance naming a repository authority. Any
    UNAVAILABLE/UNPRICED slot => NO. A caller-supplied boolean can never
    flip this: the verifier recomputes it from the hash-bound table.
    """
    for symbol in SYMBOLS:
        row = table.get(symbol)
        if not isinstance(row, dict):
            return False
        for slot in ("spread", "slippage", "commission"):
            value = row.get(slot)
            if not isinstance(value, (int, float)) or isinstance(value, bool) \
                    or value < 0:
                return False
        for slot in ("entry_treatment", "partial_close_cost",
                     "runner_close_cost", "forced_horizon_close_cost"):
            value = row.get(slot)
            if not (isinstance(value, str) and value
                    and value not in (_UNAVAILABLE, _UNPRICED)):
                return False
        prov = row.get("provenance")
        if not (isinstance(prov, str) and "fail closed" not in prov.lower()
                and "unavailable" not in prov.lower()
                and "no repository authority" not in prov.lower()):
            return False
    return True


FRICTION_MODEL = {
    "friction_model_id": FRICTION_MODEL_ID,
    "parametric_contract": "ag_edgelab.friction.model.FrictionScenario "
                           "(spread_r/commission_r/slippage_r/swap_r in R)",
    "status": "AUTHORITY_ABSENT_FAIL_CLOSED",
    "consequence": "FRICTION_AUTHORITY_COMPLETE=NO; OOS_ECONOMIC_READY=NO; "
                   "net_trade_R is never claimed; gross structural R only",
}

DATASET_ROLE_POLICY = {
    "dataset_role_policy_id": "DEV_PARTITION_ONLY_HISTDATA_2017_PINNED",
    "role": DATASET_ROLE,
    "authority": "HISTDATA_ASCII_M1_2017_PR10_PINNED "
                 "(ag_edgelab.data.fx_histdata_2017.PARTITIONS + "
                 "PINNED_SOURCE_SHA256)",
    "pinned_source_sha256": {
        "EURUSD": "0dcd66dc67d7af4716404a5315d376ee1e7eaebe292afbda3c1003d2dfa16f57",
        "GBPUSD": "e5ba3800e37fae0e326dbaa234952ca04e8f378c08b036530a2811206110c10b",
        "USDJPY": "477a1f515586f06d67cb75b3662260160e1e29e63c51804a30a5e7d69b09df5f",
        "XAUUSD": "a39c1ccaaeb022c83309685107c9e619c2bcff8b2fd94fbd7405a721a4fe70ff",
    },
    "partitions": {
        "DEVELOPMENT": ["2017-01-01T00:00:00+00:00", "2017-09-01T00:00:00+00:00"],
        "OOS": ["2017-09-01T00:00:00+00:00", "2017-12-01T00:00:00+00:00"],
        "SEALED_HOLDOUT": ["2017-12-01T00:00:00+00:00", "2018-01-01T00:00:00+00:00"],
    },
    "rule": (
        "candidate evidence may be produced ONLY from the DEVELOPMENT "
        "partition; the OOS partition must remain unopened until an "
        "explicit OOS mission; the SEALED_HOLDOUT is never readable; every "
        "evidence row must lie inside the DEVELOPMENT window"
    ),
    "oos_opened": False,
    "holdout_touched": False,
}

POPULATION_AUTHORITY = {
    "population_authority_id": "D01_CONTROL_POPULATION_V0_3_FX_DEV",
    "definition": (
        "the frozen V0.3 FX DEV campaign entry population (D01 trigger "
        "authority above); T1 (379) and T2 are recorded sub-populations, "
        "never a substitute population"
    ),
    "pinned_entry_n": 3183,
    "pinned_t1_subset_n": 379,
    "v0_6_entry_policy_ledger_sha256":
        "83ec42db616e247c59a2a21715aa41d99469da163cccd3025d61ee62426c000b",
    "v0_6_objective_sequence_ledger_sha256":
        "3729a96940886b73314309beb6ffff3b12a8c7d456865770c1a99d27aaf4f9b9",
    "v0_6_final_report_sha256":
        "4c6d3cfbac5fd4fed0bbe4558df6e44f1f1ef1240e14320608b090e6646bfce9",
    "crosscheck_rule": (
        "every DEV row must reproduce the parent V0.6 C3_F50_R0 structural "
        "outcome exactly for resolved statuses (STOPPED_BEFORE_FIRST, "
        "PARTIAL_PLUS_RUNNER_TARGET, PARTIAL_PLUS_RUNNER_STOPPED) and map "
        "1:1 for the remainder (PARTIAL_RUNNER_OPEN -> "
        "FIRST_PLUS_RUNNER_HORIZON; UNRESOLVED_WINDOW -> "
        "HORIZON_BEFORE_FIRST; NOT_APPLICABLE_* unchanged)"
    ),
}

# Sub-policy hashes (canonical, content-addressed)
TRIGGER_AUTHORITY_HASH = sha256_json(TRIGGER_AUTHORITY)
FIRST_TARGET_POLICY_HASH = sha256_json(FIRST_TARGET_POLICY)
RUNNER_TARGET_POLICY_HASH = sha256_json(RUNNER_TARGET_POLICY)
COLLISION_POLICY_HASH = sha256_json(COLLISION_POLICY)
SESSION_AUTHORITY_HASH = sha256_json(SESSION_AUTHORITY)
FRICTION_MODEL_HASH = sha256_json(FRICTION_MODEL)
FRICTION_TABLE_SHA256 = sha256_json(FRICTION_TABLE)
DATASET_ROLE_POLICY_HASH = sha256_json(DATASET_ROLE_POLICY)
POPULATION_AUTHORITY_HASH = sha256_json(POPULATION_AUTHORITY)

FRICTION_AUTHORITY_COMPLETE = derive_friction_authority_complete(FRICTION_TABLE)

CANONICAL_SERIALIZATION = {
    "encoding": "UTF-8",
    "json_keys_sorted": True,
    "separators": [",", ":"],
    "no_pretty_print": True,
    "stable_numeric_representation":
        "integers exact; floats via Python json float repr (shortest "
        "round-trip float64 repr); NaN/Infinity forbidden (allow_nan=False)",
    "path_a": "ag_edgelab.data.fingerprint.canonical_json "
              "(json.dumps sort_keys=True, separators=(',',':'), "
              "ensure_ascii=True, allow_nan=False)",
    "path_b": "ag_edgelab.verification.c3_v1_verifier.canonical_serialize "
              "(independent from-scratch recursive serializer)",
    "requirement": "PATH_A bytes == PATH_B bytes and sha256 equal, else "
                   "STATUS=HASH_REPRODUCTION_FAIL",
}

# ---------------------------------------------------------------------------
# Canonical contract (mission section 2 — every behaviorally relevant field)
# ---------------------------------------------------------------------------


def build_contract(dev_evidence_manifest_sha256: str) -> dict:
    """The single canonical contract object. Pure function of frozen
    authorities + the DEV evidence manifest binding."""
    return {
        "candidate_id": CANDIDATE_ID,
        "version": CANDIDATE_VERSION,
        "parent_sha": PARENT_SHA,
        "parent_tree": PARENT_TREE,
        "trigger_authority_id": TRIGGER_AUTHORITY["trigger_authority_id"],
        "trigger_authority_hash": TRIGGER_AUTHORITY_HASH,
        "first_objective_pct": FIRST_OBJECTIVE_PCT,
        "runner_pct": RUNNER_PCT,
        "fraction_selection_authority": FRACTION_SELECTION_AUTHORITY,
        "frozen_fraction_grid": list(FROZEN_FRACTION_GRID),
        "first_target_policy_id": FIRST_TARGET_POLICY["first_target_policy_id"],
        "first_target_policy_hash": FIRST_TARGET_POLICY_HASH,
        "runner_target_policy_id": RUNNER_TARGET_POLICY["runner_target_policy_id"],
        "runner_target_policy_hash": RUNNER_TARGET_POLICY_HASH,
        "runner_stop_policy": RUNNER_STOP_POLICY,
        "termination_policy": TERMINATION_POLICY,
        "forced_close_authority": FORCED_CLOSE_AUTHORITY,
        "research_horizon": RESEARCH_HORIZON_BARS,
        "horizon_anchor": HORIZON_ANCHOR,
        "horizon_timeframe": HORIZON_UNIT,
        "horizon_exit_price_authority": HORIZON_EXIT_PRICE_AUTHORITY,
        "same_bar_collision_policy": SAME_BAR_COLLISION_POLICY,
        "collision_authority_id": COLLISION_AUTHORITY_ID,
        "collision_policy_hash": COLLISION_POLICY_HASH,
        "censoring_policy": CENSORING_POLICY,
        "dataset_role_policy": DATASET_ROLE_POLICY["dataset_role_policy_id"],
        "dataset_role_policy_hash": DATASET_ROLE_POLICY_HASH,
        "dataset_role": DATASET_ROLE,
        "dataset_authority": DATASET_ROLE_POLICY["authority"],
        "dataset_pinned_sha256": DATASET_ROLE_POLICY["pinned_source_sha256"],
        "dataset_partitions": DATASET_ROLE_POLICY["partitions"],
        "population_authority_id": POPULATION_AUTHORITY["population_authority_id"],
        "population_authority_hash": POPULATION_AUTHORITY_HASH,
        "population_pinned_entry_n": POPULATION_AUTHORITY["pinned_entry_n"],
        "friction_model_id": FRICTION_MODEL_ID,
        "friction_model_hash": FRICTION_MODEL_HASH,
        "friction_table_hash": FRICTION_TABLE_SHA256,
        "friction_authority_complete_derived": FRICTION_AUTHORITY_COMPLETE,
        "session_authority_id": SESSION_AUTHORITY_ID,
        "session_authority_hash": SESSION_AUTHORITY_HASH,
        "target_family_contracts": {
            family: {"status": contract["status"],
                     "definition": contract["definition"]}
            for family, contract in FAMILY_CONTRACTS.items()
        },
        "v0_5_target_registry_sha256": TARGET_V0_5_REGISTRY_SHA256,
        "v0_6_target_policy_registry_sha256": V0_6_REGISTRY_SHA256,
        "dev_evidence_manifest_sha256": dev_evidence_manifest_sha256,
        "serialization": CANONICAL_SERIALIZATION,
        "oos_opened": False,
        "holdout_touched": False,
    }


def canonical_contract_bytes(contract: dict) -> bytes:
    """PATH A canonical serialization: UTF-8 bytes of the canonical JSON."""
    return canonical_json(contract).encode("utf-8")


def contract_sha256_path_a(contract: dict) -> str:
    import hashlib
    return hashlib.sha256(canonical_contract_bytes(contract)).hexdigest()


# ---------------------------------------------------------------------------
# Candidate replay — complete termination inside the frozen window
# ---------------------------------------------------------------------------

HORIZON_MINUTES = 15


@dataclass(frozen=True)
class Leg:
    pct: float
    exit_bar: int | None          # 1-based forward-bar offset
    exit_price: float | None
    exit_reason: str | None       # SL | FIRST_OBJECTIVE | RUNNER_TARGET | HORIZON_CLOSE
    leg_r: float | None


@dataclass(frozen=True)
class TradeResolution:
    status: str
    first_leg: Leg
    runner_leg: Leg
    gross_trade_r: float | None
    horizon_close: float | None
    censored: bool
    stop_bar: int | None


def _hit_stop(bar: MarketBar, bull: bool, stop: float) -> bool:
    return bar.low <= stop if bull else bar.high >= stop


def _hit_target(bar: MarketBar, bull: bool, price: float) -> bool:
    return bar.high >= price if bull else bar.low <= price


def signed_r(entry: float, stop: float, exit_price: float, bull: bool) -> float:
    """Signed exit R under the frozen geometry: (exit-entry)/risk for BULL,
    (entry-exit)/risk for BEAR. A stop exit is exactly -1.0."""
    risk = abs(entry - stop)
    if risk <= 0:
        raise ValueError("entry geometry requires non-zero risk")
    return (exit_price - entry) / risk if bull else (entry - exit_price) / risk


def resolve_trade(forward: Sequence[MarketBar], *, direction: str,
                  entry_price: float, stop_price: float,
                  first_price: float | None, first_r: float | None,
                  runner_price: float | None, runner_r: float | None,
                  horizon_bars: int = RESEARCH_HORIZON_BARS) -> TradeResolution:
    """Deterministic complete-termination resolution of ONE C3 trade.

    Bar scan, stop FIRST within every bar (the single frozen collision
    rule). The window is exactly `horizon_bars` forward bars after the
    entry bar; if fewer bars are available the trade is
    RIGHT_CENSORED_DATA_BOUNDARY (never imputed)."""
    bull = direction == "BULL"
    f = FIRST_OBJECTIVE_PCT / 100.0
    rf = RUNNER_PCT / 100.0

    if len(forward) < horizon_bars:
        return TradeResolution(
            status=CENSORED_STATUS,
            first_leg=Leg(f, None, None, None, None),
            runner_leg=Leg(rf, None, None, None, None),
            gross_trade_r=None, horizon_close=None, censored=True,
            stop_bar=None)

    window = forward[:horizon_bars]
    horizon_close = window[-1].close

    # ---- phase 1: first leg (whole position while the first objective is
    # unreached; stop first on every bar, including same-bar collisions)
    t1 = None
    stop_bar = None
    for t, bar in enumerate(window, start=1):
        if _hit_stop(bar, bull, stop_price):
            stop_bar = t
            break
        if first_price is not None and _hit_target(bar, bull, first_price):
            t1 = t
            break

    if stop_bar is not None:
        # SL before the first objective is reached (same-bar collision
        # resolves here too: stop first). Whole position -1R.
        first_leg = Leg(f, stop_bar, stop_price, "SL", f * -1.0)
        runner_leg = Leg(rf, stop_bar, stop_price, "SL", rf * -1.0)
        return TradeResolution(
            status="STOPPED_BEFORE_FIRST", first_leg=first_leg,
            runner_leg=runner_leg, gross_trade_r=-1.0,
            horizon_close=horizon_close, censored=False, stop_bar=stop_bar)

    if t1 is None:
        # neither SL nor first objective inside the window: whole position
        # force-closed at the last completed M15 bar close (DATA_END fill)
        hr = signed_r(entry_price, stop_price, horizon_close, bull)
        first_leg = Leg(f, horizon_bars, horizon_close, "HORIZON_CLOSE", f * hr)
        runner_leg = Leg(rf, horizon_bars, horizon_close, "HORIZON_CLOSE", rf * hr)
        return TradeResolution(
            status="HORIZON_BEFORE_FIRST", first_leg=first_leg,
            runner_leg=runner_leg, gross_trade_r=first_leg.leg_r + runner_leg.leg_r,
            horizon_close=horizon_close, censored=False, stop_bar=None)

    # ---- first objective reached at t1: first leg exits there
    first_leg = Leg(f, t1, first_price, "FIRST_OBJECTIVE", f * (first_r or 0.0))

    # ---- phase 2: runner leg (R0: original frozen SL retained); scan
    # restarts at t1 — a same-bar first+runner touch pays the runner
    t2 = None
    stop2 = None
    for t in range(t1, horizon_bars + 1):
        bar = window[t - 1]
        if _hit_stop(bar, bull, stop_price):
            stop2 = t
            break
        if runner_price is not None and _hit_target(bar, bull, runner_price):
            t2 = t
            break

    if t2 is not None:
        runner_leg = Leg(rf, t2, runner_price, "RUNNER_TARGET", rf * (runner_r or 0.0))
        status = "FIRST_PLUS_RUNNER_TARGET"
    elif stop2 is not None:
        runner_leg = Leg(rf, stop2, stop_price, "SL", rf * -1.0)
        status = "FIRST_PLUS_RUNNER_STOP"
    else:
        hr = signed_r(entry_price, stop_price, horizon_close, bull)
        runner_leg = Leg(rf, horizon_bars, horizon_close, "HORIZON_CLOSE", rf * hr)
        status = "FIRST_PLUS_RUNNER_HORIZON"

    return TradeResolution(
        status=status, first_leg=first_leg, runner_leg=runner_leg,
        gross_trade_r=first_leg.leg_r + runner_leg.leg_r,
        horizon_close=horizon_close, censored=False,
        stop_bar=stop2 if status == "FIRST_PLUS_RUNNER_STOP" else None)


# ---------------------------------------------------------------------------
# V0.6 parent cross-check mapping
# ---------------------------------------------------------------------------

V06_STATUS_MAP = {
    "STOPPED_BEFORE_FIRST": "STOPPED_BEFORE_FIRST",
    "PARTIAL_PLUS_RUNNER_TARGET": "FIRST_PLUS_RUNNER_TARGET",
    "PARTIAL_PLUS_RUNNER_STOPPED": "FIRST_PLUS_RUNNER_STOP",
    "PARTIAL_RUNNER_OPEN": "FIRST_PLUS_RUNNER_HORIZON",
    "UNRESOLVED_WINDOW": "HORIZON_BEFORE_FIRST",
    "NOT_APPLICABLE_NO_OBJECTIVE": "NOT_APPLICABLE_NO_OBJECTIVE",
    "NOT_APPLICABLE_NO_RUNNER_OBJECTIVE": "NOT_APPLICABLE_NO_RUNNER_OBJECTIVE",
}


def horizon_time(entry_time, horizon_bars: int = RESEARCH_HORIZON_BARS):
    """Close time of the last bar in the frozen outcome window."""
    return entry_time + timedelta(minutes=HORIZON_MINUTES * horizon_bars)
