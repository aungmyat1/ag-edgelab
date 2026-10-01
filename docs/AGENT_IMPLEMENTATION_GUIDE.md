# AG EdgeLab — Code Agent Implementation Guide

Use this document before making implementation changes.

## 1. Required reading order

1. `README.md`
2. `docs/ARCHITECTURE.md`
3. `docs/FUNNEL_MODEL.md`
4. `docs/FUNNEL_DEVELOPMENT_AND_EDGE_VERIFICATION_ROADMAP.md`
5. relevant source/tests/audit documents for the requested work package

Do not infer missing trading rules from names such as `SWEEP`, `POI`, `DISPLACEMENT`, `BIAS`, `RETEST`, `OB` or `FVG`. A rule name is not a specification.

## 2. Authority rules

### Funnel Lab may
- read DEVELOPMENT data
- execute deterministic strategy rules
- compute development diagnostics
- create explicit child strategy/funnel versions
- compare experiments
- create a freeze manifest

### Funnel Lab may not
- access sealed holdouts
- issue `EDGE_VERIFIED`
- silently mutate an existing strategy identity
- place broker orders

### Edge Validator may
- resolve authorized content-addressed evidence
- recompute metrics
- derive authoritative state from registries/ledgers
- issue policy-defined verdicts

### Edge Validator may not
- optimize/change strategy rules
- trust caller aggregate metrics
- silently repair malformed evidence
- open sealed evidence merely to improve a strategy

## 3. First MVP target

Do not overbuild. The first Funnel Lab vertical slice is:

```text
MarketFrame
 -> Rule/Funnel contracts
 -> CandidateLedger/FunnelRunner
 -> canonical final outcomes
 -> phase/rule flow metrics
 -> PASS/FAIL final win-rate attribution
 -> Weak Funnel Diagnostic report
```

Minimum report:

```text
stage_id
rule_id
input_n
pass_n
fail_n
flow_pct
pass_final_trade_n
fail_final_trade_n
pass_final_win_rate
fail_final_win_rate
parent_final_win_rate
delta_win_rate_vs_parent_pp
selection_effect_pp
diagnostic_label
```

Labels are development diagnostics only.

## 4. Work-package sequence

Implement in this order unless an explicit audited mission changes it:

- WP-F0 lineage/scope
- WP-F1 MarketFrame
- WP-F2 RuleDefinition/FunnelDefinition and canonical hashing
- WP-F3 chronological FunnelRunner + complete CandidateLedger
- WP-F4 Weak Funnel Diagnostic MVP
- WP-F5 minimal simulation adapter
- WP-F6 economic metrics (expectancy/PF/DD)
- WP-F7 immutable parent/child comparison
- WP-F8 branching funnels
- WP-F9 FrozenStrategy handoff
- WP-F10 vectorbt experiments
- WP-F11 Freqtrade diagnostics
- WP-F12 LEAN independent parity

Do not integrate large external systems earlier merely because they are available.

## 5. Implementation invariants

Every implementation must preserve:

- UTC-aware timestamps
- chronological deterministic processing
- no future-data access
- stable canonical serialization/hashing
- explicit dataset role/identity
- complete candidate accounting
- explicit terminal/rejection reason
- deterministic repeatability
- immutable rule/funnel versions
- parent/child lineage
- no broker/live execution
- fail-closed verification behavior

## 6. Candidate accounting

For every node/rule, assert where applicable:

```text
input_n = pass_n + fail_n + routed_or_terminal_n
```

No candidate may disappear due to filtering, exceptions or adapter behavior.

Rejected candidates are first-class research evidence because weak-funnel analysis needs to compare selected and rejected populations where methodology permits.

## 7. Counterfactual caution

Do not invent final trades for candidates rejected before entry. `FAIL final win rate` is only valid when a defined comparable-outcome/counterfactual methodology exists. If it does not exist, emit unavailable/insufficient rather than manufacturing an outcome.

This constraint is more important than filling every dashboard cell.

## 8. Scoring caution

V0.1 uses win rate for the first human-readable diagnostic. Do not turn it into an optimization objective for production.

V0.2 must add expectancy R. Example:

```text
WR falls, expectancy rises -> not automatically weak
WR rises, expectancy falls -> not automatically better
```

Avoid opaque composite 0-100 scores until underlying metrics and weighting policy are explicitly defined and justified.

## 9. Rule mutation discipline

Behavior change => new rule identity => new funnel identity.

Never:

```text
change SWEEP_V1 implementation while retaining SWEEP_V1 identity
```

Instead:

```text
SWEEP_V1 -> SWEEP_V2
FUNNEL_V1 -> child FUNNEL_V1_1
```

Record exact mutation lineage.

## 10. External engine integration

Prefer thin adapters and canonical interchange records over copying external code into the trusted core.

Use:
- Backtesting.py first where simulation semantics fit
- vectorbt later for fast development experiments
- Freqtrade later for crypto/lookahead/recursive diagnostics
- LEAN later for independent parity

External metrics are informational. Verification authority must recompute from canonical evidence.

## 11. Testing expectations

Each work package should include deterministic unit/regression tests. Important attack/invariant classes include:

- future-data/lookahead access
- malformed IDs/evidence
- timestamp timezone mismatch
- population disappearance/substitution
- rule/funnel hash tampering
- same identity with changed behavior
- duplicate trade/candidate IDs
- nonchronological records
- insufficient sample misclassification
- caller metric substitution
- provenance/engine/dataset mismatch

Verification-specific adversarial tests from prior audits remain permanent regressions; Funnel Lab work must not weaken them.

## 12. Definition of done for a work package

Report at minimum:

```text
STATUS = PASS | BLOCKED | FAIL
BASE/PARENT_SHA = ...
FINAL_SHA = ...
TREE_SHA = ...
WORKTREE_CLEAN = YES/NO
TEST_COUNT = ...
TESTS = PASS/FAIL
CHANGED_FILES = ...
SEALED_HOLDOUT_ACCESSED = NO
EXECUTION_CAPABILITY_ADDED = NO
```

Also report which documented acceptance criteria were proven and any remaining risks.

## 13. Stop conditions

Stop rather than improvise when:

- expected repository lineage/target commit is unavailable
- strategy rule semantics are missing/ambiguous
- required evidence identity cannot be resolved
- a task would require sealed-holdout access contrary to policy
- a proposed implementation introduces execution authority
- documentation and authoritative code/audit constraints materially conflict

A clean `BLOCKED` report is preferable to inventing semantics.
