"""SESSION_TRADE_V2 @ 2.0.0 — economic-verification campaign runner.

Research only (no Demo/Live, no order_send — frozen off in identity.py).

Stages:
  1. build   — load frozen HistData M1 zips, quality-gate, aggregate to UTC M15
  2. dev     — run the 24-cell matrix on the DEVELOPMENT partition
  3. oos     — run the frozen DEV survivors on the OOS partition
  4. report  — render the final report (Markdown + JSON)

The sealed holdout partition is structurally inaccessible (dataset.slice_partition
fails closed); this runner never touches it.

Usage:
  python scripts/run_stv2_campaign.py build
  python scripts/run_stv2_campaign.py dev
  python scripts/run_stv2_campaign.py oos
  python scripts/run_stv2_campaign.py report [--commit-sha SHA] [--pr-number N]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ag_edgelab.campaigns.session_trade_v2.campaign import CampaignResult, run_campaign  # noqa: E402
from ag_edgelab.campaigns.session_trade_v2.dataset import (  # noqa: E402
    DatasetQualityReport,
    build_symbol_dataset,
    load_histdata_m1,
)
from ag_edgelab.campaigns.session_trade_v2.report import (  # noqa: E402
    ReportInputs,
    write_report,
)
from ag_edgelab.contracts.market import MarketBar  # noqa: E402

CACHE = REPO / ".campaign_cache"
SOURCE_DATA = CACHE / "source_data"
M15_DIR = CACHE / "m15"
ARTIFACTS = REPO / "artifacts" / "session_trade_v2_economic_matrix"

SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")


# ---------------------------------------------------------------------------
# stage: build
# ---------------------------------------------------------------------------

def load_m15_cache() -> dict[str, tuple[MarketBar, ...]]:
    bars: dict[str, tuple[MarketBar, ...]] = {}
    for sym in SYMBOLS:
        path = M15_DIR / f"{sym}_M15_2017.csv"
        rows: list[MarketBar] = []
        with open(path) as fh:
            next(fh)  # header
            for line in fh:
                ts, o, h, l, c = line.strip().split(",")
                rows.append(MarketBar(
                    timestamp=datetime.fromisoformat(ts), open=float(o),
                    high=float(h), low=float(l), close=float(c)))
        bars[sym] = tuple(rows)
    return bars


def stage_build() -> None:
    M15_DIR.mkdir(parents=True, exist_ok=True)
    reports: dict[str, DatasetQualityReport] = {}
    for sym in SYMBOLS:
        zp = SOURCE_DATA / f"HISTDATA_COM_ASCII_{sym}_M1_2017.zip"
        m15, report = build_symbol_dataset(zp, sym)
        with open(M15_DIR / f"{sym}_M15_2017.csv", "w") as fh:
            fh.write("timestamp,open,high,low,close\n")
            for b in m15:
                fh.write(f"{b.timestamp.isoformat()},{b.open},{b.high},{b.low},{b.close}\n")
        reports[sym] = report
        print(f"{sym}: m1={report.m1_rows} m15={report.m15_bars} "
              f"lt13_buckets={report.m15_buckets_with_lt13_minutes} "
              f"dups={report.m1_duplicate_timestamps} "
              f"ohlc_bad={report.m1_ohlc_violations}")
    (M15_DIR / "quality_reports.json").write_text(
        json.dumps({s: asdict(r) for s, r in reports.items()}, indent=2))
    print("build complete ->", M15_DIR)


# ---------------------------------------------------------------------------
# result serialization
# ---------------------------------------------------------------------------

def result_to_payload(result: CampaignResult) -> dict:
    return {
        "role": result.role,
        "identity": result.identity,
        "started_at": result.started_at,
        "ended_at": result.ended_at,
        "partition": result.partition,
        "friction_authority": result.friction_authority,
        "cells": [c.as_row() for c in result.cells],
        "aggregates": result.aggregates,
        "session_records": [
            {"symbol": r.symbol, "session": r.session, "trading_date": r.trading_date,
             "outcome": r.outcome, "reason": r.reason, "setup": r.setup}
            for r in result.session_records
        ],
    }


# ---------------------------------------------------------------------------
# stages: dev / oos
# ---------------------------------------------------------------------------

def stage_dev() -> CampaignResult:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    bars = load_m15_cache()
    t0 = datetime.now(timezone.utc)
    result = run_campaign("DEVELOPMENT", bars,
                          run_started_at=t0, run_ended_at=datetime.now(timezone.utc))
    (ARTIFACTS / "dev_result.json").write_text(json.dumps(result_to_payload(result), indent=2))
    _print_matrix(result)
    return result


def _dev_survivor_keys() -> list[tuple[str, str, str]]:
    dev_payload = json.loads((ARTIFACTS / "dev_result.json").read_text())
    return [
        (c["branch"], c["symbol"], c["session"])
        for c in dev_payload["cells"] if c["status"] == "SURVIVES_DEV_SCREEN"
    ]


def stage_oos() -> CampaignResult:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    bars = load_m15_cache()
    gate = tuple(_dev_survivor_keys())
    print(f"frozen DEV-survivor gate cells: {gate}")
    t0 = datetime.now(timezone.utc)
    result = run_campaign("OOS", bars, run_started_at=t0,
                          run_ended_at=datetime.now(timezone.utc),
                          gate_cells=gate)
    (ARTIFACTS / "oos_result.json").write_text(json.dumps(result_to_payload(result), indent=2))
    _print_matrix(result)
    if "gate_pooled" in result.aggregates:
        g = result.aggregates["gate_pooled"]
        print(f"gate_pooled (frozen survivors only): closed={g['closed']} "
              f"net_r={g['net_r']} net_exp={g['net_expectancy_r']} "
              f"net_pf={g['net_profit_factor']} max_dd={g['max_drawdown_r']}")
    return result


def _print_matrix(result: CampaignResult) -> None:
    print(f"\n=== {result.role} 24-cell matrix ===")
    print(f"{'branch':<22}{'symbol':<8}{'session':<16}{'closed':>7}{'netR':>9}"
          f"{'netExp':>8}{'netPF':>7}{'status'}")
    for c in result.cells:
        print(f"{c.branch:<22}{c.symbol:<8}{c.session:<16}{c.closed:>7}"
              f"{c.net_r:>9.2f}"
              f"{(f'{c.net_expectancy_r:.3f}' if c.net_expectancy_r is not None else '—'):>8}"
              f"{(f'{c.net_profit_factor:.2f}' if c.net_profit_factor is not None else '—'):>7}"
              f"{c.status}")
    comb = result.aggregates["combined"]
    print(f"combined: closed={comb['closed']} net_r={comb['net_r']} "
          f"net_exp={comb['net_expectancy_r']} net_pf={comb['net_profit_factor']} "
          f"max_dd={comb['max_drawdown_r']} friction={comb['friction_drag_r']}")


# ---------------------------------------------------------------------------
# stage: report
# ---------------------------------------------------------------------------

def _git(args: list[str]) -> str:
    try:
        return subprocess.run(["git"] + args, cwd=REPO, capture_output=True,
                              text=True, check=True).stdout.strip()
    except subprocess.CalledProcessError:
        return ""


def stage_report(commit_sha: str, pr_number: str | None) -> None:
    dev_payload = json.loads((ARTIFACTS / "dev_result.json").read_text())
    oos_path = ARTIFACTS / "oos_result.json"
    oos_payload = json.loads(oos_path.read_text()) if oos_path.exists() else None
    quality = json.loads((M15_DIR / "quality_reports.json").read_text())

    from ag_edgelab.campaigns.session_trade_v2.dataset import DatasetQualityReport as R
    reports = {}
    for sym, q in quality.items():
        reports[sym] = R(
            symbol=q["symbol"], source=q["source"], m1_rows=q["m1_rows"],
            m1_duplicate_timestamps=q["m1_duplicate_timestamps"],
            m1_ohlc_violations=q["m1_ohlc_violations"], m15_bars=q["m15_bars"],
            m15_buckets_with_lt13_minutes=q["m15_buckets_with_lt13_minutes"],
            first_bar=datetime.fromisoformat(q["first_bar"]),
            last_bar=datetime.fromisoformat(q["last_bar"]),
            source_sha256=q["source_sha256"], notes=tuple(q["notes"]),
        )

    # rebuild result objects from payloads (cells/aggregates already plain data)
    from ag_edgelab.campaigns.session_trade_v2.metrics import CellMetrics
    from ag_edgelab.campaigns.session_trade_v2.campaign import CampaignResult as CR

    def _resurrect(payload: dict) -> CampaignResult:
        cells = []
        for row in payload["cells"]:
            row = dict(row)
            row["no_trade_reasons"] = dict(row["no_trade_reasons"])
            cells.append(CellMetrics(**row))
        return CR(
            role=payload["role"], identity=payload["identity"],
            started_at=payload["started_at"], ended_at=payload["ended_at"],
            cells=tuple(cells), aggregates=payload["aggregates"],
            session_records=(), friction_authority=payload["friction_authority"],
            partition=payload["partition"],
        )

    dev = _resurrect(dev_payload)
    oos = _resurrect(oos_payload) if oos_payload else None

    changed = [l for l in _git(["status", "--porcelain"]).splitlines() if l.strip()]
    tests = _git([])  # placeholder; filled below
    inputs = ReportInputs(
        dev_result=dev,
        oos_result=oos,
        dataset_reports=reports,
        repo={
            "repo": "aungmyat1/ag-edgelab",
            "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"]) or "unknown",
            "head": _git(["rev-parse", "HEAD"]) or "unknown",
            "worktree_status": "clean" if not changed else f"{len(changed)} uncommitted paths",
        },
        tests={
            "tests_run": "pytest -q (full suite incl. tests/test_stv2_*.py focused suites)",
            "test_results": (REPO / "artifacts" / "session_trade_v2_economic_matrix"
                             / "test_results.txt").read_text().strip()
            if (ARTIFACTS / "test_results.txt").exists() else "see TESTS section of report",
        },
        files_changed=tuple(sorted({
            "src/ag_edgelab/campaigns/session_trade_v2/ (campaign package)",
            "tests/test_stv2_*.py (focused suites)",
            "scripts/run_stv2_campaign.py",
            "artifacts/session_trade_v2_economic_matrix/",
        })),
        artifact_paths=(
            "artifacts/session_trade_v2_economic_matrix/dev_result.json",
            "artifacts/session_trade_v2_economic_matrix/oos_result.json",
            "artifacts/session_trade_v2_economic_matrix/supplementary.json",
            "artifacts/session_trade_v2_economic_matrix/supplementary_detail.json",
            "artifacts/session_trade_v2_economic_matrix/ledger.jsonl",
            "artifacts/session_trade_v2_economic_matrix/final_report.md",
            "artifacts/session_trade_v2_economic_matrix/final_report.json",
            "artifacts/session_trade_v2_economic_matrix/dataset_quality_reports.json",
        ),
        commit_sha=commit_sha or _git(["rev-parse", "HEAD"]),
        pr_number=pr_number,
        supplementary=_load_supplementary(),
        notes=(
            "Supplementary detail (walk-forward folds, regime slices): "
            "artifacts/session_trade_v2_economic_matrix/supplementary_detail.json",
            "Ledger freeze (EdgeLab CandidateRecord per symbol): "
            "artifacts/session_trade_v2_economic_matrix/ledger.jsonl",
        ),
    )
    md_path, json_path = write_report(inputs, ARTIFACTS)
    print("report written:", md_path, json_path)


def _load_supplementary() -> dict[str, str]:
    path = ARTIFACTS / "supplementary.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["build", "dev", "oos", "report"])
    parser.add_argument("--commit-sha", default="")
    parser.add_argument("--pr-number", default=None)
    args = parser.parse_args()
    if args.stage == "build":
        stage_build()
    elif args.stage == "dev":
        stage_dev()
    elif args.stage == "oos":
        stage_oos()
    else:
        stage_report(args.commit_sha, args.pr_number)


if __name__ == "__main__":
    main()
