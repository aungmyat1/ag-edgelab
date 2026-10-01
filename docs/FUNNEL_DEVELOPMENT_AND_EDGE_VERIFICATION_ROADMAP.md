# AG EdgeLab — Funnel Development MVP and Edge Verification Roadmap

Status: architecture / implementation plan

## 1. Objective

AG EdgeLab has two separate authority domains:

1. **Funnel Development Engine (Funnel Lab)** — market data flows through versioned strategy-rule funnels. The first MVP has one narrow job: describe the flow and identify **weak funnel candidates** whose PASS population shows deterioration in downstream/final win rate. Researchers then modify the identified strategy rule on DEVELOPMENT data and compare the new funnel version.
2. **Edge Verification Engine** — receives an immutable frozen candidate and attempts to falsify it using evidence not used to develop the strategy. Only the production verification policy may issue `EDGE_VERIFIED`.

No broker/Demo/Live execution is in scope.

```text
DEVELOPMENT MARKET DATA
        -> FUNNEL V1
        -> RULE-BY-RULE FLOW
        -> INPUT/PASS/FAIL/PASS%
        -> PASS FINAL WR vs FAIL FINAL WR
        -> DELTA WIN RATE
        -> WEAK FUNNEL CANDIDATE?
        -> MODIFY THAT RULE
        -> CHILD FUNNEL VERSION
        -> repeat on DEVELOPMENT data
        -> PROMISING STRATEGY
        -> FREEZE
        -> EDGE VERIFICATION ENGINE
        -> EDGE_VERIFIED | NO_EDGE | INSUFFICIENT_EVIDENCE
```

A good development result is not `EDGE_VERIFIED`. Any behavior-changing strategy modification after freeze creates a new candidate and validation campaign.

## 2. MVP V0.1 — Weak Funnel Diagnostic

Goal: answer reliably: **Which strategy-rule funnel appears to reduce candidate quality toward the final trade outcome, measured first by downstream/final win rate, and by how much?**

Example strategy:

```text
MARKET DATA
 -> SESSION_V1
 -> BIAS_V1
 -> SWEEP_V1
 -> DISPLACEMENT_V1
 -> RETEST_V1
 -> ENTRY_V1
 -> EXIT_V1
```

Primary report fields:

```text
stage
input_n
pass_n
fail_n
pass_rate
pass_final_trade_n
fail_final_trade_n
pass_final_win_rate
fail_final_win_rate
parent_final_win_rate
delta_win_rate_vs_parent
diagnostic_label
```

Diagnostic labels:

- `IMPROVING`
- `NEUTRAL`
- `WEAK_FUNNEL_CANDIDATE`
- `INSUFFICIENT_SAMPLE`

A stage may be labelled `WEAK_FUNNEL_CANDIDATE` only when its downstream/final win-rate delta breaches an explicit development threshold and its sample-size floor is satisfied. This is a research diagnostic, not a causal claim or verification verdict.

The ledger must retain rejected candidates so PASS and FAIL populations can both be inspected. No candidate may silently disappear.

### Interpretation rule

V0.1 intentionally begins with win rate because it is simple and directly matches the first product objective. Lower win rate does **not** necessarily mean lower economic edge. A rule may reduce win rate while increasing payoff/expectancy. V0.2 therefore adds expectancy before stronger economic-quality diagnostics are allowed.

## 3. Minimal V0.1 infrastructure

### MarketFrame

```text
timestamp_utc
symbol
timeframe
open
high
low
close
volume?
bid?
ask?
spread?
source_id
dataset_id
```

UTC-aware, deterministic, DEVELOPMENT-role data with stable identity and anti-lookahead controls.

### RuleDefinition

```text
rule_id
rule_version
rule_sha256
rule_type
parameters
input_contract
output_contract
```

Initial types: classifier, filter/decision, trade/action.

### FunnelDefinition

```text
funnel_id
version
parent_funnel_id?
nodes
edges
entry_node
changed_rules
funnel_sha256
```

A funnel is the strategy ruleset. A behavior-changing rule modification creates a new rule and funnel identity.

### FunnelEvent

```text
event_id
market_timestamp
node_id
rule_id
input_eligible
outcome
pass_fail_or_route
reason_code
```

### FunnelRunResult

```text
funnel_sha256
dataset_sha256
engine_identity
candidate_ledger_hash
trade_list_hash
stage_metrics
```

## 4. V0.1 execution loop

1. Load DEVELOPMENT `MarketFrame`.
2. Load immutable `FunnelDefinition`.
3. Evaluate candidates chronologically.
4. Record every PASS, FAIL, route and rejection.
5. Produce canonical final trade outcomes through a simulation adapter.
6. Join final outcomes back to stage histories.
7. Compute PASS and FAIL final win rates per stage.
8. Compute downstream/parent win-rate deltas.
9. Apply explicit sample floor and diagnostic thresholds.
10. Emit weak-funnel report.
11. Modify an identified strategy rule.
12. Create a child funnel; never mutate parent.
13. Re-run on the same DEVELOPMENT population.
14. Compare parent/child and keep or reject the experiment.

Acceptance: deterministic results/hashes; no future access; complete candidate ledger; reconciled stage populations; traceable outcomes; versioned thresholds; insufficient samples fail diagnostic classification; behavior change changes funnel identity; no execution capability; tests green.

## 5. V0.2 — Economic Weak-Funnel Diagnostic

Add:

```text
pass_expectancy_r
fail_expectancy_r
parent_expectancy_r
delta_expectancy_vs_parent
profit_factor
max_drawdown_r
avg_win_r
avg_loss_r
```

A win-rate drop with improved expectancy must not be classified as economically weak solely from win rate.

Example:

```text
Stage          Delta WR     Delta Expectancy
BIAS_V1         +3.6pp          +0.08R
SWEEP_V1        -8.0pp          -0.14R  <- stronger weak-rule evidence
RETEST_V1       +6.9pp          +0.13R
```

## 6. V0.3 — Rule Mutation and Parent/Child Comparison

```text
FUNNEL_V1
 SESSION_V1
 BIAS_V1
 SWEEP_V1
 ENTRY_V1
 EXIT_V1

FUNNEL_V1_1
 SESSION_V1
 BIAS_V1
 SWEEP_V2   <- changed
 ENTRY_V1
 EXIT_V1
```

Support declared rule replacement, parameter changes, valid rule removal/addition, exact changed-rule lineage, and same-population DEVELOPMENT comparison.

## 7. V0.4 — Branching Funnels

Support acyclic decision graphs such as Trend/Range/Sweep and E1/E2/E3 strategies. Routes and populations must reconcile, branch metrics remain auditable, and no-trade terminals remain recorded.

## 8. V0.5 — Fast Experiments

Reuse vectorbt for DEVELOPMENT-only parameter/rule neighborhoods where appropriate. Add deterministic diagnostics such as `POSSIBLE_HARMFUL_RULE`, `POSSIBLE_REDUNDANT_RULE`, `POSSIBLE_OVER_FILTER`, `LOW_SAMPLE_STAGE`, and `UNSTABLE_PARAMETER_NEIGHBORHOOD`. Prefer stable neighborhoods over isolated maxima.

## 9. V0.6 — AI Experiment Assistant

AI may explain stage deterioration and propose explicit child-funnel experiments. It may not use sealed holdouts to design rules, mutate frozen candidates in place, change verification policy, or declare `EDGE_VERIFIED`.

## 10. Funnel Development V1.0 — Freeze

Freeze at least:

```text
strategy_id
funnel_sha256
complete graph
rule identities
parameter identities
entry/exit/risk semantics
development_dataset_sha256
simulation_engine_identity
simulation_engine_code_sha256
candidate_ledger_hash
development_trade_list_hash
freeze_timestamp_utc
```

Any behavior change after freeze starts a new candidate/campaign.

## 11. Open-source reuse

Build only AG-specific authority: funnel definitions/versioning, candidate-flow ledger, PASS/FAIL attribution, weak-funnel diagnostics, parent/child lineage, freeze manifest, evidence/exposure authority, and final verification verdict.

Reuse:

- pandas / NumPy — data processing
- Backtesting.py — initial lightweight simulation where semantics fit
- vectorbt — fast DEVELOPMENT experiments
- Freqtrade — later crypto backtests and lookahead/recursive diagnostics
- QuantConnect LEAN — later independent event-driven parity

External engines produce evidence; they never issue AG verification verdicts. Verification metrics are recomputed from canonical evidence.

## 12. Edge Verification Engine upgrade

### EV V1.0 — unseen OOS economics
Frozen strategy + authorized unseen OOS evidence. Recompute N, win rate, expectancy, PF, DD and uncertainty from canonical evidence.

### EV V1.1 — friction
Bind a versioned friction model; verifier derives stressed outcomes.

### EV V1.2 — walk-forward
Bind unique folds to train/test data/windows, strategy/engine identity and canonical test trades; verify chronology, lineage and populations.

### EV V1.3 — stability
Bind frozen center to real neighboring rule/parameter identities, common DEVELOPMENT population, engine/code identity and preregistration.

### EV V1.4 — regimes
Bind frozen classifier and market-state provenance; caller labels are non-authoritative.

### EV V1.5 — independent parity
Resolve canonical trade lists from at least two owner-approved genuinely independent engine identities.

### EV V2.0 — production verdict

```text
FROZEN STRATEGY
 -> UNSEEN OOS ECONOMICS
 -> STATISTICAL/BOOTSTRAP GATE
 -> FRICTION
 -> WALK-FORWARD
 -> STABILITY
 -> REGIMES
 -> INDEPENDENT PARITY
 -> EXPOSURE/PROVENANCE
 -> EDGE_VERIFIED | NO_EDGE | INSUFFICIENT_EVIDENCE
```

`NO_EDGE` requires coherent negative evidence. Missing/malformed/contradictory/unresolved/provenance-incoherent evidence fails closed as `INSUFFICIENT_EVIDENCE`.

## 13. Revised delivery work packages

- **WP-F0** — lineage/scope gate; protect validator lineage, sealed holdout and no-execution invariant.
- **WP-F1** — canonical `MarketFrame` and existing-data adapters.
- **WP-F2** — rule/funnel contracts, serialization and hashing.
- **WP-F3** — chronological candidate-flow runner and PASS/FAIL/reject ledger.
- **WP-F4** — **Weak Funnel Diagnostic MVP**: stage flow + PASS/FAIL final WR + delta WR + diagnostic label.
- **WP-F5** — minimal Backtesting.py simulation adapter producing canonical outcomes.
- **WP-F6** — V0.2 expectancy/PF/DD economic diagnostics.
- **WP-F7** — V0.3 immutable parent/child rule-version comparison.
- **WP-F8** — V0.4 branching funnels.
- **WP-F9** — frozen-strategy handoff to Edge Validator.
- **WP-F10** — vectorbt fast DEVELOPMENT experiments.
- **WP-F11** — Freqtrade crypto diagnostics.
- **WP-F12** — LEAN independent parity.

## 14. First MVP completion definition

One real strategy and an existing DEVELOPMENT dataset must deterministically produce a traceable report such as:

```text
FUNNEL V1

SESSION_V1
 input=10000 pass=7000 pass_rate=70.0%
 pass_final_wr=48.0%

BIAS_V1
 input=7000 pass=4100 pass_rate=58.6%
 pass_final_wr=51.0% delta=+3.0pp

SWEEP_V1
 input=4100 pass=1500 pass_rate=36.6%
 pass_final_wr=43.0% delta=-8.0pp
 diagnostic=WEAK_FUNNEL_CANDIDATE

RETEST_V1
 input=1500 pass=720 pass_rate=48.0%
 pass_final_wr=50.0% delta=+7.0pp
```

Every number must trace to canonical candidate/trade records. The next development action is then explicit: investigate/modify `SWEEP_V1`, create a child funnel, and compare on DEVELOPMENT data. Only after a promising funnel is frozen does verification begin.

## 15. Invariants

- research only; no broker credentials/order placement/Demo/Live execution
- sealed holdouts excluded from Funnel Lab
- DEVELOPMENT may change strategy; verification may not
- every behavior change creates a new strategy identity
- third-party engines never issue verification verdicts
- verification metrics are recomputed from canonical evidence
- only the production Edge Validator may issue `EDGE_VERIFIED`
