from datetime import datetime, timezone

from ag_edgelab.analytics.branching import compare_funnel_variants, compute_branching_analytics
from ag_edgelab.contracts.branching import DecisionEdge, FunnelDefinition, FunnelEvent, FunnelRunResult, FunnelVariant, NodeType, RuleNode, RuleVersion, TradeResult
from ag_edgelab.data.fingerprint import canonical_json

Z = timezone.utc


def rule(version="1", behavior=None):
    return RuleVersion(rule_id="SWEEP", version=version, node_type=NodeType.FILTER,
                       implementation_sha256="a" * 64,
                       behavior_json=canonical_json({"threshold": 1} if behavior is None else behavior))


def definition():
    terminal = RuleVersion(rule_id="TRADE", version="1", node_type=NodeType.TRADE,
                           implementation_sha256="b" * 64, behavior_json="{}")
    return FunnelDefinition(funnel_id="SYNTH", version="1", entry_node_id="sweep",
                            nodes=(RuleNode(node_id="sweep", rule=rule(), edges=(DecisionEdge(output="PASS", target_node_id="trade"),)),
                                   RuleNode(node_id="trade", rule=terminal)))


def run(candidate, funnel_sha, *, rejected=False):
    dataset = "d" * 64
    ts = datetime(2026, 1, 1, tzinfo=Z)
    event = FunnelEvent(event_id=("a" if candidate == "a" else "b") * 64, timestamp=ts,
                        symbol="SYN", dataset_sha256=dataset, funnel_sha256=funnel_sha,
                        node_id="route", rule_version="ROUTE@1", input_json="{}",
                        output="FAIL" if rejected else "TREND", outcome="FAIL" if rejected else "ROUTE",
                        measurements_json="{}")
    events = [event]
    trades = ()
    if not rejected:
        trade = TradeResult(trade_id=f"{candidate}-trade", direction="LONG", entry=10, stop=9,
                            target=12, exit=12, result_r=2.0)
        events.append(FunnelEvent(event_id=("c" if candidate == "a" else "e") * 64, timestamp=ts,
                                  symbol="SYN", dataset_sha256=dataset, funnel_sha256=funnel_sha,
                                  node_id="terminal", rule_version="TRADE@1", input_json="{}",
                                  output="TRADE", outcome="TRADE", measurements_json="{}",
                                  trade_id=trade.trade_id))
        trades = (trade,)
    return FunnelRunResult(candidate_id=candidate, symbol="SYN", dataset_sha256=dataset,
                           funnel_sha256=funnel_sha, events=tuple(events), trades=trades)


def test_node_analytics_reconcile_counts_and_recompute_metrics():
    variant = FunnelVariant(definition=definition())
    results = (run("a", variant.sha256), run("b", variant.sha256, rejected=True))
    stats = compute_branching_analytics(results, future_outcomes_r={"a": 2.0, "b": -1.0})
    route = next(s for s in stats.node_stats if s.node_id == "route")
    terminal = next(s for s in stats.node_stats if s.node_id == "terminal")
    assert (route.input_n, route.passed_or_routed_n, route.rejected_n) == (2, 1, 1)
    assert route.pass_rate == route.passed_or_routed_n / route.input_n
    assert route.pass_future_expectancy_r == 2.0
    assert route.fail_future_expectancy_r == -1.0
    assert (stats.trade_count, stats.win_rate, stats.expectancy_r) == (1, 1.0, 2.0)
    assert terminal.terminal_trade_n == 1 and terminal.win_rate == 1.0


def test_variant_comparison_reports_rule_and_node_differences_as_development():
    before = FunnelVariant(definition=definition())
    changed_nodes = tuple(node.model_copy(update={"rule": rule("2", behavior={"threshold": 2})})
                          if node.node_id == "sweep" else node for node in before.definition.nodes)
    after_def = before.definition.model_copy(update={"version": "2", "nodes": changed_nodes})
    after = FunnelVariant(definition=after_def, parent_sha256=before.sha256)
    # Use a graph with stable node ids in both result sets for directly comparable analytics.
    before_runs = (run("a", before.sha256), run("b", before.sha256, rejected=True))
    after_runs = (run("a", after.sha256), run("b", after.sha256, rejected=True))
    report = compare_funnel_variants(before, after, before_runs, after_runs)
    assert report.status == "DEVELOPMENT_CANDIDATE"
    assert report.before.trade_count == report.after.trade_count == 1
    assert {change.node_id for change in report.changed_rules} == {"sweep"}
    assert {row.node_id for row in report.node_differences} == {"route", "terminal"}
