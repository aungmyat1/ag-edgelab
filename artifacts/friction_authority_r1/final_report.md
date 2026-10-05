# FRICTION_AUTHORITY_R1 — final report

- **Venue**: VT_MARKETS
- **Account class**: UNKNOWN
- **Authority id**: `VT_MARKETS_FRICTION_AUTHORITY_V1`
- **FRICTION_AUTHORITY_SHA256**: `66d803c797fa3d801b9b5ad4a542587224ca16c2f9547233e4dd1d10ba5a9c8e`
- **Status**: `BLOCKED_BROKER_AUTHORITY`

## Component authorities

| Component | Status |
| --- | --- |
| SPREAD | MISSING |
| COMMISSION | MISSING |
| SLIPPAGE | MISSING |
| SWAP | MISSING (UNDETERMINED) |

## Spread distribution (all sessions)

| Symbol | N | P50 | P90 | P95 | Unit |
| --- | ---: | ---: | ---: | ---: | --- |
| EURUSD | 0 | None | None | None | — |
| GBPUSD | 0 | None | None | None | — |
| USDJPY | 0 | None | None | None | — |
| XAUUSD | 0 | None | None | None | — |

## Blockers

- VENUE_IDENTITY incomplete (broker/server/account class/account currency required)
- symbol contract EURUSD missing ['digits', 'point', 'trade_tick_size', 'trade_tick_value', 'contract_size', 'currency_base', 'currency_profit', 'currency_margin']
- symbol contract GBPUSD missing ['digits', 'point', 'trade_tick_size', 'trade_tick_value', 'contract_size', 'currency_base', 'currency_profit', 'currency_margin']
- symbol contract USDJPY missing ['digits', 'point', 'trade_tick_size', 'trade_tick_value', 'contract_size', 'currency_base', 'currency_profit', 'currency_margin']
- symbol contract XAUUSD missing ['digits', 'point', 'trade_tick_size', 'trade_tick_value', 'contract_size', 'currency_base', 'currency_profit', 'currency_margin']
- SPREAD_AUTHORITY=MISSING (no quote observations)
- COMMISSION_AUTHORITY=MISSING
- SLIPPAGE_AUTHORITY=MISSING (requires read-only fill history; not inferable from quotes)
- SWAP_AUTHORITY=MISSING with applicability UNDETERMINED

## Historical applicability

Venue friction evidence is captured from a live 2026 VT Markets environment. The candidate datasets under data authority cover 2011-06-01 to 2018-06-06. Spreads, commission schedules and financing rates from 2026 are NOT evidence about 2012 or 2017 execution conditions: retail FX spreads compressed substantially over that period, commission-inclusive 'raw' accounts were not uniformly available, and the broker entity, liquidity providers and regulatory regime all differ. Any backtest over 2011-2018 priced with 2026 friction is therefore reporting VENUE_CURRENT_FRICTION_AUTHORITY applied counterfactually, not HISTORICAL_FRICTION_TRUTH. HISTORICAL_FRICTION_TRUTH for this period is UNAVAILABLE and cannot be manufactured from current captures.

## Guarantees

- No orders were placed; all venue access is read-only.
- No broker credentials were requested, stored or transmitted.
- Missing components are MISSING, never zero: `assert_usable_for_economics()` fails closed.
- No strategy was evaluated, retuned or created.
