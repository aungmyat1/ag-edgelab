# V2 trigger/confirmation temporal coupling diagnostic

Candidate: `ST_MTF_CONTROL_SHIFT_V2 @ 2.0.0`

## Primary classification

`STALE_TRIGGER_SESSION_MISMATCH`

All 18 V2 H1 shifts occur more than 240 minutes before the active session ends. Their first otherwise-valid directional M15 zones occur 960–1035 minutes before the current session starts, i.e. during the prior day. They are not close misses at the session boundary.

The 24-bar freshness relaxation admitted H1 shifts with ages 17–21 H1 bars. The trigger and its first directional M15 confirmation are temporally coupled to the prior day, while the session evaluation occurs on the following day. This supports the stale-trigger/session-mismatch classification.

## Case population

All 18 H1-shift-pass cases were audited. Full case-level timestamps are in `v2_temporal_coupling.json` under `cases_detail`.

The case set is concentrated in `USDJPY × LONDON_NEWYORK`:

- 18/18 USDJPY
- 18/18 LONDON_NEWYORK
- H1 ages: 17–21 bars

## Session boundary distribution

For the first otherwise-valid directional M15 zone after each H1 shift:

| Minutes after session end | Count | Percentage |
|---:|---:|---:|
| <= 0 | 18 | 100.0% |
| 1–15 | 0 | 0.0% |
| 16–30 | 0 | 0.0% |
| 31–60 | 0 | 0.0% |
| 61–120 | 0 | 0.0% |
| 121–240 | 0 | 0.0% |
| >240 | 0 | 0.0% |

The `<=0` bucket requires an important qualification: all 18 zones were **before session start**, not inside the original session. Their distance before session start was 960–1035 minutes.

## H1 shift timing

| Minutes remaining to session end | Count | Percentage |
|---:|---:|---:|
| >240 | 18 | 100.0% |
| 121–240 | 0 | 0.0% |
| 61–120 | 0 | 0.0% |
| 31–60 | 0 | 0.0% |
| 16–30 | 0 | 0.0% |
| 1–15 | 0 | 0.0% |
| <=0 | 0 | 0.0% |

H1 triggers are therefore not too late within the active session. They occur on the preceding day and are stale relative to the later session.

## Delay statistics

### H1 shift to first directional M15 zone

- P25: `0.0 minutes`
- P50: `22.5 minutes`
- P75: `45.0 minutes`
- P90: `45.0 minutes`
- MAX: `45.0 minutes`

### First M15 zone after session end

Using `max(0, zone_time - session_end)`:

- P25: `0.0 minutes`
- P50: `0.0 minutes`
- P75: `0.0 minutes`
- P90: `0.0 minutes`
- MAX: `0.0 minutes`

This statistic is zero because the zones occur before the session end—and, more specifically, before the session start. The separate before-session-start measurement is the relevant temporal diagnostic here.

### First M15 zone before session start

- P25: `960.0 minutes`
- P50: `997.5 minutes`
- P75: `1035.0 minutes`
- P90: `1035.0 minutes`
- MAX: `1035.0 minutes`

## Diagnostic grace-window coverage

A grace window only extends the active session end; it does not admit zones from before the session start.

| Session extension | Coverage N | Coverage % |
|---:|---:|---:|
| 0 minutes | 0 | 0.0% |
| 15 minutes | 0 | 0.0% |
| 30 minutes | 0 | 0.0% |
| 60 minutes | 0 | 0.0% |
| 120 minutes | 0 | 0.0% |
| 240 minutes | 0 | 0.0% |

Therefore, a simple post-session grace window is not supported by this evidence.

## V2 freshness coupling finding

The 4→24 relaxation did not create a set of near-session triggers. It admitted stale H1 shifts from the prior day. The first directional M15 zones followed those shifts quickly—0 to 45 minutes later—but still occurred many hours before the next session began.

This is descriptive evidence only; it does not establish causal profitability or justify changing V2.

## V3 decision

V3_HYPOTHESIS_CLASS = `TRIGGER_SESSION_TIMING`

A defensible conceptual single-rule experiment exists for owner review:

- Parent: `ST_MTF_CONTROL_SHIFT_V2 @ 2.0.0`
- New identity: `ST_MTF_CONTROL_SHIFT_V3 @ 3.0.0`
- One rule to change: session-coupling of H1 shift eligibility
- Old semantic: a shift is eligible solely from the 24-closed-H1-bar freshness limit, even when its creation is on the prior day relative to the active session
- Proposed semantic: require the H1 shift creation timestamp to belong to the active session date before allowing M15 confirmation

This is a design hypothesis only. V3 was not implemented, preregistered, or replayed.

V2 modified: `NO`  
OOS opened: `NO`  
Holdout touched: `NO`  
Execution capability added: `NO`
