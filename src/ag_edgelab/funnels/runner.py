from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from ag_edgelab.contracts.funnel import FunnelStage, FunnelStageResult
from ag_edgelab.contracts.market import EvaluationContext
from ag_edgelab.funnels.base import FunnelRule


class StageMode(StrEnum):
    ALL = "ALL"
    ANY = "ANY"
    SEQUENCE = "SEQUENCE"


@dataclass(frozen=True)
class StageDefinition:
    stage: FunnelStage
    rules: tuple[FunnelRule, ...]
    mode: StageMode = StageMode.ALL


class FunnelRunner:
    def evaluate_stage(
        self,
        *,
        candidate_id: str,
        definition: StageDefinition,
        context: EvaluationContext,
    ) -> FunnelStageResult:
        results = []
        for rule in definition.rules:
            result = rule.evaluate(context)
            results.append(result)
            if definition.mode == StageMode.SEQUENCE and not result.passed:
                break

        frozen_results = tuple(results)
        if not frozen_results:
            passed = True
        elif definition.mode in {StageMode.ALL, StageMode.SEQUENCE}:
            passed = all(r.passed for r in frozen_results) and len(frozen_results) == len(definition.rules)
        else:
            passed = any(r.passed for r in frozen_results)

        failure = None if passed else ";".join(
            r.failure_reason or r.rule_id for r in frozen_results if not r.passed
        )
        return FunnelStageResult(
            candidate_id=candidate_id,
            stage=definition.stage,
            passed=passed,
            as_of=context.as_of,
            rule_results=frozen_results,
            failure_reason=failure,
        )

    def run(
        self,
        *,
        candidate_id: str,
        stages: Iterable[StageDefinition],
        context: EvaluationContext,
    ) -> tuple[FunnelStageResult, ...]:
        out: list[FunnelStageResult] = []
        for stage in stages:
            result = self.evaluate_stage(candidate_id=candidate_id, definition=stage, context=context)
            out.append(result)
            if not result.passed:
                break
        return tuple(out)
