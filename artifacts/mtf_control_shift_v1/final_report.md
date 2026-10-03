# ST_MTF_CONTROL_SHIFT_V1 economic verification

## FINAL_STATUS = COMPLETE

## DATA_BLOCK_RESOLVED = true

DATA_REUSE_AUTHORITY = `PR_10_HISTDATA_2017`

`RAW_DATA_IDENTITY_REUSED_FROM_STV2 = true`.

The exact PR #10 HistData archives were reacquired from the pinned public mirror and matched the PR #10 SHA256 values. The STV2 strategy and results were not imported.

### Raw datasets

| Symbol | Source | Raw SHA256 | Timezone | Quality |
|---|---|---|---|---|
| EURUSD | `parrondo/deeptrading/data/raw/eurusd/HISTDATA_COM_ASCII_EURUSD_M1_2017.zip` | `0dcd66dc67d7af4716404a5315d376ee1e7eaebe292afbda3c1003d2dfa16f57` | America/New_York → UTC | PASS |
| GBPUSD | `parrondo/deeptrading/data/raw/gbpusd/HISTDATA_COM_ASCII_GBPUSD_M1_2017.zip` | `e5ba3800e37fae0e326dbaa234952ca04e8f378c08b036530a2811206110c10b` | America/New_York → UTC | PASS |
| USDJPY | `parrondo/deeptrading/data/raw/usdjpy/HISTDATA_COM_ASCII_USDJPY_M1_2017.zip` | `477a1f515586f06d67cb75b3662260160e1e29e63c51804a30a5e7d69b09df5f` | America/New_York → UTC | PASS |
| XAUUSD | `parrondo/deeptrading/data/raw/xauusd/HISTDATA_COM_ASCII_XAUUSD_M1_2017.zip` | `a39c1ccaaeb022c83309685107c9e619c2bcff8b2fd94fbd7405a721a4fe70ff` | America/New_York → UTC | PASS |

Derived M1/M15/H1/H4/D1 hashes, counts, and rejected incomplete buckets are in `dataset_manifest.json`. M15 uses the reused frozen `>=13/15` rule. H1 uses four M15 bars, H4 uses four H1 bars, and D1 uses five H4 bars because the documented session closure leaves five complete UTC H4 bars on normal trading days. No forward-fill was used.

## Partition and holdout

- WARMUP: `2017-01-01 → 2017-03-01`
- DEV: `2017-03-01 → 2017-09-01`
- OOS: `2017-09-01 → 2017-12-01`
- SEALED HOLDOUT: `2017-12-01 → 2018-01-01`
- `HOLDOUT_TOUCHED = false`

Only WARMUP + DEV bars were loaded for the economic replay. OOS was not opened because no DEV cell survived the sample gate.

## Source and tests

- Source commit: `1d1c75c92a7fda80696a56d4e1ccbe402f3ab71a`
- Source artifacts: byte-exact; hashes in `source_artifact_hashes.json`
- Focused strategy tests: **7 passed**
- Data contract tests: **4 passed**
- Full EdgeLab regression: **185 passed**
- No broker, MT5 `order_send`, demo, live, or execution-gateway API was used.

## DEV matrix

All eight cells produced zero valid signals. They are `INSUFFICIENT_SAMPLE`, not zero-profit trades.

| Symbol | Session | Signals | Filled | Closed | Net R | Net Exp | Net PF | Win % | Max DD R | Friction R | Status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| EURUSD | ASIAN_LONDON | 0 | 0 | 0 | null | null | null | null | null | 0 | INSUFFICIENT_SAMPLE |
| EURUSD | LONDON_NEWYORK | 0 | 0 | 0 | null | null | null | null | null | 0 | INSUFFICIENT_SAMPLE |
| GBPUSD | ASIAN_LONDON | 0 | 0 | 0 | null | null | null | null | null | 0 | INSUFFICIENT_SAMPLE |
| GBPUSD | LONDON_NEWYORK | 0 | 0 | 0 | null | null | null | null | null | 0 | INSUFFICIENT_SAMPLE |
| USDJPY | ASIAN_LONDON | 0 | 0 | 0 | null | null | null | null | null | 0 | INSUFFICIENT_SAMPLE |
| USDJPY | LONDON_NEWYORK | 0 | 0 | 0 | null | null | null | null | null | 0 | INSUFFICIENT_SAMPLE |
| XAUUSD | ASIAN_LONDON | 0 | 0 | 0 | null | null | null | null | null | 0 | INSUFFICIENT_SAMPLE |
| XAUUSD | LONDON_NEWYORK | 0 | 0 | 0 | null | null | null | null | null | 0 | INSUFFICIENT_SAMPLE |

## Funnel totals

- D1/H4 aligned: **2,246** observations
- Fresh H4 POI: **2,129**
- H4 POI reached: **170**
- True H1 control shifts: **0**
- M15 refinements: **0**
- Valid geometry: **0**
- Limit fills: **0**
- Expired limits: **0**
- Forced-flat: **0**
- Closed trades: **0**
- Liquidity sweeps: **1**
- FVG rebalances: **158**
- Failed shifts: **0**

The largest attrition point is the H1 control-shift trigger. D1/H4 alignment is selective but does not by itself starve the funnel; the candidate loses all 170 reached POI observations before a valid shift.

## Economics and lifecycle

- Gross R: `null` — no trades
- Net R: `null` — no trades
- Gross expectancy: `null`
- Net expectancy: `null`
- Gross PF: `null`
- Net PF: `null`
- Maximum drawdown: `null`
- Total friction: `0` — no fills, not zero-cost economics
- Friction model: available from the approved PR #10 authority, including instrument-specific XAUUSD costs

`DEV_SURVIVORS = []`.

`OOS_RESULT = NOT_RUN` because no cell survived DEV with sufficient sample.

`WALK_FORWARD = NOT_REACHED`.

`REGIME = NOT_REACHED`.

`LIFECYCLE_STAGE_REACHED = DEV_SCREEN_COMPLETE_NO_SURVIVORS`.

`EDGE_VERIFIED = false`.

## Conclusion

The frozen candidate did not produce enough valid signals to estimate economics in the frozen DEV interval. This is an insufficient-sample rejection, not evidence of positive or negative expectancy. No parameters were tuned and no OOS evidence was consumed.
