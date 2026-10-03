# SESSION_TRADE_V2 @ 2.0.0 — Economic Verification Final Report

**FINAL_STATUS: COMPLETE**

## Identity & Environment

- REPO: aungmyat1/ag-edgelab
- BRANCH: arena/01a100ce-ag-edgelab
- HEAD: e62746c35ac5a231e79366eb2d1b495b33ae43e2
- WORKTREE STATUS: 11 uncommitted paths
- SOURCE_REPO: aungmyat1/AG-profit-trading-assit (PR #33, branch `feat/session-trade-v2-unified`)
- SOURCE_STRATEGY_SHA (source_commit): `e1ffe9f1e5ccfb9a336f1b4ae4289d41901ec5d2`
- SOURCE_ARTIFACT_SHA256 (frozen byte-exact copies):
    - `engine.py`: `d7e0289c75c7cdb7386fb5f2e7e73151455cfed7605fda21841ce359fa2d0acb`
    - `models.py`: `db43c06df3da1a67276f63124bca4c8724e15c1b53d192c55ede8ce1da3ecb43`
    - `SESSION_TRADE_V2.yaml`: `3c7ea2eb68938172f9a91fcde732f7b4c9c2b0bc54c4b7e01adcc72cd52a861b`
    - `SESSION_TRADE_V2_SPEC.md`: `edf74dccc28bdbfc6c2a032b20ffe6b88c9ca086c833fbfcb368db3c04500219`
- CANDIDATE_ID: `SESSION_TRADE_V2_v2.0.0_e1ffe9f1e5cc`
- EXECUTION_AUTHORITY: {'demo_authorized': False, 'live_authorized': False, 'allow_order_send': False} (research-only: no Demo/Live, no order_send, no broker mutation)
- DEV_PARTITION: 2017-01-01T00:00:00+00:00 -> 2017-09-01T00:00:00+00:00 (DEVELOPMENT)
- OOS_PARTITION: 2017-09-01T00:00:00+00:00 -> 2017-12-01T00:00:00+00:00 (OOS)
- SEALED_HOLDOUT: [2017-12-01, 2018-01-01) — **HOLDOUT_TOUCHED: false** (structurally inaccessible: `slice_partition` fails closed)

## Datasets

| Symbol | Source | M1 rows | M15 bars | First | Last | SHA256 |
|---|---|---|---|---|---|---|
| EURUSD | HISTDATA_COM_ASCII_EURUSD_M1_2017.zip | 371635 | 24793 | 2017-01-02 07:00:00+00:00 | 2017-12-29 21:45:00+00:00 | `0dcd66dc67d7af4716404a5315d376ee1e7eaebe292afbda3c1003d2dfa16f57` |
| GBPUSD | HISTDATA_COM_ASCII_GBPUSD_M1_2017.zip | 371204 | 24757 | 2017-01-02 07:00:00+00:00 | 2017-12-29 21:45:00+00:00 | `e5ba3800e37fae0e326dbaa234952ca04e8f378c08b036530a2811206110c10b` |
| USDJPY | HISTDATA_COM_ASCII_USDJPY_M1_2017.zip | 371298 | 24731 | 2017-01-02 07:00:00+00:00 | 2017-12-29 21:45:00+00:00 | `477a1f515586f06d67cb75b3662260160e1e29e63c51804a30a5e7d69b09df5f` |
| XAUUSD | HISTDATA_COM_ASCII_XAUUSD_M1_2017.zip | 352360 | 23500 | 2017-01-02 23:00:00+00:00 | 2017-12-29 21:45:00+00:00 | `a39c1ccaaeb022c83309685107c9e619c2bcff8b2fd94fbd7405a721a4fe70ff` |

DATASET_HASHES:
- EURUSD: `0dcd66dc67d7af4716404a5315d376ee1e7eaebe292afbda3c1003d2dfa16f57`
- GBPUSD: `e5ba3800e37fae0e326dbaa234952ca04e8f378c08b036530a2811206110c10b`
- USDJPY: `477a1f515586f06d67cb75b3662260160e1e29e63c51804a30a5e7d69b09df5f`
- XAUUSD: `a39c1ccaaeb022c83309685107c9e619c2bcff8b2fd94fbd7405a721a4fe70ff`

## Lifecycle

- Stage reached: **FROZEN_FOR_OOS**
- CONTRACT_COMPLETE: PASS
- DEV_SCREEN_PASS: PASS
- FROZEN_FOR_OOS: PASS
- OOS_PASS: FAIL
- WALK_FORWARD_PASS: FAIL
- REGIME_PASS: FAIL
- STABILITY_PASS: N/A (single frozen parameter point)
- EDGE_VERIFIED: FAIL
- EDGE_VERIFIED is never reachable from DEV alone (see gate list).

## DEV Matrix (24 cells)

N = closed trades; net statistics are over closed trades only (OPEN_AT_END censored). C cells are DIAGNOSTIC_ONLY (C_FIXED_EXIT_PROXY) — never authoritative.

| Branch | Symbol | Session | N | Net R | Net Exp | Net PF | Win % | Max DD R | Friction R | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| A_SWEEP_REENTRY | EURUSD | ASIAN_LONDON | 68 | -24.8227 | -0.3650 | 0.6346 | 16.2% | 29.5514 | 13.4254 | FAILS_DEV_SCREEN |
| A_SWEEP_REENTRY | EURUSD | LONDON_NEWYORK | 72 | 6.2410 | 0.0867 | 1.1028 | 25.0% | 13.8971 | 9.2800 | SURVIVES_DEV_SCREEN |
| A_SWEEP_REENTRY | GBPUSD | ASIAN_LONDON | 62 | -24.4928 | -0.3950 | 0.5971 | 16.1% | 28.7118 | 10.4045 | FAILS_DEV_SCREEN |
| A_SWEEP_REENTRY | GBPUSD | LONDON_NEWYORK | 61 | 0.2534 | 0.0042 | 1.0049 | 22.9% | 9.8799 | 6.1969 | SURVIVES_DEV_SCREEN |
| A_SWEEP_REENTRY | USDJPY | ASIAN_LONDON | 80 | -33.5066 | -0.4188 | 0.5702 | 15.0% | 35.2448 | 11.3748 | FAILS_DEV_SCREEN |
| A_SWEEP_REENTRY | USDJPY | LONDON_NEWYORK | 87 | 9.4058 | 0.1081 | 1.1258 | 25.3% | 14.9999 | 13.0095 | SURVIVES_DEV_SCREEN |
| A_SWEEP_REENTRY | XAUUSD | ASIAN_LONDON | 50 | -19.4476 | -0.3890 | 0.6538 | 20.0% | 22.2242 | 19.6661 | FAILS_DEV_SCREEN |
| A_SWEEP_REENTRY | XAUUSD | LONDON_NEWYORK | 62 | 5.1316 | 0.0828 | 1.0833 | 30.6% | 19.2724 | 26.4714 | SURVIVES_DEV_SCREEN |
| B_RANGE_REJECTION | EURUSD | ASIAN_LONDON | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| B_RANGE_REJECTION | EURUSD | LONDON_NEWYORK | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| B_RANGE_REJECTION | GBPUSD | ASIAN_LONDON | 2 | -2.3561 | -1.1781 | 0.0000 | 0.0% | 2.3561 | 0.3561 | INSUFFICIENT_SAMPLE |
| B_RANGE_REJECTION | GBPUSD | LONDON_NEWYORK | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| B_RANGE_REJECTION | USDJPY | ASIAN_LONDON | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| B_RANGE_REJECTION | USDJPY | LONDON_NEWYORK | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| B_RANGE_REJECTION | XAUUSD | ASIAN_LONDON | 1 | -1.2389 | -1.2389 | 0.0000 | 0.0% | 1.2389 | 0.2389 | INSUFFICIENT_SAMPLE |
| B_RANGE_REJECTION | XAUUSD | LONDON_NEWYORK | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| C_TREND_EXPANSION | EURUSD | ASIAN_LONDON | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| C_TREND_EXPANSION | EURUSD | LONDON_NEWYORK | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| C_TREND_EXPANSION | GBPUSD | ASIAN_LONDON | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| C_TREND_EXPANSION | GBPUSD | LONDON_NEWYORK | 1 | 4.0515 | 4.0515 | inf | 100.0% | 0.0000 | 0.1985 | INSUFFICIENT_SAMPLE |
| C_TREND_EXPANSION | USDJPY | ASIAN_LONDON | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| C_TREND_EXPANSION | USDJPY | LONDON_NEWYORK | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| C_TREND_EXPANSION | XAUUSD | ASIAN_LONDON | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| C_TREND_EXPANSION | XAUUSD | LONDON_NEWYORK | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |

### DEV per-cell detail

| Branch | Symbol | Session | Sess | DataInv | Sig | Fill | Unfill | Exp | Open | Closed | W | L | BE | GrossR | NetR | GrossExp | NetExp | GrossPF | NetPF | Win% | AvgW | AvgL | MaxDD | LossStreak | 4R% | 5R% | BE% | HoldH | Freq | CostR | FrictR | Ambig | Authority | NoTradeReasons |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A_SWEEP_REENTRY | EURUSD | ASIAN_LONDON | 242 | 71 | 68 | 68 | 0 | 0 | 0 | 68 | 11 | 57 | 0 | -11.3974 | -24.8227 | -0.1676 | -0.3650 | 0.8000 | 0.6346 | 16.2% | 3.9192 | -1.1918 | 29.5514 | 19 | 16.2% | 16.2% | 0.0% | 1.56 | 1.959 | 0.1974 | 13.4254 | 1 | AUTHORITATIVE | NO_QUALIFYING_SETUP=13;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=60 |
| A_SWEEP_REENTRY | EURUSD | LONDON_NEWYORK | 242 | 69 | 72 | 72 | 0 | 0 | 0 | 72 | 18 | 54 | 0 | 15.5210 | 6.2410 | 0.2156 | 0.0867 | 1.2874 | 1.1028 | 25.0% | 3.7209 | -1.1247 | 13.8971 | 11 | 25.0% | 16.7% | 8.3% | 6.75 | 2.074 | 0.1289 | 9.2800 | 1 | AUTHORITATIVE | AMBIGUOUS_DUAL_SIDE_SWEEP=2;NO_QUALIFYING_SETUP=42;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=33 |
| A_SWEEP_REENTRY | GBPUSD | ASIAN_LONDON | 242 | 80 | 62 | 62 | 0 | 0 | 0 | 62 | 10 | 52 | 0 | -14.0883 | -24.4928 | -0.2272 | -0.3950 | 0.7291 | 0.5971 | 16.1% | 3.6297 | -1.1690 | 28.7118 | 14 | 16.1% | 9.7% | 6.5% | 6.18 | 1.786 | 0.1678 | 10.4045 | 0 | AUTHORITATIVE | AMBIGUOUS_DUAL_SIDE_SWEEP=1;NO_QUALIFYING_SETUP=11;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=61 |
| A_SWEEP_REENTRY | GBPUSD | LONDON_NEWYORK | 242 | 69 | 61 | 61 | 0 | 0 | 0 | 61 | 14 | 47 | 0 | 6.4503 | 0.2534 | 0.1057 | 0.0042 | 1.1372 | 1.0049 | 22.9% | 3.7001 | -1.0968 | 9.8799 | 8 | 22.9% | 14.8% | 8.2% | 12.94 | 1.757 | 0.1016 | 6.1969 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=56;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=29 |
| A_SWEEP_REENTRY | USDJPY | ASIAN_LONDON | 242 | 71 | 80 | 80 | 0 | 0 | 0 | 80 | 12 | 68 | 0 | -22.1319 | -33.5066 | -0.2766 | -0.4188 | 0.6745 | 0.5702 | 15.0% | 3.7048 | -1.1465 | 35.2448 | 23 | 15.0% | 10.0% | 5.0% | 4.59 | 2.305 | 0.1422 | 11.3748 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=44;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=22 |
| A_SWEEP_REENTRY | USDJPY | LONDON_NEWYORK | 242 | 69 | 87 | 87 | 0 | 0 | 0 | 87 | 22 | 65 | 0 | 22.4153 | 9.4058 | 0.2576 | 0.1081 | 1.3449 | 1.1258 | 25.3% | 3.8260 | -1.1502 | 14.9999 | 12 | 25.3% | 19.5% | 5.8% | 5.19 | 2.506 | 0.1495 | 13.0095 | 0 | AUTHORITATIVE | AMBIGUOUS_DUAL_SIDE_SWEEP=2;NO_QUALIFYING_SETUP=28;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=33 |
| A_SWEEP_REENTRY | XAUUSD | ASIAN_LONDON | 242 | 136 | 50 | 50 | 0 | 0 | 0 | 50 | 10 | 40 | 0 | 0.2185 | -19.4476 | 0.0044 | -0.3890 | 1.0055 | 0.6538 | 20.0% | 3.6728 | -1.4044 | 22.2242 | 7 | 20.0% | 16.0% | 4.0% | 4.77 | 1.440 | 0.3933 | 19.6661 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=29;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=12 |
| A_SWEEP_REENTRY | XAUUSD | LONDON_NEWYORK | 242 | 70 | 62 | 62 | 0 | 0 | 0 | 62 | 19 | 43 | 0 | 31.6031 | 5.1316 | 0.5097 | 0.0828 | 1.7350 | 1.0833 | 30.6% | 3.5143 | -1.4335 | 19.2724 | 9 | 30.6% | 24.2% | 6.5% | 4.82 | 1.786 | 0.4270 | 26.4714 | 0 | AUTHORITATIVE | AMBIGUOUS_DUAL_SIDE_SWEEP=1;NO_QUALIFYING_SETUP=23;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=54 |
| B_RANGE_REJECTION | EURUSD | ASIAN_LONDON | 242 | 71 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=13;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=60 |
| B_RANGE_REJECTION | EURUSD | LONDON_NEWYORK | 242 | 69 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | AUTHORITATIVE | AMBIGUOUS_DUAL_SIDE_SWEEP=2;NO_QUALIFYING_SETUP=42;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=33 |
| B_RANGE_REJECTION | GBPUSD | ASIAN_LONDON | 242 | 80 | 4 | 2 | 0 | 2 | 0 | 2 | 0 | 2 | 0 | -2.0000 | -2.3561 | -1.0000 | -1.1781 | 0.0000 | 0.0000 | 0.0% | — | -1.1781 | 2.3561 | 2 | 0.0% | 0.0% | 0.0% | 0.12 | 0.058 | 0.1781 | 0.3561 | 0 | AUTHORITATIVE | AMBIGUOUS_DUAL_SIDE_SWEEP=1;NO_QUALIFYING_SETUP=11;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=61 |
| B_RANGE_REJECTION | GBPUSD | LONDON_NEWYORK | 242 | 69 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=56;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=29 |
| B_RANGE_REJECTION | USDJPY | ASIAN_LONDON | 242 | 71 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=44;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=22 |
| B_RANGE_REJECTION | USDJPY | LONDON_NEWYORK | 242 | 69 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | AUTHORITATIVE | AMBIGUOUS_DUAL_SIDE_SWEEP=2;NO_QUALIFYING_SETUP=28;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=33 |
| B_RANGE_REJECTION | XAUUSD | ASIAN_LONDON | 242 | 136 | 3 | 1 | 0 | 2 | 0 | 1 | 0 | 1 | 0 | -1.0000 | -1.2389 | -1.0000 | -1.2389 | 0.0000 | 0.0000 | 0.0% | — | -1.2389 | 1.2389 | 1 | 0.0% | 0.0% | 0.0% | 0.50 | 0.029 | 0.2389 | 0.2389 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=29;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=12 |
| B_RANGE_REJECTION | XAUUSD | LONDON_NEWYORK | 242 | 70 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | AUTHORITATIVE | AMBIGUOUS_DUAL_SIDE_SWEEP=1;NO_QUALIFYING_SETUP=23;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=54 |
| C_TREND_EXPANSION | EURUSD | ASIAN_LONDON | 242 | 71 | 29 | 0 | 0 | 29 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | C_FIXED_EXIT_PROXY | NO_QUALIFYING_SETUP=13;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=60 |
| C_TREND_EXPANSION | EURUSD | LONDON_NEWYORK | 242 | 69 | 22 | 0 | 0 | 22 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | C_FIXED_EXIT_PROXY | AMBIGUOUS_DUAL_SIDE_SWEEP=2;NO_QUALIFYING_SETUP=42;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=33 |
| C_TREND_EXPANSION | GBPUSD | ASIAN_LONDON | 242 | 80 | 22 | 0 | 0 | 22 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | C_FIXED_EXIT_PROXY | AMBIGUOUS_DUAL_SIDE_SWEEP=1;NO_QUALIFYING_SETUP=11;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=61 |
| C_TREND_EXPANSION | GBPUSD | LONDON_NEWYORK | 242 | 69 | 25 | 1 | 0 | 24 | 0 | 1 | 1 | 0 | 0 | 4.2500 | 4.0515 | 4.2500 | 4.0515 | inf | inf | 100.0% | 4.0515 | — | 0.0000 | 0 | 100.0% | 100.0% | 0.0% | 0.25 | 0.029 | 0.1985 | 0.1985 | 1 | C_FIXED_EXIT_PROXY | NO_QUALIFYING_SETUP=56;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=29 |
| C_TREND_EXPANSION | USDJPY | ASIAN_LONDON | 242 | 71 | 24 | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | C_FIXED_EXIT_PROXY | NO_QUALIFYING_SETUP=44;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=22 |
| C_TREND_EXPANSION | USDJPY | LONDON_NEWYORK | 242 | 69 | 20 | 0 | 0 | 20 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | C_FIXED_EXIT_PROXY | AMBIGUOUS_DUAL_SIDE_SWEEP=2;NO_QUALIFYING_SETUP=28;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=33 |
| C_TREND_EXPANSION | XAUUSD | ASIAN_LONDON | 242 | 136 | 12 | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | C_FIXED_EXIT_PROXY | NO_QUALIFYING_SETUP=29;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=12 |
| C_TREND_EXPANSION | XAUUSD | LONDON_NEWYORK | 242 | 70 | 31 | 0 | 0 | 31 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | C_FIXED_EXIT_PROXY | AMBIGUOUS_DUAL_SIDE_SWEEP=1;NO_QUALIFYING_SETUP=23;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=54 |

## OOS Matrix (frozen DEV survivors only)

| Branch | Symbol | Session | N | Net R | Net Exp | Net PF | Win % | Max DD R | Friction R | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| A_SWEEP_REENTRY | EURUSD | ASIAN_LONDON | 30 | -0.5080 | -0.0169 | 0.9813 | 23.3% | 11.3319 | 5.9774 | FAILS_DEV_SCREEN |
| A_SWEEP_REENTRY | EURUSD | LONDON_NEWYORK | 34 | -6.9095 | -0.2032 | 0.7822 | 17.6% | 17.6982 | 4.4739 | FAILS_DEV_SCREEN |
| A_SWEEP_REENTRY | GBPUSD | ASIAN_LONDON | 19 | -3.3533 | -0.1765 | 0.8090 | 21.1% | 10.6402 | 3.2642 | INSUFFICIENT_SAMPLE |
| A_SWEEP_REENTRY | GBPUSD | LONDON_NEWYORK | 25 | -6.4487 | -0.2579 | 0.7220 | 16.0% | 10.5943 | 2.6096 | INSUFFICIENT_SAMPLE |
| A_SWEEP_REENTRY | USDJPY | ASIAN_LONDON | 24 | -18.8182 | -0.7841 | 0.2646 | 8.3% | 18.8182 | 3.9212 | INSUFFICIENT_SAMPLE |
| A_SWEEP_REENTRY | USDJPY | LONDON_NEWYORK | 28 | 13.1956 | 0.4713 | 1.5959 | 32.1% | 9.2009 | 4.8953 | INSUFFICIENT_SAMPLE |
| A_SWEEP_REENTRY | XAUUSD | ASIAN_LONDON | 19 | -10.6253 | -0.5592 | 0.5259 | 15.8% | 10.9517 | 7.5738 | INSUFFICIENT_SAMPLE |
| A_SWEEP_REENTRY | XAUUSD | LONDON_NEWYORK | 33 | -11.7410 | -0.3558 | 0.6814 | 21.2% | 15.6658 | 14.4767 | FAILS_DEV_SCREEN |
| B_RANGE_REJECTION | EURUSD | ASIAN_LONDON | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| B_RANGE_REJECTION | EURUSD | LONDON_NEWYORK | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| B_RANGE_REJECTION | GBPUSD | ASIAN_LONDON | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| B_RANGE_REJECTION | GBPUSD | LONDON_NEWYORK | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| B_RANGE_REJECTION | USDJPY | ASIAN_LONDON | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| B_RANGE_REJECTION | USDJPY | LONDON_NEWYORK | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| B_RANGE_REJECTION | XAUUSD | ASIAN_LONDON | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| B_RANGE_REJECTION | XAUUSD | LONDON_NEWYORK | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| C_TREND_EXPANSION | EURUSD | ASIAN_LONDON | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| C_TREND_EXPANSION | EURUSD | LONDON_NEWYORK | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| C_TREND_EXPANSION | GBPUSD | ASIAN_LONDON | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| C_TREND_EXPANSION | GBPUSD | LONDON_NEWYORK | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| C_TREND_EXPANSION | USDJPY | ASIAN_LONDON | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| C_TREND_EXPANSION | USDJPY | LONDON_NEWYORK | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| C_TREND_EXPANSION | XAUUSD | ASIAN_LONDON | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |
| C_TREND_EXPANSION | XAUUSD | LONDON_NEWYORK | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | INSUFFICIENT_SAMPLE |

### OOS per-cell detail

| Branch | Symbol | Session | Sess | DataInv | Sig | Fill | Unfill | Exp | Open | Closed | W | L | BE | GrossR | NetR | GrossExp | NetExp | GrossPF | NetPF | Win% | AvgW | AvgL | MaxDD | LossStreak | 4R% | 5R% | BE% | HoldH | Freq | CostR | FrictR | Ambig | Authority | NoTradeReasons |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A_SWEEP_REENTRY | EURUSD | ASIAN_LONDON | 90 | 31 | 30 | 30 | 0 | 0 | 0 | 30 | 7 | 23 | 0 | 5.4695 | -0.5080 | 0.1823 | -0.0169 | 1.2378 | 0.9813 | 23.3% | 3.8043 | -1.1799 | 11.3319 | 7 | 23.3% | 20.0% | 3.3% | 1.37 | 2.308 | 0.1992 | 5.9774 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=8;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=16 |
| A_SWEEP_REENTRY | EURUSD | LONDON_NEWYORK | 90 | 26 | 34 | 34 | 0 | 0 | 0 | 34 | 6 | 28 | 0 | -2.4356 | -6.9095 | -0.0716 | -0.2032 | 0.9130 | 0.7822 | 17.6% | 4.1348 | -1.1328 | 17.6982 | 11 | 17.6% | 17.6% | 0.0% | 4.02 | 2.615 | 0.1316 | 4.4739 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=14;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=8 |
| A_SWEEP_REENTRY | GBPUSD | ASIAN_LONDON | 90 | 31 | 19 | 19 | 0 | 0 | 0 | 19 | 4 | 15 | 0 | -0.0891 | -3.3533 | -0.0047 | -0.1765 | 0.9941 | 0.8090 | 21.1% | 3.5509 | -1.1704 | 10.6402 | 6 | 21.1% | 10.5% | 10.5% | 1.70 | 1.462 | 0.1718 | 3.2642 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=5;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=23 |
| A_SWEEP_REENTRY | GBPUSD | LONDON_NEWYORK | 90 | 26 | 25 | 25 | 0 | 0 | 0 | 25 | 4 | 21 | 0 | -3.8391 | -6.4487 | -0.1536 | -0.2579 | 0.8172 | 0.7220 | 16.0% | 4.1860 | -1.1044 | 10.5943 | 6 | 16.0% | 16.0% | 0.0% | 8.17 | 1.923 | 0.1044 | 2.6096 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=25;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=4 |
| A_SWEEP_REENTRY | USDJPY | ASIAN_LONDON | 90 | 34 | 24 | 24 | 0 | 0 | 0 | 24 | 2 | 22 | 0 | -14.8970 | -18.8182 | -0.6207 | -0.7841 | 0.3229 | 0.2646 | 8.3% | 3.3851 | -1.1631 | 18.8182 | 8 | 8.3% | 4.2% | 4.2% | 2.51 | 1.846 | 0.1634 | 3.9212 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=14;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=10 |
| A_SWEEP_REENTRY | USDJPY | LONDON_NEWYORK | 90 | 26 | 28 | 28 | 0 | 0 | 0 | 28 | 9 | 19 | 0 | 18.0909 | 13.1956 | 0.6461 | 0.4713 | 1.9522 | 1.5959 | 32.1% | 3.9265 | -1.1654 | 9.2009 | 8 | 32.1% | 28.6% | 3.6% | 5.54 | 2.154 | 0.1748 | 4.8953 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=14;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=14 |
| A_SWEEP_REENTRY | XAUUSD | ASIAN_LONDON | 90 | 45 | 19 | 19 | 0 | 0 | 0 | 19 | 3 | 16 | 0 | -3.0515 | -10.6253 | -0.1606 | -0.5592 | 0.8093 | 0.5259 | 15.8% | 3.9280 | -1.4006 | 10.9517 | 8 | 15.8% | 15.8% | 0.0% | 2.49 | 1.462 | 0.3986 | 7.5738 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=9;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=9 |
| A_SWEEP_REENTRY | XAUUSD | LONDON_NEWYORK | 90 | 26 | 33 | 33 | 0 | 0 | 0 | 33 | 7 | 26 | 0 | 2.7357 | -11.7410 | 0.0829 | -0.3558 | 1.1052 | 0.6814 | 21.2% | 3.5879 | -1.4176 | 15.6658 | 9 | 21.2% | 18.2% | 3.0% | 1.36 | 2.538 | 0.4387 | 14.4767 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=11;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=15 |
| B_RANGE_REJECTION | EURUSD | ASIAN_LONDON | 90 | 31 | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=8;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=16 |
| B_RANGE_REJECTION | EURUSD | LONDON_NEWYORK | 90 | 26 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=14;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=8 |
| B_RANGE_REJECTION | GBPUSD | ASIAN_LONDON | 90 | 31 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=5;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=23 |
| B_RANGE_REJECTION | GBPUSD | LONDON_NEWYORK | 90 | 26 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=25;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=4 |
| B_RANGE_REJECTION | USDJPY | ASIAN_LONDON | 90 | 34 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=14;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=10 |
| B_RANGE_REJECTION | USDJPY | LONDON_NEWYORK | 90 | 26 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=14;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=14 |
| B_RANGE_REJECTION | XAUUSD | ASIAN_LONDON | 90 | 45 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=9;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=9 |
| B_RANGE_REJECTION | XAUUSD | LONDON_NEWYORK | 90 | 26 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | AUTHORITATIVE | NO_QUALIFYING_SETUP=11;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=15 |
| C_TREND_EXPANSION | EURUSD | ASIAN_LONDON | 90 | 31 | 4 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | C_FIXED_EXIT_PROXY | NO_QUALIFYING_SETUP=8;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=16 |
| C_TREND_EXPANSION | EURUSD | LONDON_NEWYORK | 90 | 26 | 8 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | C_FIXED_EXIT_PROXY | NO_QUALIFYING_SETUP=14;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=8 |
| C_TREND_EXPANSION | GBPUSD | ASIAN_LONDON | 90 | 31 | 12 | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | C_FIXED_EXIT_PROXY | NO_QUALIFYING_SETUP=5;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=23 |
| C_TREND_EXPANSION | GBPUSD | LONDON_NEWYORK | 90 | 26 | 9 | 0 | 0 | 9 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | C_FIXED_EXIT_PROXY | NO_QUALIFYING_SETUP=25;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=4 |
| C_TREND_EXPANSION | USDJPY | ASIAN_LONDON | 90 | 34 | 8 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | C_FIXED_EXIT_PROXY | NO_QUALIFYING_SETUP=14;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=10 |
| C_TREND_EXPANSION | USDJPY | LONDON_NEWYORK | 90 | 26 | 6 | 0 | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | C_FIXED_EXIT_PROXY | NO_QUALIFYING_SETUP=14;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=14 |
| C_TREND_EXPANSION | XAUUSD | ASIAN_LONDON | 90 | 45 | 8 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | C_FIXED_EXIT_PROXY | NO_QUALIFYING_SETUP=9;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=9 |
| C_TREND_EXPANSION | XAUUSD | LONDON_NEWYORK | 90 | 26 | 4 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 | — | — | — | — | — | — | — | 0.0000 | 0 | — | — | — | — | 0.000 | — | 0.0000 | 0 | C_FIXED_EXIT_PROXY | NO_QUALIFYING_SETUP=11;SWEEP_STOP_DOES_NOT_PROTECT_EXTREME=15 |

## Aggregates (never hiding failing sub-cells)

### DEV

| Group | Label | N | Net R | Net Exp | Net PF | Win % | Max DD R | Friction R | Ambig |
|---|---|---|---|---|---|---|---|---|---|
| by_branch | A_SWEEP_REENTRY | 542 | -81.2379 | -0.1499 | 0.8412 | 21.4% | 91.1197 | 109.8285 | 2 |
| by_branch | B_RANGE_REJECTION | 3 | -3.5950 | -1.1983 | 0.0000 | 0.0% | 3.5950 | 0.5950 | 0 |
| by_branch | C_TREND_EXPANSION | 1 | 4.0515 | 4.0515 | inf | 100.0% | 0.0000 | 0.1985 | 1 |
| by_symbol | EURUSD | 140 | -18.5817 | -0.1327 | 0.8556 | 20.7% | 31.7734 | 22.7054 | 2 |
| by_symbol | GBPUSD | 126 | -22.5440 | -0.1789 | 0.8034 | 19.8% | 30.5970 | 17.1560 | 1 |
| by_symbol | USDJPY | 167 | -24.1008 | -0.1443 | 0.8422 | 20.4% | 44.7344 | 24.3843 | 0 |
| by_symbol | XAUUSD | 113 | -15.5548 | -0.1377 | 0.8693 | 25.7% | 22.2242 | 46.3764 | 0 |
| by_session | ASIAN_LONDON | 263 | -105.8648 | -0.4025 | 0.6027 | 16.4% | 107.8384 | 55.4657 | 1 |
| by_session | LONDON_NEWYORK | 283 | 25.0835 | 0.0886 | 1.1009 | 26.2% | 19.2724 | 55.1563 | 2 |
| combined | ALL | 546 | -80.7814 | -0.1480 | 0.8432 | 21.4% | 91.1197 | 110.6220 | 3 |

### OOS

| Group | Label | N | Net R | Net Exp | Net PF | Win % | Max DD R | Friction R | Ambig |
|---|---|---|---|---|---|---|---|---|---|
| by_branch | A_SWEEP_REENTRY | 212 | -45.2084 | -0.2132 | 0.7812 | 19.8% | 48.0434 | 47.1922 | 0 |
| by_branch | B_RANGE_REJECTION | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | 0 |
| by_branch | C_TREND_EXPANSION | 0 | 0.0000 | — | — | — | 0.0000 | 0.0000 | 0 |
| by_symbol | EURUSD | 64 | -7.4175 | -0.1159 | 0.8740 | 20.3% | 19.1681 | 10.4514 | 0 |
| by_symbol | GBPUSD | 44 | -9.8020 | -0.2228 | 0.7595 | 18.2% | 10.6402 | 5.8738 | 0 |
| by_symbol | USDJPY | 52 | -5.6226 | -0.1081 | 0.8822 | 21.1% | 25.1529 | 8.8165 | 0 |
| by_symbol | XAUUSD | 52 | -22.3663 | -0.4301 | 0.6226 | 19.2% | 22.3663 | 22.0505 | 0 |
| by_session | ASIAN_LONDON | 92 | -33.3048 | -0.3620 | 0.6407 | 17.4% | 36.4662 | 20.7367 | 0 |
| by_session | LONDON_NEWYORK | 120 | -11.9036 | -0.0992 | 0.8955 | 21.7% | 21.5661 | 26.4555 | 0 |
| combined | ALL | 212 | -45.2084 | -0.2132 | 0.7812 | 19.8% | 48.0434 | 47.1922 | 0 |
| gate | FROZEN_DEV_SURVIVORS | 120 | -11.9036 | -0.0992 | 0.8955 | 21.7% | 21.5661 | 26.4555 | 0 |

### OOS promotion gate (frozen DEV survivors only)

- closed trades: 120
- net R: -11.9036
- net expectancy: -0.0992 (bootstrap 90% CI [-0.4681, 0.2948])
- net profit factor: 0.8955
- max drawdown: 21.5661 R
- GATE RESULT: FAIL

## Headline economics (DEV, authoritative cells pooled incl. failing ones)

- AGGREGATE_NET_R: -80.7814
- AGGREGATE_EXPECTANCY (net R/trade): -0.1480  (bootstrap 90% CI [-0.3112, 0.0302])
- AGGREGATE_PF (net): 0.8432
- MAX_DRAWDOWN_R: 91.1197
- TOTAL_FRICTION_R: 110.6220

## Cell classifications

- CELLS_TO_FREEZE_FOR_OOS (4): ['A_SWEEP_REENTRY/EURUSD/LONDON_NEWYORK', 'A_SWEEP_REENTRY/GBPUSD/LONDON_NEWYORK', 'A_SWEEP_REENTRY/USDJPY/LONDON_NEWYORK', 'A_SWEEP_REENTRY/XAUUSD/LONDON_NEWYORK']
- REJECTED (4): ['A_SWEEP_REENTRY/EURUSD/ASIAN_LONDON', 'A_SWEEP_REENTRY/GBPUSD/ASIAN_LONDON', 'A_SWEEP_REENTRY/USDJPY/ASIAN_LONDON', 'A_SWEEP_REENTRY/XAUUSD/ASIAN_LONDON']
- INSUFFICIENT_SAMPLE (16): ['B_RANGE_REJECTION/EURUSD/ASIAN_LONDON', 'B_RANGE_REJECTION/EURUSD/LONDON_NEWYORK', 'B_RANGE_REJECTION/GBPUSD/ASIAN_LONDON', 'B_RANGE_REJECTION/GBPUSD/LONDON_NEWYORK', 'B_RANGE_REJECTION/USDJPY/ASIAN_LONDON', 'B_RANGE_REJECTION/USDJPY/LONDON_NEWYORK', 'B_RANGE_REJECTION/XAUUSD/ASIAN_LONDON', 'B_RANGE_REJECTION/XAUUSD/LONDON_NEWYORK', 'C_TREND_EXPANSION/EURUSD/ASIAN_LONDON', 'C_TREND_EXPANSION/EURUSD/LONDON_NEWYORK', 'C_TREND_EXPANSION/GBPUSD/ASIAN_LONDON', 'C_TREND_EXPANSION/GBPUSD/LONDON_NEWYORK', 'C_TREND_EXPANSION/USDJPY/ASIAN_LONDON', 'C_TREND_EXPANSION/USDJPY/LONDON_NEWYORK', 'C_TREND_EXPANSION/XAUUSD/ASIAN_LONDON', 'C_TREND_EXPANSION/XAUUSD/LONDON_NEWYORK']
- BLOCKED (0): —
- DIAGNOSTIC_ONLY (proxy, never authoritative) (8): ['C_TREND_EXPANSION/EURUSD/ASIAN_LONDON', 'C_TREND_EXPANSION/EURUSD/LONDON_NEWYORK', 'C_TREND_EXPANSION/GBPUSD/ASIAN_LONDON', 'C_TREND_EXPANSION/GBPUSD/LONDON_NEWYORK', 'C_TREND_EXPANSION/USDJPY/ASIAN_LONDON', 'C_TREND_EXPANSION/USDJPY/LONDON_NEWYORK', 'C_TREND_EXPANSION/XAUUSD/ASIAN_LONDON', 'C_TREND_EXPANSION/XAUUSD/LONDON_NEWYORK']

## Branch verdicts

- BRANCH_A_VERDICT (A_SWEEP_REENTRY): REJECT (fails OOS)
- BRANCH_B_VERDICT (B_RANGE_REJECTION): RESEARCH_ONLY (insufficient sample across all cells)
- BRANCH_C_VERDICT (C_TREND_EXPANSION): RESEARCH_ONLY (diagnostic proxy only — C runner management is not deterministically defined in the frozen source)

## Supplementary stages

- walk_forward: FAIL
- regime: REPORTED

## Provenance

- FILES_CHANGED: ['artifacts/session_trade_v2_economic_matrix/', 'scripts/run_stv2_campaign.py', 'src/ag_edgelab/campaigns/session_trade_v2/ (campaign package)', 'tests/test_stv2_*.py (focused suites)']
- TESTS_RUN: pytest -q (full suite incl. tests/test_stv2_*.py focused suites)
- TEST_RESULTS: full suite: 220 passed in 9.21s
STV2 focused suites: 97 passed in 1.01s
- ARTIFACT_PATHS: ['artifacts/session_trade_v2_economic_matrix/dev_result.json', 'artifacts/session_trade_v2_economic_matrix/oos_result.json', 'artifacts/session_trade_v2_economic_matrix/supplementary.json', 'artifacts/session_trade_v2_economic_matrix/supplementary_detail.json', 'artifacts/session_trade_v2_economic_matrix/ledger.jsonl', 'artifacts/session_trade_v2_economic_matrix/final_report.md', 'artifacts/session_trade_v2_economic_matrix/final_report.json', 'artifacts/session_trade_v2_economic_matrix/dataset_quality_reports.json']
- COMMIT_SHA: `e62746c35ac5a231e79366eb2d1b495b33ae43e2`
- PR_NUMBER: —

## Follow-up hypotheses (NEW candidates only — V2 stays frozen)

1. C_TREND_EXPANSION: replace the undefined 'confirmed M15 swing' runner trail with a broken-boundary retest exit (new candidate; V2 itself stays frozen)
2. B_RANGE_REJECTION: require stronger rejection confirmation (e.g. wick-ratio or consecutive closes back inside the box) before the limit is placed
3. A_SWEEP_REENTRY: add a minimum sweep-penetration filter (wick must exceed a fraction of R0 beyond the box extreme)
4. HTF regime filter: gate all branches on an H1/H4 trend or range regime state
5. Volatility filter: skip sessions whose reference range A is in the extreme tails of its rolling distribution

## Known limitations / blockers

- C_TREND_EXPANSION runner management ('confirmed M15 swings' trail, 5R cap) is NOT deterministically defined in the frozen source: C cells run C_FIXED_EXIT_PROXY (diagnostic-only, never authoritative).
- USDJPY friction has no VT Markets-published spread; cross-broker evidence band used with the 1.25x/1.5x stress grid.
- Parameter stability is N/A: single frozen parameter point.
- Supplementary detail (walk-forward folds, regime slices): artifacts/session_trade_v2_economic_matrix/supplementary_detail.json
- Ledger freeze (EdgeLab CandidateRecord per symbol): artifacts/session_trade_v2_economic_matrix/ledger.jsonl

NEXT_RECOMMENDED_ACTION: Survivors failed the OOS gate: reject those cells; no promotion. Pursue FOLLOW_UP_HYPOTHESES as new candidates.
