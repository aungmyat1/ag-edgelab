# Codex Adversarial Re-audit R8 — PR #6

## AUDIT_VERDICT = BLOCKED

The requested re-audit target `7f0b061` is not present in this checkout. The selected
branch is `work` at `9ccbe5fa75ff12a708d27edc89a3f50f34962354`, so the nominated artifact
cannot be inspected or authenticated.

## Repository evidence

```text
$ git rev-parse HEAD
9ccbe5fa75ff12a708d27edc89a3f50f34962354

$ git status --short --branch
## work

$ git show-ref
9ccbe5fa75ff12a708d27edc89a3f50f34962354 refs/heads/work

$ git cat-file -t 7f0b061
fatal: Not a valid object name 7f0b061

$ git show -s --format='%H %T %D %s' 7f0b061
fatal: ambiguous argument '7f0b061': unknown revision or path not in the working tree.
```

## Finding

### BLOCKER — R8-B01: nominated re-audit revision unavailable

- **Location:** Git object database; no target file or line is available.
- **Reproduction:** run the commands recorded above.
- **Impact:** authority, fail-closed cases A–X, policy/hash binding, sealed-OOS
  governance, optimization, ablation, stability, walk-forward, regime, friction,
  parity, artifact integrity, look-ahead, execution-boundary, and R8 attacks 1–8
  remain unverified. None is considered passed.

## Final status

- **EDGE_VERIFIED_SINGLE_AUTHORITY:** NOT PROVEN
- **INDEPENDENT_PARITY_PROVEN:** NO
- **BTC_SEPTEMBER_2026_HOLDOUT_ACCESSED:** NO
- **PRODUCTION_RELEASE_READY:** NO
- **NEXT_ALLOWED_ACTION:** provide a checkout whose selected PR #6 branch resolves
  to `7f0b061` (preferably the full commit ID), without exposing the sealed holdout,
  then restart the audit.

