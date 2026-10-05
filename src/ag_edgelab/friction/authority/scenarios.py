"""Preregistered economic scenarios and the historical-applicability wall.

Two separate concerns live here.

**Scenario preregistration.** A friction scenario is a rule chosen before
any candidate PnL is visible, not a number chosen after. The rule is
stored as a quantile selector plus a multiplier; the realised cost is
whatever the evidence yields when the rule is applied. The hash covers
the rule, so a scenario that is later "adjusted" produces a different
hash and the change is visible. Scenarios are never selected because
they make a strategy pass — the constructor literally has nowhere to put
a PnL series.

**Historical applicability.** Spreads captured in 2026 describe 2026.
The candidate datasets in this repository run 2011-2018. A 2026 quote
cannot be evidence about 2012 execution, so the two are kept in
different named buckets and the historical bucket is a research
assumption that must be declared, never an authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum

SCENARIO_CONTRACT_VERSION = "EDGELAB_ECONOMIC_SCENARIO_CONTRACT_V1"


class ScenarioName(StrEnum):
    BASELINE = "BASELINE"
    STRESSED = "STRESSED"


class FrictionRegime(StrEnum):
    """Which bucket a cost number belongs to. Never mix them."""

    VENUE_CURRENT_FRICTION_AUTHORITY = "VENUE_CURRENT_FRICTION_AUTHORITY"
    HISTORICAL_FRICTION_TRUTH = "HISTORICAL_FRICTION_TRUTH"
    RESEARCH_CONSERVATIVE_MODEL = "RESEARCH_CONSERVATIVE_MODEL"


@dataclass(frozen=True)
class ScenarioRule:
    """A deterministic cost rule, fixed before any candidate is priced."""

    name: ScenarioName
    spread_quantile: str
    spread_multiplier: float = 1.0
    slippage_points: float | None = None
    session_scope: str = "ALL"
    rationale: str = ""

    def as_dict(self) -> dict:
        return {
            "name": str(self.name),
            "spread_quantile": self.spread_quantile,
            "spread_multiplier": self.spread_multiplier,
            "slippage_points": self.slippage_points,
            "session_scope": self.session_scope,
            "rationale": self.rationale,
        }


#: The preregistered pair. BASELINE uses the median observed spread;
#: STRESSED uses P95, which is an *observed* quantile rather than an
#: invented multiple. Neither was chosen with reference to any strategy's
#: results, because no strategy is evaluated in this mission at all.
PREREGISTERED_SCENARIOS: tuple[ScenarioRule, ...] = (
    ScenarioRule(
        name=ScenarioName.BASELINE,
        spread_quantile="P50",
        spread_multiplier=1.0,
        rationale=(
            "Median observed spread for the symbol and session. Chosen as the "
            "central tendency of the evidence, fixed before any candidate PnL "
            "exists."),
    ),
    ScenarioRule(
        name=ScenarioName.STRESSED,
        spread_quantile="P95",
        spread_multiplier=1.0,
        rationale=(
            "95th percentile of the same observed distribution. An observed "
            "quantile is preferred to an invented multiplier because it is "
            "falsifiable against the capture evidence."),
    ),
)


@dataclass(frozen=True)
class ScenarioContract:
    """Preregistered scenarios plus the regime they are valid for."""

    rules: tuple[ScenarioRule, ...] = PREREGISTERED_SCENARIOS
    regime: FrictionRegime = FrictionRegime.VENUE_CURRENT_FRICTION_AUTHORITY
    preregistered_before_any_candidate_pnl: bool = True
    selection_inputs: tuple[str, ...] = field(default_factory=lambda: (
        "spread distribution quantiles",
        "symbol metadata",
    ))
    forbidden_selection_inputs: tuple[str, ...] = field(default_factory=lambda: (
        "candidate PnL",
        "candidate expectancy",
        "candidate profit factor",
        "OOS results",
        "holdout results",
    ))

    def payload(self) -> dict:
        return {
            "contract_version": SCENARIO_CONTRACT_VERSION,
            "regime": str(self.regime),
            "preregistered_before_any_candidate_pnl":
                self.preregistered_before_any_candidate_pnl,
            "selection_inputs": list(self.selection_inputs),
            "forbidden_selection_inputs": list(self.forbidden_selection_inputs),
            "rules": [r.as_dict() for r in self.rules],
        }

    def hash(self) -> str:
        blob = json.dumps(self.payload(), sort_keys=True,
                          separators=(",", ":")).encode()
        return hashlib.sha256(blob).hexdigest()

    def as_dict(self) -> dict:
        out = self.payload()
        out["scenario_contract_sha256"] = self.hash()
        return out


# ---------------------------------------------------------------------------
# historical applicability
# ---------------------------------------------------------------------------

HISTORICAL_FRICTION_LIMITATION = (
    "Venue friction evidence is captured from a live 2026 VT Markets "
    "environment. The candidate datasets under data authority cover "
    "2011-06-01 to 2018-06-06. Spreads, commission schedules and financing "
    "rates from 2026 are NOT evidence about 2012 or 2017 execution "
    "conditions: retail FX spreads compressed substantially over that "
    "period, commission-inclusive 'raw' accounts were not uniformly "
    "available, and the broker entity, liquidity providers and regulatory "
    "regime all differ. Any backtest over 2011-2018 priced with 2026 "
    "friction is therefore reporting VENUE_CURRENT_FRICTION_AUTHORITY "
    "applied counterfactually, not HISTORICAL_FRICTION_TRUTH. "
    "HISTORICAL_FRICTION_TRUTH for this period is UNAVAILABLE and cannot be "
    "manufactured from current captures."
)


@dataclass(frozen=True)
class HistoricalCostPolicy:
    """The reproducible conservative rule used when history has no broker.

    This is a declared research assumption, labelled
    RESEARCH_CONSERVATIVE_MODEL so it can never be mistaken for measured
    truth. It is deliberately pessimistic and deliberately simple: a
    single documented multiple of the current observed distribution,
    anchored on an observed quantile, so the whole thing is reproducible
    from the capture evidence plus one constant.
    """

    anchor_quantile: str = "P95"
    multiplier: float = 2.0
    regime: FrictionRegime = FrictionRegime.RESEARCH_CONSERVATIVE_MODEL
    applies_to_period: str = "2011-06-01/2018-06-06"
    justification: str = (
        "Absent broker evidence for the dataset period, the research cost "
        "model anchors on the P95 of the current observed distribution and "
        "doubles it. The anchor is observed rather than assumed; the "
        "multiplier is a declared constant, not a fit. It is intended to be "
        "conservative (costs over-stated) so that a candidate surviving it is "
        "not surviving on an optimistic friction assumption. It is NOT a "
        "measurement of historical spreads and must never be reported as one."
    )
    falsifiable_by: str = (
        "Period-contemporaneous broker statements, tick archives carrying the "
        "executing venue's own ask series, or an archived commission schedule."
    )

    def as_dict(self) -> dict:
        return {
            "anchor_quantile": self.anchor_quantile,
            "multiplier": self.multiplier,
            "regime": str(self.regime),
            "applies_to_period": self.applies_to_period,
            "justification": self.justification,
            "falsifiable_by": self.falsifiable_by,
            "is_measurement": False,
        }


def assert_regime_compatible(regime: FrictionRegime, dataset_period: str,
                             capture_period: str) -> None:
    """Refuse to apply current-venue friction to a historical period silently."""
    if (regime is FrictionRegime.VENUE_CURRENT_FRICTION_AUTHORITY
            and dataset_period != capture_period):
        raise ValueError(
            f"refusing to apply VENUE_CURRENT_FRICTION_AUTHORITY captured over "
            f"{capture_period} to dataset period {dataset_period}. Use "
            f"RESEARCH_CONSERVATIVE_MODEL and label the result accordingly. "
            f"{HISTORICAL_FRICTION_LIMITATION}")
