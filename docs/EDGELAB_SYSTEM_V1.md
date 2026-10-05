# EdgeLab System V1

EdgeLab is a research-only, fail-closed verification system. Four authority
layers are explicit: **Data Authority** (UTC lineage, raw hashes, partitions and
quality), **Friction Authority** (component-level evidence), **Research
Authority** (candidate identity, contamination and search pressure), and
**Verification Authority** (pre-OOS, OOS, holdout and independent reproduction).

A candidate moves from `RESEARCH_CANDIDATE` through development, a frozen
identity, PRE-OOS, one OOS evaluation, and (only after OOS and economic
authority) a sealed holdout. Candidate identity hashes strategy code,
parameters, funnel and all entry/exit/session contracts, symbols, timeframes,
data partition, friction contract, preregistration and verifier version.
Frozen identities are immutable.

Dataset identity is not freshness identity. The contamination registry is
family/date based; unknown exposure or policy is never fresh. OOS requires a
frozen candidate, valid identity, PRE-OOS PASS, OOS role, fresh family, unused
OOS and preregistration. Holdout additionally requires OOS PASS, sufficient
friction authority, unchanged candidate, unused sealed data and its own
preregistration.

Friction is recorded independently for spread, commission, slippage, swap and
funding as `MEASURED`, `PARTIAL`, `SCENARIO`, `UNAVAILABLE`, or
`NOT_APPLICABLE`. `EDGE_VERIFIED` requires every required component to be
measured or explicitly not applicable; scenario evidence never passes that
check. Current venue evidence is not silently treated as historical truth.

Search/Optuna records are DEVELOPMENT-only and include the search space,
objective, trial count, algorithm, seed and best candidate. The readiness audit
returns only `PASS`, `PARTIAL`, `BLOCKED`, or `FAIL` checks and independently
reports software completeness, operational evidence, OOS economics, and
execution authorization. `SYSTEM_SOFTWARE_COMPLETE` never implies
`EDGE_VERIFIED`, OOS, demo, or live authorization.

Execution is intentionally outside the package. No order placement or broker
mutation is exposed. Large evidence is external and hash-addressed; the
contract-level CAS pointer schema is `artifact_id`, `sha256`, `byte_size`,
`schema_version`, `producer_commit`, `candidate_id`, `dataset_role`, and
`storage_location`.
