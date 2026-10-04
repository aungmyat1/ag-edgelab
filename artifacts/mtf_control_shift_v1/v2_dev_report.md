# ST_MTF_CONTROL_SHIFT_V2 DEVELOPMENT replay

STATUS = `V2_INSUFFICIENT_SAMPLE`

The preregistered V2 replay completed on the fixed DEV partition. V2 changed only H1 freshness from 4 to 24 closed H1 bars. OOS was not opened.

## Structural flow

- CONTEXT_PASS: 2,246 aligned observations
- LOCATION_PASS: 170
- TRUE_H1_CONTROL_SHIFT: 18
- LIQUIDITY_SWEEP: 1
- FVG_REBALANCE: 140
- M15_REFINEMENT: 0
- GEOMETRY_VALID: 0
- LIMIT_FILLED: 0
- CLOSED: 0

V2 converted 18 of the 170 structural location observations into eligible H1 shifts, as predicted by the age analysis. None reached M15 confirmation, so the replay produced more structural triggers but no useful entry population.

## DEV matrix

| Symbol | Session | Signals | Filled | Closed | Net R | Net Exp | Net PF | Max DD R | Friction R | Status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| EURUSD | ASIAN_LONDON | 0 | 0 | 0 | None | None | None | None | 0 | INSUFFICIENT_SAMPLE |
| EURUSD | LONDON_NEWYORK | 0 | 0 | 0 | None | None | None | None | 0 | INSUFFICIENT_SAMPLE |
| GBPUSD | ASIAN_LONDON | 0 | 0 | 0 | None | None | None | None | 0 | INSUFFICIENT_SAMPLE |
| GBPUSD | LONDON_NEWYORK | 0 | 0 | 0 | None | None | None | None | 0 | INSUFFICIENT_SAMPLE |
| USDJPY | ASIAN_LONDON | 0 | 0 | 0 | None | None | None | None | 0 | INSUFFICIENT_SAMPLE |
| USDJPY | LONDON_NEWYORK | 0 | 0 | 0 | None | None | None | None | 0 | INSUFFICIENT_SAMPLE |
| XAUUSD | ASIAN_LONDON | 0 | 0 | 0 | None | None | None | None | 0 | INSUFFICIENT_SAMPLE |
| XAUUSD | LONDON_NEWYORK | 0 | 0 | 0 | None | None | None | None | 0 | INSUFFICIENT_SAMPLE |

## Target capability and outcomes

Target capability is null for 1R–5R because there was no M15 refinement, valid geometry, or actual entry. Producing counterfactual entries would change the frozen candidate semantics. MFE, MAE, realized gross R, friction R, net R, expectancy, PF, and drawdown are likewise null except friction total `0` because no fills occurred.

## V1 versus V2

| Metric | V1 | V2 |
|---|---:|---:|
| Location pass | 170 | 170 |
| H1 shift pass | 0 | 18 |
| Confirmation pass | 0 | 0 |
| Filled | 0 | 0 |
| Closed | 0 | 0 |

V2 created more structural triggers, but not more useful triggers in this DEV sample.
