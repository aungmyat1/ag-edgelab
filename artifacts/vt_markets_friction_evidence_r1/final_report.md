# VT_MARKETS_FRICTION_EVIDENCE_R1 — Status

## BLOCKED: no terminal in this environment

MetaTrader5 is a Windows-only package with no Linux wheel, and no VT Markets terminal is present in this environment. Venue evidence cannot be captured here; it must be captured on the owner's Windows machine.

`MetaTrader5` importable: **False** ·
platform: `linux`

No spread, commission, slippage or swap number is reported, because none
was measured. Nothing is defaulted to zero.

| component | status |
|---|---|
| SPREAD_AUTHORITY | MISSING |
| COMMISSION_AUTHORITY | MISSING |
| SLIPPAGE_AUTHORITY | MISSING |
| SWAP_AUTHORITY | MISSING |
| **FRICTION_AUTHORITY_COMPLETE** | **False** |

## Session authority conflict

Two session definitions exist in this repository and they disagree on
**2 of 24 UTC hours**.

| | governed V0.3 | friction diagnostic |
|---|---|---|
| ASIAN | 00–08 | 00–07 |
| LONDON | 08–13 | 07–12 |
| OVERLAP | 13–16 | 12–16 |
| NEW_YORK | 16–21 | 16–21 |
| last bucket | OFF_SESSION 21–24 | OTHER 21–24 |

The mission prompt asked for `LONDON_NEWYORK_OVERLAP` (a V0.3 name)
together with `OTHER` (a friction-module name) — a combination that
exists in neither. Inventing it would have created a third, ungoverned
session definition, so instead **both labels are recorded on every
captured quote** and neither authority was modified.

## What is ready to run

- `scripts/capture_vtmarkets_friction.py (v2, read-only, scheduler-safe)`
- `ag_edgelab.friction.authority.resolution (symbol resolution)`
- `ag_edgelab.friction.authority.daily (immutable daily bundles)`
- `scripts/build_vt_markets_friction_evidence.py (this ingest)`

`ORDER_CALLS_EXECUTED=NO` ·
`BROKER_MUTATION=NO`
