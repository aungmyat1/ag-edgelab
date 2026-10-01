from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ag_edgelab.contracts.branching import FunnelEvent, FunnelRunResult, FunnelVariant, NodeType, RuleVersion, TradeResult
from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import canonical_json, sha256_json
from ag_edgelab.verification.time import UTCDateTime, utc_datetime

HEX64 = r"^[0-9a-f]{64}$"


class BranchingOpportunity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    candidate_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    dataset_sha256: str = Field(pattern=HEX64)
    dataset_role: str = "DEVELOPMENT"
    as_of: UTCDateTime
    bars: tuple[MarketBar, ...]
    attributes_json: str = "{}"

    @model_validator(mode="after")
    def canonical_history(self) -> "BranchingOpportunity":
        attributes = json.loads(self.attributes_json)
        if not isinstance(attributes, dict) or canonical_json(attributes) != self.attributes_json:
            raise ValueError("attributes_json must be a canonical JSON object")
        bars = tuple(bar.model_copy(update={"timestamp": utc_datetime(bar.timestamp)}) for bar in self.bars)
        if any(bar.timestamp > self.as_of for bar in bars):
            raise ValueError("future market bar")
        if [bar.timestamp for bar in bars] != sorted(bar.timestamp for bar in bars):
            raise ValueError("market bars must be chronological")
        object.__setattr__(self, "bars", bars)
        return self

    @property
    def attributes(self) -> dict:
        return json.loads(self.attributes_json)


@dataclass(frozen=True)
class NodeEvaluation:
    output: str
    measurements: Mapping[str, object]
    passed: bool = True
    trade: TradeResult | None = None


RuleEvaluator = Callable[[BranchingOpportunity, RuleVersion], NodeEvaluation]


class GraphRuleRegistry:
    """Explicit evaluator map keyed by immutable rule identity."""
    def __init__(self):
        self._evaluators: dict[str, tuple[RuleVersion, RuleEvaluator]] = {}

    def register(self, rule: RuleVersion, evaluator: RuleEvaluator) -> None:
        if rule.sha256 in self._evaluators:
            raise ValueError(f"duplicate rule version: {rule.rule_id}@{rule.version}")
        self._evaluators[rule.sha256] = (rule, evaluator)

    def resolve(self, rule: RuleVersion) -> RuleEvaluator:
        registered = self._evaluators.get(rule.sha256)
        if registered is None or registered[0] != rule:
            raise LookupError(f"unknown rule identity: {rule.rule_id}@{rule.version}")
        return registered[1]


@dataclass(frozen=True)
class BranchingFunnelEngine:
    registry: GraphRuleRegistry

    def run(self, variant: FunnelVariant, opportunity: BranchingOpportunity) -> FunnelRunResult:
        if opportunity.dataset_role != "DEVELOPMENT":
            raise ValueError("the funnel development engine accepts DEVELOPMENT data only")
        nodes = {node.node_id: node for node in variant.definition.nodes}
        edges = {node.node_id: {edge.output: edge.target_node_id for edge in node.edges}
                 for node in variant.definition.nodes}
        current = variant.definition.entry_node_id
        events: list[FunnelEvent] = []
        trades: list[TradeResult] = []
        while current:
            if any(event.node_id == current for event in events):
                raise ValueError("cyclic funnel execution")
            node = nodes[current]
            evaluation = self.registry.resolve(node.rule)(opportunity, node.rule)
            if node.rule.node_type == NodeType.TRADE:
                if evaluation.trade is None:
                    raise ValueError("TRADE rule must return a TradeResult")
                trades.append(evaluation.trade)
                outcome = "TRADE"
                target = None
            elif node.rule.node_type == NodeType.FILTER and not evaluation.passed:
                outcome = "FAIL"
                target = None
            else:
                target = edges[current].get(evaluation.output)
                if node.edges and target is None:
                    raise ValueError(f"unrouted output {evaluation.output!r} at node {current}")
                outcome = "ROUTE" if node.rule.node_type == NodeType.CLASSIFIER else "PASS"
            inputs = {"symbol": opportunity.symbol, "attributes": opportunity.attributes,
                      "bars": [bar.model_dump(mode="json") for bar in opportunity.bars]}
            measurements = dict(evaluation.measurements)
            event_payload = {"candidate_id": opportunity.candidate_id, "index": len(events),
                             "node_id": current, "rule_sha256": node.rule.sha256,
                             "funnel_sha256": variant.sha256}
            events.append(FunnelEvent(
                event_id=sha256_json(event_payload), timestamp=opportunity.as_of,
                symbol=opportunity.symbol, dataset_sha256=opportunity.dataset_sha256,
                funnel_sha256=variant.sha256, node_id=current,
                rule_version=f"{node.rule.rule_id}@{node.rule.version}",
                input_json=canonical_json(inputs), output=evaluation.output, outcome=outcome,
                measurements_json=canonical_json(measurements),
                trade_id=evaluation.trade.trade_id if evaluation.trade else None,
            ))
            current = target
        return FunnelRunResult(candidate_id=opportunity.candidate_id, symbol=opportunity.symbol,
                               dataset_sha256=opportunity.dataset_sha256, funnel_sha256=variant.sha256,
                               events=tuple(events), trades=tuple(trades))
