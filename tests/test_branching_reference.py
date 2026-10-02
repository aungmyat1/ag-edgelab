from ag_edgelab.analytics.branching import compare_funnel_variants, compute_branching_analytics
from ag_edgelab.strategies.reference_branching import (build_reference_variants, run_reference_variant,
                                                        synthetic_development_opportunities)
from ag_edgelab.verification.production import EdgeVerdict, EdgeVerifier, VerificationContext
from ag_edgelab.verification.provenance import (ContentAddressedStore, EngineRecord, EngineRegistry,
                                                 ExposureLedger, VerificationResolvers)


def test_reference_branching_mvp_end_to_end_and_edge_authority_separation():
    v1, v1_1, registry = build_reference_variants()
    opportunities = synthetic_development_opportunities()
    old_results = run_reference_variant(v1, registry, opportunities)
    new_results = run_reference_variant(v1_1, registry, opportunities)

    old_nodes = {n.node_id: n.rule.sha256 for n in v1.definition.nodes}
    new_nodes = {n.node_id: n.rule.sha256 for n in v1_1.definition.nodes}
    changed = {node_id for node_id in old_nodes if old_nodes[node_id] != new_nodes[node_id]}
    assert changed == {"range_route"}
    assert v1.sha256 != v1_1.sha256

    old_boundary = next(e for e in old_results[3].events if e.node_id == "range_route")
    new_boundary = next(e for e in new_results[3].events if e.node_id == "range_route")
    assert (old_boundary.output, new_boundary.output) == ("SWEEP_SETUP", "RANGE_SETUP")
    for variant, results in ((v1, old_results), (v1_1, new_results)):
        for opportunity, result in zip(opportunities, results):
            assert result.status == "DEVELOPMENT_CANDIDATE"
            assert result.dataset_role == "DEVELOPMENT"
            assert result.dataset_sha256 == opportunity.dataset_sha256
            assert result.funnel_sha256 == variant.sha256
            assert result.events
            assert len({event.event_id for event in result.events}) == len(result.events)
            assert all(event.timestamp == opportunity.as_of and event.symbol == opportunity.symbol
                       and event.dataset_sha256 == opportunity.dataset_sha256
                       and event.funnel_sha256 == variant.sha256 for event in result.events)
            for trade in result.trades:
                terminal = next(event for event in result.events if event.trade_id == trade.trade_id)
                assert terminal.outcome == "TRADE"
                assert all(value is not None for value in (trade.entry, trade.stop, trade.target,
                                                            trade.direction, trade.management, trade.exit, trade.result_r))

    old_analytics = compute_branching_analytics(old_results)
    new_analytics = compute_branching_analytics(new_results)
    assert old_analytics.candidate_n == new_analytics.candidate_n == len(opportunities)
    assert old_analytics.trade_count == new_analytics.trade_count == len(opportunities)
    old_route = next(s for s in old_analytics.node_stats if s.node_id == "range_route")
    new_route = next(s for s in new_analytics.node_stats if s.node_id == "range_route")
    assert dict(old_route.route_counts) != dict(new_route.route_counts)
    future = {op.candidate_id: op.attributes["result_r"] for op in opportunities}
    old_route = next(s for s in compute_branching_analytics(old_results, future_outcomes_r=future).node_stats
                     if s.node_id == "range_route")
    new_route = next(s for s in compute_branching_analytics(new_results, future_outcomes_r=future).node_stats
                     if s.node_id == "range_route")
    assert dict(old_route.route_future_expectancy_r) != dict(new_route.route_future_expectancy_r)
    comparison = compare_funnel_variants(v1, v1_1, old_results, new_results,
                                         before_future_outcomes_r=future, after_future_outcomes_r=future)
    assert comparison.status == "DEVELOPMENT_CANDIDATE"
    assert {change.node_id for change in comparison.changed_rules} == changed

    frozen = v1.freeze()
    assert frozen.frozen
    approved = EngineRegistry.owner_approved_pair((
        EngineRecord(engine_id="synthetic-a", code_sha256="a" * 64, independence_group="A"),
        EngineRecord(engine_id="synthetic-b", code_sha256="b" * 64, independence_group="B"),
    ))
    empty = ContentAddressedStore.build({})
    verifier = EdgeVerifier(VerificationContext(VerificationResolvers(
        empty, empty, empty, approved, ExposureLedger())))
    assert verifier.verify_edge(frozen.sha256).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE
    assert all(result.status != EdgeVerdict.EDGE_VERIFIED.value for result in old_results + new_results)


def test_reference_rule_graph_covers_all_four_terminal_branches():
    v1, _, registry = build_reference_variants()
    results = run_reference_variant(v1, registry, synthetic_development_opportunities())
    paths = [{event.node_id for event in result.events} for result in results]
    assert {"trend_buy"} <= paths[0]
    assert {"trend_sell"} <= paths[1]
    assert {"range_setup"} <= paths[2]
    assert {"sweep_setup"} <= paths[3]
    assert {"sweep_setup"} <= paths[4]
