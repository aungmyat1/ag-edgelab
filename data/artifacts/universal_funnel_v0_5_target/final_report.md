# Universal Funnel V0.5 — Causal Target Model Diagnostics

EXPERIMENT: TARGET_MODEL_DIAGNOSTICS_V1 @ 0.3.0-research · parent 09ddc4d0f90e (reproduced: YES) · STATUS: **TARGET_DIAGNOSTICS_COMPLETE**

## Objective geometry (R)

| population | primary P25/P50/P75 | furthest P25/P50/P75 | first obj reach | P(2nd|1st) |
|---|---|---|---|---|
| D01 | 0.150/0.402/0.891 | 1.447/2.737/4.990 | 0.675 | 0.635 |
| T1 | 0.140/0.377/0.849 | 1.785/2.967/4.892 | 0.686 | 0.542 |

## The 5R questions (pooled D01)

- 5R beyond EVERY causal objective: 0.735
- >=5R causal objective exists: 0.249 (n=792)
- reached before SL when it exists: 0.061

## Verdict

- PRIMARY_DIAGNOSIS: **A_TARGET_MODEL_MISMATCH**
- SECONDARY: ['B_TARGET_CONTINUATION_WEAKNESS', 'D_PARTIAL_TARGET_PLUS_RUNNER_HYPOTHESIS', 'E_SL_TARGET_GEOMETRY_INTERACTION']
- NEXT_FUNNEL_TO_TEST: **NATURAL_TARGET_PLUS_RUNNER_EXPERIMENT**
- T1 effect: geometry NEUTRAL · delivery NEUTRAL · deep continuation DEGRADED · ['D_DAMAGES_DEEP_CONTINUATION']
- per-symbol: {'EURUSD': 'A_TARGET_MODEL_MISMATCH', 'GBPUSD': 'A_TARGET_MODEL_MISMATCH', 'USDJPY': 'A_TARGET_MODEL_MISMATCH', 'XAUUSD': 'A_TARGET_MODEL_MISMATCH'}
- SL/target interaction: YES

## Guards

TP unchanged · SL unchanged · no parameter search · no partial exits · no economics · no OOS · no holdout · no execution · no V0.6
