from datetime import datetime, timezone

import pytest

from ag_edgelab.contracts.definition import FunnelDefinition, RuleRef, StageMode, StageSpec
from ag_edgelab.contracts.funnel import FunnelStage, RuleResult
from ag_edgelab.contracts.market import EvaluationContext
from ag_edgelab.contracts.strategy import StrategyManifest
from ag_edgelab.funnels.compiler import FunnelCompileError, compile_funnel
from ag_edgelab.funnels.runner import FunnelRunner


class StaticRule:
    def __init__(self, rule_id: str, version: str, passed: bool):
        self.rule_id = rule_id
        self.rule_version = version
        self.rule_hash = f"sha256:{rule_id}:{version}"
        self.passed = passed

    def evaluate(self, context):
        return RuleResult(
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            rule_hash=self.rule_hash,
            passed=self.passed,
            evaluated_at=context.as_of,
            failure_reason=None if self.passed else f"{self.rule_id}_FAIL",
        )


def test_strategy_manifest_defaults_to_canonical_funnel():
    manifest = StrategyManifest(
        strategy_id="EMA_REF",
        version="1.0.0",
        source_sha256="a" * 64,
        required_timeframes=("M15",),
    )
    assert manifest.funnel_stages[0] == FunnelStage.CONTEXT
    assert manifest.funnel_stages[-1] == FunnelStage.EXECUTION


def test_definition_rejects_out_of_order_stages():
    with pytest.raises(ValueError, match="canonical order"):
        FunnelDefinition(
            definition_id="BAD",
            version="1",
            stages=(
                StageSpec(stage=FunnelStage.TRIGGER, rules=(RuleRef(rule_id="t", rule_version="1"),)),
                StageSpec(stage=FunnelStage.LOCATION, rules=(RuleRef(rule_id="l", rule_version="1"),)),
            ),
        )


def test_compiler_rejects_missing_rule():
    definition = FunnelDefinition(
        definition_id="X",
        version="1",
        stages=(StageSpec(stage=FunnelStage.CONTEXT, rules=(RuleRef(rule_id="ctx", rule_version="1"),)),),
    )
    with pytest.raises(FunnelCompileError, match="missing rule"):
        compile_funnel(definition, {})


def test_sequence_stops_inside_stage_on_first_failed_rule():
    definition = FunnelDefinition(
        definition_id="SEQ",
        version="1",
        stages=(
            StageSpec(
                stage=FunnelStage.TRIGGER,
                mode=StageMode.SEQUENCE,
                rules=(
                    RuleRef(rule_id="a", rule_version="1"),
                    RuleRef(rule_id="b", rule_version="1"),
                    RuleRef(rule_id="c", rule_version="1"),
                ),
            ),
        ),
    )
    registry = {
        ("a", "1"): StaticRule("a", "1", True),
        ("b", "1"): StaticRule("b", "1", False),
        ("c", "1"): StaticRule("c", "1", True),
    }
    stages = compile_funnel(definition, registry)
    ctx = EvaluationContext(instrument="EURUSD", as_of=datetime.now(timezone.utc))
    result = FunnelRunner().run(candidate_id="C1", stages=stages, context=ctx)[0]
    assert result.passed is False
    assert [r.rule_id for r in result.rule_results] == ["a", "b"]
