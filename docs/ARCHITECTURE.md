# AG EdgeLab Funnel Engine V1 — Architecture

## Boundary

AG EdgeLab is a standalone research product. It validates deterministic strategy edge; it does not perform live market opportunity scanning, create TradeTickets, connect to broker accounts, or authorize Demo/Live execution.

Its eventual downstream integration object is an immutable `EdgeValidationArtifact`.

## Canonical funnel

1. CONTEXT
2. LOCATION
3. TRIGGER
4. GEOMETRY
5. EXECUTION
6. OUTCOME/AUDIT (post-trade only; never a pre-trade input)

Pre-trade stages are strictly ordered. A failed stage terminates candidate progression. `SEQUENCE` mode may also stop within a stage at the first failed rule.

## Anti-look-ahead invariant

Every rule evaluates through an `EvaluationContext` with an `as_of` timestamp. Bars later than `as_of` are rejected by the core contract. Later funnel results and trade outcomes cannot be read by earlier rules.

## Candidate-first design

Every candidate is retained, including rejected candidates. This is necessary for funnel retention, rejection attribution, conditional win probabilities, expectancy lift, ablation, and robustness analysis.

## Declarative strategies

Strategies declare a `StrategyManifest` and `FunnelDefinition`. A compiler resolves `(rule_id, rule_version)` references from an explicit rule registry into executable stage definitions. This keeps strategy logic separate from the validation framework.

## Backtest authority

Backtest engines simulate fills only. They do not qualify strategies. R1 will provide a small reference replay adapter and an optional NautilusTrader adapter behind the same `BacktestEngine` protocol.

## Dataset governance

Dataset roles are `DEVELOPMENT`, `VALIDATION`, `OOS`, `SEALED_OOS`, and `FORWARD`. Exploratory operations are forbidden on OOS and SEALED_OOS datasets. SHA-256 is the canonical fingerprint mechanism.
