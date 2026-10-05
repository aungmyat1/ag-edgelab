# Capturing VT Markets friction evidence

The friction framework is built and tested, but it has **no VT Markets
evidence in it**. This sandbox cannot reach the venue: there is no MT5
terminal, the `MetaTrader5` package has no Linux build, and every
`vtmarkets.com` host is outside the network allowlist. Those checks are
re-run and recorded on every build in
`artifacts/friction_authority_r1/friction_source_inventory.json`.

So the capture has to happen on your machine. This is the whole
procedure.

---

## 1. Prerequisites

On the Windows PC where your VT Markets MT5 terminal is installed:

```
pip install MetaTrader5
```

Log the terminal in as you normally would and leave it running. The
script attaches to the already-authenticated terminal — **it never asks
for your login, password or investor password, and nothing in this
repository stores credentials.**

## 2. Run a capture session

```
python scripts/capture_vtmarkets_friction.py ^
    --out capture_bundles/vtmarkets_london_2026-10-06 ^
    --minutes 60 --interval 1.0 ^
    --session-label LONDON_OPEN
```

`capture_bundles/` is gitignored, so raw evidence stays out of the repo.

### Read-only guarantee

The script calls only `account_info`, `symbol_info`, `symbol_info_tick`,
`symbol_select`, `history_deals_get` and `history_orders_get`. A
regression test parses the file and fails if any ordering primitive
(`order_send`, `order_check`, `TRADE_ACTION_*`, …) ever appears in
executable code. It cannot place, modify or close a trade.

### Coverage you need

One session is not enough — spread is a distribution, and it widens
exactly when you are most likely to be trading. Run several short
sessions:

| Session | UTC window | Why |
| --- | --- | --- |
| ASIAN | 00:00–07:00 | the quiet baseline |
| LONDON | 07:00–12:00 | the open, where spreads jump |
| OVERLAP | 12:00–16:00 | London + New York, deepest liquidity |
| NEW_YORK | 16:00–21:00 | US data releases |
| OTHER | 21:00–24:00 | the rollover window, widest spreads |

XAUUSD has its own hours and its own halt — capture it on its own
schedule rather than assuming it tracks FX.

**Do not leave an unattended machine running overnight to hit a cadence
target.** Partial coverage is reported honestly as partial; it is not a
reason to run a PC unsafely.

## 3. Ingest the bundles

Back in the repo (any platform):

```
python scripts/build_friction_authority.py \
    --bundle capture_bundles/vtmarkets_london_2026-10-06 \
    --bundle capture_bundles/vtmarkets_ny_2026-10-06
```

Each bundle is hash-verified before a single row is read. Editing a
quote CSV after capture, adding a file, removing one or forging the
manifest root all abort the ingest.

Every artifact in `artifacts/friction_authority_r1/` is regenerated, and
`FRICTION_AUTHORITY_SHA256` is recomputed over the whole contract.

### If your strategy never holds overnight

```
    --strategy-closes-before-rollover yes --strategy-contract-frozen
```

Both flags are required. An unfrozen contract cannot waive financing,
because a "closes before rollover" claim that can still be edited is not
a guarantee. Without them, swap stays active and missing swap data
blocks economic verification.

## 4. Read the result

`artifacts/friction_authority_r1/final_report.md` gives the status and
the per-symbol distribution. `STATUS` will be one of:

- `BLOCKED_BROKER_AUTHORITY` — no evidence ingested (today's state)
- `FRICTION_PARTIALLY_ESTABLISHED` — some components captured
- `FRICTION_AUTHORITY_ESTABLISHED` — every component present

---

## What will still be MISSING after a quote capture

**Commission.** MT5 exposes no commission *schedule* through the API.
The script recovers it from what was actually charged on past deals. A
fresh account with no deal history yields `COMMISSION_AUTHORITY=MISSING`
— deliberately, because the alternative is pasting in an
industry-typical "$7 round turn" that is not your account's number. If
your account has no history, read the commission off your account
statement or the contract specification and record it by hand.

**Slippage.** Slippage is the gap between the price you asked for and
the price you got. Quote snapshots contain the price that was
*displayed*; they contain no fills. No sampling rate recovers it. It is
measurable only from executed deal history, and this mission does not
place orders to manufacture any. Until you have fills,
`SLIPPAGE_AUTHORITY=MISSING` and the required evidence is listed in
`slippage_authority.json`.

Neither gets a default. A missing component raises rather than becoming
a silent zero, because a friction bug that zeroes a cost does not crash
— it just makes every strategy look profitable.

---

## The time-mismatch wall

Your capture describes **2026**. The datasets under data authority cover
**2011-06-01 to 2018-06-06**. Retail FX spreads compressed enormously
over that period, raw/commission account types were not uniformly
available, and the broker entity and liquidity providers differ.

A 2026 quote is therefore not evidence about 2012 execution. The code
enforces this: `assert_regime_compatible()` raises if you try to apply
`VENUE_CURRENT_FRICTION_AUTHORITY` to a period it was not captured in.

For the historical period there is a declared
`RESEARCH_CONSERVATIVE_MODEL` — P95 of the current observed
distribution, doubled. The anchor is observed and the multiplier is a
stated constant, so it is reproducible, and it is labelled
`is_measurement: false` so it can never be cited as historical truth.
Period-contemporaneous broker statements would replace it; nothing else
will.
