"""Causality and integrity attacks against the gate.

Each attack deliberately corrupts one assumption and asserts the gate
notices. An attack that "passes" means the gate *rejected* the corrupted
input, or that the corruption provably could not propagate.

These are not unit tests of convenience — they are the difference
between a gate and a formality. A gate that cannot detect a relabelled
consumed-OOS window is not protecting the OOS budget, it is decorating
the decision to spend it.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ag_edgelab.data.authority.cas import CasStore, ContentMismatch
from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.statistics.bootstrap import bootstrap_expectancy_ci
from ag_edgelab.verification.pre_oos.axes import Fold, assert_folds_ordered
from ag_edgelab.verification.pre_oos.contract import RobustnessContract
from ag_edgelab.verification.pre_oos.gate import temporal_integrity
from ag_edgelab.verification.pre_oos.identity import (
    CandidateIdentity, CandidateIdentityInvalid, assert_identity,
)
from ag_edgelab.verification.pre_oos.observations import (
    ConsumedWindow, DatasetRoleViolation, LineageContamination,
    LineageDeclaration, Observation, admit,
)
from ag_edgelab.verification.pre_oos.regime import label_sequence

UTC = timezone.utc


@dataclass
class AttackResult:
    attack_id: str
    name: str
    detected: bool
    expected_detection: bool
    detail: str

    @property
    def passed(self) -> bool:
        return self.detected == self.expected_detection

    def as_dict(self) -> dict:
        return {
            "attack_id": self.attack_id,
            "name": self.name,
            "detected": self.detected,
            "expected_detection": self.expected_detection,
            "passed": self.passed,
            "detail": self.detail,
        }


def _obs(i: int, *, role: str = "DEVELOPMENT", r: float = 1.0,
         symbol: str = "EURUSD", day: int = 1) -> Observation:
    return Observation(
        observation_id=f"{symbol}:{i}", symbol=symbol,
        timestamp_utc=datetime(2017, 1, 1, tzinfo=UTC) + timedelta(days=day),
        gross_r=r, dataset_role=role, risk_distance=0.001 + i * 1e-6,
        session="LONDON")


def a1_future_bar_mutation() -> AttackResult:
    """Mutating a LATER observation must not change an EARLIER label."""
    values = [0.001 + i * 1e-5 for i in range(80)]
    symbols = ["EURUSD"] * 80
    before = label_sequence(list(values), symbols=symbols)
    mutated = list(values)
    mutated[70] = 99.0                      # a violent change in the future
    after = label_sequence(mutated, symbols=symbols)
    leaked = [i for i in range(70) if before[i].cell != after[i].cell]
    return AttackResult(
        "A1", "future-bar mutation", detected=not leaked, expected_detection=True,
        detail=("no earlier label changed when a later value was mutated"
                if not leaked else
                f"LEAK: labels {leaked[:5]} changed from future information"))


def a2_truncation() -> AttackResult:
    """Truncating evidence must change the reported sample, never be silent."""
    full = [_obs(i, day=i % 200) for i in range(300)]
    truncated = full[:100]
    from ag_edgelab.verification.pre_oos.axes import sample_sufficiency
    a = sample_sufficiency(full)
    b = sample_sufficiency(truncated)
    detected = a["resolved"] != b["resolved"]
    return AttackResult(
        "A2", "truncation", detected=detected, expected_detection=True,
        detail=f"resolved {a['resolved']} -> {b['resolved']} after truncation")


def a3_shuffled_future() -> AttackResult:
    """A population shuffled out of chronological order must be rejected."""
    rows = [_obs(i, day=i) for i in range(50)]
    shuffled = rows[25:] + rows[:25]
    finding = temporal_integrity(shuffled)
    return AttackResult(
        "A3", "shuffled future", detected=finding.fired, expected_detection=True,
        detail=finding.detail)


def a4_candidate_id_mutation() -> AttackResult:
    """Editing contract content after freezing must break hash reproduction."""
    content = {"candidate_id": "X", "rule": "a", "value": 1}
    identity = CandidateIdentity(
        candidate_id="X", candidate_version="1.0.0",
        candidate_sha256=sha256_json(content),
        strategy_rule_hash="a" * 64, dataset_manifest_hash="b" * 64,
        engine_version="E1", entry_contract_hash="c" * 64,
        sl_contract_hash="d" * 64, target_contract_hash="e" * 64,
        contract_content=content)
    assert_identity(identity)                       # clean baseline
    tampered = copy.deepcopy(content)
    tampered["value"] = 2
    mutated = CandidateIdentity(
        candidate_id="X", candidate_version="1.0.0",
        candidate_sha256=identity.candidate_sha256,
        strategy_rule_hash="a" * 64, dataset_manifest_hash="b" * 64,
        engine_version="E1", entry_contract_hash="c" * 64,
        sl_contract_hash="d" * 64, target_contract_hash="e" * 64,
        contract_content=tampered)
    try:
        assert_identity(mutated)
        return AttackResult("A4", "candidate-id mutation", False, True,
                            "MUTATION ACCEPTED — identity did not reproduce-check")
    except CandidateIdentityInvalid as exc:
        return AttackResult("A4", "candidate-id mutation", True, True, str(exc)[:200])


def a5_dataset_role_forgery() -> AttackResult:
    """An OOS-roled observation must be refused, not filtered away."""
    rows = [_obs(i, day=i) for i in range(10)]
    rows.append(_obs(99, role="OOS", day=11))
    try:
        admit(rows, lineage=LineageDeclaration("X", "F",
                                               informed_by_consumed_oos=False))
        return AttackResult("A5", "dataset-role forgery", False, True,
                            "FORGED ROLE ACCEPTED")
    except DatasetRoleViolation as exc:
        return AttackResult("A5", "dataset-role forgery", True, True, str(exc)[:200])


def a6_cas_hash_mismatch(tmp_root) -> AttackResult:
    """A corrupted content-addressed object must fail on read."""
    store = CasStore(tmp_root)
    digest = store.put_text("authoritative evidence")
    path = store.path_for(digest)
    path.write_bytes(b"tampered evidence")
    try:
        store.get_bytes(digest)
        return AttackResult("A6", "CAS hash mismatch", False, True,
                            "CORRUPTED OBJECT READ SUCCESSFULLY")
    except ContentMismatch as exc:
        return AttackResult("A6", "CAS hash mismatch", True, True, str(exc)[:200])


def a7_consumed_oos_relabelled_as_dev() -> AttackResult:
    """A spent OOS window relabelled DEVELOPMENT must be caught by lineage."""
    window = ConsumedWindow(
        window_id="OOS-002", candidate_family="TARGET_POLICY_C3",
        consumed_by="TARGET_POLICY_C3_V1",
        start_utc=datetime(2017, 9, 1, tzinfo=UTC),
        end_utc=datetime(2017, 12, 1, tzinfo=UTC))
    rows = [Observation(
        observation_id=f"EURUSD:{i}", symbol="EURUSD",
        timestamp_utc=datetime(2017, 10, 1, tzinfo=UTC) + timedelta(days=i),
        gross_r=1.0, dataset_role="DEVELOPMENT") for i in range(5)]
    informed = LineageDeclaration(
        candidate_id="C3_DESCENDANT", candidate_family="TARGET_POLICY_C3",
        informed_by_consumed_oos=True)
    try:
        admit(rows, lineage=informed, consumed_windows=(window,))
        return AttackResult("A7", "consumed-OOS relabelled as DEV", False, True,
                            "RELABELLED WINDOW ACCEPTED")
    except LineageContamination as exc:
        return AttackResult("A7", "consumed-OOS relabelled as DEV", True, True,
                            str(exc)[:200])


def a7b_ambiguous_lineage_fails_closed() -> AttackResult:
    """An undeclared lineage over a consumed window must fail closed."""
    window = ConsumedWindow(
        "OOS-002", "TARGET_POLICY_C3", "TARGET_POLICY_C3_V1",
        datetime(2017, 9, 1, tzinfo=UTC), datetime(2017, 12, 1, tzinfo=UTC))
    rows = [Observation(f"EURUSD:{i}", "EURUSD",
                        datetime(2017, 10, 1, tzinfo=UTC) + timedelta(days=i),
                        1.0, "DEVELOPMENT") for i in range(3)]
    undeclared = LineageDeclaration("UNKNOWN_DESCENDANT", "TARGET_POLICY_C3")
    try:
        admit(rows, lineage=undeclared, consumed_windows=(window,))
        return AttackResult("A7b", "ambiguous lineage", False, True,
                            "AMBIGUOUS LINEAGE ACCEPTED")
    except LineageContamination as exc:
        return AttackResult("A7b", "ambiguous lineage", True, True, str(exc)[:200])


def a8_bootstrap_seed_determinism() -> AttackResult:
    """Identical seeds must give identical intervals; different seeds must not
    be silently identical (which would mean the seed is ignored)."""
    values = [0.4, -1.0, 2.2, -1.0, 0.9, 3.1, -1.0, 0.2]
    a = bootstrap_expectancy_ci(values, samples=400, seed=7)
    b = bootstrap_expectancy_ci(values, samples=400, seed=7)
    c = bootstrap_expectancy_ci(values, samples=400, seed=8)
    stable = (a.low, a.high) == (b.low, b.high)
    seed_matters = (a.low, a.high) != (c.low, c.high)
    return AttackResult(
        "A8", "bootstrap seed determinism",
        detected=stable and seed_matters, expected_detection=True,
        detail=(f"same seed reproducible={stable}; seed actually used="
                f"{seed_matters}"))


def a9_regime_classifier_future_mutation() -> AttackResult:
    """Prefix invariance: the future must not exist, as far as a label knows.

    The strongest statement of causality available here is that labelling
    the first k observations gives the same answer whether or not
    observations k+1..n were ever supplied. If any later observation can
    reach backwards, some prefix will disagree.

    The fixture is deliberately non-monotonic — a cycling pattern with a
    genuine spread — because a monotonic series makes trailing terciles
    insensitive and would let a leak hide.
    """
    pattern = [0.0010, 0.0035, 0.0007, 0.0021, 0.0052, 0.0013, 0.0008, 0.0044]
    values = [pattern[i % len(pattern)] * (1 + 0.01 * (i % 7))
              for i in range(90)]
    symbols = ["EURUSD"] * 90
    full = label_sequence(list(values), symbols=symbols)

    disagreements = []
    for cut in (35, 50, 70, 89):
        prefix = label_sequence(values[:cut], symbols=symbols[:cut])
        for i in range(cut):
            if prefix[i].cell != full[i].cell:
                disagreements.append((cut, i))
    # A mutation to one observation must still move that observation's own
    # label when the change is large, otherwise the probe is vacuous.
    bumped = list(values)
    bumped[60] = 9.9
    after = label_sequence(bumped, symbols=symbols)
    own_label_responds = after[60].cell != full[60].cell or \
        full[60].volatility.name == "HIGH"

    ok = not disagreements and own_label_responds
    return AttackResult(
        "A9", "regime classifier future mutation (prefix invariance)",
        detected=ok, expected_detection=True,
        detail=(f"prefix invariance held at cuts 35/50/70/89 "
                f"({len(disagreements)} disagreements); probe non-vacuous="
                f"{own_label_responds}"))


def a10_parameter_grid_post_result_mutation() -> AttackResult:
    """Editing the perturbation grid must change the contract hash."""
    frozen = RobustnessContract()
    widened = RobustnessContract(
        parameter_perturbations=(0.5, 0.75, 1.00, 1.25, 1.50))
    changed = frozen.hash() != widened.hash()
    return AttackResult(
        "A10", "parameter-grid post-result mutation",
        detected=changed, expected_detection=True,
        detail=(f"contract hash {'changes' if changed else 'DOES NOT CHANGE'} "
                "when the perturbation grid is edited"))


def a11_fold_overlap() -> AttackResult:
    """Overlapping walk-forward test windows must be rejected."""
    folds = [
        Fold("F1", datetime(2017, 1, 1, tzinfo=UTC), datetime(2017, 3, 1, tzinfo=UTC),
             datetime(2017, 3, 1, tzinfo=UTC), datetime(2017, 5, 1, tzinfo=UTC)),
        Fold("F2", datetime(2017, 1, 1, tzinfo=UTC), datetime(2017, 4, 1, tzinfo=UTC),
             datetime(2017, 4, 1, tzinfo=UTC), datetime(2017, 6, 1, tzinfo=UTC)),
    ]
    try:
        assert_folds_ordered(folds)
        return AttackResult("A11", "walk-forward fold overlap", False, True,
                            "OVERLAPPING FOLDS ACCEPTED")
    except ValueError as exc:
        return AttackResult("A11", "walk-forward fold overlap", True, True,
                            str(exc)[:200])


def run_all(tmp_root) -> dict:
    results = [
        a1_future_bar_mutation(), a2_truncation(), a3_shuffled_future(),
        a4_candidate_id_mutation(), a5_dataset_role_forgery(),
        a6_cas_hash_mismatch(tmp_root), a7_consumed_oos_relabelled_as_dev(),
        a7b_ambiguous_lineage_fails_closed(), a8_bootstrap_seed_determinism(),
        a9_regime_classifier_future_mutation(),
        a10_parameter_grid_post_result_mutation(), a11_fold_overlap(),
    ]
    return {
        "attack_count": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "all_passed": all(r.passed for r in results),
        "attacks": [r.as_dict() for r in results],
    }
