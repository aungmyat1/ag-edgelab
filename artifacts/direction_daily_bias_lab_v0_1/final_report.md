# EdgeLab Direction / Daily-Bias Lab V0.1

## Status

**BLOCKED — CONTRACT_INCOMPLETE / INSUFFICIENT_EVIDENCE**

The checkout at `af58e2f23e2bd331b220c92180760ca651fdc7ed` contains the generic EdgeLab foundation and a non-authoritative synthetic BTC fixture, but it does not contain the authorized Asian V1/V2 strategy identities, MTF Control Shift candidates, owner source documents, or the expected EURUSD/GBPUSD/USDJPY/XAUUSD DEVELOPMENT lineage. The fixture was not substituted, and no OOS or holdout data was opened.

## Scope completed

- Added deterministic closed-bar direction primitives: confirmed HH/HL/LH/LL, BOS, active H4 range, premium/discount, PDH/PDL, H1 phase, MA50/MA200, invalidation, target geometry, and fixed-target capability.
- Added a separate `FunnelDiagnosticReportV3` schema preserving DIRECTION, CONFIRMATION, TARGET, and ECONOMICS semantics.
- Added authority, contract, target, causality, and immutable-strategy audit artifacts.
- No strategy rule, Asian V2 target, existing MTF candidate, execution capability, or economics was changed or run.

## Required return

```text
IMPLEMENTATION_SHA = WORKTREE_ARTIFACT_GENERATION_AT_BASELINE_HEAD
TREE_SHA = 6de91f9685ea748228f762be2a69f3ff34b4de36
BRANCH = arena/01a1041d-ag-edgelab
BASE_TEST_COUNT = 174
FINAL_TEST_COUNT = 188
TESTS = PASS (188 passed; archived HEAD baseline 174 passed)
REPORT_SCHEMA = FunnelDiagnosticReportV3
DIRECTION_ENGINE_VERSION = DIRECTION_DAILY_BIAS_ENGINE_V0.1
SOURCE_FAMILIES = A: not located; B: not located; C: research hypothesis
DATASET_ROLE = DEVELOPMENT_ONLY
DATASET_LINEAGE = blocked; no authorized Asian DEV lineage

MD01_RESULT through MD12_RESULT = NOT_RUN_NO_AUTHORIZED_DATASET
BEST_STRUCTURAL_EVIDENCE = null
BEST_MA_EVIDENCE = null
MA_ADDS_VALUE_BEYOND_STRUCTURE = null
PREMIUM_DISCOUNT_ADDS_VALUE = null
INTERNAL_FLOW_ADDS_VALUE = null
LIQUIDITY_CONTEXT_ADDS_VALUE = null
ASIAN_V2_ALIGNED_N = 0
ASIAN_V2_COUNTER_N = 0
ASIAN_V2_NEUTRAL_N = 0
RANGE_PREEMPTED_SWEEP_N = 0
RANGE_PREEMPTED_TREND_N = 0
FIXED_5R_CAPABILITY = null
NATURAL_TARGET_MEDIAN_R = null
NATURAL_TARGET_P25_R = null
NATURAL_TARGET_P75_R = null
PRIMARY_DIAGNOSIS = CONTRACT_INCOMPLETE
SECONDARY_DIAGNOSES = INSUFFICIENT_EVIDENCE
NEXT_FUNNEL_TO_CHANGE = NONE
STRATEGY_RULES_CHANGED = NO
REALIZED_ECONOMICS_RUN = NO
OOS_OPENED = NO
HOLDOUT_TOUCHED = NO
EXECUTION_CAPABILITY_ADDED = NO
STATUS = BLOCKED
```

The complete machine-readable report is `final_report.json`.
