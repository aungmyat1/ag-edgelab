# SESSION_TRADE_V2 Specification

**Status:** RESEARCH_SHADOW  
**Strategy:** `SESSION_TRADE_V2`  
**Version:** `2.0.0`  
**Authority:** informational proposals only; Demo and Live execution are disabled.

## Objective

Provide one deterministic session-trading contract for EURUSD, GBPUSD, USDJPY and XAUUSD across two daily cycles without changing or deleting historical V1 strategy authority.

## Session pairs (UTC)

| Cycle | Frozen reference | Trade window |
|---|---|---|
| ASIAN_LONDON | 22:00-06:00 | 06:00-09:00 |
| LONDON_NEWYORK | 06:00-11:00 | 11:00-14:00 |

M15 closed candles are the decision evidence. Window slicing is a caller responsibility; the engine accepts only the already-bound reference and trade candles.

## Reference geometry

`H = reference_high`, `L = reference_low`, `A = H-L`, `EQ = (H+L)/2`, `R0 = 0.25*A`.

A non-positive range is a data/contract error.

## Setup priority

The engine evaluates `A_SWEEP_REENTRY` before `B_RANGE_REJECTION` before `C_TREND_EXPANSION`. One qualifying setup ends evaluation for that symbol/cycle.

### A — Sweep + reentry

- Low-side LONG: candle trades below `L` and closes back above `L`.
- High-side SHORT: candle trades above `H` and closes back below `H`.
- A same-candle sweep of both sides is `AMBIGUOUS_DUAL_SIDE_SWEEP` and returns `NO_TRADE`.
- Entry: qualifying M15 close (`MARKET` proposal).
- Nominal stop distance: `R0` from entry.
- The nominal stop must clear the swept wick extreme. Otherwise `SWEEP_STOP_DOES_NOT_PROTECT_EXTREME` and `NO_TRADE`.

### B — Range rejection

Used only when no A setup exists.

- LONG: reference low is touched/rejected and the candle closes inside the box.
- SHORT: reference high is touched/rejected and the candle closes inside the box.
- A candle rejecting both sides is ambiguous and returns `NO_TRADE`.
- Entry: reference boundary (`LIMIT` proposal).
- Stop: one `R0` beyond that boundary.

### C — Trend expansion

Used only when neither A nor B exists.

- LONG: the qualifying candle body and close are above `H`.
- SHORT: the qualifying candle body and close are below `L`.
- Entry: retrace `LIMIT` at `EQ`.
- Stop: one `R0` beyond EQ opposite the direction.

## Targets and management

Actual risk `R = abs(entry-stop)`.

- Leg 1: 75% at `4R`.
- Leg 2: 25% at `5R`.
- A/B: after 4R, runner management is breakeven then 5R.
- C: after 4R, runner trails confirmed M15 swings with a 5R cap.

Position size is deliberately not calculated by this research/shadow implementation. The contract records 0.5% risk intent but does not authorize account mutation.

## Quotas

Contract intent: maximum one entry per symbol/cycle and two entries per day. These are portfolio/runtime state constraints, not pure single-evaluation engine logic, and must be enforced by the orchestration layer before promotion.

## Safety / promotion boundary

`proposal_generation_authorized=true` means an informational ticket may be created. It does **not** mean an order may be sent.

Frozen defaults:

- `demo_authorized=false`
- `live_authorized=false`
- `allow_order_send=false`
- delivery is `ARCHIVE_ONLY`

Promotion requires separate EdgeLab evidence, runtime quota enforcement, live-data window binding validation, spread/metadata gates, and an explicit owner authorization change. V1 files and historical evidence remain unchanged.
