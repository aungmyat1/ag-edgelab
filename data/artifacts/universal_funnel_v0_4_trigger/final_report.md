# Universal Funnel V0.4 — Trigger Research (D01 vs T1 vs T2)

EXPERIMENT: MTF_DIRECTION_TRIGGER_V1 @ 0.1.0-research · parent 977f99c53b39 (reproduced: YES) · STATUS: **TRIGGER_RESEARCH_COMPLETE**

## Policies

| policy | directional N | separation (pp) | attrition vs D01 | entered | result |
|---|---|---|---|---|---|
| D01 | 9226 | 2.04 | — | 3183 | frozen baseline |
| T1 | 899 | 7.55 | 90.26 | 379 | TRIGGER_DIRECTION_IMPROVED_TARGET_NOT_IMPROVED |
| T2 | 4762 | -1.43 | 48.38 | 1409 | TRIGGER_HYPOTHESIS_NOT_SUPPORTED |

## Target capability (pooled)

| policy | 1R | 2R | 3R | 4R | 5R | natural P50 |
|---|---|---|---|---|---|---|
| D01 | 0.4926 | 0.3032 | 0.2001 | 0.1376 | 0.0952 | 2.34 |
| T1 | 0.5330 | 0.3509 | 0.2058 | 0.1293 | 0.0765 | 2.63 |
| T2 | 0.4826 | 0.3052 | 0.1973 | 0.1263 | 0.0880 | 1.25 |

## Verdict

- Best policy: **T1** (type B)
- PRIMARY_DIAGNOSIS: **TRIGGER_DIRECTION_IMPROVED_TARGET_NOT_IMPROVED**
- NEXT_FUNNEL_TO_TEST: **TARGET**
- Propagates downstream: NO

## Guards

strategy rules changed: NO · new strategy: NO · economics: NO · OOS: NO · holdout: NO · execution: NO · Asian V2 identity: INSUFFICIENT_EVIDENCE
