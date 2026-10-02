from datetime import datetime, timezone

from ag_edgelab.contracts.funnel import FunnelStage, RuleResult
from ag_edgelab.contracts.market import EvaluationContext
from ag_edgelab.funnels.runner import FunnelRunner, StageDefinition
from ag_edgelab.ledger.candidate import CandidateRecord


class RejectRule:
    rule_id = "spread_gate"
    rule_version = "1"
    rule_hash = "a" * 64

    def evaluate(self, context):
        return RuleResult(
            rule_id=self.rule_id, rule_version=self.rule_version, rule_hash=self.rule_hash,
            passed=False, evaluated_at=context.as_of, failure_reason="spread too wide",
            rejection_code="EXEC_SPREAD_TOO_WIDE",
        )


def test_rejection_code_survives_stage_and_candidate_lineage():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = FunnelRunner().evaluate_stage(
        candidate_id="C1",
        definition=StageDefinition(FunnelStage.EXECUTION, (RejectRule(),)),
        context=EvaluationContext(instrument="EURUSD", as_of=now),
    )
    assert result.rejection_codes == ("EXEC_SPREAD_TOO_WIDE",)
    candidate = CandidateRecord(
        candidate_id="C1", instrument="EURUSD", strategy_id="S", strategy_version="1",
        strategy_sha256="a" * 64, dataset_sha256="b" * 64, stage_results=(result,),
    )
    assert candidate.rejection_codes == ("EXEC_SPREAD_TOO_WIDE",)
