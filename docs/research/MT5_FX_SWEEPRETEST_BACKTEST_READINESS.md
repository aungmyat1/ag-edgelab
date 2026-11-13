# MT5 FX SweepRetest Backtest Readiness

**Status:** PREPARATION ONLY — backtest blocked pending the gates below.
**Requested scope:** FX SweepRetest research proxy, requested dates 2025-11-13 through 2026-11-13, intended role DEVELOPMENT.
**Strategy source:** `strategies/FX_SweepRetest_V2_Research/Experts/FX_SweepRetest_Research.mq5`
**Source SHA-256 at preparation:** `be1695b387a7da825d1077f2a6adb63d7c9df5b1c8616f56e6e55207bf3639b1`

Reference artifact hashes (the bundled INI remains an unauthorized example):

| Artifact | SHA-256 |
| --- | --- |
| `Presets/FX_SweepRetest_Research.set` | `45ca412ee2275fb726bdff891a03883d4f3ac4f442e92fe259dc0ea559760d07` |
| `Tester/FX_SweepRetest_Research.ini` (audit reference only) | `470cf8c32f245061f32f689a40229b44224504588c75baa7d9821eb2971c30bd` |

## Current findings

- The project data authority registers HistData FX history through 2017. The requested 2025–2026 dates are outside its declared DEVELOPMENT partitions.
- MT5 history for the requested dates has not been registered with source provenance, raw hashes, time/bar conventions, completeness checks, or DEVELOPMENT/OOS/holdout partitions. The date range cannot be treated as DEVELOPMENT by assumption.
- The selected EA is explicitly a simplified research proxy, not the canonical FX strategy. Its signal is an M5 sweep/reversal check over completed bars. It does not implement the proposed session, news, risk guard, or strategy parity requirements.
- The EA prints `RESEARCH_SIGNAL`, then returns before any order creation. The order path remains blocked even if `InpEnableTesterOrders=true`; therefore the current EA can only support a signal-count diagnostic, not a trade backtest.
- `InpFastMAPeriod` does not participate in signal selection. `InpSlowMAPeriod` is used for input validation/history warmup only. The spread check and fixed SL/TP order path are after the unconditional return and are unreachable.
- The bundled `.ini` period (2026-10-01 to 2026-10-31) is explicitly an unauthorized example. Do not reuse it.
- Existing governance leaves `FRICTION_VENUE` unresolved. No net performance or edge claim is supported without an approved, period-compatible friction authority.
- Two `terminal64.exe` processes were observed on this Windows host. `docs/friction_authority_capture.md` says there is no MT5 terminal in its described sandbox. This environment/documentation difference is recorded here for review; it does not establish the terminal server, account type, symbol mapping, or available history.

## Gates before a signal-count diagnostic

1. **Owner-approved dataset authority:** Register the MT5 source as a new dataset before reading/running the requested period. Record broker entity, server, account type (never credentials), terminal build, exact terminal symbol, source and retrieval method, UTC conversion and bar-open convention, raw export hashes, gaps/duplicates/completeness, and license/retention notes.
2. **Partition and exposure record:** Owner must classify the exact window and freeze DEVELOPMENT/OOS/SEALED_HOLDOUT boundaries before evaluation. Record prior exposure and the candidate identity in the appropriate append-only governance records. Keep OOS and holdout closed for this DEVELOPMENT run.
3. **Symbol resolution:** Verify `EURUSD-VIP` exists in the selected terminal and bind it to the dataset manifest. The canonical HistData symbol `EURUSD` is not automatically equivalent to the VT terminal symbol.
4. **Frozen test contract:** Pin the source hash above, parameter `.set` hash, symbol, M5 timeframe, date endpoint semantics, tester model, deposit/currency/leverage settings, terminal build, and report name before run. Disable optimization and visual/live execution. The test must be Strategy Tester only.
5. **Signal-only deliverables:** Preserve the tester journal, complete signal event output, tester configuration, data manifest, source hash and report. Report signal counts only; do not report trade expectancy, PF, drawdown, or edge from a zero-trade run.

## Additional gates for a trade backtest

A trade backtest requires a separately versioned EA identity (do not edit V2 while retaining its identity) with a deterministic, tester-only order path. That successor specification must freeze:

- signal and entry timing/fill semantics, including spread side, gaps, rejected fills, and duplicate-signal handling;
- stop/target and exit behavior, sizing, one-position/concurrency rules, and session/calendar rules actually implemented;
- symbol-specific tick size/value, point/digits, contract size, volume limits/step, stop/freeze levels, and deposit-currency conversion;
- tester-only execution guard and proof that no broker/demo/live order path is reachable;
- complete candidate/trade ledger and deterministic result export;
- compiled `.ex5` hash, compiler version/log, source hash, `.set`/`.ini`, tester journal, report, and trade list.

The current V2 values (`0.01` fixed lots, 300-point stop, 450-point target, 24-bar lookback) are code defaults, not approved risk or performance policy. The spread gate and order code are unreachable. Do not silently activate them or infer their intended semantics. Any changed behavior needs a new identity and preregistration.

## Gates before an economic claim

1. Resolve owner decision `FRICTION_VENUE`: broker/server, account type, exact terminal symbol mapping, and authoritative sources for spread, commission, slippage, swap/financing, and partial exits.
2. Bind friction evidence to the evaluated dates and venue. MT5 quote history may support historical spread only if the raw bid/ask data is complete and hashed; it does not by itself establish historical commission or slippage. Unknown components stay unavailable, never zero.
3. Preregister the analysis before replay: hypothesis, immutable strategy/data identities, exact window, cost treatment, primary metrics, sample floors, uncertainty method, stress cases, and stopping/promotion rules. Do not optimize on this one-year window after seeing results.
4. Recompute metrics from the canonical trade/evidence records. Tester summary metrics alone are informational, not EdgeLab verification authority.

## Owner decisions still required

- Confirm whether the desired immediate output is **signal counts only** or a **trade backtest**. The latter requires a separately versioned EA successor.
- Approve or reject registration of the 2025-11-13 to 2026-11-13 MT5 history as a new DEVELOPMENT dataset, with exact partition boundaries and exposure disclosure.
- Identify the selected VT terminal/server, account type, and exact symbol mapping (no credentials).
- Resolve `FRICTION_VENUE` before any net/economic claim; otherwise results must be labeled gross/diagnostic and `ECONOMIC_METRICS=NOT_ESTIMABLE`.
- Decide whether to retain V2's declared parameter values in a new test contract or define a new version. No parameter changes are authorized by this readiness note.

## Run acceptance checklist

A run is ready only when every applicable item is evidenced and pinned:

- [ ] Owner-approved dataset registration and manifest hash
- [ ] Exact DEV/OOS/holdout boundaries recorded; requested window confirmed as DEV
- [ ] Prior-exposure and candidate identity recorded append-only
- [ ] Broker/server/account type and exact symbol mapping established
- [ ] Strategy identity and source/parameter hashes frozen
- [ ] Signal-only versus trade-backtest scope selected
- [ ] If trading: separate EA successor, tester-only path, and deterministic fill/risk contract frozen
- [ ] Tester build/model/date endpoint/deposit/currency/leverage frozen
- [ ] Friction authority and date compatibility established for economic reporting, or metrics explicitly marked not estimable
- [ ] Preregistration committed before the run
- [ ] OOS and SEALED_HOLDOUT remain unopened
- [ ] Output bundle plan includes logs, configuration, data/strategy hashes, trade or signal events, and report

**Current result:** NOT READY. No MT5 history was opened, no compile or tester run occurred, and the V2 source was not changed.
