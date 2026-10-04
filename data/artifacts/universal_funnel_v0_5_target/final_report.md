# Universal Funnel V0.5 — Target Model Diagnostics

EXPERIMENT: TARGET_MODEL_DIAGNOSTICS_V1 @ 0.2.0-research · parent 09ddc4d0f90e (reproduced: YES) · STATUS: **TARGET_DIAGNOSTICS_COMPLETE**

## Natural objective vs fixed targets (pooled D01)

| level | natural >= level | realize when supported | fit: beyond natural |
|---|---|---|---|
| 2R | 0.020 | 0.344 | 0.977 |
| 3R | 0.006 | 0.211 | 0.993 |
| 4R | 0.001 | 0.000 | 0.999 |
| 5R | 0.001 | 0.000 | 0.999 |

Nearest-objective quantiles — D01: P10 0.03 / P25 0.09 / P50 0.23 / P75 0.52 / P90 0.98; T1: P50 0.21, P90 0.86

## Verdict

- PRIMARY_DIAGNOSIS: **TARGET_MODEL_MISMATCH**
- SECONDARY: ['SL_TARGET_GEOMETRY_INTERACTION']
- NEXT_RECOMMENDED_RESEARCH: **PREREGISTER_NATURAL_TARGET_POLICY**
- Symbol states: {'EURUSD': 'TARGET_MODEL_MISMATCH', 'GBPUSD': 'TARGET_MODEL_MISMATCH', 'USDJPY': 'TARGET_MODEL_MISMATCH', 'XAUUSD': 'TARGET_MODEL_MISMATCH'}
- SL/target interaction: YES

## Guards

TP unchanged · SL unchanged · no parameter search · no economics · no OOS · no holdout · no execution
