# V2.1 Preregistration — Independent Audit Brief

**STOP POINT A.** No replay has been run under this contract and none may be
run until this audit completes.

| | |
|---|---|
| STRATEGY_ID | `ST_ASIAN_LIQUIDITY_DISPLACEMENT_V2` |
| STRATEGY_VERSION | `2.1.0-research` (supersedes `2.0.0-research`) |
| EXPERIMENT_ID | `GEN2_ALD_V2_1_DEV_R2` |
| PREREGISTRATION_COMMIT | `5b7d00041e1daa96ffec26db9677c2ffda9661c4` |
| CONTRACT_HASH | `2c5cfa8c1608cbed20d66606292bb90c6049310665afc59ee5079ce86bbb86d9` |
| PREREGISTRATION_HASH | `3dac1c0c3bcf9cf3404218690e0caf6681be57a5c596f93adb144392dea669ba` |
| DATASET_BINDING_HASH | `d030952440d2cfa34f541fff7cdfbf344fdc4959d0ee3826ba349636d566b483` |
| Tests | 105 collected / 105 passed / 0 failed |

---

## The thing an auditor should attack first

**This contract was written after I had already seen a development replay of
the prototype on the same partition.** `LOOK_INDEX = 2` is recorded in the
identity contract for exactly that reason.

The hazard is concrete. The 2.0.0 prototype had an *empty* parameter vector.
Hardening it — as the mission requires — necessarily **introduces** magnitudes
(`reclaim_max_bars`, `acceptance_close_count`, `min_natural_r` and others).
Every one of those numbers was chosen by someone who already knew that the
prototype measured roughly break-even. That is the textbook setup for
unconscious selection.

What I did about it, all of which is checkable:

- Each magnitude is derived in `PARAMETER_PROVENANCE` from a mechanism, a
  clock already in the contract, or a minimality argument.
- No R1 artifact was read or scanned while choosing any value, and no value
  was varied to observe its effect.
- R1's numbers are deliberately **not quoted** in the preregistration, so no
  magnitude can be traced back to them.
- The two genuinely discretionary values are named in
  `DISCRETIONARY_MAGNITUDES` rather than left for a reviewer to discover.

**None of that is proof.** Provenance arguments are written by the same person
who picked the numbers. The honest position is that a 2.1.0 result is a second
look at the same data and cannot carry a first look's evidential weight — and
that is why `LOOK_INDEX` must appear in the final return of any replay.

**Recommended auditor action:** challenge the two discretionary values below
directly. If either looks like a preference rather than a derivation, the
contract should be amended *now*, before replay, not after.

| Value | Setting | Defence offered | Weakest point |
|---|---|---|---|
| `RECLAIM_MAX_BARS` / `MSS_LOOKBACK_BARS` / `RETEST_MAX_BARS` | 12 M5 bars = 1 H1 each | H1 is already an exogenous unit of the contract (the target authority reads H1 structure). Confirmation should belong to the same structural bar as the event it confirms. | "One H1" is a clean anchor but not a forced one. 30 minutes or 2 hours would be equally expressible. |
| `ACCEPTANCE_CLOSE_COUNT` | 2 | 1 close cannot distinguish acceptance from a single-print artifact, so it fails to express the concept; 2 is the smallest integer that does. | Minimality is a genuine argument, but "smallest workable" is still a choice among workable options. |

The other magnitudes are, I think, harder to attack: `MIN_SWEEP_TICKS = 1` is
the smallest representable non-zero increment, `RETEST_TOLERANCE = 0` is the
*absence* of a parameter, `MAX_SWEEP_RANGE_FRACTION = 1.0` is the point where
"interaction with a range" stops being true by definition, `MIN_NATURAL_R =
1.0` is where the risk arithmetic changes sign, and `HANDOVER_MAX = 1` is what
stops a state machine from becoming a branch search.

---

## What changed, phase by phase

### Phase 2 — contract identity

The 2.0.0 hash covered a prose summary of the architecture, so several
operative magnitudes could be edited without moving it. 2.1.0 binds every
frozen field through `canonical_json` (sorted keys, no NaN, insertion-order
independent).

Proof obligation discharged by **30 parametrised mutation tests**, one per
frozen field, plus a meta-test (`test_every_mutable_rule_magnitude_is_covered_
by_a_mutation_test`) that fails if a magnitude is ever added to the parameter
contract without a corresponding mutation test. Section-level hashes are
exported so a diff localises what moved.

### Phase 3 — symbol normalization

New `symbol_metadata.py` is the sole authority. `PRICE_UNIT`, `POINT`,
`PIP_SIZE`, `TICK_SIZE` and `digits` are separated for EURUSD, GBPUSD, USDJPY,
XAUUSD.

Two decisions worth reviewing:

- **`pip_size` is forbidden to rules** (`RULE_FORBIDDEN_FIELDS`), enforced by a
  source scan. The gold pip convention is genuinely ambiguous — $1.00, $0.10
  and $0.01 are all used — and an ambiguity must not be allowed to reach a
  research result. Rules use `tick_size` (unambiguous) and dimensionless
  reference-range fractions.
- **Unknown symbols fail closed** (`UnknownSymbolError`) rather than defaulting
  to a tick size.

`validate_observed_precision()` turns the declared metadata into a falsifiable
claim against the feed; it is a hook for replay time, and an auditor should
note it has **not yet been run against the real archives** because this mission
reads no market data.

### Phases 4–5 — state machines

Both branches are explicit, with every transition timestamp recorded.

```
A: BOUNDARY_UNTOUCHED → SWEEP_DETECTED → RECLAIM_PENDING → RECLAIM_CONFIRMED
   → MSS_PENDING → MSS_CONFIRMED → ENTRY_AVAILABLE
B: BOUNDARY_UNTOUCHED → BREAKOUT_DETECTED → ACCEPTANCE_PENDING
   → ACCEPTED_BREAKOUT → RETEST_PENDING → RETEST_CONFIRMED
   → CONTINUATION_CONFIRMED → ENTRY_AVAILABLE
```

Enforced, not merely documented:

- The sweep bar can never be the reclaim bar; the reclaim bar can never be the
  MSS bar; the acceptance bar can never be the retest bar. `_assert_strict_
  order` raises on violation, and there is a test that the assertion fires.
- Causality is tested by **prefix invariance** — decisions taken at bar *k* are
  unchanged when all later bars are deleted — plus a recorder proving the
  structure callback is never queried beyond the confirming bar.
- Structure detection is *injected* (`mss_confirmed_at`, `continuation_
  confirmed_at`), so the state machine owns sequencing and the frozen universal
  library owns detection. An auditor should check the injection is wired to the
  frozen library at replay time; that wiring does not exist yet.

### Phase 6 — natural target authority

Deterministic priority: `OPPOSITE_SESSION_BOUNDARY` → `PRIOR_DAY_HIGH_LOW` →
`CONFIRMED_PRE_ENTRY_SWING_LIQUIDITY`. The first authority yielding a level
strictly beyond entry wins and **selection stops there**, so a richer target
can never be shopped for — there is a test that a 5R later authority does not
displace a 0.5R earlier one.

`MIN_NATURAL_R` is applied **after** selection, never as a selection criterion.
No authority yields a level → `NO_NATURAL_TARGET` → `GEOMETRY_VALID = FALSE`.
Candidates carry the instant they became known and a level known after
`entry_timestamp` **raises** rather than resolves.

The prototype's branch-B `entry ± 2R` fallback is abolished, with a source-scan
test asserting the arithmetic is absent.

### Phase 7 — duplicate event governance

`EVENT_ID = sha256(symbol, date, session, boundary, event_sequence)`. The first
valid signal locks `(symbol, date, session, boundary)`; later signals are
`DUPLICATE_SUPPRESSED` and counted. A↔B handover is permitted only via four
preregistered transitions and at most `HANDOVER_MAX = 1` time.

The handover rule is the one place where a reviewer might reasonably want
*zero* instead of one. The argument for one: a failed sweep that becomes an
accepted breakout is a real, single, mechanically meaningful transition. The
argument for zero: any handover gives one event two chances. I chose one and
capped it; this is a legitimate point of disagreement.

### Phase 8 — friction

`FRICTION_TYPE = UNAVAILABLE`, `ECONOMIC_EDGE = NOT_ESTIMABLE`. Spread,
slippage, commission and swap are `"UNKNOWN"` strings — never `0` — and a test
asserts no substitute default appears anywhere in the serialized contract. A
SCENARIO overlay can never establish `EDGE_VERIFIED`.

### Phase 9 — funnel

All ten stages preserved exactly, reported on three axes (`BRANCH_A`,
`BRANCH_B`, `POOLED`) with N, % previous stage, % original opportunities.

---

## What does NOT yet exist

An auditor should not mistake this for a runnable experiment.

1. **No replay engine for 2.1.0.** The state machines are unit-tested against
   synthetic bars; nothing yet walks the real corpus, builds opportunities, or
   wires the injected structure callbacks to the frozen universal library.
2. **No funnel analyzer for 2.1.0.** The contract specifies the ten stages and
   three axes; the code that emits them does not exist.
3. **`validate_observed_precision` has never met real data.** If the HistData
   archives disagree with a declared tick size, that is a Phase-3 defect that
   will only surface at replay.
4. **The market data itself is absent** from the workspace (gitignored, not
   snapshot-persisted). Replay requires re-running both acquisition scripts.

---

## Governance state

- V1 closed evidence: **untouched** (verified by `git diff` against `874ab7b`).
- GEN2_ALD_V2_DEV_R1 prototype evidence: **untouched**, retained as the
  superseded record. Supersession is on identity/measurement defects, not on
  unfavourable results.
- Sample floor (100) and every `PRE_OOS_ROBUSTNESS_GATE_V1` threshold:
  re-exported **unchanged** from the V1 preregistration.
- `OOS_OPENED = NO`, `HOLDOUT_TOUCHED = NO`, `BROKER_MUTATION = NO`,
  `PARAMETER_OPTIMIZATION = NO`, `V2_DEV_REPLAY_STARTED = NO`.
- The preregistration commit contains **no performance artifact** of any kind
  (verified by filename scan over the commit).
