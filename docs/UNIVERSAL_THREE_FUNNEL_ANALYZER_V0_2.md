# Universal Three-Funnel Analyzer V0.2

## Purpose

V0.2 adds a strategy-agnostic DEVELOPMENT diagnostic layer. It does **not** replace the Production Edge Validator and it has no authority to issue `EDGE_VERIFIED`.

The universal view is:

1. **TRIGGER** — did the strategy identify an opportunity with enough future price capability to justify the intended R:R?
2. **CONFIRMATION** — did the strategy validate/select the useful triggers rather than merely reduce population?
3. **OUTCOME** — after a valid entry, what targets were reachable and what did the declared exit policy actually realize?

The three groups are organizational categories, not 33/33/33 performance weights. A strategy author explicitly maps each deterministic strategy node to exactly one group. The mapping is hashed; changing a node's group changes diagnostic identity.

## Diagnostic model

Detailed strategy rules remain authoritative. Examples:

- TRIGGER: session, bias, location, sweep, breakout.
- CONFIRMATION: displacement, CHOCH, FVG, retest, geometry.
- OUTCOME: entry/fill, stop, target, MFE/MAE, exit policy, friction-adjusted result.

V0.2 reports per-rule and per-group flow (`input_n`, `pass_n`, `fail_n`, percentages), stable failure reason counts, optional downstream conditional expectancy, and target-capability diagnostics at Trigger and Confirmation boundaries. Conditional metrics are descriptive associations; they are not causal rule-contribution claims.

## Backward diagnosis: TP failure does not automatically mean confirmation failure

A poor realized 2R/5R result must be traced backward before proposing a mutation.

For every reached Trigger or Confirmation rule, a preregistered `StageExcursionObservation` may attach future MFE/MAE under a frozen observation policy. The policy must define the anchor, risk unit, observation horizon and stop/termination convention. The analyzer never invents those values.

For every requested target (1R-5R by default), the rule report contains:

- `input_reach_pct`: target capability among all candidates reaching the rule;
- `pass_reach_pct`: target capability among candidates passing the rule;
- `fail_reach_pct`: target capability among candidates failing the rule;
- `pass_uplift_vs_input_pp`: how much target reachability changed after selecting PASS;
- `pass_minus_fail_pp`: descriptive separation between PASS and FAIL populations.

This permits three materially different diagnoses:

1. **Trigger problem candidate** — Trigger PASS candidates rarely contain the intended target capability. Confirmation cannot manufacture 5R opportunity from a population that almost never contains 5R movement.
2. **Confirmation problem candidate** — Trigger input contains target-capable observations, but Confirmation PASS provides little or no target-reachability uplift while discarding candidates.
3. **Outcome/TP problem candidate** — Trigger and Confirmation select target-capable entries, but the realized exit policy still has poor economics or the declared target is rarely reachable after actual entry.

These are hypotheses, not causal proofs. No rule is automatically changed.

## TP / excursion analysis

For authoritative entry observations, V0.2 separates:

- **target reachability**: whether MFE reached 1R, 2R, 3R, 4R, 5R (or another declared target grid);
- **realized exit-policy economics**: the actual net-R series produced by a preregistered DEVELOPMENT exit policy.

This distinction prevents a target touch from being treated as if a different exit policy had actually realized that profit.

Post-entry MFE/MAE are expressed in initial-risk units and carry an observation-policy identity. Exit-policy results reference known candidate/trade identities. Stage-boundary MFE/MAE reference a known candidate and a rule boundary that candidate actually reached. Unknown candidates, unmapped nodes, unreached boundaries and duplicate observations fail closed.

## Weak-point findings

The deterministic policy can emit hypothesis labels such as:

- `LOW_FLOW`
- `POOR_TRIGGER_QUALITY`
- `CONFIRMATION_ATTRITION`
- `LOW_DISCRIMINATION`
- `ENTRY_UNREACHABLE`
- `TP_TOO_AMBITIOUS_CANDIDATE`
- `INSUFFICIENT_SAMPLE`

The important ordering is:

`target feasibility -> Trigger discrimination -> Confirmation incremental discrimination -> geometry/execution -> realized exit economics`

A low pass rate alone is not sufficient evidence that a rule is weak. Likewise, poor TP economics alone is not sufficient evidence that Confirmation should be adjusted.

Thresholds are explicit in `DiagnosticPolicy`. Findings are research prompts, not optimization commands. The analyzer never mutates strategy rules.

## Authority boundary

The analyzer accepts DEVELOPMENT runs only and returns `DEVELOPMENT_DIAGNOSTIC_ONLY` with `edge_verified_authorized=false`.

The only valid edge-claim path remains:

`diagnose -> controlled DEVELOPMENT mutation -> compare -> freeze -> Production Edge Validator -> EDGE_VERIFIED | NO_EDGE | INSUFFICIENT_EVIDENCE`

## V0.2 implementation scope

This branch establishes the universal contract, deterministic mapping identity, flow/failure analytics, conditional downstream metrics, stage-boundary target-capability analysis, post-entry MFE/MAE target survival, exit-policy comparison, deterministic weak-point hypotheses, and fail-closed evidence identity checks.

The next integration step is to map an existing deterministic strategy (preferably `SESSION_TRADE_V2`) into the three groups and verify parity with its existing strategy-specific diagnostics. Only after parity should additional strategies be onboarded.
