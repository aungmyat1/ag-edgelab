# ag-edgelab — Contribution & Agent Governance

These rules govern every human and agent contribution. They exist to keep
research evidence trustworthy: append-only verdicts, hash-pinned data,
one OOS authority, and no silent execution capability.

## Research integrity (non-negotiable)

1. **Consult the ledgers before acting.** Before defining, freezing, or
   evaluating any candidate, read
   `config/governance/candidate_ledger.json` and
   `config/governance/oos_access_log.json`. A rejected candidate is
   evidence; its record is append-only and may never be edited to rescue
   the candidate.
2. **OOS access is logged and fail-closed.** One OOS opener at a time.
   The mainline `oos_access_log.json` is authoritative: duplicate OOS use
   for the same candidate identity must fail closed, and the sealed
   holdout windows stay sealed unless a governance mission unseals them.
3. **Never invent values.** Friction, dataset, and horizon numbers come
   from pinned authorities or they do not exist. When authority is
   absent, fail closed and report `NOT_ESTIMABLE`.
4. **Execution is not research.** No demo/live order-sending capability
   may be added by a research or consolidation mission. Execution
   permissions are governed separately (see
   `config/governance/ticket_integration_contract.json`).

## Branch & agent rules

5. **Max 2 active branches per agent.** An agent with two open research
   branches must close or merge one before opening another. Historical
   research branches are archived, never deleted blindly.
6. **New research requires an explicit candidate identity** (id +
   version + canonical-contract sha256) committed before dataset
   evaluation begins. Anonymous "exploration" branches cannot produce
   citable results.
7. **One candidate lane per research agent** — one strategy family under
   investigation at a time, so DEV evidence cannot be silently shared
   across lanes.
8. **One OOS opener at a time.** Before opening OOS data, verify in the
   access log that no other open event is in flight and that your
   candidate's preregistration hash is committed.

## Size rules

9. **Large generated evidence does not belong in normal git history.**
   Bulky replay ledgers and large intermediate evidence are externalized
   with content-addressed pointers in
   `config/governance/external_artifact_registry.json`
   (see `scripts/verify_external_artifacts.py`). Retain in-tree only:
   source, tests, contracts, schemas, manifests, preregistrations,
   `final_report.md`, small `final_report.json`, hash pointers, and
   evidence required by runtime tests.
10. **PR source-code delta target < 2,000 lines** unless the change is
    an architectural one with owner approval (state which). Artifact-only
    changes are reviewed separately from code changes.
11. **Raw datasets are never committed.** They live outside git with
    sha256 pins (see `scripts/acquire_histdata_fx_2017.sh` for the
    pattern).

## Process rules

12. **Run the full test suite after every integration step.** If the
    test count drops unexpectedly, STOP and investigate before
    continuing. Zero-reduction applies to R8.1 authority protections,
    strategy identities, dataset hashes, candidate verdicts, and the OOS
    log.
13. **Merges must be justified by supersession/authority analysis**, not
    by size. Record every merge decision in
    `config/consolidation/integration_graph.json`.
14. **PRs are closed only with a recorded merge or supersession reason**
    (e.g. "superseded by X", "merged via Y", "deliberately excluded:
    execution capability").

## Edge status in tickets and reports

15. Always report BOTH `edge_status`
    (`UNVERIFIED | INSUFFICIENT_EVIDENCE | NO_EDGE | EDGE_VERIFIED`) and
    `verification_stage` (lifecycle). Never collapse different failure
    modes into one label — see
    `config/governance/edge_status_vocabulary.json`.
