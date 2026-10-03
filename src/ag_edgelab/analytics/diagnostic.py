from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from ag_edgelab.contracts.branching import FunnelRunResult
from ag_edgelab.contracts.diagnostic import (
    DiagnosticDefinition,
    ExcursionObservation,
    ExitPolicyResult,
    FunnelGroup,
    WeakPointLabel,
)


class RuleDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node_id: str
    funnel_group: FunnelGroup
    sequence: int
    input_n: int
    pass_n: int
    fail_n: int
    pass_pct: float
    reason_counts: tuple[tuple[str, int], ...]
    pass_downstream_expectancy_r: float | None
    fail_downstream_expectancy_r: float | None


class GroupDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    funnel_group: FunnelGroup
    input_n: int
    pass_n: int
    flow_pct: float
    rules: tuple[RuleDiagnostic, ...]


class TargetReachability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    target_r: float
    reached_n: int
    reached_pct: float


class ExitPolicyDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    policy_id: str
    trade_n: int
    win_rate_pct: float | None
    expectancy_r: float | None
    profit_factor: float | None
    max_drawdown_r: float | None


class WeakPointFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    label: WeakPointLabel
    scope: str
    evidence: str


class StrategyDiagnosticReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: str = "DEVELOPMENT_DIAGNOSTIC_ONLY"
    diagnostic_sha256: str
    strategy_sha256: str
    dataset_role: str
    candidate_n: int
    groups: tuple[GroupDiagnostic, ...]
    target_reachability: tuple[TargetReachability, ...]
    median_mfe_r: float | None
    median_mae_r: float | None
    exit_policies: tuple[ExitPolicyDiagnostic, ...]
    weak_points: tuple[WeakPointFinding, ...]
    edge_verified_authorized: bool = False


class DiagnosticPolicy(BaseModel):
    """Transparent heuristic policy. Findings create hypotheses; they never change rules."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    min_sample_n: int = Field(default=30, ge=1)
    over_filter_pass_pct: float = Field(default=10.0, ge=0, le=100)
    low_discrimination_delta_r: float = Field(default=0.03, ge=0)
    entry_unreachable_pct: float = Field(default=2.0, ge=0, le=100)
    ambitious_tp_reach_pct: float = Field(default=15.0, ge=0, le=100)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _economics(values: Sequence[float]) -> tuple[float | None, float | None, float | None, float | None]:
    if not values:
        return None, None, None, None
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_win / gross_loss if gross_loss else (math.inf if gross_win else None)
    equity = peak = dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return len(wins) / len(values) * 100.0, _mean(values), pf, dd


def analyze_three_funnel(
    definition: DiagnosticDefinition,
    results: Sequence[FunnelRunResult],
    *,
    downstream_outcomes_r: Mapping[str, float] | None = None,
    excursions: Sequence[ExcursionObservation] = (),
    exit_policy_results: Sequence[ExitPolicyResult] = (),
    targets_r: Sequence[float] = (1.0, 2.0, 3.0, 4.0, 5.0),
    policy: DiagnosticPolicy | None = None,
) -> StrategyDiagnosticReport:
    """Analyze flow and outcomes without granting verification authority.

    ``downstream_outcomes_r`` are explicitly conditional diagnostics, not causal
    counterfactuals. Missing failed-route outcomes remain unavailable.
    """
    policy = policy or DiagnosticPolicy()
    if len({r.candidate_id for r in results}) != len(results):
        raise ValueError("candidate ids must be unique")
    roles = {r.dataset_role for r in results}
    if len(roles) > 1:
        raise ValueError("one diagnostic run cannot mix dataset roles")
    if any(r.dataset_role != "DEVELOPMENT" for r in results):
        raise ValueError("three-funnel diagnosis is DEVELOPMENT-only")

    binding_by_node = {item.node_id: item for item in definition.bindings}
    unknown = {event.node_id for result in results for event in result.events} - set(binding_by_node)
    if unknown:
        raise ValueError(f"unmapped strategy nodes: {sorted(unknown)}")

    future = downstream_outcomes_r or {}
    by_node: dict[str, list[tuple[FunnelRunResult, object]]] = defaultdict(list)
    for result in results:
        for event in result.events:
            by_node[event.node_id].append((result, event))

    rule_stats: list[RuleDiagnostic] = []
    for binding in sorted(definition.bindings, key=lambda x: (x.funnel_group, x.sequence, x.node_id)):
        entries = by_node.get(binding.node_id, [])
        passed = [(r, e) for r, e in entries if e.outcome != "FAIL"]
        failed = [(r, e) for r, e in entries if e.outcome == "FAIL"]
        pass_future = [float(future[r.candidate_id]) for r, _ in passed if r.candidate_id in future]
        fail_future = [float(future[r.candidate_id]) for r, _ in failed if r.candidate_id in future]
        reasons = Counter(e.output for _, e in failed)
        rule_stats.append(RuleDiagnostic(
            node_id=binding.node_id,
            funnel_group=binding.funnel_group,
            sequence=binding.sequence,
            input_n=len(entries),
            pass_n=len(passed),
            fail_n=len(failed),
            pass_pct=(len(passed) / len(entries) * 100.0) if entries else 0.0,
            reason_counts=tuple(sorted(reasons.items())),
            pass_downstream_expectancy_r=_mean(pass_future),
            fail_downstream_expectancy_r=_mean(fail_future),
        ))

    groups: list[GroupDiagnostic] = []
    for group in FunnelGroup:
        rules = tuple(sorted((s for s in rule_stats if s.funnel_group == group), key=lambda x: x.sequence))
        input_n = rules[0].input_n if rules else 0
        pass_n = rules[-1].pass_n if rules else 0
        groups.append(GroupDiagnostic(
            funnel_group=group,
            input_n=input_n,
            pass_n=pass_n,
            flow_pct=(pass_n / input_n * 100.0) if input_n else 0.0,
            rules=rules,
        ))

    excursion_by_trade = {(x.candidate_id, x.trade_id): x for x in excursions}
    known_trades = {(r.candidate_id, t.trade_id) for r in results for t in r.trades}
    if set(excursion_by_trade) - known_trades:
        raise ValueError("excursion evidence references unknown trades")
    reachability = tuple(
        TargetReachability(
            target_r=float(target),
            reached_n=sum(x.mfe_r >= target for x in excursions),
            reached_pct=(sum(x.mfe_r >= target for x in excursions) / len(excursions) * 100.0) if excursions else 0.0,
        )
        for target in targets_r
    )

    policy_values: dict[str, list[float]] = defaultdict(list)
    for item in exit_policy_results:
        if (item.candidate_id, item.trade_id) not in known_trades:
            raise ValueError("exit policy evidence references unknown trades")
        policy_values[item.policy_id].append(float(item.net_result_r))
    exit_stats = []
    for policy_id, values in sorted(policy_values.items()):
        wr, exp, pf, dd = _economics(values)
        exit_stats.append(ExitPolicyDiagnostic(policy_id=policy_id, trade_n=len(values), win_rate_pct=wr,
                                               expectancy_r=exp, profit_factor=pf, max_drawdown_r=dd))

    findings: list[WeakPointFinding] = []
    for stat in rule_stats:
        if stat.input_n < policy.min_sample_n:
            findings.append(WeakPointFinding(label=WeakPointLabel.INSUFFICIENT_SAMPLE, scope=stat.node_id,
                                             evidence=f"input_n={stat.input_n} < {policy.min_sample_n}"))
            continue
        if stat.pass_pct <= policy.over_filter_pass_pct:
            label = (WeakPointLabel.CONFIRMATION_ATTRITION
                     if stat.funnel_group == FunnelGroup.CONFIRMATION else WeakPointLabel.LOW_FLOW)
            findings.append(WeakPointFinding(label=label, scope=stat.node_id,
                                             evidence=f"pass_pct={stat.pass_pct:.2f}"))
        if stat.pass_downstream_expectancy_r is not None and stat.fail_downstream_expectancy_r is not None:
            delta = stat.pass_downstream_expectancy_r - stat.fail_downstream_expectancy_r
            if abs(delta) <= policy.low_discrimination_delta_r:
                findings.append(WeakPointFinding(label=WeakPointLabel.LOW_DISCRIMINATION, scope=stat.node_id,
                                                 evidence=f"conditional_expectancy_delta_r={delta:.6f}"))

    if reachability:
        max_target = max(reachability, key=lambda x: x.target_r)
        if len(excursions) >= policy.min_sample_n and max_target.reached_pct <= policy.ambitious_tp_reach_pct:
            findings.append(WeakPointFinding(label=WeakPointLabel.TP_TOO_AMBITIOUS_CANDIDATE,
                                             scope=f"{max_target.target_r:g}R",
                                             evidence=f"reach_pct={max_target.reached_pct:.2f}"))
    if not findings:
        findings.append(WeakPointFinding(label=WeakPointLabel.NO_DIAGNOSIS, scope="STRATEGY",
                                         evidence="no configured diagnostic threshold fired"))

    return StrategyDiagnosticReport(
        diagnostic_sha256=definition.sha256,
        strategy_sha256=definition.strategy_sha256,
        dataset_role=next(iter(roles), "DEVELOPMENT"),
        candidate_n=len(results),
        groups=tuple(groups),
        target_reachability=reachability,
        median_mfe_r=_median([x.mfe_r for x in excursions]),
        median_mae_r=_median([x.mae_r for x in excursions]),
        exit_policies=tuple(exit_stats),
        weak_points=tuple(findings),
    )
