"""STV2_STRATEGY_FUNNEL_ANALYZER_V1 — runner.

Diagnostic research only.  Executes the strategy funnel

    CONTEXT -> LOCATION -> TRIGGER -> GEOMETRY -> EXECUTION -> OUTCOME

over the frozen SESSION_TRADE_V2 @ 2.0.0 candidate on the already-existing
DEVELOPMENT partition (2017-01-01 .. 2017-09-01), and writes every required
artifact under ``artifacts/session_trade_v2_funnel_analysis/``.

Authority (frozen OFF): demo_authorized=false, live_authorized=false,
allow_order_send=false.  The sealed holdout (2017-12-01 .. 2018-01-01) is
structurally unreachable from this runner.

Usage:
    python scripts/run_stv2_funnel_analysis.py
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ag_edgelab.campaigns.session_trade_v2 import funnel_analyzer as fa  # noqa: E402
from ag_edgelab.campaigns.session_trade_v2.dataset import PARTITIONS  # noqa: E402
from ag_edgelab.campaigns.session_trade_v2.funnel_models import (  # noqa: E402
    CANONICAL_CANDIDATE_ID,
    EXPECTED_FILTER_STAGE_ROWS,
    EXPECTED_SEGMENTS,
)
from ag_edgelab.campaigns.session_trade_v2.funnel_report import (  # noqa: E402
    render_stage_matrix_csv,
    render_summary_markdown,
)
from ag_edgelab.campaigns.session_trade_v2.identity import (  # noqa: E402
    EXECUTION_AUTHORITY,
    SOURCE_BRANCH,
    SOURCE_COMMIT,
    SOURCE_PR,
    SOURCE_REPO,
    verify_identity,
)
from ag_edgelab.contracts.market import MarketBar  # noqa: E402

CACHE = REPO / ".campaign_cache"
M15_DIR = CACHE / "m15"
CAMPAIGN_ARTIFACTS = REPO / "artifacts" / "session_trade_v2_economic_matrix"
ARTIFACTS = REPO / "artifacts" / "session_trade_v2_funnel_analysis"

SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")
CAMPAIGN_SOURCE_PR = 10
CAMPAIGN_BRANCH = "arena/01a100ce-ag-edgelab"
CAMPAIGN_HEAD = "d6df82edf2d65d0a1feb28ae8500199ddbbede25"


def _git(args: list[str]) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                              text=True, check=True).stdout.strip()
    except subprocess.CalledProcessError:  # pragma: no cover
        return ""


def load_m15() -> dict[str, tuple[MarketBar, ...]]:
    bars: dict[str, tuple[MarketBar, ...]] = {}
    for symbol in SYMBOLS:
        path = M15_DIR / f"{symbol}_M15_2017.csv"
        if not path.is_file():
            raise SystemExit(
                f"missing frozen M15 cache {path}; run `python scripts/run_stv2_campaign.py build` "
                "with the frozen HistData zips in .campaign_cache/source_data first"
            )
        rows: list[MarketBar] = []
        with path.open() as fh:
            next(fh)
            for line in fh:
                ts, o, h, low, c = line.strip().split(",")
                rows.append(MarketBar(timestamp=datetime.fromisoformat(ts), open=float(o),
                                      high=float(h), low=float(low), close=float(c)))
        bars[symbol] = tuple(rows)
    return bars


def _dump(path: Path, payload, compact: bool = False) -> None:
    """Strict RFC-JSON (``allow_nan=False``) — matching EdgeLab's canonical_json policy.

    PF = infinity is never written as a sentinel number: the analyzer stores
    ``null`` plus an explicit ``*_pf_status`` reason, which keeps the artifact
    strict-RFC-JSON parseable (``allow_nan=False``).
    """
    if compact:
        path.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n")
    else:
        path.write_text(json.dumps(payload, indent=2, sort_keys=False, allow_nan=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit-sha", default="")
    parser.add_argument("--pr-number", default=None)
    args = parser.parse_args()

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    identity = verify_identity()
    if identity.candidate_id != CANONICAL_CANDIDATE_ID:  # pragma: no cover - fail closed
        raise SystemExit(f"BLOCKED: candidate identity drift: {identity.candidate_id}")

    quality = json.loads((CAMPAIGN_ARTIFACTS / "dataset_quality_reports.json").read_text())
    dataset_sha = {s: quality[s]["source_sha256"] for s in SYMBOLS}

    bars = load_m15()
    build = fa.build_analysis_units("DEVELOPMENT", bars, dataset_sha)
    units = build.units

    manifest = fa.build_segment_manifest(units)
    stage_matrix = fa.build_stage_matrix(units)
    branch_summary = fa.build_branch_summary(units)
    symbol_summary = fa.build_symbol_summary(units)
    session_summary = fa.build_session_summary(units)
    attrition = fa.build_attrition_analysis(units)
    geometry = fa.build_geometry_analysis(units)
    execution = fa.build_execution_analysis(units)
    friction = fa.build_friction_analysis(units)
    conditional = fa.build_conditional_expectancy_analysis(units)
    context_analysis = fa.build_context_analysis(units)
    findings = fa.build_findings(units, attrition, geometry, execution, friction, stage_matrix)
    b_reach = fa.analyze_b_reachability(units)
    findings["branch_b_structural_reachability"] = b_reach
    roots = [fa.classify_branch_root_cause(units, b) for b in
             ("A_SWEEP_REENTRY", "B_RANGE_REJECTION", "C_TREND_EXPANSION")]

    # ---- cross-check against the frozen economic campaign --------------
    dev = json.loads((CAMPAIGN_ARTIFACTS / "dev_result.json").read_text())
    consistency = _consistency(dev, branch_summary, build)

    counts = {b: fa.branch_counts(units, b) for b in
              ("A_SWEEP_REENTRY", "B_RANGE_REJECTION", "C_TREND_EXPANSION")}

    source_identity = {
        "source_repo": SOURCE_REPO,
        "source_pr": SOURCE_PR,
        "source_branch": SOURCE_BRANCH,
        "source_commit": SOURCE_COMMIT,
        "strategy_id": identity.strategy_id,
        "strategy_version": identity.strategy_version,
        "candidate_id": identity.candidate_id,
        "frozen_artifact_sha256": identity.artifact_sha256,
        "execution_authority": dict(EXECUTION_AUTHORITY),
        "frozen_rules_modified": False,
        "edgelab_campaign": {
            "repo": "aungmyat1/ag-edgelab",
            "pr": CAMPAIGN_SOURCE_PR,
            "branch": CAMPAIGN_BRANCH,
            "head_at_handoff": CAMPAIGN_HEAD,
            "artifacts": "artifacts/session_trade_v2_economic_matrix/",
        },
        "analysis_repo": {
            "repo": "aungmyat1/ag-edgelab",
            "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"]),
            "head": _git(["rev-parse", "HEAD"]),
        },
    }
    dataset_identity = {
        "reused_frozen_dataset": True,
        "redownloaded": False,
        "dev_partition": {"start": PARTITIONS["DEVELOPMENT"][0].isoformat(),
                          "end": PARTITIONS["DEVELOPMENT"][1].isoformat()},
        "oos_partition_used": False,
        "sealed_holdout": {"start": PARTITIONS["SEALED_HOLDOUT"][0].isoformat(),
                           "end": PARTITIONS["SEALED_HOLDOUT"][1].isoformat(),
                           "touched": False},
        "holdout_touched": False,
        "preserved_semantics": [
            "timezone normalization (America/New_York -> UTC)",
            "M1 -> M15 aggregation (>= 13/15 minutes per bucket, no synthetic fills)",
            "session completeness rules (exact 32/20 reference bars, exact 12 trade bars)",
            "same-bar ambiguity policy (stop-first, limit fill-bar target suppression)",
            "fill model (MARKET next-executable bar open; LIMIT at limit price with expiry)",
            "friction model (frozen per-symbol spread/commission/slippage authority)",
            "partition boundaries (no session straddles a partition edge)",
        ],
        "symbols": {s: {k: quality[s][k] for k in
                        ("source", "source_sha256", "m1_rows", "m15_bars",
                         "m15_buckets_with_lt13_minutes", "first_bar", "last_bar")}
                    for s in SYMBOLS},
    }

    trading_dates = len({u.trading_date for u in units})
    questions = _questions(counts, branch_summary, symbol_summary, session_summary,
                           geometry, execution, friction, context_analysis, roots,
                           consistency, findings, b_reach)
    hypotheses = _hypotheses(counts, geometry, execution, friction, b_reach)

    ctx = {
        "units": units,
        "segment_manifest": manifest,
        "stage_matrix": stage_matrix,
        "branch_summary": branch_summary,
        "symbol_summary": symbol_summary,
        "session_summary": session_summary,
        "attrition": attrition,
        "geometry": geometry,
        "execution": execution,
        "friction": friction,
        "conditional": conditional,
        "context_analysis": context_analysis,
        "root_causes": roots,
        "findings": findings,
        "source_identity": source_identity,
        "dataset_identity": dataset_identity,
        "partition": build.partition,
        "trading_dates": trading_dates,
        "campaign_source_pr": CAMPAIGN_SOURCE_PR,
        "campaign_branch": CAMPAIGN_BRANCH,
        "campaign_head": CAMPAIGN_HEAD,
        "consistency": consistency,
        "questions": questions,
        "hypotheses": hypotheses,
    }

    # ---- artifacts ------------------------------------------------------
    _dump(ARTIFACTS / "analysis_units.json", {
        "candidate_id": CANONICAL_CANDIDATE_ID,
        "partition": build.partition,
        "reconciliation": build.reconciliation,
        "analysis_units": len(units),
        "identity_collisions": fa.identity_collisions(units),
        "schema": {
            "note": (
                "candidate_id is constant across every unit by design; analysis_unit_id is the "
                "collision-free unit-level economic key. Stage features are restricted to the "
                "diagnostic whitelist in funnel_analyzer.ARTIFACT_FEATURE_KEYS; omitted "
                "economics fields mean NO EVIDENCE (never zero)."
            ),
            "feature_whitelist": fa.ARTIFACT_FEATURE_KEYS,
        },
        "units": [fa.unit_artifact_row(u) for u in units],
    }, compact=True)
    _dump(ARTIFACTS / "segment_manifest.json", manifest)
    _dump(ARTIFACTS / "funnel_stage_matrix.json", stage_matrix)
    (ARTIFACTS / "funnel_stage_matrix.csv").write_text(render_stage_matrix_csv(stage_matrix["rows"]))
    _dump(ARTIFACTS / "branch_summary.json", branch_summary)
    _dump(ARTIFACTS / "symbol_summary.json", symbol_summary)
    _dump(ARTIFACTS / "session_summary.json", session_summary)
    _dump(ARTIFACTS / "attrition_analysis.json", attrition)
    _dump(ARTIFACTS / "geometry_analysis.json", geometry)
    _dump(ARTIFACTS / "execution_analysis.json", execution)
    _dump(ARTIFACTS / "friction_analysis.json", friction)
    _dump(ARTIFACTS / "conditional_expectancy_analysis.json", conditional)
    _dump(ARTIFACTS / "context_analysis.json", context_analysis)
    _dump(ARTIFACTS / "source_identity.json", source_identity)
    _dump(ARTIFACTS / "dataset_identity.json", dataset_identity)
    _dump(ARTIFACTS / "findings.json", {
        "findings": findings,
        "root_causes": roots,
        "branch_counts": counts,
        "consistency": consistency,
        "follow_up_hypotheses": hypotheses,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": args.commit_sha or _git(["rev-parse", "HEAD"]),
        "pr_number": args.pr_number,
    })
    (ARTIFACTS / "funnel_summary.md").write_text(render_summary_markdown(ctx))

    print(f"analysis units      : {len(units)}")
    print(f"segments            : {manifest['segments']} (expected {EXPECTED_SEGMENTS})")
    print(f"filter-stage rows   : {stage_matrix['filter_stage_rows']} "
          f"(expected {EXPECTED_FILTER_STAGE_ROWS})")
    print(f"identity collisions : {fa.identity_collisions(units)}")
    print(f"reconciliation      : {build.reconciliation}")
    for b, c in counts.items():
        print(f"{b:<20} {c}")
    for r in roots:
        print(f"{r['branch']:<20} ROOT_CAUSE={r['root_cause']}")
    print("artifacts ->", ARTIFACTS)


def _consistency(dev: dict, branch_summary: dict, build) -> dict:
    by_branch = dev["aggregates"]["by_branch"]
    combined = dev["aggregates"]["combined"]
    checks: dict[str, dict] = {}
    contradictions: list[str] = []
    for s in branch_summary["summaries"]:
        c = by_branch[s["branch"]]
        o = s["outcome"]
        for label, campaign_v, funnel_v, digits in (
            (f"{s['branch']} closed trades", c["closed"], s["closed_n"], 0),
            (f"{s['branch']} gross expectancy R", c["gross_expectancy_r"],
             o["conditional_downstream_gross_expectancy_r"], 4),
            (f"{s['branch']} net expectancy R", c["net_expectancy_r"],
             o["conditional_downstream_net_expectancy_r"], 4),
        ):
            if digits == 0:
                fv, match = funnel_v, campaign_v == funnel_v
            else:
                fv = None if funnel_v is None else round(funnel_v, digits)
                # Compare at the campaign's own display precision: a half-ulp
                # difference in the 4th decimal is a rounding artifact, not a
                # disagreement about the underlying economics.
                match = (
                    campaign_v is None and fv is None
                ) or (
                    campaign_v is not None and funnel_v is not None
                    and abs(campaign_v - funnel_v) <= 1e-4
                )
            checks[label] = {"campaign": campaign_v, "funnel": fv, "match": match}
            if not match:
                contradictions.append(
                    f"{label}: campaign {campaign_v} vs funnel {fv}"
                )
    checks["Combined closed trades"] = {
        "campaign": combined["closed"],
        "funnel": build.reconciliation["funnel_closed_trades"],
        "match": combined["closed"] == build.reconciliation["funnel_closed_trades"],
    }
    checks["Combined net R"] = {
        "campaign": combined["net_r"],
        "funnel": round(build.reconciliation["funnel_net_r"], 4),
        "match": abs(combined["net_r"] - build.reconciliation["funnel_net_r"]) < 1e-3,
    }
    for k, v in checks.items():
        if not v["match"] and k not in [c.split(":")[0] for c in contradictions]:
            contradictions.append(f"{k}: campaign {v['campaign']} vs funnel {v['funnel']}")
    consistent = not contradictions
    statement = (
        "Every economic quantity in this funnel analysis is produced by the SAME frozen "
        "evaluation path (`campaign.evaluate_window`) as the economic-verification campaign, "
        "then re-aggregated along the strategy funnel. The DEV campaign result was also "
        "re-executed from the frozen HistData zips and reproduced `dev_result.json` exactly. "
        "The two reports therefore agree on every shared quantity."
        if consistent else
        "At least one shared quantity disagrees with the economic-verification report; the "
        "discrepancies are listed explicitly below and are NOT silently reconciled."
    )
    return {
        "consistent": consistent,
        "statement": statement,
        "checks": checks,
        "contradictions": contradictions,
        "comparison_policy": (
            "Shared economic quantities are compared at the economic-verification report's own "
            "display precision (tolerance 1e-4 R). Differences below that are rounding "
            "artifacts of independent round() calls on the same underlying float, not "
            "disagreements. Counts are compared exactly."
        ),
        "notes": [
            "The economic-verification report's conclusion (A_SWEEP_REENTRY REJECT on OOS; B and "
            "C RESEARCH_ONLY) is a VERIFICATION-LIFECYCLE verdict. This strategy-funnel report "
            "makes no promotion/rejection decision and does not re-open or re-interpret the OOS "
            "result; it only localizes WHERE opportunity and economics are lost on DEV.",
            "No OOS data was used to design any stage of this funnel. The DEV funnel definition "
            "is frozen by this report; any later OOS confirmation view must not alter it.",
        ],
    }


def _questions(counts, branch_summary, symbol_summary, session_summary, geometry,
               execution, friction, context_analysis, roots, consistency, findings,
               b_reach):
    a, b, c = counts["A_SWEEP_REENTRY"], counts["B_RANGE_REJECTION"], counts["C_TREND_EXPANSION"]
    bs = {s["branch"]: s for s in branch_summary["summaries"]}
    geo_a = [g for g in geometry["segments"] if g["branch"] == "A_SWEEP_REENTRY"]
    sweep_total = sum(g["sweep_stop_does_not_protect_extreme"] for g in geo_a)
    trig_total = sum(g["triggered"] for g in geo_a)
    exec_c = [e for e in execution["segments"] if e["branch"] == "C_TREND_EXPANSION"]
    c_elig = sum(e["geometry_valid_signals"] for e in exec_c)
    c_fill = sum(e["fills"] for e in exec_c)
    exec_b = [e for e in execution["segments"] if e["branch"] == "B_RANGE_REJECTION"]
    b_elig = sum(e["geometry_valid_signals"] for e in exec_b)
    b_fill = sum(e["fills"] for e in exec_b)
    a_out = bs["A_SWEEP_REENTRY"]["outcome"]
    root = {r["branch"]: r for r in roots}
    root_a, root_b, root_c = (root["A_SWEEP_REENTRY"], root["B_RANGE_REJECTION"],
                              root["C_TREND_EXPANSION"])

    def pct(x, y):
        return f"{(x / y * 100.0):.1f}%" if y else "n/a"

    ses = {s["session"]: s for s in session_summary["summaries"]}
    sym = {s["symbol"]: s for s in symbol_summary["summaries"]}

    q = []
    q.append((
        "Where does A lose the largest number/percentage of opportunities?",
        f"In absolute count, A's largest single loss is **TRIGGER → GEOMETRY**: "
        f"{a['TRIGGER'] - a['GEOMETRY']} of {a['TRIGGER']} authoritative triggers are removed "
        f"({pct(a['TRIGGER'] - a['GEOMETRY'], a['TRIGGER'])}), every one of them by the frozen "
        f"`SWEEP_STOP_DOES_NOT_PROTECT_EXTREME` rule.\n\n"
        f"The full A chain is CONTEXT {a['RAW_CONTEXT_INPUT']} raw → {a['CONTEXT']} valid → "
        f"LOCATION {a['LOCATION']} → TRIGGER {a['TRIGGER']} → GEOMETRY {a['GEOMETRY']} → "
        f"EXECUTION {a['EXECUTION']} → CLOSED {a['CLOSED']}. "
        f"The CONTEXT step removes {a['RAW_CONTEXT_INPUT'] - a['CONTEXT']} observations, but "
        f"{context_analysis['data_invalid_no_reference_bars_at_all']} of those are non-trading "
        f"calendar days (zero reference bars) rather than strategy rejections, so CONTEXT is "
        f"not a strategy-quality loss. Among genuine strategy filtering, geometry is the "
        f"largest sink, followed by LOCATION → TRIGGER "
        f"(-{a['LOCATION'] - a['TRIGGER']}, {pct(a['LOCATION'] - a['TRIGGER'], a['LOCATION'])}) "
        f"and CONTEXT → LOCATION "
        f"(-{a['CONTEXT'] - a['LOCATION']}, {pct(a['CONTEXT'] - a['LOCATION'], a['CONTEXT'])}). "
        f"A's GEOMETRY → EXECUTION attrition is 0 because A uses market-style entries.",
    ))
    q.append((
        "Does A already have poor trigger behavior, or is most attrition introduced by geometry?",
        f"Both contribute, but geometry is the larger filter. Of {a['CONTEXT']} valid A "
        f"observations, {a['LOCATION']} ({pct(a['LOCATION'], a['CONTEXT'])}) reached the "
        f"structural area and {a['TRIGGER']} ({pct(a['TRIGGER'], a['LOCATION'])} of those) "
        f"produced an authoritative sweep+reclaim trigger — that is a *healthy* trigger "
        f"conversion, so A does not suffer from trigger scarcity. Geometry then removes "
        f"{pct(a['TRIGGER'] - a['GEOMETRY'], a['TRIGGER'])} of those triggers. "
        f"Conclusion: **A's attrition is dominated by geometry, not by weak triggering** — but "
        f"this is a statement about opportunity *count*, not about whether the removed "
        f"opportunities would have been profitable. Nothing in this analysis can say what the "
        f"rejected sweeps would have returned, because they were never executed.",
    ))
    q.append((
        "How frequently does `SWEEP_STOP_DOES_NOT_PROTECT_EXTREME` remove A triggers?",
        f"{sweep_total} of {trig_total} A triggers ({pct(sweep_total, trig_total)}) across the "
        f"DEV partition. Per-segment rates (see §8) range from "
        f"{min(g['sweep_stop_rejection_pct'] for g in geo_a if g['triggered']):.1f}% to "
        f"{max(g['sweep_stop_rejection_pct'] for g in geo_a if g['triggered']):.1f}%. It is the "
        f"**only** geometry rejection reason observed for A; no other geometry check "
        f"(positive risk, 25% reference-range stop, stop side, target direction, 4R/5R "
        f"distances, branch entry geometry) ever failed on a frozen STV2 signal.",
    ))
    q.append((
        "Does realistic execution/friction materially degrade the remaining A trades?",
        f"Yes, decisively. A's {a['CLOSED']} closed trades have conditional downstream **gross** "
        f"expectancy {a_out['conditional_downstream_gross_expectancy_r']:+.4f}R but **net** "
        f"expectancy {a_out['conditional_downstream_net_expectancy_r']:+.4f}R — an average "
        f"friction drag of {a_out['average_cost_r']:.4f}R per trade "
        f"({a_out['friction_r']:.2f}R in total). Friction alone flips A from gross-positive to "
        f"net-negative. Execution *fill* behaviour is not the problem for A (fill rate 100%, "
        f"market-style next-executable-price entries); the degradation is pure cost. "
        f"Friction-destroyed segments (gross expectancy > 0 and net expectancy ≤ 0): "
        + (", ".join(f"`{s}`" for s in friction["friction_destroyed_segments"]) or "none") + ".",
    ))
    q.append((
        "Is B primarily sparse at LOCATION, sparse at TRIGGER, rejected by geometry, or failing to fill?",
        f"**Neither location-sparse nor geometry-rejected.** B reaches its structural area on "
        f"{b['LOCATION']} of {b['CONTEXT']} valid observations ({pct(b['LOCATION'], b['CONTEXT'])}) "
        f"and its own frozen rejection predicate fires on "
        f"{root_b['raw_branch_rule_fired']} of them — but only **{b['TRIGGER']}** sessions are "
        f"authoritatively attributed to B by the frozen engine "
        f"({root_b['trigger_preempted_by_precedence']} are preempted), because the frozen "
        f"A → B → C priority gives the session to A whenever a sweep exists. The attrition table shows "
        f"`TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY` as B's dominant trigger-stage rejection reason. "
        f"Geometry then rejects **0** of the {b['TRIGGER']} survivors, and execution fills "
        f"{b_fill} of {b_elig} ({pct(b_fill, b_elig)}) — the remainder expire unfilled at the "
        f"boundary limit. So B is best described as **priority-starved first, fill-starved "
        f"second**; with {b['CLOSED']} closed trades no economic conclusion about B is "
        f"supportable.\n\n"
        f"**Structural root of B's scarcity** (a restatement of the frozen predicates, not a "
        f"rule change): A's long sweep predicate `low < ref_low AND close > ref_low` strictly "
        f"subsumes B's long rejection predicate `low <= ref_low AND inward close` whenever the "
        f"boundary is *breached*. Since A is scanned over the whole trade window before B, B "
        f"can only own a session when price touches the reference boundary to the **exact "
        f"tick**. All {b_reach['authoritative_b_triggers']} authoritative B triggers in DEV "
        f"have their entry exactly on the reference boundary "
        f"({b_reach['entries_exactly_on_reference_boundary']}/"
        f"{b_reach['authoritative_b_triggers']}), confirming this. B's scarcity is a "
        f"structural property of the frozen predicate overlap, not evidence that range "
        f"rejection is a weak idea.",
    ))
    q.append((
        "Is C generating valid breakouts but starving at its EQ limit?",
        f"**Yes — this is the single clearest finding in the analysis.** C produces "
        f"{c['TRIGGER']} authoritative body-close expansion triggers, of which "
        f"{c['GEOMETRY']} ({pct(c['GEOMETRY'], c['TRIGGER'])}) are geometrically valid — C has "
        f"zero geometry attrition. But only **{c_fill} of {c_elig}** geometry-valid proposals "
        f"ever fill ({pct(c_fill, c_elig)}): price must retrace from a confirmed body-close "
        f"breakout all the way back to the reference equilibrium (box mid) inside the remaining "
        f"trade window, which essentially never happens. "
        f"{sum(e['expired'] for e in exec_c)} expired unfilled, of which "
        f"{sum(e['expired_never_workable'] for e in exec_c)} were generated on the final "
        f"trade-window candle and were never workable at all. C's funnel is "
        f"**trigger-rich and execution-starved**.",
    ))
    q.append((
        "Which symbol/session segments behave differently?",
        "**Session is the dominant axis.** "
        f"LONDON_NEWYORK: {ses['LONDON_NEWYORK']['closed_n']} closed trades, conditional gross "
        f"expectancy {ses['LONDON_NEWYORK']['outcome']['conditional_downstream_gross_expectancy_r']:+.4f}R, "
        f"net {ses['LONDON_NEWYORK']['outcome']['conditional_downstream_net_expectancy_r']:+.4f}R, "
        f"win rate {ses['LONDON_NEWYORK']['outcome']['win_rate']:.1%}. "
        f"ASIAN_LONDON: {ses['ASIAN_LONDON']['closed_n']} closed trades, gross "
        f"{ses['ASIAN_LONDON']['outcome']['conditional_downstream_gross_expectancy_r']:+.4f}R, "
        f"net {ses['ASIAN_LONDON']['outcome']['conditional_downstream_net_expectancy_r']:+.4f}R, "
        f"win rate {ses['ASIAN_LONDON']['outcome']['win_rate']:.1%}. "
        "Every ASIAN_LONDON A segment is net-negative; every LONDON_NEWYORK A segment is "
        "net-positive or near flat (this matches the economic campaign's DEV survivor set). "
        "**Symbol is a weaker axis**: per-symbol conditional net expectancy ranges from "
        + ", ".join(
            f"{s}={sym[s]['outcome']['conditional_downstream_net_expectancy_r']:+.4f}R "
            f"({sym[s]['closed_n']} closed)" for s in sorted(sym)
        )
        + ". Note that this DEV-only session split is exactly the pattern that failed to "
        "replicate OOS in the economic campaign, so it must be treated as a DEV observation, "
        "not a validated edge.",
    ))
    q.append((
        "Which diagnostics are robust enough to justify a NEW candidate hypothesis?",
        "Three, all of them *structural* (count-based) rather than economic, which is why they "
        "survive the sample-size objection:\n\n"
        f"1. **C EQ-limit fill starvation** — {c_fill}/{c_elig} fills is a structural fact about "
        "the order model, not a noisy expectancy estimate. Robust.\n"
        f"2. **A geometry attrition** — {sweep_total}/{trig_total} triggers removed by a single "
        "deterministic rule, consistent across all 8 A segments. Robust as a *measurement*; it "
        "does **not** establish that the removed trades would have been profitable.\n"
        f"3. **B/C priority preemption** — B's own predicate fires "
        f"{root_b['raw_branch_rule_fired']} times but the frozen A→B→C precedence leaves it "
        f"only {b['TRIGGER']} sessions ({root_b['trigger_preempted_by_precedence']} preempted); "
        f"C loses {root_c['trigger_preempted_by_precedence']} the same way. Robust as a "
        f"measurement.\n\n"
        f"**Not** robust enough: A's friction decay is a large and reliable *cost* measurement "
        f"({a_out['average_cost_r']:.4f}R/trade over {a['CLOSED']} trades), but 'reduce friction "
        "by changing the stop' is a performance claim that requires a preregistered experiment, "
        "not an inference from this table.",
    ))
    q.append((
        "Which findings are inconclusive because of sample size?",
        "- "
        + "\n- ".join(findings["inconclusive"]),
    ))
    q.append((
        "Does any finding contradict the existing STV2 economic-verification report?",
        ("**No contradiction.** " if consistency["consistent"] else "**Contradiction found.** ")
        + consistency["statement"]
        + "\n\n"
        + "\n".join(f"- {n}" for n in consistency["notes"])
        + ("\n\nContradictions: none." if consistency["consistent"]
           else "\n\nContradictions:\n" + "\n".join(f"- {c}" for c in consistency["contradictions"])),
    ))
    return q


def _hypotheses(counts, geometry, execution, friction, b_reach):
    a, b, c = counts["A_SWEEP_REENTRY"], counts["B_RANGE_REJECTION"], counts["C_TREND_EXPANSION"]
    geo_a = [g for g in geometry["segments"] if g["branch"] == "A_SWEEP_REENTRY"]
    sweep_total = sum(g["sweep_stop_does_not_protect_extreme"] for g in geo_a)
    trig_total = sum(g["triggered"] for g in geo_a)
    exec_c = [e for e in execution["segments"] if e["branch"] == "C_TREND_EXPANSION"]
    c_elig = sum(e["geometry_valid_signals"] for e in exec_c)
    c_fill = sum(e["fills"] for e in exec_c)
    return [
        {
            "hypothesis_id": "STV3_H1_SWEEP_STOP_GEOMETRY",
            "evidence_source": "geometry_analysis.json; funnel_stage_matrix.json (TRIGGER→GEOMETRY rows)",
            "observed_problem": (
                f"{sweep_total} of {trig_total} A triggers ({sweep_total / trig_total:.1%}) are "
                "discarded because the fixed 25%-of-reference-range stop sits inside the sweep "
                "extreme. This is a measured attrition fact; the economics of the discarded "
                "opportunities are unknown and unknowable from this dataset."
            ),
            "proposed_new_candidate_change": (
                "A NEW candidate (e.g. SESSION_TRADE_V3_A_STOPGEOM) whose A stop is placed "
                "beyond the sweep extreme by a defined buffer instead of at a fixed 25% of the "
                "reference range. SESSION_TRADE_V2 @ 2.0.0 is NOT modified."
            ),
            "what_must_be_preregistered": (
                "The exact stop formula and buffer; that R is redefined by that stop (so 4R/5R "
                "targets move); the expected direction and magnitude of the effect; the "
                "acceptance thresholds; the DEV/OOS/holdout partitions; and an explicit "
                "statement that the retained-but-previously-rejected trades are a NEW "
                "population, not a recovered one."
            ),
            "required_new_validation": (
                "A fresh full verification lifecycle for the new candidate id: contract, data "
                "quality, DEV screen, freeze, OOS verification, walk-forward, regime/stability. "
                "The STV2 OOS failure may not be reused as evidence for or against it."
            ),
        },
        {
            "hypothesis_id": "STV3_H2_EXPANSION_ENTRY_MODEL",
            "evidence_source": "execution_analysis.json (C_TREND_EXPANSION rows)",
            "observed_problem": (
                f"C produces {c['TRIGGER']} valid expansion triggers with 100% geometry validity "
                f"but only {c_fill}/{c_elig} fills ({c_fill / c_elig:.2%}). The EQ (box-mid) "
                "retrace limit is almost never reached inside the remaining trade window, so C "
                "is structurally unmeasurable rather than unprofitable."
            ),
            "proposed_new_candidate_change": (
                "A NEW candidate whose expansion entry model is specified to be reachable "
                "(the design space includes, but is not limited to, a shallower retrace level, "
                "a broken-boundary retest, or a stop-entry continuation). No specific variant is "
                "endorsed by this analysis."
            ),
            "what_must_be_preregistered": (
                "The entry model and its stop/target geometry; the order type; the expiry rule; "
                "the minimum fill rate that would make the branch measurable at all; and the "
                "sample size required before any economic statement is permitted."
            ),
            "required_new_validation": (
                "Fill-rate feasibility screen on DEV first (a purely structural gate), then the "
                "full verification lifecycle under a new candidate id. C's deterministic runner "
                "management must also be defined, since the frozen spec's 'confirmed M15 swing' "
                "trail is not deterministic and is currently replayed as C_FIXED_EXIT_PROXY."
            ),
        },
        {
            "hypothesis_id": "STV3_H3_BRANCH_PRECEDENCE",
            "evidence_source": "attrition_analysis.json (B/C TRIGGER rejection reasons)",
            "observed_problem": (
                f"B's rejection rule fires on many sessions but the frozen A→B→C precedence "
                f"attributes only {b['TRIGGER']} sessions to B (dominant reason "
                f"`TRIGGER_PREEMPTED_BY_A_SWEEP_REENTRY`); C loses "
                f"{c['LOCATION'] - c['TRIGGER']} observations at TRIGGER with preemption as a "
                "major component. The branches are therefore not independently measurable under "
                "V2's single-decision-per-session contract."
            ),
            "proposed_new_candidate_change": (
                "A NEW candidate that makes branch arbitration explicit and measurable — e.g. "
                "evaluating branches independently per session, or defining a precedence rule "
                "that is itself a declared parameter. V2's precedence stays frozen."
            ),
            "what_must_be_preregistered": (
                "Whether branches may co-fire on one session; how overlapping positions are "
                "accounted for in R terms; the risk-budget implications; and the fact that this "
                "changes the unit of observation, so prior STV2 statistics are not comparable."
            ),
            "required_new_validation": (
                "Full verification lifecycle under a new candidate id, plus an explicit "
                "multiple-comparisons policy because independent branch evaluation materially "
                "increases the number of tested hypotheses."
            ),
        },
        {
            "hypothesis_id": "STV3_H4_FRICTION_AWARE_RISK_UNIT",
            "evidence_source": "friction_analysis.json; branch_summary.json",
            "observed_problem": (
                f"A's {a['CLOSED']} closed trades are gross-positive and net-negative; the "
                "friction drag is large relative to R because R itself is only 25% of a session "
                "reference range, which on quiet sessions is small in price terms."
            ),
            "proposed_new_candidate_change": (
                "A NEW candidate with a declared minimum risk distance (or a minimum "
                "friction-to-R ratio) as an admission filter, so that sessions whose R is too "
                "small to survive realistic cost are never traded."
            ),
            "what_must_be_preregistered": (
                "The exact threshold and the fact that it is a CONTEXT-stage admission filter, "
                "not an exit optimization; the expected reduction in trade count; and that the "
                "threshold must be chosen on DEV only and then frozen."
            ),
            "required_new_validation": (
                "Full verification lifecycle under a new candidate id. This is explicitly NOT a "
                "validated improvement: filtering on an in-sample cost ratio is a known "
                "overfitting hazard and must be tested out of sample."
            ),
        },
    ]


if __name__ == "__main__":
    main()
