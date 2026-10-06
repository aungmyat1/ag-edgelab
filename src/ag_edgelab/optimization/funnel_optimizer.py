"""Development-only Funnel Optimizer V1 primitives.

This is deliberately an *opportunity* evaluator rather than a trading engine.
It has no broker, order, data-loader, OOS, or holdout capability.  Callers hand
it facts that were produced by an authorized DEVELOPMENT replay and a reference
outcome model.  The evaluator then makes the normally hidden rejected
opportunities explicit, without relabelling a counterfactual outcome as a
trade.

The module is intentionally small and conservative:

* rules are tri-state: ``PASS``, ``FAIL``, or ``NOT_EVALUABLE``;
* only declared dependency failures make a downstream cell NOT_EVALUABLE;
* reference outcomes are separate from actual trade outcomes at every layer;
* only table-query-safe filters/removals can create fast children;
* path-dependent semantics fail closed with ``REQUIRES_FULL_REPLAY``;
* parent eligibility is DEVELOPMENT-only and samples the same eligible
  opportunity/time strata with an explicit seed and baseline-count authority.

It is a research analysis substrate, never an execution or promotion surface.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from statistics import mean
from typing import Callable, Mapping, Sequence

from ag_edgelab.contracts.dataset import DatasetRole
from ag_edgelab.data.fingerprint import canonical_json, sha256_json
from ag_edgelab.optimization.governance import (OptimizationGovernanceError,
                                                assert_optimization_allowed)
from ag_edgelab.optimization.contracts import DatasetExposure

UTC = timezone.utc


class RuleState(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUABLE = "NOT_EVALUABLE"


class ReferenceOutcomeStatus(StrEnum):
    EVALUABLE = "EVALUABLE"
    NOT_EVALUABLE = "NOT_EVALUABLE"


class OutcomeAuthority(StrEnum):
    REFERENCE_OUTCOME = "REFERENCE_OUTCOME"
    UNAVAILABLE = "UNAVAILABLE"


class RuleSemantics(StrEnum):
    """Whether table-only selection can preserve a rule's meaning."""

    TABLE_QUERY_SAFE = "TABLE_QUERY_SAFE"
    REQUIRES_FULL_REPLAY = "REQUIRES_FULL_REPLAY"


class AblationStatus(StrEnum):
    VALID = "VALID"
    REQUIRES_FULL_REPLAY = "REQUIRES_FULL_REPLAY"


class ChildStatus(StrEnum):
    EVALUATED = "EVALUATED"
    REQUIRES_FULL_REPLAY = "REQUIRES_FULL_REPLAY"
    FAILED = "FAILED"


class EligibilityMode(StrEnum):
    STRUCTURAL = "STRUCTURAL"
    ECONOMIC = "ECONOMIC"


class EconomicRankingStatus(StrEnum):
    BLOCKED = "BLOCKED"
    AVAILABLE = "AVAILABLE"


class EligibilityVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED_RANDOM_BASELINE_COUNT = "BLOCKED_RANDOM_BASELINE_COUNT"
    BLOCKED_INSUFFICIENT_REFERENCE_OUTCOMES = "BLOCKED_INSUFFICIENT_REFERENCE_OUTCOMES"


class CampaignState(StrEnum):
    ACTIVE = "ACTIVE"
    DEV_REJECTED_NO_SIGNAL = "DEV_REJECTED_NO_SIGNAL"
    STRUCTURAL_ELIGIBLE_NOT_EDGE = "STRUCTURAL_ELIGIBLE_NOT_EDGE"


class FastChildError(ValueError):
    """Raised when a requested fast child is not an exact table query."""


@dataclass(frozen=True)
class RuleEvaluation:
    """A rule result before it is attached to an event row.

    ``feature_values`` contains only values the evaluator actually observed.
    An evaluator must not manufacture feature values for a NOT_EVALUABLE rule.
    """

    state: RuleState
    reason_code: str
    feature_values: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.reason_code:
            raise ValueError("rule evaluation needs a reason_code")
        if self.state is RuleState.NOT_EVALUABLE and self.feature_values:
            # A feature can be separately recorded upstream, but calling it a
            # value *for this rule* would imply the rule was evaluable.
            raise ValueError("NOT_EVALUABLE rules cannot claim required feature values")


@dataclass(frozen=True)
class RuleCell:
    rule_id: str
    state: RuleState
    reason_code: str
    feature_values: Mapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "feature_values": dict(sorted(self.feature_values.items())),
            "reason_code": self.reason_code,
            "rule_id": self.rule_id,
            "rule_state": self.state.value,
        }


RuleEvaluator = Callable[["Opportunity"], RuleEvaluation]


@dataclass(frozen=True)
class RuleSpec:
    """One evaluator in a relaxed opportunity replay.

    A dependency says that the dependent rule has no defined semantic input
    unless every listed rule passed.  It does *not* mean an unrelated later
    rule should be skipped after an earlier failure.  That distinction is what
    lets a relaxed replay retain independent, evaluable diagnostics.
    """

    rule_id: str
    evaluator: RuleEvaluator
    depends_on: tuple[str, ...] = ()
    semantics: RuleSemantics = RuleSemantics.TABLE_QUERY_SAFE
    query_feature: str | None = None

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise ValueError("rule_id is required")
        if self.query_feature is not None and self.semantics is not RuleSemantics.TABLE_QUERY_SAFE:
            raise ValueError("only table-query-safe rules may name query_feature")


@dataclass(frozen=True)
class Opportunity:
    """Authorized facts for exactly one possible parent opportunity."""

    event_id: str
    candidate_id: str
    timestamp_utc: datetime
    symbol: str
    session: str
    dataset_id: str
    strategy_id: str
    engine_id: str
    feature_values: Mapping[str, object] = field(default_factory=dict)
    reference_outcome_r: float | None = None
    actual_outcome_r: float | None = None

    def __post_init__(self) -> None:
        if not all((self.event_id, self.candidate_id, self.symbol, self.session,
                    self.dataset_id, self.strategy_id, self.engine_id)):
            raise ValueError("opportunity identity fields must be non-empty")
        if self.timestamp_utc.tzinfo is None or self.timestamp_utc.utcoffset() != timezone.utc.utcoffset(self.timestamp_utc):
            raise ValueError("timestamp_utc must be an aware UTC datetime")
        for name, value in (("reference_outcome_r", self.reference_outcome_r),
                            ("actual_outcome_r", self.actual_outcome_r)):
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite when present")

    def feature(self, name: str) -> object | None:
        return self.feature_values.get(name)


@dataclass(frozen=True)
class EventRow:
    """A deterministic all-opportunity row with no execution side effects."""

    event_id: str
    candidate_id: str
    sequence_no: int
    timestamp_utc: datetime
    symbol: str
    session: str
    dataset_id: str
    strategy_id: str
    engine_id: str
    rule_cells: Mapping[str, RuleCell]
    reference_outcome_r: float | None
    reference_outcome_status: ReferenceOutcomeStatus
    actual_outcome_r: float | None
    actual_trade: bool
    outcome_authority: OutcomeAuthority

    @property
    def all_rules_pass(self) -> bool:
        return bool(self.rule_cells) and all(c.state is RuleState.PASS for c in self.rule_cells.values())

    def as_dict(self) -> dict[str, object]:
        return {
            "actual_outcome_r": self.actual_outcome_r,
            "actual_trade": self.actual_trade,
            "candidate_id": self.candidate_id,
            "dataset_id": self.dataset_id,
            "engine_id": self.engine_id,
            "event_id": self.event_id,
            "outcome_authority": self.outcome_authority.value,
            "reference_outcome_r": self.reference_outcome_r,
            "reference_outcome_status": self.reference_outcome_status.value,
            "rule_cells": {key: self.rule_cells[key].as_dict() for key in sorted(self.rule_cells)},
            "sequence_no": self.sequence_no,
            "session": self.session,
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "timestamp_utc": self.timestamp_utc.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }


@dataclass(frozen=True)
class EventTable:
    """Chronological, content-addressed event table.

    The hash is over fully normalized rows, not a filename or a process-local
    timestamp.  It therefore remains stable across cache locations and runs.
    """

    rows: tuple[EventRow, ...]
    rules: tuple[RuleSpec, ...]
    dataset_role: DatasetRole = DatasetRole.DEVELOPMENT

    def __post_init__(self) -> None:
        if self.dataset_role is not DatasetRole.DEVELOPMENT:
            raise OptimizationGovernanceError("event tables for optimization must be DEVELOPMENT-only")
        ids = [row.event_id for row in self.rows]
        if len(ids) != len(set(ids)):
            raise ValueError("event_id must be unique")
        order = tuple(sorted(self.rows, key=_event_sort_key))
        if self.rows != order:
            raise ValueError("event table rows must already be chronological and tie-break deterministic")
        if tuple(row.sequence_no for row in self.rows) != tuple(range(1, len(self.rows) + 1)):
            raise ValueError("sequence_no must be contiguous and start at 1")
        rule_ids = tuple(spec.rule_id for spec in self.rules)
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("rule ids must be unique")
        for row in self.rows:
            if tuple(sorted(row.rule_cells)) != tuple(sorted(rule_ids)):
                raise ValueError("each row must contain exactly the declared rule cells")
            if row.actual_trade != row.all_rules_pass:
                raise ValueError("actual_trade must equal all-rules-pass for a relaxed parent replay")
            if not row.actual_trade and row.actual_outcome_r is not None:
                raise ValueError("rejected event cannot carry an actual trade outcome")
            has_reference = row.reference_outcome_r is not None
            if has_reference != (row.reference_outcome_status is ReferenceOutcomeStatus.EVALUABLE):
                raise ValueError("reference_outcome_status does not match reference_outcome_r")
            expected_authority = (OutcomeAuthority.REFERENCE_OUTCOME if has_reference
                                  else OutcomeAuthority.UNAVAILABLE)
            if row.outcome_authority is not expected_authority:
                raise ValueError("outcome_authority does not match reference outcome availability")

    @property
    def sha256(self) -> str:
        return sha256_json(self.as_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            "dataset_role": self.dataset_role.value,
            "rows": [row.as_dict() for row in self.rows],
            "rule_ids": [rule.rule_id for rule in self.rules],
            "schema_version": "FUNNEL_OPTIMIZER_EVENT_TABLE_V1",
        }

    def write_cache(self, path: str | Path) -> tuple[Path, Path]:
        """Persist a deterministic JSONL cache plus a hash manifest.

        The caller supplies a DEVELOPMENT artifact location.  This method does
        not create a data source or imply that its rows are governance-admitted.
        """
        jsonl_path = Path(path)
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with jsonl_path.open("w", encoding="utf-8") as fh:
            for row in self.rows:
                fh.write(canonical_json(row.as_dict()) + "\n")
        manifest_path = jsonl_path.with_suffix(jsonl_path.suffix + ".manifest.json")
        manifest = {
            "content_sha256": self.sha256,
            "dataset_role": self.dataset_role.value,
            "event_rows": len(self.rows),
            "schema_version": "FUNNEL_OPTIMIZER_EVENT_TABLE_CACHE_V1",
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return jsonl_path, manifest_path


def _event_sort_key(row: EventRow) -> tuple[datetime, str, str, str]:
    return (row.timestamp_utc.astimezone(UTC), row.symbol, row.candidate_id, row.event_id)


class RelaxedReplay:
    """Evaluate all semantically defined rule cells for DEVELOPMENT facts.

    This is intentionally not a normal strategy runner: a FAIL in one rule does
    not stop later independent rules.  Only a declared semantic dependency
    produces a NOT_EVALUABLE downstream cell.
    """

    def __init__(self, rules: Sequence[RuleSpec], *, engine_id: str) -> None:
        self.rules = tuple(rules)
        self.engine_id = engine_id
        if not self.rules:
            raise ValueError("relaxed replay needs at least one rule")
        ids = [rule.rule_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("relaxed replay rule ids must be unique")
        known: set[str] = set()
        for rule in self.rules:
            unknown = set(rule.depends_on) - known
            if unknown:
                raise ValueError(f"{rule.rule_id} depends on an unknown or later rule: {sorted(unknown)}")
            known.add(rule.rule_id)

    def evaluate(self, opportunities: Sequence[Opportunity], *, dataset_role: DatasetRole,
                 exposure: DatasetExposure = DatasetExposure.DEVELOPMENT) -> EventTable:
        assert_optimization_allowed(dataset_role, exposure)
        ordered = tuple(sorted(opportunities, key=_opportunity_sort_key))
        if len({op.event_id for op in ordered}) != len(ordered):
            raise ValueError("opportunity event_id must be unique")
        rows: list[EventRow] = []
        for sequence_no, opportunity in enumerate(ordered, start=1):
            cells: dict[str, RuleCell] = {}
            for rule in self.rules:
                failed_dependencies = tuple(
                    dep for dep in rule.depends_on if cells[dep].state is not RuleState.PASS)
                if failed_dependencies:
                    reason = "UPSTREAM_NOT_EVALUABLE:" + ",".join(
                        f"{dep}={cells[dep].state.value}" for dep in failed_dependencies)
                    cells[rule.rule_id] = RuleCell(rule.rule_id, RuleState.NOT_EVALUABLE, reason)
                    continue
                evaluation = rule.evaluator(opportunity)
                cells[rule.rule_id] = RuleCell(
                    rule_id=rule.rule_id,
                    state=evaluation.state,
                    reason_code=evaluation.reason_code,
                    feature_values=dict(evaluation.feature_values),
                )
            all_pass = bool(cells) and all(cell.state is RuleState.PASS for cell in cells.values())
            # A normal parent could only have a realized outcome for an actual
            # all-pass trade.  A reference outcome is a different model and is
            # intentionally retained for every opportunity, including failures.
            actual_outcome = opportunity.actual_outcome_r if all_pass else None
            ref_status = (ReferenceOutcomeStatus.EVALUABLE if opportunity.reference_outcome_r is not None
                          else ReferenceOutcomeStatus.NOT_EVALUABLE)
            authority = (OutcomeAuthority.REFERENCE_OUTCOME if opportunity.reference_outcome_r is not None
                         else OutcomeAuthority.UNAVAILABLE)
            rows.append(EventRow(
                event_id=opportunity.event_id,
                candidate_id=opportunity.candidate_id,
                sequence_no=sequence_no,
                timestamp_utc=opportunity.timestamp_utc.astimezone(UTC),
                symbol=opportunity.symbol,
                session=opportunity.session,
                dataset_id=opportunity.dataset_id,
                strategy_id=opportunity.strategy_id,
                engine_id=self.engine_id,
                rule_cells=cells,
                reference_outcome_r=opportunity.reference_outcome_r,
                reference_outcome_status=ref_status,
                actual_outcome_r=actual_outcome,
                actual_trade=all_pass,
                outcome_authority=authority,
            ))
        return EventTable(tuple(rows), self.rules, dataset_role=dataset_role)


def _opportunity_sort_key(opportunity: Opportunity) -> tuple[datetime, str, str, str]:
    return (opportunity.timestamp_utc.astimezone(UTC), opportunity.symbol,
            opportunity.candidate_id, opportunity.event_id)


def threshold_rule(rule_id: str, *, feature: str, threshold: float,
                   comparator: str = ">=", depends_on: tuple[str, ...] = (),
                   semantics: RuleSemantics = RuleSemantics.TABLE_QUERY_SAFE) -> RuleSpec:
    """Make a feature-only filter suitable for exact fast threshold queries."""
    if comparator not in {">=", ">", "<=", "<"}:
        raise ValueError("comparator must be one of >=, >, <=, <")

    def evaluate(opportunity: Opportunity) -> RuleEvaluation:
        value = opportunity.feature(feature)
        if value is None:
            return RuleEvaluation(RuleState.NOT_EVALUABLE, f"MISSING_FEATURE:{feature}")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
            return RuleEvaluation(RuleState.NOT_EVALUABLE, f"INVALID_FEATURE:{feature}")
        passed = _compare(float(value), threshold, comparator)
        return RuleEvaluation(RuleState.PASS if passed else RuleState.FAIL,
                              "THRESHOLD_PASS" if passed else "THRESHOLD_FAIL",
                              {feature: float(value)})

    return RuleSpec(rule_id, evaluate, depends_on, semantics,
                    feature if semantics is RuleSemantics.TABLE_QUERY_SAFE else None)


def boolean_rule(rule_id: str, *, feature: str, depends_on: tuple[str, ...] = (),
                 semantics: RuleSemantics = RuleSemantics.TABLE_QUERY_SAFE) -> RuleSpec:
    """Make an explicitly observed boolean filter; missing is not false."""
    def evaluate(opportunity: Opportunity) -> RuleEvaluation:
        value = opportunity.feature(feature)
        if value is None or not isinstance(value, bool):
            return RuleEvaluation(RuleState.NOT_EVALUABLE, f"MISSING_OR_INVALID_FEATURE:{feature}")
        return RuleEvaluation(RuleState.PASS if value else RuleState.FAIL,
                              "BOOLEAN_PASS" if value else "BOOLEAN_FAIL", {feature: value})

    return RuleSpec(rule_id, evaluate, depends_on, semantics,
                    feature if semantics is RuleSemantics.TABLE_QUERY_SAFE else None)


def _compare(value: float, threshold: float, comparator: str) -> bool:
    return {
        ">=": value >= threshold,
        ">": value > threshold,
        "<=": value <= threshold,
        "<": value < threshold,
    }[comparator]


@dataclass(frozen=True)
class PerformanceMetrics:
    n: int
    reference_expectancy_r: float | None
    profit_factor: float | None
    max_drawdown_r: float | None
    win_rate: float | None
    total_r: float

    def as_dict(self) -> dict[str, object]:
        return {
            "N": self.n,
            "DD_R": self.max_drawdown_r,
            "PF": self.profit_factor,
            "reference_expectancy_r": self.reference_expectancy_r,
            "total_r": self.total_r,
            "win_rate": self.win_rate,
        }


def reference_metrics(rows: Sequence[EventRow]) -> PerformanceMetrics:
    """Metrics over one reference-outcome population only."""
    outcomes = [float(row.reference_outcome_r) for row in rows
                if row.reference_outcome_status is ReferenceOutcomeStatus.EVALUABLE
                and row.reference_outcome_r is not None]
    if not outcomes:
        return PerformanceMetrics(0, None, None, None, None, 0.0)
    gains = sum(value for value in outcomes if value > 0)
    losses = -sum(value for value in outcomes if value < 0)
    # Infinite PF for all wins is not a meaningful stability/ranking metric.
    pf = gains / losses if gains > 0 and losses > 0 else None
    equity = 0.0
    high_water = 0.0
    max_drawdown = 0.0
    for outcome in outcomes:
        equity += outcome
        high_water = max(high_water, equity)
        max_drawdown = max(max_drawdown, high_water - equity)
    return PerformanceMetrics(
        n=len(outcomes),
        reference_expectancy_r=sum(outcomes) / len(outcomes),
        profit_factor=pf,
        max_drawdown_r=max_drawdown,
        win_rate=sum(outcome > 0 for outcome in outcomes) / len(outcomes),
        total_r=sum(outcomes),
    )


@dataclass(frozen=True)
class StageDiagnostic:
    rule_id: str
    pass_expectancy_r: float | None
    fail_expectancy_r: float | None
    selection_delta_r: float | None
    n_pass: int
    n_fail: int
    n_not_evaluable: int
    n_reference_not_evaluable: int


def stage_diagnostics(table: EventTable) -> tuple[StageDiagnostic, ...]:
    """PASS-vs-FAIL diagnostics using *reference* outcomes on both sides.

    These summaries prioritize investigation.  They are not causal claims and
    do not mix actual trade outcomes into either population.
    """
    diagnostics: list[StageDiagnostic] = []
    for rule in table.rules:
        pass_rows = [row for row in table.rows if row.rule_cells[rule.rule_id].state is RuleState.PASS
                     and row.reference_outcome_r is not None]
        fail_rows = [row for row in table.rows if row.rule_cells[rule.rule_id].state is RuleState.FAIL
                     and row.reference_outcome_r is not None]
        n_not_eval = sum(row.rule_cells[rule.rule_id].state is RuleState.NOT_EVALUABLE for row in table.rows)
        n_no_reference = sum(row.reference_outcome_r is None for row in table.rows)
        pass_metric = reference_metrics(pass_rows).reference_expectancy_r
        fail_metric = reference_metrics(fail_rows).reference_expectancy_r
        delta = pass_metric - fail_metric if pass_metric is not None and fail_metric is not None else None
        diagnostics.append(StageDiagnostic(rule.rule_id, pass_metric, fail_metric, delta,
                                           len(pass_rows), len(fail_rows), n_not_eval, n_no_reference))
    return tuple(diagnostics)


@dataclass(frozen=True)
class LeaveOneOutResult:
    rule_id: str
    status: AblationStatus
    full_parent: PerformanceMetrics
    without_rule: PerformanceMetrics | None
    expectancy_delta_vs_full_r: float | None
    reason_code: str | None = None


def selected_parent_rows(table: EventTable, *, ignored_rule_id: str | None = None) -> tuple[EventRow, ...]:
    """Return an exactly defined filter removal over the reference population."""
    return tuple(
        row for row in table.rows
        if row.reference_outcome_r is not None
        and all(cell.state is RuleState.PASS
                for rule_id, cell in row.rule_cells.items()
                if rule_id != ignored_rule_id)
    )


def leave_one_out(table: EventTable) -> tuple[LeaveOneOutResult, ...]:
    """Run only valid table-removal ablations; all other rules fail closed."""
    full = reference_metrics(selected_parent_rows(table))
    out: list[LeaveOneOutResult] = []
    for rule in table.rules:
        # A dependency means table removal would alter whether later cells were
        # semantically evaluable.  It is therefore a full-replay question even
        # when the rule itself is a simple feature predicate.
        has_dependents = any(rule.rule_id in other.depends_on for other in table.rules)
        if rule.semantics is RuleSemantics.REQUIRES_FULL_REPLAY or has_dependents:
            out.append(LeaveOneOutResult(
                rule_id=rule.rule_id,
                status=AblationStatus.REQUIRES_FULL_REPLAY,
                full_parent=full,
                without_rule=None,
                expectancy_delta_vs_full_r=None,
                reason_code=("RULE_HAS_SEMANTIC_DEPENDENTS" if has_dependents
                             else "PATH_DEPENDENT_OR_STRUCTURAL_RULE"),
            ))
            continue
        without = reference_metrics(selected_parent_rows(table, ignored_rule_id=rule.rule_id))
        delta = (None if without.reference_expectancy_r is None or full.reference_expectancy_r is None
                 else without.reference_expectancy_r - full.reference_expectancy_r)
        out.append(LeaveOneOutResult(rule.rule_id, AblationStatus.VALID, full, without, delta))
    return tuple(out)


@dataclass(frozen=True)
class ChildProposal:
    """A bounded, deterministic fast-child request."""

    parent_id: str
    campaign_id: str
    rule_id: str
    experiment_type: str
    old_value: object | None
    new_value: object | None
    comparator: str | None = None

    @property
    def rule_diff(self) -> dict[str, object | None]:
        return {
            "comparator": self.comparator,
            "new_value": self.new_value,
            "old_value": self.old_value,
            "rule_id": self.rule_id,
        }

    @property
    def child_id(self) -> str:
        digest = sha256_json({
            "campaign_id": self.campaign_id,
            "experiment_type": self.experiment_type,
            "parent_id": self.parent_id,
            "rule_diff": self.rule_diff,
            "schema_version": "FUNNEL_OPTIMIZER_CHILD_ID_V1",
        })
        return f"FO1-{digest[:24]}"


@dataclass(frozen=True)
class ChildEvaluation:
    proposal: ChildProposal
    status: ChildStatus
    strategy_funnel_identity: str
    table: EventTable | None
    metrics: PerformanceMetrics | None
    reason_code: str | None = None


class FastChildEngine:
    """Evaluate only mutations exactly expressible over cached rule features."""

    def __init__(self, table: EventTable, *, parent_id: str, campaign_id: str,
                 strategy_funnel_identity: str) -> None:
        self.table = table
        self.parent_id = parent_id
        self.campaign_id = campaign_id
        self.strategy_funnel_identity = strategy_funnel_identity
        self._rule_by_id = {rule.rule_id: rule for rule in table.rules}

    def change_threshold(self, *, rule_id: str, old_value: float, new_value: float,
                         comparator: str = ">=") -> ChildEvaluation:
        proposal = ChildProposal(self.parent_id, self.campaign_id, rule_id,
                                 "CHANGE_THRESHOLD", old_value, new_value, comparator)
        rule = self._rule_by_id.get(rule_id)
        if (rule is None or rule.semantics is not RuleSemantics.TABLE_QUERY_SAFE
                or rule.query_feature is None or any(rule_id in other.depends_on for other in self.table.rules)):
            return self._requires_full_replay(proposal, "THRESHOLD_MUTATION_CHANGES_PATH_SEMANTICS")
        if comparator not in {">=", ">", "<=", "<"}:
            return ChildEvaluation(proposal, ChildStatus.FAILED, self.strategy_funnel_identity,
                                   None, None, "UNSUPPORTED_COMPARATOR")
        rows: list[EventRow] = []
        for original in self.table.rows:
            cell = original.rule_cells[rule_id]
            changed_cells = dict(original.rule_cells)
            if cell.state is not RuleState.NOT_EVALUABLE:
                value = cell.feature_values.get(rule.query_feature)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    return ChildEvaluation(proposal, ChildStatus.FAILED, self.strategy_funnel_identity,
                                           None, None, "QUERY_FEATURE_MISSING_FROM_EVALUABLE_CELL")
                state = RuleState.PASS if _compare(float(value), float(new_value), comparator) else RuleState.FAIL
                changed_cells[rule_id] = RuleCell(
                    rule_id, state,
                    "CHILD_THRESHOLD_PASS" if state is RuleState.PASS else "CHILD_THRESHOLD_FAIL",
                    cell.feature_values,
                )
            rows.append(_child_row(original, changed_cells))
        child_table = EventTable(tuple(rows), self.table.rules, self.table.dataset_role)
        return ChildEvaluation(proposal, ChildStatus.EVALUATED, self.strategy_funnel_identity,
                               child_table, reference_metrics(selected_parent_rows(child_table)))

    def remove_rule(self, *, rule_id: str) -> ChildEvaluation:
        proposal = ChildProposal(self.parent_id, self.campaign_id, rule_id,
                                 "REMOVE_RULE", None, None, None)
        rule = self._rule_by_id.get(rule_id)
        if (rule is None or rule.semantics is not RuleSemantics.TABLE_QUERY_SAFE
                or any(rule_id in other.depends_on for other in self.table.rules)):
            return self._requires_full_replay(proposal, "REMOVAL_CHANGES_PATH_SEMANTICS")
        rows: list[EventRow] = []
        for original in self.table.rows:
            changed_cells = dict(original.rule_cells)
            # The rule's selection filter is removed; it is not reinterpreted
            # as evidence.  Only explicitly TABLE_QUERY_SAFE rules reach here.
            previous = changed_cells[rule_id]
            changed_cells[rule_id] = RuleCell(rule_id, RuleState.PASS,
                                               "CHILD_RULE_REMOVED", previous.feature_values)
            rows.append(_child_row(original, changed_cells))
        child_table = EventTable(tuple(rows), self.table.rules, self.table.dataset_role)
        return ChildEvaluation(proposal, ChildStatus.EVALUATED, self.strategy_funnel_identity,
                               child_table, reference_metrics(selected_parent_rows(child_table)))

    def _requires_full_replay(self, proposal: ChildProposal, reason: str) -> ChildEvaluation:
        return ChildEvaluation(proposal, ChildStatus.REQUIRES_FULL_REPLAY,
                               self.strategy_funnel_identity, None, None, reason)


def _child_row(original: EventRow, cells: Mapping[str, RuleCell]) -> EventRow:
    all_pass = bool(cells) and all(cell.state is RuleState.PASS for cell in cells.values())
    # The original actual outcome can only remain where an actual original
    # trade also remains.  A newly admitted counterfactual row never receives
    # its reference outcome as an actual trade outcome.
    actual_outcome = original.actual_outcome_r if all_pass and original.actual_trade else None
    return replace(original, rule_cells=cells, actual_trade=all_pass,
                   actual_outcome_r=actual_outcome)


@dataclass(frozen=True)
class CampaignLedgerEntry:
    child_id: str
    parent_id: str
    campaign_id: str
    trial_number: int
    rule_diff: Mapping[str, object | None]
    old_value: object | None
    new_value: object | None
    experiment_type: str
    strategy_funnel_identity: str
    status: ChildStatus
    reason_code: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "campaign_id": self.campaign_id,
            "child_id": self.child_id,
            "experiment_type": self.experiment_type,
            "new_value": self.new_value,
            "old_value": self.old_value,
            "parent_id": self.parent_id,
            "reason_code": self.reason_code,
            "rule_diff": dict(sorted(self.rule_diff.items())),
            "status": self.status.value,
            "strategy_funnel_identity": self.strategy_funnel_identity,
            "trial_number": self.trial_number,
        }


class CampaignLedger:
    """Append-only campaign trial counter; a working parent cannot reset it."""

    def __init__(self, campaign_id: str, entries: Sequence[CampaignLedgerEntry] = ()) -> None:
        if not campaign_id:
            raise ValueError("campaign_id is required")
        self.campaign_id = campaign_id
        self._entries = list(entries)
        self._validate_existing()

    @property
    def entries(self) -> tuple[CampaignLedgerEntry, ...]:
        return tuple(self._entries)

    @property
    def trial_count(self) -> int:
        return len(self._entries)

    def append(self, evaluation: ChildEvaluation) -> CampaignLedgerEntry:
        proposal = evaluation.proposal
        if proposal.campaign_id != self.campaign_id:
            raise ValueError("cannot add a child from another campaign")
        entry = CampaignLedgerEntry(
            child_id=proposal.child_id,
            parent_id=proposal.parent_id,
            campaign_id=proposal.campaign_id,
            trial_number=self.trial_count + 1,
            rule_diff=proposal.rule_diff,
            old_value=proposal.old_value,
            new_value=proposal.new_value,
            experiment_type=proposal.experiment_type,
            strategy_funnel_identity=evaluation.strategy_funnel_identity,
            status=evaluation.status,
            reason_code=evaluation.reason_code,
        )
        self._entries.append(entry)
        self._validate_existing()
        return entry

    def write_jsonl(self, path: str | Path) -> Path:
        """Write the complete append-only ledger in strictly increasing order."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as fh:
            for entry in self._entries:
                fh.write(canonical_json(entry.as_dict()) + "\n")
        return target

    def _validate_existing(self) -> None:
        expected = 1
        child_ids: set[str] = set()
        for entry in self._entries:
            if entry.campaign_id != self.campaign_id:
                raise ValueError("ledger cannot mix campaign ids")
            if entry.trial_number != expected:
                raise ValueError("campaign trial count must be strictly increasing without resets")
            if entry.child_id in child_ids:
                raise ValueError("a child can be appended only once")
            child_ids.add(entry.child_id)
            expected += 1


@dataclass(frozen=True)
class FrictionScenario:
    """An explicit approved scenario; absent is never interpreted as zero."""

    authority_id: str
    cost_r_per_trade: float
    approved: bool

    def __post_init__(self) -> None:
        if not self.authority_id:
            raise ValueError("friction authority_id is required")
        if not math.isfinite(self.cost_r_per_trade) or self.cost_r_per_trade < 0:
            raise ValueError("cost_r_per_trade must be a finite non-negative measured value")
        if not self.approved:
            raise ValueError("unapproved friction scenario cannot be used for economic ranking")


@dataclass(frozen=True)
class ChildRanking:
    metrics: PerformanceMetrics
    eligibility_mode: EligibilityMode
    economic_ranking: EconomicRankingStatus
    scenario_net_expectancy_r: float | None
    neighborhood_stability: float | None


def rank_child(rows: Sequence[EventRow], *, friction_scenario: FrictionScenario | None = None,
               neighborhood_stability: float | None = None) -> ChildRanking:
    """Rank structurally unless an explicitly approved scenario was supplied."""
    metrics = reference_metrics(rows)
    if friction_scenario is None:
        return ChildRanking(metrics, EligibilityMode.STRUCTURAL, EconomicRankingStatus.BLOCKED,
                            None, neighborhood_stability)
    net = (None if metrics.reference_expectancy_r is None
           else metrics.reference_expectancy_r - friction_scenario.cost_r_per_trade)
    return ChildRanking(metrics, EligibilityMode.ECONOMIC, EconomicRankingStatus.AVAILABLE,
                        net, neighborhood_stability)


@dataclass(frozen=True)
class RandomBaselineConfig:
    """Owner-gated baseline configuration.

    ``synthetic_test_only`` exists solely to prove the mechanism on synthetic
    fixtures.  It is not authority to use that count on a real fixture.
    """

    count: int
    seed: int
    authority_id: str | None = None
    synthetic_test_only: bool = False

    def __post_init__(self) -> None:
        if self.count <= 0:
            raise ValueError("baseline count must be positive")
        if self.seed < 0:
            raise ValueError("baseline seed must be non-negative")
        if not self.authority_id and not self.synthetic_test_only:
            raise ValueError("baseline count requires owner authority or synthetic-test-only declaration")

    @property
    def authorized_for_real_fixture(self) -> bool:
        return self.authority_id is not None


def _baseline_stratum(row: EventRow) -> tuple[str, str, str, int]:
    """Stable opportunity/time structure used by matched random draws."""
    return (row.dataset_id, row.symbol, row.session, row.timestamp_utc.astimezone(UTC).year)


@dataclass(frozen=True)
class EligibilityDecision:
    mode: EligibilityMode
    verdict: EligibilityVerdict
    campaign_state: CampaignState
    parent_metrics: PerformanceMetrics
    matched_baseline_expectancies_r: tuple[float, ...]
    baseline_mean_expectancy_r: float | None
    selection_delta_r: float | None
    baseline_count: int | None
    reason_code: str


def structural_parent_eligibility(table: EventTable, *, baseline: RandomBaselineConfig | None,
                                   permit_synthetic_test: bool = False) -> EligibilityDecision:
    """Compare parent selection to seeded matched random opportunity samples.

    The sample universe contains only rows with evaluable reference outcomes
    and is stratified by dataset, symbol, session, and calendar year.  This
    ensures a random comparator has the same selected-opportunity time
    structure rather than unrelated market periods.
    """
    parent_rows = selected_parent_rows(table)
    parent_metrics = reference_metrics(parent_rows)
    if baseline is None or (not baseline.authorized_for_real_fixture and not (
            permit_synthetic_test and baseline.synthetic_test_only)):
        return EligibilityDecision(
            EligibilityMode.STRUCTURAL,
            EligibilityVerdict.BLOCKED_RANDOM_BASELINE_COUNT,
            CampaignState.ACTIVE,
            parent_metrics,
            (), None, None, None,
            "RANDOM_BASELINE_COUNT_UNRESOLVED",
        )
    if not parent_rows:
        return EligibilityDecision(
            EligibilityMode.STRUCTURAL,
            EligibilityVerdict.FAIL,
            CampaignState.DEV_REJECTED_NO_SIGNAL,
            parent_metrics,
            (), None, None, baseline.count,
            "NO_PARENT_REFERENCE_OUTCOMES",
        )
    universe = [row for row in table.rows if row.reference_outcome_r is not None]
    quotas: dict[tuple[str, str, str, int], int] = {}
    for row in parent_rows:
        key = _baseline_stratum(row)
        quotas[key] = quotas.get(key, 0) + 1
    strata: dict[tuple[str, str, str, int], list[EventRow]] = {}
    for row in universe:
        strata.setdefault(_baseline_stratum(row), []).append(row)
    if any(len(strata.get(key, ())) < quota for key, quota in quotas.items()):
        return EligibilityDecision(
            EligibilityMode.STRUCTURAL,
            EligibilityVerdict.BLOCKED_INSUFFICIENT_REFERENCE_OUTCOMES,
            CampaignState.ACTIVE,
            parent_metrics,
            (), None, None, baseline.count,
            "MATCHED_OPPORTUNITY_POPULATION_INSUFFICIENT",
        )

    draws: list[float] = []
    for draw_no in range(baseline.count):
        selected: list[EventRow] = []
        for key in sorted(quotas):
            # Isolated per-draw/per-stratum streams make adding another stratum
            # unable to alter existing sample choices.
            rng = random.Random(f"FUNNEL_OPTIMIZER_V1:{baseline.seed}:{draw_no}:{key}")
            population = sorted(strata[key], key=_event_sort_key)
            selected.extend(rng.sample(population, quotas[key]))
        expectancy = reference_metrics(selected).reference_expectancy_r
        if expectancy is None:  # guarded by quotas/universe, retained fail-closed.
            return EligibilityDecision(
                EligibilityMode.STRUCTURAL,
                EligibilityVerdict.BLOCKED_INSUFFICIENT_REFERENCE_OUTCOMES,
                CampaignState.ACTIVE,
                parent_metrics,
                tuple(draws), None, None, baseline.count,
                "MATCHED_BASELINE_NOT_EVALUABLE",
            )
        draws.append(expectancy)
    baseline_mean = mean(draws)
    delta = parent_metrics.reference_expectancy_r - baseline_mean if parent_metrics.reference_expectancy_r is not None else None
    # A structural test can reject a family when it does not outperform its
    # own matched opportunity population.  It cannot establish tradability or
    # EDGE_VERIFIED even if it passes.
    passes = delta is not None and delta > 0.0
    return EligibilityDecision(
        EligibilityMode.STRUCTURAL,
        EligibilityVerdict.PASS if passes else EligibilityVerdict.FAIL,
        CampaignState.STRUCTURAL_ELIGIBLE_NOT_EDGE if passes else CampaignState.DEV_REJECTED_NO_SIGNAL,
        parent_metrics,
        tuple(draws), baseline_mean, delta, baseline.count,
        "STRUCTURAL_MATCHED_RANDOM_BASELINE",
    )
