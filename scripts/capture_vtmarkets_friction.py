#!/usr/bin/env python3
"""Read-only VT Markets / MT5 friction capture.

Run this on the Windows machine where the VT Markets MT5 terminal is
installed and logged in. It produces a hash-verifiable evidence bundle
that ``scripts/build_friction_authority.py`` ingests.

    python scripts/capture_vtmarkets_friction.py \
        --out capture_bundles/vtmarkets_2026xxxx \
        --minutes 60 --interval 1.0

READ-ONLY BY CONSTRUCTION
-------------------------
This script calls only MT5 *reader* functions: ``account_info``,
``symbol_info``, ``symbol_info_tick``, ``history_deals_get``,
``history_orders_get``. It never calls ``order_send``, ``order_check``
or ``order_calc_*``-with-side-effects, it never opens or closes a
position, and it never writes to the terminal. A regression test asserts
the absence of every ordering primitive in this file, so the property
survives future edits.

The MetaTrader5 package is Windows-only, so it is imported lazily inside
``main``. Every pure adapter below is importable and testable anywhere,
which is how the conversion logic is covered on Linux CI.

WHAT IT CANNOT DO
-----------------
Slippage needs executed fills. If the account has no deal history, the
script writes ``SLIPPAGE_AUTHORITY=MISSING`` and the required future
evidence. It will not place a trade to manufacture a fill.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.friction.authority.capture_schema import (  # noqa: E402
    CAPTURE_SCHEMA_VERSION, QUOTE_CSV_COLUMNS, build_manifest,
)
from ag_edgelab.friction.authority.components import (  # noqa: E402
    AuthorityStatus, CommissionMode, CommissionSpec,
    DEFAULT_SLIPPAGE_REQUIREMENT, SlippageAuthority, SlippageEvidenceKind,
    SwapMode, SwapSpec,
)
from ag_edgelab.friction.authority.quotes import (  # noqa: E402
    SpreadObservation, session_for,
)
from ag_edgelab.friction.authority.symbols import (  # noqa: E402
    SymbolSpec, default_pip_convention,
)

TOOL_VERSION = "capture_vtmarkets_friction/1.0.0"
DEFAULT_SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")

#: MT5 ``SYMBOL_SWAP_MODE`` integers -> named modes.
MT5_SWAP_MODES: dict[int, SwapMode] = {
    0: SwapMode.DISABLED,
    1: SwapMode.POINTS,
    2: SwapMode.BASE_CURRENCY,
    3: SwapMode.MARGIN_CURRENCY,
    4: SwapMode.MARGIN_CURRENCY,
    5: SwapMode.INTEREST,
    6: SwapMode.INTEREST,
    7: SwapMode.BASE_CURRENCY,
    8: SwapMode.BASE_CURRENCY,
}

#: MT5 ``ENUM_DEAL_TYPE``. 2 is DEAL_TYPE_BALANCE, 3 is DEAL_TYPE_CREDIT.
DEAL_TYPE_BUY, DEAL_TYPE_SELL = 0, 1
#: ``ENUM_DEAL_ENTRY``.
DEAL_ENTRY_IN, DEAL_ENTRY_OUT = 0, 1


def _get(obj, name, default=None):
    """Read an attribute from an MT5 named tuple without assuming it exists."""
    value = getattr(obj, name, default)
    return default if value is None else value


# ---------------------------------------------------------------------------
# pure adapters (tested on any platform)
# ---------------------------------------------------------------------------

def symbol_spec_from_mt5(info, *, symbol: str, captured_at: str,
                         source: str = "mt5.symbol_info") -> SymbolSpec:
    """Convert an MT5 ``symbol_info`` record into a SymbolSpec.

    Anything the terminal does not expose stays ``None``. In particular
    ``trade_tick_value`` is copied verbatim — it is the broker's own
    account-currency conversion and must never be recomputed.
    """
    digits = _get(info, "digits")
    return SymbolSpec(
        symbol=symbol,
        broker_symbol=_get(info, "name", symbol),
        digits=digits,
        point=_get(info, "point"),
        trade_tick_size=_get(info, "trade_tick_size"),
        trade_tick_value=_get(info, "trade_tick_value"),
        contract_size=_get(info, "trade_contract_size"),
        currency_base=_get(info, "currency_base"),
        currency_profit=_get(info, "currency_profit"),
        currency_margin=_get(info, "currency_margin"),
        volume_min=_get(info, "volume_min"),
        volume_step=_get(info, "volume_step"),
        volume_max=_get(info, "volume_max"),
        pip_convention=default_pip_convention(symbol, digits),
        source=source,
        captured_at=captured_at,
    )


def swap_spec_from_mt5(info, *, symbol: str,
                       source: str = "mt5.symbol_info") -> SwapSpec:
    raw_mode = _get(info, "swap_mode")
    mode = MT5_SWAP_MODES.get(raw_mode, SwapMode.UNKNOWN) \
        if raw_mode is not None else SwapMode.UNKNOWN
    long_rate = _get(info, "swap_long")
    short_rate = _get(info, "swap_short")
    status = (AuthorityStatus.DECLARED_BY_VENUE
              if mode is not SwapMode.UNKNOWN else AuthorityStatus.MISSING)
    return SwapSpec(
        symbol=symbol,
        swap_long=long_rate,
        swap_short=short_rate,
        swap_mode=mode,
        swap_rollover_3days=_get(info, "swap_rollover3days"),
        status=status,
        source=source,
    )


def commission_from_deals(deals, *, symbol: str | None, currency: str | None,
                          source: str = "mt5.history_deals_get") -> CommissionSpec:
    """Infer the commission schedule from realised deals, or report MISSING.

    MT5 does not expose a commission *schedule* through the API; the only
    hard evidence is what was actually charged on past deals. If the
    account has charged commission on entries and exits at a stable rate
    per lot, that rate is recoverable. If there is no history, the answer
    is MISSING — not "probably $7 round turn".
    """
    rows = [d for d in (deals or [])
            if _get(d, "type") in (DEAL_TYPE_BUY, DEAL_TYPE_SELL)
            and (symbol is None or _get(d, "symbol") == symbol)
            and _get(d, "volume", 0.0) > 0]
    if not rows:
        return CommissionSpec(
            symbol=symbol, status=AuthorityStatus.MISSING,
            source=None,
            note=("no executed deals on this account, so no commission has "
                  "ever been charged and none can be measured. "
                  "COMMISSION_AUTHORITY=MISSING."))

    per_lot = []
    for d in rows:
        volume = _get(d, "volume", 0.0)
        commission = _get(d, "commission", None)
        if volume > 0 and commission is not None:
            per_lot.append(abs(commission) / volume)
    if not per_lot or all(v == 0 for v in per_lot):
        if per_lot and all(v == 0 for v in per_lot):
            return CommissionSpec(
                symbol=symbol, mode=CommissionMode.ZERO_COMMISSION_SPREAD_MARKUP,
                value=0.0, currency=currency,
                scales_linearly_with_closed_volume=True,
                status=AuthorityStatus.CAPTURED, source=source,
                note=(f"{len(per_lot)} deals all carried zero commission; this "
                      "account class prices via spread markup."))
        return CommissionSpec(
            symbol=symbol, status=AuthorityStatus.MISSING, source=source,
            note="deals exist but carry no commission field")

    lo, hi = min(per_lot), max(per_lot)
    stable = (hi - lo) <= max(1e-9, 0.02 * hi)
    if not stable:
        return CommissionSpec(
            symbol=symbol, status=AuthorityStatus.MISSING, source=source,
            note=(f"per-lot commission is not stable across {len(per_lot)} "
                  f"deals (min={lo:.6f}, max={hi:.6f}); the schedule cannot be "
                  "read off history without ambiguity"))
    median = sorted(per_lot)[len(per_lot) // 2]
    return CommissionSpec(
        symbol=symbol, mode=CommissionMode.PER_LOT_PER_SIDE,
        value=round(median, 6), currency=currency,
        scales_linearly_with_closed_volume=True,
        status=AuthorityStatus.CAPTURED, source=source,
        note=(f"measured from {len(per_lot)} executed deals; charged per side "
              f"per lot. Round-turn equivalent is {round(median * 2, 6)} "
              f"{currency or ''}.".strip()))


def slippage_from_deals(deals, orders) -> SlippageAuthority:
    """Measure slippage from fills, or return MISSING with the requirement."""
    order_price = {}
    for o in (orders or []):
        ticket = _get(o, "ticket")
        price = _get(o, "price_open")
        if ticket is not None and price:
            order_price[ticket] = price

    diffs: list[float] = []
    for d in (deals or []):
        if _get(d, "type") not in (DEAL_TYPE_BUY, DEAL_TYPE_SELL):
            continue
        requested = order_price.get(_get(d, "order"))
        achieved = _get(d, "price")
        if not requested or not achieved:
            continue
        direction = 1.0 if _get(d, "type") == DEAL_TYPE_BUY else -1.0
        # Positive means the fill was worse than requested.
        diffs.append((achieved - requested) * direction)

    if not diffs:
        return SlippageAuthority(
            status=AuthorityStatus.MISSING,
            evidence_kind=SlippageEvidenceKind.NONE,
            future_evidence_requirement=DEFAULT_SLIPPAGE_REQUIREMENT)

    diffs.sort()
    n = len(diffs)
    return SlippageAuthority(
        status=AuthorityStatus.CAPTURED,
        evidence_kind=SlippageEvidenceKind.EXECUTED_FILL_HISTORY,
        sample_size=n,
        median_points=diffs[max(0, n // 2 - (0 if n % 2 else 1))],
        p90_points=diffs[min(n - 1, int(-(-0.90 * n // 1)) - 1)],
        source="mt5.history_deals_get x history_orders_get",
        future_evidence_requirement=(),
    )


@dataclass
class CaptureSession:
    """Accumulates observations for one capture run."""

    out_dir: Path
    symbols: tuple[str, ...]
    specs: dict[str, SymbolSpec]
    rows: dict[str, list[dict]]

    @classmethod
    def new(cls, out_dir: Path, symbols: tuple[str, ...]) -> "CaptureSession":
        return cls(out_dir=out_dir, symbols=symbols, specs={},
                   rows={s: [] for s in symbols})

    def record(self, symbol: str, ts: datetime, bid: float, ask: float) -> None:
        obs = SpreadObservation(timestamp_utc=ts, symbol=symbol, bid=bid,
                                ask=ask, session=session_for(ts),
                                source="mt5.symbol_info_tick")
        spec = self.specs.get(symbol)
        row = {
            "timestamp_utc": obs.timestamp_utc.isoformat().replace("+00:00", "Z"),
            "symbol": symbol,
            "bid": f"{bid:.10g}",
            "ask": f"{ask:.10g}",
            "spread_price": f"{obs.spread_price:.10g}",
            "spread_points": (f"{obs.spread_points(spec):.6f}"
                              if spec is not None and spec.point else ""),
            "session": str(obs.session),
        }
        self.rows[symbol].append(row)

    def write_quotes(self) -> dict[str, int]:
        qdir = self.out_dir / "quotes"
        qdir.mkdir(parents=True, exist_ok=True)
        counts = {}
        for symbol, rows in self.rows.items():
            path = qdir / f"{symbol}.csv"
            with path.open("w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(QUOTE_CSV_COLUMNS))
                writer.writeheader()
                writer.writerows(rows)
            counts[symbol] = len(rows)
        return counts


def write_bundle(out_dir: Path, *, metadata: dict, specs: dict[str, SymbolSpec],
                 commissions: dict[str, CommissionSpec],
                 swaps: dict[str, SwapSpec],
                 slippage: SlippageAuthority) -> dict:
    """Write every JSON member plus the hash manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "capture_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    (out_dir / "symbol_metadata.json").write_text(json.dumps(
        {s: spec.as_dict() for s, spec in sorted(specs.items())},
        indent=2, sort_keys=True) + "\n")
    (out_dir / "commission.json").write_text(json.dumps(
        {s: c.as_dict() for s, c in sorted(commissions.items())},
        indent=2, sort_keys=True) + "\n")
    (out_dir / "swap.json").write_text(json.dumps(
        {s: w.as_dict() for s, w in sorted(swaps.items())},
        indent=2, sort_keys=True) + "\n")
    (out_dir / "slippage.json").write_text(
        json.dumps(slippage.as_dict(), indent=2, sort_keys=True) + "\n")

    manifest = build_manifest(out_dir)
    (out_dir / "BUNDLE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


# ---------------------------------------------------------------------------
# live capture
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path,
                    help="bundle output directory")
    ap.add_argument("--symbols", nargs="*", default=list(DEFAULT_SYMBOLS))
    ap.add_argument("--minutes", type=float, default=60.0,
                    help="capture duration; run several short sessions across "
                         "different market hours rather than one long one")
    ap.add_argument("--interval", type=float, default=1.0,
                    help="seconds between quote samples")
    ap.add_argument("--history-days", type=int, default=365,
                    help="days of read-only deal history to scan for "
                         "commission and slippage evidence")
    ap.add_argument("--session-label", default="",
                    help="free-text label, e.g. 'LONDON_OPEN_2026-10-06'")
    args = ap.parse_args(argv)

    try:
        import MetaTrader5 as mt5  # noqa: N813
    except ImportError:
        print("MetaTrader5 is not installed. This capture must run on the "
              "Windows machine hosting the VT Markets terminal:\n"
              "    pip install MetaTrader5\n"
              "There is no Linux build of the package and no way to capture "
              "venue evidence without the terminal.", file=sys.stderr)
        return 2

    if not mt5.initialize():
        print(f"mt5.initialize() failed: {mt5.last_error()}", file=sys.stderr)
        return 3

    try:
        started = datetime.now(timezone.utc)
        account = mt5.account_info()
        if account is None:
            print(f"account_info() returned None: {mt5.last_error()}",
                  file=sys.stderr)
            return 4

        currency = _get(account, "currency")
        is_demo = _get(account, "trade_mode", 0) == 0
        session = CaptureSession.new(args.out, tuple(args.symbols))

        specs: dict[str, SymbolSpec] = {}
        swaps: dict[str, SwapSpec] = {}
        for symbol in args.symbols:
            if not mt5.symbol_select(symbol, True):
                print(f"  ! {symbol}: not selectable on this account",
                      file=sys.stderr)
                continue
            info = mt5.symbol_info(symbol)
            if info is None:
                print(f"  ! {symbol}: symbol_info() returned None",
                      file=sys.stderr)
                continue
            specs[symbol] = symbol_spec_from_mt5(
                info, symbol=symbol,
                captured_at=started.isoformat().replace("+00:00", "Z"))
            swaps[symbol] = swap_spec_from_mt5(info, symbol=symbol)
        session.specs = specs

        # ---- read-only history -------------------------------------
        hist_from = started - timedelta(days=args.history_days)
        deals = mt5.history_deals_get(hist_from, started) or []
        orders = mt5.history_orders_get(hist_from, started) or []
        commissions = {
            symbol: commission_from_deals(deals, symbol=symbol,
                                          currency=currency)
            for symbol in specs
        }
        slippage = slippage_from_deals(deals, orders)

        # ---- quote sampling ----------------------------------------
        deadline = time.monotonic() + args.minutes * 60.0
        samples = 0
        print(f"capturing {len(specs)} symbols for {args.minutes:g} min "
              f"at {args.interval:g}s ...")
        while time.monotonic() < deadline:
            now = datetime.now(timezone.utc)
            for symbol in specs:
                tick = mt5.symbol_info_tick(symbol)
                if tick is None:
                    continue
                bid, ask = _get(tick, "bid", 0.0), _get(tick, "ask", 0.0)
                if bid and ask:
                    session.record(symbol, now, bid, ask)
            samples += 1
            time.sleep(args.interval)
        ended = datetime.now(timezone.utc)
        counts = session.write_quotes()

        metadata = {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "tool_version": TOOL_VERSION,
            "broker": _get(account, "company"),
            "server": _get(account, "server"),
            "account_class": "DEMO" if is_demo else "LIVE",
            "account_type": _get(account, "margin_mode"),
            "account_currency": currency,
            "terminal_build": _get(mt5.terminal_info(), "build"),
            "capture_started_utc": started.isoformat().replace("+00:00", "Z"),
            "capture_ended_utc": ended.isoformat().replace("+00:00", "Z"),
            "session_label": args.session_label,
            "sample_interval_seconds": args.interval,
            "sample_rounds": samples,
            "symbols": sorted(specs),
            "quote_counts": counts,
            "deal_history_days": args.history_days,
            "deal_history_count": len(deals),
            "read_only": True,
        }
        manifest = write_bundle(args.out, metadata=metadata, specs=specs,
                                commissions=commissions, swaps=swaps,
                                slippage=slippage)
        print(f"bundle written to {args.out}")
        print(f"  files={manifest['file_count']} "
              f"root={manifest['manifest_root_sha256'][:16]}...")
        for symbol, n in sorted(counts.items()):
            print(f"  {symbol}: {n} observations")
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
