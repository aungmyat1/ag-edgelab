# OWNER R3 CAUSAL POLICY DECISIONS

**Packet version:** R3_CAUSAL_POLICY_DECISIONS_V1
**Bound to:** `POLICY_FREEZE_BASE = 252059ec84e76562e8ecb7115311f42bb62eac41`
(PR #23 merge commit; R2 → R3 → R3.1 → R3.2 evidence lineage)
**Policy proposal:** `config/governance/funnel_optimizer_r3_causal_policy_proposal.json`
(POLICY_HASH embedded in that file)
**Produced by:** R3 causal policy freeze R1 (branch `governance/r3-causal-policy-freeze-r1`)

## Status vocabulary

* `RECOMMENDED_FROZEN_IN_PROPOSAL` — a single recommended value is frozen in
  the hashed policy proposal. It is NOT owner authorization; it becomes
  authority only when the owner ratifies the complete final policy.
* `UNRESOLVED_OWNER_CHOICE_REQUIRED` — no single value can be isolated from
  the evidence; the owner must choose among defensible alternatives.

**No decision below has been owner-ratified. `OWNER_R3_POLICY_AUTHORIZED = FALSE`
and `REAL_CAMPAIGN_AUTHORIZED = FALSE` until the owner explicitly approves
the complete final policy, including the baseline timing choice (R3_OD_05).**

---

## R3_OD_01 — OPPORTUNITY UNIT

* **QUESTION:** What is the atomic opportunity unit for clustering, null
  sampling, and inference?
* **RECOMMENDED_VALUE:** `ONE_SESSION_OPPORTUNITY_PER_SYMBOL_DAY_SESSION` —
  one opportunity cluster per (symbol, day, session); LONG and SHORT
  reference legs attach to the same cluster and are never sampled as
  independent observations.
* **ALTERNATIVES:** (a) per-event-bar units; (b) per-day units collapsing
  sessions.
* **EVIDENCE:** ALD V2 opportunity identity in the frozen replay; R3.1
  clustered inference; R3.2 one-leg null membership audit (one leg per
  opportunity per draw).
* **RISK_IF_WRONG:** Under-clustering inflates effective sample size and
  narrows confidence intervals; over-clustering discards information.
* **STATUS:** `RECOMMENDED_FROZEN_IN_PROPOSAL`

## R3_OD_02 — CAUSAL_ENTRY_GEOMETRY_MASK_V1

* **QUESTION:** Which selection mask defines the parent population?
* **RECOMMENDED_VALUE:** `CAUSAL_ENTRY_GEOMETRY_MASK_V1` — S1–S6 plus entry/
  stop/target geometry, every input carrying `available_at <= T2`; S9,
  future-bar existence, right-censor status, MFE/MAE, realized outcome, and
  future fill knowledge are forbidden inputs.
* **ALTERNATIVES:** (a) historical `row.all_rules_pass` — REJECTED, embeds S9
  outcome information; (b) historical S7/S8 freeze — REJECTED as-is because
  S7 depends on the existence of forward M5 bars after confirmation.
* **EVIDENCE:** R3.2 selection-time audit (`s8_entry_eligible_n = 294`,
  `s9_completed_n = 294`, all-rules-pass requires S9);
  `artifacts/funnel_optimizer_v1_r3_causal_policy_freeze/causal_mask_audit.json`.
* **RISK_IF_WRONG:** A leaking mask admits post-entry information into
  selection and manufactures eligibility (the R3.1 failure mode).
* **STATUS:** `RECOMMENDED_FROZEN_IN_PROPOSAL`

## R3_OD_03 — T2_DECISION_TIME

* **QUESTION:** When is the final parent decision deemed knowable?
* **RECOMMENDED_VALUE:** `T2_DECISION_TIME = CONFIRMATION_M5_CLOSE`
  (confirming M5 bar open + 5 minutes).
* **ALTERNATIVES:** (a) event open T0 — REJECTED, direction not yet known
  (R3.2: 294/294 noncausal); (b) T1 direction availability — insufficient,
  confirmation not yet observed.
* **EVIDENCE:** R3.2 timing ledger; `m15_direction_available_time` and
  `t2_decision_time` in `ag_edgelab.optimization.causal_time`.
* **RISK_IF_WRONG:** An earlier T2 admits direction/confirmation lookahead
  into the parent estimand.
* **STATUS:** `RECOMMENDED_FROZEN_IN_PROPOSAL`

## R3_OD_04 — NEXT_BAR_EXECUTION_RULE

* **QUESTION:** How is the executable reference entry timed?
* **RECOMMENDED_VALUE:** `REFERENCE_EXECUTABLE_ENTRY = FIRST_M5_OPEN_AT_OR_AFTER_T2`
  — never the confirmation bar itself.
* **ALTERNATIVES:** (a) confirmation close price entry (same-bar) — rejected,
  not executable at decision; (b) T2 + fixed offset — rejected, ignores the
  bar schedule.
* **EVIDENCE:** `first_m5_open_at_or_after` implementation; the R3.1 defect
  was entries preceding direction availability by 15 minutes.
* **RISK_IF_WRONG:** Same-bar entry quietly credits the strategy with prices
  it could not transact.
* **STATUS:** `RECOMMENDED_FROZEN_IN_PROPOSAL`

## R3_OD_05 — BASELINE_T2_TIMING_POLICY  ⚠ OPEN OWNER CHOICE

* **QUESTION:** How are non-parent baseline opportunities' reference entries
  timed in the causal T2 estimand?
* **RECOMMENDED_VALUE:** NONE — this is the explicitly unresolved decision.
* **ALTERNATIVES (compared without tuning; see
  `artifacts/funnel_optimizer_v1_r3_causal_policy_freeze/baseline_timing_sensitivity.json`):**
  * `A = EMPIRICAL_MATCHED_DELAY` — deterministic hash-slot into the sorted
    parent T2−T0 lag distribution (R3.2 diagnostic semantics).
  * `B = STRATIFIED_EMPIRICAL_MATCHED_DELAY` — same, stratified by symbol +
    session, and by year where the stratum has ≥ 30 parents.
  * `C = FIXED_CAUSAL_DELAY_FROM_T1` — one preregistered clock (120 minutes
    from T1) that does not depend on whether the opportunity later qualifies.
* **EVIDENCE:** The three-policy sensitivity table in
  `baseline_timing_sensitivity.json` (POLICY_SENSITIVITY_ANALYSIS, not
  candidate optimization). The current R3.2 baseline
  (`DETERMINISTIC_MATCHED_EMPIRICAL_T2_MINUS_T0_LAG_FOR_NONPARENT_UNIVERSE`)
  was an adversarial diagnostic and is NOT yet owner authority.
* **RISK_IF_WRONG:** A baseline timing choice that systematically
  over/under-credits the baseline shifts the percentile and delta CI and can
  flip an eligibility verdict; the choice must not be made by looking at
  which policy makes a strategy pass.
* **STATUS:** `UNRESOLVED_OWNER_CHOICE_REQUIRED`
  (`BASELINE_TIMING_SENSITIVITY` and per-policy verdicts are recorded in the
  sensitivity artifact.)

## R3_OD_06 — PRIMARY_DIRECTIONAL_NULL

* **QUESTION:** What is the primary null for directional eligibility?
* **RECOMMENDED_VALUE:** `RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY` — one
  direction per opportunity per draw, deterministic preregistered RNG, never
  averaging LONG+SHORT into one null observation.
* **ALTERNATIVES:** (a) `OLD_SYMMETRIC_TWO_LEG_AVERAGE` — RETIRED as
  eligibility authority (R3.2: SD 0.039829R vs 0.083890R, materially
  understated variance); retained only as a historical diagnostic.
  (b) Robustness null `MATCHED_DIRECTION_FREQUENCY_NULL` — kept as the
  secondary, direction-frequency-preserving check.
* **EVIDENCE:** R3.2 null audit; `ag_edgelab.optimization.directional_null_policy`.
* **RISK_IF_WRONG:** An understated null variance inflates parent
  percentiles and manufactures passes.
* **STATUS:** `RECOMMENDED_FROZEN_IN_PROPOSAL`

## R3_OD_07 — REFERENCE_COVERAGE_MIN

* **QUESTION:** Minimum evaluable reference-outcome coverage?
* **RECOMMENDED_VALUE:** `0.90`
* **ALTERNATIVES:** 0.80 (looser), 0.95 (stricter).
* **EVIDENCE:** Carried unchanged from the R3/R3.1 proposed policies; R3
  historical coverage was 100%.
* **RISK_IF_WRONG:** Too low permits selection-survivor coverage bias; too
  high blocks legitimate candidates near data boundaries.
* **STATUS:** `RECOMMENDED_FROZEN_IN_PROPOSAL`

## R3_OD_08 — PARENT_PERCENTILE_MIN

* **QUESTION:** Minimum parent percentile against the primary null?
* **RECOMMENDED_VALUE:** `0.95`
* **ALTERNATIVES:** 0.90, 0.99.
* **EVIDENCE:** Carried unchanged from the R3/R3.1 proposed policies; pass
  additionally requires `DELTA_CLUSTER_CI95_LOW_R > 0`.
* **RISK_IF_WRONG:** Lower thresholds admit weaker parents under multiple
  testing; higher thresholds reduce power.
* **STATUS:** `RECOMMENDED_FROZEN_IN_PROPOSAL`

## R3_OD_09 — BOOTSTRAP_CLUSTER_AND_REPLICATES

* **QUESTION:** Resampling unit and replicate count?
* **RECOMMENDED_VALUE:** `BOOTSTRAP_CLUSTER_UNIT = OPPORTUNITY`,
  `BOOTSTRAP_REPLICATES = 2000`, `NULL_REPLICATES = 2000` (minimum 1000),
  `NULL_MASTER_SEED = 4030341158` with deterministic per-campaign derivation,
  frozen BEFORE any GEN3 evaluation.
* **ALTERNATIVES:** 1000 replicates (the stated minimum); larger counts only
  if preregistered runtime evidence demands.
* **EVIDENCE:** R3.1 clustered bootstrap; R3.2 used 2000 replicates;
  `directional_null_policy.FrozenNullPolicy`.
* **RISK_IF_WRONG:** Leg-level resampling breaks clustering; too few
  replicates makes percentile/CI estimates noisy.
* **STATUS:** `RECOMMENDED_FROZEN_IN_PROPOSAL`

## R3_OD_10 — MIN_PARENT_N

* **QUESTION:** Minimum parent sample size?
* **RECOMMENDED_VALUE:** `30`
* **ALTERNATIVES:** 20, 50.
* **EVIDENCE:** Carried unchanged from the R3/R3.1 proposed policies.
* **RISK_IF_WRONG:** Too small enables small-sample percentile artifacts;
  too large starves legitimate parents.
* **STATUS:** `RECOMMENDED_FROZEN_IN_PROPOSAL`

## R3_OD_11 — REFERENCE_ATR_POLICY

* **QUESTION:** Reference stop distance authority?
* **RECOMMENDED_VALUE:** `ATR(14) on completed M5 bars before entry × 1.0`
  (`REFERENCE_ATR_PERIOD = 14`, `REFERENCE_ATR_MULTIPLE = 1.0`).
* **ALTERNATIVES:** other periods/multiples — none considered; changing them
  after seeing GEN3 performance is forbidden.
* **EVIDENCE:** `reference_outcome_v2._atr_before` (true ranges end strictly
  before the entry bar); carried unchanged from R3.
* **RISK_IF_WRONG:** ATR computed including the entry bar leaks the entry
  candle into the stop distance.
* **STATUS:** `RECOMMENDED_FROZEN_IN_PROPOSAL`

## R3_OD_12 — REFERENCE_TARGET_R

* **QUESTION:** Reference target multiple?
* **RECOMMENDED_VALUE:** `2.0R`
* **ALTERNATIVES:** 1.5R, 3.0R.
* **EVIDENCE:** Carried unchanged from R3; identical for candidate and null.
* **RISK_IF_WRONG:** Asymmetric target/stop geometry changes the baseline
  path expectancy (the symmetric 2R/1R model is not algebraically zero).
* **STATUS:** `RECOMMENDED_FROZEN_IN_PROPOSAL`

## R3_OD_13 — REFERENCE_TIMEOUT

* **QUESTION:** Reference outcome horizon?
* **RECOMMENDED_VALUE:** `REFERENCE_MAX_HOLDING_M5_BARS = 72` (6 hours),
  timeout exit at horizon close.
* **ALTERNATIVES:** 288 bars (ALD V2 natural horizon — different model),
  144 bars.
* **EVIDENCE:** Carried unchanged from R3; identical for candidate and null.
* **RISK_IF_WRONG:** A horizon shorter than typical stop/target resolution
  converts geometric outcomes into unresolved timeouts.
* **STATUS:** `RECOMMENDED_FROZEN_IN_PROPOSAL`

## R3_OD_14 — INTRABAR_TIE_POLICY

* **QUESTION:** When one bar touches both stop and target?
* **RECOMMENDED_VALUE:** `CONSERVATIVE_STOP_FIRST`
* **ALTERNATIVES:** (a) optimistic target-first — rejected; (b) drop
  ambiguous rows selectively — rejected (R2 fixture fails closed with
  AMBIGUOUS_INTRABAR instead).
* **EVIDENCE:** `reference_outcome_v2._one_direction`; R2 fixture
  `AMBIGUOUS_INTRABAR` fail-closed handling.
* **RISK_IF_WRONG:** Optimistic tie resolution systematically overstates
  expectancy.
* **STATUS:** `RECOMMENDED_FROZEN_IN_PROPOSAL`

## R3_OD_15 — ALD_FAMILY_DISPOSITION

* **QUESTION:** What happens to the ALD V2 family?
* **RECOMMENDED_VALUE:** `ALD_V2_DEV_SELECTION_STATUS = DEV_REJECTED_CAUSAL_SELECTION`,
  `ALD_FAMILY_DISPOSITION = ARCHIVE_NO_V2_2` — no causal DEV selection
  evidence, no OOS conclusion, no claim of globally proven NO_EDGE, and no
  further ALD V2 optimization on this DEVELOPMENT evidence. All artifacts
  preserved immutably.
* **ALTERNATIVES:** (a) define V2.2 on the same DEV partition — rejected
  (post-hoc search on consumed evidence); (b) treat R3.1 PASS as valid —
  rejected (R3.2 classified it R3_1_PASS_EXPLAINED_BY_MULTIPLE_ARTIFACTS).
* **EVIDENCE:** `config/governance/ald_v2_disposition.json`; appended
  clarifications in `config/governance/candidate_ledger.json`; frozen ALD V2
  SHA256 `883e9095977cd25840201f5b2b3d5ce6e67b350c1157f30045654dbd13904920`.
* **RISK_IF_WRONG:** Continuing the family on this partition reuses
  direction-timing information already observed.
* **STATUS:** `RECOMMENDED_FROZEN_IN_PROPOSAL`

## R3_OD_16 — MAX_CHILDREN_PER_PARENT

* **QUESTION:** Multiple-testing search budget per parent?
* **RECOMMENDED_VALUE:** `MAX_CHILDREN_PER_PARENT = 100`, with counting
  rules: every tested child counts, rejected children count, failed
  code-valid trials count once evaluated, no reset between rounds.
  `OWNER_AUTHORIZATION_REQUIRED = TRUE`; optimization may begin only after
  `PARENT_DEV_ACCEPTANCE = PASS` AND `OWNER_R3_POLICY_AUTHORIZED = TRUE`;
  no rescue by OOS.
* **ALTERNATIVES:** 50 (stricter), 200 (looser).
* **EVIDENCE:** Multiple-testing section of the policy proposal; GEN3 draft
  requires preregistered mutation budgets.
* **RISK_IF_WRONG:** An uncounted or resettable budget silently inflates the
  family-wise false-pass rate.
* **STATUS:** `RECOMMENDED_FROZEN_IN_PROPOSAL`

---

## Summary

| DECISION_ID | STATUS |
|---|---|
| R3_OD_01 | RECOMMENDED_FROZEN_IN_PROPOSAL |
| R3_OD_02 | RECOMMENDED_FROZEN_IN_PROPOSAL |
| R3_OD_03 | RECOMMENDED_FROZEN_IN_PROPOSAL |
| R3_OD_04 | RECOMMENDED_FROZEN_IN_PROPOSAL |
| R3_OD_05 | **UNRESOLVED_OWNER_CHOICE_REQUIRED** |
| R3_OD_06 | RECOMMENDED_FROZEN_IN_PROPOSAL |
| R3_OD_07 | RECOMMENDED_FROZEN_IN_PROPOSAL |
| R3_OD_08 | RECOMMENDED_FROZEN_IN_PROPOSAL |
| R3_OD_09 | RECOMMENDED_FROZEN_IN_PROPOSAL |
| R3_OD_10 | RECOMMENDED_FROZEN_IN_PROPOSAL |
| R3_OD_11 | RECOMMENDED_FROZEN_IN_PROPOSAL |
| R3_OD_12 | RECOMMENDED_FROZEN_IN_PROPOSAL |
| R3_OD_13 | RECOMMENDED_FROZEN_IN_PROPOSAL |
| R3_OD_14 | RECOMMENDED_FROZEN_IN_PROPOSAL |
| R3_OD_15 | RECOMMENDED_FROZEN_IN_PROPOSAL |
| R3_OD_16 | RECOMMENDED_FROZEN_IN_PROPOSAL |

**Totals:** 16 decisions; 15 with a single frozen recommended value pending
owner ratification; 1 (R3_OD_05) requiring an explicit owner choice.
**Owner-ratified decisions: 0.**
`OWNER_R3_POLICY_STATUS = PROPOSED_OWNER_POLICY`
`OWNER_R3_POLICY_AUTHORIZED = FALSE`
