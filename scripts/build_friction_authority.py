#!/usr/bin/env python3
"""Build VT_MARKETS_FRICTION_AUTHORITY_V1 from captured evidence bundles.

    python scripts/build_friction_authority.py                       # no evidence
    python scripts/build_friction_authority.py --bundle capture_bundles/a \
                                               --bundle capture_bundles/b

With no bundle the authority is emitted in its honest MISSING state: the
framework exists, the evidence does not, and every status says so. With
one or more bundles the quote CSVs are summarised into per-symbol,
per-session distributions, the venue identity and symbol contracts are
bound, and ``FRICTION_AUTHORITY_SHA256`` is computed over the lot.

Bundles are verified by hash before anything is read from them. The raw
quote CSVs stay where they are — out of git — and only their hashes,
counts and summary statistics enter the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.friction.authority import (  # noqa: E402
    AccountClass, AuthorityStatus, CommissionMode, CommissionSpec,
    DEFAULT_SLIPPAGE_REQUIREMENT, ExitKind, ExitLeg,
    FRICTION_AUTHORITY_ID, FrictionAuthorityContract,
    HISTORICAL_FRICTION_LIMITATION, HistoricalCostPolicy, PipConvention,
    ScenarioContract, Side, SlippageAuthority, SlippageEvidenceKind,
    SpreadConvention, SpreadEvidence, SpreadObservation, SwapApplicability,
    SwapSpec, SymbolSpec, TradePlan, VenueIdentity, compute_costs,
    determine_swap_applicability, economic_verification_ready, session_for,
)
from ag_edgelab.friction.authority.capture_schema import (  # noqa: E402
    CAPTURE_SCHEMA_VERSION, QUOTE_CSV_COLUMNS, read_quote_csv, verify_bundle,
)
from ag_edgelab.friction.authority.components import SwapMode  # noqa: E402

OUT_DIR = ROOT / "artifacts" / "friction_authority_r1"
SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")
VENUE = "VT_MARKETS"
DATASET_PERIOD = "2011-06-01/2018-06-06"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds") \
        .replace("+00:00", "Z")


def _write(name: str, payload) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    if isinstance(payload, str):
        path.write_text(payload)
    else:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# source inventory: what was probed and what answered
# ---------------------------------------------------------------------------

def probe_sources() -> dict:
    """Record, as evidence, which venue access paths exist on this host."""
    checks: list[dict] = []

    def record(name: str, available: bool, detail: str) -> None:
        checks.append({"source": name, "available": available,
                       "detail": detail})

    try:
        import MetaTrader5  # noqa: F401
        record("MetaTrader5 python package", True, "importable")
    except ImportError as exc:
        record("MetaTrader5 python package", False,
               f"{exc}; the package ships Windows-only wheels and has no "
               "Linux distribution")

    for path in ("/opt/mt5", "/usr/lib/wine"):
        record(f"terminal path {path}", Path(path).exists(),
               "present" if Path(path).exists() else "absent")

    for host in ("www.vtmarkets.com", "api.vtmarkets.com", "mt5.vtmarkets.com"):
        code = "000"
        try:
            proc = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 "--max-time", "8", f"https://{host}/"],
                capture_output=True, text=True, timeout=20)
            code = (proc.stdout or "000").strip() or "000"
        except Exception as exc:  # pragma: no cover - environment dependent
            code = f"error:{exc}"
        record(f"https://{host}/", code not in ("000",) and not
               str(code).startswith("error"), f"http_status={code}")

    bundles = sorted((ROOT / "capture_bundles").glob("*")) \
        if (ROOT / "capture_bundles").is_dir() else []
    record("local capture bundles", bool(bundles),
           f"{len(bundles)} bundle directory(ies) under capture_bundles/")

    return {
        "generated_utc": _now(),
        "venue": VENUE,
        "purpose": ("enumerate every path by which VT Markets account and "
                    "terminal evidence could be obtained, and record which "
                    "ones actually answered"),
        "checks": checks,
        "any_live_source_available": any(c["available"] for c in checks),
        "credentials_requested": False,
        "credentials_policy": (
            "This mission never requests, stores or transmits broker "
            "credentials. Capture runs on the user's own machine under their "
            "own logged-in terminal."),
        "orders_placed": 0,
        "access_mode": "READ_ONLY",
    }


# ---------------------------------------------------------------------------
# bundle ingest
# ---------------------------------------------------------------------------

def load_bundles(paths: list[Path]) -> dict:
    """Verify and merge evidence bundles."""
    merged = {
        "bundles": [],
        "venue": None,
        "specs": {},
        "commissions": {},
        "swaps": {},
        "slippage": None,
        "evidence": {},
        "quote_files": [],
        "capture_started": None,
        "capture_ended": None,
    }
    for path in paths:
        report = verify_bundle(Path(path))
        meta = json.loads((Path(path) / "capture_metadata.json").read_text())
        merged["bundles"].append({
            "path": str(path),
            "manifest_root_sha256": report["manifest_root_sha256"],
            "file_count": report["file_count"],
            "capture_started_utc": meta.get("capture_started_utc"),
            "capture_ended_utc": meta.get("capture_ended_utc"),
            "session_label": meta.get("session_label", ""),
            "broker": meta.get("broker"),
            "server": meta.get("server"),
            "account_class": meta.get("account_class"),
            "sample_interval_seconds": meta.get("sample_interval_seconds"),
        })

        venue = VenueIdentity(
            broker=meta.get("broker"), server=meta.get("server"),
            account_class=AccountClass(meta.get("account_class", "UNKNOWN")),
            account_type=str(meta.get("account_type"))
            if meta.get("account_type") is not None else None,
            account_currency=meta.get("account_currency"),
            terminal_build=meta.get("terminal_build"))
        if merged["venue"] is None:
            merged["venue"] = venue
        else:
            merged["venue"].assert_matches(venue)

        for label in ("capture_started", "capture_ended"):
            value = meta.get(f"{label}_utc")
            current = merged[label]
            if value and (current is None
                          or (label == "capture_started" and value < current)
                          or (label == "capture_ended" and value > current)):
                merged[label] = value

        raw_specs = json.loads((Path(path) / "symbol_metadata.json").read_text())
        for symbol, d in raw_specs.items():
            merged["specs"][symbol] = SymbolSpec(
                symbol=symbol, broker_symbol=d.get("broker_symbol"),
                digits=d.get("digits"), point=d.get("point"),
                trade_tick_size=d.get("trade_tick_size"),
                trade_tick_value=d.get("trade_tick_value"),
                contract_size=d.get("contract_size"),
                currency_base=d.get("currency_base"),
                currency_profit=d.get("currency_profit"),
                currency_margin=d.get("currency_margin"),
                volume_min=d.get("volume_min"), volume_step=d.get("volume_step"),
                volume_max=d.get("volume_max"),
                pip_convention=PipConvention(d["pip_convention"])
                if d.get("pip_convention") else None,
                source=d.get("source"), captured_at=d.get("captured_at"))

        raw_comm = json.loads((Path(path) / "commission.json").read_text())
        for symbol, d in raw_comm.items():
            merged["commissions"][symbol] = CommissionSpec(
                symbol=symbol, mode=CommissionMode(d.get("mode", "UNKNOWN")),
                value=d.get("value"), currency=d.get("currency"),
                scales_linearly_with_closed_volume=d.get(
                    "scales_linearly_with_closed_volume"),
                status=AuthorityStatus(d.get("status", "MISSING")),
                source=d.get("source"), source_hash=d.get("source_hash"),
                note=d.get("note", ""))

        raw_swap = json.loads((Path(path) / "swap.json").read_text())
        for symbol, d in raw_swap.items():
            merged["swaps"][symbol] = SwapSpec(
                symbol=symbol, swap_long=d.get("swap_long"),
                swap_short=d.get("swap_short"),
                swap_mode=SwapMode(d.get("swap_mode", "UNKNOWN")),
                swap_rollover_3days=d.get("swap_rollover_3days"),
                status=AuthorityStatus(d.get("status", "MISSING")),
                source=d.get("source"))

        raw_slip = json.loads((Path(path) / "slippage.json").read_text())
        slip = SlippageAuthority(
            status=AuthorityStatus(raw_slip.get("status", "MISSING")),
            evidence_kind=SlippageEvidenceKind(
                raw_slip.get("evidence_kind", "NONE")),
            sample_size=raw_slip.get("sample_size"),
            median_points=raw_slip.get("median_points"),
            p90_points=raw_slip.get("p90_points"),
            source=raw_slip.get("source"),
            future_evidence_requirement=tuple(
                raw_slip.get("future_evidence_requirement", ())))
        if merged["slippage"] is None or slip.is_complete:
            merged["slippage"] = slip

        qdir = Path(path) / "quotes"
        for csv_path in sorted(qdir.glob("*.csv")) if qdir.is_dir() else []:
            symbol = csv_path.stem
            rows = read_quote_csv(csv_path)
            merged["quote_files"].append({
                "bundle": str(path),
                "relative_path": csv_path.relative_to(Path(path)).as_posix(),
                "symbol": symbol,
                "rows": len(rows),
                "sha256": report["files"][
                    csv_path.relative_to(Path(path)).as_posix()],
                "bytes": csv_path.stat().st_size,
            })
            ev = merged["evidence"].setdefault(symbol, SpreadEvidence(symbol))
            for row in rows:
                ts = datetime.fromisoformat(
                    row["timestamp_utc"].replace("Z", "+00:00"))
                ev.observations.append(SpreadObservation(
                    timestamp_utc=ts, symbol=symbol,
                    bid=float(row["bid"]), ask=float(row["ask"]),
                    session=session_for(ts), source="mt5.symbol_info_tick"))
    return merged


# ---------------------------------------------------------------------------
# cost contract
# ---------------------------------------------------------------------------

def partial_runner_contract() -> dict:
    """The leg model, its invariants, and a clearly-labelled worked example."""
    illustrative = SymbolSpec(
        symbol="ILLUSTRATIVE_FX_5DIGIT", digits=5, point=0.00001,
        trade_tick_size=0.00001, trade_tick_value=1.0, contract_size=100000.0,
        currency_base="XXX", currency_profit="YYY", currency_margin="XXX",
        source="ILLUSTRATIVE_NOT_VENUE_EVIDENCE")
    commission = CommissionSpec(
        symbol="ILLUSTRATIVE_FX_5DIGIT", mode=CommissionMode.PER_LOT_PER_SIDE,
        value=3.5, currency="YYY", scales_linearly_with_closed_volume=True,
        status=AuthorityStatus.CAPTURED, source="ILLUSTRATIVE_NOT_VENUE_EVIDENCE")
    slippage = SlippageAuthority(
        status=AuthorityStatus.CAPTURED,
        evidence_kind=SlippageEvidenceKind.EXECUTED_FILL_HISTORY,
        sample_size=1, median_points=0.0, p90_points=0.0,
        source="ILLUSTRATIVE_NOT_VENUE_EVIDENCE")
    swap = SwapSpec(symbol="ILLUSTRATIVE_FX_5DIGIT", swap_mode=SwapMode.DISABLED,
                    status=AuthorityStatus.DECLARED_BY_VENUE,
                    source="ILLUSTRATIVE_NOT_VENUE_EVIDENCE")

    shapes = {}
    entry, stop = 1.10000, 1.09800
    common = dict(spec=illustrative, spread_price=0.00010,
                  commission=commission, slippage=slippage, swap=swap,
                  swap_applicability=SwapApplicability.NOT_APPLICABLE)

    plans = {
        "single_full_exit": TradePlan(
            symbol=illustrative.symbol, side=Side.LONG, entry_price=entry,
            stop_price=stop, volume_lots=1.0,
            exits=(ExitLeg(1.0, 1.10400, ExitKind.FULL_TARGET),)),
        "partial_then_runner": TradePlan(
            symbol=illustrative.symbol, side=Side.LONG, entry_price=entry,
            stop_price=stop, volume_lots=1.0,
            exits=(ExitLeg(0.5, 1.10200, ExitKind.TARGET_PARTIAL),
                   ExitLeg(0.5, 1.10600, ExitKind.RUNNER))),
        "stop_exit": TradePlan(
            symbol=illustrative.symbol, side=Side.LONG, entry_price=entry,
            stop_price=stop, volume_lots=1.0,
            exits=(ExitLeg(1.0, 1.09800, ExitKind.STOP),)),
        "horizon_exit": TradePlan(
            symbol=illustrative.symbol, side=Side.LONG, entry_price=entry,
            stop_price=stop, volume_lots=1.0,
            exits=(ExitLeg(1.0, 1.10050, ExitKind.HORIZON),)),
        "forced_close": TradePlan(
            symbol=illustrative.symbol, side=Side.LONG, entry_price=entry,
            stop_price=stop, volume_lots=1.0,
            exits=(ExitLeg(0.5, 1.10200, ExitKind.TARGET_PARTIAL),
                   ExitLeg(0.5, 1.09950, ExitKind.FORCED_CLOSE))),
    }
    for name, plan in plans.items():
        shapes[name] = compute_costs(plan, **common).as_dict()

    return {
        "contract_version": "EDGELAB_PARTIAL_RUNNER_COST_CONTRACT_V1",
        "generated_utc": _now(),
        "exit_shapes_priced": sorted(plans),
        "leg_model": {
            "entry": "one crossing on full volume",
            "each_exit": "one crossing on that leg's volume",
            "legs_are_explicit": True,
            "exit_kinds": [str(k) for k in ExitKind],
        },
        "spread_allocation": {
            "default_convention": str(SpreadConvention.FULL_SPREAD_ON_ENTRY),
            "reference_price_basis": "BID",
            "why": (
                "The data authority's canonical OHLC is built from the BID "
                "series. A long signalled on bid actually enters at ask "
                "(bid + spread) and exits at bid, so the entire round-trip "
                "spread is incurred once, at entry. A short is the mirror "
                "image. Charging a further spread at each exit would bill a "
                "two-partial trade for three round trips."),
            "alternative_convention": str(SpreadConvention.HALF_SPREAD_PER_LEG),
            "alternative_use": (
                "correct when the reference series is mid-price; half the "
                "spread is charged at entry and half pro-rata across exits"),
            "invariant": (
                "total spread cost depends only on the volume traded, never "
                "on how many pieces the exit was broken into; both "
                "conventions produce the same round-trip total"),
        },
        "commission_allocation": {
            "charged": "per side, on the volume that side actually transacts",
            "partial_exits": (
                "each partial is charged on its own closed volume, so the sum "
                "over partials equals the single full-volume exit charge"),
            "round_turn_modes_are_halved_per_side": True,
            "invariant": "sum(partial exit commissions) == full exit commission",
        },
        "slippage_allocation": {
            "charged": "per leg, on that leg's volume",
            "per_leg_override": "supported, for stop/forced legs that slip worse",
            "default": "the authority's conservative (P90) figure",
            "missing_behaviour": "raises; never silently zero",
        },
        "swap_allocation": {
            "charged": "per rollover held, on the volume still open",
            "excluded_only_when": (
                "a FROZEN strategy contract proves no position can be open at "
                "the venue rollover"),
        },
        "double_counting_guards": [
            "spread total is invariant to the number of partial exits",
            "commission is never charged twice for the same crossing",
            "swap is charged on open volume only, so a closed partial stops "
            "accruing financing",
        ],
        "worked_example_illustrative": {
            "WARNING": (
                "These numbers are ARITHMETIC ILLUSTRATION ONLY. The symbol "
                "contract, commission and slippage values below are invented "
                "placeholders to demonstrate the leg algebra. They are NOT VT "
                "Markets evidence and must never be cited as venue friction."),
            "is_venue_evidence": False,
            "symbol_spec": illustrative.as_dict(),
            "commission_spec": commission.as_dict(),
            "spread_price": 0.00010,
            "results": shapes,
            "demonstrated_invariants": {
                "spread_identical_across_exit_shapes": (
                    round(shapes["single_full_exit"]["spread_money"], 8)
                    == round(shapes["partial_then_runner"]["spread_money"], 8)),
                "commission_identical_across_exit_shapes": (
                    round(shapes["single_full_exit"]["commission_money"], 8)
                    == round(shapes["partial_then_runner"]["commission_money"], 8)),
            },
        },
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", action="append", type=Path, default=[],
                    help="evidence bundle directory (repeatable)")
    ap.add_argument("--strategy-closes-before-rollover",
                    choices=["yes", "no", "unknown"], default="unknown")
    ap.add_argument("--strategy-contract-frozen", action="store_true")
    ap.add_argument("--manifest-only", action="store_true",
                    help="rehash the existing artifacts and rewrite only "
                         "artifact_manifest.json; used after test_results.txt "
                         "is written so the manifest covers the real run")
    args = ap.parse_args(argv)

    if args.manifest_only:
        return _rewrite_manifest()

    inventory = probe_sources()
    merged = load_bundles(args.bundle) if args.bundle else None

    # ---- assemble the contract -------------------------------------
    if merged:
        venue = merged["venue"] or VenueIdentity()
        specs = merged["specs"]
        commissions = merged["commissions"]
        swaps = merged["swaps"]
        slippage = merged["slippage"] or SlippageAuthority(
            future_evidence_requirement=DEFAULT_SLIPPAGE_REQUIREMENT)
        evidence = merged["evidence"]
    else:
        venue = VenueIdentity()
        specs = {s: SymbolSpec(symbol=s) for s in SYMBOLS}
        commissions = {s: CommissionSpec(
            symbol=s, status=AuthorityStatus.MISSING,
            note=("no VT Markets account evidence has been ingested; the "
                  "commission schedule is unknown and no industry default is "
                  "substituted")) for s in SYMBOLS}
        swaps = {s: SwapSpec(symbol=s, status=AuthorityStatus.MISSING)
                 for s in SYMBOLS}
        slippage = SlippageAuthority(
            future_evidence_requirement=DEFAULT_SLIPPAGE_REQUIREMENT)
        evidence = {}

    closes = {"yes": True, "no": False, "unknown": None}[
        args.strategy_closes_before_rollover]
    applicability, reason = determine_swap_applicability(
        strategy_contract_closes_before_rollover=closes,
        contract_is_frozen=args.strategy_contract_frozen)

    # ---- distributions ----------------------------------------------
    distributions: dict[str, dict] = {}
    spread_evidence_block: dict[str, dict] = {}
    for symbol in sorted(set(SYMBOLS) | set(evidence)):
        spec = specs.get(symbol, SymbolSpec(symbol=symbol))
        ev = evidence.get(symbol)
        if ev is None or not ev.observations:
            distributions[symbol] = {
                "symbol": symbol, "status": "MISSING", "N": 0,
                "sessions": {},
                "note": ("no quote observations captured for this symbol; "
                         "SPREAD_AUTHORITY=MISSING"),
            }
            spread_evidence_block[symbol] = {"n": 0, "status": "MISSING"}
            continue
        cells = {k: d.as_dict() for k, d in ev.distributions(spec).items()}
        distributions[symbol] = {
            "symbol": symbol, "status": "CAPTURED",
            "N": cells["ALL"]["N"], "unit": cells["ALL"]["unit"],
            "sessions": cells,
        }
        spread_evidence_block[symbol] = {
            "n": cells["ALL"]["N"],
            "status": "CAPTURED",
            "unit": cells["ALL"]["unit"],
            "p50": cells["ALL"]["P50"],
            "p90": cells["ALL"]["P90"],
            "p95": cells["ALL"]["P95"],
            "evidence_sha256": sorted(
                q["sha256"] for q in (merged["quote_files"] if merged else [])
                if q["symbol"] == symbol),
        }

    contract = FrictionAuthorityContract(
        venue=venue, symbols=specs, commissions=commissions, swaps=swaps,
        slippage=slippage, swap_applicability=applicability,
        swap_applicability_reason=reason,
        spread_evidence=spread_evidence_block,
        capture_started_utc=merged["capture_started"] if merged else None,
        capture_ended_utc=merged["capture_ended"] if merged else None,
        scenario_contract=ScenarioContract(),
        historical_policy=HistoricalCostPolicy(),
    )

    # ---- readiness ---------------------------------------------------
    readiness = {}
    for symbol in SYMBOLS:
        ok, blockers = economic_verification_ready(
            spec=specs.get(symbol, SymbolSpec(symbol=symbol)),
            spread_observations=spread_evidence_block.get(
                symbol, {}).get("n", 0),
            commission=commissions.get(symbol, CommissionSpec(symbol=symbol)),
            slippage=slippage,
            swap=swaps.get(symbol, SwapSpec(symbol=symbol)),
            swap_applicability=applicability)
        readiness[symbol] = {"ready": ok, "blockers": blockers}

    # ---- write artifacts ---------------------------------------------
    written: list[Path] = []
    written.append(_write("friction_source_inventory.json", inventory))
    written.append(_write("vtmarkets_symbol_metadata.json", {
        "generated_utc": _now(),
        "venue": VENUE,
        "declared_universe": list(SYMBOLS),
        "symbols": {s: specs[s].as_dict() for s in sorted(specs)},
        "complete_symbols": sorted(s for s, v in specs.items() if v.is_complete),
        "incomplete_symbols": sorted(
            s for s, v in specs.items() if not v.is_complete),
        "policy": ("fields absent from the terminal remain null; nothing is "
                   "derived, defaulted or inferred — trade_tick_value in "
                   "particular is the broker's own account-currency figure"),
    }))
    written.append(_write("spread_capture_manifest.json", {
        "generated_utc": _now(),
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "quote_csv_columns": list(QUOTE_CSV_COLUMNS),
        "bundles": merged["bundles"] if merged else [],
        "quote_files": merged["quote_files"] if merged else [],
        "total_observations": sum(
            q["rows"] for q in (merged["quote_files"] if merged else [])),
        "storage_policy": (
            "raw quote CSVs are content-addressed evidence held OUTSIDE git; "
            "only hashes, counts and summary statistics are committed"),
        "session_coverage_required": [
            "ASIAN (quiet)", "LONDON", "OVERLAP (London/New York)",
            "NEW_YORK", "session opens", "XAUUSD instrument-specific hours"],
        "session_coverage_observed": sorted({
            s for d in distributions.values()
            for s in d.get("sessions", {}) if s != "ALL"}),
        "coverage_complete": bool(merged) and bool(distributions) and all(
            d.get("N", 0) > 0 for d in distributions.values()),
        "cadence_policy": (
            "capture in several short supervised sessions across different "
            "market hours; do not leave an unattended machine running to "
            "satisfy a cadence target"),
    }))
    written.append(_write("spread_distribution.json", {
        "generated_utc": _now(),
        "quantile_method": "nearest-rank, no interpolation",
        "outlier_policy": ("flagged above 10x the median and COUNTED, never "
                           "removed — a spread spike is real cost"),
        "quantile_selection_policy": (
            "this mission establishes the distribution only; it does not "
            "nominate P50/P90/P95 as 'the' friction for any strategy"),
        "symbols": distributions,
    }))
    written.append(_write("commission_authority.json", {
        "generated_utc": _now(),
        "status": str(contract.commission_authority_status),
        "per_symbol": {s: c.as_dict() for s, c in sorted(commissions.items())},
        "questions_the_authority_must_answer": [
            "per lot or per notional?", "per side or round turn?",
            "which currency?",
            "does it scale linearly with closed volume on partial exits?"],
        "no_default_policy": (
            "if the schedule is unavailable the status is MISSING; no "
            "industry-typical figure is substituted"),
    }))
    written.append(_write("slippage_authority.json", {
        "generated_utc": _now(),
        **slippage.as_dict(),
        "separate_from_spread": True,
        "no_default_policy": (
            "no 0.1/0.2 pip allowance is invented; slippage without fill "
            "evidence is MISSING"),
    }))
    written.append(_write("swap_authority.json", {
        "generated_utc": _now(),
        "status": str(contract.swap_authority_status),
        "applicability": str(applicability),
        "applicability_reason": reason,
        "per_symbol": {s: w.as_dict() for s, w in sorted(swaps.items())},
        "not_applicable_requires": (
            "a FROZEN strategy contract proving no position can be open at "
            "the venue rollover; absent that, swap stays active"),
    }))
    written.append(_write("partial_runner_cost_contract.json",
                          partial_runner_contract()))

    contract_dict = contract.as_dict()
    written.append(_write("friction_authority_contract.json", contract_dict))
    authority_hash = contract.hash()
    written.append(_write("friction_authority_hash.json", {
        "friction_authority_id": FRICTION_AUTHORITY_ID,
        "FRICTION_AUTHORITY_SHA256": authority_hash,
        "generated_utc": _now(),
        "hash_covers": sorted(contract.payload().keys()),
        "hash_method": ("sha256 over the canonical JSON payload "
                        "(sort_keys=True, separators=(',',':'))"),
    }))
    written.append(_write("economic_scenario_contract.json", {
        "generated_utc": _now(),
        **ScenarioContract().as_dict(),
        "historical_applicability": {
            "limitation": HISTORICAL_FRICTION_LIMITATION,
            "dataset_period": DATASET_PERIOD,
            "capture_period": (
                f"{contract.capture_started_utc}/{contract.capture_ended_utc}"
                if contract.capture_started_utc else "NONE"),
            "research_policy": HistoricalCostPolicy().as_dict(),
        },
        "scenarios_are_executable": bool(
            spread_evidence_block and any(
                v.get("n", 0) > 0 for v in spread_evidence_block.values())),
    }))
    written.append(_write("friction_readiness.json", {
        "generated_utc": _now(),
        "FRICTION_FRAMEWORK_READY": True,
        "FRICTION_AUTHORITY_COMPLETE": contract.is_complete,
        "ECONOMIC_VERIFICATION_READY": all(
            r["ready"] for r in readiness.values()),
        "PARTIAL_EXIT_COST_READY": True,
        "RUNNER_EXIT_COST_READY": True,
        "per_symbol": readiness,
        "blockers": contract.blockers(),
        "fail_closed": (
            "assert_usable_for_economics() raises while any required "
            "component is MISSING; nothing defaults to zero"),
    }))
    return _finalise(written, contract, contract_dict, authority_hash,
                     distributions, readiness, inventory, merged, applicability)


def _rewrite_manifest() -> int:
    """Rehash every artifact already on disk; rewrite only the manifest."""
    existing = json.loads((OUT_DIR / "artifact_manifest.json").read_text())
    entries = [{"name": p.name, "sha256": _sha256(p), "bytes": p.stat().st_size}
               for p in sorted(OUT_DIR.iterdir())
               if p.is_file() and p.name != "artifact_manifest.json"]
    existing["artifact_count"] = len(entries)
    existing["artifacts"] = entries
    existing["generated_utc"] = _now()
    _write("artifact_manifest.json", existing)
    print(f"rehashed {len(entries)} artifacts in {OUT_DIR}")
    return 0


def _finalise(written, contract, contract_dict, authority_hash, distributions,
              readiness, inventory, merged, applicability) -> int:
    """Write the report trio and the artifact manifest."""
    blockers = contract.blockers()
    status = ("FRICTION_AUTHORITY_ESTABLISHED" if contract.is_complete
              else ("FRICTION_PARTIALLY_ESTABLISHED"
                    if merged else "BLOCKED_BROKER_AUTHORITY"))

    def cell(symbol: str, key: str):
        d = distributions.get(symbol, {})
        allc = d.get("sessions", {}).get("ALL", {})
        return allc.get(key)

    spread_blocks = {
        symbol: {
            "N": cell(symbol, "N") or 0,
            "P50": cell(symbol, "P50"),
            "P90": cell(symbol, "P90"),
            "P95": cell(symbol, "P95"),
            "unit": cell(symbol, "unit"),
        } for symbol in SYMBOLS
    }

    report = {
        "TASK_CLASS": "SYSTEM_DEVELOPMENT / FRICTION_AUTHORITY",
        "generated_utc": _now(),
        "VENUE": VENUE,
        "ACCOUNT_CLASS": str(contract.venue.account_class),
        "SYMBOLS": list(SYMBOLS),
        "SPREAD_AUTHORITY": str(contract.spread_authority_status),
        "COMMISSION_AUTHORITY": str(contract.commission_authority_status),
        "SLIPPAGE_AUTHORITY": str(contract.slippage.status),
        "SWAP_AUTHORITY": str(contract.swap_authority_status),
        "SWAP_APPLICABILITY": str(applicability),
        "PARTIAL_EXIT_COST_READY": "YES",
        "RUNNER_EXIT_COST_READY": "YES",
        "FRICTION_AUTHORITY_ID": FRICTION_AUTHORITY_ID,
        "FRICTION_AUTHORITY_SHA256": authority_hash,
        "SPREAD": spread_blocks,
        "HISTORICAL_FRICTION_LIMITATION": HISTORICAL_FRICTION_LIMITATION,
        "FRICTION_AUTHORITY_COMPLETE": "YES" if contract.is_complete else "NO",
        "ECONOMIC_VERIFICATION_READY": (
            "YES" if all(r["ready"] for r in readiness.values()) else "NO"),
        "BLOCKERS": blockers,
        "LIVE_SOURCE_AVAILABLE": inventory["any_live_source_available"],
        "ORDERS_PLACED": 0,
        "STATUS": status,
    }
    written.append(_write("final_report.json", report))

    md = [
        "# FRICTION_AUTHORITY_R1 — final report",
        "",
        f"- **Venue**: {VENUE}",
        f"- **Account class**: {contract.venue.account_class}",
        f"- **Authority id**: `{FRICTION_AUTHORITY_ID}`",
        f"- **FRICTION_AUTHORITY_SHA256**: `{authority_hash}`",
        f"- **Status**: `{status}`",
        "",
        "## Component authorities",
        "",
        "| Component | Status |",
        "| --- | --- |",
        f"| SPREAD | {contract.spread_authority_status} |",
        f"| COMMISSION | {contract.commission_authority_status} |",
        f"| SLIPPAGE | {contract.slippage.status} |",
        f"| SWAP | {contract.swap_authority_status} ({applicability}) |",
        "",
        "## Spread distribution (all sessions)",
        "",
        "| Symbol | N | P50 | P90 | P95 | Unit |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for symbol in SYMBOLS:
        b = spread_blocks[symbol]
        md.append(f"| {symbol} | {b['N']} | {b['P50']} | {b['P90']} | "
                  f"{b['P95']} | {b['unit'] or '—'} |")
    md += [
        "",
        "## Blockers",
        "",
    ]
    md += [f"- {b}" for b in blockers] or ["- none"]
    md += [
        "",
        "## Historical applicability",
        "",
        HISTORICAL_FRICTION_LIMITATION,
        "",
        "## Guarantees",
        "",
        "- No orders were placed; all venue access is read-only.",
        "- No broker credentials were requested, stored or transmitted.",
        "- Missing components are MISSING, never zero: "
        "`assert_usable_for_economics()` fails closed.",
        "- No strategy was evaluated, retuned or created.",
        "",
    ]
    written.append(_write("final_report.md", "\n".join(md)))

    manifest_entries = []
    for path in written:
        manifest_entries.append({
            "name": path.name,
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        })
    # test_results.txt is produced by the test run; include it if present.
    tr = OUT_DIR / "test_results.txt"
    if tr.is_file():
        manifest_entries.append({"name": tr.name, "sha256": _sha256(tr),
                                 "bytes": tr.stat().st_size})
    manifest_entries.sort(key=lambda e: e["name"])
    _write("artifact_manifest.json", {
        "generated_utc": _now(),
        "mission": "EDGELAB_FRICTION_AUTHORITY_R1",
        "artifact_count": len(manifest_entries),
        "artifacts": manifest_entries,
        "external_evidence": (merged["quote_files"] if merged else []),
        "external_evidence_policy": (
            "raw quote CSVs are hash-pinned here but stored outside git"),
    })

    print(f"wrote {len(manifest_entries) + 1} artifacts to {OUT_DIR}")
    print(f"STATUS={status}")
    print(f"FRICTION_AUTHORITY_SHA256={authority_hash}")
    for b in blockers:
        print(f"  blocker: {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
