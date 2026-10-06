# GEN3_INDEPENDENT_FILTER_PARENT_V0

**STATUS = DESIGN_DRAFT_NOT_AUTHORIZED**

This is design preparation only. It does not authorize replay, optimization,
OOS/holdout access, execution, promotion, or an edge claim.

## Hypothesis

A parent assembled from independently observable session-opportunity filters may
select a more useful DEVELOPMENT subset while retaining exact table-query
mutation semantics. The hypothesis is unverified and deliberately avoids the
chained SMC structure dependencies in ALD V2.

## Base opportunity universe

The proposed denominator is every preregistered session opportunity in the
DEVELOPMENT partition. Opportunity identity, session calendar, symbols, years,
and duplicate policy must be owner-frozen before replay. Every filter is
calculated for every row from information available at that row's timestamp.

## Candidate inputs and filter semantics

1. **TIME_WINDOW_FILTER** — pass when the opportunity timestamp is inside an
   owner-preregistered UTC interval. Input: opportunity timestamp and the frozen
   session calendar.
2. **VOLATILITY_PERCENTILE_FILTER** — pass when a causal realized-volatility or
   ATR value, calculated only from completed bars before the opportunity, lies
   inside preregistered percentile bounds. Percentile fitting uses DEVELOPMENT
   training history only and must have an explicit warm-up policy.
3. **OVERNIGHT_RETURN_FILTER** — pass when the signed or absolute return from
   preregistered prior-session endpoints lies inside frozen bounds. Both
   endpoints must precede the opportunity timestamp; missing endpoints fail
   closed rather than being imputed from future data.

No filter may consume another filter's pass/fail state. Each produces its own
`PASS`, `FAIL`, or `NOT_EVALUABLE` result directly from the same opportunity
row. There are no chained structure, POI, confirmation, or trade-acceptance
requirements.

## Data requirements

Required data are timestamped OHLC bars, a frozen UTC/session calendar, symbol
identity, dataset identity, and DEVELOPMENT partition labels. Input hashes,
timezone conversion, bar-completeness rules, warm-up coverage, and duplicate
handling must be recorded. September–November OOS and December sealed holdout
are forbidden during design, fitting, eligibility, and future DEV optimization.

## Table-query safety

After a full parent fact replay, each filter is a pure predicate over persisted
causal features on one opportunity row. Removing one filter or changing an
owner-approved threshold can therefore be represented as an exact table query,
provided the feature derivation itself is unchanged. Cross-filter dependencies,
short-circuit evaluation, and path-dependent feature recomputation are banned.

## Reference-outcome compatibility

The design is compatible with `REFERENCE_OUTCOME_MODEL_V2`: entry is the market
reference price at the opportunity timestamp; stop distance is ATR-normalized;
target is fixed-R; exit is the preregistered horizon; and direction mode is
explicit. Reference outcomes do not depend on any GEN3 filter passing. The R3
provisional symmetric direction mode is diagnostic only and remains
owner-unauthorized.

## Expected mutation classes

Potential future classes are single-filter removal, independently specified
threshold substitution, and conjunctions of independently evaluated filters.
Mutation budgets, threshold grids, multiplicity controls, and stop rules require
preregistration. No mutation is run by this draft.

## Proposed parent eligibility requirements

Before any child search, require at least 90% reference coverage, minimum sample
floors, an independent full-opportunity baseline universe, parent performance at
or above a proposed 95th percentile, a positive bootstrap CI95 lower bound for
parent-minus-baseline expectancy, and passing permanent null controls. These are
`PROPOSED_OWNER_POLICY`, not current authority.

## Friction limitations

Reference outcomes are gross structural diagnostics. Unknown spread,
commission, slippage, and swap remain separate and must not be substituted with
zero. Economic ranking and `EDGE_VERIFIED` remain unavailable until governed
venue-specific friction evidence exists.

## DEV-only boundary

`DATA_ROLE = DEVELOPMENT_ONLY`. This draft permits no OOS or holdout access, no
broker connectivity or orders, no ALD V2 tuning, and no optimization campaign.
Owner approval and a new preregistration are required before implementation.
