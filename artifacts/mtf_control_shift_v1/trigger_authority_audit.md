# Trigger authority audit

Campaign: `ST_MTF_CONTROL_SHIFT_V1 @ 1.0.0`

## Verdict

`ROOT_VERDICT = TRIGGER_ZERO_IS_SOURCE_FAITHFUL`

All 170 deterministic H4-location-pass observations were audited. Every case classified as `SHIFT_TOO_OLD` under the frozen four-H1-bar age gate. The source implementation and an independently written semantic reference produced the same H1 shift set in all 170 cases. The EdgeLab replay calls the byte-exact frozen source engine directly; there is no separate strategy adapter that could silently alter the trigger.

## Frozen source references

- `src/mtf_control_shift/structure.py:confirmed_swings`
  - swing strength `2`; a swing is usable only with two right bars present.
- `src/mtf_control_shift/structure.py:zones`
  - strict three-candle FVG, confirmed-swing BOS, six-bar opposite-candle origin OB.
- `src/mtf_control_shift/structure.py:control_shift_zones`
  - creates a directional zone only when a prior opposing zone was active immediately before the zone candle and the zone candle closes beyond that opposing zone.
- `src/mtf_control_shift/engine.py:evaluate`
  - uses causal D1/H4/H1/M15 sequences, filters control shifts to the latest four H1 bars, then requires M15 refinement in the session.

The source has no mutable trigger state or portfolio state. The replay orchestration owns session/day quota, while the source engine is stateless.

## Direct source ↔ EdgeLab mapping

| Frozen source rule | EdgeLab replay rule |
|---|---|
| `confirmed_swings(..., strength=2)` | Same frozen source function on H1 bars closed by evaluation timestamp |
| FVG plus BOS plus six-bar opposing origin candle | Same `zones()` implementation |
| Active opposing zone before break | Same `_active_before()` check in `control_shift_zones()` |
| Strict close beyond opposing zone | `close > active.high` bullish; `close < active.low` bearish |
| H1 shift age 4 bars | `created_time >= h1[-4].time` |
| D1/H4 aligned bias | Same `structure_bias()` and `evaluate()` |
| H1 candle close timing | H1 bars admitted only when `bar.open + 1 hour <= T` |
| M15 signal timing | M15 bar admitted only when `bar.open + 15 minutes <= T` |

## Audit population

- Location-pass observations: `170 / 170`
- Deterministic sample retained: first 30 in stable symbol/session/timestamp order
- Full case ledger: `trigger_cases.jsonl`
- Symbols: EURUSD, GBPUSD, USDJPY, XAUUSD
- Sessions: ASIAN_LONDON and LONDON_NEWYORK
- Holdout: not touched

## Failure reasons

| Reason | Count | Percentage |
|---|---:|---:|
| `SHIFT_TOO_OLD` | 170 | 100.0% |

This means the causal H1 history contained prior directional control-shift zones, but none were within the frozen four-H1-bar maximum age at the location-pass timestamps. It is not equivalent to “no historical shift ever occurred.”

## Parity

- `MATCH`: 170
- `SOURCE_PASS_EDGELAB_FAIL`: 0
- `SOURCE_FAIL_EDGELAB_PASS`: 0
- `TIMING_MISMATCH`: 0
- `STATE_MISMATCH`: 0
- `DATA_MISMATCH`: 0

The EdgeLab campaign path uses the frozen source package directly rather than a rewritten trigger adapter. The audit additionally recomputed the control-shift zone set with an independent reference function; it matched the source in all cases.

## Causality

- Causality: `PASS`
- 170/170 cases had no incomplete D1, H4, H1, or M15 bars admitted.
- Re-evaluation from clipped closed-bar views matched the original decision in all cases.
- No future swing confirmation, future control break, future POI, or incomplete H1 bar was used.

## Three-funnel mapping

The requested PR #13-style mapping is diagnostic only and does not modify V1:

- **TRIGGER:** D1/H4 alignment, fresh H4 POI, H4 POI reached, true H1 control shift, liquidity sweep.
- **CONFIRMATION:** FVG rebalance, M15 refinement, valid geometry.
- **OUTCOME:** limit filled, limit expired, TP1, TP2, runner BE, forced flat.

## Final audit decision

`ST_MTF_CONTROL_SHIFT_V1 @ 1.0.0`

- V1 rules changed: `NO`
- OOS opened: `NO`
- Holdout touched: `NO`
- Execution capability added: `NO`
- Current campaign verdict remains: `INSUFFICIENT_SAMPLE`
- Primary weak point: `TRIGGER`
- Bottleneck: `TRUE_H1_CONTROL_SHIFT`

No V2 candidate was implemented. A future V2 hypothesis may examine the measured age bottleneck, but it must use a new strategy identity and must not be retroactively applied to V1.
