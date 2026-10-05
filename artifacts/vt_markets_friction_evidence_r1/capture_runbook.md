# VT Markets friction capture — runbook

This is the half of `VT_MARKETS_FRICTION_EVIDENCE_R1` that has to run on
your Windows machine. Nothing here places, modifies or cancels an order,
and nothing changes your terminal or account configuration.

## 0. Before you start

- The VT Markets MT5 terminal must be **installed, logged in and open**.
  The Python package attaches to a running terminal; it cannot log in
  for you, and it is never given credentials.
- Python 3.11+ on the same machine.
- You never type a password, token or login number into this tool. The
  account login is written to evidence as `REDACTED`.

## 1. Install

```bat
pip install MetaTrader5
```

There is no Linux build of this package. That is why the capture cannot
run in the agent sandbox and has to run on your machine.

## 2. One manual run first

```bat
cd C:\path\to\ag-edgelab
python scripts\capture_vtmarkets_friction.py --root capture_bundles --tick-history-hours 24
```

Read the first few lines of output. They show the resolved mapping:

```
  EURUSD   -> EURUSD-VIP  [RESOLVED]
  GBPUSD   -> GBPUSD-VIP  [RESOLVED]
  USDJPY   -> USDJPY-VIP  [RESOLVED]
  XAUUSD   -> GOLD-VIP    [RESOLVED_AMBIGUOUS]
  crypto found: BTCUSD-VIP
  crypto found: ETHUSD-VIP
```

**Check this mapping before trusting anything downstream.** The tool
never guesses a suffix — it only matches names your terminal actually
publishes — but where several names share a root it reports
`RESOLVED_AMBIGUOUS` and records every candidate in
`symbol_resolution.json`. If it picked the wrong contract, pass the
right one explicitly:

```bat
python scripts\capture_vtmarkets_friction.py --root capture_bundles --symbols EURUSD GBPUSD USDJPY XAUUSD BTCUSD ETHUSD
```

If a canonical name comes back `NOT_FOUND`, that is the honest answer —
do not invent a suffix to make it resolve.

## 3. Schedule it

Spread is a distribution, not a number. One hour of quotes tells you
almost nothing about what you pay at the London open or during a news
print. Register an hourly task and leave it running for at least a
couple of weeks, including a rollover (Wednesday) and a non-farm payroll
Friday.

```bat
schtasks /Create /TN EdgeLabFrictionCapture /SC HOURLY ^
  /TR "C:\Python311\python.exe C:\path\to\ag-edgelab\scripts\capture_vtmarkets_friction.py --root C:\path\to\ag-edgelab\capture_bundles"
```

Scheduler safety is built in:

- every run seals a **new** bundle, `friction_capture_YYYYMMDD` (then
  `_002`, `_003` … within a day);
- a sealed bundle is never rewritten — re-sealing changed content
  raises;
- `capture_registry.json` is **append-only** and records sha256, byte
  size, capture window, symbol set and sample count per bundle;
- a lock file makes an overlapping run exit cleanly rather than
  interleave writes.

## 4. What it captures, and what it cannot

| component | captured | how |
|---|---|---|
| spread | yes | `copy_ticks_range` tick history, falling back to polling |
| swap | yes | `symbol_info.swap_long/short/mode/rollover3days` |
| commission | **only if your evidence has it** | deal history with a commission field, or an account spec/statement you hold locally |
| slippage | **no** | needs executed fills: requested vs filled price |

Slippage cannot be derived from quotes at any sampling rate — a quote
shows what was displayed, not what an order received. The tool will not
place a trade to manufacture a fill, so slippage stays `MISSING` until
real deal evidence exists.

Commission is never filled in with an industry default. If your account
specification isn't in the deal history, it stays `MISSING` and you can
add the broker statement later.

## 5. Bring the evidence back

Copy the `capture_bundles` directory into the repo checkout and run:

```bat
python scripts\build_vt_markets_friction_evidence.py --bundle-root capture_bundles
```

This verifies every bundle hash, refuses tampered ones, pools the
quotes and writes the spread distributions per symbol and per session.

The large quote CSVs are **not** committed to git — only the manifests,
hashes and derived distributions are.

## 6. A note on session labels

Two session definitions exist in this repository and they disagree at
07:00 and 12:00 UTC:

| | governed V0.3 | friction diagnostic |
|---|---|---|
| ASIAN | 00–08 | 00–07 |
| LONDON | 08–13 | 07–12 |
| overlap | `LONDON_NEWYORK_OVERLAP` 13–16 | `OVERLAP` 12–16 |
| NEW_YORK | 16–21 | 16–21 |
| last | `OFF_SESSION` 21–24 | `OTHER` 21–24 |

Rather than pick one silently or invent a third, **every captured quote
carries both labels**: `session_governed_v03` and `session`.
Distributions are computed on the governed V0.3 authority.
