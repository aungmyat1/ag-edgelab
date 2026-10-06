# Funnel Optimizer V1 — development-only vertical slice

## Purpose and boundary

This slice implements the governed path from a DEVELOPMENT opportunity replay to
an honest terminal decision:

```text
UNVERIFIED → RelaxedReplay → all-opportunity event table
           → structural eligibility / matched random baseline
           → stage diagnostic + valid ablation
           → exact table-query child → append-only campaign ledger
```

It is **research-only**.  It does not load a broker, create an order, use a
live/OOS/holdout outcome, issue `EDGE_VERIFIED`, or mutate a frozen strategy.
`RelaxedReplay.evaluate()` requires both `DatasetRole.DEVELOPMENT` and
`DatasetExposure.DEVELOPMENT`; OOS and sealed-OOS roles raise before any event
table is built.

The implementation is in `ag_edgelab.optimization.funnel_optimizer`.  The
ALD V2 integration lives in the new
`ag_edgelab.strategies.asian_liquidity_displacement_v2_relaxed` adapter.  The
frozen `asian_liquidity_displacement_v2.py` is not altered.

## Event-table contract

Every row has stable identity fields, chronological `sequence_no`, tri-state
rule cells, and two distinct outcome channels:

| Field | Meaning |
| --- | --- |
| `reference_outcome_r` | Explicit counterfactual/reference model result, usable for PASS **and** FAIL attribution populations. |
| `actual_outcome_r` | Parent-trade result only; it is never filled from a reference outcome. |
| `actual_trade` | `false` for every rejected row. |
| `reference_outcome_status` | `EVALUABLE` or `NOT_EVALUABLE`; unavailable values are not zero-filled. |
| `outcome_authority` | `REFERENCE_OUTCOME` only where that reference value exists. |

Rules use `PASS`, `FAIL`, and `NOT_EVALUABLE`.  A dependency that did not pass
makes a downstream rule `NOT_EVALUABLE`; an independent later rule is still
evaluated.  This prevents a normal first-failure strategy runner from turning
unknown downstream semantics into false rejections.

`EventTable.write_cache()` writes canonical JSONL plus a content-hash manifest.
Rows are normalized by UTC timestamp, symbol, candidate ID, and event ID.

## Attribution and fast children

`stage_diagnostics()` computes PASS/FAIL expectancy and selection delta using
**reference outcomes on both sides**.  It is diagnostic, not causal.

`leave_one_out()` allows a table removal only when the rule is explicitly
`TABLE_QUERY_SAFE` and no later rule depends on it.  Structural/path-dependent
rules and rules with semantic dependants return `REQUIRES_FULL_REPLAY`; no
ablation number is manufactured.

`FastChildEngine` supports only:

1. a numeric threshold change whose rule stored the exact feature value; and
2. an explicitly safe independent filter removal.

A child ID is a deterministic hash of campaign, parent, experiment type, and
rule diff.  `CampaignLedger.append()` creates strictly increasing campaign-wide
trial numbers, including failed or `REQUIRES_FULL_REPLAY` attempts.  Changing a
working parent cannot reset the counter.

## Eligibility and friction

`structural_parent_eligibility()` selects only all-pass rows that have
reference outcomes and compares them with fixed-seed random samples from the
same `(dataset, symbol, session, calendar-year)` eligible opportunity strata.
It cannot run a real fixture until `RANDOM_BASELINE_COUNT` is owner-authorized.
A `synthetic_test_only` baseline configuration exists only to test machinery;
it has no authority for real evidence.

Without an explicit approved `FrictionScenario`, `rank_child()` returns:

```text
ELIGIBILITY_MODE = STRUCTURAL
ECONOMIC_RANKING = BLOCKED
scenario_net_expectancy_r = null
```

It never silently assigns friction zero.  A structural pass remains
`STRUCTURAL_ELIGIBLE_NOT_EDGE`, not tradability or verification.

## FX fixture materialization

`config/governance/funnel_optimizer_v1_fixture_preregistration.json` registers
the small, DEVELOPMENT-only EURUSD/GBPUSD 2015–2017 candidate fixture and
forbids each year's Sep–Nov OOS and December holdout.  It records the six raw
archive hashes, source identity proof, exact source, and duration.

To reproduce materialization (raw data is gitignored):

```bash
PYTHONPATH=src .venv/bin/python scripts/materialize_funnel_optimizer_fx_fixture.py \
  --timebox-minutes 60
```

The script obtains only those six symbol-years, checks the two 2017 repository
pins and verifies byte identity of each 2017 mirror archive against its pinned
archive.  It never decodes bars during acquisition.  Any network, checksum, archive, or
timebox issue writes a `DATA_BLOCKED` receipt—synthetic proof does not inherit
that dataset identity.

The downloaded bytes are materialized, but this mission intentionally does not
run a real strategy event table from them: `REFERENCE_OUTCOME_MODEL`,
`RANDOM_BASELINE_COUNT`, and `DEV_FRICTION_SCENARIO` are unresolved owner
inputs.  This is why the machine acceptance artifact labels the generated
14-row table `SYNTHETIC_FUNNEL_NEGATIVE_V1`, rather than market evidence.

## Acceptance proof

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_funnel_optimizer_v1.py
PYTHONPATH=src .venv/bin/python scripts/run_funnel_optimizer_v1_acceptance.py
```

The second command produces `artifacts/funnel_optimizer_v1/`:

- a deterministic 14-opportunity negative event table and content manifest;
- a separate mechanism-only append-only child ledger;
- `acceptance_evidence.json`, including rule-cell counts, frozen ALD V2 hash,
  eligibility block/rejection evidence, data provenance, and explicit no-OOS /
  no-holdout / no-broker / no-EDGE_VERIFIED assertions.

The synthetic parent fails its fixed-seed matched baseline and terminates as
`DEV_REJECTED_NO_SIGNAL`.  No child is presented as an optimization continuation
of that rejected parent; the two child-ledger rows are a separate API mechanism
proof.

## Deferred owner decisions

Before a real FX replay may use this vertical slice, the owner must supply:

1. `REFERENCE_OUTCOME_MODEL` and its identity/semantics;
2. an authorized `RANDOM_BASELINE_COUNT` and campaign budget; and
3. an approved `DEV_FRICTION_SCENARIO` if economic ranking is desired.

A future mission must implement the all-opportunity ALD V2 fact producer (not
modify frozen V2), evaluate only the registered DEVELOPMENT windows, and stop
at freeze.  It must not spend OOS or sealed holdout evidence to rescue an
unqualified parent.
