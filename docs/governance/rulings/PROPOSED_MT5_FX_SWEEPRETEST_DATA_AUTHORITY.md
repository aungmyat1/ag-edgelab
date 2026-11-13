# PROPOSED_MT5_FX_SWEEPRETEST_DATA_AUTHORITY

## Conflict

The requested MT5 window for `FX_SweepRetest_V2_Research` is 2025-11-13 through 2026-11-13, with the requested role `DEVELOPMENT`. The authoritative `config/governance/data_authority_gap.json` defines the approved FX authorities as HistData ASCII M1 through 2017, with DEVELOPMENT partitions `[YYYY-01-01, YYYY-09-01)` for each admitted year. It requires a source manifest, pinned raw hashes, timezone and bar convention, gap and duplicate accounting, causal resampling, and preregistered dataset partitions. The requested dates are outside that authority. MT5 broker history has not been registered as a dataset and cannot be presumed to be DEVELOPMENT.

The V2 EA also returns before order placement on every signal, regardless of `InpEnableTesterOrders`. Its code can log signal events but cannot produce trades or trade-based performance metrics in MT5 as written. Its package documentation records no approved tester runs and calls the bundled date settings unauthorized examples.

## Options

1. Keep the run blocked. Use an already-authorized DEVELOPMENT partition for which the symbol and required data are available, after verifying the exact contract and instrument mapping.
2. Establish a separate MT5 data authority before any replay: specify broker/server, exact terminal symbol, account/feed identity, raw history export and hashes, UTC and bar conventions, completeness/gap policy, DEVELOPMENT/OOS/holdout partitions, and register the dataset. Do not reuse the requested recent window as DEVELOPMENT until that authority is approved.
3. If the intended result is only a signal-count diagnostic, explicitly authorize a signal-only run on a newly registered data source and report signal counts without trade metrics. A trade backtest additionally requires a separately versioned EA implementation whose order path is enabled for research simulation under the applicable governance; do not alter the V2 source under its existing identity.

## Recommendation

Keep the requested run blocked pending resolution of data authority and the intended output (signal count versus trade backtest). Do not open terminal history for the requested dates under a DEVELOPMENT label. Preserve the V2 EA identity and source bytes.

## Status

PROPOSAL ONLY — no owner ruling, dataset registration, terminal history access, compilation, or backtest has occurred.
