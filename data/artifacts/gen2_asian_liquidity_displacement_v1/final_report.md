# ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1 — GENERATION 2 DEV report

STATUS: **DEV_REJECTED** · PRE_OOS_RESULT: **NOT_REACHED** · FROZEN_CANDIDATE: **NO**

| field | value |
|---|---|
| strategy_id | `ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1` |
| strategy_version | `1.0.0-research` |
| strategy_hash | `28c4f52f2ef6b54977e407e0c5ce93ef4f9b41a7bced37327a4844d392669a94` |
| preregistration_hash | `6662c33f9b5b6d5b05bcabff889659ca522abe0a00d1e4dcce4dc89d9972f13b` |
| implementation_sha | `8b9ef4e11929de6f0782839e1a4378bc445002d5` |
| tree_sha | `e8eb9ba97cbb69c13607dba3a5d45743f3a31ed5` |
| dataset_role | `DEVELOPMENT` (2017-01-01T00:00:00+00:00 .. 2017-09-01T00:00:00+00:00) |
| dev_partition_hash | `50f0ca09d61ec14a10d12a1b8d7834a937d6361991d6c742279b79bb4b72f2ab` |
| symbols | EURUSD, GBPUSD, USDJPY, XAUUSD |
| sessions | ASIAN_LONDON, LONDON_NEWYORK, POOLED |
| OOS_OPENED / HOLDOUT_TOUCHED | NO / NO |
| execution added / broker mutation | NO / NO |
| friction | FRICTION_EDGE_VERIFICATION_READY = NO → ECONOMIC_METRICS = NOT_ESTIMABLE |

## 1. Funnel (pooled)

| stage | n | % of previous |
|---|---:|---:|
| CANDIDATE (symbol x day x session) | 1768 | 100.00% |
| TRIGGER_INPUT | 1768 | 100.00% |
| TRIGGER_PASS | 42 | 2.38% |
| CONFIRMATION_PASS | 6 | 14.29% |
| GEOMETRY_VALID | 3 | 50.00% |
| ENTRY_AVAILABLE | 3 | 100.00% |
| 1R | 0 | 0.00% |
| 2R | 0 | 0.00% |
| 3R | 0 | 0.00% |
| 4R | 0 | 0.00% |
| 5R | 0 | 0.00% |

### per symbol

| symbol | TRIGGER_PASS | CONFIRMATION_PASS | ENTRY_AVAILABLE |
|---|---:|---:|---:|
| EURUSD | 13 | 1 | 1 |
| GBPUSD | 6 | 2 | 0 |
| USDJPY | 14 | 2 | 1 |
| XAUUSD | 9 | 1 | 1 |

### per session

| session | TRIGGER_PASS | CONFIRMATION_PASS | ENTRY_AVAILABLE |
|---|---:|---:|---:|
| ASIAN_LONDON | 25 | 3 | 1 |
| LONDON_NEWYORK | 17 | 3 | 2 |

## 2. Confirmation chain (mission section 5 ordering)

| step | input | pass | pass % | dominant reason |
|---|---:|---:|---:|---|
| 1_SWEEP | 151 | 73 | 48.34% | NO_ASIAN_SWEEP_ON_DIRECTION_SIDE |
| 2_CLOSE_BACK_INSIDE | 73 | 42 | 57.53% | NO_CLOSE_BACK_INSIDE |
| 3_DISPLACEMENT | 42 | 28 | 66.67% | NO_DISPLACEMENT_BODY_RATIO |
| 4_MSS_BOS | 28 | 10 | 35.71% | NO_MSS_BOS_AFTER_DISPLACEMENT |
| 5_FRESH_FVG | 10 | 7 | 70.00% | NO_FRESH_FVG_AFTER_MSS |
| 6_FVG_RETRACE_AVAILABLE | 7 | 6 | 85.71% | NO_CAUSAL_RETRACE_INTO_FVG |

## 3. Target capability

| metric | value |
|---|---|
| 1R capability | 0.0 |
| 2R capability | 0.0 |
| 3R capability | 0.0 |
| 4R capability | 0.0 |
| 5R capability | 0.0 |
| median natural target R | 1.276923 |
| median MFE_R / MAE_R | 0.727273 / 1.097436 |
| continuation | {'P(2R|1R)': None, 'P(3R|2R)': None, 'P(4R|3R)': None, 'P(5R|4R)': None} |

Economic profitability is **not** claimed: no measured friction authority exists
(section 13), so only structural R is reported.

## 4. Trigger quality (opportunity basis, frozen observation policy)

| population | n | 1R | 3R | 5R |
|---|---:|---:|---:|---:|
| DIRECTION_NON_NEUTRAL | 151 | 0.562914 | 0.271523 | 0.198675 |
| TRIGGER_PASS | 42 | 0.595238 | 0.261905 | 0.214286 |

## 5. Temporal diagnostics

- median M15 bars left in the entry window after the reclaim bar: **8.0**
- sequential events still required after the reclaim bar: **4**
- window-bounded share of post-trigger attrition: **56.410256%**

## 6. Root cause

- PRIMARY_FUNNEL_WEAKNESS: **INSUFFICIENT_SAMPLE**
- SECONDARY_DIAGNOSES: ['TRIGGER_FUNNEL_WEAKNESS']

- `INSUFFICIENT_SAMPLE` (PREREGISTERED_DECISION_ORDER) — TRIGGER_INPUT=1768 (floor 200), ENTRY_AVAILABLE=3 (floor 30)
- `TRIGGER_FUNNEL_WEAKNESS` (UNIVERSAL_FUNNEL_ANALYZER) — T1_ASIAN_REFERENCE_VALID: 5R pass_reach_pct=19.87; T2_DIRECTION_DECIDED: 5R pass_reach_pct=19.87; T3_DIRECTION_NON_NEUTRAL: 5R pass_reach_pct=19.87; T4_ASIAN_SWEEP: 5R pass_reach_pct=16.44

### 6.1 Starvation attribution (which step destroyed the sample)

| step | input | output | survival | absolute loss |
|---|---:|---:|---:|---:|
| CANDIDATE_N -> T1_ASIAN_REFERENCE_VALID | 1768 | 1270 | 71.83% | 498 |
| T1_ASIAN_REFERENCE_VALID -> T2_DIRECTION_DECIDED | 1270 | 1270 | 100.00% | 0 |
| T2_DIRECTION_DECIDED -> T3_DIRECTION_NON_NEUTRAL | 1270 | 151 | 11.89% | 1119 |
| T3_DIRECTION_NON_NEUTRAL -> T4_ASIAN_SWEEP | 151 | 73 | 48.34% | 78 |
| T4_ASIAN_SWEEP -> T5_CLOSE_BACK_INSIDE | 73 | 42 | 57.53% | 31 |
| T5_CLOSE_BACK_INSIDE -> C1_DISPLACEMENT | 42 | 28 | 66.67% | 14 |
| C1_DISPLACEMENT -> C2_MSS_BOS | 28 | 10 | 35.71% | 18 |
| C2_MSS_BOS -> C3_FRESH_FVG | 10 | 7 | 70.00% | 3 |
| C3_FRESH_FVG -> C4_FVG_RETRACE_AVAILABLE | 7 | 6 | 85.71% | 1 |
| C4_FVG_RETRACE_AVAILABLE -> C5_GEOMETRY_VALID | 6 | 3 | 50.00% | 3 |
| C5_GEOMETRY_VALID -> C6_ENTRY_AVAILABLE | 3 | 3 | 100.00% | 0 |
| C6_ENTRY_AVAILABLE -> O1_1R | 3 | 0 | 0.00% | 3 |
| O1_1R -> O2_2R | 0 | 0 | - | 0 |
| O2_2R -> O3_3R | 0 | 0 | - | 0 |
| O3_3R -> O4_4R | 0 | 0 | - | 0 |
| O4_4R -> O5_5R | 0 | 0 | - | 0 |

Largest absolute attrition (excluding calendar structure): **T3_DIRECTION_NON_NEUTRAL** (1270 -> 151, survival 11.889764%, 1119 candidates lost).

498 rejects are ASIAN_REFERENCE_INSUFFICIENT_BARS, of which 496 fall on Saturday/Sunday (FX has no weekend session); this step is calendar structure, not a rule weakness

### 6.2 Universal Funnel Analyzer verdict (accepted system, frozen thresholds)

| label | scope | evidence |
|---|---|---|
| `INSUFFICIENT_SAMPLE` | C2_MSS_BOS | input_n=28 < 30 |
| `INSUFFICIENT_SAMPLE` | C3_FRESH_FVG | input_n=10 < 30 |
| `INSUFFICIENT_SAMPLE` | C4_FVG_RETRACE_AVAILABLE | input_n=7 < 30 |
| `INSUFFICIENT_SAMPLE` | C5_GEOMETRY_VALID | input_n=6 < 30 |
| `INSUFFICIENT_SAMPLE` | C6_ENTRY_AVAILABLE | input_n=3 < 30 |
| `INSUFFICIENT_SAMPLE` | O1_1R | input_n=3 < 30 |
| `INSUFFICIENT_SAMPLE` | O2_2R | input_n=0 < 30 |
| `INSUFFICIENT_SAMPLE` | O3_3R | input_n=0 < 30 |
| `INSUFFICIENT_SAMPLE` | O4_4R | input_n=0 < 30 |
| `INSUFFICIENT_SAMPLE` | O5_5R | input_n=0 < 30 |
| `POOR_TRIGGER_QUALITY` | T1_ASIAN_REFERENCE_VALID | 5R pass_reach_pct=19.87 |
| `POOR_TRIGGER_QUALITY` | T2_DIRECTION_DECIDED | 5R pass_reach_pct=19.87 |
| `POOR_TRIGGER_QUALITY` | T3_DIRECTION_NON_NEUTRAL | 5R pass_reach_pct=19.87 |
| `POOR_TRIGGER_QUALITY` | T4_ASIAN_SWEEP | 5R pass_reach_pct=16.44 |

mapped mission labels: INSUFFICIENT_SAMPLE, TRIGGER_FUNNEL_WEAKNESS

## 7. Robustness / Pre-OOS Robustness Gate V1

eligibility: pooled ENTRY_AVAILABLE = 3 (required 100) → eligible = False

| axis | state |
|---|---|
| WALK_FORWARD | NOT_RUN_INSUFFICIENT_SAMPLE |
| YEAR_STABILITY | NOT_RUN_INSUFFICIENT_SAMPLE |
| SYMBOL_STABILITY | NOT_RUN_INSUFFICIENT_SAMPLE |
| SESSION_STABILITY | NOT_RUN_INSUFFICIENT_SAMPLE |
| REGIME_STABILITY | NOT_RUN_INSUFFICIENT_SAMPLE |
| TAIL_DEPENDENCE | NOT_RUN_INSUFFICIENT_SAMPLE |
| MEAN_MEDIAN_DIVERGENCE | NOT_RUN_INSUFFICIENT_SAMPLE |
| BOOTSTRAP | NOT_RUN_INSUFFICIENT_SAMPLE |
| PARAMETER_NEIGHBORHOOD | NOT_RUN_INSUFFICIENT_SAMPLE |

PRE_OOS_RESULT = **NOT_REACHED** · failing axes: none · unevaluable: ['BOOTSTRAP', 'ENTRY_POPULATION', 'MEAN_MEDIAN_DIVERGENCE', 'PARAMETER_NEIGHBORHOOD', 'REGIME_STABILITY', 'SAMPLE_ELIGIBILITY', 'SESSION_STABILITY', 'STRUCTURAL_CAPABILITY_1R', 'STRUCTURAL_CAPABILITY_3R', 'SYMBOL_STABILITY', 'TAIL_DEPENDENCE', 'WALK_FORWARD', 'YEAR_STABILITY']

## 8. Freeze decision

FROZEN_CANDIDATE = **NO** — Pre-OOS Robustness Gate V1 did not pass: NOT_REACHED; failing axes=[]; unevaluable axes=['BOOTSTRAP', 'ENTRY_POPULATION', 'MEAN_MEDIAN_DIVERGENCE', 'PARAMETER_NEIGHBORHOOD', 'REGIME_STABILITY', 'SAMPLE_ELIGIBILITY', 'SESSION_STABILITY', 'STRUCTURAL_CAPABILITY_1R', 'STRUCTURAL_CAPABILITY_3R', 'SYMBOL_STABILITY', 'TAIL_DEPENDENCE', 'WALK_FORWARD', 'YEAR_STABILITY']

CANDIDATE_IDENTITY_SHA256 = `None`

## 9. Search policy compliance

optimizer runs = 0 · trials = 0 · hypotheses evaluated = 1 · verifier threshold mutations = 0 ·
post-hoc symbol/rule selection = NONE · session windows never widened · displacement threshold
0.70 frozen throughout.
