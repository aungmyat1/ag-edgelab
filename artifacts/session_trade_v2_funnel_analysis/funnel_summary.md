# SESSION_TRADE_V2 @ 2.0.0 — Strategy Funnel Analysis

`STV2_STRATEGY_FUNNEL_ANALYZER_V1` — **diagnostic research only**.

This report implements **Funnel B — Strategy Funnel Analyzer** (`CONTEXT → LOCATION → TRIGGER → GEOMETRY → EXECUTION → OUTCOME`), which is a *trade-rule diagnostic*. It is **not** the Verification Lifecycle Funnel (`CONTRACT → DATA_QUALITY → DEV_SCREEN → FREEZE → OOS_VERIFICATION → WALK_FORWARD → REGIME/STABILITY → EDGE_VERIFIED`) that the existing economic-matrix campaign belongs to. The two funnels are kept strictly separate; no lifecycle stage was repurposed.

## 0. Authority and scope

| Key | Value |
|---|---|
| `demo_authorized` | `false` |
| `live_authorized` | `false` |
| `allow_order_send` | `false` |
| `HOLDOUT_TOUCHED` | `false` |
| Frozen rules modified | `none` |
| Parameters optimized | `none` |
| Production scanner changed | `no` |
| Promotion decision made | `no` |

## 1. Identity and provenance

| Key | Value |
|---|---|
| Strategy source repo | `aungmyat1/AG-profit-trading-assit` |
| Source PR | `#33` |
| Source branch | `feat/session-trade-v2-unified` |
| `SOURCE_STRATEGY_SHA` | `e1ffe9f1e5ccfb9a336f1b4ae4289d41901ec5d2` |
| `CANONICAL_CANDIDATE_ID` | `SESSION_TRADE_V2_v2.0.0_e1ffe9f1e5cc` |
| EdgeLab campaign PR | `#10` |
| Campaign branch | `arena/01a100ce-ag-edgelab` |
| Campaign head at handoff | `d6df82edf2d65d0a1feb28ae8500199ddbbede25` |
| DEV partition | `2017-01-01T00:00:00+00:00` → `2017-09-01T00:00:00+00:00` |
| Sealed holdout | `2017-12-01` → `2018-01-01` (never opened) |

### Identity model (outcome-collision fix)

The generic funnel analytics indexed outcomes by `record.candidate_id`. Every STV2 observation shares one candidate id, so that key collapses the whole dataset onto a single outcome. Three identity concepts are now distinct:

| Concept | Meaning | Count |
|---|---|---|
| `candidate_id` | `SESSION_TRADE_V2_v2.0.0_e1ffe9f1e5cc` (strategy candidate) | 1 |
| `segment_id` | `SESSION_TRADE_V2\|SYMBOL\|SESSION\|BRANCH` | 24 |
| `analysis_unit_id` | sha256 of (candidate_id, strategy_id, strategy_version, symbol, session, branch, trading_date, event_identity, dataset_sha256) | 5808 |

`EXPECTED_SEGMENTS = 24`; `SEGMENTS = 24`; `IDENTITY_COLLISIONS = 0`.

`EXPECTED_ANALYSIS_UNITS != 24`. The analysis-unit count is data-driven: `5808` = 242 evaluable trading dates × 4 symbols × 2 sessions × 3 branches.

### Dataset identity (frozen, reused — not re-downloaded)

| Symbol | Source artifact | sha256 | M15 bars |
|---|---|---|---|
| EURUSD | `HISTDATA_COM_ASCII_EURUSD_M1_2017.zip` | `0dcd66dc67d7af4716404a5315d376ee1e7eaebe292afbda3c1003d2dfa16f57` | 24793 |
| GBPUSD | `HISTDATA_COM_ASCII_GBPUSD_M1_2017.zip` | `e5ba3800e37fae0e326dbaa234952ca04e8f378c08b036530a2811206110c10b` | 24757 |
| USDJPY | `HISTDATA_COM_ASCII_USDJPY_M1_2017.zip` | `477a1f515586f06d67cb75b3662260160e1e29e63c51804a30a5e7d69b09df5f` | 24731 |
| XAUUSD | `HISTDATA_COM_ASCII_XAUUSD_M1_2017.zip` | `a39c1ccaaeb022c83309685107c9e619c2bcff8b2fd94fbd7405a721a4fe70ff` | 23500 |

All four hashes are byte-identical to the frozen campaign's `dataset_quality_reports.json`, and re-running the frozen DEV campaign reproduced `dev_result.json` exactly (cells, aggregates, session records, partition and friction authority all match). Timezone normalization, M1→M15 aggregation, session completeness, same-bar ambiguity policy, fill model, friction model and partition boundaries are all reused unchanged.

## 2. Metric semantics (mandatory reading)

Two metric classes are reported, and they are never mixed:

**A. Retention metrics** (`stage_input_count`, `stage_retained_count`, `stage_retained_pct`) — always valid at every stage.

**B. Conditional downstream economic metrics** (`conditional_downstream_*`) — *Among observations that reached this stage and eventually produced a CLOSED trade under unchanged downstream rules, what was the realized result?*

The following are explicitly **not** done anywhere in this analyzer:

- rejected / unfilled / expired observations are **never** imputed as `0R`;
- no hypothetical outcome is fabricated for a signal that never filled;
- `DATA_INVALID` observations are counted separately and never become losses;
- `OPEN_AT_END` fills are censored, never merged into closed-trade economics;
- undefined metrics are `null`, never `0`;
- `PF = ∞` is stored as `null` plus an explicit `*_pf_status = "INFINITE_NO_LOSING_TRADES"` (never a sentinel such as `999`); the Markdown rendering shows `∞`.

### A structural property of the conditional-cohort definition

Under the mandated (non-counterfactual) definition, the conditional cohort is *identical at every stage*: a trade can only close if it survived **all** five stages, so the set of closed trades retained at CONTEXT equals the set retained at EXECUTION. Consequently `conditional_net_expectancy_shift_r` is **0.0 by construction at every transition**, and this report says so rather than manufacturing a stage-to-stage economic decay curve. Any non-zero stage-wise "expectancy decay" would require assigning realized results to observations that were rejected later — exactly the counterfactual invention this mission forbids. The one economically real degradation that *is* measurable on executed trades is **gross → net friction decay**, reported in §8.

### R-unit and target accounting

One risk unit `R` is the frozen quarter-reference-range stop distance `r0 = 0.25 * (reference_high - reference_low)`, measured from the actual fill price. Branch A and branch B scale out: **75% of the position at +4R, then the stop moves to entry, and the remaining 25% runs to +5R**. A full winner is therefore `0.75 * 4R + 0.25 * 5R = ` **4.25R gross**, and it is reported as 4.25R throughout this document — it is *not* a "5R" result. If the runner is stopped at breakeven after the first target, the trade books `0.75 * 4R = 3.00R` gross. Net R is the same quantity after the frozen friction model. Branch C is replayed under the diagnostic `C_FIXED_EXIT_PROXY` exit because the frozen spec's "confirmed M15 swing" trail is not deterministic.

## 3. Full 24-segment funnel matrix

`FILTER_STAGE_ROWS = 120` (`EXPECTED_FILTER_STAGE_ROWS = 120`). No structurally impossible stage rows exist for STV2; all five filtering stages are reachable for every branch.

| Branch | Symbol | Session | Stage | Input | Retained | Retained % | Closed | Win % | Cond Net Exp R | Net PF | Exp Shift | Friction R |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | EURUSD | AL | CONTEXT | 242 | 171 | 70.66 | 68 | 16.18 | -0.3650 | 0.635 | — | 13.425 |
| A | EURUSD | AL | LOCATION | 171 | 160 | 93.57 | 68 | 16.18 | -0.3650 | 0.635 | 0.0000 | 13.425 |
| A | EURUSD | AL | TRIGGER | 160 | 128 | 80.00 | 68 | 16.18 | -0.3650 | 0.635 | 0.0000 | 13.425 |
| A | EURUSD | AL | GEOMETRY | 128 | 68 | 53.12 | 68 | 16.18 | -0.3650 | 0.635 | 0.0000 | 13.425 |
| A | EURUSD | AL | EXECUTION | 68 | 68 | 100.00 | 68 | 16.18 | -0.3650 | 0.635 | 0.0000 | 13.425 |
| A | EURUSD | LN | CONTEXT | 242 | 173 | 71.49 | 72 | 25.00 | 0.0867 | 1.103 | — | 9.280 |
| A | EURUSD | LN | LOCATION | 173 | 135 | 78.03 | 72 | 25.00 | 0.0867 | 1.103 | 0.0000 | 9.280 |
| A | EURUSD | LN | TRIGGER | 135 | 105 | 77.78 | 72 | 25.00 | 0.0867 | 1.103 | 0.0000 | 9.280 |
| A | EURUSD | LN | GEOMETRY | 105 | 72 | 68.57 | 72 | 25.00 | 0.0867 | 1.103 | 0.0000 | 9.280 |
| A | EURUSD | LN | EXECUTION | 72 | 72 | 100.00 | 72 | 25.00 | 0.0867 | 1.103 | 0.0000 | 9.280 |
| A | GBPUSD | AL | CONTEXT | 242 | 162 | 66.94 | 62 | 16.13 | -0.3950 | 0.597 | — | 10.404 |
| A | GBPUSD | AL | LOCATION | 162 | 152 | 93.83 | 62 | 16.13 | -0.3950 | 0.597 | 0.0000 | 10.404 |
| A | GBPUSD | AL | TRIGGER | 152 | 123 | 80.92 | 62 | 16.13 | -0.3950 | 0.597 | 0.0000 | 10.404 |
| A | GBPUSD | AL | GEOMETRY | 123 | 62 | 50.41 | 62 | 16.13 | -0.3950 | 0.597 | 0.0000 | 10.404 |
| A | GBPUSD | AL | EXECUTION | 62 | 62 | 100.00 | 62 | 16.13 | -0.3950 | 0.597 | 0.0000 | 10.404 |
| A | GBPUSD | LN | CONTEXT | 242 | 173 | 71.49 | 61 | 22.95 | 0.0042 | 1.005 | — | 6.197 |
| A | GBPUSD | LN | LOCATION | 173 | 118 | 68.21 | 61 | 22.95 | 0.0042 | 1.005 | 0.0000 | 6.197 |
| A | GBPUSD | LN | TRIGGER | 118 | 90 | 76.27 | 61 | 22.95 | 0.0042 | 1.005 | 0.0000 | 6.197 |
| A | GBPUSD | LN | GEOMETRY | 90 | 61 | 67.78 | 61 | 22.95 | 0.0042 | 1.005 | 0.0000 | 6.197 |
| A | GBPUSD | LN | EXECUTION | 61 | 61 | 100.00 | 61 | 22.95 | 0.0042 | 1.005 | 0.0000 | 6.197 |
| A | USDJPY | AL | CONTEXT | 242 | 171 | 70.66 | 80 | 15.00 | -0.4188 | 0.570 | — | 11.375 |
| A | USDJPY | AL | LOCATION | 171 | 128 | 74.85 | 80 | 15.00 | -0.4188 | 0.570 | 0.0000 | 11.375 |
| A | USDJPY | AL | TRIGGER | 128 | 102 | 79.69 | 80 | 15.00 | -0.4188 | 0.570 | 0.0000 | 11.375 |
| A | USDJPY | AL | GEOMETRY | 102 | 80 | 78.43 | 80 | 15.00 | -0.4188 | 0.570 | 0.0000 | 11.375 |
| A | USDJPY | AL | EXECUTION | 80 | 80 | 100.00 | 80 | 15.00 | -0.4188 | 0.570 | 0.0000 | 11.375 |
| A | USDJPY | LN | CONTEXT | 242 | 173 | 71.49 | 87 | 25.29 | 0.1081 | 1.126 | — | 13.010 |
| A | USDJPY | LN | LOCATION | 173 | 146 | 84.39 | 87 | 25.29 | 0.1081 | 1.126 | 0.0000 | 13.010 |
| A | USDJPY | LN | TRIGGER | 146 | 120 | 82.19 | 87 | 25.29 | 0.1081 | 1.126 | 0.0000 | 13.010 |
| A | USDJPY | LN | GEOMETRY | 120 | 87 | 72.50 | 87 | 25.29 | 0.1081 | 1.126 | 0.0000 | 13.010 |
| A | USDJPY | LN | EXECUTION | 87 | 87 | 100.00 | 87 | 25.29 | 0.1081 | 1.126 | 0.0000 | 13.010 |
| A | XAUUSD | AL | CONTEXT | 242 | 106 | 43.80 | 50 | 20.00 | -0.3890 | 0.654 | — | 19.666 |
| A | XAUUSD | AL | LOCATION | 106 | 76 | 71.70 | 50 | 20.00 | -0.3890 | 0.654 | 0.0000 | 19.666 |
| A | XAUUSD | AL | TRIGGER | 76 | 62 | 81.58 | 50 | 20.00 | -0.3890 | 0.654 | 0.0000 | 19.666 |
| A | XAUUSD | AL | GEOMETRY | 62 | 50 | 80.65 | 50 | 20.00 | -0.3890 | 0.654 | 0.0000 | 19.666 |
| A | XAUUSD | AL | EXECUTION | 50 | 50 | 100.00 | 50 | 20.00 | -0.3890 | 0.654 | 0.0000 | 19.666 |
| A | XAUUSD | LN | CONTEXT | 242 | 172 | 71.07 | 62 | 30.65 | 0.0828 | 1.083 | — | 26.471 |
| A | XAUUSD | LN | LOCATION | 172 | 152 | 88.37 | 62 | 30.65 | 0.0828 | 1.083 | 0.0000 | 26.471 |
| A | XAUUSD | LN | TRIGGER | 152 | 116 | 76.32 | 62 | 30.65 | 0.0828 | 1.083 | 0.0000 | 26.471 |
| A | XAUUSD | LN | GEOMETRY | 116 | 62 | 53.45 | 62 | 30.65 | 0.0828 | 1.083 | 0.0000 | 26.471 |
| A | XAUUSD | LN | EXECUTION | 62 | 62 | 100.00 | 62 | 30.65 | 0.0828 | 1.083 | 0.0000 | 26.471 |
| B | EURUSD | AL | CONTEXT | 242 | 171 | 70.66 | 0 | — | — | — | — | — |
| B | EURUSD | AL | LOCATION | 171 | 160 | 93.57 | 0 | — | — | — | — | — |
| B | EURUSD | AL | TRIGGER | 160 | 0 | 0.00 | 0 | — | — | — | — | — |
| B | EURUSD | AL | GEOMETRY | 0 | 0 | — | 0 | — | — | — | — | — |
| B | EURUSD | AL | EXECUTION | 0 | 0 | — | 0 | — | — | — | — | — |
| B | EURUSD | LN | CONTEXT | 242 | 173 | 71.49 | 0 | — | — | — | — | — |
| B | EURUSD | LN | LOCATION | 173 | 135 | 78.03 | 0 | — | — | — | — | — |
| B | EURUSD | LN | TRIGGER | 135 | 0 | 0.00 | 0 | — | — | — | — | — |
| B | EURUSD | LN | GEOMETRY | 0 | 0 | — | 0 | — | — | — | — | — |
| B | EURUSD | LN | EXECUTION | 0 | 0 | — | 0 | — | — | — | — | — |
| B | GBPUSD | AL | CONTEXT | 242 | 162 | 66.94 | 2 | 0.00 | -1.1781 | 0.000 | — | 0.356 |
| B | GBPUSD | AL | LOCATION | 162 | 154 | 95.06 | 2 | 0.00 | -1.1781 | 0.000 | 0.0000 | 0.356 |
| B | GBPUSD | AL | TRIGGER | 154 | 4 | 2.60 | 2 | 0.00 | -1.1781 | 0.000 | 0.0000 | 0.356 |
| B | GBPUSD | AL | GEOMETRY | 4 | 4 | 100.00 | 2 | 0.00 | -1.1781 | 0.000 | 0.0000 | 0.356 |
| B | GBPUSD | AL | EXECUTION | 4 | 2 | 50.00 | 2 | 0.00 | -1.1781 | 0.000 | 0.0000 | 0.356 |
| B | GBPUSD | LN | CONTEXT | 242 | 173 | 71.49 | 0 | — | — | — | — | — |
| B | GBPUSD | LN | LOCATION | 173 | 118 | 68.21 | 0 | — | — | — | — | — |
| B | GBPUSD | LN | TRIGGER | 118 | 0 | 0.00 | 0 | — | — | — | — | — |
| B | GBPUSD | LN | GEOMETRY | 0 | 0 | — | 0 | — | — | — | — | — |
| B | GBPUSD | LN | EXECUTION | 0 | 0 | — | 0 | — | — | — | — | — |
| B | USDJPY | AL | CONTEXT | 242 | 171 | 70.66 | 0 | — | — | — | — | — |
| B | USDJPY | AL | LOCATION | 171 | 128 | 74.85 | 0 | — | — | — | — | — |
| B | USDJPY | AL | TRIGGER | 128 | 0 | 0.00 | 0 | — | — | — | — | — |
| B | USDJPY | AL | GEOMETRY | 0 | 0 | — | 0 | — | — | — | — | — |
| B | USDJPY | AL | EXECUTION | 0 | 0 | — | 0 | — | — | — | — | — |
| B | USDJPY | LN | CONTEXT | 242 | 173 | 71.49 | 0 | — | — | — | — | — |
| B | USDJPY | LN | LOCATION | 173 | 146 | 84.39 | 0 | — | — | — | — | — |
| B | USDJPY | LN | TRIGGER | 146 | 0 | 0.00 | 0 | — | — | — | — | — |
| B | USDJPY | LN | GEOMETRY | 0 | 0 | — | 0 | — | — | — | — | — |
| B | USDJPY | LN | EXECUTION | 0 | 0 | — | 0 | — | — | — | — | — |
| B | XAUUSD | AL | CONTEXT | 242 | 106 | 43.80 | 1 | 0.00 | -1.2389 | 0.000 | — | 0.239 |
| B | XAUUSD | AL | LOCATION | 106 | 78 | 73.58 | 1 | 0.00 | -1.2389 | 0.000 | 0.0000 | 0.239 |
| B | XAUUSD | AL | TRIGGER | 78 | 3 | 3.85 | 1 | 0.00 | -1.2389 | 0.000 | 0.0000 | 0.239 |
| B | XAUUSD | AL | GEOMETRY | 3 | 3 | 100.00 | 1 | 0.00 | -1.2389 | 0.000 | 0.0000 | 0.239 |
| B | XAUUSD | AL | EXECUTION | 3 | 1 | 33.33 | 1 | 0.00 | -1.2389 | 0.000 | 0.0000 | 0.239 |
| B | XAUUSD | LN | CONTEXT | 242 | 172 | 71.07 | 0 | — | — | — | — | — |
| B | XAUUSD | LN | LOCATION | 172 | 152 | 88.37 | 0 | — | — | — | — | — |
| B | XAUUSD | LN | TRIGGER | 152 | 0 | 0.00 | 0 | — | — | — | — | — |
| B | XAUUSD | LN | GEOMETRY | 0 | 0 | — | 0 | — | — | — | — | — |
| B | XAUUSD | LN | EXECUTION | 0 | 0 | — | 0 | — | — | — | — | — |
| C | EURUSD | AL | CONTEXT | 242 | 171 | 70.66 | 0 | — | — | — | — | — |
| C | EURUSD | AL | LOCATION | 171 | 160 | 93.57 | 0 | — | — | — | — | — |
| C | EURUSD | AL | TRIGGER | 160 | 30 | 18.75 | 0 | — | — | — | — | — |
| C | EURUSD | AL | GEOMETRY | 30 | 30 | 100.00 | 0 | — | — | — | — | — |
| C | EURUSD | AL | EXECUTION | 30 | 0 | 0.00 | 0 | — | — | — | — | — |
| C | EURUSD | LN | CONTEXT | 242 | 173 | 71.49 | 0 | — | — | — | — | — |
| C | EURUSD | LN | LOCATION | 173 | 135 | 78.03 | 0 | — | — | — | — | — |
| C | EURUSD | LN | TRIGGER | 135 | 24 | 17.78 | 0 | — | — | — | — | — |
| C | EURUSD | LN | GEOMETRY | 24 | 24 | 100.00 | 0 | — | — | — | — | — |
| C | EURUSD | LN | EXECUTION | 24 | 0 | 0.00 | 0 | — | — | — | — | — |
| C | GBPUSD | AL | CONTEXT | 242 | 162 | 66.94 | 0 | — | — | — | — | — |
| C | GBPUSD | AL | LOCATION | 162 | 152 | 93.83 | 0 | — | — | — | — | — |
| C | GBPUSD | AL | TRIGGER | 152 | 23 | 15.13 | 0 | — | — | — | — | — |
| C | GBPUSD | AL | GEOMETRY | 23 | 23 | 100.00 | 0 | — | — | — | — | — |
| C | GBPUSD | AL | EXECUTION | 23 | 0 | 0.00 | 0 | — | — | — | — | — |
| C | GBPUSD | LN | CONTEXT | 242 | 173 | 71.49 | 1 | 100.00 | 4.0515 | ∞ | — | 0.198 |
| C | GBPUSD | LN | LOCATION | 173 | 118 | 68.21 | 1 | 100.00 | 4.0515 | ∞ | 0.0000 | 0.198 |
| C | GBPUSD | LN | TRIGGER | 118 | 27 | 22.88 | 1 | 100.00 | 4.0515 | ∞ | 0.0000 | 0.198 |
| C | GBPUSD | LN | GEOMETRY | 27 | 27 | 100.00 | 1 | 100.00 | 4.0515 | ∞ | 0.0000 | 0.198 |
| C | GBPUSD | LN | EXECUTION | 27 | 1 | 3.70 | 1 | 100.00 | 4.0515 | ∞ | 0.0000 | 0.198 |
| C | USDJPY | AL | CONTEXT | 242 | 171 | 70.66 | 0 | — | — | — | — | — |
| C | USDJPY | AL | LOCATION | 171 | 128 | 74.85 | 0 | — | — | — | — | — |
| C | USDJPY | AL | TRIGGER | 128 | 25 | 19.53 | 0 | — | — | — | — | — |
| C | USDJPY | AL | GEOMETRY | 25 | 25 | 100.00 | 0 | — | — | — | — | — |
| C | USDJPY | AL | EXECUTION | 25 | 0 | 0.00 | 0 | — | — | — | — | — |
| C | USDJPY | LN | CONTEXT | 242 | 173 | 71.49 | 0 | — | — | — | — | — |
| C | USDJPY | LN | LOCATION | 173 | 146 | 84.39 | 0 | — | — | — | — | — |
| C | USDJPY | LN | TRIGGER | 146 | 23 | 15.75 | 0 | — | — | — | — | — |
| C | USDJPY | LN | GEOMETRY | 23 | 23 | 100.00 | 0 | — | — | — | — | — |
| C | USDJPY | LN | EXECUTION | 23 | 0 | 0.00 | 0 | — | — | — | — | — |
| C | XAUUSD | AL | CONTEXT | 242 | 106 | 43.80 | 0 | — | — | — | — | — |
| C | XAUUSD | AL | LOCATION | 106 | 76 | 71.70 | 0 | — | — | — | — | — |
| C | XAUUSD | AL | TRIGGER | 76 | 12 | 15.79 | 0 | — | — | — | — | — |
| C | XAUUSD | AL | GEOMETRY | 12 | 12 | 100.00 | 0 | — | — | — | — | — |
| C | XAUUSD | AL | EXECUTION | 12 | 0 | 0.00 | 0 | — | — | — | — | — |
| C | XAUUSD | LN | CONTEXT | 242 | 172 | 71.07 | 0 | — | — | — | — | — |
| C | XAUUSD | LN | LOCATION | 172 | 152 | 88.37 | 0 | — | — | — | — | — |
| C | XAUUSD | LN | TRIGGER | 152 | 32 | 21.05 | 0 | — | — | — | — | — |
| C | XAUUSD | LN | GEOMETRY | 32 | 32 | 100.00 | 0 | — | — | — | — | — |
| C | XAUUSD | LN | EXECUTION | 32 | 0 | 0.00 | 0 | — | — | — | — | — |

_Session codes: `AL` = ASIAN_LONDON, `LN` = LONDON_NEWYORK._

## 4. Branch summaries

| Branch | Raw CONTEXT N | CONTEXT | LOCATION | TRIGGER | GEOMETRY | EXECUTION (fills) | CLOSED | Cond Gross Exp R | Cond Net Exp R | Win % | Net PF | Friction R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_SWEEP_REENTRY | 1936 | 1301 | 1067 | 846 | 542 | 542 | 542 | 0.0527 | -0.1499 | 21.40 | 0.841 | 109.829 |
| B_RANGE_REJECTION | 1936 | 1301 | 1071 | 7 | 7 | 3 | 3 | -1.0000 | -1.1983 | 0.00 | 0.000 | 0.595 |
| C_TREND_EXPANSION | 1936 | 1301 | 1067 | 196 | 196 | 1 | 1 | 4.2500 | 4.0515 | 100.00 | ∞ | 0.198 |

## 5. Symbol summaries

| Symbol | Raw CONTEXT N | CONTEXT | LOCATION | TRIGGER | GEOMETRY | EXECUTION (fills) | CLOSED | Cond Gross Exp R | Cond Net Exp R | Win % | Net PF | Friction R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EURUSD | 1452 | 1032 | 885 | 287 | 194 | 140 | 140 | 0.0295 | -0.1327 | 20.71 | 0.856 | 22.705 |
| GBPUSD | 1452 | 1005 | 812 | 267 | 177 | 126 | 126 | -0.0428 | -0.1789 | 19.84 | 0.803 | 17.156 |
| USDJPY | 1452 | 1032 | 822 | 270 | 215 | 167 | 167 | 0.0017 | -0.1443 | 20.36 | 0.842 | 24.384 |
| XAUUSD | 1452 | 834 | 686 | 225 | 159 | 113 | 113 | 0.2728 | -0.1377 | 25.66 | 0.869 | 46.376 |

## 6. Session summaries

| Session | Raw CONTEXT N | CONTEXT | LOCATION | TRIGGER | GEOMETRY | EXECUTION (fills) | CLOSED | Cond Gross Exp R | Cond Net Exp R | Win % | Net PF | Friction R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ASIAN_LONDON | 2904 | 1830 | 1552 | 512 | 357 | 263 | 263 | -0.1916 | -0.4025 | 16.35 | 0.603 | 55.466 |
| LONDON_NEWYORK | 2904 | 2073 | 1653 | 537 | 388 | 283 | 283 | 0.2835 | 0.0886 | 26.15 | 1.101 | 55.156 |

## 7. Attrition analysis

### 7.1 CONTEXT attrition (data validity, not strategy rejection)

| Metric | Value |
|---|---|
| Session observations (per branch) | 1936 |
| CONTEXT valid | 1301 |
| `DATA_INVALID` | 635 (32.80 %) |
| … zero reference bars (non-trading calendar day) | 551 |
| … partial reference window (real data gap) | 84 |

### 7.2 Per-segment stage-to-stage attrition

| Branch | Symbol | Session | Transition | Input | Retained | Lost | Attrition % | Dominant rejection reason |
|---|---|---|---|---:|---:|---:|---:|---|
| A | EURUSD | AL | CONTEXT→LOCATION | 171 | 160 | 11 | 6.43 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (11) |
| A | EURUSD | AL | LOCATION→TRIGGER | 160 | 128 | 32 | 20.00 | `TRIGGER_RULE_NOT_MET` (32) |
| A | EURUSD | AL | TRIGGER→GEOMETRY | 128 | 68 | 60 | 46.88 | `SWEEP_STOP_DOES_NOT_PROTECT_EXTREME` (60) |
| A | EURUSD | AL | GEOMETRY→EXECUTION | 68 | 68 | 0 | 0.00 | — |
| A | EURUSD | LN | CONTEXT→LOCATION | 173 | 135 | 38 | 21.97 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (38) |
| A | EURUSD | LN | LOCATION→TRIGGER | 135 | 105 | 30 | 22.22 | `TRIGGER_RULE_NOT_MET` (28) |
| A | EURUSD | LN | TRIGGER→GEOMETRY | 105 | 72 | 33 | 31.43 | `SWEEP_STOP_DOES_NOT_PROTECT_EXTREME` (33) |
| A | EURUSD | LN | GEOMETRY→EXECUTION | 72 | 72 | 0 | 0.00 | — |
| A | GBPUSD | AL | CONTEXT→LOCATION | 162 | 152 | 10 | 6.17 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (10) |
| A | GBPUSD | AL | LOCATION→TRIGGER | 152 | 123 | 29 | 19.08 | `TRIGGER_RULE_NOT_MET` (28) |
| A | GBPUSD | AL | TRIGGER→GEOMETRY | 123 | 62 | 61 | 49.59 | `SWEEP_STOP_DOES_NOT_PROTECT_EXTREME` (61) |
| A | GBPUSD | AL | GEOMETRY→EXECUTION | 62 | 62 | 0 | 0.00 | — |
| A | GBPUSD | LN | CONTEXT→LOCATION | 173 | 118 | 55 | 31.79 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (55) |
| A | GBPUSD | LN | LOCATION→TRIGGER | 118 | 90 | 28 | 23.73 | `TRIGGER_RULE_NOT_MET` (28) |
| A | GBPUSD | LN | TRIGGER→GEOMETRY | 90 | 61 | 29 | 32.22 | `SWEEP_STOP_DOES_NOT_PROTECT_EXTREME` (29) |
| A | GBPUSD | LN | GEOMETRY→EXECUTION | 61 | 61 | 0 | 0.00 | — |
| A | USDJPY | AL | CONTEXT→LOCATION | 171 | 128 | 43 | 25.15 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (43) |
| A | USDJPY | AL | LOCATION→TRIGGER | 128 | 102 | 26 | 20.31 | `TRIGGER_RULE_NOT_MET` (26) |
| A | USDJPY | AL | TRIGGER→GEOMETRY | 102 | 80 | 22 | 21.57 | `SWEEP_STOP_DOES_NOT_PROTECT_EXTREME` (22) |
| A | USDJPY | AL | GEOMETRY→EXECUTION | 80 | 80 | 0 | 0.00 | — |
| A | USDJPY | LN | CONTEXT→LOCATION | 173 | 146 | 27 | 15.61 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (27) |
| A | USDJPY | LN | LOCATION→TRIGGER | 146 | 120 | 26 | 17.81 | `TRIGGER_RULE_NOT_MET` (24) |
| A | USDJPY | LN | TRIGGER→GEOMETRY | 120 | 87 | 33 | 27.50 | `SWEEP_STOP_DOES_NOT_PROTECT_EXTREME` (33) |
| A | USDJPY | LN | GEOMETRY→EXECUTION | 87 | 87 | 0 | 0.00 | — |
| A | XAUUSD | AL | CONTEXT→LOCATION | 106 | 76 | 30 | 28.30 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (30) |
| A | XAUUSD | AL | LOCATION→TRIGGER | 76 | 62 | 14 | 18.42 | `TRIGGER_RULE_NOT_MET` (14) |
| A | XAUUSD | AL | TRIGGER→GEOMETRY | 62 | 50 | 12 | 19.35 | `SWEEP_STOP_DOES_NOT_PROTECT_EXTREME` (12) |
| A | XAUUSD | AL | GEOMETRY→EXECUTION | 50 | 50 | 0 | 0.00 | — |
| A | XAUUSD | LN | CONTEXT→LOCATION | 172 | 152 | 20 | 11.63 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (20) |
| A | XAUUSD | LN | LOCATION→TRIGGER | 152 | 116 | 36 | 23.68 | `TRIGGER_RULE_NOT_MET` (35) |
| A | XAUUSD | LN | TRIGGER→GEOMETRY | 116 | 62 | 54 | 46.55 | `SWEEP_STOP_DOES_NOT_PROTECT_EXTREME` (54) |
| A | XAUUSD | LN | GEOMETRY→EXECUTION | 62 | 62 | 0 | 0.00 | — |
| B | EURUSD | AL | CONTEXT→LOCATION | 171 | 160 | 11 | 6.43 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (11) |
| B | EURUSD | AL | LOCATION→TRIGGER | 160 | 0 | 160 | 100.00 | `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` (127) |
| B | EURUSD | AL | TRIGGER→GEOMETRY | 0 | 0 | 0 | — | — |
| B | EURUSD | AL | GEOMETRY→EXECUTION | 0 | 0 | 0 | — | — |
| B | EURUSD | LN | CONTEXT→LOCATION | 173 | 135 | 38 | 21.97 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (38) |
| B | EURUSD | LN | LOCATION→TRIGGER | 135 | 0 | 135 | 100.00 | `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` (106) |
| B | EURUSD | LN | TRIGGER→GEOMETRY | 0 | 0 | 0 | — | — |
| B | EURUSD | LN | GEOMETRY→EXECUTION | 0 | 0 | 0 | — | — |
| B | GBPUSD | AL | CONTEXT→LOCATION | 162 | 154 | 8 | 4.94 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (8) |
| B | GBPUSD | AL | LOCATION→TRIGGER | 154 | 4 | 150 | 97.40 | `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` (124) |
| B | GBPUSD | AL | TRIGGER→GEOMETRY | 4 | 4 | 0 | 0.00 | — |
| B | GBPUSD | AL | GEOMETRY→EXECUTION | 4 | 2 | 2 | 50.00 | `EXECUTION_LIMIT_EXPIRED` (2) |
| B | GBPUSD | LN | CONTEXT→LOCATION | 173 | 118 | 55 | 31.79 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (55) |
| B | GBPUSD | LN | LOCATION→TRIGGER | 118 | 0 | 118 | 100.00 | `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` (90) |
| B | GBPUSD | LN | TRIGGER→GEOMETRY | 0 | 0 | 0 | — | — |
| B | GBPUSD | LN | GEOMETRY→EXECUTION | 0 | 0 | 0 | — | — |
| B | USDJPY | AL | CONTEXT→LOCATION | 171 | 128 | 43 | 25.15 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (43) |
| B | USDJPY | AL | LOCATION→TRIGGER | 128 | 0 | 128 | 100.00 | `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` (102) |
| B | USDJPY | AL | TRIGGER→GEOMETRY | 0 | 0 | 0 | — | — |
| B | USDJPY | AL | GEOMETRY→EXECUTION | 0 | 0 | 0 | — | — |
| B | USDJPY | LN | CONTEXT→LOCATION | 173 | 146 | 27 | 15.61 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (27) |
| B | USDJPY | LN | LOCATION→TRIGGER | 146 | 0 | 146 | 100.00 | `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` (121) |
| B | USDJPY | LN | TRIGGER→GEOMETRY | 0 | 0 | 0 | — | — |
| B | USDJPY | LN | GEOMETRY→EXECUTION | 0 | 0 | 0 | — | — |
| B | XAUUSD | AL | CONTEXT→LOCATION | 106 | 78 | 28 | 26.42 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (28) |
| B | XAUUSD | AL | LOCATION→TRIGGER | 78 | 3 | 75 | 96.15 | `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` (62) |
| B | XAUUSD | AL | TRIGGER→GEOMETRY | 3 | 3 | 0 | 0.00 | — |
| B | XAUUSD | AL | GEOMETRY→EXECUTION | 3 | 1 | 2 | 66.67 | `EXECUTION_LIMIT_EXPIRED` (2) |
| B | XAUUSD | LN | CONTEXT→LOCATION | 172 | 152 | 20 | 11.63 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (20) |
| B | XAUUSD | LN | LOCATION→TRIGGER | 152 | 0 | 152 | 100.00 | `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` (115) |
| B | XAUUSD | LN | TRIGGER→GEOMETRY | 0 | 0 | 0 | — | — |
| B | XAUUSD | LN | GEOMETRY→EXECUTION | 0 | 0 | 0 | — | — |
| C | EURUSD | AL | CONTEXT→LOCATION | 171 | 160 | 11 | 6.43 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (11) |
| C | EURUSD | AL | LOCATION→TRIGGER | 160 | 30 | 130 | 81.25 | `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` (97) |
| C | EURUSD | AL | TRIGGER→GEOMETRY | 30 | 30 | 0 | 0.00 | — |
| C | EURUSD | AL | GEOMETRY→EXECUTION | 30 | 0 | 30 | 100.00 | `EXECUTION_LIMIT_EXPIRED` (29) |
| C | EURUSD | LN | CONTEXT→LOCATION | 173 | 135 | 38 | 21.97 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (38) |
| C | EURUSD | LN | LOCATION→TRIGGER | 135 | 24 | 111 | 82.22 | `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` (64) |
| C | EURUSD | LN | TRIGGER→GEOMETRY | 24 | 24 | 0 | 0.00 | — |
| C | EURUSD | LN | GEOMETRY→EXECUTION | 24 | 0 | 24 | 100.00 | `EXECUTION_LIMIT_EXPIRED` (22) |
| C | GBPUSD | AL | CONTEXT→LOCATION | 162 | 152 | 10 | 6.17 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (10) |
| C | GBPUSD | AL | LOCATION→TRIGGER | 152 | 23 | 129 | 84.87 | `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` (84) |
| C | GBPUSD | AL | TRIGGER→GEOMETRY | 23 | 23 | 0 | 0.00 | — |
| C | GBPUSD | AL | GEOMETRY→EXECUTION | 23 | 0 | 23 | 100.00 | `EXECUTION_LIMIT_EXPIRED` (22) |
| C | GBPUSD | LN | CONTEXT→LOCATION | 173 | 118 | 55 | 31.79 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (55) |
| C | GBPUSD | LN | LOCATION→TRIGGER | 118 | 27 | 91 | 77.12 | `TRIGGER_RULE_NOT_MET` (46) |
| C | GBPUSD | LN | TRIGGER→GEOMETRY | 27 | 27 | 0 | 0.00 | — |
| C | GBPUSD | LN | GEOMETRY→EXECUTION | 27 | 1 | 26 | 96.30 | `EXECUTION_LIMIT_EXPIRED` (24) |
| C | USDJPY | AL | CONTEXT→LOCATION | 171 | 128 | 43 | 25.15 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (43) |
| C | USDJPY | AL | LOCATION→TRIGGER | 128 | 25 | 103 | 80.47 | `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` (58) |
| C | USDJPY | AL | TRIGGER→GEOMETRY | 25 | 25 | 0 | 0.00 | — |
| C | USDJPY | AL | GEOMETRY→EXECUTION | 25 | 0 | 25 | 100.00 | `EXECUTION_LIMIT_EXPIRED` (24) |
| C | USDJPY | LN | CONTEXT→LOCATION | 173 | 146 | 27 | 15.61 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (27) |
| C | USDJPY | LN | LOCATION→TRIGGER | 146 | 23 | 123 | 84.25 | `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` (78) |
| C | USDJPY | LN | TRIGGER→GEOMETRY | 23 | 23 | 0 | 0.00 | — |
| C | USDJPY | LN | GEOMETRY→EXECUTION | 23 | 0 | 23 | 100.00 | `EXECUTION_LIMIT_EXPIRED` (20) |
| C | XAUUSD | AL | CONTEXT→LOCATION | 106 | 76 | 30 | 28.30 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (30) |
| C | XAUUSD | AL | LOCATION→TRIGGER | 76 | 12 | 64 | 84.21 | `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` (34) |
| C | XAUUSD | AL | TRIGGER→GEOMETRY | 12 | 12 | 0 | 0.00 | — |
| C | XAUUSD | AL | GEOMETRY→EXECUTION | 12 | 0 | 12 | 100.00 | `EXECUTION_LIMIT_EXPIRED` (12) |
| C | XAUUSD | LN | CONTEXT→LOCATION | 172 | 152 | 20 | 11.63 | `LOCATION_STRUCTURAL_AREA_NOT_REACHED` (20) |
| C | XAUUSD | LN | LOCATION→TRIGGER | 152 | 32 | 120 | 78.95 | `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` (74) |
| C | XAUUSD | LN | TRIGGER→GEOMETRY | 32 | 32 | 0 | 0.00 | — |
| C | XAUUSD | LN | GEOMETRY→EXECUTION | 32 | 0 | 32 | 100.00 | `EXECUTION_LIMIT_EXPIRED` (31) |

### 7.3 Largest attrition points

- `SESSION_TRADE_V2|EURUSD|ASIAN_LONDON|B_RANGE_REJECTION` LOCATION→TRIGGER: -160 of 160 (100.0%), dominant reason `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` ×127
- `SESSION_TRADE_V2|XAUUSD|LONDON_NEWYORK|B_RANGE_REJECTION` LOCATION→TRIGGER: -152 of 152 (100.0%), dominant reason `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` ×115
- `SESSION_TRADE_V2|GBPUSD|ASIAN_LONDON|B_RANGE_REJECTION` LOCATION→TRIGGER: -150 of 154 (97.4%), dominant reason `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` ×124
- `SESSION_TRADE_V2|USDJPY|LONDON_NEWYORK|B_RANGE_REJECTION` LOCATION→TRIGGER: -146 of 146 (100.0%), dominant reason `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` ×121
- `SESSION_TRADE_V2|EURUSD|LONDON_NEWYORK|B_RANGE_REJECTION` LOCATION→TRIGGER: -135 of 135 (100.0%), dominant reason `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` ×106
- `SESSION_TRADE_V2|EURUSD|ASIAN_LONDON|C_TREND_EXPANSION` LOCATION→TRIGGER: -130 of 160 (81.2%), dominant reason `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` ×97
- `SESSION_TRADE_V2|GBPUSD|ASIAN_LONDON|C_TREND_EXPANSION` LOCATION→TRIGGER: -129 of 152 (84.9%), dominant reason `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` ×84
- `SESSION_TRADE_V2|USDJPY|ASIAN_LONDON|B_RANGE_REJECTION` LOCATION→TRIGGER: -128 of 128 (100.0%), dominant reason `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` ×102
- `SESSION_TRADE_V2|USDJPY|LONDON_NEWYORK|C_TREND_EXPANSION` LOCATION→TRIGGER: -123 of 146 (84.2%), dominant reason `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` ×78
- `SESSION_TRADE_V2|XAUUSD|LONDON_NEWYORK|C_TREND_EXPANSION` LOCATION→TRIGGER: -120 of 152 (78.9%), dominant reason `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` ×74
- `SESSION_TRADE_V2|GBPUSD|LONDON_NEWYORK|B_RANGE_REJECTION` LOCATION→TRIGGER: -118 of 118 (100.0%), dominant reason `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` ×90
- `SESSION_TRADE_V2|EURUSD|LONDON_NEWYORK|C_TREND_EXPANSION` LOCATION→TRIGGER: -111 of 135 (82.2%), dominant reason `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` ×64

## 8. Geometry diagnostics

| Branch | Symbol | Session | Triggered | Geometry valid | Rejected | Rejection % | `SWEEP_STOP_DOES_NOT_PROTECT_EXTREME` | Sweep-stop % | Other reasons |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| A | EURUSD | AL | 128 | 68 | 60 | 46.88 | 60 | 46.88 | — |
| A | EURUSD | LN | 105 | 72 | 33 | 31.43 | 33 | 31.43 | — |
| A | GBPUSD | AL | 123 | 62 | 61 | 49.59 | 61 | 49.59 | — |
| A | GBPUSD | LN | 90 | 61 | 29 | 32.22 | 29 | 32.22 | — |
| A | USDJPY | AL | 102 | 80 | 22 | 21.57 | 22 | 21.57 | — |
| A | USDJPY | LN | 120 | 87 | 33 | 27.50 | 33 | 27.50 | — |
| A | XAUUSD | AL | 62 | 50 | 12 | 19.35 | 12 | 19.35 | — |
| A | XAUUSD | LN | 116 | 62 | 54 | 46.55 | 54 | 46.55 | — |
| B | EURUSD | AL | 0 | 0 | 0 | — | 0 | — | — |
| B | EURUSD | LN | 0 | 0 | 0 | — | 0 | — | — |
| B | GBPUSD | AL | 4 | 4 | 0 | 0.00 | 0 | 0.00 | — |
| B | GBPUSD | LN | 0 | 0 | 0 | — | 0 | — | — |
| B | USDJPY | AL | 0 | 0 | 0 | — | 0 | — | — |
| B | USDJPY | LN | 0 | 0 | 0 | — | 0 | — | — |
| B | XAUUSD | AL | 3 | 3 | 0 | 0.00 | 0 | 0.00 | — |
| B | XAUUSD | LN | 0 | 0 | 0 | — | 0 | — | — |
| C | EURUSD | AL | 30 | 30 | 0 | 0.00 | 0 | 0.00 | — |
| C | EURUSD | LN | 24 | 24 | 0 | 0.00 | 0 | 0.00 | — |
| C | GBPUSD | AL | 23 | 23 | 0 | 0.00 | 0 | 0.00 | — |
| C | GBPUSD | LN | 27 | 27 | 0 | 0.00 | 0 | 0.00 | — |
| C | USDJPY | AL | 25 | 25 | 0 | 0.00 | 0 | 0.00 | — |
| C | USDJPY | LN | 23 | 23 | 0 | 0.00 | 0 | 0.00 | — |
| C | XAUUSD | AL | 12 | 12 | 0 | 0.00 | 0 | 0.00 | — |
| C | XAUUSD | LN | 32 | 32 | 0 | 0.00 | 0 | 0.00 | — |

## 9. Execution diagnostics

| Branch | Symbol | Session | Order type | Geometry-valid signals | Fills | Unfilled | Expired | … never workable | Same-bar ambiguities | Fill rate | Closed | Open at end |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | EURUSD | AL | MARKET | 68 | 68 | 0 | 0 | 0 | 1 | 100.00 | 68 | 0 |
| A | EURUSD | LN | MARKET | 72 | 72 | 0 | 0 | 0 | 1 | 100.00 | 72 | 0 |
| A | GBPUSD | AL | MARKET | 62 | 62 | 0 | 0 | 0 | 0 | 100.00 | 62 | 0 |
| A | GBPUSD | LN | MARKET | 61 | 61 | 0 | 0 | 0 | 0 | 100.00 | 61 | 0 |
| A | USDJPY | AL | MARKET | 80 | 80 | 0 | 0 | 0 | 0 | 100.00 | 80 | 0 |
| A | USDJPY | LN | MARKET | 87 | 87 | 0 | 0 | 0 | 0 | 100.00 | 87 | 0 |
| A | XAUUSD | AL | MARKET | 50 | 50 | 0 | 0 | 0 | 0 | 100.00 | 50 | 0 |
| A | XAUUSD | LN | MARKET | 62 | 62 | 0 | 0 | 0 | 0 | 100.00 | 62 | 0 |
| B | EURUSD | AL | — | 0 | 0 | 0 | 0 | 0 | 0 | — | 0 | 0 |
| B | EURUSD | LN | — | 0 | 0 | 0 | 0 | 0 | 0 | — | 0 | 0 |
| B | GBPUSD | AL | LIMIT | 4 | 2 | 0 | 2 | 0 | 0 | 50.00 | 2 | 0 |
| B | GBPUSD | LN | — | 0 | 0 | 0 | 0 | 0 | 0 | — | 0 | 0 |
| B | USDJPY | AL | — | 0 | 0 | 0 | 0 | 0 | 0 | — | 0 | 0 |
| B | USDJPY | LN | — | 0 | 0 | 0 | 0 | 0 | 0 | — | 0 | 0 |
| B | XAUUSD | AL | LIMIT | 3 | 1 | 0 | 2 | 0 | 0 | 33.33 | 1 | 0 |
| B | XAUUSD | LN | — | 0 | 0 | 0 | 0 | 0 | 0 | — | 0 | 0 |
| C | EURUSD | AL | LIMIT | 30 | 0 | 0 | 30 | 1 | 0 | 0.00 | 0 | 0 |
| C | EURUSD | LN | LIMIT | 24 | 0 | 0 | 24 | 2 | 0 | 0.00 | 0 | 0 |
| C | GBPUSD | AL | LIMIT | 23 | 0 | 0 | 23 | 1 | 0 | 0.00 | 0 | 0 |
| C | GBPUSD | LN | LIMIT | 27 | 1 | 0 | 26 | 2 | 1 | 3.70 | 1 | 0 |
| C | USDJPY | AL | LIMIT | 25 | 0 | 0 | 25 | 1 | 0 | 0.00 | 0 | 0 |
| C | USDJPY | LN | LIMIT | 23 | 0 | 0 | 23 | 3 | 0 | 0.00 | 0 | 0 |
| C | XAUUSD | AL | LIMIT | 12 | 0 | 0 | 12 | 0 | 0 | 0.00 | 0 | 0 |
| C | XAUUSD | LN | LIMIT | 32 | 0 | 0 | 32 | 1 | 0 | 0.00 | 0 | 0 |

## 10. Friction analysis

Applied **only** to actually executed, closed trades. Segments with no executed trades report `—` (null), never a fabricated zero.

| Branch | Symbol | Session | Closed | Gross R | Net R | Friction R | Gross Exp R | Net Exp R | Friction drag / trade R | Gross>0 and Net≤0 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A | EURUSD | AL | 68 | -11.397 | -24.823 | 13.425 | -0.1676 | -0.3650 | 0.1974 | no |
| A | EURUSD | LN | 72 | 15.521 | 6.241 | 9.280 | 0.2156 | 0.0867 | 0.1289 | no |
| A | GBPUSD | AL | 62 | -14.088 | -24.493 | 10.404 | -0.2272 | -0.3950 | 0.1678 | no |
| A | GBPUSD | LN | 61 | 6.450 | 0.253 | 6.197 | 0.1057 | 0.0042 | 0.1016 | no |
| A | USDJPY | AL | 80 | -22.132 | -33.507 | 11.375 | -0.2766 | -0.4188 | 0.1422 | no |
| A | USDJPY | LN | 87 | 22.415 | 9.406 | 13.010 | 0.2576 | 0.1081 | 0.1495 | no |
| A | XAUUSD | AL | 50 | 0.218 | -19.448 | 19.666 | 0.0044 | -0.3890 | 0.3933 | yes |
| A | XAUUSD | LN | 62 | 31.603 | 5.132 | 26.471 | 0.5097 | 0.0828 | 0.4270 | no |
| B | EURUSD | AL | 0 | — | — | — | — | — | — | — |
| B | EURUSD | LN | 0 | — | — | — | — | — | — | — |
| B | GBPUSD | AL | 2 | -2.000 | -2.356 | 0.356 | -1.0000 | -1.1781 | 0.1781 | no |
| B | GBPUSD | LN | 0 | — | — | — | — | — | — | — |
| B | USDJPY | AL | 0 | — | — | — | — | — | — | — |
| B | USDJPY | LN | 0 | — | — | — | — | — | — | — |
| B | XAUUSD | AL | 1 | -1.000 | -1.239 | 0.239 | -1.0000 | -1.2389 | 0.2389 | no |
| B | XAUUSD | LN | 0 | — | — | — | — | — | — | — |
| C | EURUSD | AL | 0 | — | — | — | — | — | — | — |
| C | EURUSD | LN | 0 | — | — | — | — | — | — | — |
| C | GBPUSD | AL | 0 | — | — | — | — | — | — | — |
| C | GBPUSD | LN | 1 | 4.250 | 4.052 | 0.198 | 4.2500 | 4.0515 | 0.1985 | no |
| C | USDJPY | AL | 0 | — | — | — | — | — | — | — |
| C | USDJPY | LN | 0 | — | — | — | — | — | — | — |
| C | XAUUSD | AL | 0 | — | — | — | — | — | — | — |
| C | XAUUSD | LN | 0 | — | — | — | — | — | — | — |

**Friction-destroyed segments** (gross expectancy > 0 **and** net expectancy ≤ 0): `SESSION_TRADE_V2|XAUUSD|ASIAN_LONDON|A_SWEEP_REENTRY`

## 11. Conditional expectancy-shift view — **DIAGNOSTIC / NON-CAUSAL**

> These are expectancy shifts among surviving/downstream CLOSED-TRADE cohorts under sequential filtering. They are diagnostic associations, NOT causal estimates, and NOT counterfactual expectancies for the observations removed at each stage. No counterfactual methodology is implemented in this mission.

As explained in §2, under the non-counterfactual definition every stage's closed-trade cohort is the same set, so all shifts are exactly `0.0`. This is reported honestly rather than replaced with a fabricated decay curve.

| Branch | Stage | Retained | Closed | Cond Gross Exp R | Cond Net Exp R | Exp shift R | Win % | Win lift pp |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| A | CONTEXT | 1301 | 542 | 0.0527 | -0.1499 | — | 21.40 | — |
| A | LOCATION | 1067 | 542 | 0.0527 | -0.1499 | 0.0000 | 21.40 | 0.00 |
| A | TRIGGER | 846 | 542 | 0.0527 | -0.1499 | 0.0000 | 21.40 | 0.00 |
| A | GEOMETRY | 542 | 542 | 0.0527 | -0.1499 | 0.0000 | 21.40 | 0.00 |
| A | EXECUTION | 542 | 542 | 0.0527 | -0.1499 | 0.0000 | 21.40 | 0.00 |
| B | CONTEXT | 1301 | 3 | -1.0000 | -1.1983 | — | 0.00 | — |
| B | LOCATION | 1071 | 3 | -1.0000 | -1.1983 | 0.0000 | 0.00 | 0.00 |
| B | TRIGGER | 7 | 3 | -1.0000 | -1.1983 | 0.0000 | 0.00 | 0.00 |
| B | GEOMETRY | 7 | 3 | -1.0000 | -1.1983 | 0.0000 | 0.00 | 0.00 |
| B | EXECUTION | 3 | 3 | -1.0000 | -1.1983 | 0.0000 | 0.00 | 0.00 |
| C | CONTEXT | 1301 | 1 | 4.2500 | 4.0515 | — | 100.00 | — |
| C | LOCATION | 1067 | 1 | 4.2500 | 4.0515 | 0.0000 | 100.00 | 0.00 |
| C | TRIGGER | 196 | 1 | 4.2500 | 4.0515 | 0.0000 | 100.00 | 0.00 |
| C | GEOMETRY | 196 | 1 | 4.2500 | 4.0515 | 0.0000 | 100.00 | 0.00 |
| C | EXECUTION | 1 | 1 | 4.2500 | 4.0515 | 0.0000 | 100.00 | 0.00 |

**Measurable economic degradation on executed trades (gross → net):**

| Branch | Closed | Gross Exp R | Net Exp R | Friction decay R/trade |
|---|---:|---:|---:|---:|
| A_SWEEP_REENTRY | 542 | 0.0527 | -0.1499 | 0.2026 |
| B_RANGE_REJECTION | 3 | -1.0000 | -1.1983 | 0.1983 |
| C_TREND_EXPANSION | 1 | 4.2500 | 4.0515 | 0.1985 |

## 12. Report questions

### Q1. Where does A lose the largest number/percentage of opportunities?

In absolute count, A's largest single loss is **TRIGGER → GEOMETRY**: 304 of 846 authoritative triggers are removed (35.9%), every one of them by the frozen `SWEEP_STOP_DOES_NOT_PROTECT_EXTREME` rule.

The full A chain is CONTEXT 1936 raw → 1301 valid → LOCATION 1067 → TRIGGER 846 → GEOMETRY 542 → EXECUTION 542 → CLOSED 542. The CONTEXT step removes 635 observations, but 551 of those are non-trading calendar days (zero reference bars) rather than strategy rejections, so CONTEXT is not a strategy-quality loss. Among genuine strategy filtering, geometry is the largest sink, followed by LOCATION → TRIGGER (-221, 20.7%) and CONTEXT → LOCATION (-234, 18.0%). A's GEOMETRY → EXECUTION attrition is 0 because A uses market-style entries.

### Q2. Does A already have poor trigger behavior, or is most attrition introduced by geometry?

Both contribute, but geometry is the larger filter. Of 1301 valid A observations, 1067 (82.0%) reached the structural area and 846 (79.3% of those) produced an authoritative sweep+reclaim trigger — that is a *healthy* trigger conversion, so A does not suffer from trigger scarcity. Geometry then removes 35.9% of those triggers. Conclusion: **A's attrition is dominated by geometry, not by weak triggering** — but this is a statement about opportunity *count*, not about whether the removed opportunities would have been profitable. Nothing in this analysis can say what the rejected sweeps would have returned, because they were never executed.

### Q3. How frequently does `SWEEP_STOP_DOES_NOT_PROTECT_EXTREME` remove A triggers?

304 of 846 A triggers (35.9%) across the DEV partition. Per-segment rates (see §8) range from 19.4% to 49.6%. It is the **only** geometry rejection reason observed for A; no other geometry check (positive risk, 25% reference-range stop, stop side, target direction, 4R/5R distances, branch entry geometry) ever failed on a frozen STV2 signal.

### Q4. Does realistic execution/friction materially degrade the remaining A trades?

Yes, decisively. A's 542 closed trades have conditional downstream **gross** expectancy +0.0527R but **net** expectancy -0.1499R — an average friction drag of 0.2026R per trade (109.83R in total). Friction alone flips A from gross-positive to net-negative. Execution *fill* behaviour is not the problem for A (fill rate 100%, market-style next-executable-price entries); the degradation is pure cost. Friction-destroyed segments (gross expectancy > 0 and net expectancy ≤ 0): `SESSION_TRADE_V2|XAUUSD|ASIAN_LONDON|A_SWEEP_REENTRY`.

### Q5. Is B primarily sparse at LOCATION, sparse at TRIGGER, rejected by geometry, or failing to fill?

**Neither location-sparse nor geometry-rejected.** B reaches its structural area on 1071 of 1301 valid observations (82.3%) and its own frozen rejection predicate fires on 854 of them — but only **7** sessions are authoritatively attributed to B by the frozen engine (847 are preempted), because the frozen A → B → C priority gives the session to A whenever a sweep exists. The attrition table shows `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` as B's dominant trigger-stage rejection reason. Geometry then rejects **0** of the 7 survivors, and execution fills 3 of 7 (42.9%) — the remainder expire unfilled at the boundary limit. So B is best described as **priority-starved first, fill-starved second**; with 3 closed trades no economic conclusion about B is supportable.

**Structural root of B's scarcity** (a restatement of the frozen predicates, not a rule change): A's long sweep predicate `low < ref_low AND close > ref_low` strictly subsumes B's long rejection predicate `low <= ref_low AND inward close` whenever the boundary is *breached*. Since A is scanned over the whole trade window before B, B can only own a session when price touches the reference boundary to the **exact tick**. All 7 authoritative B triggers in DEV have their entry exactly on the reference boundary (7/7), confirming this. B's scarcity is a structural property of the frozen predicate overlap, not evidence that range rejection is a weak idea.

### Q6. Is C generating valid breakouts but starving at its EQ limit?

**Yes — this is the single clearest finding in the analysis.** C produces 196 authoritative body-close expansion triggers, of which 196 (100.0%) are geometrically valid — C has zero geometry attrition. But only **1 of 196** geometry-valid proposals ever fill (0.5%): price must retrace from a confirmed body-close breakout all the way back to the reference equilibrium (box mid) inside the remaining trade window, which essentially never happens. 195 expired unfilled, of which 11 were generated on the final trade-window candle and were never workable at all. C's funnel is **trigger-rich and execution-starved**.

### Q7. Which symbol/session segments behave differently?

**Session is the dominant axis.** LONDON_NEWYORK: 283 closed trades, conditional gross expectancy +0.2835R, net +0.0886R, win rate 26.1%. ASIAN_LONDON: 263 closed trades, gross -0.1916R, net -0.4025R, win rate 16.3%. Every ASIAN_LONDON A segment is net-negative; every LONDON_NEWYORK A segment is net-positive or near flat (this matches the economic campaign's DEV survivor set). **Symbol is a weaker axis**: per-symbol conditional net expectancy ranges from EURUSD=-0.1327R (140 closed), GBPUSD=-0.1789R (126 closed), USDJPY=-0.1443R (167 closed), XAUUSD=-0.1377R (113 closed). Note that this DEV-only session split is exactly the pattern that failed to replicate OOS in the economic campaign, so it must be treated as a DEV observation, not a validated edge.

### Q8. Which diagnostics are robust enough to justify a NEW candidate hypothesis?

Three, all of them *structural* (count-based) rather than economic, which is why they survive the sample-size objection:

1. **C EQ-limit fill starvation** — 1/196 fills is a structural fact about the order model, not a noisy expectancy estimate. Robust.
2. **A geometry attrition** — 304/846 triggers removed by a single deterministic rule, consistent across all 8 A segments. Robust as a *measurement*; it does **not** establish that the removed trades would have been profitable.
3. **B/C priority preemption** — B's own predicate fires 854 times but the frozen A→B→C precedence leaves it only 7 sessions (847 preempted); C loses 537 the same way. Robust as a measurement.

**Not** robust enough: A's friction decay is a large and reliable *cost* measurement (0.2026R/trade over 542 trades), but 'reduce friction by changing the stop' is a performance claim that requires a preregistered experiment, not an inference from this table.

### Q9. Which findings are inconclusive because of sample size?

- `SESSION_TRADE_V2|EURUSD|ASIAN_LONDON|B_RANGE_REJECTION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|EURUSD|LONDON_NEWYORK|B_RANGE_REJECTION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|GBPUSD|ASIAN_LONDON|B_RANGE_REJECTION`: 2 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|GBPUSD|LONDON_NEWYORK|B_RANGE_REJECTION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|USDJPY|ASIAN_LONDON|B_RANGE_REJECTION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|USDJPY|LONDON_NEWYORK|B_RANGE_REJECTION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|XAUUSD|ASIAN_LONDON|B_RANGE_REJECTION`: 1 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|XAUUSD|LONDON_NEWYORK|B_RANGE_REJECTION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|EURUSD|ASIAN_LONDON|C_TREND_EXPANSION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|EURUSD|LONDON_NEWYORK|C_TREND_EXPANSION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|GBPUSD|ASIAN_LONDON|C_TREND_EXPANSION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|GBPUSD|LONDON_NEWYORK|C_TREND_EXPANSION`: 1 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|USDJPY|ASIAN_LONDON|C_TREND_EXPANSION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|USDJPY|LONDON_NEWYORK|C_TREND_EXPANSION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|XAUUSD|ASIAN_LONDON|C_TREND_EXPANSION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|XAUUSD|LONDON_NEWYORK|C_TREND_EXPANSION`: 0 closed trades (< 30) — no economic conclusion supportable
- Stage-to-stage conditional expectancy shifts are 0.0 by construction and therefore carry no information about whether any individual stage rule helps or hurts; answering that requires a preregistered counterfactual experiment, which is out of scope for this diagnostic mission.

### Q10. Does any finding contradict the existing STV2 economic-verification report?

**No contradiction.** Every economic quantity in this funnel analysis is produced by the SAME frozen evaluation path (`campaign.evaluate_window`) as the economic-verification campaign, then re-aggregated along the strategy funnel. The DEV campaign result was also re-executed from the frozen HistData zips and reproduced `dev_result.json` exactly. The two reports therefore agree on every shared quantity.

- The economic-verification report's conclusion (A_SWEEP_REENTRY REJECT on OOS; B and C RESEARCH_ONLY) is a VERIFICATION-LIFECYCLE verdict. This strategy-funnel report makes no promotion/rejection decision and does not re-open or re-interpret the OOS result; it only localizes WHERE opportunity and economics are lost on DEV.
- No OOS data was used to design any stage of this funnel. The DEV funnel definition is frozen by this report; any later OOS confirmation view must not alter it.

Contradictions: none.

## 13. Root-cause classification

| Branch | Root cause | Contributors | Closed N | Sample sufficient for economics |
|---|---|---|---:|---|
| A_SWEEP_REENTRY | `MULTIPLE_CONTRIBUTORS` | `EVIDENCE_SUPPORTS_GEOMETRY_ATTRITION`, `EVIDENCE_SUPPORTS_FRICTION_DECAY` | 542 | yes |
| B_RANGE_REJECTION | `INSUFFICIENT_SAMPLE` | — | 3 | no |
| C_TREND_EXPANSION | `EVIDENCE_SUPPORTS_EXECUTION_FILL_STARVATION` | `EVIDENCE_SUPPORTS_EXECUTION_FILL_STARVATION` | 1 | no |

**A_SWEEP_REENTRY** — `MULTIPLE_CONTRIBUTORS`

- A_SWEEP_REENTRY: LOCATION->TRIGGER attrition 20.7% (1067->846); own predicate fired 852 times, 0 removed by frozen precedence
- A_SWEEP_REENTRY: TRIGGER->GEOMETRY attrition 35.9% (846->542); rejection reasons {'SWEEP_STOP_DOES_NOT_PROTECT_EXTREME': 304}
- A_SWEEP_REENTRY: conditional downstream gross expectancy +0.0527R flips to net -0.1499R over 542 closed trades (avg cost 0.2026R/trade)

**B_RANGE_REJECTION** — `INSUFFICIENT_SAMPLE`

- B_RANGE_REJECTION: LOCATION->TRIGGER attrition is 99.3% (1071->7) BUT the branch's own predicate fires on 854/1071 (79.7%) observations and 847 are removed by the frozen A->B->C precedence. This is precedence preemption, NOT trigger weakness — it is not classified as a trigger-rule defect.
- B_RANGE_REJECTION: geometry removes only 0.0% of triggers (7->7) — geometry is not a material filter for this branch
- B_RANGE_REJECTION: fill rate 42.86% (3/7) is low but the 7-proposal sample is below the 30-observation threshold for a structural claim
- B_RANGE_REJECTION: only 3 closed trades (< 30); no economic claim about this branch is supportable

**C_TREND_EXPANSION** — `EVIDENCE_SUPPORTS_EXECUTION_FILL_STARVATION`

- C_TREND_EXPANSION: LOCATION->TRIGGER attrition 81.6% (1067->196); own predicate fired 733 times, 537 removed by frozen precedence
- C_TREND_EXPANSION: geometry removes only 0.0% of triggers (196->196) — geometry is not a material filter for this branch
- C_TREND_EXPANSION: fill rate 0.51% (1/196 geometry-valid proposals filled under the frozen order model)
- C_TREND_EXPANSION: only 1 closed trades (< 30); no economic claim about this branch is supportable

## 14. Consistency with the existing STV2 economic-verification report

Every economic quantity in this funnel analysis is produced by the SAME frozen evaluation path (`campaign.evaluate_window`) as the economic-verification campaign, then re-aggregated along the strategy funnel. The DEV campaign result was also re-executed from the frozen HistData zips and reproduced `dev_result.json` exactly. The two reports therefore agree on every shared quantity.

| Quantity | Economic-verification campaign | This funnel analysis | Match |
|---|---:|---:|---|
| A_SWEEP_REENTRY closed trades | 542 | 542 | yes |
| A_SWEEP_REENTRY gross expectancy R | 0.0528 | 0.0527 | yes |
| A_SWEEP_REENTRY net expectancy R | -0.1499 | -0.1499 | yes |
| B_RANGE_REJECTION closed trades | 3 | 3 | yes |
| B_RANGE_REJECTION gross expectancy R | -1.0 | -1.0 | yes |
| B_RANGE_REJECTION net expectancy R | -1.1983 | -1.1983 | yes |
| C_TREND_EXPANSION closed trades | 1 | 1 | yes |
| C_TREND_EXPANSION gross expectancy R | 4.25 | 4.25 | yes |
| C_TREND_EXPANSION net expectancy R | 4.0515 | 4.0515 | yes |
| Combined closed trades | 546 | 546 | yes |
| Combined net R | -80.7814 | -80.7814 | yes |

`CONSISTENT_WITH_EXISTING_STV2_REPORT = True`

**Contradictions:**

- none

## 15. Follow-up hypotheses (post-measurement only)

Each item below is a proposal for a **NEW candidate identity**. `SESSION_TRADE_V2_v2.0.0_e1ffe9f1e5cc` is never mutated in place, and no V3 code was written in this mission. None of these is asserted to be correct — each is a preregistration requirement, not a finding.

### `STV3_H1_SWEEP_STOP_GEOMETRY`

| Field | Value |
|---|---|
| `evidence_source` | geometry_analysis.json; funnel_stage_matrix.json (TRIGGER→GEOMETRY rows) |
| `observed_problem` | 304 of 846 A triggers (35.9%) are discarded because the fixed 25%-of-reference-range stop sits inside the sweep extreme. This is a measured attrition fact; the economics of the discarded opportunities are unknown and unknowable from this dataset. |
| `proposed_new_candidate_change` | A NEW candidate (e.g. SESSION_TRADE_V3_A_STOPGEOM) whose A stop is placed beyond the sweep extreme by a defined buffer instead of at a fixed 25% of the reference range. SESSION_TRADE_V2 @ 2.0.0 is NOT modified. |
| `what_must_be_preregistered` | The exact stop formula and buffer; that R is redefined by that stop (so 4R/5R targets move); the expected direction and magnitude of the effect; the acceptance thresholds; the DEV/OOS/holdout partitions; and an explicit statement that the retained-but-previously-rejected trades are a NEW population, not a recovered one. |
| `required_new_validation` | A fresh full verification lifecycle for the new candidate id: contract, data quality, DEV screen, freeze, OOS verification, walk-forward, regime/stability. The STV2 OOS failure may not be reused as evidence for or against it. |

### `STV3_H2_EXPANSION_ENTRY_MODEL`

| Field | Value |
|---|---|
| `evidence_source` | execution_analysis.json (C_TREND_EXPANSION rows) |
| `observed_problem` | C produces 196 valid expansion triggers with 100% geometry validity but only 1/196 fills (0.51%). The EQ (box-mid) retrace limit is almost never reached inside the remaining trade window, so C is structurally unmeasurable rather than unprofitable. |
| `proposed_new_candidate_change` | A NEW candidate whose expansion entry model is specified to be reachable (the design space includes, but is not limited to, a shallower retrace level, a broken-boundary retest, or a stop-entry continuation). No specific variant is endorsed by this analysis. |
| `what_must_be_preregistered` | The entry model and its stop/target geometry; the order type; the expiry rule; the minimum fill rate that would make the branch measurable at all; and the sample size required before any economic statement is permitted. |
| `required_new_validation` | Fill-rate feasibility screen on DEV first (a purely structural gate), then the full verification lifecycle under a new candidate id. C's deterministic runner management must also be defined, since the frozen spec's 'confirmed M15 swing' trail is not deterministic and is currently replayed as C_FIXED_EXIT_PROXY. |

### `STV3_H3_BRANCH_PRECEDENCE`

| Field | Value |
|---|---|
| `evidence_source` | attrition_analysis.json (B/C TRIGGER rejection reasons) |
| `observed_problem` | B's rejection rule fires on many sessions but the frozen A→B→C precedence attributes only 7 sessions to B (dominant reason `TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY`); C loses 871 observations at TRIGGER with preemption as a major component. The branches are therefore not independently measurable under V2's single-decision-per-session contract. |
| `proposed_new_candidate_change` | A NEW candidate that makes branch arbitration explicit and measurable — e.g. evaluating branches independently per session, or defining a precedence rule that is itself a declared parameter. V2's precedence stays frozen. |
| `what_must_be_preregistered` | Whether branches may co-fire on one session; how overlapping positions are accounted for in R terms; the risk-budget implications; and the fact that this changes the unit of observation, so prior STV2 statistics are not comparable. |
| `required_new_validation` | Full verification lifecycle under a new candidate id, plus an explicit multiple-comparisons policy because independent branch evaluation materially increases the number of tested hypotheses. |

### `STV3_H4_FRICTION_AWARE_RISK_UNIT`

| Field | Value |
|---|---|
| `evidence_source` | friction_analysis.json; branch_summary.json |
| `observed_problem` | A's 542 closed trades are gross-positive and net-negative; the friction drag is large relative to R because R itself is only 25% of a session reference range, which on quiet sessions is small in price terms. |
| `proposed_new_candidate_change` | A NEW candidate with a declared minimum risk distance (or a minimum friction-to-R ratio) as an admission filter, so that sessions whose R is too small to survive realistic cost are never traded. |
| `what_must_be_preregistered` | The exact threshold and the fact that it is a CONTEXT-stage admission filter, not an exit optimization; the expected reduction in trade count; and that the threshold must be chosen on DEV only and then frozen. |
| `required_new_validation` | Full verification lifecycle under a new candidate id. This is explicitly NOT a validated improvement: filtering on an in-sample cost ratio is a known overfitting hazard and must be tested out of sample. |

## 16. Inconclusive findings

- `SESSION_TRADE_V2|EURUSD|ASIAN_LONDON|B_RANGE_REJECTION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|EURUSD|LONDON_NEWYORK|B_RANGE_REJECTION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|GBPUSD|ASIAN_LONDON|B_RANGE_REJECTION`: 2 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|GBPUSD|LONDON_NEWYORK|B_RANGE_REJECTION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|USDJPY|ASIAN_LONDON|B_RANGE_REJECTION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|USDJPY|LONDON_NEWYORK|B_RANGE_REJECTION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|XAUUSD|ASIAN_LONDON|B_RANGE_REJECTION`: 1 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|XAUUSD|LONDON_NEWYORK|B_RANGE_REJECTION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|EURUSD|ASIAN_LONDON|C_TREND_EXPANSION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|EURUSD|LONDON_NEWYORK|C_TREND_EXPANSION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|GBPUSD|ASIAN_LONDON|C_TREND_EXPANSION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|GBPUSD|LONDON_NEWYORK|C_TREND_EXPANSION`: 1 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|USDJPY|ASIAN_LONDON|C_TREND_EXPANSION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|USDJPY|LONDON_NEWYORK|C_TREND_EXPANSION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|XAUUSD|ASIAN_LONDON|C_TREND_EXPANSION`: 0 closed trades (< 30) — no economic conclusion supportable
- `SESSION_TRADE_V2|XAUUSD|LONDON_NEWYORK|C_TREND_EXPANSION`: 0 closed trades (< 30) — no economic conclusion supportable
- Stage-to-stage conditional expectancy shifts are 0.0 by construction and therefore carry no information about whether any individual stage rule helps or hurts; answering that requires a preregistered counterfactual experiment, which is out of scope for this diagnostic mission.

_Economic claims require at least 30 closed trades (EdgeLab canonical minimum). Segments below that threshold are reported but no economic conclusion is drawn from them._

