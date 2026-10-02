from __future__ import annotations

from collections.abc import Mapping

from ag_edgelab.contracts.definition import FunnelDefinition, StageMode as SpecStageMode
from ag_edgelab.funnels.base import FunnelRule
from ag_edgelab.funnels.runner import StageDefinition, StageMode


class FunnelCompileError(ValueError):
    pass


def compile_funnel(
    definition: FunnelDefinition,
    registry: Mapping[tuple[str, str], FunnelRule],
) -> tuple[StageDefinition, ...]:
    compiled: list[StageDefinition] = []
    for stage_spec in definition.stages:
        resolved = []
        for ref in stage_spec.rules:
            key = (ref.rule_id, ref.rule_version)
            try:
                resolved.append(registry[key])
            except KeyError as exc:
                raise FunnelCompileError(f"missing rule {ref.rule_id}@{ref.rule_version}") from exc
        compiled.append(
            StageDefinition(
                stage=stage_spec.stage,
                rules=tuple(resolved),
                mode=StageMode(SpecStageMode(stage_spec.mode).value),
            )
        )
    return tuple(compiled)
