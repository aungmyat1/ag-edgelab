# AG EdgeLab — Real Funnel Model

## Purpose

This document is the canonical interpretation of a trading strategy inside Funnel Lab.

A strategy is not a single backtest function. It is a versioned decision funnel through which market candidates flow.

```text
CONTEXT -> LOCATION -> TRIGGER -> RISK -> EXECUTION -> OUTCOME/AUDIT
```

Each phase contains one or more deterministic versioned rules. A strategy may branch; phases classify decisions semantically and do not require a purely linear graph.

## Reference funnel

```text
ST_ASIAN_SESSION_V1
|
+-- CONTEXT
|   +-- ASIAN_SESSION_V1
|   `-- H1_BIAS_V1
|
+-- LOCATION
|   `-- ASIAN_RANGE_V1
|
+-- TRIGGER
|   +-- SWEEP_V1
|   `-- DISPLACEMENT_V1
|
+-- RISK
|   +-- RANGE_25_SL_V1
|   `-- RR_GATE_V1
|
+-- EXECUTION
|   `-- ENTRY_RETEST_V1
|
`-- OUTCOME
    +-- TP1_RANGE_V1
    +-- BE_AFTER_TP1_V1
    `-- TP2_5R_V1
```

Names do not define behavior. Each rule requires a deterministic contract. If exact semantics are missing, implementation must stop rather than guess.

## Candidate flow

Example:

```text
candidate
 -> CONTEXT: PASS
 -> LOCATION: PASS
 -> TRIGGER/SWEEP: PASS
 -> TRIGGER/DISPLACEMENT: FAIL
 -> terminal REJECT
```

Another candidate may reach EXECUTION and generate a canonical simulated trade. Every path must remain in the CandidateLedger.

## Percentage model

### 1. Flow percentage

How selective is a funnel?

```text
flow_pct = pass_n / input_n * 100
```

Example: 2,100 of 3,100 candidates pass `DISPLACEMENT_V1` => 67.74% flow.

Flow is not quality. A very selective rule may be excellent or harmful.

### 2. PASS final win percentage

Among candidates passing the stage and eventually producing comparable final trades/outcomes, what percentage win?

### 3. FAIL final win percentage

Where a valid counterfactual/comparable outcome methodology exists, measure the downstream outcome of the rejected population too. The methodology must be explicit; do not fabricate trades for rejected candidates.

### 4. Selection effect

```text
selection_effect_pp = pass_final_win_rate - fail_final_win_rate
```

A negative value makes the rule an investigation candidate, subject to sample requirements.

### 5. Parent delta

```text
delta_win_rate_vs_parent_pp = rule_pass_final_wr - parent_population_final_wr
```

This describes where deterioration appears in the funnel.

## Phase-level and rule-level diagnosis

First inspect phases:

```text
CONTEXT     final WR 46%
LOCATION    final WR 49%
TRIGGER     final WR 42%  <- weak phase candidate
RISK        final WR 45%
EXECUTION   final WR 53%
```

Then inspect the weak phase:

```text
TRIGGER
  SWEEP_V1         final WR 50%
  DISPLACEMENT_V1  final WR 42% <- weak rule candidate
```

This hierarchy is central to the product: locate weak phase -> locate weak rule -> create controlled experiment.

## V0.1 diagnostic labels

- `IMPROVING`
- `NEUTRAL`
- `WEAK_FUNNEL_CANDIDATE`
- `INSUFFICIENT_SAMPLE`

Thresholds and sample floors must be explicit/versioned configuration. Never hide them in presentation code.

## Why win rate is only MVP V0.1

Win rate is intuitive but incomplete. Example:

```text
before rule: WR 55%, expectancy +0.10R
after rule:  WR 48%, expectancy +0.31R
```

The rule lowers win rate but improves economics. Therefore V0.2 adds expectancy and other R-based metrics. A production-quality Funnel Lab must not optimize only win rate.

## V0.2 economic metrics

At phase/rule level where valid:

```text
expectancy_r
profit_factor
max_drawdown_r
avg_win_r
avg_loss_r
pass_expectancy_r
fail_expectancy_r
delta_expectancy_vs_parent_r
```

## Outcome phase

`OUTCOME` differs from filtering phases. It measures what happened after a trade was accepted rather than simply deciding whether a candidate advances.

Example measures:

```text
trades_n
tp1_reached_pct
be_after_tp1_pct
tp2_reached_pct
sl_before_tp1_pct
win_rate
expectancy_r
avg_win_r
avg_loss_r
```

Exit rules remain versionable, so TP/BE/exit changes create new strategy identities and can be tested as child funnels.

## Version mutation

Never edit `DISPLACEMENT_V1` behavior in place.

```text
ST_ASIAN_SESSION_V1
  ...
  DISPLACEMENT_V1

ST_ASIAN_SESSION_V1_1
  ...
  DISPLACEMENT_V2  <- only declared change
```

Record:
- parent funnel identity
- child funnel identity
- old/new rule identities
- changed parameters/semantics
- development dataset identity
- engine/code identity

Then compare on the same DEVELOPMENT population.

## Branching funnels

A strategy may branch:

```text
CONTEXT
  -> MARKET_STATE
       |-- TREND -> trend location/trigger path
       `-- RANGE
            |-- SWEEP -> sweep trigger path
            `-- NORMAL_RANGE -> range trigger path
  -> RISK
  -> EXECUTION
  -> OUTCOME
```

Every route requires explicit population accounting and terminal reason codes.

## Freeze boundary

When development yields a promising strategy:

```text
PROMISING FUNNEL
 -> freeze graph/rules/parameters/data/engine identities
 -> FrozenStrategyManifest
 -> stop optimization
 -> Edge Verification Engine
```

If verification evidence is negative and the strategy is changed, the changed strategy is a new development candidate. Do not optimize against the validation/holdout evidence.
