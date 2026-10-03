"""Deterministic synthetic BTCUSDT-like M5 fixture — NOT market data.

Purpose: prove the ST_CRYPTO_MTF_SMC_V1 machinery end-to-end with a pinned
seed (repeatability, anti-lookahead tests, funding plumbing). The series is
fully synthetic: a seeded random walk with stylistically injected SMC
templates. It MUST NEVER be presented as, or mixed with, real market data.
Its dataset manifests carry provider=SYNTHETIC_FIXTURE and
dataset_is_authoritative=false.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

Z = timezone.utc
STEP = timedelta(minutes=5)


def build_bars(start: datetime, days: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    bars: list[dict] = []
    ts = start
    price = 60_000.0

    # Segment plan: seeded noise interludes with anchored SMC template
    # episodes injected periodically. Templates are emitted with the SAME
    # generator so input order fully determines output bytes.
    #
    # Template layout (proven geometry; all levels anchored to the template
    # start price via m(); grid-aligned to 48 M5 bars = H4 boundary):
    #   A1  240 bars impulse leg 1 (+3200)
    #   A2a  12 bars deep dip (one full H1, bearish origin: poi.low = deep low)
    #   A2r  10 bars recovery (+530 off the dip)
    #   A2b  12 bars bullish chop (shallow M15 SSL pool ABOVE poi.low)
    #   A3  210 bars impulse leg 2 (+2600) -> opposing-liquidity target pool
    #   B   9 zigzag decay blocks (12 bars each) + 10 filler bars
    #   -------------------------------- phase: plunge lands at H1 offset +2
    #   PL  plunge: pool+190 -> pool+60 -> pool-120, close back at pool+220
    #   C   candles +130/+55/+70 (displacement + FVG (w2_1, w2_2, c1))
    #   TH  8 bars thrust, then 4-bar dip to the engine FVG midpoint - 5
    #   E   rally toward the old pool (+400 past it), settle 60
    total = days * 288
    i = 0
    cycle = 0

    def emit(o: float, h: float, l: float, c: float) -> None:
        nonlocal ts
        # Hard OHLC invariant: an invalid fixture is a bug, not data.
        h, l = max(h, o, c), min(l, o, c)
        bars.append({"timestamp": ts, "open": round(o, 1), "high": round(h, 1), "low": round(l, 1), "close": round(c, 1), "volume": 1.0})
        ts += STEP

    price_ref = price
    def walk(n: int, target: float, wick: float) -> None:
        """n bars interpolating open->close from current price to `target`."""
        nonlocal price
        start_p = price
        prev = start_p
        for k in range(1, n + 1):
            nxt = start_p + (target - start_p) * (k / n)
            emit(prev, max(prev, nxt) + wick, min(prev, nxt) - wick, nxt)
            prev = nxt
        price = target

    def noisy_walk(n: int, span: float, wick_ratio: float = 0.4) -> None:
        nonlocal price
        for _ in range(n):
            step = rng.uniform(-span, span)
            o = price
            c = max(1.0, price + step)
            emit(o, max(o, c) + abs(rng.uniform(0, max(wick_ratio * span, 0.5))),
                 min(o, c) - abs(rng.uniform(0, max(wick_ratio * span, 0.5))), c)
            price = c

    rng_seed_noise = 18.0
    while i < total:
        # bland interlude
        interlude = min(700 + rng.randrange(400), total - i)
        if interlude <= 0:
            break
        noisy_walk(interlude, rng_seed_noise + 6.0 * ((i // 4000) % 2))
        i += interlude
        if i >= total:
            break
        # pad to an H4 grid boundary so every injected template shares an
        # identical internal phase against M15/H1/H4/D1 grids (deterministic
        # outcome per template, not alignment roulette)
        while i % 48 != 0:
            noisy_walk(1, rng_seed_noise)
            i += 1
            if i >= total:
                break
        if i >= total:
            break

        cycle += 1
        up = (cycle % 2 == 1)
        sign = 1.0 if up else -1.0
        anchor = price

        def m(val: float) -> float:
            # All A-phase levels are absolute offsets from the template start
            # price, NOT from the live price (otherwise A2a "dips" upward).
            return anchor + sign * val

        # ---- A1: impulse leg 1 (establishes H4/M15 structure) ----
        walk(240, m(3200.0), 6.0)
        i += 240
        # ---- A2a: 12-bar deep dip. One grid-aligned H1 candle; bullish
        #      displacement origin (POI low = this candle's low). ----
        dip_o = price
        walk(12, m(2520.0), 4.0)
        deep_low = min(b["low"] for b in bars[-12:]) if up else max(b["high"] for b in bars[-12:])
        i += 12
        # ---- A2r: recovery (H1-bullish region) ----
        walk(10, m(3050.0), 3.0)
        i += 10
        # ---- A2b: net-H1-bullish chop that leaves a SHALLOW M15 swing pool
        #      (the sweep target) ABOVE the H1 POI low. ----
        for seg in ((-320.0, +325.0), (-180.0, +185.0)):
            walk(3, price + sign * seg[0], 2.0)
            walk(3, price + sign * seg[1], 2.0)
            i += 6
        shallow_extreme = min(b["low"] for b in bars[-6:-3]) if up else max(b["high"] for b in bars[-6:-3])
        pool_extreme = shallow_extreme
        def pool(off: float) -> float:
            return pool_extreme + sign * off
        # ---- A3: impulse leg 2 to a fresh extreme (opposing liquidity draw).
        walk(210, price + sign * 2600.0, 5.0)
        i += 210
        old_pool = max(b["high"] for b in bars[-210:]) if up else min(b["low"] for b in bars[-210:])
        # ---- B: 9 decay blocks of 12 M5 bars; net decay per block with an
        #      internal 3-bar bounce leaving descending confirmed M5 pivot
        #      highs (the future CHoCH trigger). ----
        decay_start = price
        decay_end = pool(190.0)
        per_block = abs(decay_end - decay_start) / 9.0
        level = price
        for block in range(9):
            base = level
            for k in range(6):
                o = level
                c = base - sign * (per_block * 0.75) * ((k + 1) / 6)
                emit(o, max(o, c) + 2.0, min(o, c) - 2.0, c)
                level = c
            bounce_top = base - sign * (per_block * 0.75) + sign * (per_block * 0.35)
            walk(3, bounce_top, 1.0)
            pivot_extreme = max(b["high"] for b in bars[-3:]) if up else min(b["low"] for b in bars[-3:])
            block_low = base - sign * per_block
            o = level
            for k in range(3):
                o = bars[-1]["close"]
                c = bounce_top - sign * abs(bounce_top - block_low) * ((k + 1) / 3)
                if up:
                    emit(o, min(o + 1.0, pivot_extreme - 2.0), c - 2.0, c)
                else:
                    emit(o, c + 2.0, max(o - 1.0, pivot_extreme + 2.0), c)
            level = bars[-1]["close"]
            i += 12
        # 10 filler bars so the plunge lands at H1 phase offset +2 (containing
        # H1 closes back inside the POI: sweep must be a wick, not close-through).
        walk(10, decay_end, 1.5)
        i += 10
        # ---- plunge: 3 bars driving through the pool and closing back ----
        o = price
        if up:
            emit(o, o + 6.0, pool(60.0), pool(60.0))
            emit(pool(60.0), pool(70.0), pool(-60.0), pool(-40.0))
        else:
            emit(o, pool(54.0), o - 2.0, pool(60.0))
            emit(pool(60.0), pool(-60.0), pool(70.0), pool(40.0))
        walk(2, pool(220.0), 3.0)
        i += 4
        # ---- C: displacement out of the pool with a 3-candle FVG ----
        # Candle 1 must alone clear the 2x-median-body displacement gate vs the
        # late-decay reference window (choch fires on its close).
        b1o = price
        b1c = b1o + sign * 130.0
        emit(b1o, max(b1o, b1c) + 4.0, min(b1o, b1c) - 4.0, b1c)          # candle 1
        # The engine locks entry to the FIRST FVG whose third candle is closed
        # at CHoCH time; CHoCH fires on candle1's close, so the engine gap is
        # (walk2 bar1, walk2 bar2, candle1). Compute its midpoint directly.
        if up:
            entry_mid = (bars[-3]["high"] + bars[-1]["low"]) / 2.0
        else:
            entry_mid = (bars[-3]["low"] + bars[-1]["high"]) / 2.0
        b2o = b1c
        b2c = b2o + sign * 55.0
        emit(b2o, max(b2o, b2c) + 4.0, min(b2o, b2c) - 1.0, b2c)          # candle 2
        b3o = b2c
        b3c = b3o + sign * 70.0
        if up:
            emit(b3o, b3c + 4.0, b1c + 10.0, b3c)                          # low > candle1 high => FVG
        else:
            emit(b3o, b1c - 10.0, b3c - 4.0, b3c)                          # high < candle1 low => FVG
        price = b3c
        i += 3
        # ---- TH: thrust beyond the pre-decay internal swing (M5 CHoCH) then
        #      a 4-bar dip into the engine FVG midpoint to fill. ----
        walk(8, price + sign * 220.0, 4.0)
        i += 8
        dip = entry_mid - sign * 5.0
        walk(4, dip, 2.0)
        i += 4
        walk(3, entry_mid + sign * 40.0, 2.0)
        i += 3
        # ---- E: drawn toward the opposing pool (TP region), then settle ----
        walk(150, old_pool + sign * 400.0, 5.0)
        i += 150
        walk(60, price - sign * 60.0, 4.0)
        i += 60

    return bars


def build_funding(start: datetime, days: int, seed: int) -> list[dict]:
    rng = random.Random(seed + 1)
    events = []
    ts = start
    sign = 1.0
    for d in range(days):
        for _ in range(3):  # 8h cadence: 00, 08, 16 UTC
            # deterministic but varying; conventions consistent inside a day-week
            sign = sign if rng.random() > 0.15 else -sign
            rate = round(0.0001 * sign, 5)
            events.append({"timestamp": ts.isoformat(), "funding_rate": rate})
            ts += timedelta(hours=8)
    return events


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-05-01T00:00:00+00:00")
    ap.add_argument("--days", type=int, default=150)
    ap.add_argument("--seed", type=int, default=20261003)
    ap.add_argument("--out-dir", default="data/artifacts/synthetic_btcusdt")
    ap.add_argument("--with-manifest", action="store_true",
                    help="also write SHA-pinned manifests for both artifacts")
    args = ap.parse_args()

    start = datetime.fromisoformat(args.start).astimezone(Z)
    bars = build_bars(start, args.days, args.seed)
    funding = build_funding(start, args.days, args.seed)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from ag_edgelab.contracts.market import MarketBar
    from ag_edgelab.data.bars import write_bars_csv

    mbars = tuple(
        MarketBar(timestamp=b["timestamp"], open=b["open"], high=b["high"], low=b["low"], close=b["close"], volume=b["volume"])
        for b in bars
    )
    bars_path, sha = write_bars_csv(out / "BTCUSDT_M5_SYNTHETIC.csv", mbars)
    fpath = out / "BTCUSDT_FUNDING_SYNTHETIC.csv"
    with fpath.open("w", encoding="utf-8", newline="") as fh:
        fh.write("timestamp,funding_rate\n")
        for row in funding:
            fh.write(f"{row['timestamp']},{row['funding_rate']!r}\n")
    f_sha = hashlib.sha256(fpath.read_bytes()).hexdigest()
    if args.with_manifest:
        manifest_common = {
            "provider": "SYNTHETIC_FIXTURE",
            "dataset_is_authoritative": False,
            "symbol": "BTCUSDT",
            "instrument_type": "LINEAR_PERPETUAL (declared simulation target; NOT exchange data)",
            "construction": {
                "generator": str(Path(__file__).name),
                "seed": args.seed,
                "start": start.isoformat(),
                "days": args.days,
            },
        }
        (out / "BTCUSDT_M5_SYNTHETIC.csv.manifest.json").write_text(json.dumps({
            **manifest_common,
            "artifact": Path(bars_path).name,
            "timeframe": "M5",
            "rows": len(bars),
            "sha256": sha,
            "first": bars[0]["timestamp"].isoformat(),
            "last": bars[-1]["timestamp"].isoformat(),
        }, indent=2))
        (out / "BTCUSDT_FUNDING_SYNTHETIC.csv.manifest.json").write_text(json.dumps({
            **manifest_common,
            "artifact": fpath.name,
            "kind": "funding_schedule",
            "cadence_hours": 8,
            "rows": len(funding),
            "sha256": f_sha,
            "first": funding[0]["timestamp"],
            "last": funding[-1]["timestamp"],
        }, indent=2))
    print(json.dumps({
        "bars": len(bars),
        "bars_sha256": sha,
        "funding_events": len(funding),
        "funding_sha256": f_sha,
        "first": bars[0]["timestamp"].isoformat(),
        "last": bars[-1]["timestamp"].isoformat(),
        "NOTE": "SYNTHETIC FIXTURE - NOT MARKET DATA",
    }, indent=2))


if __name__ == "__main__":
    main()
