# GEN2 ALD V2.1 — Replay Infrastructure Audit Brief (Mission 3B-A)

**Status: `BLOCKED_CONTRACT_AMBIGUITY`. `REAL_HISTORICAL_REPLAY_EXECUTED = NO`.**

This brief hands the V2.1 replay infrastructure to the independent auditor. It is
written by the *implementing* agent. Nothing in it is an audit verdict, and the
implementing agent has deliberately not formed one. Where this document says
"verified", it means "a test in this repository asserts it" — that is exactly the
claim an auditor should be re-checking rather than accepting.

This brief supersedes nothing. The STOP-POINT-A brief
(`GEN2_ALD_V2_1_AUDIT_BRIEF.md`) covers the *contract*; this one covers the
*software built to replay it*.

---

## 1. Identity under audit

| Item | Value |
|---|---|
| Implementation commit | `e859206c9c6ba39c266d878739ea1457bfa1c52c` |
| Tree | `f699f7e844c4133634ca7a4e2e8d826ddc65c79c` |
| Preregistration commit | `5b7d00041e1daa96ffec26db9677c2ffda9661c4` |
| `CONTRACT_HASH` | `2c5cfa8c1608cbed20d66606292bb90c6049310665afc59ee5079ce86bbb86d9` |
| `PREREGISTRATION_HASH` | `3dac1c0c3bcf9cf3404218690e0caf6681be57a5c596f93adb144392dea669ba` |
| `DATASET_BINDING_HASH` | `d030952440d2cfa34f541fff7cdfbf344fdc4959d0ee3826ba349636d566b483` |
| `EXPERIMENT_ID` | `GEN2_ALD_V2_1_DEV_R2` |
| `LOOK_INDEX` | **2** |

All three hashes were recomputed live at the start and end of this mission and
match the frozen values. The frozen contract module, the preregistration module
and the preregistration artifact were **not modified** (`git diff` against them
is empty — worth re-confirming independently, since the contract hash is
prose-sensitive and would move on any edit).

**Contamination disclosure, restated:** the 2.1.0 contract was authored *after*
the R1 prototype result on the same DEV partition. Any 2.1.0 number is a
**second look**. That is a property of the design, not of this infrastructure,
and no amount of engineering quality here removes it.

---

## 2. The finding that matters: `CONTRACT_AMBIGUITY_FOUND`

Implementing the contract surfaced **four** places where the frozen text names a
concept but never defines it well enough to determine behaviour. Per mission
instruction the implementing agent did **not** choose a reading. Each is an
un-defaulted policy hook that fails closed.

These are questions for the owner, and they are *material* — each one changes
the reported result on identical data.

### AMB_1 — `OPPORTUNITY_UNIT`
> **Q: Is an OPPORTUNITY one `(symbol, trading_date, session)` or one `(symbol, trading_date, session, boundary)`?**

`OPPORTUNITY` appears in the contract **only** as a funnel stage name. It is the
denominator of every funnel percentage. The event lock keys on
`(symbol, date, session, boundary)`, which admits up to **two** accepted trades
per symbol-day-session; the 2.0.0 prototype counted **one** unit per
`(symbol, day, session)`. The two readings produce different `OPPORTUNITY_N` on
the same bars, and the choice decides whether the V2.1 funnel is comparable to
V1's 26,814 denominator at all.

### AMB_2 — `CONTEXT_ELIGIBLE` / `LOCATION_ELIGIBLE`
> **Q: What predicate defines `CONTEXT_ELIGIBLE`, and what defines `LOCATION_ELIGIBLE`?**

Both are stage names with no operative predicate. In the V1 evidence the
equivalent stage absorbed **53% of all opportunities**, and in the V2 prototype
`S1_CONTEXT_ELIGIBLE` was the `PRIMARY_FUNNEL_WEAKNESS` (14,196 of 14,212 losses
were `REFERENCE_INSUFFICIENT_BARS`). An unfrozen definition here dominates the
funnel shape.

### AMB_3 — `INITIAL_BRANCH_SELECTION`
> **Q: Which branch is attempted first on a boundary interaction — decided by the interaction bar's close (prototype behaviour), by a fixed precedence, or are both run and the earlier `ENTRY_AVAILABLE` taken?**

`PERMITTED_HANDOVERS` presupposes that some branch is tried first, but no rule
selects it. Because `HANDOVER_MAX = 1`, the first branch gets first claim on the
lock, so branch mix — and therefore the branch-stability robustness axis —
depends entirely on this unfrozen choice.

*Note:* whether `HANDOVER_MAX = 1` is itself statistically desirable is **not**
assessed here. That is audit territory and was left alone on purpose.

### AMB_4 — second and third target authorities
> **Q: Define "prior day" (previous calendar day vs previous trading day; UTC vs session day) and define the swing-liquidity derivation (timeframe, and whether `SWING_ORDER = 2` applies).**

`PRIOR_DAY_HIGH_LOW` and `CONFIRMED_PRE_ENTRY_SWING_LIQUIDITY` are ordered in the
authority list but never operationally defined. They set `NATURAL_TARGET_R` for
most of branch B, because for a continuation entry the opposite session boundary
usually lies *behind* the entry and is therefore not a valid target. The
synthetic branch-B fixture demonstrates exactly this fallback.

### How these are handled instead of guessed

- `ReplayPolicy.__post_init__` raises `ContractAmbiguityError` unless **all four**
  ids are explicitly declared resolved. There are no defaults to fall through to.
- `ReplayPolicy` also requires a `provenance` of either `SYNTHETIC_FIXTURE_ONLY`
  or `OWNER_RESOLVED_CONTRACT_AMENDMENT`, else `PolicyProvenanceError`.
- `V21Engine(policy, allow_synthetic=False)` refuses a synthetic policy, and the
  authorization gate independently denies non-owner-resolved provenance. Two
  separate mechanisms must both be defeated for a synthetic reading to touch a
  real partition.
- The replay command therefore terminates `BLOCKED_CONTRACT_AMBIGUITY` today.

Consequently **`CONTRACT_MAPPING_COMPLETE = false`** (30 of 34 contract fields
mapped; 4 blocked). That `false` is the honest value. An auditor should treat
any future flip to `true` that is *not* accompanied by an owner-resolved contract
amendment as a red flag.

---

## 3. What was built

| Module | Role |
|---|---|
| `src/ag_edgelab/strategies/v2_1_engine.py` | State-machine driver, event identity + duplicate lock, handover, natural target engine, geometry engine, outcome engine |
| `src/ag_edgelab/strategies/v2_1_funnel.py` | Funnel taxonomy (8 reporting dimensions), sample gate, 10 robustness axes |
| `src/ag_edgelab/governance/v2_1_data_authorization.py` | Fail-closed authorization gate, six verdicts |
| `scripts/run_gen2_ald_v2_1_replay.py` | The single future command — **built, not executed** |
| `scripts/build_v2_1_infrastructure_artifacts.py` | Emits the evidence artifacts below |
| `tests/fixtures_v2_1.py`, `tests/test_gen2_ald_v2_1_engine.py` | Synthetic fixtures + 71 adversarial / determinism tests |

Transitions are enriched in `v2_1_engine.py`, **not** in the frozen contract
module, specifically to avoid perturbing `CONTRACT_HASH`. Every transition
records `event_id, symbol, trading_date, session, branch, boundary, from_state,
to_state, decision_timestamp, source_bar_timestamp, reason_code`.

---

## 4. Evidence artifacts

All under `data/artifacts/gen2_ald_v2_1/`. None of these use a filename reserved
for a performance result; the preregistration guard test
(`test_no_v2_1_performance_artifact_exists_yet`) still passes, which is the
check that this mission did not smuggle in a result.

| Artifact | Contains |
|---|---|
| `v2_1_contract_implementation_matrix.json` | 30 implemented rows (`contract_field → implementation → test → replay_output`) + 4 blocked rows |
| `event_governance_validation.json` | All 9 mandated event cases |
| `symbol_normalization_audit.json` | 37 classified numeric/pip occurrences, 0 violations |
| `synthetic_determinism_evidence.json` | Two full passes, canonical hashes |
| `infrastructure_build_summary.json` | Build roll-up |
| `audit_handoff_package.json` | Machine-readable form of this brief |

The four evidence artifacts are **byte-identical across rebuilds** (they embed no
timestamp); only the build summary carries a generation time. That is a cheap
reproducibility check an auditor can run directly.

---

## 5. Claims, and how to falsify them

Each row is something an auditor should attack rather than accept.

**Event governance — all 9 cases behave as named.**
`A_SUCCEEDS` (1 accepted, branch A) · `B_SUCCEEDS` (1, branch B) ·
`A_FAILS_THEN_B_HANDOVER` (1 handover, `RECLAIM_TIMEOUT`) ·
`B_FAILS_THEN_A_HANDOVER` (1 handover, `BREAKOUT_REJECTED_CLOSE_BACK_INSIDE`) ·
`A_SUCCEEDS_THEN_B_LATER` and `B_SUCCEEDS_THEN_A_LATER` (1 accepted, 1
suppressed) · `DUPLICATE_REPEATED_CANDLE` (1 accepted, 1 suppressed) ·
`DUPLICATE_BOUNDARY_TOUCH` (**2 accepted** — opposite boundary is a different
lock key) · `SESSION_ROLLOVER` (**2 accepted** — new session is a fresh key).

> ⚠️ **Read this carefully before calling it a bug:** in the "later appears"
> cases the suppressed occurrence carries a *different* `EVENT_ID` from the
> accepted one. That is intended — `EVENT_ID` distinguishes occurrences
> (it includes `event_sequence`), whereas suppression is decided by the **lock
> key** `(symbol, date, session, boundary)`. If the auditor's reading is that
> `EVENT_ID` should itself be the lock key, that is a real disagreement and it
> interacts directly with AMB_1.

**Temporal isolation — no future bar modifies an earlier decision.** Tested by
mutating later bars and requiring the earlier transition ledger to be identical.
Note the constraint that `MarketBar` enforces `high ≥ close ≥ low`, so mutation
bars must remain OHLC-valid; an auditor should check the mutations are actually
*material* and not trivially absorbed.

**Natural targets.** First valid level strictly beyond entry wins, then the
search stops; the level must exist at or before the entry timestamp;
future-confirmed swings are forbidden; absent ⇒ `NO_NATURAL_TARGET` +
`GEOMETRY_VALID = FALSE`. 2R/3R/4R/5R and ATR are never substituted —
`MIN_NATURAL_R = 1.0` is applied *after* selection, never as a fallback target.

**Symbol authority.** 37 occurrences of `0.0001`, `0.00001`, `0.01`, `0.1`,
`pip`, `pips` in the new code were classified; 0 are rule-governing. No universal
FX constant governs XAUUSD or USDJPY; rules consume `tick_size`/`point` only and
`pip_size` stays reporting-only. Caveat worth probing: `at_least_one_tick` has a
half-tick guard, so `0.005` passes for a `0.01`-tick instrument by design.

**Outcome engine.** Same-bar collisions resolve by the frozen
`STOP_FIRST_FAIL_CLOSED_V0_3` authority; a test asserts the stop branch is
evaluated *before* the target, so optimistic sequencing is not reachable. Horizon
is 288 M5 bars. 1R–5R are diagnostics only.

**Robustness.** Ten axes prepared, **not executed on any real corpus**.
`PARAMETER_NEIGHBORHOOD` returns `NOT_APPLICABLE` with
`counts_toward_pass = false` because the prototype parameter vector is empty — it
must never be read as a silent PASS. All gate thresholds are V1's, unchanged.

**Authorization gate.** Pure: a test asserts it performs **no I/O**, so
exercising it cannot record a dataset access. It was run only against mock
registry fixtures, never against the real intended partition. Denial precedence:
`IDENTITY → HOLDOUT → OOS → role → CONTAMINATED → not-permitted →
undeclared-symbol → non-owner-resolved`.

**Determinism.** Two full synthetic passes, canonical-hash identical:
`7491361521425f8ef22175c7aafe2e7c45bf28b096bc17a9d5556aeae9fe6667`.

**Economics.** `FRICTION_TYPE = UNAVAILABLE`, `EDGE_VERIFIED = False`,
`ECONOMIC_EDGE = NOT_ESTIMABLE`. No friction number was introduced and unknown
friction is not treated as zero.

---

## 6. Tests

- **Synthetic / V2.1 suites: 176 passed, 0 failed** (105 contract + 71 engine).
- **Full suite: 1060 passed, 7 failed, 16 skipped.**
- The 7 failures are the **pre-existing baseline**, unrelated to V2.1:
  `test_governance_consolidation_r1::test_all_evidence_pointers_resolve_and_hash_match`,
  3 × `test_stv2_funnel_guards`,
  `test_target_policy_v0_6::test_resolver_establishes_b_over_a`,
  2 × `test_target_v0_5`.
- **`NEW_FAILURES = 0`.** No failure was reclassified as baseline to reach that
  number; the baseline list predates this mission and is unchanged.

One test failed on first run and **the test was wrong, not the engine** — a
"missing target" case had been written with an entry that a synthetic prior-day
level genuinely sat beyond. The fixture was corrected; the rule was not.

---

## 7. What this infrastructure does **not** establish

- It does **not** show the strategy has an edge. No real data was replayed.
- It does **not** resolve the `LOOK_INDEX = 2` contamination hazard.
- It does **not** validate the two named discretionary magnitudes (the three
  1-hour bar budgets, and `ACCEPTANCE_CLOSE_COUNT = 2`).
- It does **not** verify `validate_observed_precision()` against real data —
  that function has still never run against a real corpus.
- It does **not** judge `HANDOVER_MAX = 1`.
- Passing synthetic fixtures is a statement about the *fixtures*. They were
  authored by the same agent that authored the engine, which is a real
  independence limitation an auditor should weigh.

---

## 8. Mission flags

```
REAL_HISTORICAL_REPLAY_EXECUTED = NO     REAL_DEV_READ         = NO
OOS_OPENED                      = NO     HOLDOUT_TOUCHED       = NO
PARAMETER_OPTIMIZATION          = NO     STRATEGY_RULES_CHANGED = NO
BROKER_MUTATION                 = NO     LIVE_EXECUTION        = NO
CLAUDE_AUDIT_STATUS             = PENDING
STATUS = BLOCKED_CONTRACT_AMBIGUITY      NEXT = WAIT_FOR_CLAUDE_AUDIT
```

The replay command exists and is wired end to end:

```
python scripts/run_gen2_ald_v2_1_replay.py --execute-frozen-v2-1
```

Running it today returns `BLOCKED_CONTRACT_AMBIGUITY` and reads no market data.
It cannot proceed until the four AMB questions in §2 receive owner answers — and
those answers belong in an amended, re-hashed contract, not in engine defaults.
