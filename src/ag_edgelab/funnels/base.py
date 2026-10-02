from __future__ import annotations

from typing import Protocol

from ag_edgelab.contracts.funnel import RuleResult
from ag_edgelab.contracts.market import EvaluationContext


class FunnelRule(Protocol):
    rule_id: str
    rule_version: str
    rule_hash: str

    def evaluate(self, context: EvaluationContext) -> RuleResult: ...
