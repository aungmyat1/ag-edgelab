# CONSOLIDATION R1 — Authoritative Record

**Mission:** consolidate the fragmented EdgeLab repository into one
authoritative mainline without changing any strategy rule, research result,
or verification verdict. No new strategy research, no OOS access, no
parameter changes, no execution capability.

**Status: CONSOLIDATION_COMPLETE.**

## What changed

- **Merged into the mainline** (via the consolidation PR from
  `arena/01a1073e-ag-edgelab`): the STV2/MTF research lineage
  (`arena/01a1015a` ⊃ `arena/01a100ce`, `arena/01a101e6`,
  `arena/01a1041d`), the Universal Three-Funnel Analyzer V0.2
  (`feat/universal-three-funnel-analyzer-v0-2`, selected as the canonical
  strategy-agnostic funnel diagnostic), and the blocked-audit record
  (`codex/conduct-adversarial-audit-for-pr-#6`, docs-only).
- **Deliberately NOT merged:** `feat/r1-nautilus-adapter` (execution
  capability), `feat/crypto-btc-economic-verification` +
  `feat/crypto-btc-spot-candidate` (fail the crypto data-adapter contract:
  no missing-bar validation, no byte-level provenance),
  `feat/strategy-verification` (superseded by main's R8/R8.1 verification
  authority), `feat/r2-robustness` (performance.py superseded via the
  crypto lane; monte_carlo has no canonical consumer), and the seven
  donor-strategy development screens (archived).
- **Governance created** (`config/governance/` + `config/consolidation/`):
  candidate ledger (with the permanent C3 rejection record), OOS access
  log (authoritative, fail-closed), friction authority gap, data authority
  gap (with the crypto contract reviews), edge-status vocabulary, ticket
  integration contract, canonical subsystem selections, branch inventory,
  integration graph, external artifact registry. Locking tests:
  `tests/test_governance_consolidation_r1.py`.
- **Evidence externalized:** the two bulky V0.5 DEV ledgers (15.6 MB) moved
  out of the tree with content-addressed pointers; seven large evidence
  files (2 externalized + 5 in-tree) are hash-pinned and verified by
  `scripts/verify_external_artifacts.py` (7/7 VERIFIED).

## Required return

```
MAIN_BEFORE = af58e2f23e2bd331b220c92180760ca651fdc7ed (main suite: 174 tests)
MAIN_AFTER  = merge commit of the consolidation PR (recorded in the PR and the mission return)
BASE_TEST_COUNT = 465   (pre-consolidation canonical research line, arena/01a1073e@9c94c77)
FINAL_TEST_COUNT = 747  (consolidated tree; zero tests removed;
                          174 foundation + 291 research line + 264 merged lineage
                          tests + 18 governance locks)

CANONICAL_SUBSYSTEMS =
  funnel_analyzer            -> analytics/funnel.py + analytics/diagnostic.py + contracts/diagnostic.py (Three-Funnel Analyzer V0.2)
  verification_authority     -> main R8/R8.1 boundary + c3_v1 frozen verifiers (V0.6.2 pattern)
  r8_1_protections           -> main R8.1 commits (PR#6), locked by adversarial regressions
  friction_framework         -> src/ag_edgelab/friction (framework); VALUES authority MISSING (gap record)
  dataset_acquisition        -> data/fx_histdata_2017.py + acquire_histdata_fx_2017.sh (hash-pinned)
  fx_campaign_engine         -> universal/fx_dev_campaign.py + universal/campaign.py (V0.3 line)
  crypto_data_adapter        -> NONE (no implementation passes the merge contract)
  content_addressed_evidence -> data/fingerprint.py + external_artifact_registry.json + verifier
  candidate_ledger           -> config/governance/candidate_ledger.json (append-only)
  oos_governance             -> config/governance/oos_access_log.json + fail-closed data layer

MERGED_BRANCHES =
  arena/01a1015a-ag-edgelab (contains arena/01a100ce), arena/01a101e6-ag-edgelab,
  arena/01a1041d-ag-edgelab, feat/universal-three-funnel-analyzer-v0-2,
  codex/conduct-adversarial-audit-for-pr-#6   [via the consolidation PR]
  previously in main: feat/r0-foundation, feat/r3-r7-funnel-optimization-production,
  integration/r0-foundation-into-main, arena/01a1007a-ag-edgelab

SUPERSEDED_BRANCHES =
  arena/01a100ce-ag-edgelab (contained in 01a1015a),
  arena/01a105f9-ag-edgelab (ancestor of the consolidation branch),
  feat/strategy-verification (superseded by main R8/R8.1),
  feat/r2-robustness performance.py (superseded via crypto lane)

ARCHIVED_RESEARCH_BRANCHES =
  feat/r1-nautilus-adapter, feat/crypto-btc-economic-verification,
  feat/crypto-btc-spot-candidate, feat/crypto-btc-breakout-candidate,
  feat/crypto-btc-h1-candidate, feat/fx-asian-sweep-candidate,
  feat/fx-cycle2-breakout, feat/fx-edge-candidate, feat/fx-lny-candidate
  (all branches retained; nothing deleted)

CONFLICTS_FOUND = 6
CONFLICTS_RESOLVED = 6  (.gitignore 3-way; funnel.py union;
                          performance.py 3-way divergence; synthetic fixture CSVs;
                          funnel_stage_matrix.csv regeneration; analysis_units.json
                          externalization reversal — full register in integration_graph.json)

C3_LEDGER_STATUS = REJECTED_OOS
C3_OOS_CONSUMED = YES
OOS_ACCESS_LOG = CREATED (2 events: OOS-001 SESSION_TRADE_V2, OOS-002 TARGET_POLICY_C3_V1)
LARGE_ARTIFACTS_EXTERNALIZED = 2
ARTIFACT_HASH_POINTERS_CREATED = 7
FRICTION_AUTHORITY_STATUS = MISSING
MULTIYEAR_FX_DATA_STATUS = NOT_READY
REAL_CRYPTO_DATA_STATUS = INSUFFICIENT (no passing acquisition authority; synthetic lane is not edge evidence)
STRATEGY_RULES_CHANGED = NO
OOS_OPENED = NO (no new OOS access during consolidation; historical events recorded only)
HOLDOUT_TOUCHED = NO
EXECUTION_CAPABILITY_ADDED = NO
STATUS = CONSOLIDATION_COMPLETE
NEXT = MULTIYEAR_DATA_AUTHORITY
```

## Why NEXT = MULTIYEAR_DATA_AUTHORITY

Every candidate on record is rejected or archived (C3 structural OOS
rejection; STV2 economic OOS rejection; MTF DEV rejection). The 2017
single-year lane's OOS window is consumed by two candidate identities and
its holdout is the only untouched window — too precious for ordinary
candidates. A meaningful research generation 2 needs a multi-year data
authority built under the contract in
`config/governance/data_authority_gap.json` (provenance, raw hashes,
timezone normalization, gap/duplicate handling, causal resampling, and
pre-registered DEVELOPMENT / OOS / SEALED_HOLDOUT partitions). Friction
authority remains MISSING and blocks economic claims, but structural
research does not require it; data authority gates everything.
