# PRE_OOS_ROBUSTNESS_GATE_V1 — Final Report

**Contract** `6add4d2d155e32cea07f96ac5b520498f6a040456db1a23421865d39803d4f7a`
**Gate status** OPERATIONAL · **Causality** PASS
(12/12 attacks) · **Determinism** PASS

## What this gate is for

EdgeLab could already answer *"does this look good on DEV?"*. It had no
way to answer *"is that DEV result distributed, stable and reproducible
enough to justify spending a fresh OOS window?"* — and a fresh window is
non-renewable. Once read, it can never be fresh again for any descendant
of the candidate that read it.

`TARGET_POLICY_C3_V1` is why this exists. It looked promising on DEV and
failed structurally on OOS, spending a window to learn it.

## Negative control: C3

| field | value |
|---|---|
| `C3_PRE_OOS_DECISION` | **INSUFFICIENT_EVIDENCE** |
| `C3_PRIMARY_DIAGNOSIS` | **INSUFFICIENT_SAMPLE** |
| `C3_SECONDARY_DIAGNOSES` | SYMBOL_DEPENDENCY, ASYMMETRIC_TAIL_DEPENDENCE, FRICTION_AUTHORITY_INCOMPLETE |
| `KNOWN_C3_OOS_RESULT` | STRUCTURAL_GENERALIZATION_FAILS |

The contract was frozen and committed before this run. Thresholds were
not adjusted afterwards.

### Why the gate refused

C3's pooled DEV mean of **+0.0603 R** over 3,092 trades reads like a
tradable edge. Split by symbol, it is not one:

| symbol | n | mean R | median R | gross R | PF | status |
|---|---:|---:|---:|---:|---:|---|
| EURUSD | 716 | -0.0891 | -0.4091 | -63.81 | 0.810 | NEGATIVE |
| GBPUSD | 854 | +0.0247 | -0.3342 | +21.07 | 1.062 | POSITIVE |
| USDJPY | 715 | +0.0209 | -0.3098 | +14.95 | 1.053 | POSITIVE |
| XAUUSD | 807 | +0.2655 | -0.2077 | +214.26 | 1.732 | POSITIVE |

The pooled number is gold. Remove XAUUSD and the mean goes **negative**
(−0.0122, a 120% swing and a sign flip); EURUSD is already losing at
−0.0891. Separately, the pooled median is **−0.330** against a mean of
+0.060 — 59% of trades lose, and the positive mean is carried by rare
large winners (`RARE_LARGE_WINNER`).

The known OOS outcome was mean structural R **−0.106**, with all four
symbols graded C. The gate reached its refusal from DEV evidence alone.

## Known limitations

**TEMPORAL_CONCENTRATION_NOT_TESTED** (MATERIAL)  
Observed: 90.6% of C3's pooled gross R across walk-forward folds comes from the single fold WF04_201705.  
Why: The frozen contract tests the SIGN of each fold's mean (5 of 7 positive, above the 0.60 floor) and the share of positive R held by any one REGIME, but it has no rule for the share of gross R held by any one TIME fold. The walk-forward axis therefore passed.  
Action: `NONE`  
Why no action: Adding a fold-concentration threshold now, having just seen that it would fire on a candidate already known to have failed OOS, is exactly the post-hoc calibration this mission forbids. It is recorded for V2, where it must be preregistered before being run against any candidate.

**LEAVE_ONE_YEAR_OUT_UNEVALUABLE** (STRUCTURAL)  
Observed: C3's DEV evidence spans one calendar year (2017).  
Why: Not a miss — the axis correctly reported NOT EVALUATED and the sample axis fired INSUFFICIENT_SAMPLE. Recorded so the absence of a year-stability number is not mistaken for a year-stability pass.  
Action: `AXIS_REPORTED_NOT_EVALUATED`

**PARAMETER_NEIGHBOURHOOD_NOT_EVALUABLE** (INFORMATIONAL)  
Observed: C3's numeric parameters could not be perturbed from the frozen resolution ledger, which stores outcomes not paths.  
Why: Re-deriving outcomes at perturbed values requires replaying the engine, which is a strategy re-run and outside this mission's boundary. Reported as NOT_APPLICABLE with a reason rather than silently skipped or interpolated.  
Action: `REPORTED_NOT_APPLICABLE`

## Axis results

| axis | result |
|---|---|
| temporal integrity | PASS |
| sample sufficiency | INSUFFICIENT_SAMPLE |
| walk-forward | PASS |
| leave-one-year-out | NOT_EVALUATED |
| leave-one-symbol-out | SYMBOL_DEPENDENCY |
| regime robustness | PASS |
| tail contribution | PASS |
| mean/median divergence | ASYMMETRIC_TAIL_DEPENDENCE |
| bootstrap uncertainty | PASS |
| parameter neighbourhood | NOT_EVALUATED |

## Boundaries held

`OOS_OPENED=False` · `HOLDOUT_TOUCHED=False` ·
`STRATEGY_RULES_CHANGED=NO` ·
`NEW_STRATEGY_CREATED=NO` ·
`PARAMETER_OPTIMIZATION=NO` ·
`REALIZED_ECONOMICS_RUN=NO`

`PRE_OOS_PASS` authorizes one fresh OOS window. It never means
profitable, `ECONOMIC_VERIFIED`, or `EDGE_VERIFIED`.
Friction is `BLOCKED_BROKER_AUTHORITY`; missing friction is recorded as
NOT MEASURED and is never treated as zero.
