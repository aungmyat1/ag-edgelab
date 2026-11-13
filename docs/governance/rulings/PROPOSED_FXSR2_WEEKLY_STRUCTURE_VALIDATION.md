# PROPOSED_FXSR2_WEEKLY_STRUCTURE_VALIDATION

## Conflict

The owner-supplied Gate A verification condition requires the tools/check_bars.py output field weekly_structure to be compared before and after the 2026-03-08 weekend. The addendum's pinned tools/check_bars.py does not produce a weekly_structure field. Its report contains row counts, duplicate/non-monotonic/invalid OHLC counts, aggregate gap counts, estimated missing M5 bars, and at most the 15 largest intra-week gaps.

The owner also requires every intra-week gap above 60 minutes to be listed individually. The pinned checker truncates largest_intra_week_gaps to 15 entries, so that report alone cannot guarantee a complete list when more than 15 such gaps exist.

The addendum instructs the agent not to alter its tools or data to force a pass. No MT5 history has been exported or read.

## Options

1. Keep Phase 2 blocked until an owner-approved, hash-pinned supplemental checker defines and emits weekly structure and a complete list of all intra-week gaps over 60 minutes.
2. Amend the preregistered verification criterion before export to use only fields the pinned checker actually emits, and explicitly define a separate approved method for validating the UTC/DST transition.
3. Retain the current conditions and mark the run blocked because the named fields cannot be computed by the pinned tool.

## Recommendation

Choose option 1 or 2 before opening/exporting history. Preserve all pinned addendum files; do not edit check_bars.py or proceed on an assumed meaning of weekly_structure.

## Status

PROPOSAL ONLY — no owner ruling or data access has occurred. The proposal does not authorize opening OOS or SEALED_HOLDOUT.

## Reference project reviewed

The owner-provided repository, pinned for this review at tree commit d7a5d5ef552240c839eae6f66086740d1e1e9796, provides a relevant method but does not clear the mismatch:

- docs/setup/MT5_MCP_SETUP.md states that this project does not use MT5 Strategy Tester; its MT5 path is read-only market-data access and its historical replay is a separate Python engine.
- docs/status/SSC_V1_0_1_ONE_YEAR_HISTORICAL_REPLAY_STATUS.md records BLOCKED_CROSS_LEG_TIMEZONE_INCONSISTENT and says no replay was executed.
- src/mt5/broker_time.py derives a seasonal UTC offset from the weekly FX reopen bars rather than applying a fixed offset schedule. This is a useful methodology reference, but the repo's server and data source are not authority for the selected VT Markets feed.
- The historical window reported in the reference project's one-year audit (2025-09-15 through 2026-09-14) overlaps the proposed FXSR2 DEVELOPMENT dates. The referenced status reports no replay, but market-data access in the other project must be disclosed by the owner; it cannot be silently recorded as no prior exposure.

Potential resolution: owner may authorize a separately hashed supplemental checker that records per-week reopen-derived offset/weekly structure and emits every intra-week gap over 60 minutes. Do not copy or run that method against FXSR2 data until the owner resolves the exposure disclosure and approves the amended validation procedure.

Source links:
- https://github.com/aungmyat1/AG-profit-trading-assit/blob/d7a5d5ef552240c839eae6f66086740d1e1e9796/docs/setup/MT5_MCP_SETUP.md
- https://github.com/aungmyat1/AG-profit-trading-assit/blob/d7a5d5ef552240c839eae6f66086740d1e1e9796/docs/status/SSC_V1_0_1_ONE_YEAR_HISTORICAL_REPLAY_STATUS.md
- https://github.com/aungmyat1/AG-profit-trading-assit/blob/d7a5d5ef552240c839eae6f66086740d1e1e9796/src/mt5/broker_time.py
