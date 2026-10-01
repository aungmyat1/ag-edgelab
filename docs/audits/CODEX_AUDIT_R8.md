# Codex Adversarial Audit R8 — PR #6

## Audit identity

- **Requested branch:** `feat/r3-r7-funnel-optimization-production`
- **Expected commit:** `24d9c23117e073a180c5633d7fd40d81a8ec20bd`
- **Expected tree:** `6b3bab802aabdf0693c39d40d9c0a17ca38b6943`
- **Available branch:** `work`
- **Available commit:** `0688b222960b175a50c05f6302fbfdbb69f1bd8f`
- **Available tree:** `172347c65deedf2aecc1aacc4875eed5e453f94b`
- **Scope constraint:** audit only; no application or test execution; BTC September 2026 sealed holdout must not be opened or consumed.

## AUDIT_VERDICT = BLOCKED

The exact review object is unavailable in this checkout. Git cannot resolve the expected commit, the
requested branch is absent, and both the checked-out commit and tree differ from the supplied audit
identity. Auditing any other object would not establish properties of PR #6 and would violate artifact
identity requirements. The audit therefore stopped before source review or adversarial execution.

`AUDIT_BLOCKED_BY_HOLDOUT_PROTECTION` is **not** the blocking reason. The sealed holdout was neither
needed nor accessed. The blocker is the missing expected Git object and branch.

## Findings by severity

### BLOCKER — B-01: requested PR revision is unavailable

- **Location:** repository identity, before file-level review (`git` object database; no source line exists).
- **Evidence:** `git rev-parse HEAD` returned `0688b222960b175a50c05f6302fbfdbb69f1bd8f`;
  `git rev-parse HEAD^{tree}` returned `172347c65deedf2aecc1aacc4875eed5e453f94b`;
  `git show 24d9c23117e073a180c5633d7fd40d81a8ec20bd` returned
  `fatal: bad object`; and `git show-ref` listed only `refs/heads/work`.
- **Impact:** policy binding, artifact integrity, authority behavior, and every adversarial property in
  the requested R8 scope are unverifiable for the nominated commit and tree.
- **Reproduction (inspection only):** run `git status --short --branch`, `git rev-parse HEAD`,
  `git rev-parse HEAD^{tree}`, `git show-ref`, and
  `git show -s --format='%H %T %D %s' 24d9c23117e073a180c5633d7fd40d81a8ec20bd`.
- **Required resolution:** provide a checkout in which the requested branch resolves to the expected
  commit and its tree resolves exactly to the expected tree, without exposing or materializing the BTC
  September 2026 sealed holdout.

No CRITICAL, HIGH, MEDIUM, or LOW findings are asserted because the target revision was unavailable.
Absence of such findings is not evidence of correctness.

## Checklist disposition

All items below are **NOT AUDITED / BLOCKED**, not passed:

| Audit area | Disposition |
|---|---|
| Authority model and single-authority decision path | BLOCKED — target unavailable |
| Fail-closed cases A–X | BLOCKED — target unavailable |
| Policy immutability and canonical hash binding | BLOCKED — target unavailable |
| Sealed-OOS governance and exposure-ledger authority | BLOCKED — target unavailable; holdout not accessed |
| Optimization boundary | BLOCKED — target unavailable |
| Ablation | BLOCKED — target unavailable |
| Parameter stability | BLOCKED — target unavailable |
| Walk-forward validation | BLOCKED — target unavailable |
| Regime analysis | BLOCKED — target unavailable |
| Friction analysis | BLOCKED — target unavailable |
| Independent-engine parity | BLOCKED — target unavailable |
| Artifact integrity and content-addressed store behavior | BLOCKED — target unavailable |
| Look-ahead regression controls | BLOCKED — target unavailable |
| Execution boundary | BLOCKED — target unavailable |

## R8-specific attacks

Per the no-execution constraint, no attack was executed. Because the implementation under audit is
also absent, none can be verified by static inspection. Each required failure property remains
**BLOCKED / UNVERIFIED**:

1. **Fabricated strategy/funnel/parameter hashes and fake stability/WF/parity:** not run; rejection and
   `validate_artifact == False` are not established.
2. **Caller-supplied expectancy/PF/DD:** not run; rejection/ignoring in favor of recomputation is not
   established.
3. **Unknown or tampered content hash:** not run; fail-closed behavior is not established.
4. **Self-declared frozen/unseen state and broken ExposureLedger chain:** not run; ledger-only authority,
   broken-chain rejection, and the impossibility of `BURNED_HOLDOUT -> UNSEEN` are not established.
5. **Parity spoof:** unapproved engines, the same engine twice, and identical one-engine fabricated
   trades were not run; rejection is not established.
6. **Threshold or non-canonical policy-hash alteration:** not run; rejection is not established.
7. **Coherent negative evidence:** not run; a `NO_EDGE` result rather than `INSUFFICIENT_EVIDENCE` or
   `EDGE_VERIFIED` is not established.
8. **Trade-list manipulation:** duplicate, future-dated, non-finite, and out-of-window trades were not
   run; rejection is not established.

## Mandatory conclusions

- **EDGE_VERIFIED_SINGLE_AUTHORITY:** NOT PROVEN
- **INDEPENDENT_PARITY_PROVEN:** NO
- **BTC_SEPTEMBER_2026_HOLDOUT_ACCESSED:** NO
- **PRODUCTION_RELEASE_READY:** NO
- **NEXT_ALLOWED_ACTION:** Restore/furnish the exact expected commit and tree on the requested branch
  without opening or copying the sealed holdout, then rerun the complete audit in a fresh environment.
  Do not promote, merge, release, or claim `EDGE_VERIFIED` from this audit.

