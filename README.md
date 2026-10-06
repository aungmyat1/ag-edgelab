# AG EdgeLab

Standalone, strategy-agnostic research system for rapidly checking, diagnosing, optimizing, and edge-verifying unverified trading strategies under fail-closed evidence governance.

> **Primary objective:** take an `UNVERIFIED` strategy with explicit rules, measure its funnel on DEVELOPMENT data, identify which rules improve or damage economic quality, run controlled rule experiments quickly, freeze the first candidate that satisfies the promotion gates, and move that immutable candidate through Edge Verification as efficiently as possible without weakening OOS, friction, provenance, or holdout controls.
>
> **Canonical mental model:** `UNVERIFIED STRATEGY -> CHECK RULES -> FUNNEL DIAGNOSIS -> CONTROLLED DEVELOPMENT OPTIMIZATION -> PROMOTION GATE -> FREEZE -> EDGE VERIFICATION -> EDGE_VERIFIED | NO_EDGE | INSUFFICIENT_EVIDENCE`. The system is optimized for fast falsification and fast promotion of genuine survivors, not for making every strategy pass.

## Start here — code agents

Before implementing or auditing EdgeLab, read:

1. `README.md` — project authority, terminology, lifecycle and invariants.
2. `docs/ARCHITECTURE.md` — canonical system boundaries and component contracts.
3. `docs/FUNNEL_MODEL.md` — real six-phase strategy funnel, scoring and weak-funnel semantics.
4. `docs/FUNNEL_DEVELOPMENT_AND_EDGE_VERIFICATION_ROADMAP.md` — MVP-to-production implementation sequence.
5. `docs/AGENT_IMPLEMENTATION_GUIDE.md` — rules for implementation agents and definition of done.

If code and documentation disagree, **do not silently reinterpret strategy or verification authority**. Stop, report the conflict, and resolve it explicitly.

## Product architecture

```text
                    AG EDGELAB
                        |
        +---------------+----------------+
        |                                |
        v                                v
FUNNEL DEVELOPMENT ENGINE        EDGE VERIFICATION ENGINE
        |                                |
DEVELOPMENT data                 frozen candidate only
        |                                |
market data -> funnel            authorized unseen evidence
        |                                |
measure phase/rule flow          recompute evidence
        |                                |
find weak candidates             OOS / statistics / friction
        |                        walk-forward / stability
change versioned rules           regimes / independent parity
        |                                |
repeat                           falsification verdict
        |                                |
PROMISING STRATEGY                       |
        |                                |
        +------> FREEZE -----------------+
                                         |
                     EDGE_VERIFIED | NO_EDGE |
                     INSUFFICIENT_EVIDENCE
```

A good DEVELOPMENT result is **not** `EDGE_VERIFIED`.

## Canonical real strategy funnel

Every strategy is organized by six semantic phases. The phases provide stable structure; the versioned rules inside them define the actual strategy.

```text
STRATEGY
|
+-- CONTEXT
|   +-- strategy-specific rules
|
+-- LOCATION
|   +-- strategy-specific rules
|
+-- TRIGGER
|   +-- strategy-specific rules
|
+-- RISK
|   +-- strategy-specific rules
|
+-- EXECUTION
|   +-- strategy-specific rules
|
`-- OUTCOME / AUDIT
    +-- exit/result rules and outcome measurements
```

Reference structure:

```text
ST_ASIAN_SESSION_V1
|
+-- CONTEXT
|   +-- ASIAN_SESSION_V1
|   `-- H1_BIAS_V1
|
+-- LOCATION
|   `-- ASIAN_RANGE_V1
|
+-- TRIGGER
|   +-- SWEEP_V1
|   `-- DISPLACEMENT_V1
|
+-- RISK
|   +-- RANGE_25_SL_V1
|   `-- RR_GATE_V1
|
+-- EXECUTION
|   `-- ENTRY_RETEST_V1
|
`-- OUTCOME
    +-- TP1_RANGE_V1
    +-- BE_AFTER_TP1_V1
    `-- TP2_5R_V1
```

The graph may branch. The six phases are semantic categories, not a requirement that every strategy be a single linear chain.

## First MVP

The first useful product is intentionally narrow: **Weak Funnel Diagnostic**.

For every filtering rule/phase, record at least:

```text
input_n
pass_n
fail_n
flow_pct
pass_final_win_rate
fail_final_win_rate
parent_final_win_rate
delta_win_rate_vs_parent
selection_effect_pct
diagnostic_label
```

Initial labels:

- `IMPROVING`
- `NEUTRAL`
- `WEAK_FUNNEL_CANDIDATE`
- `INSUFFICIENT_SAMPLE`

A weak-funnel label is a DEVELOPMENT diagnostic, not proof of causality and not an edge verdict. V0.2 adds expectancy/PF/DD so a lower win rate cannot by itself be treated as worse economics.

## Primary workflow — rapid edge verification

The main operating workflow starts from an **unverified strategy**, not from an assumption that its current rules are correct:

```text
UNVERIFIED STRATEGY
 -> normalize explicit rule contract
 -> run DEVELOPMENT funnel
 -> measure phase/rule attrition + economics
 -> identify weak or non-contributing rules
 -> create a declared child experiment
 -> change one rule or one preregistered rule bundle
 -> rerun the same authorized DEVELOPMENT population
 -> compare parent/child on expectancy, PF, DD, sample size and stability
 -> reject regressions quickly
 -> retain only improvements that survive the DEVELOPMENT promotion policy
 -> repeat within a preregistered search budget
 -> PROMOTION GATE
 -> FREEZE EXACT CANDIDATE
 -> PRE-OOS
 -> authorized fresh OOS
 -> measured friction/economic verification
 -> stability / regime / independent parity as required
 -> EDGE_VERIFIED | NO_EDGE | INSUFFICIENT_EVIDENCE
```

**Speed objective:** minimize time from `UNVERIFIED` to a trustworthy terminal verdict. Cheap DEVELOPMENT diagnostics and batch experiments should reject weak rules early; expensive OOS and independent verification are reserved for frozen survivors.

**Optimization boundary:** optimization is allowed only on authorized DEVELOPMENT evidence. Never mutate a parent strategy in place. Every behavior-changing rule modification creates a new rule/funnel identity and is recorded in the candidate/search ledger. Search pressure, tested variants, and failed children are evidence and must not be hidden.

**No rescue-by-OOS:** OOS and sealed holdout are verification evidence, never optimization data. A failed OOS candidate is rejected under its frozen identity; it is not tuned against the same unseen window and resubmitted as though fresh.

## Verification boundary

After freeze, strategy optimization stops. Verification receives immutable strategy/evidence identities and recomputes authoritative metrics from canonical evidence.

Production direction:

```text
FROZEN STRATEGY
 -> authorized unseen OOS
 -> statistical/bootstrap evidence
 -> friction
 -> walk-forward
 -> parameter/rule stability
 -> regime robustness
 -> independent engine parity
 -> exposure/provenance checks
 -> EDGE_VERIFIED | NO_EDGE | INSUFFICIENT_EVIDENCE
```

`NO_EDGE` requires coherent negative evidence. Missing, malformed, unresolved or provenance-incoherent evidence fails closed as `INSUFFICIENT_EVIDENCE`.

## Open-source reuse

Do not build another complete trading platform. Reuse external systems behind adapters where useful:

- pandas / NumPy — market and result processing
- Backtesting.py — initial lightweight simulation where semantics fit
- vectorbt — later fast DEVELOPMENT experiments
- Freqtrade — later crypto research and lookahead/recursive diagnostics
- QuantConnect LEAN — later independent event-driven parity

External engines are evidence producers, never EdgeLab verification authority.

## Non-negotiable invariants

- research only
- no broker credentials or broker mutation
- no order placement
- no Demo/Live execution authority
- no sealed holdout access from Funnel Lab
- no look-ahead data access
- complete candidate ledger, including rejected candidates
- deterministic ordering and identities
- DEVELOPMENT may modify strategy; verification may not
- every behavior change creates a new strategy identity
- caller aggregate metrics are non-authoritative at verification
- only production verification policy may issue `EDGE_VERIFIED`

## Current direction

The project is now **verification-throughput oriented**. Infrastructure exists to support rigorous falsification; the next priority is to shorten the safe path from an unverified strategy to an edge verdict.

The operating priority is:

`UnverifiedStrategy -> RuleContract -> Funnel diagnostics -> DEVELOPMENT optimization/search -> economic + robustness promotion gate -> FrozenStrategy -> PRE-OOS -> fresh OOS -> measured friction -> final verification`.

Development work should therefore prioritize:

1. fast deterministic replay and cached reusable market/feature computation without changing strategy semantics;
2. generic stage adapters so each strategy can expose detailed funnel stages without hard-coding strategy logic into the universal analyzer;
3. batch DEVELOPMENT experiments with explicit search budgets and multiple-testing controls;
4. automatic weak-rule diagnostics using expectancy/PF/DD/sample/stability evidence, not win rate alone;
5. measured friction and authoritative real-data adapters needed to unblock economic verification;
6. one-click generation of a frozen candidate/evidence manifest when promotion gates pass.

The target is **not maximum backtest performance**. The target is the shortest governed route to a trustworthy `EDGE_VERIFIED`, `NO_EDGE`, or `INSUFFICIENT_EVIDENCE` verdict.

See `docs/FUNNEL_DEVELOPMENT_AND_EDGE_VERIFICATION_ROADMAP.md` for detailed work packages and the Edge Validator upgrade sequence.

## Governance (Consolidation R1)

The repository is governed by append-only, hash-pinned records. Before any
candidate work, OOS access, or merge decision, consult:

- `config/governance/candidate_ledger.json` — every candidate's verdict
  (the C3 rejection record is permanent and append-only)
- `config/governance/oos_access_log.json` — THE authoritative OOS log
  (duplicate use fails closed; sealed holdouts stay sealed)
- `config/governance/friction_authority_gap.json` and
  `config/governance/data_authority_gap.json` — what evidence is missing
  and the contracts for filling it (never invent values)
- `config/governance/edge_status_vocabulary.json` and
  `config/governance/ticket_integration_contract.json` — status vocabularies
  and the ticket data contract (execution stays separately governed)
- `config/governance/canonical_subsystems.json` — the single selected
  authority per subsystem
- `config/consolidation/branch_inventory.json` and
  `config/consolidation/integration_graph.json` — every branch's
  classification and every merge decision's rationale
- `config/governance/external_artifact_registry.json` +
  `scripts/verify_external_artifacts.py` — content-addressed pointers for
  large evidence (7/7 verified)
- `CONTRIBUTING.md` — agent and size governance rules
- `docs/CONSOLIDATION_R1.md` — the consolidation record

The governance records are locked by
`tests/test_governance_consolidation_r1.py`.
