from __future__ import annotations

"""Final report renderer for the SESSION_TRADE_V2 economic-verification campaign.

Produces the campaign's final report (Markdown + machine-readable JSON) with
every REQUIRED field from the campaign brief:

* FINAL_STATUS (COMPLETE | BLOCKED | PARTIAL)
* REPO / BRANCH / HEAD / SOURCE_STRATEGY_SHA / CANDIDATE_ID / DATASETS /
  DATASET_HASHES / DEV_PARTITION / OOS_PARTITION / HOLDOUT_TOUCHED=false
* the full 24-row matrix table with the exact required columns
* branch / symbol / session / combined aggregates (failing sub-cells stay visible)
* BRANCH_A/B/C_VERDICT, CELLS_TO_FREEZE_FOR_OOS / REJECTED /
  INSUFFICIENT_SAMPLE / BLOCKED
* AGGREGATE_NET_R / EXPECTANCY / PF, MAX_DRAWDOWN_R, TOTAL_FRICTION_R
* FILES_CHANGED / TESTS_RUN / TEST_RESULTS / ARTIFACT_PATHS / COMMIT_SHA /
  PR_NUMBER / NEXT_RECOMMENDED_ACTION
* FOLLOW_UP_HYPOTHESES (new candidates only — never edits to V2)

Lifecycle gating (never EDGE_VERIFIED from DEV alone):

CONTRACT_COMPLETE -> DEV_SCREEN_PASS -> FROZEN_FOR_OOS -> OOS_PASS ->
WALK_FORWARD_PASS -> REGIME_PASS -> STABILITY_PASS -> EDGE_VERIFIED

No rendering code here invents economics: every number is read from the frozen
campaign result objects.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from ag_edgelab.campaigns.session_trade_v2.campaign import CampaignResult
from ag_edgelab.campaigns.session_trade_v2.dataset import DatasetQualityReport
from ag_edgelab.campaigns.session_trade_v2.metrics import CellMetrics
from ag_edgelab.campaigns.session_trade_v2.windows import BRANCHES as METRIC_BRANCHES
from ag_edgelab.campaigns.session_trade_v2.windows import SESSIONS, SYMBOLS

LIFECYCLE_STAGES = (
    "CONTRACT_COMPLETE",
    "DEV_SCREEN_PASS",
    "FROZEN_FOR_OOS",
    "OOS_PASS",
    "WALK_FORWARD_PASS",
    "REGIME_PASS",
    "STABILITY_PASS",
    "EDGE_VERIFIED",
)

DEV_SURVIVOR_STATUSES = ("SURVIVES_DEV_SCREEN",)
REJECT_STATUSES = ("FAILS_DEV_SCREEN",)
INSUFFICIENT_STATUSES = ("INSUFFICIENT_SAMPLE",)
BLOCKED_STATUSES = ("DATA_BLOCKED", "FRICTION_UNQUALIFIED")

DEFAULT_FOLLOW_UP_HYPOTHESES = (
    "C_TREND_EXPANSION: replace the undefined 'confirmed M15 swing' runner trail "
    "with a broken-boundary retest exit (new candidate; V2 itself stays frozen)",
    "B_RANGE_REJECTION: require stronger rejection confirmation (e.g. wick-ratio or "
    "consecutive closes back inside the box) before the limit is placed",
    "A_SWEEP_REENTRY: add a minimum sweep-penetration filter (wick must exceed a "
    "fraction of R0 beyond the box extreme)",
    "HTF regime filter: gate all branches on an H1/H4 trend or range regime state",
    "Volatility filter: skip sessions whose reference range A is in the extreme "
    "tails of its rolling distribution",
)


def _fmt(x, digits=4, dash="—"):
    return dash if x is None else f"{x:.{digits}f}"


def _pct(x, dash="—"):
    return dash if x is None else f"{100.0 * x:.1f}%"


@dataclass(frozen=True)
class ReportInputs:
    dev_result: CampaignResult
    oos_result: CampaignResult | None = None
    dataset_reports: Mapping[str, DatasetQualityReport] = field(default_factory=dict)
    repo: Mapping[str, str] = field(default_factory=dict)      # repo/branch/head/worktree_status
    tests: Mapping[str, str] = field(default_factory=dict)     # tests_run/test_results
    files_changed: tuple[str, ...] = ()
    artifact_paths: tuple[str, ...] = ()
    commit_sha: str = ""
    pr_number: str | int | None = None
    follow_up_hypotheses: tuple[str, ...] = DEFAULT_FOLLOW_UP_HYPOTHESES
    supplementary: Mapping[str, str] = field(default_factory=dict)  # walk_forward/regime notes
    blocked_reason: str | None = None
    notes: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------

def cells_of(result: CampaignResult, branch: str) -> tuple[CellMetrics, ...]:
    return tuple(c for c in result.cells if c.branch == branch)


def split_cells(result: CampaignResult) -> dict[str, list[CellMetrics]]:
    out = {"survivors": [], "rejected": [], "insufficient": [], "blocked": [],
           "proxy": []}
    for c in result.cells:
        if c.status in DEV_SURVIVOR_STATUSES:
            out["survivors"].append(c)
        elif c.status in REJECT_STATUSES:
            out["rejected"].append(c)
        elif c.status in INSUFFICIENT_STATUSES:
            out["insufficient"].append(c)
        else:
            out["blocked"].append(c)
        if not c.authoritative:
            out["proxy"].append(c)
    return out


def branch_verdict(dev: CampaignResult, branch: str,
                   oos: CampaignResult | None) -> str:
    """Verdict for one branch: promotion vs research-only vs rejection vs blocked."""
    cells = cells_of(dev, branch)
    if not cells:
        return "BLOCKED"
    if all(c.status in BLOCKED_STATUSES for c in cells):
        return "BLOCKED"
    if not any(c.authoritative for c in cells):
        return ("RESEARCH_ONLY (diagnostic proxy only — C runner management is "
                "not deterministically defined in the frozen source)")
    survivors = [c for c in cells if c.status in DEV_SURVIVOR_STATUSES]
    if not survivors:
        if all(c.status in INSUFFICIENT_STATUSES for c in cells if c.authoritative):
            return "RESEARCH_ONLY (insufficient sample across all cells)"
        return "REJECT (fails DEV screen)"
    if oos is None:
        return "PROMOTION_CANDIDATE (pending OOS)"
    # OOS verdict pools ONLY the frozen DEV-survivor cells of this branch
    pooled = oos.aggregates.get("gate_by_branch", {}).get(branch) \
        or oos.aggregates["by_branch"][branch]
    if pooled["closed"] == 0:
        return "RESEARCH_ONLY (no closed OOS trades among frozen survivors)"
    if (pooled["net_expectancy_r"] or 0.0) > 0.0 and (pooled["net_profit_factor"] or 0.0) > 1.0:
        return "PROMOTION_CANDIDATE (passes OOS; remaining gates pending)"
    return "REJECT (fails OOS)"


def lifecycle(dev: CampaignResult, oos: CampaignResult | None,
              supplementary: Mapping[str, str]) -> dict[str, object]:
    """Highest lifecycle stage reached plus per-gate pass/fail. Never
    EDGE_VERIFIED from DEV alone (structurally impossible: OOS/walk-forward/
    regime/stability gates must each pass first)."""
    gates = {"CONTRACT_COMPLETE": True}  # identity verified inside run_campaign
    survivors = split_cells(dev)["survivors"]
    gates["DEV_SCREEN_PASS"] = bool(survivors)
    gates["FROZEN_FOR_OOS"] = gates["DEV_SCREEN_PASS"]  # survivors frozen for OOS
    oos_pass = False
    if oos is not None and survivors:
        # gate on the frozen survivors only (falls back to combined)
        pooled = oos.aggregates.get("gate_pooled") or oos.aggregates["combined"]
        oos_pass = (
            pooled["closed"] > 0
            and (pooled["net_expectancy_r"] or 0.0) > 0.0
            and (pooled["net_profit_factor"] or 0.0) > 1.0
        )
    gates["OOS_PASS"] = oos_pass
    gates["WALK_FORWARD_PASS"] = oos_pass and supplementary.get("walk_forward") == "PASS"
    gates["REGIME_PASS"] = oos_pass and supplementary.get("regime") == "PASS"
    # Parameter stability is structurally N/A: the candidate is a single frozen
    # parameter point (no tunable surface was exercised). Reported explicitly.
    gates["STABILITY_PASS"] = None  # N/A — single frozen parameter point
    gates["EDGE_VERIFIED"] = bool(
        gates["WALK_FORWARD_PASS"] and gates["REGIME_PASS"]
    )
    reached = "CONTRACT_COMPLETE"
    for stage in LIFECYCLE_STAGES:
        if gates.get(stage):
            reached = stage
    return {"reached": reached, "gates": gates}


def final_status(inputs: ReportInputs) -> tuple[str, str]:
    """(FINAL_STATUS, NEXT_RECOMMENDED_ACTION)."""
    if inputs.blocked_reason:
        return "BLOCKED", f"Resolve blocker: {inputs.blocked_reason}"
    survivors = split_cells(inputs.dev_result)["survivors"]
    if not survivors:
        return ("COMPLETE",
                "Negative result: no cell survives the DEV screen. Close this "
                "candidate; pursue FOLLOW_UP_HYPOTHESES as NEW candidates only.")
    if inputs.oos_result is None:
        return ("PARTIAL",
                "Freeze DEV survivors and run the OOS partition "
                "(2017-09-01 -> 2017-12-01) before any promotion decision.")
    lc = lifecycle(inputs.dev_result, inputs.oos_result, inputs.supplementary)
    if not lc["gates"]["OOS_PASS"]:
        return ("COMPLETE",
                "Survivors failed the OOS gate: reject those cells; no promotion. "
                "Pursue FOLLOW_UP_HYPOTHESES as new candidates.")
    if not lc["gates"]["WALK_FORWARD_PASS"] or not lc["gates"]["REGIME_PASS"]:
        return ("PARTIAL",
                "OOS passed; complete the supplementary walk-forward and regime "
                "stages before promotion decisions.")
    return ("COMPLETE",
            "All completed gates passed. Promotion decision may proceed to "
            "EdgeLab's standard release pipeline (still research-only: no "
            "Demo/Live authorization is granted by this campaign).")


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------

def matrix_rows(result: CampaignResult) -> list[list[str]]:
    """The required 24-row matrix with the exact required columns."""
    rows = []
    for branch in METRIC_BRANCHES:
        for symbol in SYMBOLS:
            for session in SESSIONS:
                c = result.cell_by_key[(branch, symbol, session)]
                rows.append([
                    branch, symbol, session, str(c.closed),
                    _fmt(c.net_r), _fmt(c.net_expectancy_r),
                    _fmt(c.net_profit_factor), _pct(c.win_rate),
                    _fmt(c.max_drawdown_r), _fmt(c.friction_drag_r),
                    c.status,
                ])
    return rows


def detail_rows(result: CampaignResult) -> list[list[str]]:
    """Full per-cell statistics (every required per-cell metric)."""
    rows = []
    for branch in METRIC_BRANCHES:
        for symbol in SYMBOLS:
            for session in SESSIONS:
                c = result.cell_by_key[(branch, symbol, session)]
                rows.append([
                    branch, symbol, session,
                    str(c.sessions_evaluated), str(c.data_invalid_sessions),
                    str(c.signals), str(c.filled), str(c.unfilled), str(c.expired),
                    str(c.open_at_end), str(c.closed), str(c.wins), str(c.losses),
                    str(c.breakeven_outcomes),
                    _fmt(c.gross_r), _fmt(c.net_r),
                    _fmt(c.gross_expectancy_r), _fmt(c.net_expectancy_r),
                    _fmt(c.gross_profit_factor), _fmt(c.net_profit_factor),
                    _pct(c.win_rate), _fmt(c.average_win_r), _fmt(c.average_loss_r),
                    _fmt(c.max_drawdown_r), str(c.max_losing_streak),
                    _pct(c.tp1_4r_hit_rate), _pct(c.runner_5r_hit_rate),
                    _pct(c.runner_breakeven_rate),
                    _fmt(c.average_holding_hours, 2), _fmt(c.trades_per_week, 3),
                    _fmt(c.cost_per_trade_r), _fmt(c.friction_drag_r),
                    str(c.same_bar_ambiguity_count),
                    c.proxy_label or ("AUTHORITATIVE" if c.authoritative else "PROXY"),
                    ";".join(f"{k}={v}" for k, v in sorted(c.no_trade_reasons.items()))
                    or "—",
                ])
    return rows


_MATRIX_HEADER = ("| Branch | Symbol | Session | N | Net R | Net Exp | Net PF "
                  "| Win % | Max DD R | Friction R | Status |")
_MATRIX_RULE = "|---|---|---|---|---|---|---|---|---|---|---|"

_DETAIL_HEADER = (
    "| Branch | Symbol | Session | Sess | DataInv | Sig | Fill | Unfill | Exp "
    "| Open | Closed | W | L | BE | GrossR | NetR | GrossExp | NetExp | GrossPF "
    "| NetPF | Win% | AvgW | AvgL | MaxDD | LossStreak | 4R% | 5R% | BE% "
    "| HoldH | Freq | CostR | FrictR | Ambig | Authority | NoTradeReasons |"
)
_DETAIL_RULE = ("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---"
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---"
                "|---|---|---|---|---|---|")


def _table(header: str, rule: str, rows: list[list[str]]) -> str:
    return "\n".join([header, rule] + ["| " + " | ".join(r) + " |" for r in rows])


def _aggregate_table(aggregates: dict) -> str:
    rows = []
    for name in ("by_branch", "by_symbol", "by_session"):
        for label, a in aggregates[name].items():
            rows.append([name, label, str(a["closed"]), _fmt(a["net_r"]),
                         _fmt(a["net_expectancy_r"]), _fmt(a["net_profit_factor"]),
                         _pct(a["win_rate"]), _fmt(a["max_drawdown_r"]),
                         _fmt(a["friction_drag_r"]), str(a["same_bar_ambiguity_count"])])
    a = aggregates["combined"]
    rows.append(["combined", "ALL", str(a["closed"]), _fmt(a["net_r"]),
                 _fmt(a["net_expectancy_r"]), _fmt(a["net_profit_factor"]),
                 _pct(a["win_rate"]), _fmt(a["max_drawdown_r"]),
                 _fmt(a["friction_drag_r"]), str(a["same_bar_ambiguity_count"])])
    if "gate_pooled" in aggregates:
        g = aggregates["gate_pooled"]
        rows.append(["gate", "FROZEN_DEV_SURVIVORS", str(g["closed"]), _fmt(g["net_r"]),
                     _fmt(g["net_expectancy_r"]), _fmt(g["net_profit_factor"]),
                     _pct(g["win_rate"]), _fmt(g["max_drawdown_r"]),
                     _fmt(g["friction_drag_r"]), str(g["same_bar_ambiguity_count"])])
    return _table(
        "| Group | Label | N | Net R | Net Exp | Net PF | Win % | Max DD R "
        "| Friction R | Ambig |",
        "|---|---|---|---|---|---|---|---|---|---|",
        rows,
    )


# ---------------------------------------------------------------------------
# report assembly
# ---------------------------------------------------------------------------

def cell_names(cells: list[CellMetrics]) -> list[str]:
    return [f"{c.branch}/{c.symbol}/{c.session}" for c in cells]


def render_markdown(inputs: ReportInputs) -> str:
    dev, oos = inputs.dev_result, inputs.oos_result
    ident = dev.identity
    status, next_action = final_status(inputs)
    lc = lifecycle(dev, oos, inputs.supplementary)
    split = split_cells(dev)
    repo = inputs.repo
    tests = inputs.tests

    L: list[str] = []
    L.append("# SESSION_TRADE_V2 @ 2.0.0 — Economic Verification Final Report")
    L.append("")
    L.append(f"**FINAL_STATUS: {status}**")
    L.append("")
    L.append("## Identity & Environment")
    L.append("")
    L.append(f"- REPO: {repo.get('repo', '')}")
    L.append(f"- BRANCH: {repo.get('branch', '')}")
    L.append(f"- HEAD: {repo.get('head', '')}")
    L.append(f"- WORKTREE STATUS: {repo.get('worktree_status', '')}")
    L.append(f"- SOURCE_REPO: {ident['source_repo']} (PR #{ident['source_pr']}, "
             f"branch `{ident['source_branch']}`)")
    L.append(f"- SOURCE_STRATEGY_SHA (source_commit): `{ident['source_commit']}`")
    L.append("- SOURCE_ARTIFACT_SHA256 (frozen byte-exact copies):")
    for name, sha in ident["artifact_sha256"].items():
        L.append(f"    - `{name}`: `{sha}`")
    L.append(f"- CANDIDATE_ID: `{ident['candidate_id']}`")
    L.append(f"- EXECUTION_AUTHORITY: {ident['execution_authority']} "
             "(research-only: no Demo/Live, no order_send, no broker mutation)")
    L.append(f"- DEV_PARTITION: {dev.partition['start']} -> {dev.partition['end']} "
             f"({dev.role})")
    L.append(f"- OOS_PARTITION: "
             f"{(oos.partition['start'] + ' -> ' + oos.partition['end'] + ' (' + oos.role + ')') if oos else 'NOT RUN'}")
    L.append("- SEALED_HOLDOUT: [2017-12-01, 2018-01-01) — **HOLDOUT_TOUCHED: false** "
             "(structurally inaccessible: `slice_partition` fails closed)")
    L.append("")
    L.append("## Datasets")
    L.append("")
    if inputs.dataset_reports:
        L.append("| Symbol | Source | M1 rows | M15 bars | First | Last | SHA256 |")
        L.append("|---|---|---|---|---|---|---|")
        for sym, r in sorted(inputs.dataset_reports.items()):
            L.append(f"| {sym} | {r.source} | {r.m1_rows} | {r.m15_bars} "
                     f"| {r.first_bar} | {r.last_bar} | `{r.source_sha256}` |")
        L.append("")
        L.append("DATASET_HASHES:")
        for sym, r in sorted(inputs.dataset_reports.items()):
            L.append(f"- {sym}: `{r.source_sha256}`")
    else:
        L.append("DATASETS: none supplied")
        L.append("DATASET_HASHES: none")
    L.append("")
    L.append("## Lifecycle")
    L.append("")
    L.append(f"- Stage reached: **{lc['reached']}**")
    for stage in LIFECYCLE_STAGES:
        v = lc["gates"].get(stage)
        v_str = "PASS" if v else ("N/A (single frozen parameter point)" if v is None else "FAIL")
        L.append(f"- {stage}: {v_str}")
    L.append("- EDGE_VERIFIED is never reachable from DEV alone (see gate list).")
    L.append("")
    L.append("## DEV Matrix (24 cells)")
    L.append("")
    L.append("N = closed trades; net statistics are over closed trades only "
             "(OPEN_AT_END censored). C cells are DIAGNOSTIC_ONLY "
             "(C_FIXED_EXIT_PROXY) — never authoritative.")
    L.append("")
    L.append(_table(_MATRIX_HEADER, _MATRIX_RULE, matrix_rows(dev)))
    L.append("")
    L.append("### DEV per-cell detail")
    L.append("")
    L.append(_table(_DETAIL_HEADER, _DETAIL_RULE, detail_rows(dev)))
    L.append("")
    if oos is not None:
        L.append("## OOS Matrix (frozen DEV survivors only)")
        L.append("")
        L.append(_table(_MATRIX_HEADER, _MATRIX_RULE, matrix_rows(oos)))
        L.append("")
        L.append("### OOS per-cell detail")
        L.append("")
        L.append(_table(_DETAIL_HEADER, _DETAIL_RULE, detail_rows(oos)))
        L.append("")
    L.append("## Aggregates (never hiding failing sub-cells)")
    L.append("")
    L.append("### DEV")
    L.append("")
    L.append(_aggregate_table(dev.aggregates))
    L.append("")
    if oos is not None:
        L.append("### OOS")
        L.append("")
        L.append(_aggregate_table(oos.aggregates))
        L.append("")
        if "gate_pooled" in oos.aggregates:
            g = oos.aggregates["gate_pooled"]
            L.append("### OOS promotion gate (frozen DEV survivors only)")
            L.append("")
            L.append(f"- closed trades: {g['closed']}")
            L.append(f"- net R: {_fmt(g['net_r'])}")
            L.append(f"- net expectancy: {_fmt(g['net_expectancy_r'])} "
                     f"(bootstrap 90% CI [{_fmt(g['net_expectancy_ci_low'])}, "
                     f"{_fmt(g['net_expectancy_ci_high'])}])")
            L.append(f"- net profit factor: {_fmt(g['net_profit_factor'])}")
            L.append(f"- max drawdown: {_fmt(g['max_drawdown_r'])} R")
            L.append(f"- GATE RESULT: {'PASS' if (g['net_expectancy_r'] or 0) > 0 and (g['net_profit_factor'] or 0) > 1 else 'FAIL'}")
            L.append("")
    combined = dev.aggregates["combined"]
    L.append("## Headline economics (DEV, authoritative cells pooled incl. "
             "failing ones)")
    L.append("")
    L.append(f"- AGGREGATE_NET_R: {_fmt(combined['net_r'])}")
    L.append(f"- AGGREGATE_EXPECTANCY (net R/trade): {_fmt(combined['net_expectancy_r'])}"
             f"  (bootstrap 90% CI [{_fmt(combined['net_expectancy_ci_low'])}, "
             f"{_fmt(combined['net_expectancy_ci_high'])}])")
    L.append(f"- AGGREGATE_PF (net): {_fmt(combined['net_profit_factor'])}")
    L.append(f"- MAX_DRAWDOWN_R: {_fmt(combined['max_drawdown_r'])}")
    L.append(f"- TOTAL_FRICTION_R: {_fmt(combined['friction_drag_r'])}")
    L.append("")
    L.append("## Cell classifications")
    L.append("")
    L.append(f"- CELLS_TO_FREEZE_FOR_OOS ({len(split['survivors'])}): "
             f"{cell_names(split['survivors']) or '—'}")
    L.append(f"- REJECTED ({len(split['rejected'])}): "
             f"{cell_names(split['rejected']) or '—'}")
    L.append(f"- INSUFFICIENT_SAMPLE ({len(split['insufficient'])}): "
             f"{cell_names(split['insufficient']) or '—'}")
    L.append(f"- BLOCKED ({len(split['blocked'])}): "
             f"{cell_names(split['blocked']) or '—'}")
    L.append(f"- DIAGNOSTIC_ONLY (proxy, never authoritative) "
             f"({len(split['proxy'])}): {cell_names(split['proxy']) or '—'}")
    L.append("")
    L.append("## Branch verdicts")
    L.append("")
    for b in METRIC_BRANCHES:
        L.append(f"- BRANCH_{b.split('_')[0]}_VERDICT ({b}): "
                 f"{branch_verdict(dev, b, oos)}")
    L.append("")
    if inputs.supplementary:
        L.append("## Supplementary stages")
        L.append("")
        for k, v in inputs.supplementary.items():
            L.append(f"- {k}: {v}")
        L.append("")
    L.append("## Provenance")
    L.append("")
    L.append(f"- FILES_CHANGED: {list(inputs.files_changed) or '—'}")
    L.append(f"- TESTS_RUN: {tests.get('tests_run', '')}")
    L.append(f"- TEST_RESULTS: {tests.get('test_results', '')}")
    L.append(f"- ARTIFACT_PATHS: {list(inputs.artifact_paths) or '—'}")
    L.append(f"- COMMIT_SHA: `{inputs.commit_sha or ''}`")
    L.append(f"- PR_NUMBER: {inputs.pr_number if inputs.pr_number is not None else '—'}")
    L.append("")
    L.append("## Follow-up hypotheses (NEW candidates only — V2 stays frozen)")
    L.append("")
    for i, h in enumerate(inputs.follow_up_hypotheses, 1):
        L.append(f"{i}. {h}")
    L.append("")
    L.append("## Known limitations / blockers")
    L.append("")
    L.append("- C_TREND_EXPANSION runner management ('confirmed M15 swings' trail, "
             "5R cap) is NOT deterministically defined in the frozen source: C "
             "cells run C_FIXED_EXIT_PROXY (diagnostic-only, never authoritative).")
    L.append("- USDJPY friction has no VT Markets-published spread; cross-broker "
             "evidence band used with the 1.25x/1.5x stress grid.")
    L.append("- Parameter stability is N/A: single frozen parameter point.")
    for n in inputs.notes:
        L.append(f"- {n}")
    L.append("")
    L.append(f"NEXT_RECOMMENDED_ACTION: {next_action}")
    L.append("")
    return "\n".join(L)


def build_report_payload(inputs: ReportInputs) -> dict:
    """Machine-readable mirror of the Markdown report."""
    dev, oos = inputs.dev_result, inputs.oos_result
    status, next_action = final_status(inputs)
    lc = lifecycle(dev, oos, inputs.supplementary)
    split = split_cells(dev)
    combined = dev.aggregates["combined"]
    return {
        "FINAL_STATUS": status,
        "REPO": inputs.repo.get("repo", ""),
        "BRANCH": inputs.repo.get("branch", ""),
        "HEAD": inputs.repo.get("head", ""),
        "SOURCE_STRATEGY_SHA": dev.identity["source_commit"],
        "SOURCE_ARTIFACT_SHA256": dev.identity["artifact_sha256"],
        "CANDIDATE_ID": dev.identity["candidate_id"],
        "EXECUTION_AUTHORITY": dev.identity["execution_authority"],
        "DATASETS": {
            sym: {"source": r.source, "m1_rows": r.m1_rows, "m15_bars": r.m15_bars,
                  "first_bar": r.first_bar.isoformat() if r.first_bar else None,
                  "last_bar": r.last_bar.isoformat() if r.last_bar else None,
                  "notes": list(r.notes)}
            for sym, r in inputs.dataset_reports.items()
        },
        "DATASET_HASHES": {sym: r.source_sha256
                           for sym, r in inputs.dataset_reports.items()},
        "DEV_PARTITION": {"start": dev.partition["start"], "end": dev.partition["end"]},
        "OOS_PARTITION": ({"start": oos.partition["start"], "end": oos.partition["end"]}
                          if oos else None),
        "HOLDOUT_TOUCHED": False,
        "LIFECYCLE": lc,
        "DEV_MATRIX": [c.as_row() for c in dev.cells],
        "OOS_MATRIX": [c.as_row() for c in oos.cells] if oos else None,
        "DEV_AGGREGATES": dev.aggregates,
        "OOS_AGGREGATES": oos.aggregates if oos else None,
        "OOS_GATE_POOLED": oos.aggregates.get("gate_pooled") if oos else None,
        "AGGREGATE_NET_R": combined["net_r"],
        "AGGREGATE_EXPECTANCY": combined["net_expectancy_r"],
        "AGGREGATE_PF": combined["net_profit_factor"],
        "MAX_DRAWDOWN_R": combined["max_drawdown_r"],
        "TOTAL_FRICTION_R": combined["friction_drag_r"],
        "BRANCH_VERDICTS": {b: branch_verdict(dev, b, oos) for b in METRIC_BRANCHES},
        **{f"BRANCH_{b.split('_')[0]}_VERDICT": branch_verdict(dev, b, oos)
           for b in METRIC_BRANCHES},
        "CELLS_TO_FREEZE_FOR_OOS": cell_names(split["survivors"]),
        "REJECTED": cell_names(split["rejected"]),
        "INSUFFICIENT_SAMPLE": cell_names(split["insufficient"]),
        "BLOCKED": cell_names(split["blocked"]),
        "DIAGNOSTIC_ONLY": cell_names(split["proxy"]),
        "SUPPLEMENTARY": dict(inputs.supplementary),
        "FILES_CHANGED": list(inputs.files_changed),
        "TESTS_RUN": inputs.tests.get("tests_run", ""),
        "TEST_RESULTS": inputs.tests.get("test_results", ""),
        "ARTIFACT_PATHS": list(inputs.artifact_paths),
        "COMMIT_SHA": inputs.commit_sha,
        "PR_NUMBER": inputs.pr_number,
        "FOLLOW_UP_HYPOTHESES": list(inputs.follow_up_hypotheses),
        "NEXT_RECOMMENDED_ACTION": next_action,
    }


def write_report(inputs: ReportInputs, out_dir: Path,
                 stem: str = "final_report") -> tuple[Path, Path]:
    """Write `<stem>.md` and `<stem>.json`; returns their paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{stem}.md"
    json_path = out_dir / f"{stem}.json"
    md_path.write_text(render_markdown(inputs), encoding="utf-8")
    payload = build_report_payload(inputs)

    def _default(o):
        if isinstance(o, CellMetrics):
            return o.as_row()
        return str(o)

    json_path.write_text(json.dumps(payload, indent=2, default=_default),
                         encoding="utf-8")
    return md_path, json_path
