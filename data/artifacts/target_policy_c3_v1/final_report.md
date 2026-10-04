# TARGET_POLICY_C3_V1 — PRE-OOS CONTRACT AUTHORITY REMEDIATION

CANDIDATE = TARGET_POLICY_C3_V1 @ 1.0.0-frozen · PARENT = V0.6 @ 8d132355c0138068fd79a2fb22c9c0f38f295a80

## REQUIRED RETURN

IMPLEMENTATION_SHA = a860f5ebcf0ecba4ff29e142125d64ec6e911235a0c0e5329ebbb1ddbb2668c9
TREE_SHA = git tree of the freeze commit (reported in the mission return; a file cannot contain its own tree hash)
CANDIDATE_ID = TARGET_POLICY_C3_V1
CANDIDATE_VERSION = 1.0.0-frozen
CANONICAL_CONTRACT_SHA256 = 5a485308841d1c5d2096e348665ef3f9b1f689c1ed4ce4b30385eeaf2c828112
HASH_REPRODUCED_TWO_PATHS = True
TRIGGER_AUTHORITY_HASH = 5f5e1aafe195b0e5be0f1679bfd3703f52ba817c348d7f716976d73908199f9f
FIRST_TARGET_POLICY_HASH = 92ba68ad3517076c9d92d2e6e6ea66ec8ffd95357bc547cf44ef159df4456fdd
RUNNER_TARGET_POLICY_HASH = aa7a3b8d3e61369f997cb23ef0317418cbddc9461701f48e1759dfee5d4e7326
PARTIAL_FRACTION = 50
RUNNER_FRACTION = 50
RUNNER_STOP_POLICY = R0_ORIGINAL_FROZEN_SL_RETAINED_BY_RUNNER_LEG
RESEARCH_HORIZON = 96 M15_BARS anchored at ENTRY_BAR_CLOSE_TIME
HORIZON_EXIT_PRICE_POLICY = M15_CLOSE_OF_LAST_COMPLETED_BAR_AT_OR_BEFORE_HORIZON — the close of the 96th M15 bar after the entry bar (the last bar of the frozen V0.3 outcome window); identical to the repository AG_REFERENCE_REPLAY v1.1.0 DATA_END fill (exit_price = last completed bar close)
SAME_BAR_COLLISION_POLICY = STOP_FIRST_FROZEN_V0_3_SINGLE_RULE
COLLISION_POLICY_HASH = 33c32dbc61d3ce0f708a3048ff2cc551a7130824d163be417a6bd645e86e22d8
CENSORING_POLICY = RIGHT_CENSORED_DATA_BOUNDARY_EXPLICIT — a trade whose frozen 96-bar outcome window is truncated by the dataset partition end is RIGHT_CENSORED_DATA_BOUNDARY: excluded from resolution and from economic metrics under this frozen policy, its entry_id persisted in the censoring list, and counted in population summaries; never imputed, never a loss, never silently dropped
FRICTION_MODEL_ID = FX_2017_FRICTION_AUTHORITY_ABSENT_FAIL_CLOSED_V1
FRICTION_TABLE_SHA256 = fcd44663adcd686917d406edf3e50e1f65eb188fe72482635cca1c9effd654ec
FRICTION_AUTHORITY_COMPLETE = False
ATTACKS_EXECUTED = 10
ATTACKS_PASSED = 10
ATTACKS_FAILED = 0
FUTURE_TARGET_ATTACK = PASS
FRACTION_ATTACK = PASS
RUNNER_STOP_ATTACK = PASS
HORIZON_ATTACK = PASS
FRICTION_ATTACK = PASS
TARGET_FAMILY_ATTACK = PASS
POPULATION_ATTACK = PASS
DATASET_ROLE_ATTACK = PASS
CENSORING_ATTACK = PASS
COLLISION_ATTACK = PASS
UNRESOLVED_RUNNER_N = 0
RIGHT_CENSORED_N = 0
DEV_ACCOUNTING_VALIDATION = True
CAUSALITY = True
DETERMINISM = True
OOS_STRUCTURAL_READY = True
OOS_ECONOMIC_READY = False
OOS_OPENED = NO
HOLDOUT_TOUCHED = NO
STATUS = CANDIDATE_STRUCTURAL_ONLY
NEXT = OOS_STRUCTURAL_VERIFICATION

## DEV structural resolution summary (DEVELOPMENT only; NOT
## verified economics — friction authority is absent)

- population: 3183 D01 entries (T1 subset 379; pinned values reproduced exactly)
- traded (C3 applicable): 3092; not applicable: 91 (3 no objective, 88 single-objective ladder)
- right-censored (data boundary): 0; unresolved runners: 0
- gross structural R over traded: sum 186.472998, mean 0.060308

Status counts:

- FIRST_PLUS_RUNNER_HORIZON: 325
- FIRST_PLUS_RUNNER_STOP: 914
- FIRST_PLUS_RUNNER_TARGET: 870
- HORIZON_BEFORE_FIRST: 52
- NOT_APPLICABLE_NO_OBJECTIVE: 3
- NOT_APPLICABLE_NO_RUNNER_OBJECTIVE: 88
- STOPPED_BEFORE_FIRST: 931

Fraction-grid transparency (V0.6 structural diagnostics, NULL for
unresolved; the candidate fraction is the preregistered grid
midpoint 50/50 fixed in the contract — never selected from DEV):

- C3_F25_R0: resolved 2715, mean structural R -0.0387
- C3_F50_R0: resolved 2715, mean structural R -0.043339
- C3_F75_R0: resolved 2715, mean structural R -0.047978

## Notes

- Prior readiness declarations were NOT copied; every value above
  was independently reproduced in this freeze run from the pinned
  raw dataset (sha256-verified), the frozen V0.3-V0.6 authority
  chain, and the independent verifier module.
- The independent verifier re-derived all 3092 traded outcomes
  bar-by-bar from the pinned M15 bars with its own scan
  implementation and re-validated every accounting identity.
- Parent reproduction: 18/18 V0.5 pinned values match; 3183/3183
  rows reproduce the parent V0.6 C3_F50_R0 structural outcome;
  3183/3183 objective selections match the parent committed
  objective-sequence ledger.
- Fraction authority: preregistered midpoint of the frozen 25/50/75
  grid; never derived from DEV outcomes (V0.6 rule respected).
- Friction authority is ABSENT in this repository (fail-closed):
  FRICTION_AUTHORITY_COMPLETE = NO and OOS_ECONOMIC_READY = NO.
- Net economics are NOT claimed; gross structural R only.
- OOS was NOT opened; the sealed holdout was NOT touched.
- TREE_SHA is the git tree of the freeze commit (a file cannot
  contain its own tree hash); see the mission return.
