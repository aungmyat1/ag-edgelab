# Universal Three-Funnel Analyzer V0.2

## Purpose

V0.2 adds a strategy-agnostic DEVELOPMENT diagnostic layer. It does **not** replace the Production Edge Validator and it has no authority to issue `EDGE_VERIFIED`.

The universal view is:

1. **TRIGGER** — did the strategy identify an opportunity?
2. **CONFIRMATION** — did the strategy validate the setup?
3. **OUTCOME** — what happened after a valid entry, including target reachability and realized exit-policy economics?

The three groups are organizational categories, not 33/33/33 performance weights. A strategy author explicitly maps each deterministic strategy node to exactly one group. The mapping is hashed; changing a node's group changes diagnostic identity.

## Diagnostic model

Detailed strategy rules remain authoritative. Examples:

- TRIGGER: session, bias, location, sweep, breakout.
- CONFIRMATION: displacement, CHOCH, FVG, retest, geometry.
- OUTCOME: entry/fill, stop, target, MFE/MAE, exit policy, friction-adjusted result.

V0.2 reports per-rule and per-group flow (`input_n`, `pass_n`, `fail_n`, percentages), stable failure reason counts, and optional downstream conditional expectancy. Conditional metrics are descriptive associations; they are not causal rule-contribution claims and missing failed-route outcomes are not fabricated.

## TP / excursion analysis

For authoritative entry observations, V0.2 separates:

- **target reachability**: whether MFE reached 1R, 2R, 3R, 4R, 5R (or another declared target grid);
- **realized exit-policy economics**: the actual net-R series produced by a preregistered DEVELOPMENT exit policy.

This distinction prevents a target touch from being treated as if a different exit policy had actually realized that profit.

MFE and MAE are expressed in initial-risk units and must carry an observation-policy identity. Exit-policy results must reference known candidate/trade identities.

## Weak-point findings

The first deterministic policy can emit hypothesis labels such as:

- `LOW_FLOW`
- `CONFIRMATION_ATTRITION`
- `LOW_DISCRIMINATION`
- `ENTRY_UNREACHABLE`
- `TP_TOO_AMBITIOUS_CANDIDATE`
- `INSUFFICIENT_SAMPLE`

These labels are research prompts, not optimization commands. Thresholds are explicit in `DiagnosticPolicy`. The analyzer never mutates strategy rules.

## Authority boundary

The analyzer accepts DEVELOPMENT runs only and returns `DEVELOPMENT_DIAGNOSTIC_ONLY` with `edge_verified_authorized=false`.

The only valid edge-claim path remains:

`diagnose -> controlled DEVELOPMENT mutation -> compare -> freeze -> Production Edge Validator -> EDGE_VERIFIED | NO_EDGE | INSUFFICIENT_EVIDENCE`

## V0.2 implementation scope

This branch establishes the universal contract, deterministic mapping identity, flow/failure analytics, conditional downstream metrics, MFE/MAE target survival, exit-policy comparison, and deterministic weak-point hypotheses.

Follow-up integration should map an existing deterministic strategy (preferably `SESSION_TRADE_V2`) into the three groups and verify parity with its existing strategy-specific diagnostics before onboarding additional strategies.
