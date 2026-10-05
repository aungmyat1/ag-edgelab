# ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2 — Generation-2 DEV Report

**Experiment** `GEN2_ALD_V2_DEV_R1` · **Version** `2.0.0-research` · **Class** RESEARCH / GENERATION_2 / DEV_ONLY

| | |
|---|---|
| PREREGISTRATION_COMMIT | `6ae179a18b456b1903efa2c111ec49453578caab` |
| PREREGISTRATION_SHA256 | `c914c657097bb262c67ca119204ee6182cf7938b9176950643ee947d80349b9f` |
| STRATEGY_CONTRACT_SHA256 | `f4bef1cf7044138c7471261855836557f8a0dee1b213506883de19e2b7dded53` |
| Corpus | `HISTDATA_ASCII_M1_MULTIYEAR_R2`, 63 symbol-years, 18 DEV years, 4 symbols |
| Partition | DEVELOPMENT_KNOWN `[Y-01-01Z, Y-09-01Z)` only |
| OOS_OPENED / HOLDOUT_TOUCHED | NO / NO |
| PARAMETER_OPTIMIZATION | NO — `PARAMETER_VECTOR = ()` |

---

## 1. Headline

V2 **solved the structural starvation that closed V1** and then **failed the
pre-OOS robustness gate**. Both halves of that sentence are the result; neither
cancels the other.

- Starvation: **SOLVED.** 35 entries → **2,078** on an identical opportunity
  basis (26,814). Entry yield 1.31 → **77.50 per 1,000 opportunities** (59×).
- Edge: **NOT DEMONSTRATED.** Pooled structural expectancy **−0.0042 R** with a
  95% bootstrap interval of **[−0.0619, +0.0550]** — indistinguishable from zero
  *before* any friction is applied.

`PRE_OOS_RESULT = FAIL` · `FROZEN_CANDIDATE = NO` · `EDGE_VERIFIED = NO` ·
`ECONOMIC_EDGE = NOT_ESTIMABLE`.

The gate was run **unchanged**, with the V1 thresholds, after the sample floor
was met. No threshold was moved, no branch was deleted, no symbol or session was
dropped in response to these numbers.

---

## 2. Architecture (frozen before replay)

A preregistered **A/B branch model**, selected on market-mechanism reasoning, not
on outcome:

| Branch | Event | Mechanism | Target authority |
|---|---|---|---|
| `A_SWEEP_RECLAIM_REVERSAL` | Interaction bar trades beyond a reference boundary and **closes back inside** | Failed auction — liquidity taken, price rejected | `OPPOSITE_REFERENCE_BOUNDARY` |
| `B_BREAKOUT_RETEST_CONTINUATION` | Interaction bar **closes beyond**; an M5 retest returns to the broken level and still closes on the breakout side | Accepted auction — level flips to support/resistance | `NEXT_CLOSED_H1_LIQUIDITY_POOL` |

The two branches **partition one event** and are disjoint by construction, so
pooled = A + B and no selection occurs between them. A third architecture
(`C_TIME_OF_DAY_MOMENTUM_IGNITION`) was `REJECTED_AT_DESIGN_TIME` because it has
no location mechanism and would have amounted to a clock search.

**Three mechanism fixes aimed at V1's measured attrition:**

1. **Trigger.** Direction is now *endogenous to the event*. V1 lost 11,195
   decidable opportunities (≈89%) to `NEUTRAL_DIRECTION` from an MTF direction
   gate. In V2, D1/H4/H1 structure, premium/discount and regime are **strata,
   never gates** — enforced by an AST test.
2. **Confirmation.** Exactly **one** condition: the first closed-M5 MSS/BOS in
   the event direction before session expiry. V1's displacement-body ratio, FVG
   and FVG-retrace age windows were **removed, not relaxed**
   (`EXCLUDED_V1_TUNING`).
3. **Target.** Mechanical, from causally-known liquidity/location. 5R is
   **diagnostic only** and is never a target authority.

---

## 3. Funnel — 26,814 opportunities

| Stage | N | % previous | % opportunities |
|---|---:|---:|---:|
| OPPORTUNITY | 26,814 | — | 100.00 |
| S1_CONTEXT_ELIGIBLE | 12,602 | 47.00 | 47.00 |
| S2_LOCATION_ELIGIBLE | 12,571 | 99.75 | 46.88 |
| S3_SESSION_EVENT | 11,384 | 90.56 | 42.46 |
| S4_SWEEP_OR_BREAKOUT | 11,171 | 98.13 | 41.66 |
| S5_RECLAIM_OR_RETEST | 5,730 | 51.29 | 21.37 |
| S6_STRUCTURE_CONFIRM | 2,078 | 36.27 | 7.75 |
| S7_ENTRY_AVAILABLE | 2,078 | 100.00 | 7.75 |
| S8_GEOMETRY_VALID | 1,934 | 93.07 | 7.21 |
| S9_TRADE_COMPLETED | 1,934 | 100.00 | 7.21 |

`PRIMARY_FUNNEL_WEAKNESS = S1_CONTEXT_ELIGIBLE` (14,212 lost, 53.0% of all
opportunities), dominated by `REFERENCE_INSUFFICIENT_BARS` (14,196). **This is a
data-coverage property, not a rule weakness**: the reference session needs ≥16
M15 bars, and early-corpus years plus weekends simply do not have them. It is
reported as a diagnosis and was **not** used to justify changing any rule inside
this mission.

The largest *behavioural* losses are S5 (5,441 — the market swept or broke out
but never reclaimed or retested) and S6 (3,652 — reclaim/retest occurred but no
MSS/BOS followed before expiry).

---

## 4. V1 → V2 comparison (diagnostic only)

V1 is closed evidence: not re-run, not re-tuned, not re-interpreted. The
opportunity basis is deliberately identical, so this compares **architecture**,
not a changed denominator.

| Metric | V1 | V2 | V2/V1 |
|---|---:|---:|---:|
| Opportunities | 26,814 | 26,814 | 1.00 |
| Event / trigger passes | 441 | 11,171 | 25.33 |
| Confirmations | 51 | 2,078 | 40.75 |
| Entries | 35 | 2,078 | **59.37** |
| Entry yield / 1,000 | 1.31 | 77.50 | 59.37 |
| Median natural target R | 1.004 | 1.242 | 1.24 |
| 1R capability | 0.4286 | 0.5165 | 1.21 |
| 2R capability | 0.2857 | 0.3325 | 1.16 |
| 3R capability | 0.2571 | 0.2291 | 0.89 |
| 4R capability | 0.0571 | 0.1608 | 2.81 |
| 5R capability | **0.0000** | **0.1163** | — |

**DID V2 SOLVE STRUCTURAL STARVATION? YES.** `ENTRY_AVAILABLE_N = 2,078` against
a preregistered floor of 100 (`SAMPLE_GATE = PASS`). V1's `TARGET_MODEL_MISMATCH`
is also addressed: 5R went from structurally unreachable (0/35) to 11.6% of
1,934 trades. Note 3R capability *fell* slightly — V2 trades a much larger and
less selected population, which is the expected cost of removing the gates.

---

## 5. Pre-OOS robustness gate — `PRE_OOS_ROBUSTNESS_GATE_V1`, unchanged

Run because the sample floor was met. Expectancy metric: realised structural R
per completed trade (target → +natural_target_R, stop → −1R, horizon →
mark-to-close R). **No friction is modelled.** Fail-closed semantics.

| Axis | Result | Evidence |
|---|---|---|
| WALK_FORWARD | **PASS** | 10/15 qualifying monthly folds positive (0.667 ≥ 0.60) |
| YEAR_STABILITY | FAIL | 7/13 years positive (0.538 < 0.60); relative spike 3.13 > 2.0 |
| SYMBOL_STABILITY | FAIL | 2/4 positive (0.50) |
| SESSION_STABILITY | FAIL | 1/2 positive (0.50) |
| BRANCH_STABILITY | FAIL | 1/2 positive (0.50) |
| REGIME_STABILITY | FAIL | 1/2 positive (0.50) |
| TAIL_DEPENDENCE | FAIL | −0.0042 R pooled; −0.0118 without the best trade; **−0.1915** without the best 5% (97 trades) |
| BOOTSTRAP | FAIL | 5,000 resamples, seed 20251005: CI₉₅ **[−0.0619, +0.0550]**, point −0.0042 |
| CONCENTRATION | FAIL | one branch supplies 70.9% of gross gain, one session 61.7% (limit 50%) |
| STRUCTURAL_CAPABILITY | FAIL | reach_1R 0.5165 ≥ 0.50 ✓ but reach_3R 0.2291 < 0.25 ✗ |
| FRICTION_READINESS | PASS | disclosed, `ECONOMIC_EDGE = NOT_ESTIMABLE`, no substitute values |
| DATASET_ROLE_VALIDATION | PASS | all reads DEVELOPMENT; OOS_OPENED=NO; HOLDOUT_TOUCHED=NO |
| CANDIDATE_IDENTITY_VALIDATION | PASS | all contract hashes recomputed and equal; no historical-id collision |
| PARAMETER_NEIGHBORHOOD | **NOT_APPLICABLE** | V2's parameter vector is empty — nothing to perturb |

### A note on PARAMETER_NEIGHBORHOOD

V2 has no free numeric parameter, so there is no neighbourhood to perturb and no
parameter sensitivity to measure. The axis is recorded as
`NOT_APPLICABLE_EMPTY_PARAMETER_VECTOR` with `counts_toward_pass = false` rather
than silently marked PASS. A reviewer who disagrees should treat the gate as
*incomplete* on that axis. It does not change the verdict here — nine decisive
axes failed regardless.

### A note on YEAR_STABILITY

V1 could only run an intra-year quarterly *substitution*, because its authority
covered a single calendar year (2017), carrying the standing limitation
`YEAR_COVERAGE_LIMITED_SINGLE_CALENDAR_YEAR_2017`. V2 runs **true calendar-year
stability** across 18 DEV years, so that limitation no longer applies. This is a
strengthening of the gate, declared here because it is a change in what the axis
measures — but the *pass rule* (≥0.60 positive fraction, ≤2.0 relative spike) is
the frozen V1 rule, unchanged.

---

## 6. Heterogeneity — reported, not pruned

Per the standing constraints, losing strata are reported and kept. Nothing below
was deleted, down-weighted, or excluded.

**By branch** (both `BRANCH_POWERED`, n ≥ 30):

| Branch | Entries | Completed | Expectancy R |
|---|---:|---:|---:|
| A_SWEEP_RECLAIM_REVERSAL | 1,378 | 1,306 | **+0.0358** |
| B_BREAKOUT_RETEST_CONTINUATION | 700 | 628 | **−0.0875** |

**By symbol:**

| Symbol | Completed | Expectancy R |
|---|---:|---:|
| EURUSD | 531 | +0.0883 |
| USDJPY | 501 | +0.0068 |
| GBPUSD | 482 | −0.0459 |
| XAUUSD | 420 | −0.0865 |

Branch A looks better than branch B, and EURUSD better than XAUUSD. **Dropping
branch B or trading only EURUSD is exactly the post-hoc selection this mission
prohibits.** The A/B split was preregistered as a *partition* precisely so that
pooled performance — not the better half — is the result. Those spreads are also
well inside the bootstrap noise band of the pooled estimate.

---

## 7. Interpretation

V2 was designed to answer one question — *can this family of session hypotheses
produce a usable sample at all?* — and it answered yes, decisively. The three
mechanism fixes each did what they were predicted to do: removing the MTF
direction gate recovered the 89% `NEUTRAL_DIRECTION` loss, the single-condition
confirmation lifted confirmations 40×, and the mechanical target made 5R
reachable for the first time.

What the larger sample then revealed is that **the V1 funnel was not hiding an
edge, it was hiding the absence of one.** With 35 trades, V1's +0.43 1R rate was
unfalsifiable. With 1,934 trades, the same structural family measures
break-even, and the gain that does exist is concentrated in one branch and one
session rather than distributed.

This is a more informative negative result than V1's. V1 ended in
`INSUFFICIENT_SAMPLE` — the statistical equivalent of no answer. V2 ends with a
real measurement: on DEVELOPMENT data, with zero friction assumed and a
preregistered rule set, this architecture has no detectable structural edge.

**No remedial tuning was performed and none should be.** The honest next step is
not a V2.1; it is either a different hypothesis family or acceptance that
reference-session boundary interaction on these four symbols is efficiently
priced.

---

## 8. Governance

- Phase 0 verification: **14/14 PASS** (`phase0_governance_verification.json`).
- The preregistration was committed **separately, at `6ae179a`, before any V2
  replay executed.** The strategy module hash was re-verified at freeze time and
  again at replay time; the runner hard-stops on `STRATEGY_IDENTITY_MISMATCH`.
- V1 artifacts were read-only throughout. V1 evidence sha256
  `46393c519c2d6a674b348b5796dc460bb6f074b47a5eb30cf717bb2aa6913235`.
- All Sep–Dec OOS windows remain **FRESH**; the sealed holdout remains
  **UNTOUCHED**; the OOS access log records zero events under R2.
- Large per-trade evidence is an external CAS pointer only:
  `data/external/gen2_ald_v2/candidate_ledger.jsonl.gz`.
- `LIVE_EXECUTION = NO`, `BROKER_MUTATION = NO`. No execution code was imported.

## 9. Artifacts

`data/artifacts/gen2_asian_liquidity_displacement_v2/` — `final_report.json`,
`funnel_report.json`, `attrition_reasons.json`, `target_capability.json`,
`branch_report.json`, `strata_report.json`, `v1_vs_v2.json`, `sample_gate.json`,
`pre_oos_gate_result.json`, `dataset_binding.json`, `preregistration.json`,
`candidate_instance_identity.json`, `phase0_governance_verification.json`,
`artifact_manifest.json`, plus `year_matrix.csv`, `symbol_session_matrix.csv`,
`branch_matrix.csv`.
