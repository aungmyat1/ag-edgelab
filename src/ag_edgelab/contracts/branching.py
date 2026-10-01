from __future__ import annotations

import json
import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ag_edgelab.data.fingerprint import canonical_json, sha256_json
from ag_edgelab.verification.time import UTCDateTime

HEX64 = r"^[0-9a-f]{64}$"


class NodeType(StrEnum):
    CLASSIFIER = "CLASSIFIER"
    FILTER = "FILTER"
    TRADE = "TRADE"


class RuleVersion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    rule_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    node_type: NodeType
    implementation_sha256: str = Field(pattern=HEX64)
    behavior_json: str = Field(min_length=2)
    display_name: str = ""

    @model_validator(mode="after")
    def canonical_behavior(self) -> "RuleVersion":
        value = json.loads(self.behavior_json)
        if not isinstance(value, dict) or canonical_json(value) != self.behavior_json:
            raise ValueError("behavior_json must be a canonical JSON object")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json({"rule_id": self.rule_id, "version": self.version,
                            "node_type": self.node_type, "implementation_sha256": self.implementation_sha256,
                            "behavior_json": self.behavior_json})


class DecisionEdge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    output: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)


class RuleNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node_id: str = Field(min_length=1)
    rule: RuleVersion
    edges: tuple[DecisionEdge, ...] = ()

    @model_validator(mode="after")
    def valid_edges(self) -> "RuleNode":
        outputs = [edge.output for edge in self.edges]
        if len(outputs) != len(set(outputs)):
            raise ValueError("node edge outputs must be unique")
        if self.rule.node_type == NodeType.TRADE and self.edges:
            raise ValueError("TRADE nodes are terminal")
        return self


class FunnelDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    funnel_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    entry_node_id: str = Field(min_length=1)
    nodes: tuple[RuleNode, ...] = Field(min_length=1)
    display_name: str = ""

    @model_validator(mode="after")
    def graph_is_closed(self) -> "FunnelDefinition":
        by_id = {node.node_id: node for node in self.nodes}
        if len(by_id) != len(self.nodes) or self.entry_node_id not in by_id:
            raise ValueError("funnel node ids must be unique and entry node must exist")
        for node in self.nodes:
            if any(edge.target_node_id not in by_id for edge in node.edges):
                raise ValueError("decision edge references an unknown node")
        return self

    @property
    def sha256(self) -> str:
        nodes = sorted(self.nodes, key=lambda item: item.node_id)
        identity = {"funnel_id": self.funnel_id, "version": self.version,
                    "entry_node_id": self.entry_node_id,
                    "nodes": [{"node_id": n.node_id, "rule_sha256": n.rule.sha256,
                               "edges": sorted((e.model_dump(mode="python") for e in n.edges),
                                               key=lambda edge: (edge["output"], edge["target_node_id"]))}
                              for n in nodes]}
        return sha256_json(identity)


class FunnelVariant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    definition: FunnelDefinition
    parent_sha256: str | None = Field(default=None, pattern=HEX64)
    frozen: bool = False

    @property
    def sha256(self) -> str:
        return self.definition.sha256

    def mutate_rule(self, node_id: str, rule: RuleVersion, *, dataset_role: str) -> "FunnelVariant":
        if self.frozen:
            raise ValueError("frozen funnel variants cannot be mutated")
        if dataset_role != "DEVELOPMENT":
            raise ValueError("funnel mutation requires DEVELOPMENT data")
        nodes = list(self.definition.nodes)
        for index, node in enumerate(nodes):
            if node.node_id == node_id:
                nodes[index] = node.model_copy(update={"rule": rule})
                break
        else:
            raise ValueError(f"unknown funnel node: {node_id}")
        child = self.definition.model_copy(update={"version": f"{self.definition.version}+child", "nodes": tuple(nodes)})
        return FunnelVariant(definition=child, parent_sha256=self.sha256)

    def freeze(self) -> "FunnelVariant":
        return self.model_copy(update={"frozen": True})


class FunnelEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str = Field(pattern=HEX64)
    timestamp: UTCDateTime
    symbol: str = Field(min_length=1)
    dataset_sha256: str = Field(pattern=HEX64)
    funnel_sha256: str = Field(pattern=HEX64)
    node_id: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    input_json: str
    output: str
    outcome: str
    measurements_json: str


class TradeResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    trade_id: str = Field(min_length=1)
    direction: str
    entry: float
    stop: float
    target: float
    exit: float
    result_r: float

    @model_validator(mode="after")
    def finite_prices(self) -> "TradeResult":
        if any(not math.isfinite(v) for v in (self.entry, self.stop, self.target, self.exit, self.result_r)):
            raise ValueError("trade result values must be finite")
        if self.direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        return self


class FunnelRunResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    candidate_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    dataset_sha256: str = Field(pattern=HEX64)
    dataset_role: str = "DEVELOPMENT"
    funnel_sha256: str = Field(pattern=HEX64)
    events: tuple[FunnelEvent, ...]
    trades: tuple[TradeResult, ...]
    status: str = "DEVELOPMENT_CANDIDATE"
