from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from ag_edgelab.contracts.branching import FunnelRunResult, FunnelVariant


class NodeAnalytics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node_id: str
    input_n: int
    passed_or_routed_n: int
    rejected_n: int
    pass_rate: float
    route_counts: tuple[tuple[str, int], ...]
    route_future_expectancy_r: tuple[tuple[str, float], ...]
    terminal_trade_n: int
    win_rate: float | None
    avg_win_r: float | None
    avg_loss_r: float | None
    expectancy_r: float | None
    profit_factor: float | None
    max_drawdown_r: float | None
    pass_future_expectancy_r: float | None
    fail_future_expectancy_r: float | None


class FunnelAnalytics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    funnel_sha256: str
    dataset_role: str
    candidate_n: int
    node_stats: tuple[NodeAnalytics, ...]
    trade_count: int
    win_rate: float | None
    expectancy_r: float | None
    profit_factor: float | None
    max_drawdown_r: float | None


class RuleChange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node_id: str
    before_rule_sha256: str | None
    after_rule_sha256: str | None


class NodeDifference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node_id: str
    before: NodeAnalytics | None
    after: NodeAnalytics | None


class FunnelVariantComparison(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: str = "DEVELOPMENT_CANDIDATE"
    before_funnel_sha256: str
    after_funnel_sha256: str
    changed_rules: tuple[RuleChange, ...]
    before: FunnelAnalytics
    after: FunnelAnalytics
    node_differences: tuple[NodeDifference, ...]


def _metrics(rs: Sequence[float]) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    if not rs:
        return None, None, None, None, None
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    equity = peak = drawdown = 0.0
    for value in rs:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    profit_factor = gross_win / gross_loss if gross_loss else (math.inf if gross_win else None)
    return (len(wins) / len(rs), sum(wins) / len(wins) if wins else None,
            sum(losses) / len(losses) if losses else None, sum(rs) / len(rs), profit_factor)


def _drawdown(rs: Sequence[float]) -> float | None:
    if not rs:
        return None
    equity = peak = drawdown = 0.0
    for value in rs:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def compute_branching_analytics(
    results: Sequence[FunnelRunResult], *, future_outcomes_r: Mapping[str, float] | None = None,
) -> FunnelAnalytics:
    if len({r.candidate_id for r in results}) != len(results):
        raise ValueError("candidate ids must be unique within analytics input")
    roles = {r.dataset_role for r in results}
    funnels = {r.funnel_sha256 for r in results}
    if len(roles) > 1 or len(funnels) > 1:
        raise ValueError("analytics input must use one dataset role and funnel identity")
    all_trades = [trade for result in results for trade in result.trades]
    all_rs = [float(trade.result_r) for trade in all_trades]
    wr, _, _, expectancy, pf = _metrics(all_rs)
    nodes: dict[str, list[tuple[FunnelRunResult, object]]] = defaultdict(list)
    trades_by_id = {(result.candidate_id, trade.trade_id): trade
                    for result in results for trade in result.trades}
    for result in results:
        for event in result.events:
            nodes[event.node_id].append((result, event))
    future = future_outcomes_r or {}
    stats = []
    for node_id in sorted(nodes):
        entries = nodes[node_id]
        routed = sum(event.outcome != "FAIL" for _, event in entries)
        rejected = len(entries) - routed
        route_counts = Counter(event.output for _, event in entries)
        route_outcomes: dict[str, list[float]] = defaultdict(list)
        for result, event in entries:
            if result.candidate_id in future:
                route_outcomes[event.output].append(float(future[result.candidate_id]))
        node_trades = [trades_by_id[(result.candidate_id, event.trade_id)] for result, event in entries
                       if event.trade_id is not None and (result.candidate_id, event.trade_id) in trades_by_id]
        rs = [float(trade.result_r) for trade in node_trades]
        nwr, avg_win, avg_loss, exp, node_pf = _metrics(rs)
        passed_future = [float(future[result.candidate_id]) for result, event in entries
                         if event.outcome != "FAIL" and result.candidate_id in future]
        failed_future = [float(future[result.candidate_id]) for result, event in entries
                         if event.outcome == "FAIL" and result.candidate_id in future]
        stats.append(NodeAnalytics(
            node_id=node_id, input_n=len(entries), passed_or_routed_n=routed, rejected_n=rejected,
            pass_rate=routed / len(entries) if entries else 0.0,
            route_counts=tuple(sorted(route_counts.items())),
            route_future_expectancy_r=tuple((route, sum(values) / len(values))
                                             for route, values in sorted(route_outcomes.items())),
            terminal_trade_n=len(node_trades),
            win_rate=nwr, avg_win_r=avg_win, avg_loss_r=avg_loss, expectancy_r=exp,
            profit_factor=node_pf, max_drawdown_r=_drawdown(rs),
            pass_future_expectancy_r=sum(passed_future) / len(passed_future) if passed_future else None,
            fail_future_expectancy_r=sum(failed_future) / len(failed_future) if failed_future else None,
        ))
    return FunnelAnalytics(
        funnel_sha256=next(iter(funnels), "0" * 64), dataset_role=next(iter(roles), "DEVELOPMENT"),
        candidate_n=len(results), node_stats=tuple(stats), trade_count=len(all_trades),
        win_rate=wr, expectancy_r=expectancy, profit_factor=pf, max_drawdown_r=_drawdown(all_rs),
    )


def compare_funnel_variants(
    before_variant: FunnelVariant, after_variant: FunnelVariant,
    before_results: Sequence[FunnelRunResult], after_results: Sequence[FunnelRunResult],
    *, before_future_outcomes_r: Mapping[str, float] | None = None,
    after_future_outcomes_r: Mapping[str, float] | None = None,
) -> FunnelVariantComparison:
    if before_variant.frozen or after_variant.frozen:
        raise ValueError("variant comparison is a DEVELOPMENT operation")
    if any(result.dataset_role != "DEVELOPMENT" for result in (*before_results, *after_results)):
        raise ValueError("variant comparison requires DEVELOPMENT runs")
    if any(result.funnel_sha256 != before_variant.sha256 for result in before_results):
        raise ValueError("before runs do not match the before variant")
    if any(result.funnel_sha256 != after_variant.sha256 for result in after_results):
        raise ValueError("after runs do not match the after variant")
    if ({result.candidate_id for result in before_results} != {result.candidate_id for result in after_results}
            or {result.dataset_sha256 for result in before_results} != {result.dataset_sha256 for result in after_results}):
        raise ValueError("variant comparison requires identical candidates and datasets")
    old_rules = {node.node_id: node.rule.sha256 for node in before_variant.definition.nodes}
    new_rules = {node.node_id: node.rule.sha256 for node in after_variant.definition.nodes}
    changes = tuple(RuleChange(node_id=node_id, before_rule_sha256=old_rules.get(node_id),
                               after_rule_sha256=new_rules.get(node_id))
                    for node_id in sorted(old_rules.keys() | new_rules.keys())
                    if old_rules.get(node_id) != new_rules.get(node_id))
    before = compute_branching_analytics(before_results, future_outcomes_r=before_future_outcomes_r)
    after = compute_branching_analytics(after_results, future_outcomes_r=after_future_outcomes_r)
    before_nodes = {stat.node_id: stat for stat in before.node_stats}
    after_nodes = {stat.node_id: stat for stat in after.node_stats}
    differences = tuple(NodeDifference(node_id=node_id, before=before_nodes.get(node_id), after=after_nodes.get(node_id))
                        for node_id in sorted(before_nodes.keys() | after_nodes.keys()))
    return FunnelVariantComparison(before_funnel_sha256=before_variant.sha256, after_funnel_sha256=after_variant.sha256,
                                   changed_rules=changes, before=before, after=after, node_differences=differences)
