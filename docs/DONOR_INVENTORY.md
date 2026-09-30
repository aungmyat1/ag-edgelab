# Donor inventory

Reusable patterns identified from the owner's existing repositories.

## aungmyat1/smc-lss-platform

- `src/research/dataset_manifest.py`: SHA-256 file lineage, git SHA, runner fingerprint, dirty-worktree flag
- `src/research/experiment_registry.py`: YAML hypothesis registry pattern
- `src/research/trade_recorder.py`: stable candidate/trade serialization
- `src/research/metrics.py`: R-based metrics integration
- `src/research/monte_carlo.py`: deterministic seeded trade shuffling
- `src/research/walk_forward.py`: chronological fold pattern
- `src/research/report_builder.py`: lightweight report helpers
- `docs/strategy/st_c3/ST-C3_FUNNEL_LIFECYCLE.md`: ordered binary funnel concept
- `docs/strategy/st_c3/ST-C3_STATE_MACHINE.md`: deterministic transitions and rejection codes

## aungmyat1/simple-smc-ag-trading-bot

Potential later rule donors after independent audit and adaptation:

- `smc_bot/structure.py`
- `smc_bot/liquidity.py`
- `smc_bot/poi.py`
- `smc_bot/fib.py`
- `smc_bot/session_range.py`
- `smc_bot/confirmation.py`
- `smc_bot/fee_gate.py`
- `strategies/session_trader.py`
- `strategies/smc_sniper.py`

## Explicit exclusions

The EdgeLab core does not import broker connectors, live signal paths, execution authorization, account risk authority, TradeTickets, or owner UI concerns. Reuse algorithms and tested research patterns aggressively; reuse execution authority never.
