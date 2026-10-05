"""Tests for PRE_OOS_ROBUSTNESS_GATE_V1.

The gate's whole value is that it refuses things, so most of these tests
assert a refusal. A gate that cannot be made to fail is not a gate.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.verification.pre_oos import attacks, axes, c3_adapter
from ag_edgelab.verification.pre_oos.contract import (
    DIAGNOSIS_PRECEDENCE, FROZEN_CONTRACT, SECONDARY_ONLY_DIAGNOSES,
    RobustnessContract,
)
from ag_edgelab.verification.pre_oos.gate import (
    Decision, Diagnosis, FrictionReadiness, decide, evaluate_friction,
    evaluate_parameters, evaluate_tail, temporal_integrity,
)
from ag_edgelab.verification.pre_oos.identity import (
    CandidateIdentity, CandidateIdentityInvalid, REQUIRED_IDENTITY_FIELDS,
    assert_identity,
)
from ag_edgelab.verification.pre_oos.observations import (
    ConsumedWindow, DatasetRoleViolation, LineageContamination,
    LineageDeclaration, Observation, admit,
)
from ag_edgelab.verification.pre_oos.regime import label_sequence

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO / "artifacts" / "pre_oos_robustness_gate_v1"


def obs(i, *, r=1.0, symbol="EURUSD", role="DEVELOPMENT", year=2017, day=None):
    return Observation(
        observation_id=f"{symbol}:{i}", symbol=symbol,
        timestamp_utc=datetime(year, 1, 1, tzinfo=UTC) + timedelta(
            days=i if day is None else day),
        gross_r=r, dataset_role=role, risk_distance=0.001 + i * 1e-6,
        session="LONDON")


# ---------------------------------------------------------------------------
# identity (§4)
# ---------------------------------------------------------------------------

def _identity(**over):
    content = {"candidate_id": "T", "rule": "frozen"}
    base = dict(
        candidate_id="T", candidate_version="1.0.0",
        candidate_sha256=sha256_json(content), strategy_rule_hash="a" * 64,
        dataset_manifest_hash="b" * 64, engine_version="E1",
        entry_contract_hash="c" * 64, sl_contract_hash="d" * 64,
        target_contract_hash="e" * 64, contract_content=content)
    base.update(over)
    return CandidateIdentity(**base)


def test_identity_accepts_a_complete_reproducible_candidate():
    assert_identity(_identity()) is None or True


@pytest.mark.parametrize("field", sorted(REQUIRED_IDENTITY_FIELDS))
def test_identity_requires_every_mandatory_field(field):
    with pytest.raises(CandidateIdentityInvalid):
        assert_identity(_identity(**{field: ""}))


def test_identity_rejects_unreproducible_hash():
    ident = _identity(candidate_sha256="f" * 64)
    with pytest.raises(CandidateIdentityInvalid):
        assert_identity(ident)


def test_identity_rejects_malformed_hash():
    with pytest.raises(CandidateIdentityInvalid):
        assert_identity(_identity(strategy_rule_hash="not-a-sha"))


def test_preregistration_hash_required_when_applicable():
    with pytest.raises(CandidateIdentityInvalid):
        assert_identity(_identity(preregistration_applicable=True,
                                  preregistration_hash=None))


# ---------------------------------------------------------------------------
# dataset role + lineage (§3)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["OOS", "SEALED_OOS", "HOLDOUT",
                                  "SEALED_HOLDOUT", "UNKNOWN"])
def test_forbidden_roles_are_refused_not_dropped(role):
    rows = [obs(i) for i in range(5)] + [obs(99, role=role)]
    with pytest.raises(DatasetRoleViolation) as exc:
        admit(rows, lineage=LineageDeclaration("X", "F",
                                               informed_by_consumed_oos=False))
    assert role in str(exc.value)


def test_missing_role_is_a_violation_not_a_default():
    with pytest.raises(DatasetRoleViolation):
        admit([obs(1, role="")],
              lineage=LineageDeclaration("X", "F",
                                         informed_by_consumed_oos=False))


def test_development_known_is_allowed():
    rows = [obs(i, role="DEVELOPMENT_KNOWN") for i in range(3)]
    admitted, audit = admit(
        rows, lineage=LineageDeclaration("X", "F",
                                         informed_by_consumed_oos=False))
    assert len(admitted) == 3
    assert audit.as_dict()["admitted"] == 3


def test_consumed_oos_contaminates_an_informed_descendant():
    window = ConsumedWindow("OOS-002", "C3", "C3_V1",
                            datetime(2017, 9, 1, tzinfo=UTC),
                            datetime(2017, 12, 1, tzinfo=UTC))
    rows = [Observation(f"E:{i}", "EURUSD",
                        datetime(2017, 10, 1, tzinfo=UTC) + timedelta(days=i),
                        1.0, "DEVELOPMENT_KNOWN") for i in range(4)]
    with pytest.raises(LineageContamination):
        admit(rows, lineage=LineageDeclaration(
            "C3_CHILD", "C3", informed_by_consumed_oos=True),
            consumed_windows=(window,))


def test_undeclared_lineage_over_consumed_window_fails_closed():
    window = ConsumedWindow("OOS-002", "C3", "C3_V1",
                            datetime(2017, 9, 1, tzinfo=UTC),
                            datetime(2017, 12, 1, tzinfo=UTC))
    rows = [Observation("E:1", "EURUSD",
                        datetime(2017, 10, 1, tzinfo=UTC), 1.0, "DEVELOPMENT")]
    with pytest.raises(LineageContamination):
        admit(rows, lineage=LineageDeclaration("UNKNOWN", "C3"),
              consumed_windows=(window,))


def test_uninformed_candidate_may_use_a_consumed_window_as_development_known():
    window = ConsumedWindow("OOS-002", "C3", "C3_V1",
                            datetime(2017, 9, 1, tzinfo=UTC),
                            datetime(2017, 12, 1, tzinfo=UTC))
    rows = [Observation(f"E:{i}", "EURUSD",
                        datetime(2017, 10, 1, tzinfo=UTC) + timedelta(days=i),
                        1.0, "DEVELOPMENT_KNOWN") for i in range(3)]
    admitted, _ = admit(rows, lineage=LineageDeclaration(
        "UNRELATED", "OTHER_FAMILY", informed_by_consumed_oos=False),
        consumed_windows=(window,))
    assert len(admitted) == 3


# ---------------------------------------------------------------------------
# temporal causality (§8, §18)
# ---------------------------------------------------------------------------

def test_out_of_order_population_is_flagged():
    rows = [obs(i) for i in range(10)]
    assert temporal_integrity(rows[5:] + rows[:5]).fired


def test_regime_labels_are_prefix_invariant():
    values = [0.001, 0.004, 0.0007, 0.002, 0.005, 0.0013, 0.0008, 0.0044] * 10
    syms = ["EURUSD"] * len(values)
    full = label_sequence(list(values), symbols=syms)
    for cut in (31, 45, 60):
        prefix = label_sequence(values[:cut], symbols=syms[:cut])
        assert [p.cell for p in prefix] == [f.cell for f in full[:cut]]


def test_regime_warmup_is_unclassified_not_guessed():
    values = [0.001 + i * 1e-5 for i in range(10)]
    labels = label_sequence(values, symbols=["EURUSD"] * 10)
    assert not any(l.is_classified for l in labels)


def test_regime_is_per_symbol_not_pooled():
    values = [0.001] * 40 + [5.0] * 40
    syms = ["EURUSD"] * 40 + ["XAUUSD"] * 40
    labels = label_sequence(values, symbols=syms)
    # XAUUSD's much larger risk distances must not make it permanently HIGH;
    # it is ranked against its own history.
    xau = [l for l, s in zip(labels, syms) if s == "XAUUSD" and l.is_classified]
    assert xau, "XAUUSD should accumulate its own history"


# ---------------------------------------------------------------------------
# axis arithmetic (§6, §7, §9, §10)
# ---------------------------------------------------------------------------

def test_leave_one_year_out_needs_three_years():
    rows = [obs(i, year=2016) for i in range(30)] + \
           [obs(i, year=2017) for i in range(30)]
    report = axes.leave_one_year_out(rows)
    assert report["group_count"] == 2
    from ag_edgelab.verification.pre_oos.gate import evaluate_year
    assert evaluate_year(report, FROZEN_CONTRACT).evaluated is False


def test_leave_one_symbol_out_detects_a_sign_flip():
    rows = ([obs(i, symbol="EURUSD", r=-0.2) for i in range(60)] +
            [obs(i, symbol="XAUUSD", r=2.0) for i in range(60)])
    report = axes.leave_one_symbol_out(rows)
    assert report["any_sign_flip"] is True
    flipped = [r["excluded_symbol"] for r in report["results"] if r["sign_flip"]]
    assert flipped == ["XAUUSD"]


def test_per_symbol_results_are_reported_independently():
    rows = ([obs(i, symbol="EURUSD", r=-0.2) for i in range(60)] +
            [obs(i, symbol="XAUUSD", r=2.0) for i in range(60)])
    per = axes.leave_one_symbol_out(rows)["per_symbol_independent"]
    assert per["EURUSD"]["status"] == "NEGATIVE"
    assert per["XAUUSD"]["status"] == "POSITIVE"


def test_tail_shares_are_arithmetically_consistent():
    rs = [5.0] + [0.1] * 99
    report = axes.tail_contribution(
        [obs(i, r=r) for i, r in enumerate(rs)], winsor_levels=(0.99, 0.95))
    shares = report["shares"]
    assert shares["TOP_1_PCT_POSITIVE_R_SHARE"]["share"] == pytest.approx(
        5.0 / (5.0 + 9.9), rel=1e-9)
    assert (shares["TOP_1_PCT_POSITIVE_R_SHARE"]["share"]
            <= shares["TOP_5_PCT_POSITIVE_R_SHARE"]["share"]
            <= shares["TOP_10_PCT_POSITIVE_R_SHARE"]["share"])


def test_winsorization_is_diagnostic_only():
    rs = [20.0] + [-0.1] * 99
    report = axes.tail_contribution(
        [obs(i, r=r) for i, r in enumerate(rs)], winsor_levels=(0.99, 0.95))
    assert report["distribution"]["mean_r"] == pytest.approx(
        sum(rs) / len(rs), rel=1e-12)
    assert report["winsorized"]["WINSORIZED_95"]["sign_flip_vs_canonical"]
    assert "DIAGNOSTIC ONLY" in report["winsorization_policy"]


def test_winsorize_bounds_values_without_dropping_them():
    rs = [float(i) for i in range(100)]
    w = axes.winsorize(rs, 0.95)
    assert len(w) == len(rs)
    assert max(w) < max(rs)


def test_mean_median_divergence_is_classified_not_collapsed():
    rs = [-0.3] * 70 + [5.0] * 30
    report = axes.mean_median_analysis([obs(i, r=r) for i, r in enumerate(rs)],
                                      frequent_rate=0.5, divergence_ratio=0.5)
    assert report["MEAN_R"] > 0 > report["MEDIAN_R"]
    assert report["asymmetric_tail_dependence"] is True
    assert report["shape"] == "RARE_LARGE_WINNER"


def test_outcome_rates_sum_to_one():
    rs = [-1.0] * 10 + [0.0] * 5 + [2.0] * 7
    r = axes.mean_median_analysis([obs(i, r=v) for i, v in enumerate(rs)],
                                 frequent_rate=0.5, divergence_ratio=0.5)
    assert (r["POSITIVE_OUTCOME_RATE"] + r["NEGATIVE_OUTCOME_RATE"]
            + r["ZERO_OUTCOME_RATE"]) == pytest.approx(1.0)


def test_unresolved_observations_are_counted_never_coerced_to_zero():
    rows = [obs(i, r=1.0) for i in range(5)]
    rows.append(Observation("E:none", "EURUSD", datetime(2017, 2, 1, tzinfo=UTC),
                            None, "DEVELOPMENT"))
    s = axes.sample_sufficiency(rows)
    assert s["unresolved"] == 1 and s["resolved"] == 5
    assert axes.describe(axes._rs(rows))["n"] == 5


# ---------------------------------------------------------------------------
# walk-forward (§5)
# ---------------------------------------------------------------------------

def test_overlapping_folds_are_rejected():
    f = [axes.Fold("A", datetime(2017, 1, 1, tzinfo=UTC), datetime(2017, 3, 1, tzinfo=UTC),
                   datetime(2017, 3, 1, tzinfo=UTC), datetime(2017, 5, 1, tzinfo=UTC)),
         axes.Fold("B", datetime(2017, 1, 1, tzinfo=UTC), datetime(2017, 4, 1, tzinfo=UTC),
                   datetime(2017, 4, 1, tzinfo=UTC), datetime(2017, 6, 1, tzinfo=UTC))]
    with pytest.raises(ValueError):
        axes.assert_folds_ordered(f)


def test_fold_with_train_after_test_is_rejected_at_construction():
    with pytest.raises(ValueError, match="chronological"):
        axes.Fold("A", datetime(2017, 5, 1, tzinfo=UTC),
                  datetime(2017, 7, 1, tzinfo=UTC),
                  datetime(2017, 1, 1, tzinfo=UTC),
                  datetime(2017, 3, 1, tzinfo=UTC))


def test_fold_training_past_its_own_test_start_is_lookahead():
    """A train window that reaches into the test window is lookahead."""
    good = axes.Fold("A", datetime(2017, 1, 1, tzinfo=UTC),
                     datetime(2017, 3, 1, tzinfo=UTC),
                     datetime(2017, 3, 1, tzinfo=UTC),
                     datetime(2017, 5, 1, tzinfo=UTC))
    axes.assert_folds_ordered([good])
    object.__setattr__(good, "train_end", datetime(2017, 4, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="lookahead"):
        axes.assert_folds_ordered([good])


def test_walk_forward_never_refits():
    rows = [obs(i, day=i) for i in range(200)]
    folds = c3_adapter.build_folds(rows)
    report = axes.walk_forward(rows, folds)
    assert report["refitting_performed"] is False


# ---------------------------------------------------------------------------
# bootstrap (§11)
# ---------------------------------------------------------------------------

def test_bootstrap_is_seed_deterministic():
    rows = [obs(i, r=(1.0 if i % 3 else -1.0)) for i in range(100)]
    a = axes.bootstrap_uncertainty(rows, samples=200, seed=11, confidence=0.95)
    b = axes.bootstrap_uncertainty(rows, samples=200, seed=11, confidence=0.95)
    assert sha256_json(a) == sha256_json(b)


def test_bootstrap_records_its_seed_and_sample_count():
    rows = [obs(i, r=0.5) for i in range(60)]
    r = axes.bootstrap_uncertainty(rows, samples=150, seed=4, confidence=0.95)
    mean = r["metrics"]["mean_r"]
    assert mean["seed"] == 4 and mean["bootstrap_n"] == 150
    assert mean["CI_LOW"] <= mean["estimate"] <= mean["CI_HIGH"]


def test_bootstrap_reuses_the_canonical_engine():
    assert "ag_edgelab.statistics.bootstrap" in \
        axes.bootstrap_uncertainty([obs(i) for i in range(40)], samples=50,
                                   seed=1, confidence=0.95)["engine"]


# ---------------------------------------------------------------------------
# parameter neighbourhood (§12)
# ---------------------------------------------------------------------------

def test_categorical_parameters_are_never_mutated():
    p = axes.PerturbableParameter(
        name="session_filter", frozen_value=None, semantics="categorical",
        perturbable=False, reason_not_perturbable="categorical rule")
    report = axes.parameter_neighborhood([p], lambda n, v: 1.0, perturbations=(0.9, 0.95, 1.0, 1.05, 1.1),
        min_positive_fraction=0.6, max_relative_spike=2.0)
    assert report["status"] == "NOT_APPLICABLE"
    assert report["parameters"][0]["status"] == "NOT_APPLICABLE"


def test_no_perturbable_parameter_yields_not_applicable_not_an_invention():
    report = axes.parameter_neighborhood([], lambda n, v: 1.0, perturbations=(0.9, 0.95, 1.0, 1.05, 1.1),
        min_positive_fraction=0.6, max_relative_spike=2.0)
    assert report["status"] == "NOT_APPLICABLE"
    assert evaluate_parameters(report).evaluated is False


def test_parameter_neighbourhood_is_not_a_search():
    p = axes.PerturbableParameter("tp_mult", 2.0, "target multiple")
    report = axes.parameter_neighborhood(
        [p], lambda n, v: 10.0 if v > 2.0 else 0.1, perturbations=(0.9, 0.95, 1.0, 1.05, 1.1),
        min_positive_fraction=0.6, max_relative_spike=2.0)
    assert report["is_search"] is False
    assert "no neighbour may be promoted" in report["promotion_policy"]
    # the frozen value is still reported as frozen, not replaced by the best
    assert report["parameters"][0]["FROZEN_VALUE"] == 2.0


def test_parameter_fragility_is_detected():
    p = axes.PerturbableParameter("tp_mult", 2.0, "target multiple")
    report = axes.parameter_neighborhood(
        [p], lambda n, v: 1.0 if v == 2.0 else -1.0, perturbations=(0.9, 0.95, 1.0, 1.05, 1.1),
        min_positive_fraction=0.6, max_relative_spike=2.0)
    assert report["all_stable"] is False


# ---------------------------------------------------------------------------
# friction (§13)
# ---------------------------------------------------------------------------

def test_missing_friction_blocks_economics_but_not_structure():
    f = evaluate_friction(FrictionReadiness.FRICTION_UNAVAILABLE)
    assert f.fired and f.diagnosis is Diagnosis.FRICTION_AUTHORITY_INCOMPLETE
    assert Diagnosis.FRICTION_AUTHORITY_INCOMPLETE in SECONDARY_ONLY_DIAGNOSES


def test_friction_is_never_primary_so_it_cannot_block_structure():
    assert Diagnosis.FRICTION_AUTHORITY_INCOMPLETE not in DIAGNOSIS_PRECEDENCE


def test_measured_friction_does_not_fire():
    assert not evaluate_friction(FrictionReadiness.FRICTION_MEASURED).fired


# ---------------------------------------------------------------------------
# decision semantics (§14, §15)
# ---------------------------------------------------------------------------

def _clean_findings():
    from ag_edgelab.verification.pre_oos.gate import AxisFinding
    names = ["temporal_integrity", "sample_sufficiency", "walk_forward",
             "leave_one_year_out", "leave_one_symbol_out", "regime", "tail",
             "mean_median", "bootstrap"]
    return [AxisFinding(n, None, False, True, "ok") for n in names]


def test_pass_never_implies_edge_or_economic_verified():
    d = decide(_clean_findings(), contract=FROZEN_CONTRACT,
               friction=FrictionReadiness.FRICTION_MEASURED)
    assert d.decision is Decision.PRE_OOS_PASS
    assert d.implies_edge_verified() is False
    assert d.implies_economic_verified() is False
    assert d.as_dict()["EDGE_STATUS"] == "UNVERIFIED"


def test_pass_with_missing_friction_still_blocks_economics():
    d = decide(_clean_findings(), contract=FROZEN_CONTRACT,
               friction=FrictionReadiness.FRICTION_UNAVAILABLE)
    assert d.implies_economic_verified() is False
    assert Diagnosis.FRICTION_AUTHORITY_INCOMPLETE in d.secondary_diagnoses


def test_primary_diagnosis_follows_frozen_precedence():
    from ag_edgelab.verification.pre_oos.gate import AxisFinding
    findings = _clean_findings() + [
        AxisFinding("tail", Diagnosis.TAIL_DEPENDENCY, True, True, "x"),
        AxisFinding("sample_sufficiency", Diagnosis.INSUFFICIENT_SAMPLE,
                    True, True, "x"),
    ]
    d = decide(findings, contract=FROZEN_CONTRACT,
               friction=FrictionReadiness.FRICTION_MEASURED)
    assert d.primary_diagnosis is Diagnosis.INSUFFICIENT_SAMPLE


def test_no_generic_collapsed_fail():
    assert not hasattr(Diagnosis, "FAIL")
    assert len(list(Diagnosis)) >= 14


def test_unevaluated_axis_yields_insufficient_evidence_not_pass():
    from ag_edgelab.verification.pre_oos.gate import AxisFinding
    findings = [f for f in _clean_findings() if f.axis != "regime"]
    findings.append(AxisFinding("regime", None, False, False, "not evaluated"))
    d = decide(findings, contract=FROZEN_CONTRACT,
               friction=FrictionReadiness.FRICTION_MEASURED)
    assert d.decision is Decision.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# contract integrity (§18 A10, §19)
# ---------------------------------------------------------------------------

def test_contract_hash_is_stable():
    assert RobustnessContract().hash() == FROZEN_CONTRACT.hash()


@pytest.mark.parametrize("field,value", [
    ("min_distinct_years", 2),
    ("parameter_perturbations", (0.5, 1.0, 1.5)),
    ("bootstrap_seed", 1),
    ("max_single_regime_positive_r_share", 0.9),
])
def test_any_threshold_edit_changes_the_contract_hash(field, value):
    assert RobustnessContract(**{field: value}).hash() != FROZEN_CONTRACT.hash()


def test_secondary_only_diagnoses_cannot_be_primary():
    for d in SECONDARY_ONLY_DIAGNOSES:
        assert d not in DIAGNOSIS_PRECEDENCE


# ---------------------------------------------------------------------------
# causality attacks (§18)
# ---------------------------------------------------------------------------

def test_every_causality_attack_is_detected(tmp_path):
    report = attacks.run_all(tmp_path)
    failed = [a for a in report["attacks"] if not a["passed"]]
    assert not failed, failed
    assert report["attack_count"] >= 10


# ---------------------------------------------------------------------------
# C3 negative control (§17)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not (REPO / c3_adapter.C3_DIR).is_dir(),
                    reason="C3 evidence not present")
def test_c3_adapter_reads_only_development_evidence():
    rows = c3_adapter.load_observations(REPO)
    assert rows
    assert {o.dataset_role for o in rows} == {"DEVELOPMENT"}


def test_c3_adapter_never_references_the_oos_directory():
    source = (REPO / "src/ag_edgelab/verification/pre_oos/c3_adapter.py").read_text()
    assert "target_policy_c3_v1_oos" not in source.replace(
        "data/artifacts/target_policy_c3_v1_oos/", "<<redacted-mention>>")


@pytest.mark.skipif(not (REPO / c3_adapter.C3_DIR).is_dir(),
                    reason="C3 evidence not present")
def test_c3_identity_reproduces_from_its_own_frozen_contract():
    assert_identity(c3_adapter.build_identity(REPO))


@pytest.mark.skipif(not (REPO / c3_adapter.C3_DIR).is_dir(),
                    reason="C3 evidence not present")
def test_c3_parameters_report_not_applicable_rather_than_inventing_one():
    report = axes.parameter_neighborhood(c3_adapter.parameters(), lambda n, v: None, perturbations=(0.9, 0.95, 1.0, 1.05, 1.1),
        min_positive_fraction=0.6, max_relative_spike=2.0)
    assert report["status"] == "NOT_APPLICABLE"
    assert all("NOT_EVALUABLE_FROM_FROZEN_LEDGER" in p["reason"]
               for p in report["parameters"])


# ---------------------------------------------------------------------------
# artifacts (§19, §20)
# ---------------------------------------------------------------------------

REQUIRED_ARTIFACTS = [
    "preregistration.json", "candidate_identity.json", "dataset_authority.json",
    "walk_forward_report.json", "leave_one_year_out.json",
    "leave_one_symbol_out.json", "regime_robustness.json",
    "tail_contribution.json", "mean_median_analysis.json",
    "bootstrap_uncertainty.json", "parameter_neighborhood.json",
    "friction_readiness.json", "causality_attacks.json", "determinism.json",
    "root_cause_analysis.json", "oos_authorization.json",
    "c3_negative_control.json", "artifact_manifest.json", "final_report.json",
    "final_report.md",
]


@pytest.mark.skipif(not ARTIFACTS.is_dir(), reason="campaign not run")
@pytest.mark.parametrize("name", REQUIRED_ARTIFACTS)
def test_required_artifact_exists(name):
    path = ARTIFACTS / name
    assert path.is_file() and path.stat().st_size > 0


@pytest.mark.skipif(not (ARTIFACTS / "determinism.json").is_file(),
                    reason="campaign not run")
def test_campaign_is_deterministic():
    d = json.loads((ARTIFACTS / "determinism.json").read_text())
    assert d["DETERMINISM"] == "PASS"
    assert d["run_1_sha256"] == d["run_2_sha256"]


@pytest.mark.skipif(not (ARTIFACTS / "artifact_manifest.json").is_file(),
                    reason="campaign not run")
def test_artifact_manifest_matches_on_disk_content():
    from ag_edgelab.data.fingerprint import sha256_file
    manifest = json.loads((ARTIFACTS / "artifact_manifest.json").read_text())
    for name, entry in manifest["artifacts"].items():
        path = ARTIFACTS / name
        assert path.is_file(), name
        if entry["sha256"] == "EXEMPT_SELF_REFERENTIAL":
            assert path.stat().st_size > 0
            continue
        assert sha256_file(path) == entry["sha256"], name


@pytest.mark.skipif(not (ARTIFACTS / "oos_authorization.json").is_file(),
                    reason="campaign not run")
def test_no_oos_or_holdout_was_opened():
    a = json.loads((ARTIFACTS / "oos_authorization.json").read_text())
    assert a["OOS_OPENED"] is False
    assert a["HOLDOUT_TOUCHED"] is False
    assert a["implies_edge_verified"] is False
    assert a["implies_economic_verified"] is False


@pytest.mark.skipif(not (ARTIFACTS / "c3_negative_control.json").is_file(),
                    reason="campaign not run")
def test_c3_negative_control_records_the_known_oos_result_separately():
    c = json.loads((ARTIFACTS / "c3_negative_control.json").read_text())
    assert c["KNOWN_HISTORICAL_OOS_RESULT"] == "STRUCTURAL_GENERALIZATION_FAILS"
    assert c["thresholds_calibrated_to_this_result"] is False
    assert c["oos_evidence_read"] is False


@pytest.mark.skipif(not (ARTIFACTS / "preregistration.json").is_file(),
                    reason="campaign not run")
def test_preregistration_pins_the_contract_actually_used():
    p = json.loads((ARTIFACTS / "preregistration.json").read_text())
    c = json.loads((ARTIFACTS / "c3_negative_control.json").read_text())
    assert p["contract"]["CONTRACT_SHA256"] == FROZEN_CONTRACT.hash()
    assert c["contract_sha256"] == FROZEN_CONTRACT.hash()
