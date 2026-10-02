from datetime import datetime, timezone

from ag_edgelab.contracts.funnel import FunnelStage, RuleResult
from ag_edgelab.contracts.market import EvaluationContext
from ag_edgelab.funnels.runner import FunnelRunner, StageDefinition


class StaticRule:
    rule_version = "1"
    rule_hash = "sha256:test"

    def __init__(self, rule_id: str, passed: bool):
        self.rule_id = rule_id
        self.passed = passed

    def evaluate(self, context):
        return RuleResult(
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            rule_hash=self.rule_hash,
            passed=self.passed,
            evaluated_at=context.as_of,
            failure_reason=None if self.passed else "REJECTED",
        )


def test_funnel_stops_at_first_failed_stage():
    ctx = EvaluationContext(instrument="EURUSD", as_of=datetime.now(timezone.utc))
    stages = (
        StageDefinition(FunnelStage.CONTEXT, (StaticRule("ctx", True),)),
        StageDefinition(FunnelStage.LOCATION, (StaticRule("loc", False),)),
        StageDefinition(FunnelStage.TRIGGER, (StaticRule("trigger", True),)),
    )
    results = FunnelRunner().run(candidate_id="C1", stages=stages, context=ctx)
    assert [r.stage for r in results] == [FunnelStage.CONTEXT, FunnelStage.LOCATION]
    assert results[-1].passed is False
