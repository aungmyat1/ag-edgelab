# FX_SweepRetest_V2_Research — Minimum MT5 Backtest Requirements

**Status:** PREPARATION ONLY. NOT READY. Requested window 2025-11-13 → 2026-11-13, requested role DEVELOPMENT (unapproved).
**Frozen identities (from uploaded package):**

| Artifact | SHA-256 |
| --- | --- |
| Experts/FX_SweepRetest_Research.mq5 (v2.00) | be1695b387a7da825d1077f2a6adb63d7c9df5b1c8616f56e6e55207bf3639b1 |
| Presets/FX_SweepRetest_Research.set | 45ca412ee2275fb726bdff891a03883d4f3ac4f442e92fe259dc0ea559760d07 |
| Tester/FX_SweepRetest_Research.ini (UNAUTHORIZED example, 2026.10.01–10.31) | 470cf8c32f245061f32f689a40229b44224504588c75baa7d9821eb2971c30bd |

## 1. What the EA can and cannot do (verified by reading the source)
- Tester-only: `OnInit` fails outside `MQL_TESTER`.
- Signal = M5, completed bar `r[1]` sweeps the min/max of bars `r[2]..r[InpLookbackBars+1]` and closes back inside with a same-direction body. Long = +1, short = −1.
- Evaluated once per new M5 bar (when `iTime(M5,0)` changes). Logged timestamp is the **open time of the forming bar**, i.e. the bar after the signal bar. Signal bar open = logged time − 5 min.
- Output: journal line `RESEARCH_SIGNAL,<symbol>,<YYYY.MM.DD HH:MM>,<+1|-1>,NO_EDGE_CLAIM`.
- If `InpEnableTesterOrders=true` it prints `V2_ORDER_BLOCKED_UNVERIFIED_GATES` and returns. Everything after (spread check, lot check, SL/TP, `Buy`/`Sell`) is unreachable. **No trades are ever produced.**
- `InpFastMAPeriod` unused; `InpSlowMAPeriod` only affects validation and the history-copy size (`need = max(Lookback+5, Slow+5)`; default 41 bars). `InpMaxSpreadPoints/Fixed lots/Stop/Target` are inert.
- No session, news, rollover, Friday-flat, risk guard or de-duplication logic exists (those are specification-only in `EDGE_VERIFICATION_REQUIREMENTS.md`).

**Consequence:** the only runnable deliverable is a **signal-count diagnostic**. Report counts, long/short split, per-hour/per-weekday distribution. No PF, drawdown, expectancy, win rate or edge claim.

## 2. Minimum requirements — SIGNAL_ONLY run (all must be evidenced)
| # | Requirement | Evidence file |
|---|---|---|
| R1 | Owner-approved registration of the MT5 history as a **new** dataset (not HistData) | gov/manifest_tpl.json (filled, hashed) |
| R2 | Owner classification of the exact window + frozen DEV/OOS/SEALED_HOLDOUT boundaries; prior-exposure disclosure; OOS/holdout stay closed | gov/partition_tpl.json |
| R3 | Terminal/server/account type (no credentials), build, exact symbol (`EURUSD-VIP`) verified present and bound to manifest | manifest `terminal`, `symbol` blocks |
| R4 | Frozen test contract: source hash, .set hash, symbol, M5, date endpoint semantics, model, deposit/currency/leverage, build, report name; Optimization=0, Visual=0, Forward=0, tester only | gov/contract_tpl.json |
| R5 | Preregistration committed **before** the run | gov/prereg_tpl.md |
| R6 | Compile evidence: compiler version/log and `.ex5` SHA-256 (package has never been compiled) | out/compile_log + ex5 hash in contract |
| R7 | Output bundle: tester journal, tester config actually used, signal CSV, counts summary, hashes | tools/parse_signals.py output |
| R8 | Labels: result marked `SIGNAL_COUNT_DIAGNOSTIC`, `ECONOMIC_METRICS=NOT_ESTIMABLE`, `EDGE_CLAIM=NONE` | summary JSON |

### MT5 tester settings to freeze (owner decisions marked)
- `Symbol=EURUSD-VIP`, `Period=M5`, `Optimization=0`, `ForwardMode=0`, `Visual=0`, `UseCloud=0`, `ExecutionMode` pinned.
- **Model:** the signal uses completed M5 bars only, so `Model=1` (1-minute OHLC) reproduces bar signals with far less tick-history dependency than `Model=4` (real ticks, the draft INI value). Owner decides; whichever is chosen must be frozen and recorded. Real ticks requires complete tick history for the whole window or the run is invalid.
- **Date endpoints:** the requested end date 2026-11-13 is *today*, so that day is incomplete. Recommended: freeze the end at the last fully closed day (e.g., `2026.11.12`) and record how MT5 treats `ToDate` (documented behavior: tester runs through the end date; verify by the last journal timestamp).
- `Deposit/Currency/Leverage`: irrelevant to signal counts but must be frozen anyway; the draft's `Deposit=1025` is an unexplained value, not an approved one.
- Broker time vs UTC: tester timestamps are in **broker server time**. Record offset/DST rule in the manifest and convert in the parser before any hour-of-day analysis.

## 3. Data quality checks to run on the exported history (before signals are counted)
1. Bar-open convention (MT5 = bar open time) and server-time→UTC rule incl. DST transitions (March and Oct/Nov 2026 shifts).
2. Missing M5 bars on trading days; duplicates; zero-range or non-monotonic bars; weekend/holiday gaps listed separately.
3. SHA-256 of the raw export file(s); row counts; first/last bar.
4. Tester "history quality"/synchronization percentage recorded from the tester log.

## 4. Gates before any economic claim (not requested now)
Resolve `FRICTION_VENUE`; bind spread/commission/slippage/swap evidence to the dated venue; unknown = unavailable, never zero; preregister metrics, sample floors, uncertainty method, stress cases; recompute metrics from canonical trade records (tester summary is informational only).

## 5. Governance reminders
- Do not edit V2 under its identity; any behavior change = new identity + preregistration.
- Do not tune parameters on this window after seeing results. Do not reuse the burned V123 holdout.
- Do not reuse the bundled INI dates (2026-10-01..31): unauthorized.

## 6. Trade backtest — separate successor required (not generated here)
A new versioned EA (e.g., `FX_SweepRetest_V3_Research`) with a deterministic tester-only order path must freeze: entry timing/fill semantics (next-bar open? spread side), SL/TP/exit, sizing, concurrency/one-position rule, duplicate-signal handling, session/news/rollover/Friday rules actually implemented, symbol tick size/value/contract size/volume limits/stops & freeze levels, deposit-currency conversion, tester-only execution guard, full trade ledger export, `.ex5` hash + compiler log. Candidate policy inputs already proposed in `PROPOSED_EDGE_PROFILE.json` (0.25% risk, 06–11/12–16 UTC windows, 21–23 UTC rollover blackout, ±15 min tier‑1 news, Friday 15:00 UTC flat) are **unapproved hypotheses**. Say the word and I can draft the successor specification (spec only, no code under V2's identity).

## 7. Owner decisions
See DECISIONS_PROPOSED.md: items 1, 2 (boundaries), 4, 6 are adopted as PROPOSED values; items marked STILL REQUIRED remain open.

Original list:
1. Signal-count only now, or authorize drafting a trade-capable successor?
2. Approve/reject registering 2025‑11‑13→2026‑11‑13 MT5 history as new DEVELOPMENT dataset; provide partition boundaries and exposure disclosure.
3. VT terminal/server/account type/exact symbol mapping (no credentials).
4. Tester model (1 vs 4) and end-date semantics.
5. `FRICTION_VENUE` (only needed for economic claims).
6. Retain V2 parameters verbatim in the contract (default recommendation: yes, unchanged).
