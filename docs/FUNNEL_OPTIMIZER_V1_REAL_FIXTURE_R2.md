# Funnel Optimizer V1 R2 — real DEVELOPMENT fixture integration

## Scope and owner policy

R2 connects the materialized FX fixture to the PR #22 Funnel Optimizer V1
mechanism without changing frozen ALD V2 or opening any protected partition.

| Policy | R2 value |
| --- | --- |
| Reference outcome model | `FIXED_REFERENCE_2R_V1` |
| Matched random baselines | 1,000, deterministic seed derived from immutable campaign inputs |
| Eligibility mode | `STRUCTURAL` |
| Friction | `UNRESOLVED`; economic ranking is `BLOCKED` |
| Search budget | 100 children per eligible parent |

The registered fixture is EURUSD and GBPUSD in 2015–2017.  Every annual
DEVELOPMENT window is `[Jan 1, Sep 1) UTC`.  OOS and sealed-holdout roles are
rejected before a raw fixture archive is opened.

## Non-mutating fact producer

`ag_edgelab.strategies.asian_liquidity_displacement_v2_real_fixture` is a new
adapter.  It:

1. verifies the preregistered raw zip hash;
2. streams only local Jan–Aug source rows, converts only rows inside the UTC
   DEVELOPMENT interval into M1 bars, and explicitly records zero parsed OOS /
   holdout rows;
3. applies the existing M15/M5 aggregation and H1/H4/D1 derivation contracts;
4. invokes frozen `asian_liquidity_displacement_v2.replay_symbol`; and
5. maps recorded parent stages to PASS/FAIL and absent downstream stages to
   `NOT_EVALUABLE`.

The parent is therefore the authority for session clocks, opportunity basis,
structure construction, branch semantics, canonical confirmation entry, and
structural invalidation.  No frozen source is edited or monkey-patched.

## `FIXED_REFERENCE_2R_V1`

The reference evaluator applies only when frozen V2 defined an S7 canonical
entry and invalidation.  It records:

- entry price/time: confirmation-close price and next M5 bar open time;
- stop: frozen V2 structural invalidation;
- target: exactly two times the structural risk from entry;
- exit price/time/reason: `TARGET_2R`, `STOP`, `TIMEOUT`, or `NOT_EVALUABLE`.

It traverses subsequent M5 candles in chronological order through frozen V2's
existing 288-M5-bar opportunity horizon.  A truncated unresolved horizon is
`NOT_EVALUABLE`, never a fabricated timeout. If stop and target touch in the same M5 candle, it returns
`reference_outcome_status=NOT_EVALUABLE`,
`reference_exit_reason=NOT_EVALUABLE`, and
`reference_ambiguity_code=AMBIGUOUS_INTRABAR`.  It does not select a favorable
side.  The result is optimizer attribution evidence only—not an actual trade,
parent performance result, OOS evidence, or EDGE_VERIFIED evidence.

## Running and artifacts

```bash
PYTHONPATH=src .venv/bin/python scripts/run_funnel_optimizer_v1_real_fixture.py
```

The runner executes two independent real-fixture productions and requires the
same event-table hash.  It writes:

- `artifacts/funnel_optimizer_v1_real_fixture_r2/real_development_event_table.jsonl`;
- its content-hash manifest; and
- `real_fixture_acceptance_evidence.json`, with data quality, outcome counts,
  all 1,000-baseline summary statistics, attribution, and governance flags.

The only safe child forms are table-query thresholds and semantic-safe removal.
All ALD V2 stages are marked structural/path-dependent in this R2 adapter, so
its real fixture has zero valid fast ablations and zero child trials.  This is a
fail-closed result, not an omitted search.

## R2 result boundary

The R2 structural result is not an economic or edge verdict.  A structural pass
only means the full frozen parent selection exceeded its fixed-seed matched
reference opportunity baseline under this reference model.  `FRICTION` remains
unresolved, no scenario net expectancy is calculated, and no `EDGE_VERIFIED`
state is available.
