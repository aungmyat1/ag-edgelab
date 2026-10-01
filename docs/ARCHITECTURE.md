# AG EdgeLab — Canonical Architecture

This document defines the architecture all implementation and audit agents should use.

## 1. Two authority domains

### Funnel Development Engine
Purpose: develop deterministic strategy rules on DEVELOPMENT data.

Responsibilities:
- ingest canonical market data
- execute versioned funnel rules without look-ahead
- record every candidate PASS/FAIL/route/rejection
- attribute downstream outcomes to phases and rules
- identify weak funnel candidates
- compare immutable parent/child funnel versions
- freeze a promising candidate

It cannot issue `EDGE_VERIFIED`.

### Edge Verification Engine
Purpose: attempt to falsify a frozen strategy using authorized evidence that was not used to optimize it.

Responsibilities:
- resolve content-addressed evidence IDs
- derive exposure/unseen state from authoritative ledger
- recompute metrics from canonical trade/evidence records
- evaluate OOS economics and uncertainty
- apply friction, walk-forward, stability and regime gates
- check approved independent-engine parity
- fail closed on missing/incoherent authority
- issue only policy-defined verification verdicts

It cannot modify strategy rules.

## 2. Development-to-verification lifecycle

```text
DEVELOPMENT DATA
   |
   v
MarketFrame
   |
   v
FunnelDefinition + RuleDefinitions
   |
   v
FunnelRunner
   |
   +--> CandidateLedger
   +--> canonical trade/outcome records
   |
   v
FunnelMetrics
   |
   v
Weak Funnel Diagnostic
   |
   v
Rule experiment -> child FunnelDefinition
   |
   +---------------- repeat ----------------+
   |
   v
Promising candidate
   |
   v
FrozenStrategyManifest
   ||
   || HARD AUTHORITY WALL
   \/
Edge Verification Engine
   |
   v
EDGE_VERIFIED | NO_EDGE | INSUFFICIENT_EVIDENCE
```

## 3. Canonical domain objects

### MarketFrame
Normalized, UTC-aware market observations with stable dataset/source identity and explicit dataset role.

### RuleDefinition
Immutable behavior definition. Behavior-changing parameter changes create a new rule identity.

### FunnelDefinition
Immutable strategy graph composed of phases, nodes, rules and routes. Stores parent identity and changed-rule lineage for child experiments.

### FunnelEvent
One candidate's auditable evaluation at one rule/node.

### CandidateLedger
Complete chronological record of candidates, including rejects and no-trade terminals. Trade-only logging is insufficient.

### CanonicalTrade / OutcomeRecord
Deterministic final trade/outcome representation used for development attribution and later evidence production.

### FunnelMetrics
Derived development metrics. Never verification authority by themselves.

### FrozenStrategyManifest
Immutable handoff containing graph/rules/parameters, development dataset identity, engine/code identity, ledger/trade hashes and freeze time.

### Verification evidence
Content-addressed records resolved by the production verifier. Caller-supplied aggregates are not authoritative.

## 4. Real funnel semantics

The stable semantic phases are:

1. `CONTEXT` — session, higher-timeframe structure/bias, market environment, optional event/news gate.
2. `LOCATION` — price area/POI where the strategy is allowed to seek a setup.
3. `TRIGGER` — lower-timeframe event/confirmation required to advance.
4. `RISK` — invalidation, stop geometry, reward/risk and strategy risk constraints.
5. `EXECUTION` — entry model, order semantics and cost/spread acceptance for research simulation.
6. `OUTCOME` — exit management and measurable trade outcome/audit.

Rules are strategy-specific; phases are structural. Strategies may branch inside or across phases.

## 5. Funnel scoring architecture

Do not begin with one opaque 0-100 score.

### Flow
`flow_pct = pass_n / input_n * 100`

### Downstream quality
For V0.1:
- PASS final win rate
- FAIL final win rate
- parent final win rate
- delta win rate vs parent
- selection effect = PASS final WR - FAIL final WR

### Economic quality — V0.2+
- expectancy R
- PF
- max DD R
- average win/loss R
- corresponding PASS/FAIL and delta measures

### Robustness — later
- sample uncertainty
- temporal/walk-forward stability
- parameter/rule-neighborhood stability
- regime robustness
- friction survival
- independent parity

## 6. Weak funnel semantics

`WEAK_FUNNEL_CANDIDATE` means a rule/phase's PASS population shows material downstream deterioration on DEVELOPMENT data under configured thresholds and adequate sample size.

It does not mean:
- the rule caused the loss
- the rule should automatically be removed
- the strategy has no edge
- a new rule is better

The correct response is a controlled child-funnel experiment.

Analysis hierarchy:

```text
STRATEGY
 -> identify weak PHASE
 -> inspect rules inside phase
 -> identify weak RULE candidate
 -> create explicit rule mutation
 -> create CHILD FUNNEL
 -> compare on same DEVELOPMENT population
```

## 7. Example strategy

```text
ST_ASIAN_SESSION_V1
|
+-- CONTEXT
|   +-- ASIAN_SESSION_V1
|   `-- H1_BIAS_V1
+-- LOCATION
|   `-- ASIAN_RANGE_V1
+-- TRIGGER
|   +-- SWEEP_V1
|   `-- DISPLACEMENT_V1
+-- RISK
|   +-- RANGE_25_SL_V1
|   `-- RR_GATE_V1
+-- EXECUTION
|   `-- ENTRY_RETEST_V1
`-- OUTCOME
    +-- TP1_RANGE_V1
    +-- BE_AFTER_TP1_V1
    `-- TP2_5R_V1
```

This is a reference structure, not permission to invent missing strategy semantics. Exact rules must be explicitly defined and versioned before execution.

## 8. Adapter boundary

External backtest/research systems sit outside the authority core:

```text
AG Funnel/Market contracts
        |
        +--> Backtesting.py adapter
        +--> vectorbt adapter
        +--> Freqtrade adapter
        `--> LEAN adapter
                 |
                 v
       canonical AG records
```

Never accept an external engine's aggregate PF/expectancy as production verification authority. Import canonical evidence and recompute inside EdgeLab.

## 9. Data-role boundary

At minimum distinguish:
- `DEVELOPMENT` — may be repeatedly inspected and used to modify strategy.
- authorized unseen/OOS roles — used only under verification policy.
- sealed holdout — inaccessible to Funnel Lab and not opened merely to improve a strategy.

If verification fails and the strategy is changed, return to DEVELOPMENT and create a new candidate/campaign.

## 10. Safety boundary

EdgeLab is not an execution service. No component in this repository should require broker credentials or place/modify/cancel real or Demo orders. `OrderIntent`-like research objects must remain neutral simulation/research representations.
