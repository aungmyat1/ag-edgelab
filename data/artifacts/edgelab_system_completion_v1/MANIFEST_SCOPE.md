# artifact_manifest.json — authority boundary

`artifact_manifest.json` (ARTIFACT_MANIFEST_V1) is the sealed snapshot of the
17 EdgeLab System Completion V1 base outputs added in 84414f4
(`producer_commit` 35723e5, `schema_version` EDGELAB_SYSTEM_COMPLETION_V1).
All 17 entries verify byte-exact (sha256 + byte_size) against the committed
blobs.

Remediation and acceptance records added afterwards are intentionally outside
that manifest and are not registered in it:

- 129dd55: `edgelab_remediation_summary.json`, `python312_environment.json`,
  `system_acceptance_regression.json`, `v0_5_lineage_resolution.json`,
  `zero_variance_contract_validation.json`
- 419f28b: `system_acceptance_regression_v2.json` (supersedes
  `system_acceptance_regression.json`, which is preserved unchanged)

Basis: the 129dd55 remediation left the manifest untouched, and no code,
script or test in this repository reads this manifest, so registering later
records would rewrite a sealed snapshot without any consumer requiring it.
Each later record carries its own identity (tested SHA/tree, CI run id).
