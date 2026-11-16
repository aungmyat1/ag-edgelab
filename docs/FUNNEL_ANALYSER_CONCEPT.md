# Funnel Analyser — Concept v1.0

**Project:** AG EdgeLab / Objective B  
**Status:** Proposed research tooling; not an approved strategy rule or verified trading edge.  
**Purpose:** Explain where candidate opportunities are rejected, quantify their economics, and support controlled research without contaminating independent validation.

## 1. Principles

- Read-only diagnostic analysis first; never submit orders or change strategy parameters automatically.
- Preserve immutable source data, strategy version, configuration hash, broker costs, timestamps and event IDs.
- Every rejection must identify the exact rule ID, threshold, observed value and reason.
- Calculate all metrics on DEV only during design and tuning. Keep VAL/HOLD sealed until separately authorized.
- An event is not a trade. Distinguish raw opportunities, eligible setups, executable trades and independent clusters.
- No increase in sample size, win rate or profit factor alone establishes an edge.

## 2. Six funnel phases

| Phase | Input | Output | Diagnostic |
| --- | --- | --- | --- |
| F1 Opportunity detection | Admitted market observations | Raw candidate events | Event counts by symbol, session, direction and regime |
| F2 Level qualification | Raw events | Eligible levels | Level type, first-breach/consumption state, age and invalidation |
| F3 Trigger confirmation | Qualified levels | Triggered candidates | Sweep, MSS/displacement, bar-close causality and time-to-trigger |
| F4 Entry qualification | Triggered candidates | Entry candidates | Retest, TTL, RR, stop distance and rule-specific exclusions |
| F5 Execution feasibility | Entry candidates | Cost-feasible executable trades | Spread, commission, slippage, min lot, risk cap and available liquidity |
| F6 Economic outcomes | Feasible trades | Net-R distributions and research summaries | Net R, expectancy, drawdown, uncertainty and robustness |

A phase may be skipped only when the strategy contract explicitly declares it inapplicable. Report both stage-local conversion and cumulative conversion.

## 3. Event schema and traceability

Minimum fields: dataset_id, data_hash, strategy_id, strategy_version, rule_set_hash, symbol, broker, session, regime, event_id, independent_cluster_id, level_id, event_time_utc, source_bar_close_utc, phase, rule_id, observed_value, threshold, decision, rejection_reason, cost_model_id, and run_id.

Enforce deterministic event IDs and explicit timestamp timezone. A rejected candidate retains its full trace; do not silently drop rows. When multiple rules fail, record all failures plus the deterministic primary rejection rule.

## 4. Rule-level diagnostics

For each rule: number tested, number passed, number rejected, conditional pass rate, cumulative survival, distinct cluster count, and distribution of observed values relative to thresholds. Identify bottlenecks without assuming relaxing them improves profitability.

Separate mutually exclusive primary-rejection attribution from all-failure attribution to prevent double counting. Report missing-data and not-evaluated cases separately from strategy rejection.

## 5. Economic metrics

Use realized or explicitly modeled broker-specific spread, commissions, slippage and financing where relevant. Report gross and net R/trade, expectancy, profit factor, median, quantiles, max drawdown, exposure, trade frequency and confidence intervals with dependence-aware uncertainty estimates. Distinguish candidate-level, executed-trade-level and independent-cluster-level sample counts.

When fewer than the program's applicable minimum sample requirements are met, report **INSUFFICIENT_SAMPLE**; do not manufacture a definitive edge verdict. For Objective B, preserve the existing 100/300 floors as governed, without redefining their denominator or waiving them in this concept.

## 6. Controlled optimization

1. Freeze baseline strategy contract and dataset manifests.
2. On DEV only, identify a specific bottleneck and hypothesize a causal improvement.
3. Change one predeclared rule or a bounded group of linked rules per experiment.
4. Compare against unchanged baseline with costs and independent clusters.
5. Record every trial, including failures; account for multiple comparisons and selection bias.
6. Promote only a candidate that satisfies applicable sample, causality, robustness and governance gates.
7. Request separate owner authorization before any VAL/HOLD unsealing or independent verification.

Never optimize on VAL/HOLD results, repeatedly inspect sealed partitions, or describe DEV lift as verified edge.

## 7. Example diagnostic reports

**Example A — scarce entries:** 300 raw opportunities → 180 eligible levels → 72 triggers → 25 entries → 12 feasible trades. Report a 4% end-to-end conversion, rule-level rejection causes and INSUFFICIENT_SAMPLE; do not loosen gates merely to reach a quota.

**Example B — negative economics:** 150 executable trades with +0.08 gross R/trade but -0.04 net R/trade. Investigate costs and feasible holding/target geometry on DEV; no claim of net profitability or authorization to trade.

Both examples are illustrative, not EdgeLab backtest results.

## 8. Outputs and acceptance

Generate machine-readable per-event trace, per-rule diagnostics, funnel summary, cost breakdown, experiment comparison, and human-readable research report. Require reproducible hashes, causal bar-close timing, reconciliation of counts across phases, explicit no-data handling, and tests for duplicate events and multi-rule rejection.

**Acceptance:** On a fixed fixture, repeated runs produce identical event IDs and counts; each candidate is accounted for at every applicable phase; gross-to-net R reconciliation passes; DEV/VAL/HOLD access restrictions fail closed; sample insufficiency is prominently labeled.

## 9. Governance boundary

This concept is documentation only. It does not alter AGENTS.md, strategy rules, Objective A D0/E0 gates, Objective B floors, COST-A policy, MT5 tester authorization, broker accounts, or demo/live execution. Any implementation requires a bounded mission, exact owner approval, and separate run authorization under the controlling repository governance.
