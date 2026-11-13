# LSMC — Edge verification requirements (PROPOSED / NOT IMPLEMENTED)

This document captures user-supplied candidate constraints for future preregistration. No statistical edge is verified. It does not authorize tests, modify the EA, or replace canonical project rules.

## Eligible universe
Proposed symbols: EURUSD-VIP, GBPUSD-VIP, USDJPY-VIP, XAUUSD-VIP, BTCUSD, ETHUSD.
AUDUSD-VIP is not in the current project whitelist and is EXCLUDED pending separate admission and owner approval. Gold requires its own tick-value/lot-size/stops/spread constraints; crypto requires separate venue feed and weekend/exposure models.

## Candidate operational windows
Canonical LSMC context/session expiry must control; suggested London 06:00–11:00 and New York 12:00–16:00 are unapproved changes.
Suggested rollover blackout 21:00–23:00 UTC is NOT a broker-verified invariant; account for DST, symbol trading calendars and broker server time. Proposed Tier-1 news entry blackout: 15 minutes before through 15 minutes after each event, only when a complete trusted timestamped calendar is available; missing calendar must fail closed if news gate is mandatory. Suggested FX Friday flat deadline 15:00 UTC is a NEW RULE requiring explicit owner decision, conflict review and safe close handling; do not assume it applies to crypto.

## Proposed risk controls (not implemented by this package)
- PortfolioGuard, demo-only, account-wide exposure, max entries and daily/weekly loss stops must be inherited from the current canonical governance. Do not silently change existing limits.
- Per-trade risk candidate 0.25% equity; 1% is NOT an approved default. Compute using tick value, tick size, volume step, contract size, currency conversion, commissions and worst-case slippage; reject if the minimum lot breaches cap.
- Every trade requires valid stop loss and take profit before placement, broker stops/freeze checks, and spread-to-stop/slippage-to-stop checks; reject missing broker metadata.
- Crypto weekend size-halving and correlated BTC/ETH exposure restrictions are hypotheses requiring explicit limits and independent tests; do not apply without authorization.
- For each gate, log evaluated timestamp, input provenance, allow/deny decision, and reason. Unknown inputs => deny.

## Evidence and statistical gates
- Freeze a versioned preregistration with strategy ID, source hash, data hashes, timeframe, costs, UTC conversion, symbol, hypothesis, parameter bounds and designated DEV/VAL/HOLD periods BEFORE any run.
- Compute trade expectancy E = p(win)*mean(win R) - p(loss)*mean(loss R), net of spread, commissions, slippage and swaps, with confidence intervals and clustered sampling. Positive sample expectancy alone is not proof.
- Report PF, drawdown, tail losses, clusters, sample sizes, per-symbol/per-regime stability, exposure, largest-win concentration, costs and sensitivity under widened spreads and slippage.
- Walk-forward validation must respect chronology; untouched holdout must be used once under preregistration. Do not tune after OOS disclosure or reuse burned windows.
- Run negative tests: absent news feed, DST shift, rollover, Friday boundary, broker holiday, extreme spread, minimum lot violation, stop rejection, quote gaps, missing tick value, order rejection and power/restart recovery.
- Require independent MQL5/offline signal parity and execution reproducibility; archived reports, tester journal, exact .set/.ini, terminal .ex5 hash and compiler log.
- Preserve project-specific gates (e.g., PF >= 1.30 research, stricter promotion threshold if adopted); a threshold is necessary but never sufficient.

## Current blocker
Supplied prototype is a moving-average sweep proxy, NOT the canonical LSMC; earlier LSMC look-ahead concerns unresolved.

## Implementation status
ALL new window/news/weekend/Friday-flat/account risk additions in this document: SPECIFICATION ONLY. Existing .mq5/.set/.ini in this ZIP are unchanged, uncompiled prototypes with order placement disabled by default. No authorized Tester run or performance evidence.
