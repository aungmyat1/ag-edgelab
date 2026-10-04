# UNIVERSAL_PRICE_ACTION_FUNNEL_V0_3_REPORT

Research / diagnostic infrastructure only — no trades created or executed, no strategy rules changed, no optimization performed.

## Engines

- RULE_CLASSIFIER = PASS
- DIRECTION_ENGINE = PASS
- LOCATION_ENGINE = PASS
- CONFIRMATION_ENGINE = PASS
- TARGET_LAB = PASS
- FX_PROFILE = PASS
- CRYPTO_PROFILE = PASS
- CROSS_ASSET_PARITY = PASS

## Session behavior
- FX_SESSION_BEHAVIOR = OPTIONAL_DIAGNOSTIC (Asian strategy family: REQUIRED)
- CRYPTO_SESSION_BEHAVIOR = NOT_APPLICABLE (intentional; never serialized as missing evidence)

## Asian V2 overlay
- ST_ASIAN_SESSION_BRANCH_V2_NOT_PRESENT_IN_REPOSITORY — overlay executed against SYNTHETIC_BRANCHING_REFERENCE as a declared proxy population
- ALIGNED_N = 3, COUNTER_N = 1, NEUTRAL_N = 1
- RANGE_PREEMPTION_FINDING: 1 candidate(s) flip between SWEEP and RANGE across the frozen variants; of these 0 align with direction authority and 1 suppress a later better-aligned SWEEP/TREND candidate. Proxy population — no claim is made about ST_ASIAN_SESSION_BRANCH_V2 itself.

## Crypto reference (DEVELOPMENT, synthetic, non-authoritative)
- SYMBOLS = BTCUSDT (synthetic fixture); ETHUSDT skipped — no authorized repo data
- DIRECTION_POPULATION = 458
- CONFIRMED_POPULATION = 70
- PRIMARY_DIAGNOSIS = TARGET_MODEL_MISMATCH (case D): median natural target 2.58R < frozen fixed target 3R (diagnostic only — the strategy target is NOT replaced)
- NEXT_FUNNEL_TO_CHANGE = TARGET

## Invariants
- STRATEGY_RULES_CHANGED = NO
- NEW_STRATEGY_CREATED = NO
- REALIZED_ECONOMICS_RUN = NO (non-authoritative synthetic data only)
- OOS_OPENED = NO
- HOLDOUT_TOUCHED = NO
- EXECUTION_CAPABILITY_ADDED = NO

## STATUS

UNIVERSAL_FUNNEL_V0_3_READY

STOP — no next FX/crypto strategy version is created automatically; evidence is returned to the owner.
