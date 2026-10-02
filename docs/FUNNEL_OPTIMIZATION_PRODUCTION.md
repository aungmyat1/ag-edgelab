# EdgeLab Funnel Optimization — Production Research Contract

## Product boundary

EdgeLab is research-only. Production means a reproducible, CI-gated research service/library. It does **not** mean broker, MT5, exchange, Demo, or Live execution. No optimizer, AI agent, backtest engine, or validator receives execution authority.

## Two-layer architecture

1. **Funnel Optimization Engine** — DEVELOPMENT data only. Market observations flow through deterministic strategy stages. The engine measures retention, win rate, expectancy, profit factor, net R, and incremental stage contribution. It may create auditable child variants by removing/replacing/adding stages or changing coarse parameters.
2. **Edge Verification Engine** — frozen candidates only. It opens untouched OOS/SEALED_OOS once, then applies friction, robustness, walk-forward/regime analysis, and independent-engine parity before any `EDGE_VERIFIED` artifact is possible.

## Required optimization loop

`MEASURE -> DIAGNOSE -> ONE CONTROLLED MUTATION -> DEV COMPARE -> KEEP/REJECT -> FREEZE`

Optimization target is not win rate alone. Prefer simple, stable funnels with positive net expectancy, acceptable drawdown, sufficient population, friction survival, and broad parameter neighborhoods.

## Dataset exposure state

- `UNSEEN`: no result inspected.
- `DEVELOPMENT`: exploratory optimization is allowed.
- `OBSERVED_VALIDATION`: result has informed research and is no longer pristine.
- `BURNED_HOLDOUT`: OOS/SEALED_OOS result has been inspected; it can never be represented as unseen again.

OOS, SEALED_OOS, and FORWARD data are forbidden inputs to optimization primitives. A holdout may be opened only for a frozen strategy hash and only while exposure is `UNSEEN`.

## Funnel diagnostics

For each stage retain at least:

- input and pass counts / retention
- wins, losses, win rate
- net expectancy R and profit factor
- net R after friction
- delta win-rate percentage points
- delta expectancy R

Run leave-one-stage-out ablation on DEVELOPMENT data to estimate incremental contribution. A weak stage is a research hypothesis, not an automatic deletion; any changed funnel is a new immutable child variant.

## Parameter discipline

Structural optimization precedes fine parameter optimization. Parameter searches use coarse, preregistered neighborhoods. Isolated optimum spikes are treated as fragility; broad positive plateaus are preferred. The selected candidate is frozen before OOS access.

## Verification gates

A future `EDGE_VERIFIED` artifact requires all mandatory gates to pass under the frozen contract:

1. deterministic strategy/rule hashes and valid dataset lineage
2. untouched OOS evaluation
3. realistic friction and friction stress
4. parameter/structural robustness
5. chronological walk-forward and regime reporting
6. uncertainty reporting (bootstrap/confidence diagnostics)
7. independent-engine reproduction within declared tolerances
8. immutable evidence artifact and audit lineage

Failure does not authorize tuning on the same holdout. The exposed holdout becomes research evidence; a revised strategy requires a new untouched validation population.

## Current migration plan

- R3: funnel observability + immutable mutation/variant contracts
- R4: leave-one-out ablation and stage contribution
- R5: controlled structural/coarse-parameter mutations + experiment registry
- R6: exposure/contamination governance + parameter stability
- R7: walk-forward, regime, friction stress, independent parity gates
- R8: optional AI hypothesis generator; may create research experiments only

## Current objective

The product objective remains one honestly verified FX edge and one honestly verified crypto edge. Negative or inconclusive evidence is a valid production outcome; the engine must never manufacture a positive edge to satisfy the objective.
