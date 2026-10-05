#!/usr/bin/env python3
"""Ingest VT Markets capture bundles into FRICTION_AUTHORITY_R1 and report.

Run with no bundles (the state on any machine without the Windows MT5
terminal) and it reports exactly that: every component MISSING, nothing
inferred, nothing defaulted to zero. Run it against a directory of
sealed bundles produced by ``capture_vtmarkets_friction.py`` and it
verifies their hashes, pools the quotes and reports real distributions.

    python scripts/build_vt_markets_friction_evidence.py \
        --bundle-root capture_bundles
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.data.fingerprint import sha256_file  # noqa: E402
from ag_edgelab.friction.authority import daily  # noqa: E402
from ag_edgelab.friction.authority.capture_schema import (  # noqa: E402
    BundleInvalid, verify_bundle,
)
from ag_edgelab.friction.authority.quotes import session_for  # noqa: E402
from ag_edgelab.friction.authority.resolution import CANONICAL_FX  # noqa: E402
from ag_edgelab.universal.trigger_v0_4 import session_label  # noqa: E402

OUT = ROOT / "artifacts" / "vt_markets_friction_evidence_r1"
PERCENTILES = (25, 50, 75, 90, 95, 99)


def write(name: str, payload) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    if isinstance(payload, str):
        path.write_text(payload)
    else:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


# ---------------------------------------------------------------------------
# session authority conflict (§4)
# ---------------------------------------------------------------------------

def session_authority_report() -> dict:
    """Two session definitions exist in this repository and they disagree.

    Surfaced rather than silently resolved, per the standing rule that
    repository evidence beats a mission prompt and conflicts get
    reported instead of papered over.
    """
    probes = []
    for hour in range(24):
        ts = datetime(2017, 1, 3, hour, 30, tzinfo=timezone.utc)
        governed = session_label(ts)
        diagnostic = str(session_for(ts))
        probes.append({"utc_hour": hour, "governed_v03": governed,
                       "friction_diagnostic": diagnostic,
                       "agree": governed == diagnostic
                       or (governed == "LONDON_NEWYORK_OVERLAP"
                           and diagnostic == "OVERLAP")
                       or (governed == "OFF_SESSION" and diagnostic == "OTHER")})
    disagreements = [p for p in probes if not p["agree"]]
    return {
        "conflict_detected": bool(disagreements),
        "governed_authority": {
            "id": "SESSION_WINDOWS_UTC_V0_3_STRATIFICATION",
            "implementation": "ag_edgelab.universal.trigger_v0_4.session_label",
            "windows_utc": {"ASIAN": "00-08", "LONDON": "08-13",
                            "LONDON_NEWYORK_OVERLAP": "13-16",
                            "NEW_YORK": "16-21", "OFF_SESSION": "21-24"},
            "status": "GOVERNED — hashed into TARGET_POLICY_C3_V1's canonical "
                      "contract as session_authority_id",
        },
        "friction_diagnostic_authority": {
            "id": "EDGELAB_SPREAD_OBSERVATION_V1 session slicer",
            "implementation": "ag_edgelab.friction.authority.quotes.session_for",
            "windows_utc": {"ASIAN": "00-07", "LONDON": "07-12",
                            "OVERLAP": "12-16", "NEW_YORK": "16-21",
                            "OTHER": "21-24"},
            "status": "DIAGNOSTIC — introduced by FRICTION_AUTHORITY_R1, "
                      "self-documented as 'diagnostic only'",
        },
        "disagreeing_hours": [p["utc_hour"] for p in disagreements],
        "disagreement_count": len(disagreements),
        "examples": disagreements[:4],
        "mission_prompt_requested": ["ASIAN", "LONDON", "NEW_YORK",
                                     "LONDON_NEWYORK_OVERLAP", "OTHER"],
        "prompt_matches_neither": True,
        "resolution": (
            "Both labels are recorded on every captured quote: "
            "'session_governed_v03' from the governed V0.3 authority and "
            "'session' from R1's diagnostic slicer. No third window scheme "
            "was invented to match the mission prompt's exact list, and "
            "neither existing authority was modified."),
        "note": (
            "The prompt asked for LONDON_NEWYORK_OVERLAP (a V0.3 name) "
            "alongside OTHER (a friction-module name). That combination "
            "exists in neither authority. Inventing it would have created a "
            "third, ungoverned session definition."),
    }


# ---------------------------------------------------------------------------
# bundle ingest
# ---------------------------------------------------------------------------

def load_bundles(bundle_root: Path) -> dict:
    """Verify and pool every sealed bundle under ``bundle_root``."""
    if not bundle_root.is_dir():
        return {"bundle_root": str(bundle_root), "present": False,
                "bundle_count": 0, "verified": 0, "quotes": {}, "errors": [],
                "registry": None}

    registry = daily.load_registry(bundle_root)
    verification = daily.verify_registry(bundle_root)
    quotes: dict[str, list[dict]] = defaultdict(list)
    errors: list[str] = []
    verified = 0

    for entry in sorted(bundle_root.iterdir()):
        if not entry.is_dir() or not daily.parse_bundle_name(entry.name):
            continue
        try:
            verify_bundle(entry)
            verified += 1
        except BundleInvalid as exc:
            errors.append(f"{entry.name}: {exc}")
            continue
        qdir = entry / "quotes"
        if not qdir.is_dir():
            continue
        for csv_path in sorted(qdir.glob("*.csv")):
            with csv_path.open() as fh:
                for row in csv.DictReader(fh):
                    quotes[csv_path.stem].append(row)

    return {
        "bundle_root": str(bundle_root), "present": True,
        "bundle_count": registry.get("bundle_count", 0),
        "verified": verified, "errors": errors,
        "registry_all_verified": verification["all_verified"],
        "registry_problems": verification["problems"],
        "quotes": dict(quotes),
    }


def distributions(quotes: dict[str, list[dict]]) -> dict:
    """Per symbol and per session spread distributions (§6)."""
    report: dict = {}
    for symbol, rows in sorted(quotes.items()):
        buckets: dict[str, list[float]] = defaultdict(list)
        zero = invalid = 0
        for row in rows:
            try:
                bid, ask = float(row["bid"]), float(row["ask"])
            except (TypeError, ValueError):
                invalid += 1
                continue
            if bid <= 0 or ask <= 0 or ask < bid:
                invalid += 1
                continue
            spread = ask - bid
            if spread == 0:
                zero += 1
            session = row.get("session_governed_v03") or row.get("session") or "UNKNOWN"
            buckets[session].append(spread)
            buckets["ALL"].append(spread)

        per_session = {}
        for session, values in sorted(buckets.items()):
            if not values:
                continue
            values.sort()
            n = len(values)
            per_session[session] = {
                "N": n, "MIN": values[0], "MAX": values[-1],
                **{f"P{p}": _percentile(values, p) for p in PERCENTILES},
            }
        report[symbol] = {
            "N": len(rows),
            "ZERO_SPREAD_N": zero,
            "INVALID_QUOTE_N": invalid,
            "OUTLIER_N": _outliers(buckets.get("ALL", [])),
            "by_session": per_session,
            "session_authority": "SESSION_WINDOWS_UTC_V0_3_STRATIFICATION",
        }
    return report


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return float("nan")
    k = (len(sorted_values) - 1) * pct / 100.0
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def _outliers(values: list[float]) -> int:
    """Count beyond 1.5 IQR above P75 — flagged, never removed."""
    if len(values) < 8:
        return 0
    ordered = sorted(values)
    q1, q3 = _percentile(ordered, 25), _percentile(ordered, 75)
    fence = q3 + 1.5 * (q3 - q1)
    return sum(1 for v in ordered if v > fence)


# ---------------------------------------------------------------------------
# authority verdicts
# ---------------------------------------------------------------------------

def authority_status(loaded: dict, dist: dict) -> dict:
    captured = bool(dist) and any(d["N"] > 0 for d in dist.values())
    spread = "CAPTURED" if captured else "MISSING"
    return {
        "SPREAD_AUTHORITY": spread,
        "COMMISSION_AUTHORITY": "MISSING",
        "SLIPPAGE_AUTHORITY": "MISSING",
        "SWAP_AUTHORITY": "MISSING",
        "FRICTION_AUTHORITY_COMPLETE": False,
        "rationale": {
            "SPREAD": ("quote evidence present" if captured else
                       "no verified capture bundle; no quote evidence exists "
                       "on this machine"),
            "COMMISSION": ("Requires the account specification, an MT5 deal "
                           "history with a commission field, or a broker "
                           "statement held locally. None is reachable from "
                           "this environment. No industry default is "
                           "substituted."),
            "SLIPPAGE": ("Requires executed fill evidence: requested price "
                         "versus filled price on real deals. Quote history "
                         "cannot establish it at any sampling rate, and this "
                         "mission forbids placing a trade to manufacture "
                         "one."),
            "SWAP": ("swap_long / swap_short / swap_mode come from "
                     "symbol_info, which requires the terminal."),
        },
        "missing_is_not_zero": True,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-root", type=Path, default=ROOT / "capture_bundles")
    args = ap.parse_args(argv)

    env = {
        "platform": sys.platform,
        "metatrader5_importable": _mt5_importable(),
        "terminal_reachable": False,
        "capture_possible_here": False,
        "reason": ("MetaTrader5 is a Windows-only package with no Linux "
                   "wheel, and no VT Markets terminal is present in this "
                   "environment. Venue evidence cannot be captured here; it "
                   "must be captured on the owner's Windows machine."),
    }

    loaded = load_bundles(args.bundle_root)
    dist = distributions(loaded["quotes"])
    status = authority_status(loaded, dist)
    conflict = session_authority_report()

    write("capture_environment.json", env)
    write("session_authority_conflict.json", conflict)
    write("symbol_resolution.json", {
        "status": "NOT_CAPTURED",
        "canonical_requested": list(CANONICAL_FX),
        "crypto_requested": "owner's two crypto symbols, if present",
        "mapping": {},
        "reason": env["reason"],
        "resolver": "ag_edgelab.friction.authority.resolution.resolve_all",
        "suffix_policy": ("Broker suffixes are never assumed. The resolver "
                          "matches only against names the terminal "
                          "publishes, records every candidate, and reports "
                          "RESOLVED_AMBIGUOUS when more than one matches."),
    })
    write("capture_registry_status.json", {
        "bundle_root": str(args.bundle_root),
        "present": loaded["present"],
        "bundle_count": loaded["bundle_count"],
        "verified": loaded["verified"],
        "errors": loaded["errors"],
        "append_only": True,
    })
    write("spread_distribution.json", {
        "symbols": dist,
        "status": status["SPREAD_AUTHORITY"],
        "percentiles_reported": ["MIN", *[f"P{p}" for p in PERCENTILES], "MAX"],
        "outlier_policy": "flagged by 1.5 IQR above P75, never removed",
        "no_assumption_chosen": (
            "No strategy spread assumption is selected here. Choosing one "
            "is a separate, later decision that must be preregistered."),
    })
    write("friction_authority_status.json", status)

    report = {
        "mission": "VT_MARKETS_FRICTION_EVIDENCE_R1",
        "VENUE": "VT Markets (unverified — terminal not reachable)",
        "SERVER": None,
        "ACCOUNT_CURRENCY": None,
        "ACCOUNT_CLASS": None,
        "SYMBOL_MAPPING": {},
        **{f"{s}_SPREAD_N": dist.get(s, {}).get("N", 0) for s in CANONICAL_FX},
        **status,
        "ORDER_CALLS_EXECUTED": "NO",
        "BROKER_MUTATION": "NO",
        "environment": env,
        "session_authority_conflict": conflict["conflict_detected"],
        "PRIMARY_BLOCKER": "NO_TERMINAL_ACCESS_FROM_THIS_ENVIRONMENT",
        "deliverables_ready": [
            "scripts/capture_vtmarkets_friction.py (v2, read-only, "
            "scheduler-safe)",
            "ag_edgelab.friction.authority.resolution (symbol resolution)",
            "ag_edgelab.friction.authority.daily (immutable daily bundles)",
            "scripts/build_vt_markets_friction_evidence.py (this ingest)",
        ],
    }
    write("final_report.json", report)
    write("final_report.md", render_md(report, conflict))

    manifest = {p.name: {"sha256": sha256_file(p), "bytes": p.stat().st_size}
                for p in sorted(OUT.iterdir())
                if p.is_file() and p.name != "artifact_manifest.json"}
    write("artifact_manifest.json",
          {"artifact_count": len(manifest), "artifacts": manifest})

    print(json.dumps({k: report[k] for k in (
        "SPREAD_AUTHORITY", "COMMISSION_AUTHORITY", "SLIPPAGE_AUTHORITY",
        "SWAP_AUTHORITY", "FRICTION_AUTHORITY_COMPLETE", "PRIMARY_BLOCKER")},
        indent=2))
    return 0


def _mt5_importable() -> bool:
    try:
        import MetaTrader5  # noqa: F401
        return True
    except ImportError:
        return False


def render_md(r: dict, conflict: dict) -> str:
    return f"""# VT_MARKETS_FRICTION_EVIDENCE_R1 — Status

## BLOCKED: no terminal in this environment

{r['environment']['reason']}

`MetaTrader5` importable: **{r['environment']['metatrader5_importable']}** ·
platform: `{r['environment']['platform']}`

No spread, commission, slippage or swap number is reported, because none
was measured. Nothing is defaulted to zero.

| component | status |
|---|---|
| SPREAD_AUTHORITY | {r['SPREAD_AUTHORITY']} |
| COMMISSION_AUTHORITY | {r['COMMISSION_AUTHORITY']} |
| SLIPPAGE_AUTHORITY | {r['SLIPPAGE_AUTHORITY']} |
| SWAP_AUTHORITY | {r['SWAP_AUTHORITY']} |
| **FRICTION_AUTHORITY_COMPLETE** | **{r['FRICTION_AUTHORITY_COMPLETE']}** |

## Session authority conflict

Two session definitions exist in this repository and they disagree on
**{conflict['disagreement_count']} of 24 UTC hours**.

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

{chr(10).join('- `' + d + '`' for d in r['deliverables_ready'])}

`ORDER_CALLS_EXECUTED={r['ORDER_CALLS_EXECUTED']}` ·
`BROKER_MUTATION={r['BROKER_MUTATION']}`
"""


if __name__ == "__main__":
    raise SystemExit(main())
