# AG EdgeLab — Funnel Development MVP and Edge Verification Roadmap

Status: architecture / implementation plan

## 1. Objective

AG EdgeLab is split into two authority domains:

1. **Funnel Development Engine (Funnel Lab)** — market data flows through versioned strategy rules; stage results reveal where flow and economic quality improve or deteriorate; researchers change rules on DEVELOPMENT data until a promising candidate exists.
2. **Edge Verification Engine** — receives an immutable frozen candidate and attempts to falsify it on evidence that was not used to develop the strategy. It alone may issue `EDGE_VERIFIED` under the production policy.

The live AG trading runtime remains out of scope. EdgeLab must not connect to brokers, place orders, create executable trade tickets, or authorize Demo/Live execution.

Core lifecycle:

```text
DEVELOPMENT DATA
      |
      v
VERSIONED FUNNEL
      |
      v
STAGE / BRANCH METRICS
      |
      v
WEAK OR REDUNDANT RULE?
      | yes
      v
CONTROLLED RULE MUTATION ----+
      |                       |
      +-----------------------+
      |
      v
PROMISING DEVELOPMENT RESULT
      |
      v
FREEZE FUNNEL + DATA + ENGINE IDENTITY
      |
      v
UNSEEN VALIDATION EVIDENCE
      |
      v
EDGE VALIDATOR
      |
      +--> EDGE_VERIFIED
      +--> NO_EDGE
      +--> INSUFFICIENT_EVIDENCE
```

A good development backtest is **not** `EDGE_VERIFIED`. Any behavior-changing strategy modification after freeze creates a new candidate and a new validation campaign.

---

## 2. Reuse-first infrastructure policy

EdgeLab should be an orchestrator and evidence authority, not another full trading platform.

### Build in AG EdgeLab

- `FunnelDefinition`
- versioned `RuleDefinition`
- `NodeDefinition` and `EdgeDefinition`
- deterministic funnel/decision-graph runner
- per-node and per-branch candidate ledger
- stage-flow metrics
- rule/funnel lineage
- canonical result/trade interchange contracts
- frozen-strategy manifest and content hash
- dataset identity and role controls
- evidence stores and exposure ledger
- production verification policy and verdict authority

### Reuse from open source

- **pandas / NumPy**: tabular and numerical processing
- **Backtesting.py**: initial lightweight trade simulation adapter
- **vectorbt**: later fast parameter/rule-neighborhood experiments
- **Freqtrade**: later crypto adapter plus lookahead and recursive-analysis diagnostics
- **QuantConnect LEAN**: later independent event-driven parity engine

External engines are evidence producers, never verification authorities. EdgeLab must recompute authoritative metrics from canonical stored observations/trades rather than trusting caller-supplied expectancy, PF, drawdown, win rate, or other summaries.

---

## 3. Canonical data boundary

All sources first map into an AG-owned canonical structure.

### `MarketFrame`

Minimum fields:

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

Requirements:

- UTC-aware timestamps only.
- Deterministic ordering.
- No duplicate canonical keys unless explicitly supported.
- Dataset role is explicit: `DEVELOPMENT`, `OOS`, or sealed holdout role.
- Dataset content receives a stable identity/fingerprint.
- Funnel Lab may consume DEVELOPMENT data only unless a campaign explicitly authorizes another non-sealed role.
- Sealed holdout data is never exposed to strategy optimization.

Adapters may ingest existing MT5/local FX data and existing crypto data, but downstream funnel logic sees only canonical `MarketFrame` records.

---

## 4. Funnel model

A funnel is the strategy ruleset. It may be linear or branching.

Example linear strategy:

```text
SESSION_V1
  -> BIAS_V1
  -> SWEEP_V1
  -> DISPLACEMENT_V1
  -> RETEST_V1
  -> ENTRY_V1
  -> EXIT_V1
```

Example branching strategy:

```text
MARKET_STATE_V1
  |-- TREND
  |    |-- BULLISH -> TREND_LONG_V1
  |    `-- BEARISH -> TREND_SHORT_V1
  `-- RANGE
       |-- NORMAL_RANGE -> RANGE_SETUP_V1
       `-- SWEEP -> SWEEP_SETUP_V1
```

A behavior-changing rule modification creates a new rule version and therefore a new funnel identity.

Example:

```text
FUNNEL_V1
  SWEEP_V1

FUNNEL_V1_1
  SWEEP_V2   # only behavior change
```

Documentation, logging, naming, or performance-only changes that preserve deterministic outputs do not create a new strategy version.

---

## 5. MVP V0.1 — minimum Funnel Development Engine

### Goal

Prove the simplest loop:

```text
MarketFrame -> FunnelDefinition -> FunnelRunner -> FunnelMetrics -> compare versions -> freeze candidate
```

### Required contracts

#### `RuleDefinition`

```text
rule_id
rule_version
rule_sha256
rule_type
parameters
input_contract
output_contract
```

MVP rule types:

1. classifier
2. filter/decision
3. trade/action rule

#### `NodeDefinition`

```text
node_id
rule_ref
terminal
```

#### `EdgeDefinition`

```text
from_node
to_node
outcome
```

#### `FunnelDefinition`

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

#### `FunnelEvent`

For every candidate/event at every evaluated node:

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

#### `FunnelRunResult`

```text
funnel_sha256
dataset_sha256
engine_identity
candidate_ledger_hash
trade_list_hash
stage_metrics
```

### MVP metrics

Every stage/branch must expose at least:

```text
INPUT_N
PASS_N
FAIL_N
PASS_RATE
FINAL_TRADE_N
FINAL_WIN_RATE
FINAL_EXPECTANCY_R
```

Recommended immediately if available from canonical trades:

```text
PROFIT_FACTOR
MAX_DRAWDOWN_R
AVG_WIN_R
AVG_LOSS_R
DELTA_EXPECTANCY_VS_PARENT
```

No opaque composite score is required in V0.1.

### MVP workflow

1. Load DEVELOPMENT `MarketFrame`.
2. Load immutable `FunnelDefinition`.
3. Evaluate each candidate through the graph chronologically.
4. Record every node decision, including rejects.
5. Produce canonical trade intents/results through a simulation adapter.
6. Recompute stage metrics from canonical records.
7. Identify stages with poor attrition/economic contribution.
8. Researcher proposes exactly identified rule changes.
9. Create a child funnel version; never mutate the parent.
10. Re-run on DEVELOPMENT data.
11. Compare child with parent.
12. Keep/reject the child as a development decision.
13. Repeat until a promising candidate is selected.
14. Freeze it; development stops for that candidate identity.

### V0.1 acceptance criteria

- deterministic repeat: same data + same funnel + same engine -> same hashes/results
- no future candle access
- all timestamps timezone-aware
- every candidate is represented, including rejects
- a one-rule change changes the funnel identity
- unchanged rules retain identities
- stage counts reconcile parent-to-child
- metrics are recomputed from canonical observations/trades
- no broker/execution capability
- unit and property tests green

---

## 6. MVP simulation adapter

Use a small adapter boundary instead of embedding a third-party engine into validation authority.

```text
FunnelRunner
    |
    v
Canonical OrderIntent / Signal
    |
    v
SimulationAdapter
    |
    v
Canonical TradeList
```

### First adapter

Prefer Backtesting.py for the first implementation when its semantics fit the strategy. The adapter owns translation only. AG owns canonical inputs and outputs.

### Fallback reference simulator

Keep or implement only the smallest deterministic AG simulator necessary for strategies that cannot be represented safely by the first adapter. Do not build brokerage/live execution features.

---

## 7. Funnel Development V0.2 — branching funnels

Add arbitrary acyclic decision branches and branch-level reports.

Acceptance:

- branch routes are explicit outcomes
- branch populations reconcile
- branch metrics are independent
- no candidate silently disappears
- terminal no-trade outcomes remain auditable

This supports Trend/Range/Sweep and E1/E2/E3-style strategies without strategy-specific engine code.

---

## 8. Funnel Development V0.3 — controlled rule/parameter experiments

Add an experiment planner that generates declared child funnels.

Allowed mutation operations:

- replace one rule version
- change one or more preregistered parameters
- remove a rule/edge where the graph remains valid
- add a preregistered rule/edge

Use vectorbt where appropriate for fast DEVELOPMENT-only parameter sweeps/neighborhood calculations.

Do not select a candidate from sealed/unseen validation performance.

Report parameter neighborhoods, not only the single maximum result, to discourage isolated optimum chasing.

---

## 9. Funnel Development V0.4 — diagnostics

Add deterministic diagnostics such as:

- `POSSIBLE_HARMFUL_RULE`
- `POSSIBLE_REDUNDANT_RULE`
- `POSSIBLE_OVER_FILTER`
- `LOW_SAMPLE_STAGE`
- `UNSTABLE_PARAMETER_NEIGHBORHOOD`

Diagnostics are research hints, not verification verdicts.

A rule that reduces raw win rate is not automatically harmful. Economic contribution must consider expectancy and the trade distribution; a lower-win-rate filter can still improve expectancy.

---

## 10. Funnel Development V0.5 — AI experiment assistant

AI may consume DEVELOPMENT reports and propose explicit experiments.

Allowed:

- explain stage attrition
- propose a rule removal/replacement
- propose a bounded parameter neighborhood
- generate a child `FunnelDefinition` proposal
- summarize parent/child differences

Not allowed as authority:

- reading sealed holdout data to design rules
- rewriting a frozen candidate in place
- declaring `EDGE_VERIFIED`
- changing verification policy

Every AI-generated experiment must become an explicit versioned child funnel before execution.

---

## 11. Funnel Development V1.0 — production freeze contract

`FrozenStrategyManifest` is the handoff boundary.

Minimum commitments:

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

Freeze rules:

- manifest is immutable/content-addressed
- frozen strategy cannot consume new DEVELOPMENT changes under the same identity
- any behavior change creates a new funnel hash and new campaign
- exposure state is derived from the authoritative exposure ledger

---

## 12. Edge Verification upgrade roadmap

The Edge Validator is a separate authority path. Development metrics are context, not proof.

### EV V1.0 — unseen OOS economics

Input: frozen strategy identity + authorized unseen OOS evidence IDs.

Verifier recomputes:

- trade count
- expectancy R
- profit factor
- maximum drawdown R
- uncertainty/bootstrap policy metrics

Caller-supplied aggregate metrics are non-authoritative.

Output before full production gate may use `CANDIDATE_PASS`, `NO_EDGE`, or `INSUFFICIENT_EVIDENCE`; reserve `EDGE_VERIFIED` for the full production policy.

### EV V1.1 — authoritative friction

- bind a versioned friction model
- baseline costs are present in canonical evidence
- verifier derives stressed trades itself
- test configured stress levels such as 1.0x / 1.25x / 1.5x
- caller-provided stressed outcome lists are non-authoritative

### EV V1.2 — walk-forward provenance

Each fold commits to:

- unique fold ID
- train window/data identity
- test window/data identity
- strategy identity
- engine identity
- canonical test trades

Verifier checks chronological/non-overlapping policy, minimum populations, dataset lineage, and fold-level economics.

### EV V1.3 — parameter/rule stability

Stability evidence must bind:

- frozen center parameter/funnel identity
- real neighboring parameter/funnel identities
- common DEVELOPMENT population/dataset identity
- engine/code identity
- preregistration before holdout exposure

The verifier recomputes neighborhood results from stored trade lists. Arbitrary profitable lists cannot stand in for real neighboring configurations.

### EV V1.4 — regime robustness

- frozen strategy commits to a classifier identity
- market-state evidence is content-addressed
- verifier/classifier authority derives regime labels
- caller-supplied labels are non-authoritative
- regime metrics are recomputed from canonical trades

### EV V1.5 — independent parity

Use an owner-approved engine registry with at least two genuinely independent engine identities.

Suggested later independent engine: QuantConnect LEAN, because it is event-driven, modular, open source, and supports local backtesting with custom data.

Parity must resolve both canonical stored trade lists and compare the required trade identity/outcome fields. An engine's aggregate report is not authoritative evidence.

### EV V2.0 — production `EDGE_VERIFIED`

Full gate requires coherent evidence for all policy-required dimensions:

```text
FROZEN STRATEGY
  -> UNSEEN OOS ECONOMICS
  -> STATISTICAL / BOOTSTRAP GATE
  -> FRICTION
  -> WALK-FORWARD
  -> STABILITY
  -> REGIMES
  -> INDEPENDENT PARITY
  -> EXPOSURE / PROVENANCE CHECKS
  -> EDGE_VERIFIED | NO_EDGE | INSUFFICIENT_EVIDENCE
```

`NO_EDGE` is for coherent negative evidence. Missing, malformed, contradictory, unresolved, or provenance-incoherent evidence must fail closed as `INSUFFICIENT_EVIDENCE`.

---

## 13. External-system integration sequence

### Phase A — MVP

Use:

- existing AG datasets
- pandas / NumPy
- Backtesting.py adapter where appropriate
- existing EdgeLab canonical contracts/validator work

Do not add LEAN/Freqtrade/vectorbt simultaneously.

### Phase B — fast research

Add vectorbt adapter for DEVELOPMENT-only batch rule/parameter experiments.

### Phase C — crypto diagnostics

Add Freqtrade integration for crypto datasets/backtests where useful. Run its lookahead-analysis and recursive-analysis as supplementary diagnostics. Their reports do not replace AG provenance or final verification.

### Phase D — independent parity

Add LEAN as an owner-approved independent engine. Keep live deployment disabled/out of scope.

---

## 14. Proposed repository layout

```text
src/ag_edgelab/
  data/
    market_frame.py
    adapters/
  funnel/
    definition.py
    rules.py
    graph.py
    runner.py
    events.py
    metrics.py
    lineage.py
    freeze.py
  simulation/
    contracts.py
    backtesting_py_adapter.py
    vectorbt_adapter.py        # V0.3+
    freqtrade_adapter.py       # later
    lean_adapter.py            # EV V1.5+
  experiments/
    compare.py
    mutations.py
    diagnostics.py
  verification/
    ... existing production validator ...

tests/
  funnel/
  simulation/
  experiments/
  verification/

docs/
  FUNNEL_DEVELOPMENT_AND_EDGE_VERIFICATION_ROADMAP.md
```

---

## 15. Delivery work packages

### WP-F0 — lineage and scope gate

- choose authoritative branch/base
- protect current production-validator lineage
- confirm sealed holdout remains inaccessible
- document no-execution invariant

### WP-F1 — canonical `MarketFrame`

- schema
- timestamp policy
- dataset identity
- adapters for already-available data
- tests

### WP-F2 — Funnel contracts

- rules/nodes/edges/funnel schema
- canonical serialization/hash
- validation
- tests

### WP-F3 — deterministic runner + candidate ledger

- chronological graph execution
- explicit reject/route records
- reconciliation invariants
- anti-lookahead context
- tests

### WP-F4 — metrics

- stage counts/pass rate
- final trade conversion
- win rate
- expectancy R
- PF/DD/average R metrics
- parent-child delta report
- tests

### WP-F5 — first simulation adapter

- canonical signal/order-intent translation
- canonical trade-list output
- no broker/live methods
- deterministic fixture parity tests

### WP-F6 — versioning and comparison

- immutable parent/child funnel versions
- changed-rule manifest
- report diff
- tests

### WP-F7 — freeze handoff

- `FrozenStrategyManifest`
- content-addressed storage
- exposure ledger transition
- validator-compatible evidence references
- tests

### WP-F8 — first reference strategy

Encode one simple real strategy as a funnel and prove end-to-end:

```text
market data
-> funnel
-> stage report
-> controlled child version
-> comparison
-> freeze
```

Do not use sealed holdout data for this demonstration.

### WP-F9 — research acceleration

- vectorbt experiment adapter
- bounded mutation batches
- neighborhood reports

### WP-F10 — crypto diagnostics

- optional Freqtrade adapter
- lookahead-analysis integration
- recursive-analysis integration

### WP-F11 — independent parity

- LEAN adapter
- canonical trade-list conversion
- EngineRegistry integration
- parity evidence

---

## 16. CI gates

Every PR touching Funnel Lab or verification should run, as applicable:

```text
compile/type/static checks
unit tests
property/invariant tests
canonical serialization/hash tests
anti-lookahead tests
timestamp authority tests
candidate population reconciliation tests
trade-list recomputation tests
malformed evidence fail-closed tests
no-execution-capability test
```

Later integration jobs may include external-engine adapter tests, but third-party availability must not weaken core deterministic tests.

---

## 17. Security and research-integrity invariants

1. No live or Demo execution capability in EdgeLab.
2. No sealed holdout access from Funnel Lab.
3. No caller boolean can assert unseen/frozen authority.
4. No caller aggregate metric is verification authority.
5. Every behavior-changing rule has a new identity.
6. Every frozen funnel is content-addressed.
7. Failed validation never edits the frozen strategy; research returns to DEVELOPMENT and creates a new version.
8. External engines provide evidence, never final verdicts.
9. Missing/incoherent authority fails closed.
10. Holdout exposure is irreversible according to ExposureLedger policy.

---

## 18. Definition of MVP complete

Funnel Development MVP is complete when a developer can:

1. import an existing DEVELOPMENT dataset into `MarketFrame`;
2. define a versioned linear funnel without editing engine internals;
3. run all candidates through it deterministically;
4. inspect input/pass/fail counts and downstream economic metrics at each stage;
5. create a child funnel changing one rule;
6. rerun and compare parent vs child;
7. preserve both results and lineage;
8. freeze a selected candidate into an immutable manifest;
9. hand only evidence IDs/identities to the Edge Validator;
10. do all of the above with no broker/execution capability and no sealed-holdout access.

The MVP does **not** require AI optimization, a UI, LEAN, Freqtrade, automated strategy discovery, or `EDGE_VERIFIED` issuance.

---

## 19. Definition of production Edge Validator complete

Production `EDGE_VERIFIED` is available only when the frozen candidate passes the pinned policy's required gates with authoritative evidence and all metrics are recomputed from content-addressed canonical records/trade lists.

At minimum the production policy is expected to cover:

- immutable frozen strategy identity
- authoritative unseen/exposure state
- OOS economics and uncertainty
- deterministic friction stress
- walk-forward provenance
- real stability-neighborhood provenance
- authoritative regime classification
- owner-approved independent-engine parity
- fail-closed malformed/missing evidence behavior
- immutable policy identity

The exact policy thresholds belong in the versioned production policy registry, not in this architecture document.

---

## 20. Recommended implementation order

```text
Finish / independently audit current validator remediation
                 |
                 v
WP-F0 lineage gate
                 |
                 v
WP-F1 MarketFrame
                 |
                 v
WP-F2 FunnelDefinition
                 |
                 v
WP-F3 FunnelRunner + CandidateLedger
                 |
                 v
WP-F4 FunnelMetrics
                 |
                 v
WP-F5 lightweight simulator adapter
                 |
                 v
WP-F6 version comparison
                 |
                 v
WP-F7 freeze handoff
                 |
                 v
WP-F8 first real strategy
                 |
                 +--> MVP COMPLETE
                 |
                 v
WP-F9 vectorized experiments
                 v
WP-F10 crypto diagnostics
                 v
WP-F11 independent LEAN parity
                 v
Production Edge Validator V2 campaign
```

This order keeps the trusted core small, maximizes reuse, and prevents research convenience from weakening evidence authority.
