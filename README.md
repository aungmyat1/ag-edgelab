# AG EdgeLab

Standalone, strategy-agnostic research system for developing trading strategies as measurable funnels and independently validating frozen candidates for economic edge.

> **Canonical mental model:** market data flows through versioned strategy rules; Funnel Lab measures where candidate quality improves or deteriorates; researchers modify rules only on DEVELOPMENT data; a promising strategy is frozen; the Edge Validator then attempts to falsify that immutable candidate using authorized unseen evidence.

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

## Development loop

```text
MARKET DATA
 -> FUNNEL V1
 -> phase metrics
 -> rule metrics
 -> locate weak phase
 -> locate weak rule
 -> change one declared rule
 -> create child funnel version
 -> rerun same DEVELOPMENT population
 -> compare parent/child
 -> keep or reject experiment
 -> repeat
 -> promising candidate
 -> FREEZE
```

Never mutate a parent strategy in place. A behavior-changing rule modification creates a new rule/funnel identity.

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

The project should be implemented in the smallest useful vertical slices. The immediate Funnel Lab path is:

`MarketFrame -> Funnel contracts -> Candidate-flow runner -> Weak Funnel Diagnostic -> simulation adapter -> economic metrics -> version comparison -> branching funnels -> FrozenStrategy handoff`.

See `docs/FUNNEL_DEVELOPMENT_AND_EDGE_VERIFICATION_ROADMAP.md` for detailed work packages and the Edge Validator upgrade sequence.
