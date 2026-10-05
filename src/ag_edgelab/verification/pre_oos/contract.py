"""PRE_OOS_ROBUSTNESS_CONTRACT_V1 — thresholds frozen before any candidate runs.

A threshold chosen after seeing the result is not a threshold, it is a
rationalisation. Every number in this module is fixed here, hashed, and
written to ``preregistration.json`` before the gate touches candidate
evidence. Changing any of them changes ``CONTRACT_SHA256``, so a
post-hoc adjustment is visible in the diff and in the artifact.

PROVENANCE OF EACH THRESHOLD
----------------------------
Thresholds come from one of three places, recorded per-threshold in
``RATIONALE`` below:

* **STRUCTURAL** — forced by the arithmetic of the test itself. The
  leave-one-year-out minimum is the clearest case: with two years,
  removing one leaves a single year and "leave one out" is no longer a
  test, it is just the other year. Three is the smallest number at which
  the question is meaningful.
* **REPOSITORY_AUTHORITY** — already frozen elsewhere in this codebase
  and reused rather than re-invented, so the gate stays consistent with
  decisions the project already made.
* **CONSERVATIVE_DEFAULT** — a declared judgement call, set to the
  stricter side, stated plainly as a judgement rather than dressed up as
  a derivation.

WHAT THESE THRESHOLDS ARE NOT
-----------------------------
They were not calibrated against TARGET_POLICY_C3_V1's known OOS
failure. The C3 negative control in section 17 of the mission is run
*after* this contract is frozen and its hash recorded, and the contract
is not amended afterwards regardless of whether the gate's verdict
agrees with history. Agreement would be mild evidence the gate works;
disagreement is reported as-is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.universal.matrix import MIN_COMPARABLE_SAMPLE

CONTRACT_ID = "PRE_OOS_ROBUSTNESS_CONTRACT_V1"
GATE_ID = "PRE_OOS_ROBUSTNESS_GATE_V1"


class ThresholdProvenance(StrEnum):
    STRUCTURAL = "STRUCTURAL"
    REPOSITORY_AUTHORITY = "REPOSITORY_AUTHORITY"
    CONSERVATIVE_DEFAULT = "CONSERVATIVE_DEFAULT"


# ---------------------------------------------------------------------------
# sample sufficiency
# ---------------------------------------------------------------------------

#: Minimum resolved observations pooled across all symbols.
MIN_POOLED_OBSERVATIONS = 200

#: Minimum resolved observations for a symbol to carry independent weight.
MIN_OBSERVATIONS_PER_SYMBOL = MIN_COMPARABLE_SAMPLE

#: Minimum observations in a walk-forward fold for that fold to count.
MIN_OBSERVATIONS_PER_FOLD = MIN_COMPARABLE_SAMPLE

#: Minimum observations in a calendar year for that year to count.
MIN_OBSERVATIONS_PER_YEAR = MIN_COMPARABLE_SAMPLE

#: Minimum observations in a regime cell for that cell to count.
MIN_OBSERVATIONS_PER_REGIME = MIN_COMPARABLE_SAMPLE

#: Leave-one-year-out is undefined below three distinct years: with two,
#: removing one leaves a single year and the "test" is a tautology.
MIN_DISTINCT_YEARS = 3

#: Leave-one-symbol-out needs at least two symbols to remove one.
MIN_DISTINCT_SYMBOLS = 2

#: Walk-forward needs enough folds for a stability fraction to mean
#: anything. Below this, one fold moves the fraction by >20pp.
MIN_WALK_FORWARD_FOLDS = 5


# ---------------------------------------------------------------------------
# stability
# ---------------------------------------------------------------------------

#: Share of walk-forward folds whose metric must be positive. Reused from
#: ag_edgelab.optimization.stability.assess_parameter_stability, which
#: already fixed 0.60 as this project's "mostly holds" bar.
MIN_POSITIVE_FOLD_FRACTION = 0.60

#: Same bar applied to the year and symbol axes.
MIN_POSITIVE_YEAR_FRACTION = 0.60
MIN_POSITIVE_SYMBOL_FRACTION = 0.60

#: A leave-one-out delta larger than this share of the baseline means the
#: removed slice was carrying the result rather than contributing to it.
MAX_LEAVE_ONE_OUT_RELATIVE_DELTA = 0.50

#: Removing one slice must never flip the sign of the metric.
LEAVE_ONE_OUT_SIGN_FLIP_IS_DEPENDENCY = True


# ---------------------------------------------------------------------------
# regime
# ---------------------------------------------------------------------------

#: If one regime cell holds this share or more of all positive gross R,
#: the claimed effect lives in that regime rather than across regimes.
MAX_SINGLE_REGIME_POSITIVE_R_SHARE = 0.70

#: Share of qualifying regime cells that must show a positive metric.
MIN_POSITIVE_REGIME_FRACTION = 0.50


# ---------------------------------------------------------------------------
# tail concentration
# ---------------------------------------------------------------------------

#: Shares of total POSITIVE gross R attributable to the largest outcomes.
#: A handful of runners carrying half the upside is the exact failure
#: mode that produced a positive C3 DEV mean with a near-zero median.
MAX_TOP_1_PCT_POSITIVE_R_SHARE = 0.25
MAX_TOP_5_PCT_POSITIVE_R_SHARE = 0.50
MAX_TOP_10_PCT_POSITIVE_R_SHARE = 0.65

#: If clipping the distribution at its own 95th/99th percentile flips the
#: sign of the mean, the result is an artefact of a few observations.
WINSOR_SIGN_FLIP_IS_TAIL_DEPENDENCY = True

#: Winsorization levels computed as DIAGNOSTICS. The canonical metric is
#: never replaced by a winsorized one.
WINSOR_LEVELS: tuple[float, ...] = (0.99, 0.95)


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------

#: Resamples. 5000 matches the default already used by
#: ag_edgelab.statistics.bootstrap.bootstrap_expectancy_ci.
BOOTSTRAP_SAMPLES = 5000

#: Fixed seed, recorded in artifacts; determinism is asserted by test.
BOOTSTRAP_SEED = 20251005

BOOTSTRAP_CONFIDENCE = 0.95

#: The floor the lower confidence bound must clear. Structural mean R
#: must be positive to justify spending an OOS window; a CI that includes
#: zero means the DEV evidence cannot distinguish the candidate from
#: noise, whatever its point estimate.
MEAN_R_REQUIRED_FLOOR = 0.0


# ---------------------------------------------------------------------------
# parameter neighborhood
# ---------------------------------------------------------------------------

#: Multiplicative perturbations applied to numeric, semantically
#: continuous frozen parameters. This is a FRAGILITY probe, not a search:
#: the frozen value is never replaced by a better-scoring neighbour, and
#: no neighbour is ever promoted.
PARAMETER_PERTURBATIONS: tuple[float, ...] = (0.90, 0.95, 1.00, 1.05, 1.10)

#: Reused verbatim from ag_edgelab.optimization.stability.
MIN_POSITIVE_NEIGHBOR_FRACTION = 0.60
MAX_RELATIVE_SPIKE = 2.0


# ---------------------------------------------------------------------------
# distribution shape
# ---------------------------------------------------------------------------

#: Outcome rate above which wins are "frequent".
FREQUENT_OUTCOME_RATE = 0.50

#: |mean - median| above this share of |mean| marks the mean as
#: tail-driven rather than representative.
MEAN_MEDIAN_DIVERGENCE_RATIO = 0.50


#: Deterministic precedence for the PRIMARY diagnosis when several fire.
#: Authority failures come first because they invalidate everything
#: downstream: there is no point reporting tail concentration for a
#: population whose dataset roles cannot be trusted. Within the
#: robustness failures the order runs broadest-scope to narrowest, so the
#: headline names the most general thing that is wrong.
#:
#: ASYMMETRIC_TAIL_DEPENDENCE and FRICTION_AUTHORITY_INCOMPLETE are
#: deliberately absent: the mission classifies the first as "not
#: automatically failure" and the second must never block STRUCTURAL
#: analysis. Both can only ever appear as secondary diagnoses.
DIAGNOSIS_PRECEDENCE: tuple[str, ...] = (
    "CANDIDATE_IDENTITY_INVALID",
    "DATASET_ROLE_VIOLATION",
    "TEMPORAL_CAUSALITY_FAILURE",
    "INSUFFICIENT_SAMPLE",
    "WALK_FORWARD_INSTABILITY",
    "YEAR_DEPENDENCY",
    "SYMBOL_DEPENDENCY",
    "REGIME_DEPENDENCY",
    "TAIL_DEPENDENCY",
    "STATISTICAL_UNCERTAINTY",
    "PARAMETER_FRAGILITY",
)

#: Diagnoses that may only ever be secondary.
SECONDARY_ONLY_DIAGNOSES: tuple[str, ...] = (
    "ASYMMETRIC_TAIL_DEPENDENCE",
    "FRICTION_AUTHORITY_INCOMPLETE",
)


RATIONALE: dict[str, dict[str, object]] = {
    "MIN_POOLED_OBSERVATIONS": {
        "value": MIN_POOLED_OBSERVATIONS,
        "provenance": ThresholdProvenance.CONSERVATIVE_DEFAULT,
        "why": ("Below a few hundred resolved outcomes, per-year and "
                "per-regime slices fall under the comparability minimum and "
                "every downstream axis degrades to INSUFFICIENT_SAMPLE."),
    },
    "MIN_OBSERVATIONS_PER_SYMBOL": {
        "value": MIN_OBSERVATIONS_PER_SYMBOL,
        "provenance": ThresholdProvenance.REPOSITORY_AUTHORITY,
        "why": "ag_edgelab.universal.matrix.MIN_COMPARABLE_SAMPLE.",
    },
    "MIN_DISTINCT_YEARS": {
        "value": MIN_DISTINCT_YEARS,
        "provenance": ThresholdProvenance.STRUCTURAL,
        "why": ("Leave-one-year-out requires at least three years to be a "
                "test. With two, removing one leaves a single year and the "
                "comparison is tautological; with one, the test is undefined. "
                "This follows from the construction of the test and not from "
                "any candidate's results."),
    },
    "MIN_DISTINCT_SYMBOLS": {
        "value": MIN_DISTINCT_SYMBOLS,
        "provenance": ThresholdProvenance.STRUCTURAL,
        "why": "Removing one symbol requires at least two to exist.",
    },
    "MIN_WALK_FORWARD_FOLDS": {
        "value": MIN_WALK_FORWARD_FOLDS,
        "provenance": ThresholdProvenance.CONSERVATIVE_DEFAULT,
        "why": ("With fewer than five folds a single fold moves the positive "
                "fraction by more than 20 percentage points, so the stability "
                "fraction is not informative."),
    },
    "MIN_POSITIVE_FOLD_FRACTION": {
        "value": MIN_POSITIVE_FOLD_FRACTION,
        "provenance": ThresholdProvenance.REPOSITORY_AUTHORITY,
        "why": ("ag_edgelab.optimization.stability.assess_parameter_stability "
                "min_positive_fraction=0.6, reused so the gate agrees with the "
                "project's existing definition of 'mostly holds'."),
    },
    "MAX_LEAVE_ONE_OUT_RELATIVE_DELTA": {
        "value": MAX_LEAVE_ONE_OUT_RELATIVE_DELTA,
        "provenance": ThresholdProvenance.CONSERVATIVE_DEFAULT,
        "why": ("If removing one year or symbol moves the pooled metric by "
                "more than half, that slice was carrying the result."),
    },
    "MAX_SINGLE_REGIME_POSITIVE_R_SHARE": {
        "value": MAX_SINGLE_REGIME_POSITIVE_R_SHARE,
        "provenance": ThresholdProvenance.CONSERVATIVE_DEFAULT,
        "why": ("A regime holding 70%+ of all positive R is where the effect "
                "lives; the pooled number is then a statement about that "
                "regime wearing a pooled label."),
    },
    "MAX_TOP_5_PCT_POSITIVE_R_SHARE": {
        "value": MAX_TOP_5_PCT_POSITIVE_R_SHARE,
        "provenance": ThresholdProvenance.CONSERVATIVE_DEFAULT,
        "why": ("Five percent of outcomes producing half the upside means an "
                "OOS window containing none of them shows nothing. This is "
                "the documented C3 DEV failure shape — positive mean, median "
                "paired delta near zero — and the reason this axis is "
                "mandatory."),
    },
    "BOOTSTRAP_SEED": {
        "value": BOOTSTRAP_SEED,
        "provenance": ThresholdProvenance.CONSERVATIVE_DEFAULT,
        "why": ("Arbitrary but fixed and recorded; determinism is asserted by "
                "regression test, and no metric used in authorization may "
                "vary with it."),
    },
    "MEAN_R_REQUIRED_FLOOR": {
        "value": MEAN_R_REQUIRED_FLOOR,
        "provenance": ThresholdProvenance.STRUCTURAL,
        "why": ("A lower confidence bound at or below zero means the DEV "
                "evidence cannot distinguish the candidate from no effect, "
                "whatever the point estimate."),
    },
    "PARAMETER_PERTURBATIONS": {
        "value": list(PARAMETER_PERTURBATIONS),
        "provenance": ThresholdProvenance.CONSERVATIVE_DEFAULT,
        "why": ("A +/-10% local probe. Narrow enough to stay semantically "
                "valid, wide enough to expose a knife-edge. No neighbour is "
                "ever promoted: this detects fragility, it does not search."),
    },
}


@dataclass(frozen=True)
class RobustnessContract:
    """The frozen threshold set, serialisable and hashable."""

    contract_id: str = CONTRACT_ID
    gate_id: str = GATE_ID
    min_pooled_observations: int = MIN_POOLED_OBSERVATIONS
    min_observations_per_symbol: int = MIN_OBSERVATIONS_PER_SYMBOL
    min_observations_per_fold: int = MIN_OBSERVATIONS_PER_FOLD
    min_observations_per_year: int = MIN_OBSERVATIONS_PER_YEAR
    min_observations_per_regime: int = MIN_OBSERVATIONS_PER_REGIME
    min_distinct_years: int = MIN_DISTINCT_YEARS
    min_distinct_symbols: int = MIN_DISTINCT_SYMBOLS
    min_walk_forward_folds: int = MIN_WALK_FORWARD_FOLDS
    min_positive_fold_fraction: float = MIN_POSITIVE_FOLD_FRACTION
    min_positive_year_fraction: float = MIN_POSITIVE_YEAR_FRACTION
    min_positive_symbol_fraction: float = MIN_POSITIVE_SYMBOL_FRACTION
    max_leave_one_out_relative_delta: float = MAX_LEAVE_ONE_OUT_RELATIVE_DELTA
    leave_one_out_sign_flip_is_dependency: bool = (
        LEAVE_ONE_OUT_SIGN_FLIP_IS_DEPENDENCY)
    max_single_regime_positive_r_share: float = (
        MAX_SINGLE_REGIME_POSITIVE_R_SHARE)
    min_positive_regime_fraction: float = MIN_POSITIVE_REGIME_FRACTION
    max_top_1_pct_positive_r_share: float = MAX_TOP_1_PCT_POSITIVE_R_SHARE
    max_top_5_pct_positive_r_share: float = MAX_TOP_5_PCT_POSITIVE_R_SHARE
    max_top_10_pct_positive_r_share: float = MAX_TOP_10_PCT_POSITIVE_R_SHARE
    winsor_sign_flip_is_tail_dependency: bool = (
        WINSOR_SIGN_FLIP_IS_TAIL_DEPENDENCY)
    winsor_levels: tuple[float, ...] = WINSOR_LEVELS
    bootstrap_samples: int = BOOTSTRAP_SAMPLES
    bootstrap_seed: int = BOOTSTRAP_SEED
    bootstrap_confidence: float = BOOTSTRAP_CONFIDENCE
    mean_r_required_floor: float = MEAN_R_REQUIRED_FLOOR
    parameter_perturbations: tuple[float, ...] = PARAMETER_PERTURBATIONS
    min_positive_neighbor_fraction: float = MIN_POSITIVE_NEIGHBOR_FRACTION
    max_relative_spike: float = MAX_RELATIVE_SPIKE
    frequent_outcome_rate: float = FREQUENT_OUTCOME_RATE
    mean_median_divergence_ratio: float = MEAN_MEDIAN_DIVERGENCE_RATIO
    allowed_dataset_roles: tuple[str, ...] = ("DEVELOPMENT", "DEVELOPMENT_KNOWN")
    forbidden_dataset_roles: tuple[str, ...] = (
        "OOS", "SEALED_OOS", "HOLDOUT", "SEALED_HOLDOUT", "UNKNOWN")

    def payload(self) -> dict:
        return {
            "contract_id": self.contract_id,
            "gate_id": self.gate_id,
            "sample_sufficiency": {
                "min_pooled_observations": self.min_pooled_observations,
                "min_observations_per_symbol": self.min_observations_per_symbol,
                "min_observations_per_fold": self.min_observations_per_fold,
                "min_observations_per_year": self.min_observations_per_year,
                "min_observations_per_regime": self.min_observations_per_regime,
                "min_distinct_years": self.min_distinct_years,
                "min_distinct_symbols": self.min_distinct_symbols,
                "min_walk_forward_folds": self.min_walk_forward_folds,
            },
            "stability": {
                "min_positive_fold_fraction": self.min_positive_fold_fraction,
                "min_positive_year_fraction": self.min_positive_year_fraction,
                "min_positive_symbol_fraction": self.min_positive_symbol_fraction,
                "max_leave_one_out_relative_delta":
                    self.max_leave_one_out_relative_delta,
                "leave_one_out_sign_flip_is_dependency":
                    self.leave_one_out_sign_flip_is_dependency,
            },
            "regime": {
                "max_single_regime_positive_r_share":
                    self.max_single_regime_positive_r_share,
                "min_positive_regime_fraction": self.min_positive_regime_fraction,
            },
            "tail": {
                "max_top_1_pct_positive_r_share":
                    self.max_top_1_pct_positive_r_share,
                "max_top_5_pct_positive_r_share":
                    self.max_top_5_pct_positive_r_share,
                "max_top_10_pct_positive_r_share":
                    self.max_top_10_pct_positive_r_share,
                "winsor_sign_flip_is_tail_dependency":
                    self.winsor_sign_flip_is_tail_dependency,
                "winsor_levels": list(self.winsor_levels),
            },
            "bootstrap": {
                "samples": self.bootstrap_samples,
                "seed": self.bootstrap_seed,
                "confidence": self.bootstrap_confidence,
                "mean_r_required_floor": self.mean_r_required_floor,
            },
            "parameter_neighborhood": {
                "perturbations": list(self.parameter_perturbations),
                "min_positive_neighbor_fraction":
                    self.min_positive_neighbor_fraction,
                "max_relative_spike": self.max_relative_spike,
                "is_search": False,
                "note": ("fragility probe only; no neighbour may be promoted "
                         "and the frozen value is never replaced"),
            },
            "distribution_shape": {
                "frequent_outcome_rate": self.frequent_outcome_rate,
                "mean_median_divergence_ratio": self.mean_median_divergence_ratio,
            },
            "dataset_roles": {
                "allowed": list(self.allowed_dataset_roles),
                "forbidden": list(self.forbidden_dataset_roles),
            },
            "diagnosis_precedence": list(DIAGNOSIS_PRECEDENCE),
            "secondary_only_diagnoses": list(SECONDARY_ONLY_DIAGNOSES),
        }

    def hash(self) -> str:
        return sha256_json(self.payload())

    def as_dict(self) -> dict:
        out = self.payload()
        out["CONTRACT_SHA256"] = self.hash()
        out["rationale"] = {
            k: {"value": v["value"], "provenance": str(v["provenance"]),
                "why": v["why"]}
            for k, v in RATIONALE.items()
        }
        return out


FROZEN_CONTRACT = RobustnessContract()
