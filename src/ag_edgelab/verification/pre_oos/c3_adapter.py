"""Adapter: TARGET_POLICY_C3_V1's frozen DEV evidence -> gate observations.

C3 is used here as a historical NEGATIVE CONTROL. Its OOS verdict is
already spent and recorded as a permanent rejection, which makes it the
one candidate whose later behaviour is known and therefore the only one
against which the gate's pre-OOS judgement can be checked.

Three boundaries are respected absolutely:

* **Nothing about C3 is modified.** The verifier adapts to the
  candidate's frozen artifacts; the candidate does not mutate for the
  verifier. This module only reads.
* **Only DEV evidence is read.** ``dev_resolution_ledger.jsonl`` and
  ``canonical_contract.json`` from the freeze. The OOS directory is
  never opened by this module, and a test asserts that.
* **The OOS result is not used to calibrate anything.** Thresholds were
  frozen and committed before this file existed.

FOLD CONSTRUCTION
-----------------
C3's DEV window is HistData 2017 (2017-01-01 to 2017-09-01), not the
Dukascopy multi-year corpus, so the data authority's 21 walk-forward
folds do not apply to it. Folds are therefore constructed by a fixed
calendar rule — anchored expanding train, one-calendar-month test
windows — chosen for being mechanical and stated in the artifact. It is
not tuned to produce any particular number of folds.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ag_edgelab.data.fingerprint import sha256_file, sha256_json
from ag_edgelab.verification.pre_oos.axes import Fold, PerturbableParameter
from ag_edgelab.verification.pre_oos.identity import CandidateIdentity
from ag_edgelab.verification.pre_oos.observations import (
    LineageDeclaration, Observation,
)
from ag_edgelab.verification.pre_oos.regime import label_sequence

C3_DIR = Path("data/artifacts/target_policy_c3_v1")
C3_LEDGER = "dev_resolution_ledger.jsonl"
C3_CONTRACT = "canonical_contract.json"
C3_ACCOUNTING = "dev_accounting.json"
V0_6_PREREG = Path(
    "data/artifacts/universal_funnel_v0_6_target_policy/preregistration.json")

#: Subsets of the canonical contract that define each rule surface. The
#: candidate did not publish separate entry/SL/target hashes, so they are
#: derived deterministically from documented key subsets rather than
#: invented or left blank.
ENTRY_KEYS = ("trigger_authority_id", "trigger_authority_hash",
              "population_authority_id", "population_authority_hash")
SL_KEYS = ("same_bar_collision_policy", "collision_authority_id",
           "collision_policy_hash", "runner_stop_policy")
TARGET_KEYS = ("first_target_policy_id", "first_target_policy_hash",
               "runner_target_policy_id", "runner_target_policy_hash",
               "first_objective_pct", "runner_pct", "frozen_fraction_grid",
               "research_horizon", "horizon_anchor",
               "horizon_exit_price_authority")
STRATEGY_RULE_KEYS = ENTRY_KEYS + SL_KEYS + TARGET_KEYS


def _subset_hash(contract: dict, keys: tuple[str, ...]) -> str:
    return sha256_json({k: contract[k] for k in keys if k in contract})


def load_contract(root: Path = Path(".")) -> dict:
    return json.loads((root / C3_DIR / C3_CONTRACT).read_text())


def load_accounting(root: Path = Path(".")) -> dict:
    return json.loads((root / C3_DIR / C3_ACCOUNTING).read_text())


def build_identity(root: Path = Path(".")) -> CandidateIdentity:
    """Assemble C3's identity from its own frozen artifacts."""
    contract = load_contract(root)
    prereg_path = root / V0_6_PREREG
    prereg_hash = sha256_file(prereg_path) if prereg_path.is_file() else None
    return CandidateIdentity(
        candidate_id=contract["candidate_id"],
        candidate_version=contract["version"],
        candidate_sha256=sha256_json(contract),
        strategy_rule_hash=_subset_hash(contract, STRATEGY_RULE_KEYS),
        dataset_manifest_hash=contract["dev_evidence_manifest_sha256"],
        engine_version=contract["collision_authority_id"],
        entry_contract_hash=_subset_hash(contract, ENTRY_KEYS),
        sl_contract_hash=_subset_hash(contract, SL_KEYS),
        target_contract_hash=_subset_hash(contract, TARGET_KEYS),
        preregistration_hash=prereg_hash,
        preregistration_applicable=prereg_hash is not None,
        contract_content=contract,
    )


def load_observations(root: Path = Path(".")) -> list[Observation]:
    """Read the frozen DEV resolution ledger, labelling regimes causally."""
    accounting = load_accounting(root)
    role = accounting["dataset_role"]           # DEVELOPMENT, read not assumed
    rows = []
    with (root / C3_DIR / C3_LEDGER).open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows.sort(key=lambda r: (r["entry_time"], r["entry_id"]))

    observations = [
        Observation(
            observation_id=r["entry_id"],
            symbol=r["symbol"],
            timestamp_utc=datetime.fromisoformat(r["entry_time"]).astimezone(
                timezone.utc),
            gross_r=r.get("gross_trade_r"),
            dataset_role=role,
            session=r.get("session"),
            status=r.get("status"),
            risk_distance=r.get("risk_distance"),
        )
        for r in rows
    ]
    return _apply_regimes(observations)


def _apply_regimes(observations: list[Observation]) -> list[Observation]:
    """Attach causal volatility x session regime cells."""
    labels = label_sequence(
        [o.risk_distance for o in observations],
        symbols=[o.symbol for o in observations])
    out = []
    for obs, label in zip(observations, labels):
        cell = (f"{label.volatility}|{obs.session}" if label.is_classified
                else None)
        out.append(Observation(
            observation_id=obs.observation_id, symbol=obs.symbol,
            timestamp_utc=obs.timestamp_utc, gross_r=obs.gross_r,
            dataset_role=obs.dataset_role, session=obs.session,
            regime=cell, status=obs.status,
            risk_distance=obs.risk_distance))
    return out


def recompute_regimes(observations: list[Observation]) -> list[str | None]:
    """Independent causal recomputation, for the temporal-integrity check."""
    labels = label_sequence(
        [o.risk_distance for o in observations],
        symbols=[o.symbol for o in observations])
    return [(f"{l.volatility}|{o.session}" if l.is_classified else None)
            for o, l in zip(observations, labels)]


def build_folds(observations: list[Observation]) -> list[Fold]:
    """Anchored expanding train, one-calendar-month test windows."""
    if not observations:
        return []
    times = sorted(o.timestamp_utc for o in observations)
    start = datetime(times[0].year, times[0].month, 1, tzinfo=timezone.utc)
    last = times[-1]

    months: list[datetime] = []
    cursor = start
    while cursor <= last:
        months.append(cursor)
        cursor = (datetime(cursor.year + 1, 1, 1, tzinfo=timezone.utc)
                  if cursor.month == 12
                  else datetime(cursor.year, cursor.month + 1, 1,
                                tzinfo=timezone.utc))
    months.append(cursor)

    folds = []
    for i in range(1, len(months) - 1):
        folds.append(Fold(
            fold_id=f"WF{i:02d}_{months[i]:%Y%m}",
            train_start=start, train_end=months[i],
            test_start=months[i], test_end=months[i + 1]))
    return folds


def lineage(root: Path = Path(".")) -> LineageDeclaration:
    """C3 predates its own OOS verdict, so its DEV evidence is uninformed."""
    return LineageDeclaration(
        candidate_id="TARGET_POLICY_C3_V1",
        candidate_family="TARGET_POLICY_C3",
        designed_at_utc=datetime(2017, 1, 1, tzinfo=timezone.utc),
        informed_by_consumed_oos=False,
        informed_by_windows=(),
    )


def parameters() -> list[PerturbableParameter]:
    """C3's numeric parameters, and why the frozen ledger cannot probe them.

    ``first_objective_pct`` and ``research_horizon`` are genuinely
    numeric and genuinely perturbable in principle. But moving either
    changes which price path events fire, and the frozen DEV ledger
    stores only each trade's RESOLVED outcome — not the path. Re-deriving
    an outcome at 45% or at 86 bars would require replaying the engine
    over the 2017 bars, which is a re-run of the strategy and outside
    this mission's boundary.

    So the honest state is "not evaluable from the frozen evidence",
    recorded as such rather than silently skipped or faked with an
    interpolation.
    """
    return [
        PerturbableParameter(
            name="first_objective_pct", frozen_value=50.0,
            semantics="percent of position closed at the first objective",
            perturbable=False,
            reason_not_perturbable=(
                "NOT_EVALUABLE_FROM_FROZEN_LEDGER — changing the split "
                "changes which path events fire; the DEV ledger stores "
                "resolved outcomes only, and replaying the engine to "
                "re-derive them would be a strategy re-run, which this "
                "mission forbids. No interpolation is substituted.")),
        PerturbableParameter(
            name="research_horizon_bars", frozen_value=96.0,
            semantics="M15 bars before forced horizon close",
            perturbable=False,
            reason_not_perturbable=(
                "NOT_EVALUABLE_FROM_FROZEN_LEDGER — the horizon determines "
                "the forced-close price, which is a path property absent "
                "from the resolved ledger.")),
    ]


def fold_construction_note() -> dict:
    return {
        "rule": "anchored expanding train; one-calendar-month test windows",
        "why_not_data_authority_folds": (
            "C3's DEV evidence is HISTDATA_ASCII_M1_2017_PR10_PINNED "
            "(2017-01-01 to 2017-09-01), not the Dukascopy 2011-2018 corpus, "
            "so the data authority's 21 walk-forward folds do not cover it."),
        "preregistered": True,
        "chosen_after_seeing_results": False,
    }
