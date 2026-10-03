# ST_MTF_CONTROL_SHIFT_V2 freshness hypothesis design

## Status

`STATUS = READY_FOR_V2_DEV_REPLAY`

No economic replay has been run. V1 remains unchanged and the holdout remains sealed.

## Parent and candidate

- Parent: `ST_MTF_CONTROL_SHIFT_V1 @ 1.0.0`
- Candidate: `ST_MTF_CONTROL_SHIFT_V2 @ 2.0.0`
- V1 YAML SHA256: `9e94b4354caf81bb596fcf981cb723fbc7755bc0401d51f8eb2c291635ddb80f`
- V2 YAML SHA256: `56b6032fc949564e0ff8d147eb794560088fb0d90eac3bc549de504f01a6cc91`
- Only behavior change: `max_h1_shift_age: 4 -> 24` closed H1 bars

## Age measurement

The most recent historical directional H1 control shift otherwise matching the required direction/context was measured for all 170 location-pass observations. V1 eligibility remains exactly `shift_age_h1_bars <= 4`.

| Age | Count | Percentage | Cumulative count | Cumulative percentage |
|---:|---:|---:|---:|---:|
| 17 | 4 | 2.3529% | 4 | 2.3529% |
| 18 | 4 | 2.3529% | 8 | 4.7059% |
| 19 | 5 | 2.9412% | 13 | 7.6471% |
| 20 | 4 | 2.3529% | 17 | 10.0000% |
| 21 | 1 | 0.5882% | 18 | 10.5882% |
| 31 | 4 | 2.3529% | 22 | 12.9412% |
| 32 | 1 | 0.5882% | 23 | 13.5294% |
| 34 | 3 | 1.7647% | 26 | 15.2941% |
| 35 | 4 | 2.3529% | 30 | 17.6471% |
| 36 | 8 | 4.7059% | 38 | 22.3529% |
| 37 | 5 | 2.9412% | 43 | 25.2941% |
| 38 | 1 | 0.5882% | 44 | 25.8824% |
| 40 | 7 | 4.1176% | 51 | 30.0000% |
| 41 | 1 | 0.5882% | 52 | 30.5882% |
| 43 | 3 | 1.7647% | 55 | 32.3529% |
| 44 | 4 | 2.3529% | 59 | 34.7059% |
| 45 | 4 | 2.3529% | 63 | 37.0588% |
| 46 | 1 | 0.5882% | 64 | 37.6471% |
| 50 | 1 | 0.5882% | 65 | 38.2353% |
| 52 | 3 | 1.7647% | 68 | 40.0000% |
| 53 | 4 | 2.3529% | 72 | 42.3529% |
| 59 | 4 | 2.3529% | 76 | 44.7059% |
| 60 | 8 | 4.7059% | 84 | 49.4118% |
| 61 | 5 | 2.9412% | 89 | 52.3529% |
| 62 | 4 | 2.3529% | 93 | 54.7059% |
| 63 | 4 | 2.3529% | 97 | 57.0588% |
| 64 | 1 | 0.5882% | 98 | 57.6471% |
| 66 | 3 | 1.7647% | 101 | 59.4118% |
| 71 | 4 | 2.3529% | 105 | 61.7647% |
| 72 | 1 | 0.5882% | 106 | 62.3529% |
| 112 | 3 | 1.7647% | 109 | 64.1176% |
| 113 | 4 | 2.3529% | 113 | 66.4706% |
| 114 | 4 | 2.3529% | 117 | 68.8235% |
| 115 | 1 | 0.5882% | 118 | 69.4118% |
| 140 | 3 | 1.7647% | 121 | 71.1765% |
| 141 | 4 | 2.3529% | 125 | 73.5294% |
| 144 | 1 | 0.5882% | 126 | 74.1176% |
| 154 | 3 | 1.7647% | 129 | 75.8824% |
| 155 | 4 | 2.3529% | 133 | 78.2353% |
| 156 | 4 | 2.3529% | 137 | 80.5882% |
| 157 | 1 | 0.5882% | 138 | 81.1765% |
| 231 | 3 | 1.7647% | 141 | 82.9412% |
| 232 | 4 | 2.3529% | 145 | 85.2941% |
| 233 | 4 | 2.3529% | 149 | 87.6471% |
| 234 | 5 | 2.9412% | 154 | 90.5882% |
| 235 | 1 | 0.5882% | 155 | 91.1765% |
| 255 | 4 | 2.3529% | 159 | 93.5294% |
| 256 | 4 | 2.3529% | 163 | 95.8824% |
| 257 | 4 | 2.3529% | 167 | 98.2353% |
| 259 | 3 | 1.7647% | 170 | 100.0000% |

Quantiles:

- P25: `37.25`
- P50: `61.0`
- P75: `154.0`
- P90: `234.0`
- P95: `256.0`
- MAX: `259`

## Structural coverage

| Max shift age | Eligible N | Eligible % |
|---:|---:|---:|
| 4 | 0 | 0.0000% |
| 6 | 0 | 0.0000% |
| 8 | 0 | 0.0000% |
| 12 | 0 | 0.0000% |
| 16 | 0 | 0.0000% |
| 24 | 18 | 10.5882% |

## Selection

`PROPOSED_V2_MAX_SHIFT_AGE = 24`. This is the smallest nonzero threshold among the preregistered diagnostic values. It yields 18/170, or 10.5882%, structural trigger coverage. The selection is based only on the measured age distribution, not expectancy or any economic result.

## Preregistration

The fixed symbols, sessions, data lineage, friction authority, funnel mapping, DEV partition, and existing gates are recorded in `v2_preregistration.json`. The economic replay was intentionally stopped before execution.
