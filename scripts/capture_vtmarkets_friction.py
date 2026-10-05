#!/usr/bin/env python3
"""Read-only VT Markets / MT5 friction capture (v2).

Run this on the Windows machine where the VT Markets MT5 terminal is
installed and logged in. Each run seals one immutable, hash-verified
evidence bundle that ``scripts/build_friction_authority.py`` ingests.

    python scripts\\capture_vtmarkets_friction.py --root capture_bundles

SCHEDULING (the intended use)
-----------------------------
Spread is a distribution, and a distribution needs repeated sampling
across sessions and weekdays. Register this as a Windows Scheduled Task
and leave it alone:

    schtasks /Create /TN EdgeLabFrictionCapture /SC HOURLY ^
      /TR "C:\\Python311\\python.exe C:\\path\\to\\scripts\\capture_vtmarkets_friction.py --root C:\\path\\to\\capture_bundles"

Every run creates a NEW bundle, ``friction_capture_YYYYMMDD`` (then
``_002``, ``_003`` … within the same day). Nothing previously written is
ever modified: bundles are sealed with a manifest and recorded in an
append-only ``capture_registry.json``. A lock file makes overlapping
runs exit cleanly rather than interleave writes.

READ-ONLY BY CONSTRUCTION
-------------------------
This script calls only MT5 *reader* functions: ``account_info``,
``symbols_get``, ``symbol_info``, ``symbol_info_tick``,
``copy_ticks_range``, ``history_deals_get``, ``history_orders_get``. It
never calls ``order_send``, ``order_check`` or any ``TRADE_ACTION_*``
primitive, never opens, closes or modifies a position or pending order,
and never writes to the terminal or changes account configuration. A
regression test tokenizes this file and asserts the absence of every
ordering primitive, so the property survives future edits.

The account login is written as ``REDACTED``. No credential of any
kind, and no login number, is ever persisted or printed.

SYMBOL NAMES ARE RESOLVED, NEVER ASSUMED
----------------------------------------
Venues decorate symbol names (``EURUSD-VIP``, ``EURUSD.r``, ``GOLD``).
The tool reads the published symbol list and matches against it. It
never constructs a candidate name, because a guessed suffix can resolve
to a different contract with a different lot size, swap and commission,
and every downstream cost figure would then describe an instrument the
owner does not trade. Ambiguities are recorded with all candidates.

QUOTES
------
Real tick history via ``copy_ticks_range`` is preferred; live polling of
``symbol_info_tick`` is the fallback when history is unavailable. Each
quote carries BOTH session labels — the governed V0.3 stratification and
R1's diagnostic slicer — because the two disagree on boundaries and this
tool is not the place to silently pick a winner.

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
from dataclasses import dataclass, replace
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
from ag_edgelab.friction.authority import daily  # noqa: E402
from ag_edgelab.friction.authority.resolution import (  # noqa: E402
    CANONICAL_FX, raw_symbol_info, resolve_all,
)
from ag_edgelab.universal.trigger_v0_4 import session_label  # noqa: E402

TOOL_VERSION = "capture_vtmarkets_friction/2.0.0"
DEFAULT_SYMBOLS = CANONICAL_FX

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


def ticks_to_observations(ticks, *, symbol: str):
    """Convert a ``copy_ticks_range`` result into (ts, bid, ask) triples.

    MT5 returns a numpy structured array with a ``time_msc`` field in
    milliseconds since epoch UTC. Ticks with a zero bid or ask are quote
    updates that carry no two-sided price (volume-only prints); they are
    skipped here and counted by the caller, never written as a spread of
    whatever the other side happened to be.

    Pure, so the conversion is tested on Linux without a terminal.
    """
    out = []
    skipped = 0
    for tick in ticks if ticks is not None else []:
        bid = float(_get(tick, "bid", 0.0) or 0.0)
        ask = float(_get(tick, "ask", 0.0) or 0.0)
        if bid <= 0 or ask <= 0:
            skipped += 1
            continue
        msc = _get(tick, "time_msc", None)
        if msc:
            ts = datetime.fromtimestamp(float(msc) / 1000.0, tz=timezone.utc)
        else:
            secs = _get(tick, "time", None)
            if not secs:
                skipped += 1
                continue
            ts = datetime.fromtimestamp(float(secs), tz=timezone.utc)
        out.append((ts, bid, ask))
    return out, skipped


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

    def record(self, symbol: str, ts: datetime, bid: float, ask: float,
               source: str = "mt5.symbol_info_tick") -> None:
        obs = SpreadObservation(timestamp_utc=ts, symbol=symbol, bid=bid,
                                ask=ask, session=session_for(ts),
                                source=source)
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
            # Governed V0.3 stratification (trigger_v0_4.session_label) is
            # the authority; the column above is R1's diagnostic slicer and
            # is kept so existing distribution code still reads. The two
            # disagree on boundaries, so both are recorded rather than one
            # being silently overwritten by the other.
            "session_governed_v03": session_label(ts),
        }
        self.rows[symbol].append(row)

    def write_quotes(self) -> dict[str, int]:
        qdir = self.out_dir / "quotes"
        qdir.mkdir(parents=True, exist_ok=True)
        counts = {}
        for symbol, rows in self.rows.items():
            path = qdir / f"{symbol}.csv"
            with path.open("w", newline="") as fh:
                writer = csv.DictWriter(
                    fh, fieldnames=[*QUOTE_CSV_COLUMNS, "session_governed_v03"])
                writer.writeheader()
                writer.writerows(rows)
            counts[symbol] = len(rows)
        return counts


def write_bundle(out_dir: Path, *, metadata: dict, specs: dict[str, SymbolSpec],
                 commissions: dict[str, CommissionSpec],
                 swaps: dict[str, SwapSpec],
                 slippage: SlippageAuthority,
                 resolution: dict | None = None,
                 raw_symbol_info_map: dict | None = None) -> dict:
    """Write every JSON member plus the hash manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if resolution is not None:
        (out_dir / "symbol_resolution.json").write_text(
            json.dumps(resolution, indent=2, sort_keys=True) + "\n")
    if raw_symbol_info_map is not None:
        (out_dir / "symbol_info_raw.json").write_text(
            json.dumps(raw_symbol_info_map, indent=2, sort_keys=True,
                       default=str) + "\n")
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

    return daily.seal_bundle(out_dir)


# ---------------------------------------------------------------------------
# live capture
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path("capture_bundles"),
                    help="evidence root; each run seals a new immutable "
                         "friction_capture_YYYYMMDD bundle inside it")
    ap.add_argument("--out", type=Path, default=None,
                    help="explicit bundle directory (overrides --root naming)")
    ap.add_argument("--symbols", nargs="*", default=list(DEFAULT_SYMBOLS),
                    help="canonical names; broker names are RESOLVED, never assumed")
    ap.add_argument("--minutes", type=float, default=60.0,
                    help="live polling duration when tick history is unavailable")
    ap.add_argument("--interval", type=float, default=1.0,
                    help="seconds between polled quote samples")
    ap.add_argument("--tick-history-hours", type=float, default=24.0,
                    help="hours of copy_ticks_range history to prefer over "
                         "polling; 0 disables and forces live polling")
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
        with daily.capture_lock(args.root):
            return _capture(mt5, args)
    except daily.CaptureLocked as exc:
        print(f"{exc}", file=sys.stderr)
        return 5
    finally:
        mt5.shutdown()


def _capture(mt5, args) -> int:
    started = datetime.now(timezone.utc)
    out_dir = args.out or daily.next_bundle_dir(args.root, started)

    account = mt5.account_info()
    if account is None:
        print(f"account_info() returned None: {mt5.last_error()}",
              file=sys.stderr)
        return 4
    currency = _get(account, "currency")
    trade_mode = _get(account, "trade_mode", 0)

    # ---- 1. symbol resolution: never assume a suffix ------------------
    published = mt5.symbols_get() or []
    available = [{"name": _get(x, "name"), "visible": _get(x, "visible"),
                  "select": _get(x, "select"), "path": _get(x, "path")}
                 for x in published]
    resolution = resolve_all(tuple(args.symbols), available)
    mapping = resolution["mapping"]
    if resolution["unresolved"]:
        print(f"  ! unresolved canonicals: {resolution['unresolved']}",
              file=sys.stderr)
    for canonical, broker in sorted(mapping.items()):
        flag = resolution["resolutions"][canonical]["status"]
        print(f"  {canonical:8s} -> {broker}  [{flag}]")
    for c in resolution["crypto_discovered"]:
        print(f"  crypto found: {c['broker_symbol']}")

    session = CaptureSession.new(out_dir, tuple(mapping))
    specs: dict[str, SymbolSpec] = {}
    swaps: dict[str, SwapSpec] = {}
    raw_info: dict[str, dict] = {}
    captured_at = started.isoformat().replace("+00:00", "Z")

    for canonical, broker in sorted(mapping.items()):
        if not mt5.symbol_select(broker, True):
            print(f"  ! {broker}: not selectable", file=sys.stderr)
            continue
        info = mt5.symbol_info(broker)
        if info is None:
            print(f"  ! {broker}: symbol_info() returned None", file=sys.stderr)
            continue
        specs[canonical] = symbol_spec_from_mt5(
            info, symbol=canonical, captured_at=captured_at)
        specs[canonical] = replace(specs[canonical], broker_symbol=broker)
        swaps[canonical] = swap_spec_from_mt5(info, symbol=canonical)
        raw_info[canonical] = raw_symbol_info(info, broker_symbol=broker)
    session.specs = specs

    # ---- 2. read-only account history ---------------------------------
    hist_from = started - timedelta(days=args.history_days)
    deals = mt5.history_deals_get(hist_from, started) or []
    orders = mt5.history_orders_get(hist_from, started) or []
    commissions = {
        canonical: commission_from_deals(deals, symbol=mapping[canonical],
                                         currency=currency)
        for canonical in specs}
    slippage = slippage_from_deals(deals, orders)

    # ---- 3. quotes: prefer real tick history --------------------------
    tick_sources: dict[str, str] = {}
    skipped_total = 0
    if args.tick_history_hours > 0:
        frm = started - timedelta(hours=args.tick_history_hours)
        for canonical in specs:
            broker = mapping[canonical]
            try:
                ticks = mt5.copy_ticks_range(
                    broker, frm, started, mt5.COPY_TICKS_INFO)
            except Exception as exc:                      # noqa: BLE001
                print(f"  ! {broker}: copy_ticks_range failed: {exc}",
                      file=sys.stderr)
                ticks = None
            rows, skipped = ticks_to_observations(ticks, symbol=canonical)
            skipped_total += skipped
            for ts, bid, ask in rows:
                session.record(canonical, ts, bid, ask,
                               source="mt5.copy_ticks_range")
            tick_sources[canonical] = (
                "copy_ticks_range" if rows else "copy_ticks_range_empty")
            print(f"  {broker}: {len(rows)} ticks from history "
                  f"({skipped} one-sided skipped)")

    polled_rounds = 0
    needs_poll = args.minutes > 0 and (
        not tick_sources or all(v.endswith("_empty") for v in tick_sources.values()))
    if needs_poll:
        deadline = time.monotonic() + args.minutes * 60.0
        print(f"tick history unavailable; polling {len(specs)} symbols for "
              f"{args.minutes:g} min at {args.interval:g}s ...")
        while time.monotonic() < deadline:
            now = datetime.now(timezone.utc)
            for canonical in specs:
                tick = mt5.symbol_info_tick(mapping[canonical])
                if tick is None:
                    continue
                bid, ask = _get(tick, "bid", 0.0), _get(tick, "ask", 0.0)
                if bid and ask:
                    session.record(canonical, now, bid, ask)
            polled_rounds += 1
            time.sleep(args.interval)
        for canonical in specs:
            tick_sources.setdefault(canonical, "symbol_info_tick_poll")

    ended = datetime.now(timezone.utc)
    counts = session.write_quotes()

    terminal = mt5.terminal_info()
    metadata = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "broker": _get(account, "company"),
        "server": _get(account, "server"),
        "account_class": "DEMO" if trade_mode == 0 else "LIVE",
        "account_type": _get(account, "margin_mode"),
        "account_currency": currency,
        "account_trade_mode_raw": trade_mode,
        "account_login": "REDACTED",
        "login_redacted": True,
        "terminal_build": _get(terminal, "build"),
        "terminal_company": _get(terminal, "company"),
        "terminal_name": _get(terminal, "name"),
        "capture_started_utc": captured_at,
        "capture_ended_utc": ended.isoformat().replace("+00:00", "Z"),
        "session_label": args.session_label,
        "sample_interval_seconds": args.interval,
        "sample_rounds": polled_rounds,
        "quote_source": tick_sources,
        "one_sided_ticks_skipped": skipped_total,
        "symbols": sorted(specs),
        "symbol_mapping": mapping,
        "quote_counts": counts,
        "deal_history_days": args.history_days,
        "deal_history_count": len(deals),
        "session_authority": {
            "governed": "SESSION_WINDOWS_UTC_V0_3_STRATIFICATION "
                        "(ag_edgelab.universal.trigger_v0_4.session_label)",
            "diagnostic": "ag_edgelab.friction.authority.quotes.session_for",
            "note": "both recorded per quote; no new session window defined",
        },
        "read_only": True,
        "order_calls_executed": False,
    }
    manifest = write_bundle(out_dir, metadata=metadata, specs=specs,
                            commissions=commissions, swaps=swaps,
                            slippage=slippage, resolution=resolution,
                            raw_symbol_info_map=raw_info)
    row = daily.row_for(out_dir, manifest, metadata)
    daily.append_registry(args.root, row)

    print(f"\nsealed {out_dir}")
    print(f"  files={manifest['file_count']} bytes={manifest['total_bytes']} "
          f"root={manifest['manifest_root_sha256'][:16]}...")
    for canonical, n in sorted(counts.items()):
        print(f"  {canonical}: {n} observations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
