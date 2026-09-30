# AG EdgeLab

Standalone, strategy-agnostic edge validation laboratory for funnel-based trading research.

## Purpose

AG EdgeLab evaluates whether a deterministic strategy exhibits reproducible economic edge and identifies which funnel stages add or destroy that edge.

Core funnel:

`CONTEXT -> LOCATION -> TRIGGER -> GEOMETRY -> EXECUTION -> OUTCOME/AUDIT`

The live AG trading runtime is intentionally out of scope. EdgeLab does not connect to broker accounts, create TradeTickets, or authorize Demo/Live execution.

## Design principles

- Strategy-agnostic contracts
- No look-ahead access
- Immutable experiment and dataset lineage
- SHA-256 fingerprints
- Candidate ledger, not trade-only logging
- R-based performance metrics
- OOS / SEALED_OOS separation
- Interchangeable backtest engines
- NautilusTrader as an optional simulation adapter, never validation authority
- Funnel-stage conditional win rate and expectancy attribution

## Current implementation stage

R0 foundation.

Implemented first:

- domain contracts
- five pre-trade funnel stages
- anti-look-ahead evaluation context
- sequential funnel runner
- candidate ledger model
- neutral OrderIntent
- dataset roles and SHA-256 fingerprint helpers
- experiment sealing guard

Next:

- DatasetManifest V2
- StrategyManifest
- declarative FunnelDefinition / compiler
- canonical rejection-code contract
- stable result hashing
- manifest serialization
- property-based invariant tests

## Source reuse

This repository reuses audited concepts and selected implementation patterns from the owner's existing trading repositories, especially `smc-lss-platform`, while deliberately excluding live/broker execution authority.
