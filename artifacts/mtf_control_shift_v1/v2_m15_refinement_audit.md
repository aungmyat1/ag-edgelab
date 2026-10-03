# M15 refinement authority audit

Candidate: `ST_MTF_CONTROL_SHIFT_V2 @ 2.0.0`

## Root verdict

`M15_ZERO_IS_SOURCE_FAITHFUL`

All 18 V2 H1-shift-pass cases were audited. Every case failed at the source-defined session-time requirement for M15 zone creation. The frozen source and the EdgeLab replay returned the same result for all 18 cases, and causal clipped-data replay passed for all 18.

## Source semantics

Source references:

- `src/mtf_control_shift/engine.py:evaluate`
- `src/mtf_control_shift/structure.py:zones`
- `src/mtf_control_shift/structure.py:confirmed_swings`
- `src/mtf_control_shift/structure.py:fvg`

The exact source M15 refinement behavior is:

1. A valid H1 control shift must already exist.
2. The M15 entry zone must have the same direction as the HTF bias:
   - bullish → `DEMAND`
   - bearish → `SUPPLY`
3. The zone must be produced by the frozen `zones()` function, which requires:
   - confirmed swing strength 2
   - strict three-candle FVG
   - close beyond the latest already-confirmed same-direction swing
   - latest opposite-color origin candle within the six-bar lookback
4. The M15 zone creation timestamp must be at or after the H1 shift creation timestamp.
5. The M15 zone creation timestamp must be inside the active session window.
6. The source selects the latest qualifying zone; it does not require a separate midpoint retest before producing a signal.
7. Geometry is evaluated only after a qualifying M15 zone exists.

A closed M15 bar is available only when its 15-minute bucket has closed at the evaluation timestamp. No future M15 FVG, zone, retest, or midpoint touch is exposed.

## Full 18-case reconciliation

- H1 shift-pass cases: `18`
- Cases audited: `18`
- Source refinement passes: `0`
- EdgeLab refinement passes: `0`
- Source/EdgeLab matches: `18`
- M15 failure: `SESSION_WINDOW_EXPIRED` in `18/18` cases

The detailed ledger is `v2_m15_refinement_cases.jsonl`.

## Failure reasons

| Reason | Count | Percentage |
|---|---:|---:|
| `SESSION_WINDOW_EXPIRED` | 18 | 100.0% |

The cases did contain directional M15 zones after the H1 shift, but none of those zones was created inside the active session window. This is distinct from `NO_M15_CONFIRMING_STRUCTURE`: the source found directional M15 structures, but they were not eligible under the frozen session-time rule.

## Parity

| Classification | Count |
|---|---:|
| MATCH | 18 |
| SOURCE_PASS_EDGELAB_FAIL | 0 |
| SOURCE_FAIL_EDGELAB_PASS | 0 |
| TIMING_MISMATCH | 0 |
| STATE_MISMATCH | 0 |
| DATA_MISMATCH | 0 |

## Causality

`CAUSALITY = PASS`

All 18 cases satisfied the truncation invariant:

```text
decision(data up to T)
==
decision(full dataset clipped to closed bars at T)
```

No incomplete M15 bar, future FVG, future zone, future retest, midpoint backfill, or backfilled limit entry was used.

## Funnel interpretation

- TRIGGER: 18 H1 shifts admitted
- CONFIRMATION: 18 M15 refinement inputs, 0 passes, 18 failures
- OUTCOME: not evaluable

No target-capability or economic analysis was performed because no valid M15 geometry or entry existed.

## Final V2 state

- V2 rules changed: `NO`
- OOS opened: `NO`
- Holdout touched: `NO`
- Execution capability added: `NO`
- Status: `INSUFFICIENT_SAMPLE`
- Primary weak point: `CONFIRMATION`
- Bottleneck: `M15_REFINEMENT`

Any future V3 hypothesis must be a new strategy identity. No V3 rule was implemented.
