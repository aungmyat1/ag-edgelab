# GEN2 ASIAN LIQUIDITY DISPLACEMENT V1 — MULTI-YEAR DEV REPLAY

**EXPERIMENT_ID** `GEN2_ALD_V1_MULTIYEAR_DEV_R1` · **STATUS** `MULTIYEAR_DEV_INSUFFICIENT_SAMPLE` · **NEXT** `NEW_V2_HYPOTHESIS_DESIGN`

- STRATEGY_ID `ST_ASIAN_LIQUIDITY_DISPLACEMENT_V1` @ `1.0.0-research`
- STRATEGY_HASH `28c4f52f2ef6b54977e407e0c5ce93ef4f9b41a7bced37327a4844d392669a94` — reproduces EXPECTED_RULE_HASH (**RULES_CHANGED = NO**, DATASET_BINDING_CHANGED = YES)
- DATASET_AUTHORITY `HISTDATA_ASCII_M1_MULTIYEAR_R2`, role DEVELOPMENT, 63 symbol-years across 18 calendar years
- DEV_PARTITION_HASH `da5e7c58c1e297d7ac95fe583394909adca637dcf8c78a9a0e3bc14501994e3a`
- OOS_OPENED **NO** · HOLDOUT_TOUCHED **NO** · PARAMETER_OPTIMIZATION **NO** · BROKER_MUTATION **NO**

## 1. Verdict

**SAMPLE_CLASSIFICATION = `STRATEGY_STRUCTURAL_STARVATION`** (CASE_B, rule `decision_order[4]` of `MULTIYEAR_SAMPLE_CLASSIFICATION_V1`)

Pooled ENTRY_AVAILABLE_N = **35** against the preregistered eligibility floor of 100; no symbol x session cell reaches the 30-entry floor (viable cells: none).

## 2. Pooled funnel

| stage | INPUT_N | PASS_N | FAIL_N | PASS_% | % of opportunity |
|---|---:|---:|---:|---:|---:|
| T1_ASIAN_REFERENCE_VALID | 26814 | 12601 | 14213 | 46.994108 | 46.994108 |
| T2_DIRECTION_DECIDED | 12601 | 12577 | 24 | 99.809539 | 46.904602 |
| T3_DIRECTION_NON_NEUTRAL | 12577 | 1382 | 11195 | 10.988312 | 5.154024 |
| T4_ASIAN_SWEEP | 1382 | 669 | 713 | 48.408104 | 2.494965 |
| T5_CLOSE_BACK_INSIDE | 669 | 441 | 228 | 65.919283 | 1.644663 |
| C1_DISPLACEMENT | 441 | 294 | 147 | 66.666667 | 1.096442 |
| C2_MSS_BOS | 294 | 119 | 175 | 40.47619 | 0.443798 |
| C3_FRESH_FVG | 119 | 76 | 43 | 63.865546 | 0.283434 |
| C4_FVG_RETRACE_AVAILABLE | 76 | 51 | 25 | 67.105263 | 0.190199 |
| C5_GEOMETRY_VALID | 51 | 36 | 15 | 70.588235 | 0.134258 |
| C6_ENTRY_AVAILABLE | 36 | 35 | 1 | 97.222222 | 0.130529 |

1R-5R capability: **1R** 0.428571 · **2R** 0.285714 · **3R** 0.257143 · **4R** 0.057143 · **5R** 0.0

natural_target_median_R = 1.003804; conditional continuation {'P(2R|1R)': 0.666667, 'P(3R|2R)': 0.9, 'P(4R|3R)': 0.222222, 'P(5R|4R)': 0.0}

## 3. Attrition decomposition

Trigger failures (never collapsed into one bucket):

| mission reason | n | frozen vocabulary |
|---|---:|---|
| DIRECTION_SWEEP_MISMATCH | 0 | — |
| NEUTRAL_DIRECTION | 11195 | DIRECTION_NEUTRAL=11195 |
| NO_ASIAN_SWEEP | 713 | NO_ASIAN_SWEEP_ON_DIRECTION_SIDE=713 |
| NO_RECLAIM | 228 | NO_CLOSE_BACK_INSIDE=228 |
| OTHER_DEFINED_REASON | 14220 | ASIAN_REFERENCE_INSUFFICIENT_BARS=14196, ASIAN_RANGE_DEGENERATE=0, DIRECTION_UNDECIDABLE=24 |
| SESSION_EXPIRED | 17 | ENTRY_WINDOW_NO_BARS=17 |

Confirmation failures:

| mission reason | n | frozen vocabulary |
|---|---:|---|
| GEOMETRY_INVALID | 15 | GEOMETRY_RISK_NON_POSITIVE=0, GEOMETRY_TP1_NOT_BEYOND_ENTRY=15 |
| NO_DISPLACEMENT | 147 | NO_DISPLACEMENT_BODY_RATIO=147 |
| NO_FVG | 43 | NO_FRESH_FVG_AFTER_MSS=43 |
| NO_FVG_RETRACE | 25 | NO_CAUSAL_RETRACE_INTO_FVG=22, RETRACE_INVALIDATED_BY_STOP_FIRST=3 |
| NO_MSS_BOS | 175 | NO_MSS_BOS_AFTER_DISPLACEMENT=175 |
| TEMPORAL_INVALID | 1 | GEOMETRY_TEMPORAL_ORDER_INVALID=0, RIGHT_CENSORED_DATA_BOUNDARY=1 |

Reconciliation of mapped vs raw rejection counts: `True`

## 4. Year distribution (reported, never ranked)

| year | symbols | OPPORTUNITY_N | DIRECTIONAL_N | TRIGGER_N | CONFIRMATION_N | ENTRY_N | entries / 1000 candidates |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2000 | 3 | 432 | 0 | 0 | 0 | 0 | 0.0 |
| 2001 | 3 | 1326 | 0 | 0 | 0 | 0 | 0.0 |
| 2002 | 3 | 1320 | 4 | 0 | 0 | 0 | 0.0 |
| 2003 | 3 | 1322 | 14 | 4 | 0 | 0 | 0.0 |
| 2004 | 3 | 1332 | 44 | 13 | 0 | 0 | 0.0 |
| 2005 | 3 | 1320 | 24 | 9 | 0 | 0 | 0.0 |
| 2006 | 3 | 1320 | 22 | 7 | 1 | 0 | 0.0 |
| 2007 | 3 | 1326 | 8 | 4 | 0 | 0 | 0.0 |
| 2008 | 3 | 1332 | 44 | 14 | 1 | 1 | 0.750751 |
| 2009 | 4 | 1624 | 130 | 34 | 2 | 2 | 1.231527 |
| 2010 | 4 | 1760 | 137 | 52 | 8 | 6 | 3.409091 |
| 2011 | 4 | 1768 | 108 | 32 | 5 | 5 | 2.828054 |
| 2012 | 4 | 1776 | 143 | 45 | 3 | 2 | 1.126126 |
| 2013 | 4 | 1768 | 150 | 42 | 4 | 3 | 1.696833 |
| 2014 | 4 | 1776 | 131 | 52 | 6 | 6 | 3.378378 |
| 2015 | 4 | 1776 | 156 | 57 | 10 | 5 | 2.815315 |
| 2016 | 4 | 1768 | 116 | 34 | 5 | 2 | 1.131222 |
| 2017 | 4 | 1768 | 151 | 42 | 6 | 3 | 1.696833 |

## 5. Symbol x session cells (independent, nothing removed)

| cell | OPPORTUNITY_N | DIRECTIONAL_N | TRIGGER_N | CONFIRMATION_N | ENTRY_N | starved |
|---|---:|---:|---:|---:|---:|---|
| EURUSD|ASIAN_LONDON | 3830 | 188 | 79 | 3 | 2 | YES |
| EURUSD|LONDON_NEWYORK | 3830 | 171 | 43 | 5 | 3 | YES |
| GBPUSD|ASIAN_LONDON | 3828 | 146 | 61 | 12 | 6 | YES |
| GBPUSD|LONDON_NEWYORK | 3828 | 154 | 41 | 5 | 4 | YES |
| USDJPY|ASIAN_LONDON | 3830 | 185 | 50 | 1 | 1 | YES |
| USDJPY|LONDON_NEWYORK | 3830 | 194 | 45 | 8 | 5 | YES |
| XAUUSD|ASIAN_LONDON | 1919 | 170 | 52 | 9 | 7 | YES |
| XAUUSD|LONDON_NEWYORK | 1919 | 174 | 70 | 8 | 7 | YES |

SYMBOL_STARVATION = ['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD'] · SESSION_STARVATION = ['ASIAN_LONDON', 'LONDON_NEWYORK']

## 6. Narrow 2017 vs multi-year

| metric | 2017 DEV | multi-year | growth x |
|---|---:|---:|---:|
| CANDIDATE_N | 1768 | 26814 | 15.1663 |
| TRIGGER_PASS_N | 42 | 441 | 10.5 |
| CONFIRMATION_PASS_N | 6 | 51 | 8.5 |
| GEOMETRY_VALID_N | 3 | 36 | 12.0 |
| ENTRY_AVAILABLE_N | 3 | 35 | 11.6667 |
| symbol-years | 4 | 63 | 15.75 |

2017 entry yield 1.696833 per 1000 candidates; other years span [0.0, 3.409091]. **2017 representative: True**.

## 6b. Data coverage and the balanced panel

HistData coverage is not uniform: gold starts in 2009 and the 2000 archives start in May, so the four-symbol **balanced panel is 2009-2017** (36 symbol-years), declared in the data authority before any result.

- balanced-panel counts: {'CANDIDATE_N': 15784, 'DIRECTIONAL_N': 1222, 'TRIGGER_PASS_N': 390, 'CONFIRMATION_PASS_N': 49, 'ENTRY_AVAILABLE_N': 34}
- balanced-panel capability: {'1R': 0.411765, '2R': 0.264706, '3R': 0.235294, '4R': 0.058824, '5R': 0.0}
- entries per symbol-year: **0.944444**
- classification computed on the panel alone: `STRATEGY_STRUCTURAL_STARVATION` (same verdict as pooled)

At that yield the corpus would need **106 symbol-years** (~26.47 calendar years of four symbols) merely to reach the pooled eligibility floor, and 255 symbol-years (~63.53 calendar years) for every symbol x session cell to clear the 30-entry floor. HistData FX M1 begins in 2000 and gold in 2009; the DEV half of every year is already consumed by this experiment, so no further DEVELOPMENT evidence of this kind exists to collect.

## 7. Temporal diagnostics

- entry window = 12 M15 bars; median bars remaining after reclaim = 8
- sequential events still required after reclaim = 4
- window-bounded share of post-trigger attrition = 59.1133%; right-censored 1

## 8. Robustness and the Pre-OOS gate

ROBUSTNESS_RUN = **NO** (pooled entries 35 vs required 100)

| axis | state | provisional state if eligible |
|---|---|---|
| WALK_FORWARD | `NOT_RUN_INSUFFICIENT_SAMPLE` | `INSUFFICIENT_SAMPLE` |
| YEAR_STABILITY | `NOT_RUN_INSUFFICIENT_SAMPLE` | `INSUFFICIENT_SAMPLE` |
| SYMBOL_STABILITY | `NOT_RUN_INSUFFICIENT_SAMPLE` | `INSUFFICIENT_SAMPLE` |
| SESSION_STABILITY | `NOT_RUN_INSUFFICIENT_SAMPLE` | `INSUFFICIENT_SAMPLE` |
| REGIME_STABILITY | `NOT_RUN_INSUFFICIENT_SAMPLE` | `INSUFFICIENT_SAMPLE` |
| TAIL_DEPENDENCE | `NOT_RUN_INSUFFICIENT_SAMPLE` | `FAIL` |
| MEAN_MEDIAN_DIVERGENCE | `NOT_RUN_INSUFFICIENT_SAMPLE` | `PASS` |
| BOOTSTRAP | `NOT_RUN_INSUFFICIENT_SAMPLE` | `FAIL` |
| PARAMETER_NEIGHBORHOOD | `NOT_RUN_INSUFFICIENT_SAMPLE` | `NOT_RUN_INSUFFICIENT_SAMPLE` |
| INTRA_YEAR_SEGMENT_STABILITY | `NOT_RUN_INSUFFICIENT_SAMPLE` | `INSUFFICIENT_SAMPLE` |
| LEAVE_ONE_YEAR_OUT | `NOT_RUN_INSUFFICIENT_SAMPLE` | `FAIL` |
| LEAVE_ONE_SYMBOL_OUT | `NOT_RUN_INSUFFICIENT_SAMPLE` | `FAIL` |

**PRE_OOS_RESULT = `NOT_REACHED`** — failing axes [], unevaluable axes 15. FROZEN_CANDIDATE = NO.

## 9. Economics

ECONOMIC_EDGE = **NOT_ESTIMABLE**. Measured friction authority is still missing, so no spread, commission or slippage value exists anywhere in this bundle. Only structural R is reported.

## 10. Research integrity

- optimizer_runs = `0`
- trial_count = `0`
- hypotheses_evaluated = `1`
- threshold_mutations = `0`
- post_hoc_selection = `NONE`
- years_ranked_or_selected = `NONE`
- cells_removed = `NONE`
- EXCLUDED_SYMBOL_YEARS = `none`
- determinism: per-symbol-year double pass `BYTE_IDENTICAL` over 63 symbol-years; pooled ledger sha256 `412e680a8ef9a4e4d3985b460293f9af5c049764e1b719ba9d1ba7d6adbf4a5e`

