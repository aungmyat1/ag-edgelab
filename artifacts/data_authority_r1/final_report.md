# EDGELAB_DATA_AUTHORITY_R1 — Final Report

**STATUS:** DATA_AUTHORITY_ESTABLISHED  
**TASK_CLASS:** SYSTEM_DEVELOPMENT / DATA_AUTHORITY

## What was built

A multi-year, hash-pinned, timezone-proven FX bar authority covering **EURUSD, GBPUSD, USDJPY, XAUUSD** across 2011..2018 (32 symbol-years).

Window common to all four symbols: **[2011-06-01T00:00:00Z, 2018-06-06T00:00:00Z)**. The upstream mirror does not publish identical spans per symbol (XAUUSD starts 2011-05-10; GBPUSD stops 2018-06-06). No year was fabricated to even this out — every partition is bounded by the common window instead.

- **720,153,242 raw ticks** parsed from 179,703 archive members (37.0 GB uncompressed, 6.2 GB on disk)
- **10,719,608 canonical M1 bars**, 13,822,002 rows across all six timeframes
- In-session coverage 92.71% – 99.92%

## Timezone authority

**UTC — PROVEN**

A single instrument cannot distinguish a clock from a venue session: (UTC+0, Chicago 17:00) and (UTC+1, New York 17:00) predict identical observations. Each instrument is therefore only narrowed to a set of admissible offsets, and the corpus intersection picks the unique one.

> every instrument admits UTC+0 and no other offset is admitted by all of them; with the clock fixed, each instrument's venue session contract is uniquely determined

Resolved venue sessions:

- `EURUSD` → SPOT_FX_NY_1700
- `GBPUSD` → SPOT_FX_NY_1700
- `USDJPY` → SPOT_FX_NY_1700
- `XAUUSD` → CME_METALS_CHICAGO_1700

## Integrity

| Check | Count |
| --- | ---: |
| Duplicate timestamps | 0 |
| Invalid OHLC bars | 0 |
| Timezone anomalies | 0 |
| Grid misalignments | 0 |
| Non-monotonic timestamps | 0 |
| Price precision anomalies | 0 |

Missing-bar policy: **EXPLICIT_ABSENCE_NO_FILL** — a minute with no tick produces no row. Nothing is forward filled, interpolated or invented.

## Cross-source check

Comparator: HISTDATA_ASCII_M1_2017_PR10_PINNED (frozen, unmodified).

| Symbol | Verdict | Median relative close difference |
| --- | --- | ---: |
| EURUSD | AGREEMENT | 8.59e-06 |
| GBPUSD | AGREEMENT | 7.98e-06 |
| USDJPY | AGREEMENT | 8.99e-06 |
| XAUUSD | AGREEMENT | 3.91e-05 |

Scale disagreements: **0**. NONE — diagnostic only, neither source altered.

## Readiness (DATA only — not edge claims)

- `MULTIYEAR_FX_DATA_READY` = **YES**
- `WALK_FORWARD_DATA_READY` = **YES** (21 usable folds on the weakest symbol)
- `REGIME_DATA_READY` = **YES**
- `FRICTION_FRAMEWORK_READY` = **YES**
- `FRICTION_AUTHORITY_COMPLETE` = **NO**
- `CRYPTO_DATA_ADAPTER_READY` = **NO**

## Governance

- **PREVIOUS_OOS_LOG_PRESERVED**: YES
- **C3_REJECTION_PRESERVED**: YES
- **TARGET_POLICY_C3_V1**: EDGE_STATUS=NO_EDGE, OOS_STATUS=CONSUMED, RETUNING=FORBIDDEN
- **CONSUMED_OOS_WINDOW**: [2017-09-01, 2017-12-01) remains CONSUMED; the same calendar period in the new dataset is registered DEVELOPMENT_KNOWN so it cannot be re-sold as fresh OOS via a second provider
- **SEALED_HOLDOUT**: [2017-12-01, 2018-01-01) never opened; mirrored as SEALED in the new dataset too

## Safety boundary

- STRATEGY_RULES_CHANGED = **NO**
- NEW_STRATEGY_CREATED = **NO**
- PARAMETER_OPTIMIZATION = **NO**
- OOS_OPENED = **NO**
- HOLDOUT_TOUCHED = **NO**
- EXECUTION_CAPABILITY_ADDED = **NO**
- SYNTHETIC_USED_AS_EDGE_EVIDENCE = **NO**
- STRATEGIES_RUN = **NO**

## Primary blocker

FRICTION_VALUE_AUTHORITY — commission, swap and contract specifications require broker access that does not exist in this environment. Net/economic claims remain NOT_ESTIMABLE.

## Next

1. Capture an authoritative VT Markets RAW_ECN friction snapshot into the prepared FrictionQuote schema; that single input flips FRICTION_AUTHORITY_COMPLETE and unlocks net economic evaluation.
2. Preregister any candidate BEFORE touching the fresh [2018-01-01, 2018-04-01) OOS window, and record it in config/governance/oos_access_log.json.
3. Keep [2017-09-01, 2017-12-01) classified DEVELOPMENT_KNOWN for every new candidate family.
4. If crypto is wanted, close the exact contracts listed in crypto_data_adapter_review.json rather than merging an adapter.
