# Owner Decisions R2

Status: UNRESOLVED

This package records eight owner decisions blocking the GEN2 ALD V2.1 replay gate. Every answer remains null; no option is selected.

## AMB_1 — OPPORTUNITY_UNIT

Status: UNRESOLVED

Question: Is an OPPORTUNITY one `(symbol, trading_date, session)` or one `(symbol, trading_date, session, boundary)`?

Options and consequences:
- `(symbol, trading_date, session)`: Keeps one opportunity per session and aligns with the 2.0.0 prototype denominator; opposite boundaries share one unit.
- `(symbol, trading_date, session, boundary)`: Counts each boundary independently and can produce up to two opportunities per symbol-day-session; prior funnel denominators are not directly comparable.

Owner answer: null

## AMB_2 — CONTEXT_ELIGIBLE / LOCATION_ELIGIBLE

Status: UNRESOLVED

Question: What predicate defines `CONTEXT_ELIGIBLE`, and what defines `LOCATION_ELIGIBLE`?

Options and consequences:
- Define separate deterministic context and location predicates in an owner-approved contract amendment: A replay may be considered only after the amended predicates are preregistered and tested.
- Retain the current predicates as unresolved and keep replay blocked: No V2.1 replay or funnel denominator is authorized.

Owner answer: null

## AMB_3 — INITIAL_BRANCH_SELECTION

Status: UNRESOLVED

Question: Which branch is attempted first on a boundary interaction — decided by the interaction bar's close (prototype behaviour), by a fixed precedence, or are both run and the earlier `ENTRY_AVAILABLE` taken?

Options and consequences:
- Select the branch from the interaction bar close: Branch assignment depends on close direction and must be fully specified for ties and handovers.
- Use a fixed A/B precedence: The preferred branch gets first claim on the event lock, potentially changing branch mix.
- Evaluate both and take the earlier ENTRY_AVAILABLE: Both branches compete for the lock; deterministic tie handling is required.

Owner answer: null

## AMB_4 — Prior-day and swing-liquidity authority

Status: UNRESOLVED

Question: Define "prior day" (previous calendar day vs previous trading day; UTC vs session day) and define the swing-liquidity derivation (timeframe, and whether `SWING_ORDER = 2` applies).

Options and consequences:
- Use previous calendar day in UTC and define swing liquidity on the contract's named timeframe with SWING_ORDER = 2: Produces calendar-day levels and a fixed swing derivation, which may differ at weekends and session boundaries.
- Use previous trading/session day and owner-specify the swing-liquidity timeframe and swing order: Requires an explicit session-day calendar and amended timeframe/order before any result can be generated.

Owner answer: null

## SESSION_AUTHORITY_CONFLICT — Canonical session authority

Status: UNRESOLVED

Question: Which session authority controls: governed V0.3 (ASIAN/LONDON) or the R1 slicer (LONDON/OVERLAP), particularly at 07:00 and 12:00 UTC?

Options and consequences:
- Use governed V0.3 ASIAN/LONDON boundaries: Events at 07:00 and 12:00 UTC use V0.3 boundaries; R1 slicer outputs are not the session authority.
- Use the R1 slicer LONDON/OVERLAP boundaries: Events at 07:00 and 12:00 UTC follow R1 slices; V0.3 comparisons require an explicit mapping.
- Keep the conflict unresolved and block replay: No session-dependent V2.1 evaluation is authorized.

Owner answer: null

## V2.1_KILL_RULE — Family termination

Status: UNRESOLVED

Proposed rule: "archive the ALD family with no V2.2 if DEV pooled expectancy <= 0 OR bootstrap CI95 includes 0 OR PRE_OOS gate FAIL".

Options and consequences:
- Accept: Any listed condition archives the ALD family and prohibits V2.2.
- Edit: The edited rule must be preregistered and approved before any replay or successor design.
- Reject: No kill rule is established; the family remains blocked from replay or successor work until another rule is approved.

Owner answer: null

## FRICTION_VENUE — Venue authority

Status: UNRESOLVED

Question: Which broker, account type, and exact terminal symbol names will define the friction evidence venue?

Options and consequences:
- Select one broker/account type and list exact terminal names for EURUSD, GBPUSD, USDJPY, and XAUUSD: Friction capture can be specified against one venue once the exact names and evidence source are supplied.
- Select a different explicitly named broker/account/symbol mapping and document its authoritative friction source: The alternative venue becomes the sole approved friction authority after its mapping and measurement method are preregistered.
- Keep friction venue unavailable and prohibit economic claims: Economic edge remains NOT_ESTIMABLE and no friction values may be substituted.

Owner answer: null

## CONTAMINATION_TIMESTAMP_CONFIRMATION — Legacy exposure dates

Status: UNRESOLVED

Question: Are the 2025-10-05 and 2025-01-01 ALD exposure timestamps intended, or are they year typos for 2026?

Evidence: Commits `4f27640` and `705ec56` are dated 2026-10-05; `4f27640` is the V1 preregistration commit and `705ec56` contains the V1 development report. The archived `feat/fx-asian-sweep-candidate` points to `e5725c4`, dated 2026-10-01; that screen has no committed verdict artifact.

Options and consequences:
- Confirm the recorded 2025-10-05 and 2025-01-01 timestamps are intended historical exposure dates: The existing registry entries remain unchanged and the dates are treated as owner-confirmed historical knowledge dates.
- Confirm both dates are year typos for 2026 and authorize a separately evidenced append-only correction: A new correction record may be added only with the owner decision and commit-backed date evidence; original entries remain immutable.
- Leave both dates unresolved pending stronger timestamp evidence: The registry remains unchanged and these dates cannot be used as precise exposure chronology.

Owner answer: null

This package is append-only and non-authoritative until the owner answers all eight decisions.
