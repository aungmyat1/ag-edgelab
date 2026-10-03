# ST_MTF_CONTROL_SHIFT_V1 — Frozen Research Specification

**Version:** 1.0.0  
**Status:** RESEARCH_SHADOW  
**Execution authority:** none. Demo/Live/order_send are disabled.

## Purpose

Formalize the user's multi-timeframe Smart Money day-trading workflow into a deterministic candidate that can be replayed and falsified in EdgeLab without discretionary interpretation.

The source concepts are D1/H4 top-down structure, H4 supply/demand and order blocks with FVG/BOS evidence, H1 control shifts, M15 entry refinement, OB-based invalidation, 2R partial profit, structural final target, and no overnight holding.

Several numerical choices below are **implementation formalizations for V1**, not claims that they came from the source material. They are frozen before the economic campaign.

## Instruments and sessions

- EURUSD
- GBPUSD
- USDJPY
- XAUUSD

UTC execution windows:

- ASIAN_LONDON: 06:00 <= signal < 09:00
- LONDON_NEWYORK: 11:00 <= signal < 14:00

Unfilled limits expire at the end of the active session window. At most one entry is accepted per symbol/cycle/trading day; the earliest valid signal wins. Any still-open position is force-closed at 21:00 UTC so the candidate never holds overnight. These are V1 backtest formalization choices.

## Timeframe stack

| Layer | Timeframe | Function |
|---|---|---|
| Context | D1 | long-term structural bias |
| Context / POI | H4 | aligned structure + fresh supply/demand POI + final target |
| Control shift | H1 | opposing-zone break + BOS + FVG + new OB |
| Entry refinement | M15 | same-direction BOS/FVG/OB; limit at OB midpoint |

## Deterministic primitives

### Confirmed swing

Swing strength = 2.

A swing high is a candle whose high is greater than both two preceding highs and greater-than-or-equal to both two following highs. It becomes usable only after the two right-hand candles are closed. Swing lows are symmetric.

### Structure bias

Using the last two confirmed swing highs and lows:

- BULLISH = higher high AND higher low
- BEARISH = lower high AND lower low
- otherwise NEUTRAL

D1 and H4 must agree. Neutral or disagreement returns `HTF_BIAS_NOT_ALIGNED`.

### Strict 3-candle FVG

For candle i:

- bullish FVG: `low[i] > high[i-2]`
- bearish FVG: `high[i] < low[i-2]`

### BOS

A bullish displacement candle must close above the latest swing high that had already been confirmed before that candle. Bearish BOS is symmetric.

### Order block

Search backward at most 6 bars before the displacement candle:

- bullish demand OB = latest bearish candle
- bearish supply OB = latest bullish candle

Zone = full origin candle low/high.

A zone is fresh if no later close invalidates the far edge and no completed candle before the current final candle has already mitigated it.

## Context gate

1. D1/H4 bias must align.
2. Select the latest fresh H4 zone in the bias direction:
   - bullish -> demand
   - bearish -> supply
3. At least one of the most recent 4 H1 candles must touch the H4 POI.

Failure returns `NO_FRESH_H4_POI` or `HTF_POI_NOT_REACHED`.

## H1 control shift

A valid control shift must create a new same-direction zone and close through a previously created **opposing H1 zone that was still active immediately before the break**.

The new zone already requires BOS + FVG + OB by construction.

Only shifts created within the latest 4 H1 bars are eligible.

### False-CHoCH diagnostics

These labels do not create trades:

- `LIQUIDITY_SWEEP`: wick breaches the active opposing zone but closes back inside.
- `FVG_REBALANCE`: latest bar overlaps an earlier FVG without a valid control shift.
- `FAILED_SHIFT`: reserved for post-event campaign diagnostics where a valid break is reclaimed within two H1 bars; it is not used to create a live signal.

## M15 entry refinement

After the H1 control shift, require a same-direction M15 BOS/FVG/OB zone inside the active session window.

Entry = midpoint of the latest qualifying M15 OB.

Order type = LIMIT.

For event-driven replay, evaluate closed M15 bars sequentially. Once the first valid signal for a symbol/cycle/day is accepted, later signals in that same symbol/cycle/day are ignored.

## Stop loss

Let OB height = `zone.high - zone.low`.

Buffer = `10% * OB height`.

LONG: `SL = OB.low - buffer`.

SHORT: `SL = OB.high + buffer`.

Non-positive zone/risk geometry is `DATA_INVALID`.

## Targets

Actual R = absolute entry-to-stop distance.

TP1:

- 2R
- close 50%
- move remaining 50% to breakeven

TP2:

Nearest opposing H4 structural level beyond TP1:

- LONG: nearest H4 supply-zone low above TP1; if none, nearest confirmed H4 swing high above TP1.
- SHORT: nearest H4 demand-zone high below TP1; if none, nearest confirmed H4 swing low below TP1.

If no structural target beyond TP1 exists, return `NO_VALID_HTF_FINAL_TARGET`.

If neither SL nor final target resolves the remaining position, force-flat the open remainder at 21:00 UTC using the first executable price at/after that time under the replay engine's frozen fill semantics.

## Risk and friction

Risk intent = 0.5% per trade, but this module does not calculate position size.

The strategy engine does not optimize or gate on a post-hoc transaction-cost threshold. The ticket records expected round-trip cost in R when supplied. EdgeLab must model spread, slippage, commission, partial-exit friction, and instrument-specific XAUUSD costs before economic qualification.

## Research funnel mapping

This candidate maps naturally to EdgeLab's strategy funnel:

- CONTEXT = D1/H4 alignment + valid fresh H4 POI
- LOCATION = H4 POI touched
- TRIGGER = valid H1 control shift + M15 refinement
- GEOMETRY = OB entry/SL + TP1/structural TP2 valid
- EXECUTION = limit fill + expiry + realistic friction
- OUTCOME = realized weighted R

## Safety boundary

- `proposal_generation_authorized = true`
- `demo_authorized = false`
- `live_authorized = false`
- `allow_order_send = false`
- `position_size_authorized = false`

No result from this implementation alone authorizes broker mutation. Promotion requires a separate EdgeLab campaign and explicit owner authority change.
