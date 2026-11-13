# Decisions adopted from recommendations — PENDING OWNER SIGN-OFF
Adopting these is a proposal until the owner signs the governance records. Nothing below is an approved ruling.

| Decision | Adopted value | Basis |
| --- | --- | --- |
| Scope | SIGNAL_ONLY (no trade backtest, no successor EA) | V2 cannot place orders by design |
| Symbol | EURUSD-VIP, M5 | requested; equivalence to HistData EURUSD still to be verified in the terminal |
| Tester model | Model=1 (1-minute OHLC) | signals use completed M5 bars only; no tick-history dependency |
| Window requested | 2025-11-13 → 2026-11-12 (last fully closed day; 11-13 is incomplete) | |
| DEVELOPMENT (this run) | 2025-11-13 → 2026-08-31 | mirrors the project's Sep-1 DEVELOPMENT cut convention |
| OOS (closed) | 2026-09-01 → 2026-09-30 | untouched |
| SEALED_HOLDOUT (closed) | 2026-10-01 → 2026-11-12 | untouched; contains the October 2026 dates named in the unauthorized draft INI (named, never run) |
| Parameters | V2 `.set` verbatim | no tuning |
| Terminal / server / account type / build | **STILL REQUIRED FROM OWNER** | cannot be inferred; run `mql5/ExportHistory.mq5` to capture them (no credentials) |
| Time conversion | **STILL REQUIRED** broker server-time → UTC rule incl. DST | |
| FRICTION_VENUE | unresolved; economics stay NOT_ESTIMABLE | |

Only the DEVELOPMENT partition is run. The tester window is therefore `2025.11.13`–`2026.08.31`.
Owner must still record approval (name/date) in the manifest and partition record.
