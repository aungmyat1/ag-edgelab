# AG EdgeLab + AG Profit Trading — Master Implementation Plan

Updated: 2026-10-06

## Objective

The goal is the shortest governed route from an UNVERIFIED strategy to a trustworthy terminal verdict, ending with at least one FX and one crypto strategy that is EDGE_VERIFIED and eligible for separately governed AG Profit Trading demo validation.

Speed means:
- reject weak parents before optimization;
- use DEVELOPMENT evidence repeatedly but never OOS/holdout as optimization data;
- target weak rules instead of brute-force searching everything;
- use existing/open-source data first;
- collect missing live/measured evidence in parallel;
- spend irreversible evidence only on frozen robust survivors.

NO_EDGE, INSUFFICIENT_EVIDENCE, DATA_BLOCKED, FRICTION_BLOCKED and BUDGET_EXHAUSTED are valid outcomes.

## Baseline

- EdgeLab main at plan creation: fdabc07.
- PR #20 remains open and unmerged; R2C records/owner decisions are therefore not yet canonical main authority.
- EDGE_VERIFIED count: 0 FX / 0 crypto.
- FX multi-year development authority exists; crypto canonical data authority remains incomplete.
- Measured venue friction authority remains incomplete.
- Universal funnel analyzer exists, but rejected opportunities do not yet have comparable counterfactual/reference outcomes.
- 2017 Sep-Nov OOS was previously consumed by earlier candidates; do not describe all OOS as fresh.
- Sealed holdout remains protected.

## Non-negotiable invariants

1. EdgeLab is research-only: no broker/order mutation.
2. OOS and sealed holdout are never optimization data.
3. Every evaluated child counts in one campaign-wide trial ledger.
4. Missing friction/data/policy is UNAVAILABLE/BLOCKED, never zero or guessed.
5. Governance remains append-only.
6. Cheap reversible checks precede expensive/irreversible evidence.
7. Implementation changes are PR-only.
8. Owner policy decisions remain explicit; agents do not guess them.
9. Behavior changes create new deterministic strategy identities.
10. Optimization authority ends at freeze.

## Open-source-first + live-evidence acceleration policy

Use already-authorized or independently verifiable public data before acquiring new proprietary data.

### FX development
Priority order:
1. Existing content-addressed multi-year FX authority and its repository acquisition script/manifest.
2. Materialize only the preregistered fixture subset needed for the current mission.
3. For Funnel Optimizer V1, default fixture proposal is EURUSD + GBPUSD, DEVELOPMENT windows 2015-2017, because those windows are already development-known. This is a fixture proposal, not new authority.
4. Acquisition is timeboxed to 60 minutes. If unavailable/slow, stop acquisition and complete infrastructure on synthetic fixtures with DATA_BLOCKED recorded.

Never redownload all 63 symbol-years merely to prove an optimizer API.

### Crypto development/evidence
Prefer public exchange archives with published checksums and explicit UTC/bar-close semantics. Preserve OHLCV, funding, mark/index and fee evidence separately. Missing bars/funding are errors or missing evidence, never forward-filled or replaced by zero.

Crypto data admission is a separate authority task; public availability alone does not make data canonical.

### Live/measured evidence
Live collection runs in parallel and must never block DEVELOPMENT infrastructure:
- FX: read-only VT Markets/approved venue capture for spread, commission, swap and observable slippage by exact symbol/session.
- Crypto: public market/funding/fee evidence may be collected continuously with source/as-of/hash provenance.
- Raw capture bundles are sealed/content-addressed and immutable.
- Credentials are never committed and must not appear in argv.
- Live observations do not become OOS, holdout, or EDGE_VERIFIED evidence merely because they are recent.
- A collector must fail closed if any order/mutation capability is reachable.

## Runtime pipeline

UNVERIFIED STRATEGY
-> contract/intake
-> relaxed replay
-> all-opportunity event table
-> parent eligibility vs matched random baseline
-> if FAIL: terminal DEV_REJECTED_NO_SIGNAL
-> if PASS: stage diagnostics + valid leave-one-out/ablation
-> targeted DEVELOPMENT optimization within campaign budget
-> cheap friction-aware screen when scenario authority exists
-> robustness/neighborhood screen
-> locked DEV_VALIDATION promotion gate
-> freeze exact candidate
=== OPTIMIZATION AUTHORITY WALL ===
-> measured friction lock
-> PRE-OOS
-> one authorized fresh OOS spend
-> sealed holdout only under policy
-> EDGE_VERIFIED | NO_EDGE | INSUFFICIENT_EVIDENCE

## Funnel Optimizer V1 correctness amendments

### Reference outcomes
Attribution must compare one outcome model. Store:
- reference_outcome_r for every opportunity where the reference model is evaluable;
- actual_outcome_r separately for actual parent trades;
- actual_trade boolean;
- outcome_authority = REFERENCE_OUTCOME for counterfactual/reference rows.

Never compare PASS actual trades directly with FAIL reference outcomes.

### Tri-state rules
Relaxed replay uses PASS / FAIL / NOT_EVALUABLE.

NOT_EVALUABLE means an upstream structure required by the rule does not exist. Never fabricate a later-stage value merely to fill the table.

### Frozen strategy protection
Relaxed replay is implemented as a wrapper/adapter. Never edit a frozen strategy module to make it optimizer-friendly.

### Attribution
Stage PASS-vs-FAIL deltas answer WHERE TO INVESTIGATE.
Leave-one-out/ablation answers WHETHER REMOVAL APPEARS TO ADD VALUE.
Only perform leave-one-out when removal semantics are defined. Structural/path-dependent removals return REQUIRES_FULL_REPLAY.

### Eligibility modes
If approved friction scenario exists:
ELIGIBILITY_MODE = ECONOMIC.

If friction scenario is unresolved:
ELIGIBILITY_MODE = STRUCTURAL,
compare gross parent/reference expectancy with gross matched baseline,
and keep ECONOMIC_RANKING = BLOCKED.

Structural eligibility can reject noise; it cannot establish tradability or edge.

## Owner inputs

The optimizer must not invent these:
- REFERENCE_OUTCOME_MODEL
- RANDOM_BASELINE_COUNT (proposal: 1000)
- DEV_FRICTION_SCENARIO
- DEV_SEARCH / DEV_VALIDATION boundaries
- campaign search budget
- OOS spending policy
- FRICTION_VENUE and exact symbols/account type
- V2.1 kill rule and AMB_1..AMB_4 if V2.1 is ever replayed
- session-authority conflict if a session parent depends on it

If the first three are unresolved, the 6-hour mission still builds the machinery and may run STRUCTURAL eligibility where semantics are already authorized.

## Six-hour acceleration mission

### 00:00-00:30 — Preflight
Record base/head/tree/worktree, candidate-ledger hash, OOS-log hash and contamination-registry hash. Run focused baseline tests. Confirm no OOS/holdout/broker mutation.

### 00:30-01:30 — Data materialization + relaxed replay skeleton
In parallel:
- attempt the preregistered small FX fixture acquisition/materialization using existing repository tooling;
- hard timebox data work to 60 minutes;
- build a new relaxed-replay wrapper, not a frozen-strategy edit.

On acquisition overrun: stop data work, mark DATA_BLOCKED, continue with synthetic fixtures.

### 01:30-02:30 — All-opportunity event table
Produce deterministic, hashed/cached rows with tri-state rule cells, feature values, reference outcome, separate actual outcome, identities and reason codes.

### 02:30-03:15 — Attribution
Implement stage diagnostic deltas and valid ablation/leave-one-out. Undefined/path-dependent removals fail closed as REQUIRES_FULL_REPLAY.

### 03:15-04:00 — Fast children
Support only table-query-safe threshold/filter changes and valid removals. Every child gets parent lineage and deterministic identity.

### 04:00-04:45 — Campaign ledger + ranking
Count every trial cumulatively. Rank by net expectancy when approved scenario friction exists; otherwise keep economic ranking blocked and expose structural metrics only. PF/DD/N and neighborhood stability are guards; win rate is diagnostic only.

### 04:45-05:30 — Parent eligibility
Run matched seeded baseline machinery. Use the authorized baseline count. If no economic scenario exists, run STRUCTURAL_ELIGIBILITY only. A known weak fixture must not be hard-coded to fail; the verdict must follow canonical evidence.

### 05:30-06:00 — Acceptance
Stop feature work. Run tests, artifact verifier/relevant suite, generate acceptance artifact, commit/push, and open a draft PR if incomplete.

At exactly 6:00, preserve all valid work. Never leave useful work only uncommitted because the timebox expired.

## Six-hour acceptance tests

Required:
- PASS rows can carry reference outcomes.
- FAIL rows can carry reference outcomes.
- actual_outcome and reference_outcome are separate.
- reference outcome is never mislabeled actual trade.
- NOT_EVALUABLE is exercised on path-dependent rules.
- event-table ordering/hash deterministic.
- valid ablation reconciles with full replay fixture.
- structural removals fail closed when undefined.
- every child increments campaign trial count.
- trial count never resets/decreases.
- missing friction never becomes zero.
- OOS and holdout access are rejected.
- frozen strategy source is unchanged.
- negative/noise fixtures cannot be promoted.
- acquisition failure does not weaken authority; it produces DATA_BLOCKED/synthetic-only evidence.

## Parallel evidence tracks

These should start immediately but are not required to finish the six-hour optimizer mission.

### FX measured friction
Run read-only daily capture on the approved Windows MT5 host across required sessions. Seal raw bundles with source, terminal symbol, account type, timestamps and hashes. Target enough trading days to support the preregistered friction authority; do not invent a calendar threshold inside an agent mission.

### Crypto authority
Build/admit checksum-verified public archive ingestion with missing-bar checks, explicit timestamps and separate funding/mark/index/fee evidence. Public data must pass EdgeLab authority/admission before verification use.

## Candidate campaigns after MVP

Prefer diverse simple parents over repeated refinement of one SMC family:
- time-of-day/session drift;
- volatility-conditioned breakout;
- trend pullback;
- carry/funding hypotheses for crypto;
- selected existing session/SMC parents as controls.

Most parents should die cheaply. The primary program metric is time from UNVERIFIED to a trustworthy terminal verdict.

## Explicitly not in the six-hour mission

- DEV_VALIDATION opening
- production promotion/freeze decision
- PRE-OOS/OOS/holdout
- V2.1 historical replay
- AI experiment assistant
- general Optuna-style optimizer
- unlimited combinations/rule bundles
- full 63-symbol-year reacquisition
- broker/order integration
- EDGE_VERIFIED issuance
- AG Profit Trading cleanup

## Delivery protocol

Every implementation mission:
1. branches from current origin/main or an explicitly authorized base;
2. records exact base identity;
3. makes small commits;
4. runs focused tests plus the relevant canonical suite/verifier;
5. pushes and opens a PR;
6. reports counts verbatim;
7. receives independent file-level review before merge;
8. converts each discovered defect class into a regression/lock test.

## Final objective

EdgeLab is successful when it can rapidly take an unverified rule-based strategy, reject noise cheaply, optimize only on authorized DEVELOPMENT evidence, freeze a robust survivor without hidden search pressure, and independently verify it using measured friction and protected unseen evidence. The program target remains at least one FX and one crypto EDGE_VERIFIED strategy, but the system must prefer an honest NO_EDGE over a manufactured pass.
