"""Universal Funnel V0.3 — REAL FX DEV campaign runner.

Verifies the pinned HistData 2017 identities (fail-closed), builds every
timeframe from the single normalized M1 lineage, runs the preregistered
direction-first funnel on the DEVELOPMENT partition for EURUSD / GBPUSD /
USDJPY / XAUUSD, and emits the 16 mission artifacts under
``data/artifacts/universal_price_action_v0_3_fx_dev/``.

Capability diagnosis only: no strategy change, no economics, no OOS, no
holdout, no execution. Deterministic end to end.

Usage:
    PYTHONPATH=src python scripts/run_universal_fx_dev_v0_3.py [zip_dir]
    (zip_dir defaults to data/external/histdata_fx_2017; run
     scripts/acquire_histdata_fx_2017.sh first)
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.data.fingerprint import sha256_json  # noqa: E402
from ag_edgelab.data.fx_histdata_2017 import (  # noqa: E402
    BlockedDataAuthority, MTF_COVERAGE_FRACTION, MTF_TIMEFRAMES, PARTITIONS,
    PINNED_SOURCE_SHA256, SYMBOLS, aggregate_m15, derive_fx_timeframe,
    load_histdata_m1, quality_gate_m1, slice_partition, verify_source_identity)
from ag_edgelab.universal.fx_direction import (  # noqa: E402
    DIRECTION_HYPOTHESES, FX_DIRECTION_REGISTRY_SHA256, PRIMARY_FUNNEL_HYPOTHESIS)
from ag_edgelab.universal import fx_dev_campaign as camp  # noqa: E402
from ag_edgelab.universal.fx_dev_campaign import (  # noqa: E402
    FUNNEL_STAGES, build_funnel, build_series, confirmation_value, context_at,
    decisions_from_truncated_frames, fx_root_cause, hypothesis_comparison,
    reach_share, required_comparisons, run_fx_symbol_campaign, target_lab,
    _decided_mfe)
from ag_edgelab.universal.direction import Direction  # noqa: E402
from ag_edgelab.universal.fx_direction import evaluate_direction_hypotheses  # noqa: E402
from ag_edgelab.contracts.market import MarketBar  # noqa: E402

OUT_DIR = ROOT / "data" / "artifacts" / "universal_price_action_v0_3_fx_dev"
DATASET_ROLE = "DEVELOPMENT"
AUDIT_SAMPLES_PER_SYMBOL = 4


def write(name: str, payload) -> None:
    path = OUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT)}")


def mutate_future(bars, timeframe: str, as_of):
    """Scale OHLC of every bar NOT closed at `as_of` by 1.1 (future mutation)."""
    from ag_edgelab.data.derive import TIMEFRAME_MINUTES
    span = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
    out = []
    for b in bars:
        if b.timestamp + span <= as_of:
            out.append(b)
        else:
            out.append(MarketBar(timestamp=b.timestamp, open=b.open * 1.1,
                                 high=b.high * 1.1, low=b.low * 1.1, close=b.close * 1.1))
    return tuple(out)


def decisions_from_full_frames(frames, as_of, price):
    """Decisions read from series built over FULL frames at the closed cuts."""
    from ag_edgelab.data.derive import TIMEFRAME_MINUTES
    bundle = build_series(frames)
    cuts = {}
    for tf in ("H1", "H4", "D1"):
        span = timedelta(minutes=TIMEFRAME_MINUTES[tf])
        idx = -1
        for i, b in enumerate(frames[tf]):
            if b.timestamp + span <= as_of:
                idx = i
            else:
                break
        cuts[tf] = idx
    ctx, _ = context_at(bundle, cuts["D1"], cuts["H4"], cuts["H1"], price)
    return {k: v.value for k, v in evaluate_direction_hypotheses(ctx).items()}


def main() -> int:
    zip_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "external" / "histdata_fx_2017"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dev_start, dev_end = PARTITIONS[DATASET_ROLE]

    manifest_symbols = {}
    lineage_doc = {}
    audit_doc = {"invariants": [
        "decision at T uses only bars fully closed at T (open + span <= T)",
        "truncating all frames at T leaves every decision unchanged",
        "mutating bars not closed at T (OHLC x1.1) leaves every decision unchanged",
    ], "samples": []}
    campaigns = {}
    all_observations = []
    pooled_raw = 0

    # ---------------- dataset authority + frames + campaign per symbol ------
    for symbol in SYMBOLS:
        zip_path = zip_dir / f"HISTDATA_COM_ASCII_{symbol}_M1_2017.zip"
        if not zip_path.is_file():
            print(f"BLOCKED_DATA_AUTHORITY: missing {zip_path}", file=sys.stderr)
            print("run scripts/acquire_histdata_fx_2017.sh first", file=sys.stderr)
            return 2
        try:
            source_sha = verify_source_identity(zip_path, symbol)
        except BlockedDataAuthority as exc:
            print(f"BLOCKED_DATA_AUTHORITY: {exc}", file=sys.stderr)
            return 2
        print(f"[{symbol}] identity verified {source_sha[:16]}…")

        m1 = load_histdata_m1(zip_path)
        quality = quality_gate_m1(m1, symbol)
        m1_dev = slice_partition(m1, DATASET_ROLE)          # holdout fails closed
        m15 = aggregate_m15(m1_dev)
        frames = {"M15": m15}
        lineages = []
        for tf in MTF_TIMEFRAMES:
            frames[tf], lineage = derive_fx_timeframe(m15, tf, symbol)
            lineages.append(lineage)

        manifest_symbols[symbol] = {
            "source_file": zip_path.name,
            "source_sha256": source_sha,
            "pinned_sha256": PINNED_SOURCE_SHA256[symbol],
            "identity_verified": True,
            "m1_rows_full_2017": len(m1),
            "m1_rows_development": len(m1_dev),
            "m15_bars_development": len(m15),
            "quality": quality,
            "timezone_rule": "source wall-clock America/New_York (DST) -> UTC before any logic",
            "partition": {"role": DATASET_ROLE,
                          "start": dev_start.isoformat(), "end": dev_end.isoformat()},
            "oos_opened": False, "holdout_touched": False,
        }
        lineage_doc[symbol] = {
            "statement": "M15/H1/H4/D1 all derived from ONE normalized M1 feed; "
                         "no independent higher-timeframe provider",
            "m15_rule": ">= 13/15 M1 minutes per bucket; missing bars never filled",
            "coverage_fraction": MTF_COVERAGE_FRACTION,
            "derived": [{
                "timeframe": ln.output_timeframe, "rows": ln.rows,
                "coverage_rule": ln.coverage_rule,
                "source_hash": ln.source_hash, "output_hash": ln.output_hash,
            } for ln in lineages],
        }

        result = run_fx_symbol_campaign(frames, symbol, dev_start, dev_end)
        campaigns[symbol] = result
        all_observations.extend(result.observations)
        pooled_raw += result.raw_observations
        print(f"[{symbol}] raw={result.raw_observations} decided={len(result.observations)} "
              f"entered={sum(1 for o in result.observations if o.entered)}")

        # ---- causality audit on real data -------------------------------
        obs_list = result.observations
        step = max(1, len(obs_list) // (AUDIT_SAMPLES_PER_SYMBOL + 1))
        for obs in obs_list[step::step][:AUDIT_SAMPLES_PER_SYMBOL]:
            truncated = decisions_from_truncated_frames(frames, obs.observed_at, obs.price)
            mutated_frames = {"M15": m15}
            for tf in MTF_TIMEFRAMES:
                mutated_frames[tf] = mutate_future(frames[tf], tf, obs.observed_at)
            mutated = decisions_from_full_frames(mutated_frames, obs.observed_at, obs.price)
            audit_doc["samples"].append({
                "symbol": symbol, "observed_at": obs.observed_at.isoformat(),
                "campaign_decisions": obs.directions,
                "truncation_invariant": truncated == obs.directions,
                "future_mutation_invariant": mutated == obs.directions,
            })

    audit_doc["all_passed"] = all(
        s["truncation_invariant"] and s["future_mutation_invariant"]
        for s in audit_doc["samples"])
    if not audit_doc["all_passed"]:
        print("CAUSALITY AUDIT FAILED", file=sys.stderr)
        write("causality_audit.json", audit_doc)
        return 3

    # ---------------- aggregation: per symbol AND pooled ---------------------
    per_symbol_obs = {s: campaigns[s].observations for s in SYMBOLS}
    pooled_obs = tuple(all_observations)

    def scoped(fn):
        return {**{s: fn(per_symbol_obs[s]) for s in SYMBOLS}, "POOLED": fn(pooled_obs)}

    direction_population = scoped(lambda obs: {
        hyp: {d: sum(1 for o in obs if o.directions.get(hyp) == d)
              for d in ("BULL", "BEAR", "NEUTRAL")}
        for hyp in DIRECTION_HYPOTHESES})
    comparison = scoped(hypothesis_comparison)
    comparisons15 = scoped(required_comparisons)
    conf_value = scoped(confirmation_value)
    targets = scoped(target_lab)

    pooled_cmp = comparison["POOLED"]
    eligible = {h: v for h, v in pooled_cmp.items()
                if v["sample_sufficient"] and v["separation_pp"] is not None}
    best_hyp = max(eligible, key=lambda h: eligible[h]["separation_pp"]) if eligible else None
    best_reason = (f"highest pooled separation {eligible[best_hyp]['separation_pp']}pp over "
                   f"{eligible[best_hyp]['n_bull'] + eligible[best_hyp]['n_bear']} directional "
                   "observations (shared diagnostic basis)") if best_hyp else "no eligible hypothesis"

    funnels = {s: list(campaigns[s].funnel) for s in SYMBOLS}
    pooled_funnel = list(build_funnel(pooled_obs, pooled_raw))

    # trigger x location x confirmation matrix (opportunity basis per cell)
    def matrix(obs):
        rows = []
        for direction in ("BULL", "BEAR"):
            for loc in ("ALIGNED", "MISMATCH_RECORDED", "UNAVAILABLE"):
                for conf in ("ALIGNED", "COUNTER_DIRECTION", "NONE"):
                    cell = [o for o in obs if o.primary_direction == direction
                            and o.location_state == loc
                            and (o.confirmation_alignment or "NONE") == conf]
                    rows.append({
                        "direction": direction, "location": loc, "confirmation": conf,
                        "n": len(cell),
                        "capability": reach_share(
                            [_decided_mfe(o, o.primary_direction) for o in cell]),
                    })
        return rows

    # location funnel detail
    def location_detail(obs):
        directional = [o for o in obs if o.primary_direction != "NEUTRAL"]
        states = {}
        for state in ("ALIGNED", "MISMATCH_RECORDED", "UNAVAILABLE"):
            group = [o for o in directional if o.location_state == state]
            states[state] = {
                "n": len(group),
                "capability": reach_share(
                    [_decided_mfe(o, o.primary_direction) for o in group]),
            }
        families = {}
        for o in directional:
            for fam in o.location_families_hit:
                families[fam] = families.get(fam, 0) + 1
        return {"direction_n": len(directional), "states": states,
                "families_hit": families,
                "midrange_policy": "MISMATCH_RECORDED observations are recorded, never dropped"}

    def confirmation_detail(obs):
        aligned_loc = [o for o in obs if o.location_state == "ALIGNED"]
        primitives = {}
        for o in aligned_loc:
            if o.confirmation_primitive:
                key = f"{o.confirmation_primitive}:{o.confirmation_alignment}"
                primitives[key] = primitives.get(key, 0) + 1
        candles = {}
        for o in aligned_loc:
            for c in o.candle_primitives_in_window:
                candles[c] = candles.get(c, 0) + 1
        return {"location_aligned_n": len(aligned_loc),
                "first_structure_event": primitives,
                "candle_primitives_present_in_window": candles,
                "value_analysis": confirmation_value(obs)}

    root_cause = {s: fx_root_cause(per_symbol_obs[s], comparison[s], conf_value[s], targets[s])
                  for s in SYMBOLS}
    root_cause["POOLED"] = fx_root_cause(pooled_obs, pooled_cmp, conf_value["POOLED"],
                                         targets["POOLED"])
    pooled_rc = root_cause["POOLED"]
    pooled_targets = targets["POOLED"]
    pooled_conf = conf_value["POOLED"]
    pooled_cmp15 = comparisons15["POOLED"]

    sep = pooled_cmp[PRIMARY_FUNNEL_HYPOTHESIS]["separation_pp"]
    loc_cap = pooled_conf["opportunity_capability_location_aligned"]
    dir_cap = pooled_cmp[PRIMARY_FUNNEL_HYPOTHESIS]["capability_decided_direction"]
    location_adds = None
    if loc_cap is not None and dir_cap is not None:
        location_adds = "YES" if loc_cap > dir_cap else "NO"
    conf_uplift = pooled_conf["uplift_pp_same_basis"]
    confirmation_adds = None if conf_uplift is None else ("YES" if conf_uplift > 0 else "NO")

    status = "FX_DEV_FUNNEL_COMPLETE" if pooled_rc["case"] != "INSUFFICIENT" \
        else "INSUFFICIENT_EVIDENCE"

    final = {
        "mission": "UNIVERSAL FUNNEL V0.3 REAL FX DEV CAMPAIGN",
        "engine": {"funnel_engine_sha": "2ae7474bd5dff5a6eea9fdf9cfdcfc7381692789",
                   "engines_modified": False,
                   "fx_direction_registry_sha256": FX_DIRECTION_REGISTRY_SHA256},
        "dataset": {"authority": "HISTDATA_ASCII_M1_2017_PR10_PINNED",
                    "role": DATASET_ROLE, "hashes_verified": True,
                    "symbols": {s: manifest_symbols[s]["source_sha256"] for s in SYMBOLS}},
        "observations": {f"{s}_N": campaigns[s].raw_observations for s in SYMBOLS},
        "primary_funnel_hypothesis": PRIMARY_FUNNEL_HYPOTHESIS,
        "best_direction_hypothesis": best_hyp,
        "best_direction_hypothesis_reason": best_reason,
        "direction_separation_pp": sep,
        "direction_separation": "YES" if (sep is not None and sep >= camp.MIN_SEPARATION_PP) else "NO",
        "location_adds_value": location_adds,
        "confirmation_adds_value_same_basis": confirmation_adds,
        "confirmation_uplift_pp_same_basis": conf_uplift,
        "entry_conditioned_uplift": None,
        "entry_conditioned_uplift_reason": "INCOMPARABLE_CAPABILITY_SEMANTICS",
        "fixed_reach_pooled": pooled_targets["fixed_reach"],
        "continuation_survival_pooled": pooled_targets["continuation_survival"],
        "natural_target_pooled": {
            "median_r": pooled_targets["natural_target_median_r"],
            "p25_r": pooled_targets["natural_target_p25_r"],
            "p75_r": pooled_targets["natural_target_p75_r"]},
        "asian_v2_status": "NOT_RUN_AUTHORITATIVE_STRATEGY_LINEAGE_UNAVAILABLE",
        "asian_v2_discovery_note": (
            "No strategy named ST_ASIAN_SESSION_BRANCH_V2 exists in any branch. Closest "
            "unconfirmed candidate: SESSION_TRADE_V2 @2.0.0 on PR #10 branch "
            "(arena/01a100ce-ag-edgelab), self-declared as a DISTINCT authority "
            "(status RESEARCH_SHADOW, unmerged) with DEV ledger "
            "artifacts/session_trade_v2_economic_matrix/ledger.jsonl. Owner confirmation "
            "required before any overlay."),
        "root_cause": pooled_rc,
        "root_cause_per_symbol": {s: root_cause[s]["primary"] for s in SYMBOLS},
        "comparisons": pooled_cmp15,
        "guards": {"strategy_rules_changed": False, "realized_economics_run": False,
                   "oos_opened": False, "holdout_touched": False,
                   "execution_capability_added": False},
        "status": status,
    }
    final["final_report_sha256"] = sha256_json(final)

    print("\nartifacts:")
    write("dataset_manifest.json", {"role": DATASET_ROLE, "symbols": manifest_symbols,
                                    "partitions": {k: [v[0].isoformat(), v[1].isoformat()]
                                                   for k, v in PARTITIONS.items()},
                                    "holdout_policy": "SEALED_HOLDOUT fails closed"})
    write("mtf_lineage.json", lineage_doc)
    write("causality_audit.json", audit_doc)
    write("direction_population.json", direction_population)
    write("direction_hypothesis_comparison.json", {
        "registry": DIRECTION_HYPOTHESES,
        "registry_sha256": FX_DIRECTION_REGISTRY_SHA256,
        "primary_funnel_hypothesis": PRIMARY_FUNNEL_HYPOTHESIS,
        "best_direction_hypothesis": best_hyp,
        "best_direction_hypothesis_reason": best_reason,
        "results": comparison})
    write("location_funnel.json", scoped(location_detail))
    write("confirmation_funnel.json", scoped(confirmation_detail))
    write("trigger_location_confirmation_matrix.json", scoped(matrix))
    write("target_capability.json", targets)
    write("continuation_survival.json", scoped(
        lambda obs: target_lab(obs)["continuation_survival"]))
    write("natural_target_geometry.json", scoped(lambda obs: {
        k: target_lab(obs)[k] for k in ("natural_target_n", "natural_target_median_r",
                                        "natural_target_p25_r", "natural_target_p75_r",
                                        "natural_families")}))
    write("per_symbol_funnel.json", funnels)
    write("pooled_funnel.json", {"stages": pooled_funnel,
                                 "note": "pooled across EURUSD/GBPUSD/USDJPY/XAUUSD; "
                                         "per-symbol funnels in per_symbol_funnel.json"})
    write("root_cause_analysis.json", {"precedence": ["A", "B", "C", "D", "E"],
                                       "results": root_cause})
    write("final_report.json", final)

    md = ["# Universal Funnel V0.3 — Real FX DEV Campaign", "",
          f"STATUS: **{final['status']}** · dataset role: DEVELOPMENT · hashes verified: YES", "",
          "## Pooled funnel", "", "| stage | n | % of previous |", "|---|---|---|"]
    for row in pooled_funnel:
        md.append(f"| {row['stage']} | {row['n']} | {row['pct_of_previous']} |")
    md += ["", "## Direction hypotheses (pooled)", "",
           "| hyp | bull | bear | neutral | decided cap | opposite cap | sep (pp) |",
           "|---|---|---|---|---|---|---|"]
    for hyp, v in pooled_cmp.items():
        md.append(f"| {hyp} | {v['n_bull']} | {v['n_bear']} | {v['n_neutral']} | "
                  f"{v['capability_decided_direction']} | {v['capability_opposite_direction']} | "
                  f"{v['separation_pp']} |")
    md += ["", f"Primary (preregistered) hypothesis: **{PRIMARY_FUNNEL_HYPOTHESIS}**; "
               f"best by separation: **{best_hyp}** — {best_reason}", "",
           "## Root cause (pooled, precedence A→E)", "",
           f"- CASE: **{pooled_rc['case']}** — {pooled_rc['primary']}",
           f"- NEXT_FUNNEL_TO_CHANGE: **{pooled_rc['next_funnel_to_change']}**",
           f"- {pooled_rc['rationale']}", "",
           "## Guards", "",
           "strategy rules changed: NO · economics run: NO · OOS opened: NO · "
           "holdout touched: NO · execution added: NO · Asian V2: NOT_RUN "
           "(authoritative lineage unavailable)", ""]
    (OUT_DIR / "final_report.md").write_text("\n".join(md), encoding="utf-8")
    print(f"  wrote {(OUT_DIR / 'final_report.md').relative_to(ROOT)}")

    print(f"\nSTATUS={final['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
