from datetime import datetime, timezone

import pytest

from ag_edgelab.analytics.diagnostic import analyze_three_funnel
from ag_edgelab.contracts.branching import FunnelEvent, FunnelRunResult, TradeResult
from ag_edgelab.contracts.diagnostic import (
    DiagnosticDefinition,
    DiagnosticRuleBinding,
    ExcursionObservation,
    ExitPolicyResult,
    FunnelGroup,
    WeakPointLabel,
)

H = "a" * 64
F = "b" * 64
S = "c" * 64


def _event(candidate: str, node: str, outcome: str, output: str, seq: int, trade_id=None):
    return FunnelEvent(
        event_id=f"{seq:064x}", timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), symbol="EURUSD",
        dataset_sha256=H, funnel_sha256=F, node_id=node, rule_version="1", input_json="{}",
        output=output, outcome=outcome, measurements_json="{}", trade_id=trade_id,
    )


def _run(candidate: str, *, confirmation_pass: bool, trade: bool = False):
    events = [_event(candidate, "sweep", "PASS", "PASS", 1)]
    events.append(_event(candidate, "confirm", "PASS" if confirmation_pass else "FAIL",
                         "PASS" if confirmation_pass else "NO_CONFIRMATION", 2))
    trades = ()
    if confirmation_pass and trade:
        events.append(_event(candidate, "entry", "PASS", "TRADE", 3, trade_id=f"t-{candidate}"))
        trades = (TradeResult(trade_id=f"t-{candidate}", direction="LONG", management="FIXED_R",
                              entry=100, stop=99, target=105, exit=105, result_r=5),)
    return FunnelRunResult(candidate_id=candidate, symbol="EURUSD", dataset_sha256=H,
                           dataset_role="DEVELOPMENT", funnel_sha256=F,
                           events=tuple(events), trades=trades)


def _definition():
    return DiagnosticDefinition(
        diagnostic_id="THREE_FUNNEL_V0_2", version="0.2.0", strategy_sha256=S,
        bindings=(
            DiagnosticRuleBinding(node_id="sweep", funnel_group=FunnelGroup.TRIGGER, sequence=10),
            DiagnosticRuleBinding(node_id="confirm", funnel_group=FunnelGroup.CONFIRMATION, sequence=10),
            DiagnosticRuleBinding(node_id="entry", funnel_group=FunnelGroup.OUTCOME, sequence=10),
        ),
    )


def test_three_funnel_flow_and_conditional_metrics_are_descriptive():
    results = tuple(_run(f"c{i}", confirmation_pass=i < 5, trade=i < 5) for i in range(40))
    future = {f"c{i}": (0.10 if i < 5 else 0.09) for i in range(40)}
    report = analyze_three_funnel(_definition(), results, downstream_outcomes_r=future)
    assert report.status == "DEVELOPMENT_DIAGNOSTIC_ONLY"
    assert report.edge_verified_authorized is False
    trigger, confirmation, outcome = report.groups
    assert trigger.flow_pct == 100.0
    assert confirmation.input_n == 40
    assert confirmation.pass_n == 5
    assert confirmation.flow_pct == 12.5
    assert outcome.pass_n == 5
    confirm = confirmation.rules[0]
    assert confirm.pass_downstream_expectancy_r == pytest.approx(0.10)
    assert confirm.fail_downstream_expectancy_r == pytest.approx(0.09)
    assert WeakPointLabel.LOW_DISCRIMINATION in {x.label for x in report.weak_points}


def test_tp_reachability_is_separate_from_realized_exit_policy_economics():
    results = tuple(_run(f"c{i}", confirmation_pass=True, trade=True) for i in range(40))
    excursions = tuple(
        ExcursionObservation(candidate_id=f"c{i}", trade_id=f"t-c{i}",
                             mfe_r=5.2 if i < 4 else 2.2, mae_r=0.4, observation_policy_id="OBS_V1")
        for i in range(40)
    )
    policies = tuple(
        ExitPolicyResult(candidate_id=f"c{i}", trade_id=f"t-c{i}", policy_id="EXIT_2R_V1",
                         net_result_r=2.0 if i < 24 else -1.0)
        for i in range(40)
    ) + tuple(
        ExitPolicyResult(candidate_id=f"c{i}", trade_id=f"t-c{i}", policy_id="EXIT_5R_V1",
                         net_result_r=5.0 if i < 4 else -1.0)
        for i in range(40)
    )
    report = analyze_three_funnel(_definition(), results, excursions=excursions,
                                  exit_policy_results=policies)
    reaches = {x.target_r: x.reached_pct for x in report.target_reachability}
    assert reaches[2.0] == 100.0
    assert reaches[5.0] == 10.0
    economics = {x.policy_id: x for x in report.exit_policies}
    assert economics["EXIT_2R_V1"].expectancy_r == pytest.approx(0.8)
    assert economics["EXIT_5R_V1"].expectancy_r == pytest.approx(-0.4)
    assert WeakPointLabel.TP_TOO_AMBITIOUS_CANDIDATE in {x.label for x in report.weak_points}


def test_unmapped_nodes_and_non_development_runs_fail_closed():
    result = _run("c1", confirmation_pass=True, trade=True)
    bad_definition = DiagnosticDefinition(
        diagnostic_id="BAD", version="1", strategy_sha256=S,
        bindings=(DiagnosticRuleBinding(node_id="sweep", funnel_group=FunnelGroup.TRIGGER, sequence=1),),
    )
    with pytest.raises(ValueError, match="unmapped strategy nodes"):
        analyze_three_funnel(bad_definition, [result])
    with pytest.raises(ValueError, match="DEVELOPMENT-only"):
        analyze_three_funnel(_definition(), [result.model_copy(update={"dataset_role": "OOS"})])


def test_mapping_changes_diagnostic_identity():
    before = _definition()
    after = before.model_copy(update={"bindings": (
        DiagnosticRuleBinding(node_id="sweep", funnel_group=FunnelGroup.CONFIRMATION, sequence=20),
        *before.bindings[1:],
    )})
    assert before.sha256 != after.sha256
