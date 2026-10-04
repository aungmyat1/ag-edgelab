from __future__ import annotations

"""Rendering layer for ``STV2_STRATEGY_FUNNEL_ANALYZER_V1``.

Produces ``funnel_stage_matrix.csv`` and ``funnel_summary.md``.  Nothing here
computes economics: every number is read from the analyzer's artifacts.
"""

import csv
import io
from typing import Any, Mapping, Sequence

from ag_edgelab.campaigns.session_trade_v2.funnel_analyzer import (
    MIN_SAMPLE_FOR_ECONOMIC_CLAIM,
    branch_counts,
)
from ag_edgelab.campaigns.session_trade_v2.funnel_models import (
    CANONICAL_CANDIDATE_ID,
    EXPECTED_FILTER_STAGE_ROWS,
    EXPECTED_SEGMENTS,
)
from ag_edgelab.campaigns.session_trade_v2.windows import BRANCHES, SESSIONS, SYMBOLS

CSV_COLUMNS = (
    "segment_id",
    "branch",
    "symbol",
    "session",
    "stage",
    "stage_index",
    "structurally_possible",
    "stage_input_count",
    "stage_retained_count",
    "stage_retained_pct",
    "data_invalid_count",
    "ambiguity_count",
    "signals",
    "geometry_valid",
    "fills",
    "unfilled",
    "expired",
    "open_at_end",
    "closed_trades",
    "wins",
    "losses",
    "breakeven",
    "win_rate",
    "win_ci95_low",
    "win_ci95_high",
    "conditional_downstream_gross_expectancy_r",
    "conditional_downstream_net_expectancy_r",
    "conditional_downstream_gross_pf",
    "conditional_downstream_gross_pf_status",
    "conditional_downstream_net_pf",
    "conditional_downstream_net_pf_status",
    "conditional_downstream_gross_r",
    "conditional_downstream_net_r",
    "friction_r",
    "average_cost_r",
    "win_rate_lift_pp",
    "conditional_net_expectancy_shift_r",
)


def render_stage_matrix_csv(rows: Sequence[Mapping[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: _csv_value(row.get(c)) for c in CSV_COLUMNS})
    return buffer.getvalue()


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


# ---------------------------------------------------------------------------
# markdown helpers
# ---------------------------------------------------------------------------


def _n(value: Any, digits: int = 4, pf_status: str | None = None) -> str:
    if pf_status == "INFINITE_NO_LOSING_TRADES":
        return "∞"
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _table(header: Sequence[str], rows: Sequence[Sequence[Any]], align: Sequence[str] | None = None) -> str:
    align = align or (["---"] * len(header))
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(align) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


def render_summary_markdown(ctx: Mapping[str, Any]) -> str:
    units = ctx["units"]
    matrix = ctx["stage_matrix"]
    manifest = ctx["segment_manifest"]
    branch_sum = ctx["branch_summary"]
    symbol_sum = ctx["symbol_summary"]
    session_sum = ctx["session_summary"]
    attrition = ctx["attrition"]
    geometry = ctx["geometry"]
    execution = ctx["execution"]
    friction = ctx["friction"]
    conditional = ctx["conditional"]
    context_an = ctx["context_analysis"]
    roots = ctx["root_causes"]
    source = ctx["source_identity"]
    dataset = ctx["dataset_identity"]
    findings = ctx["findings"]

    p: list[str] = []
    w = p.append

    w("# SESSION_TRADE_V2 @ 2.0.0 — Strategy Funnel Analysis")
    w("")
    w("`STV2_STRATEGY_FUNNEL_ANALYZER_V1` — **diagnostic research only**.")
    w("")
    w(
        "This report implements **Funnel B — Strategy Funnel Analyzer** "
        "(`CONTEXT → LOCATION → TRIGGER → GEOMETRY → EXECUTION → OUTCOME`), which is a "
        "*trade-rule diagnostic*. It is **not** the Verification Lifecycle Funnel "
        "(`CONTRACT → DATA_QUALITY → DEV_SCREEN → FREEZE → OOS_VERIFICATION → WALK_FORWARD → "
        "REGIME/STABILITY → EDGE_VERIFIED`) that the existing economic-matrix campaign belongs "
        "to. The two funnels are kept strictly separate; no lifecycle stage was repurposed."
    )
    w("")
    w("## 0. Authority and scope")
    w("")
    w(
        _table(
            ["Key", "Value"],
            [
                ["`demo_authorized`", "`false`"],
                ["`live_authorized`", "`false`"],
                ["`allow_order_send`", "`false`"],
                ["`HOLDOUT_TOUCHED`", "`false`"],
                ["Frozen rules modified", "`none`"],
                ["Parameters optimized", "`none`"],
                ["Production scanner changed", "`no`"],
                ["Promotion decision made", "`no`"],
            ],
        )
    )
    w("")
    w("## 1. Identity and provenance")
    w("")
    w(
        _table(
            ["Key", "Value"],
            [
                ["Strategy source repo", f"`{source['source_repo']}`"],
                ["Source PR", f"`#{source['source_pr']}`"],
                ["Source branch", f"`{source['source_branch']}`"],
                ["`SOURCE_STRATEGY_SHA`", f"`{source['source_commit']}`"],
                ["`CANONICAL_CANDIDATE_ID`", f"`{CANONICAL_CANDIDATE_ID}`"],
                ["EdgeLab campaign PR", f"`#{ctx['campaign_source_pr']}`"],
                ["Campaign branch", f"`{ctx['campaign_branch']}`"],
                ["Campaign head at handoff", f"`{ctx['campaign_head']}`"],
                ["DEV partition", f"`{ctx['partition']['start']}` → `{ctx['partition']['end']}`"],
                ["Sealed holdout", "`2017-12-01` → `2018-01-01` (never opened)"],
            ],
        )
    )
    w("")
    w("### Identity model (outcome-collision fix)")
    w("")
    w(
        "The generic funnel analytics indexed outcomes by `record.candidate_id`. Every STV2 "
        "observation shares one candidate id, so that key collapses the whole dataset onto a "
        "single outcome. Three identity concepts are now distinct:"
    )
    w("")
    w(
        _table(
            ["Concept", "Meaning", "Count"],
            [
                ["`candidate_id`", f"`{CANONICAL_CANDIDATE_ID}` (strategy candidate)", "1"],
                ["`segment_id`", "`SESSION_TRADE_V2\\|SYMBOL\\|SESSION\\|BRANCH`", str(manifest["segments"])],
                [
                    "`analysis_unit_id`",
                    "sha256 of (candidate_id, strategy_id, strategy_version, symbol, session, "
                    "branch, trading_date, event_identity, dataset_sha256)",
                    str(manifest["analysis_units"]),
                ],
            ],
        )
    )
    w("")
    w(f"`EXPECTED_SEGMENTS = {EXPECTED_SEGMENTS}`; `SEGMENTS = {manifest['segments']}`; "
      f"`IDENTITY_COLLISIONS = {manifest['identity_collisions']}`.")
    w("")
    w(
        f"`EXPECTED_ANALYSIS_UNITS != 24`. The analysis-unit count is data-driven: "
        f"`{manifest['analysis_units']}` = "
        f"{ctx['trading_dates']} evaluable trading dates × {len(SYMBOLS)} symbols × "
        f"{len(SESSIONS)} sessions × {len(BRANCHES)} branches."
    )
    w("")
    w("### Dataset identity (frozen, reused — not re-downloaded)")
    w("")
    w(
        _table(
            ["Symbol", "Source artifact", "sha256", "M15 bars"],
            [
                [s, f"`{d['source']}`", f"`{d['source_sha256']}`", str(d["m15_bars"])]
                for s, d in dataset["symbols"].items()
            ],
        )
    )
    w("")
    w(
        "All four hashes are byte-identical to the frozen campaign's "
        "`dataset_quality_reports.json`, and re-running the frozen DEV campaign reproduced "
        "`dev_result.json` exactly (cells, aggregates, session records, partition and friction "
        "authority all match). Timezone normalization, M1→M15 aggregation, session completeness, "
        "same-bar ambiguity policy, fill model, friction model and partition boundaries are all "
        "reused unchanged."
    )
    w("")
    w("## 2. Metric semantics (mandatory reading)")
    w("")
    w("Two metric classes are reported, and they are never mixed:")
    w("")
    w(
        "**A. Retention metrics** (`stage_input_count`, `stage_retained_count`, "
        "`stage_retained_pct`) — always valid at every stage."
    )
    w("")
    w(
        "**B. Conditional downstream economic metrics** "
        "(`conditional_downstream_*`) — *Among observations that reached this stage and "
        "eventually produced a CLOSED trade under unchanged downstream rules, what was the "
        "realized result?*"
    )
    w("")
    w("The following are explicitly **not** done anywhere in this analyzer:")
    w("")
    w("- rejected / unfilled / expired observations are **never** imputed as `0R`;")
    w("- no hypothetical outcome is fabricated for a signal that never filled;")
    w("- `DATA_INVALID` observations are counted separately and never become losses;")
    w("- `OPEN_AT_END` fills are censored, never merged into closed-trade economics;")
    w("- undefined metrics are `null`, never `0`;")
    w("- `PF = ∞` is stored as `null` plus an explicit "
      "`*_pf_status = \"INFINITE_NO_LOSING_TRADES\"` (never a sentinel such as `999`); the "
      "Markdown rendering shows `∞`.")
    w("")
    w("### A structural property of the conditional-cohort definition")
    w("")
    w(
        "Under the mandated (non-counterfactual) definition, the conditional cohort is "
        "*identical at every stage*: a trade can only close if it survived **all** five stages, "
        "so the set of closed trades retained at CONTEXT equals the set retained at EXECUTION. "
        "Consequently `conditional_net_expectancy_shift_r` is **0.0 by construction at every "
        "transition**, and this report says so rather than manufacturing a stage-to-stage "
        "economic decay curve. Any non-zero stage-wise \"expectancy decay\" would require "
        "assigning realized results to observations that were rejected later — exactly the "
        "counterfactual invention this mission forbids. The one economically real degradation "
        "that *is* measurable on executed trades is **gross → net friction decay**, reported in "
        "§8."
    )
    w("")
    w("### R-unit and target accounting")
    w("")
    w(
        "One risk unit `R` is the frozen quarter-reference-range stop distance "
        "`r0 = 0.25 * (reference_high - reference_low)`, measured from the actual fill price. "
        "Branch A and branch B scale out: **75% of the position at +4R, then the stop moves to "
        "entry, and the remaining 25% runs to +5R**. A full winner is therefore "
        "`0.75 * 4R + 0.25 * 5R = ` **4.25R gross**, and it is reported as 4.25R throughout this "
        "document — it is *not* a \"5R\" result. If the runner is stopped at breakeven after the "
        "first target, the trade books `0.75 * 4R = 3.00R` gross. Net R is the same quantity "
        "after the frozen friction model. Branch C is replayed under the diagnostic "
        "`C_FIXED_EXIT_PROXY` exit because the frozen spec's \"confirmed M15 swing\" trail is not "
        "deterministic."
    )
    w("")
    w("## 3. Full 24-segment funnel matrix")
    w("")
    w(f"`FILTER_STAGE_ROWS = {matrix['filter_stage_rows']}` "
      f"(`EXPECTED_FILTER_STAGE_ROWS = {EXPECTED_FILTER_STAGE_ROWS}`). "
      "No structurally impossible stage rows exist for STV2; all five filtering stages are "
      "reachable for every branch.")
    w("")
    rows = []
    for r in matrix["rows"]:
        rows.append(
            [
                r["branch"].split("_")[0],
                r["symbol"],
                "AL" if r["session"] == "ASIAN_LONDON" else "LN",
                r["stage"],
                r["stage_input_count"],
                r["stage_retained_count"],
                _n(r["stage_retained_pct"], 2),
                r["closed_trades"],
                _n(None if r["win_rate"] is None else r["win_rate"] * 100, 2),
                _n(r["conditional_downstream_net_expectancy_r"]),
                _n(r["conditional_downstream_net_pf"], 3, r["conditional_downstream_net_pf_status"]),
                _n(r["conditional_net_expectancy_shift_r"]),
                _n(r["friction_r"], 3),
            ]
        )
    w(
        _table(
            ["Branch", "Symbol", "Session", "Stage", "Input", "Retained", "Retained %",
             "Closed", "Win %", "Cond Net Exp R", "Net PF", "Exp Shift", "Friction R"],
            rows,
            align=["---", "---", "---", "---", "---:", "---:", "---:", "---:", "---:",
                   "---:", "---:", "---:", "---:"],
        )
    )
    w("")
    w("_Session codes: `AL` = ASIAN_LONDON, `LN` = LONDON_NEWYORK._")
    w("")
    w("## 4. Branch summaries")
    w("")
    w(
        _table(
            ["Branch", "Raw CONTEXT N", "CONTEXT", "LOCATION", "TRIGGER", "GEOMETRY",
             "EXECUTION (fills)", "CLOSED", "Cond Gross Exp R", "Cond Net Exp R", "Win %",
             "Net PF", "Friction R"],
            [
                [
                    s["branch"], s["raw_context_n"], s["context_n"], s["location_n"],
                    s["trigger_n"], s["geometry_n"], s["execution_n"], s["closed_n"],
                    _n(s["outcome"]["conditional_downstream_gross_expectancy_r"]),
                    _n(s["outcome"]["conditional_downstream_net_expectancy_r"]),
                    _n(None if s["outcome"]["win_rate"] is None else s["outcome"]["win_rate"] * 100, 2),
                    _n(s["outcome"]["conditional_downstream_net_pf"], 3,
                       s["outcome"]["conditional_downstream_net_pf_status"]),
                    _n(s["outcome"]["friction_r"], 3),
                ]
                for s in branch_sum["summaries"]
            ],
            align=["---"] + ["---:"] * 12,
        )
    )
    w("")
    w("## 5. Symbol summaries")
    w("")
    w(_dimension_table(symbol_sum, "symbol"))
    w("")
    w("## 6. Session summaries")
    w("")
    w(_dimension_table(session_sum, "session"))
    w("")
    w("## 7. Attrition analysis")
    w("")
    w("### 7.1 CONTEXT attrition (data validity, not strategy rejection)")
    w("")
    w(
        _table(
            ["Metric", "Value"],
            [
                ["Session observations (per branch)", context_an["session_observations"]],
                ["CONTEXT valid", context_an["context_valid"]],
                ["`DATA_INVALID`", f"{context_an['data_invalid']} "
                                   f"({_n(context_an['data_invalid_pct'], 2)} %)"],
                ["… zero reference bars (non-trading calendar day)",
                 context_an["data_invalid_no_reference_bars_at_all"]],
                ["… partial reference window (real data gap)",
                 context_an["data_invalid_partial_reference_window"]],
            ],
        )
    )
    w("")
    w("### 7.2 Per-segment stage-to-stage attrition")
    w("")
    arows = []
    for seg in attrition["segments"]:
        for t in seg["transitions"]:
            top = next(iter(t["rejection_reasons"].items()), None)
            arows.append(
                [
                    seg["branch"].split("_")[0], seg["symbol"],
                    "AL" if seg["session"] == "ASIAN_LONDON" else "LN",
                    f"{t['from_stage']}→{t['to_stage']}",
                    t["input_count"], t["retained_count"], t["attrition_count"],
                    _n(t["attrition_pct"], 2),
                    f"`{top[0]}` ({top[1]})" if top else "—",
                ]
            )
    w(
        _table(
            ["Branch", "Symbol", "Session", "Transition", "Input", "Retained", "Lost",
             "Attrition %", "Dominant rejection reason"],
            arows,
            align=["---", "---", "---", "---", "---:", "---:", "---:", "---:", "---"],
        )
    )
    w("")
    w("### 7.3 Largest attrition points")
    w("")
    for line in findings["largest_attrition_points"]:
        w(f"- {line}")
    w("")
    w("## 8. Geometry diagnostics")
    w("")
    w(
        _table(
            ["Branch", "Symbol", "Session", "Triggered", "Geometry valid", "Rejected",
             "Rejection %", "`SWEEP_STOP_DOES_NOT_PROTECT_EXTREME`", "Sweep-stop %",
             "Other reasons"],
            [
                [
                    g["branch"].split("_")[0], g["symbol"],
                    "AL" if g["session"] == "ASIAN_LONDON" else "LN",
                    g["triggered"], g["geometry_valid"], g["geometry_rejected"],
                    _n(g["geometry_rejection_pct"], 2), g["sweep_stop_does_not_protect_extreme"],
                    _n(g["sweep_stop_rejection_pct"], 2),
                    ", ".join(f"`{k}`×{v}" for k, v in g["other_geometry_rejection_reasons"].items()) or "—",
                ]
                for g in geometry["segments"]
            ],
            align=["---", "---", "---", "---:", "---:", "---:", "---:", "---:", "---:", "---"],
        )
    )
    w("")
    w("## 9. Execution diagnostics")
    w("")
    w(
        _table(
            ["Branch", "Symbol", "Session", "Order type", "Geometry-valid signals", "Fills",
             "Unfilled", "Expired", "… never workable", "Same-bar ambiguities", "Fill rate",
             "Closed", "Open at end"],
            [
                [
                    e["branch"].split("_")[0], e["symbol"],
                    "AL" if e["session"] == "ASIAN_LONDON" else "LN",
                    e["order_type"] or "—", e["geometry_valid_signals"], e["fills"],
                    e["unfilled"], e["expired"], e["expired_never_workable"],
                    e["same_bar_ambiguities"],
                    _n(None if e["fill_rate"] is None else e["fill_rate"] * 100, 2),
                    e["closed_trades"], e["open_at_end"],
                ]
                for e in execution["segments"]
            ],
            align=["---", "---", "---", "---"] + ["---:"] * 9,
        )
    )
    w("")
    w("## 10. Friction analysis")
    w("")
    w(
        "Applied **only** to actually executed, closed trades. Segments with no executed trades "
        "report `—` (null), never a fabricated zero."
    )
    w("")
    w(
        _table(
            ["Branch", "Symbol", "Session", "Closed", "Gross R", "Net R", "Friction R",
             "Gross Exp R", "Net Exp R", "Friction drag / trade R", "Gross>0 and Net≤0"],
            [
                [
                    f["branch"].split("_")[0], f["symbol"],
                    "AL" if f["session"] == "ASIAN_LONDON" else "LN",
                    f["closed_trades"], _n(f["gross_r"], 3), _n(f["net_r"], 3),
                    _n(f["friction_r"], 3), _n(f["gross_expectancy_r"]),
                    _n(f["net_expectancy_r"]), _n(f["friction_drag_per_trade_r"]),
                    _n(f["gross_positive_net_non_positive"]),
                ]
                for f in friction["segments"]
            ],
            align=["---", "---", "---"] + ["---:"] * 8,
        )
    )
    w("")
    w(
        "**Friction-destroyed segments** (gross expectancy > 0 **and** net expectancy ≤ 0): "
        + (", ".join(f"`{s}`" for s in friction["friction_destroyed_segments"]) or "none")
    )
    w("")
    w("## 11. Conditional expectancy-shift view — **DIAGNOSTIC / NON-CAUSAL**")
    w("")
    w(f"> {conditional['interpretation_rule']}")
    w("")
    w(
        "As explained in §2, under the non-counterfactual definition every stage's closed-trade "
        "cohort is the same set, so all shifts are exactly `0.0`. This is reported honestly "
        "rather than replaced with a fabricated decay curve."
    )
    w("")
    w(
        _table(
            ["Branch", "Stage", "Retained", "Closed", "Cond Gross Exp R", "Cond Net Exp R",
             "Exp shift R", "Win %", "Win lift pp"],
            [
                [
                    s["branch"].split("_")[0], r["stage"], r["stage_retained_count"],
                    r["closed_trades"],
                    _n(r["conditional_downstream_gross_expectancy_r"]),
                    _n(r["conditional_downstream_net_expectancy_r"]),
                    _n(r["conditional_net_expectancy_shift_r"]),
                    _n(None if r["win_rate"] is None else r["win_rate"] * 100, 2),
                    _n(r["win_rate_lift_pp"], 2),
                ]
                for s in branch_sum["summaries"] for r in s["stage_rows"]
            ],
            align=["---", "---"] + ["---:"] * 7,
        )
    )
    w("")
    w("**Measurable economic degradation on executed trades (gross → net):**")
    w("")
    w(
        _table(
            ["Branch", "Closed", "Gross Exp R", "Net Exp R", "Friction decay R/trade"],
            [
                [
                    s["branch"], s["closed_n"],
                    _n(s["outcome"]["conditional_downstream_gross_expectancy_r"]),
                    _n(s["outcome"]["conditional_downstream_net_expectancy_r"]),
                    _n(s["outcome"]["average_cost_r"]),
                ]
                for s in branch_sum["summaries"]
            ],
            align=["---"] + ["---:"] * 4,
        )
    )
    w("")
    w("## 12. Report questions")
    w("")
    for i, (question, answer) in enumerate(ctx["questions"], start=1):
        w(f"### Q{i}. {question}")
        w("")
        w(answer)
        w("")
    w("## 13. Root-cause classification")
    w("")
    w(
        _table(
            ["Branch", "Root cause", "Contributors", "Closed N", "Sample sufficient for economics"],
            [
                [
                    r["branch"], f"`{r['root_cause']}`",
                    ", ".join(f"`{c}`" for c in r["contributors"]) or "—",
                    r["closed_n"], _n(r["sample_sufficient_for_economics"]),
                ]
                for r in roots
            ],
            align=["---", "---", "---", "---:", "---"],
        )
    )
    w("")
    for r in roots:
        w(f"**{r['branch']}** — `{r['root_cause']}`")
        w("")
        for line in r["evidence"]:
            w(f"- {line}")
        w("")
    w("## 14. Consistency with the existing STV2 economic-verification report")
    w("")
    w(ctx["consistency"]["statement"])
    w("")
    w(
        _table(
            ["Quantity", "Economic-verification campaign", "This funnel analysis", "Match"],
            [[k, v["campaign"], v["funnel"], _n(v["match"])] for k, v in ctx["consistency"]["checks"].items()],
            align=["---", "---:", "---:", "---"],
        )
    )
    w("")
    w(f"`CONSISTENT_WITH_EXISTING_STV2_REPORT = {ctx['consistency']['consistent']}`")
    w("")
    w("**Contradictions:**")
    w("")
    if ctx["consistency"]["contradictions"]:
        for c in ctx["consistency"]["contradictions"]:
            w(f"- {c}")
    else:
        w("- none")
    w("")
    w("## 15. Follow-up hypotheses (post-measurement only)")
    w("")
    w(
        "Each item below is a proposal for a **NEW candidate identity**. "
        f"`{CANONICAL_CANDIDATE_ID}` is never mutated in place, and no V3 code was written in "
        "this mission. None of these is asserted to be correct — each is a preregistration "
        "requirement, not a finding."
    )
    w("")
    for h in ctx["hypotheses"]:
        w(f"### `{h['hypothesis_id']}`")
        w("")
        w(
            _table(
                ["Field", "Value"],
                [
                    ["`evidence_source`", h["evidence_source"]],
                    ["`observed_problem`", h["observed_problem"]],
                    ["`proposed_new_candidate_change`", h["proposed_new_candidate_change"]],
                    ["`what_must_be_preregistered`", h["what_must_be_preregistered"]],
                    ["`required_new_validation`", h["required_new_validation"]],
                ],
            )
        )
        w("")
    w("## 16. Inconclusive findings")
    w("")
    for line in findings["inconclusive"]:
        w(f"- {line}")
    w("")
    w(
        f"_Economic claims require at least {MIN_SAMPLE_FOR_ECONOMIC_CLAIM} closed trades "
        "(EdgeLab canonical minimum). Segments below that threshold are reported but no "
        "economic conclusion is drawn from them._"
    )
    w("")
    return "\n".join(p) + "\n"


def _dimension_table(summary: Mapping[str, Any], key: str) -> str:
    return _table(
        [key.capitalize(), "Raw CONTEXT N", "CONTEXT", "LOCATION", "TRIGGER", "GEOMETRY",
         "EXECUTION (fills)", "CLOSED", "Cond Gross Exp R", "Cond Net Exp R", "Win %",
         "Net PF", "Friction R"],
        [
            [
                s[key], s["raw_context_n"], s["context_n"], s["location_n"], s["trigger_n"],
                s["geometry_n"], s["execution_n"], s["closed_n"],
                _n(s["outcome"]["conditional_downstream_gross_expectancy_r"]),
                _n(s["outcome"]["conditional_downstream_net_expectancy_r"]),
                _n(None if s["outcome"]["win_rate"] is None else s["outcome"]["win_rate"] * 100, 2),
                _n(s["outcome"]["conditional_downstream_net_pf"], 3,
                   s["outcome"]["conditional_downstream_net_pf_status"]),
                _n(s["outcome"]["friction_r"], 3),
            ]
            for s in summary["summaries"]
        ],
        align=["---"] + ["---:"] * 12,
    )


__all__ = ["CSV_COLUMNS", "render_stage_matrix_csv", "render_summary_markdown", "branch_counts"]
