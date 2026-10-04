# Universal Funnel V0.6 — Natural Target + Runner Research

EXPERIMENT: TARGET_POLICY_NATURAL_RUNNER_V1 @ 0.1.0-research · authoritative V0.5 65ba0ed76304 (resolved + reproduced) · STATUS: **V0_6_TARGET_POLICY_RESEARCH_COMPLETE**

## Mean structural R by policy (NULL-safe, resolved outcomes only)

| policy | D01 mean R | D01 resolved | T1 mean R | T1 resolved |
|---|---|---|---|---|
| C0_1R | +0.034 | 3034 | +0.116 | 362 |
| C0_2R | +0.025 | 2824 | +0.177 | 339 |
| C0_3R | -0.026 | 2617 | -0.010 | 315 |
| C0_4R | -0.117 | 2481 | -0.175 | 297 |
| C0_5R | -0.234 | 2372 | -0.379 | 280 |
| C1 | +0.006 | 3116 | -0.001 | 375 |
| C2_F25_R0 | +0.013 | 2893 | -0.026 | 341 |
| C2_F25_R1 | +0.017 | 3009 | -0.076 | 360 |
| C2_F50_R0 | +0.002 | 2893 | -0.027 | 341 |
| C2_F50_R1 | +0.011 | 3009 | -0.055 | 360 |
| C2_F75_R0 | -0.009 | 2893 | -0.028 | 341 |
| C2_F75_R1 | +0.006 | 3009 | -0.034 | 360 |
| C3_F25_R0 | -0.039 | 2715 | -0.049 | 320 |
| C3_F25_R1 | -0.017 | 2971 | -0.079 | 360 |
| C3_F50_R0 | -0.043 | 2715 | -0.048 | 320 |
| C3_F50_R1 | -0.016 | 2971 | -0.057 | 360 |
| C3_F75_R0 | -0.048 | 2715 | -0.047 | 320 |
| C3_F75_R1 | -0.015 | 2971 | -0.035 | 360 |
| C4_F25_R0 | -0.211 | 2343 | -0.337 | 279 |
| C4_F25_R1 | -0.073 | 2886 | -0.177 | 361 |
| C4_F50_R0 | -0.187 | 2343 | -0.277 | 279 |
| C4_F50_R1 | -0.064 | 2886 | -0.133 | 361 |
| C4_F75_R0 | -0.164 | 2343 | -0.216 | 279 |
| C4_F75_R1 | -0.055 | 2886 | -0.088 | 361 |

## Verdict

- PRIMARY_DIAGNOSIS (D01 control): **C_NATURAL_TARGET_PLUS_RUNNER_SUPPORTED_FOR_FURTHER_TESTING**
- SECONDARY: ['A_FIXED_TARGET_MODEL_INFERIOR', 'F_T1_DIRECTION_FILTER_HARMS_RUNNER_CONTINUATION']
- T1 decision: F_T1_DIRECTION_FILTER_HARMS_RUNNER_CONTINUATION
- BEST_STRUCTURAL_POLICY (descriptive, fraction never promoted): D01 {'policy': 'C4_F75_R0', 'mean_paired_delta_vs_C0_2R': 0.1844064645558774, 'pair_n': 2343, 'rule': 'BEST_STRUCTURAL_POLICY = highest mean paired delta vs C0_2R with >= 100 pairs; descriptive only; partial fraction never promoted', 'fraction_not_promoted': True} · T1 {'policy': 'C4_F75_R0', 'mean_paired_delta_vs_C0_2R': -0.0008709861968253706, 'pair_n': 279, 'rule': 'BEST_STRUCTURAL_POLICY = highest mean paired delta vs C0_2R with >= 100 pairs; descriptive only; partial fraction never promoted', 'fraction_not_promoted': True}
- P(2nd|1st): D01 0.635 · T1 0.542
- SL-geometry dependence: {'D01': 'NO', 'T1': 'NO'}
- Economics: NOT RUN (exit contract + friction authority fail-closed)
- Candidate freeze: FREEZE_CANDIDATE_FOR_FUTURE_OOS_VERIFICATION
- NEXT: **FREEZE_RUNNER_POLICY_CONTRACT_THEN_OOS_VERIFICATION_MISSION**

## Guards

upstream frozen · no partial-% optimization · no promotion · no economics claims · no OOS · no holdout · no V0.7
