"""Non-mutating Funnel Optimizer adapter for frozen ALD V2 research facts.

``asian_liquidity_displacement_v2`` is intentionally not imported as a place to
add optimizer hooks.  Its ordinary replay stops at its first terminal failure;
that trace cannot truthfully turn absent downstream stages into failures.  This
adapter converts independently produced stage facts into the generic
:class:`~ag_edgelab.optimization.funnel_optimizer.RelaxedReplay` contract and
labels unavailable facts ``NOT_EVALUABLE``.

A future all-opportunity ALD fact producer can supply every semantically
available stage fact.  Passing a legacy ``V2Unit`` is also supported for
migration, but only stages actually recorded by that early-terminating engine
are treated as facts.  It never fabricates later values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from ag_edgelab.optimization.funnel_optimizer import (Opportunity, RuleEvaluation,
                                                       RuleSemantics, RuleSpec,
                                                       RuleState)
from ag_edgelab.strategies.asian_liquidity_displacement_v2 import (REASON_NODE,
                                                                    STAGE_NODES,
                                                                    V2Unit)

V2_RELAXED_ENGINE_ID = "ALD_V2_RELAXED_OPPORTUNITY_REPLAY_V1"

# ALD stage construction is path-dependent: even a stage whose pass/fail cell
# is known cannot safely be removed by a table query because doing so changes
# subsequent branch/state construction.  Every V2 stage therefore fails closed
# for leave-one-out / removal until a full replay implementation says otherwise.
V2_RULE_SEMANTICS: Mapping[str, RuleSemantics] = {
    stage: RuleSemantics.REQUIRES_FULL_REPLAY for stage in STAGE_NODES
}


@dataclass(frozen=True)
class V2StageFact:
    """An independently observed stage fact, not an inferred terminal trace."""

    state: RuleState
    reason_code: str
    feature_values: Mapping[str, object]


def v2_relaxed_rules() -> tuple[RuleSpec, ...]:
    """Build stage rules that consume explicit ``v2_stage_facts`` only.

    The dependency chain represents actual semantic prerequisites.  The generic
    relaxed replay still evaluates unrelated rules after a failure; ALD's stages
    are deliberately dependent because later branch geometry has no meaning
    without the required earlier construction.
    """
    rules: list[RuleSpec] = []
    for index, stage in enumerate(STAGE_NODES):
        dependencies = () if index == 0 else (STAGE_NODES[index - 1],)

        def evaluate(opportunity: Opportunity, *, stage_id: str = stage) -> RuleEvaluation:
            facts = opportunity.feature("v2_stage_facts")
            if not isinstance(facts, Mapping):
                return RuleEvaluation(RuleState.NOT_EVALUABLE, "V2_STAGE_FACTS_UNAVAILABLE")
            fact = facts.get(stage_id)
            if not isinstance(fact, V2StageFact):
                return RuleEvaluation(RuleState.NOT_EVALUABLE, f"V2_STAGE_FACT_UNAVAILABLE:{stage_id}")
            return RuleEvaluation(fact.state, fact.reason_code, fact.feature_values)

        rules.append(RuleSpec(stage, evaluate, dependencies,
                              V2_RULE_SEMANTICS[stage], None))
    return tuple(rules)


def legacy_stage_facts(unit: V2Unit) -> Mapping[str, V2StageFact]:
    """Return only facts genuinely present in a frozen V2 terminal trace.

    Missing later keys stay absent.  The relaxed adapter will emit
    ``NOT_EVALUABLE`` rather than reinterpret them as ``FAIL``.
    """
    facts: dict[str, V2StageFact] = {}
    for stage, passed in unit.stages.items():
        if stage not in STAGE_NODES:
            continue
        reason = "PASS" if passed else (unit.reject_reason if unit.reject_node == stage
                                         else f"LEGACY_STAGE_{stage}_FAIL")
        facts[stage] = V2StageFact(RuleState.PASS if passed else RuleState.FAIL,
                                   reason, _stage_features(unit, stage))
    return facts


def opportunity_from_v2_unit(unit: V2Unit, *, timestamp_utc: datetime,
                              dataset_id: str,
                              reference_outcome_r: float | None = None) -> Opportunity:
    """Adapt a frozen replay unit without assigning a reference outcome.

    ``reference_outcome_r`` is intentionally optional.  A caller must provide
    it from an explicit outcome model; the V2 actual trade result is not copied
    into it.  Existing actual outcome remains available only for all-pass units
    when the generic relaxed evaluator builds the event table.
    """
    return Opportunity(
        event_id=f"{unit.candidate_id}|RELAXED_V1",
        candidate_id=unit.candidate_id,
        timestamp_utc=timestamp_utc,
        symbol=unit.symbol,
        session=unit.session,
        dataset_id=dataset_id,
        strategy_id="ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2",
        engine_id=V2_RELAXED_ENGINE_ID,
        feature_values={"v2_stage_facts": legacy_stage_facts(unit)},
        reference_outcome_r=reference_outcome_r,
        actual_outcome_r=unit.realised_r,
    )


def _stage_features(unit: V2Unit, stage: str) -> Mapping[str, object]:
    """Expose only values the frozen V2 replay has actually populated."""
    candidates: Mapping[str, tuple[str, ...]] = {
        "S1_CONTEXT_ELIGIBLE": ("reference_bars", "entry_window_m5_bars"),
        "S2_LOCATION_ELIGIBLE": ("reference_high", "reference_low"),
        "S3_SESSION_EVENT": ("event_time", "boundary_side"),
        "S4_SWEEP_OR_BREAKOUT": ("branch", "direction"),
        "S5_RECLAIM_OR_RETEST": ("reclaim_or_retest_time",),
        "S6_STRUCTURE_CONFIRM": ("confirm_time", "confirm_primitive"),
        "S7_ENTRY_AVAILABLE": ("entry", "forward_bars"),
        "S8_GEOMETRY_VALID": ("entry", "stop", "risk", "target", "natural_target_r"),
        "S9_TRADE_COMPLETED": ("resolution", "realised_r", "mfe_r", "mae_r"),
    }
    out: dict[str, object] = {}
    for field_name in candidates.get(stage, ()):
        value = getattr(unit, field_name)
        if value is not None:
            out[field_name] = value
    return out


def source_reason_node_is_consistent(unit: V2Unit) -> bool:
    """Small guard useful to adapters: frozen V2 reason-node mapping is intact."""
    if unit.reject_reason == "PASS":
        return unit.reject_node is None
    return REASON_NODE.get(unit.reject_reason) == unit.reject_node
