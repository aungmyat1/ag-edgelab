# ST_MTF_CONTROL_SHIFT_V3 session-date coupling preregistration

## Status

`STATUS = V3_STRUCTURALLY_ZERO_BUT_PREREGISTERED`

No V3 economic replay was run. V2 remains unchanged. OOS and the sealed holdout remain unopened.

## Identity

- Parent: `ST_MTF_CONTROL_SHIFT_V2 @ 2.0.0`
- Parent YAML SHA256: `56b6032fc949564e0ff8d147eb794560088fb0d90eac3bc549de504f01a6cc91`
- Child: `ST_MTF_CONTROL_SHIFT_V3 @ 3.0.0`
- Child YAML SHA256: `65862fa02e6b38d0b1a3f06489c81ff3313384b392fa11df075674ac54f7c918`
- Only changed behavior: `H1_SHIFT_SESSION_DATE_COUPLING`

## Frozen V3 semantic

A qualifying H1 control shift must satisfy both:

1. Existing V2 freshness: `shift_age_h1_bars <= 24` closed H1 bars.
2. The shift creation timestamp's UTC calendar date equals the active session date.

The existing H1, H4, M15, POI, FVG, entry, risk, outcome, and session-window rules are unchanged.

## Date and timezone authority

- Raw HistData timestamps are normalized from `America/New_York` to UTC using the established PR #10 pipeline.
- Session assignment and session-date comparison use UTC.
- The active session date is the UTC calendar date of the evaluation M15 bucket/session observation.
- `ASIAN_LONDON` remains `[06:00, 09:00)` UTC.
- `LONDON_NEWYORK` remains `[11:00, 14:00)` UTC.
- Session start is inclusive; session end is exclusive.
- Neither session crosses midnight.
- A timestamp exactly at `00:00 UTC` belongs to that UTC date.
- DST is resolved only during New York-to-UTC normalization; no additional DST adjustment occurs during date comparison.
- A shift before the session start is accepted by the date-coupling rule if it is on the same UTC calendar date. The separate existing M15 in-session creation rule remains unchanged.
- A shift whose UTC date is after the active session date is invalid.

## Structural precheck

| Population | Count |
|---|---:|
| LOCATION_PASS | 170 |
| V2 eligible at age <=24 | 18 |
| V3 eligible after date coupling | 0 |
| SAME_SESSION_DATE | 0 |
| PRIOR_SESSION_DATE | 18 |
| FUTURE_DATE_INVALID | 0 |

The precheck confirms that every V2 trigger came from the prior UTC calendar date. V3 therefore has zero structural triggers in this fixed 170-case population.

This zero result is allowed and has not been used to loosen the preregistered rule.

## Fixed preregistration controls

- Dataset lineage: PR #10 HistData 2017, same raw hashes and causal derived data as V2
- Symbols: EURUSD, GBPUSD, USDJPY, XAUUSD
- Sessions: ASIAN_LONDON and LONDON_NEWYORK
- Warmup: 2017-01-01 through 2017-03-01
- DEV: 2017-03-01 through 2017-09-01
- OOS: 2017-09-01 through 2017-12-01, not opened
- Sealed holdout: 2017-12-01 through 2018-01-01, untouched
- Friction: unchanged PR #10-approved instrument-specific model
- Funnel mapping: unchanged TRIGGER → CONFIRMATION → OUTCOME mapping
- Gates: unchanged EdgeLab DEV gates, no optimization, one entry per symbol/session/day, earliest signal wins, post-signal M1 fill, 21:00 force-flat, no overnight

## Preregistration state

`PREREGISTERED = YES`

The exact preregistration is stored in `v3_preregistration.json`. No economic result was used to change the rule.
