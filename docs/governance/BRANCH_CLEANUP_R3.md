# Branch Cleanup R3

Rechecked against `origin/main` at `7772b5e221d4fa2ca2cbabb5619cec7ff1e404cc`
on 2026-10-06. Counts below are `git rev-list --count origin/main..origin/<branch>`.
GitHub PR states were queried with authenticated `gh`; no branch is deleted
while an open PR exists.

## Group A: merged

Every listed branch has 0 commits ahead. PR state was verified as merged or no
PR; these branches are eligible for `archive/<branch>` tags followed by remote
deletion after this manifest PR merges.

| Branch | Ahead | PR state |
| --- | ---: | --- |
| `codex/conduct-adversarial-audit-for-pr-#6` | 0 | Merged #7 |
| `feat/r0-foundation` | 0 | Merged #1 |
| `feat/r3-r7-funnel-optimization-production` | 0 | Merged #6 |
| `integration/r0-foundation-into-main` | 0 | Merged #8 |
| `feat/universal-three-funnel-analyzer-v0-2` | 0 | Merged #13 |
| `fix/zero-variance-test-contract` | 0 | No PR |
| `consolidation/r2-gen2` | 0 | Merged #19 |
| `consolidation/r2c-records` | 0 | Merged #20 |
| `plan/funnel-optimizer-6h-acceleration` | 0 | Merged #21 |
| `arena/01a1007a-ag-edgelab` | 0 | Merged #9 |
| `arena/01a100ce-ag-edgelab` | 0 | Merged #10 |
| `arena/01a1015a-ag-edgelab` | 0 | Merged #11 |
| `arena/01a101e6-ag-edgelab` | 0 | Merged #12 |
| `arena/01a1041d-ag-edgelab` | 0 | No PR |
| `arena/01a105f9-ag-edgelab` | 0 | Merged #14 |
| `arena/01a1073e-ag-edgelab` | 0 | Merged #15 |
| `arena/01a10816-ag-edgelab` | 0 | Merged #16 |
| `arena/01a10a59-ag-edgelab` | 0 | Merged #17 |
| `arena/01a10add-ag-edgelab` | 0 | Merged #18 |
| `arena/684d3674-ag-edgelab` | 0 | Merged #23 |
| `arena/f020a01b-ag-edgelab` | 0 | Merged #22 |

## Group B: owner approval required

| Branch | Ahead | PR state | Decision |
| --- | ---: | --- | --- |
| `feat/fx-cycle2-breakout` | 1 | No PR | Tag only; retain branch |
| `feat/fx-asian-sweep-candidate` | 2 | No open PR | Tag only; retain branch |
| `feat/fx-edge-candidate` | 2 | No PR | Tag only; retain branch |
| `feat/fx-lny-candidate` | 2 | No PR | Tag only; retain branch |
| `feat/crypto-btc-breakout-candidate` | 2 | Closed #5 | Tag only; retain branch |
| `feat/crypto-btc-h1-candidate` | 2 | No PR | Tag only; retain branch |

`OWNER_APPROVAL_B=NO`; no Group B branch is deleted. The requested registry
append is blocked by the frozen-identity rule: the current
`candidate_contamination_registry.json` SHA-256 is
`b0ea16c07f43edd79db81acafdd7e6284a733b7979666ce491d0678f451843b0`, exactly
the value pinned in `candidate_ledger.json`. The registry is not modified.
Only the existing Asian-sweep reference is present in that registry; the other
five requested branch records remain an owner decision.

## Group C: salvage review

| Branch | Ahead | PR state | Decision |
| --- | ---: | --- | --- |
| `feat/crypto-btc-spot-candidate` | 3 | No PR | No extraction: the branch's acquisition is embedded in its screening script; the consolidation inventory documents missing gap validation and provenance. |
| `feat/crypto-btc-economic-verification` | 8 | No PR | No extraction: its Bybit verifier embeds acquisition and timestamp parsing; the consolidation inventory documents missing-bar and byte-provenance/checksum gaps. |
| `feat/r2-robustness` | 4 | Closed #3 | Salvage deterministic Monte Carlo into `src/ag_edgelab/statistics/`; main already contains equivalent R-based performance metrics. |
| `feat/strategy-verification` | 10 | Closed #4 | `SUPERSEDED`: main has the shared R metrics and current `verification/` authority. |
| `ci/edgelab-py312-acceptance` | 3 | No PR | CI-only workflow; latest run for branch tip `eccac6cb14af592e8437ffda04a7a8ab3e0b1d4f` succeeded (run 37273523946). Include the workflow; archive the branch after merge. |

The two crypto donor screens are not copied because the requested narrow
download-only extraction would bypass the repository's recorded data-quality
and provenance objections. No candidate, evidence, or OOS files were opened.

## Group D: parked

`feat/r1-nautilus-adapter` is retained unchanged per the Consolidation R1
decision (5 commits ahead; PR #2 is closed).

## Unlisted refs and counts

The initial inventory contained 34 remote heads including `main`. Two refs
appeared during this work and are not in the supplied groups:

- `governance/r3-causal-policy-freeze-r1` has open PR #24; preserve it. This
  maintenance task does not inspect or change its R3 work.
- `arena/2c6637fd-ag-edgelab` has no listed PR or mission classification;
  preserve it and request owner disposition before archival.

After removing the temporary Phase 1 branch, 36 remote heads were observed.
The generated branch inventory was refreshed to reflect this live count. The
Phase 1 report workflow is registered on GitHub, but manual dispatch returned
HTTP 403 (`Resource not accessible by integration`); a hosted report run is
therefore not yet verified.

## Integrity

No candidate ledger, external artifact registry, OOS access log, frozen path,
or file whose hash is pinned by those records was edited. Frozen bytes changed:
0. No OOS or holdout data was opened.