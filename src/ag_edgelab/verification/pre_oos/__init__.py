"""PRE_OOS_ROBUSTNESS_GATE_V1.

EdgeLab already answers "does this look good on DEV?". This package adds
the question that TARGET_POLICY_C3_V1 showed was missing: *is that DEV
result distributed, stable and reproducible enough that spending a fresh
OOS window on it is justified?*

A fresh OOS window is a non-renewable resource. Once it is read, its
verdict has informed the researcher and it can never again be fresh for
any descendant candidate. The gate exists so that windows are spent on
candidates whose development evidence could plausibly survive, rather
than on candidates whose apparent edge lives in one year, one symbol,
one regime, or forty lucky runners.

The gate never inspects OOS or holdout data to make its decision, and
``PRE_OOS_PASS`` is permission to run one test — never a claim that a
candidate is profitable, economically verified, or an edge.
"""

from ag_edgelab.verification.pre_oos.axes import (
    CAPABILITY_LEVELS, Fold, PerturbableParameter, assert_folds_ordered,
    bootstrap_uncertainty, capability, describe, leave_one_symbol_out,
    leave_one_year_out, mean_median_analysis, parameter_neighborhood,
    regime_robustness, sample_sufficiency, tail_contribution, walk_forward,
    winsorize,
)
from ag_edgelab.verification.pre_oos.contract import (
    CONTRACT_ID, DIAGNOSIS_PRECEDENCE, FROZEN_CONTRACT, GATE_ID,
    SECONDARY_ONLY_DIAGNOSES, RobustnessContract, ThresholdProvenance,
)
from ag_edgelab.verification.pre_oos.gate import (
    ECONOMIC_VERDICT_NO_FRICTION, EDGE_STATUS_UNVERIFIED, AxisFinding,
    Decision, Diagnosis, FrictionReadiness, GateDecision, decide,
    temporal_integrity,
)
from ag_edgelab.verification.pre_oos.identity import (
    CandidateIdentity, CandidateIdentityInvalid, REQUIRED_IDENTITY_FIELDS,
    assert_identity,
)
from ag_edgelab.verification.pre_oos.observations import (
    ALLOWED_ROLES, FORBIDDEN_ROLES, ConsumedWindow, DatasetRoleViolation,
    EvidenceRole, LineageContamination, LineageDeclaration, Observation,
    RoleAudit, admit, resolved_r,
)
from ag_edgelab.verification.pre_oos.regime import (
    MIN_HISTORY, REGIME_CLASSIFIER_ID, TRAILING_WINDOW, RegimeLabel,
    TrendState, Volatility, classifier_fingerprint, classify_trend,
    classify_volatility, label_sequence,
)
from ag_edgelab.verification.pre_oos.runner import RobustnessRun, run_gate

__all__ = [
    "CAPABILITY_LEVELS", "Fold", "PerturbableParameter", "assert_folds_ordered",
    "bootstrap_uncertainty", "capability", "describe", "leave_one_symbol_out",
    "leave_one_year_out", "mean_median_analysis", "parameter_neighborhood",
    "regime_robustness", "sample_sufficiency", "tail_contribution",
    "walk_forward", "winsorize",
    "CONTRACT_ID", "DIAGNOSIS_PRECEDENCE", "FROZEN_CONTRACT", "GATE_ID",
    "SECONDARY_ONLY_DIAGNOSES", "RobustnessContract", "ThresholdProvenance",
    "ECONOMIC_VERDICT_NO_FRICTION", "EDGE_STATUS_UNVERIFIED", "AxisFinding",
    "Decision", "Diagnosis", "FrictionReadiness", "GateDecision", "decide",
    "temporal_integrity",
    "CandidateIdentity", "CandidateIdentityInvalid", "REQUIRED_IDENTITY_FIELDS",
    "assert_identity",
    "ALLOWED_ROLES", "FORBIDDEN_ROLES", "ConsumedWindow",
    "DatasetRoleViolation", "EvidenceRole", "LineageContamination",
    "LineageDeclaration", "Observation", "RoleAudit", "admit", "resolved_r",
    "MIN_HISTORY", "REGIME_CLASSIFIER_ID", "TRAILING_WINDOW", "RegimeLabel",
    "TrendState", "Volatility", "classifier_fingerprint", "classify_trend",
    "classify_volatility", "label_sequence",
    "RobustnessRun", "run_gate",
]
