from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ag_edgelab.contracts.branching import (DecisionEdge, FunnelDefinition, FunnelVariant,
                                             NodeType, RuleNode, RuleVersion, TradeResult)
from ag_edgelab.data.fingerprint import canonical_json, sha256_json
from ag_edgelab.funnels.graph import (BranchingFunnelEngine, BranchingOpportunity,
                                       GraphRuleRegistry, NodeEvaluation)

Z = timezone.utc
SYNTHETIC_IMPLEMENTATION_SHA256 = sha256_json({"implementation": "synthetic reference branching strategy v1"})


def _rule(rule_id: str, version: str, node_type: NodeType, behavior: dict | None = None) -> RuleVersion:
    return RuleVersion(rule_id=rule_id, version=version, node_type=node_type,
                       implementation_sha256=SYNTHETIC_IMPLEMENTATION_SHA256,
                       behavior_json=canonical_json(behavior or {}))


def _definition(sweep_version: str) -> FunnelDefinition:
    rules = {
        "market": _rule("MARKET_STATE", "V1", NodeType.CLASSIFIER),
        "trend": _rule("TREND_DIRECTION", "V1", NodeType.CLASSIFIER),
        "range": _rule("SWEEP", sweep_version, NodeType.CLASSIFIER,
                        {"minimum_sweep_strength": 0.5 if sweep_version == "V1" else 0.8}),
        "trend_buy": _rule("TREND_BUY", "V1", NodeType.TRADE, {"direction": "LONG"}),
        "trend_sell": _rule("TREND_SELL", "V1", NodeType.TRADE, {"direction": "SHORT"}),
        "range_setup": _rule("RANGE_SETUP", "V1", NodeType.TRADE, {"direction": "LONG"}),
        "sweep_setup": _rule("SWEEP_SETUP", "V1", NodeType.TRADE, {"direction": "LONG"}),
    }
    nodes = (
        RuleNode(node_id="market", rule=rules["market"], edges=(
            DecisionEdge(output="TREND", target_node_id="trend_direction"),
            DecisionEdge(output="RANGE", target_node_id="range_route"))),
        RuleNode(node_id="trend_direction", rule=rules["trend"], edges=(
            DecisionEdge(output="BUY", target_node_id="trend_buy"),
            DecisionEdge(output="SELL", target_node_id="trend_sell"))),
        RuleNode(node_id="range_route", rule=rules["range"], edges=(
            DecisionEdge(output="RANGE_SETUP", target_node_id="range_setup"),
            DecisionEdge(output="SWEEP_SETUP", target_node_id="sweep_setup"))),
        RuleNode(node_id="trend_buy", rule=rules["trend_buy"]),
        RuleNode(node_id="trend_sell", rule=rules["trend_sell"]),
        RuleNode(node_id="range_setup", rule=rules["range_setup"]),
        RuleNode(node_id="sweep_setup", rule=rules["sweep_setup"]),
    )
    return FunnelDefinition(funnel_id="SYNTHETIC_BRANCHING_REFERENCE", version=sweep_version,
                            entry_node_id="market", nodes=nodes)


def build_reference_variants() -> tuple[FunnelVariant, FunnelVariant, GraphRuleRegistry]:
    v1 = FunnelVariant(definition=_definition("V1"))
    v2_rule = _rule("SWEEP", "V2", NodeType.CLASSIFIER, {"minimum_sweep_strength": 0.8})
    v1_1 = v1.mutate_rule("range_route", v2_rule, dataset_role="DEVELOPMENT")
    registry = GraphRuleRegistry()

    def market(opportunity, rule):
        state = opportunity.attributes["market_state"]
        return NodeEvaluation(output=state, measurements={"market_state": state})

    def trend(opportunity, rule):
        direction = opportunity.attributes["direction"]
        return NodeEvaluation(output=direction, measurements={"trend_direction": direction})

    def sweep(opportunity, rule):
        strength = float(opportunity.attributes["sweep_strength"])
        threshold = json.loads(rule.behavior_json)["minimum_sweep_strength"]
        route = "SWEEP_SETUP" if strength >= threshold else "RANGE_SETUP"
        return NodeEvaluation(output=route, measurements={"sweep_strength": strength, "threshold": threshold})

    def trade(opportunity, rule):
        attrs = opportunity.attributes
        direction = json.loads(rule.behavior_json)["direction"]
        entry = float(attrs.get("entry", 100.0))
        result_r = float(attrs["result_r"])
        risk = float(attrs.get("risk", 1.0))
        stop = entry - risk if direction == "LONG" else entry + risk
        target = entry + 2 * risk if direction == "LONG" else entry - 2 * risk
        exit_price = entry + result_r * risk if direction == "LONG" else entry - result_r * risk
        result = TradeResult(trade_id=f"{opportunity.candidate_id}-trade", direction=direction,
                             management="SYNTHETIC_FIXED_TARGET",
                             entry=entry, stop=stop, target=target, exit=exit_price, result_r=result_r)
        return NodeEvaluation(output="TRADE", measurements={"result_r": result_r}, trade=result)

    callbacks = {"MARKET_STATE": market, "TREND_DIRECTION": trend, "SWEEP": sweep,
                 "TREND_BUY": trade, "TREND_SELL": trade,
                 "RANGE_SETUP": trade, "SWEEP_SETUP": trade}
    versions = {node.rule.sha256: node.rule for variant in (v1, v1_1)
                for node in variant.definition.nodes}
    for rule in versions.values():
        registry.register(rule, callbacks[rule.rule_id])
    return v1, v1_1, registry


def synthetic_development_opportunities() -> tuple[BranchingOpportunity, ...]:
    dataset = sha256_json({"fixture": "synthetic-development-branching-bars-v1"})
    scenarios = (
        ("trend-buy", "TREND", "BUY", 0.0, 1.5),
        ("trend-sell", "TREND", "SELL", 0.0, -1.0),
        ("normal-range", "RANGE", "BUY", 0.3, 0.5),
        ("sweep-boundary", "RANGE", "BUY", 0.6, 1.0),
        ("strong-sweep", "RANGE", "BUY", 0.9, 1.25),
    )
    start = datetime(2025, 1, 1, tzinfo=Z)
    opportunities = []
    for index, (candidate, state, direction, strength, result_r) in enumerate(scenarios):
        timestamp = start + timedelta(hours=index)
        opportunities.append(BranchingOpportunity(
            candidate_id=candidate, symbol="SYNTH", dataset_sha256=dataset,
            dataset_role="DEVELOPMENT", as_of=timestamp,
            bars=({"timestamp": timestamp, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10},),
            attributes_json=canonical_json({"market_state": state, "direction": direction,
                                            "sweep_strength": strength, "result_r": result_r}),
        ))
    return tuple(opportunities)


def run_reference_variant(variant: FunnelVariant, registry: GraphRuleRegistry,
                          opportunities: tuple[BranchingOpportunity, ...]):
    engine = BranchingFunnelEngine(registry)
    return tuple(engine.run(variant, opportunity) for opportunity in opportunities)
