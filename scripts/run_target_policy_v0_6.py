"""Universal Funnel V0.6 — NATURAL TARGET + RUNNER POLICY RESEARCH runner.

Phase order (fail-closed):
  0. V0.5 authority resolution from repository history (two historical result
     sets; the later formal-spec run must demonstrably supersede) else
     BLOCKED_V0_5_AUTHORITY_AMBIGUOUS;
  1. exact reproduction of the authoritative V0.5 pinned values else
     BLOCKED_V0_5_REPRODUCTION;
  2+ preregistered policy grid evaluated pathwise on the SAME entry ids;
     economics fail-closed (exit contract + friction authority incomplete);
     double-run determinism; causality audit.

No SL/entry/trigger/location/confirmation change. No OOS. No V0.7.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.contracts.market import MarketBar  # noqa: E402
from ag_edgelab.data.derive import TIMEFRAME_MINUTES  # noqa: E402
from ag_edgelab.data.fingerprint import sha256_json  # noqa: E402
from ag_edgelab.data.fx_histdata_2017 import (  # noqa: E402
    BlockedDataAuthority, MTF_TIMEFRAMES, PARTITIONS, PINNED_SOURCE_SHA256, SYMBOLS,
    aggregate_m15, bars_closed_at, derive_fx_timeframe, load_histdata_m1,
    quality_gate_m1, slice_partition, verify_source_identity)
from ag_edgelab.universal.fx_dev_campaign import run_fx_symbol_campaign  # noqa: E402
from ag_edgelab.universal.targets import EntryGeometry  # noqa: E402
from ag_edgelab.universal.direction import Direction  # noqa: E402
from ag_edgelab.universal.trigger_v0_4 import enrich_symbol  # noqa: E402
from ag_edgelab.universal import target_v0_5 as tv5  # noqa: E402
from ag_edgelab.universal import target_policy_v0_6 as tp6  # noqa: E402
from ag_edgelab.universal.target_policy_v0_6 import (  # noqa: E402
    AUTHORITATIVE_V0_5_SHA, AUTHORITATIVE_V0_5_TREE, CONTROL_IDS, EXPERIMENT_ID,
    EXPERIMENT_VERSION, FOCAL_CONTROLS, FRACTIONS, POLICY_CONTRACTS, POLICY_IDS,
    SUPERSEDED_V0_5_SHA, TARGET_POLICY_REGISTRY_SHA256, build_policy_entries,
    decision, entry_policy_rows, evaluate_all, objective_sequence_rows,
    paired_delta, pathwise_comparison, policy_summary, quartile_analysis,
    runner_report, session_stratification)

OUT_DIR = ROOT / "data" / "artifacts" / "universal_funnel_v0_6_target_policy"
DATASET_ROLE = "DEVELOPMENT"
AUDIT_SAMPLES_PER_SYMBOL = 4

V05_PINNED = {
    "D01_ENTRY_N": 3183, "T1_ENTRY_N": 379,
    "D01_PRIMARY": {"P25": 0.150, "P50": 0.402, "P75": 0.891},
    "T1_PRIMARY": {"P25": 0.140, "P50": 0.377, "P75": 0.849},
    "D01_FURTHEST_P50": 2.737, "T1_FURTHEST_P50": 2.967,
    "D01_FIRST_OBJECTIVE_PCT": 67.55, "T1_FIRST_OBJECTIVE_PCT": 68.60,
    "D01_SECOND_OBJECTIVE_PCT": 43.34, "T1_SECOND_OBJECTIVE_PCT": 37.64,
    "D01_GE5R_AVAILABLE_PCT": 24.91, "T1_GE5R_AVAILABLE_PCT": 22.96,
    "D01_5R_REACH_WHEN_AVAILABLE_PCT": 6.06, "T1_5R_REACH_WHEN_AVAILABLE_PCT": 3.45,
}

PREREGISTRATION = {
    "experiment_id": EXPERIMENT_ID, "version": EXPERIMENT_VERSION,
    "authoritative_v0_5_sha": AUTHORITATIVE_V0_5_SHA,
    "superseded_v0_5_sha": SUPERSEDED_V0_5_SHA,
    "registered_before_results": True,
    "objective": "does a causal natural-target (+ runner) exit policy improve "
                 "structural target delivery vs the frozen fixed-R ladder on "
                 "the SAME entries? DEVELOPMENT research only; no promotion",
    "frozen_upstream": ["direction", "location", "confirmation", "entry", "SL",
                        "sessions", "dataset", "fill semantics",
                        "V0.5 causal target contracts"],
    "populations": {"D01": "control population", "T1": "research treatment; "
                    "never assumed superior; never pooled for selection"},
    "policy_contracts": POLICY_CONTRACTS,
    "policy_ids": POLICY_IDS,
    "fraction_grid_rule": "25/75, 50/50, 75/25 sensitivity grid only; no "
                          "best percentage may be promoted from DEV",
    "pathwise_rule": "all policy comparisons are paired on the SAME entry "
                     "ids, both outcomes resolved; different-population exit "
                     "inference is forbidden",
    "focal_controls_for_pairing": FOCAL_CONTROLS,
    "best_policy_rule": "BEST_STRUCTURAL_POLICY = highest mean paired delta "
                        "vs C0_2R with >= 100 pairs; descriptive only; "
                        "partial fraction never promoted",
    "economics_gate": "realized economics ONLY if EXIT_CONTRACT_COMPLETE and "
                      "FRICTION_AUTHORITY_COMPLETE; both fail closed here",
    "decision_rules": {
        "A": "FIXED_TARGET_MODEL_INFERIOR: C1 or a runner family (all "
             "fractions, R0) beats every C0_k pairwise (mean delta > 0, "
             ">= 100 pairs)",
        "B": "NATURAL_SINGLE_TARGET_SUPPORTED: C1 beats every C0_k",
        "C": "NATURAL_TARGET_PLUS_RUNNER_SUPPORTED: some runner family R0 "
             "beats every C0_k AND C1 across ALL fractions",
        "D": "RUNNER_CONTINUATION_TOO_WEAK: P(2nd|1st) < 0.35 OR no runner "
             "policy beats C1 on any fraction",
        "E": "TARGET_POLICY_DEPENDS_ON_SL_GEOMETRY: every pooled positive "
             "paired advantage is confined to risk quartiles Q1/Q2",
        "F": "T1_DIRECTION_FILTER_HARMS_RUNNER_CONTINUATION: D01 P(2nd|1st) "
             "exceeds T1's by >= 5pp (evaluated for T1)",
        "G": "INSUFFICIENT_EVIDENCE: population or pair floors unmet",
        "primary_precedence": ["C", "B", "D", "F", "E", "else G"],
        "freeze_rule": "if D01 primary is C -> freeze the qualifying runner "
                       "family contract (fraction grid intact, no selection); "
                       "if B -> freeze C1 contract; else NO_FREEZE; frozen "
                       "contract is hashed for a FUTURE OOS mission only",
    },
    "v0_5_pinned_reproduction_targets": V05_PINNED,
    "registry_sha256": TARGET_POLICY_REGISTRY_SHA256,
    "forbidden": ["SL change", "entry/trigger/location/confirmation change",
                  "partial-percentage optimization", "policy promotion",
                  "EDGE_VERIFIED claims", "OOS/holdout", "V0.7", "auto-merge"],
}
PREREGISTRATION["experiment_hash"] = sha256_json(PREREGISTRATION)


def write(name: str, payload) -> None:
    path = OUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT)}")


def write_jsonl(name: str, rows) -> None:
    path = OUT_DIR / name
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    print(f"  wrote {path.relative_to(ROOT)} ({len(rows)} rows)")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


# ---------------------------------------------------------------- PHASE 0

def resolve_v0_5_authority() -> tuple[bool, dict]:
    a, b = SUPERSEDED_V0_5_SHA, AUTHORITATIVE_V0_5_SHA
    art = "data/artifacts/universal_funnel_v0_5_target"
    res = {"candidate_a_sha": a, "candidate_b_sha": b}
    try:
        prereg_a = json.loads(_git("show", f"{a}:{art}/preregistration.json"))
        prereg_b = json.loads(_git("show", f"{b}:{art}/preregistration.json"))
        res["contract_a_hash"] = prereg_a["experiment_hash"]
        res["contract_b_hash"] = prereg_b["experiment_hash"]
        res["contract_a_version"] = prereg_a["version"]
        res["contract_b_version"] = prereg_b["version"]
        files_a = _git("ls-tree", "--name-only", a, f"{art}/").splitlines()
        files_b = _git("ls-tree", "--name-only", b, f"{art}/").splitlines()
        res["artifact_set_a"] = sorted(Path(p).name for p in files_a)
        res["artifact_set_b"] = sorted(Path(p).name for p in files_b)
        ancestry = subprocess.run(
            ["git", "merge-base", "--is-ancestor", a, b], cwd=ROOT).returncode == 0
        subject_b = _git("log", "-1", "--format=%s", b)
        tree_b = _git("rev-parse", f"{b}^{{tree}}")
        res["supersession_evidence"] = {
            "b_descends_from_a": ancestry,
            "b_commit_subject": subject_b,
            "b_subject_declares_formal_mission_spec":
                "formal mission spec" in subject_b,
            "contract_versions": f"{prereg_a['version']} -> {prereg_b['version']}",
            "b_preregistration_supersedes_amendment":
                prereg_b["version"] > prereg_a["version"],
            "artifact_sets_disjointly_specified":
                res["artifact_set_a"] != res["artifact_set_b"],
            "b_artifact_set_matches_formal_spec_19": sorted(
                ["preregistration.json", "parent_reproduction.json",
                 "dataset_manifest.json", "target_family_contracts.json",
                 "target_candidate_ledger.jsonl", "target_ladders.jsonl",
                 "target_geometry_distribution.json", "target_delivery.json",
                 "multi_objective_delivery.json", "fixed_vs_natural.json",
                 "stop_target_geometry.json", "d01_target_report.json",
                 "t1_target_report.json", "d01_vs_t1_target_comparison.json",
                 "per_symbol_target_report.json", "causality_audit.json",
                 "determinism_report.json", "root_cause_analysis.json",
                 "final_report.json", "final_report.md",
                 "artifact_manifest.json"]
            ) == sorted(n for n in res["artifact_set_b"]
                        if n != "test_results.txt"),
            "statistics_never_combined_across_runs": True,
        }
        ok = (ancestry
              and res["supersession_evidence"]["b_subject_declares_formal_mission_spec"]
              and res["supersession_evidence"]["b_preregistration_supersedes_amendment"]
              and res["supersession_evidence"]["b_artifact_set_matches_formal_spec_19"]
              and tree_b == AUTHORITATIVE_V0_5_TREE)
        res["head_contains_authoritative"] = subprocess.run(
            ["git", "merge-base", "--is-ancestor", b, "HEAD"],
            cwd=ROOT).returncode == 0
        ok = ok and res["head_contains_authoritative"]
    except subprocess.CalledProcessError as exc:
        res["error"] = str(exc)
        ok = False
    if ok:
        res["V0_5_AUTHORITY"] = b
        res["SUPERSEDES"] = a
        res["AUTHORITATIVE_V0_5_SHA"] = b
        res["AUTHORITATIVE_V0_5_TREE"] = AUTHORITATIVE_V0_5_TREE
        res["AUTHORITATIVE_CONTRACT_HASH"] = res["contract_b_hash"]
    return ok, res


# ---------------------------------------------------------------- PHASE 1

def check_v0_5_reproduction(records) -> tuple[bool, dict]:
    d01 = list(records)
    t1 = [r for r in records if r.is_t1]
    checks = {}

    def add(name, got, want):
        checks[name] = {"computed": got, "pinned": want, "match": got == want}

    rep = {p: tv5.population_target_report(rows)
           for p, rows in (("D01", d01), ("T1", t1))}
    add("D01_ENTRY_N", len(d01), V05_PINNED["D01_ENTRY_N"])
    add("T1_ENTRY_N", len(t1), V05_PINNED["T1_ENTRY_N"])
    for p in ("D01", "T1"):
        pq = rep[p]["primary_target_r_quantiles"]
        for q in ("P25", "P50", "P75"):
            add(f"{p}_PRIMARY_{q}", round(pq[q], 3), V05_PINNED[f"{p}_PRIMARY"][q])
        add(f"{p}_FURTHEST_P50",
            round(rep[p]["furthest_target_r_quantiles"]["P50"], 3),
            V05_PINNED[f"{p}_FURTHEST_P50"])
        mo = rep[p]["multi_objective_delivery"]
        add(f"{p}_FIRST_OBJECTIVE_PCT",
            round(mo["FIRST_OBJECTIVE_REACHED_PCT"] * 100, 2),
            V05_PINNED[f"{p}_FIRST_OBJECTIVE_PCT"])
        add(f"{p}_SECOND_OBJECTIVE_PCT",
            round(mo["SECOND_OBJECTIVE_REACHED_PCT"] * 100, 2),
            V05_PINNED[f"{p}_SECOND_OBJECTIVE_PCT"])
        lv5 = rep[p]["ladder_levels"]["5R"]
        add(f"{p}_GE5R_AVAILABLE_PCT",
            round(lv5["OBJECTIVE_AVAILABLE_PCT"] * 100, 2),
            V05_PINNED[f"{p}_GE5R_AVAILABLE_PCT"])
        add(f"{p}_5R_REACH_WHEN_AVAILABLE_PCT",
            round(lv5["OBJECTIVE_REACHED_WHEN_AVAILABLE_PCT"] * 100, 2),
            V05_PINNED[f"{p}_5R_REACH_WHEN_AVAILABLE_PCT"])
    return all(v["match"] for v in checks.values()), checks


# ---------------------------------------------------------------- compute

def compute(zip_dir: Path) -> dict:
    dev_start, dev_end = PARTITIONS[DATASET_ROLE]
    policy_entries = []
    dataset = {}
    frames_by_symbol = {}
    records_all = []
    for symbol in SYMBOLS:
        zip_path = zip_dir / f"HISTDATA_COM_ASCII_{symbol}_M1_2017.zip"
        source_sha = verify_source_identity(zip_path, symbol)
        m1 = load_histdata_m1(zip_path)
        quality_gate_m1(m1, symbol)
        m15 = aggregate_m15(slice_partition(m1, DATASET_ROLE))
        frames = {"M15": m15}
        for tf in MTF_TIMEFRAMES:
            frames[tf], _ = derive_fx_timeframe(m15, tf, symbol)
        campaign = run_fx_symbol_campaign(frames, symbol, dev_start, dev_end)
        enriched = enrich_symbol(frames, campaign, dev_start, dev_end)
        records = tv5.build_entry_records(frames, campaign, enriched)
        records_all.extend(records)
        policy_entries.extend(build_policy_entries(frames, records))
        frames_by_symbol[symbol] = frames
        dataset[symbol] = {"source_sha256": source_sha,
                           "pinned_sha256": PINNED_SOURCE_SHA256[symbol],
                           "identity_verified": True,
                           "entries": len(records)}
    return {"entries": tuple(policy_entries), "records": tuple(records_all),
            "dataset": dataset, "frames_by_symbol": frames_by_symbol}


def aggregate(entries) -> dict:
    pops = {"D01": list(entries),
            "T1": [pe for pe in entries if pe.base.is_t1]}
    outcomes = {p: evaluate_all(rows) for p, rows in pops.items()}
    summaries = {p: policy_summary(rows, outcomes[p]) for p, rows in pops.items()}
    pathwise = {p: pathwise_comparison(rows, outcomes[p])
                for p, rows in pops.items()}
    runners = {p: runner_report(rows) for p, rows in pops.items()}
    quart = {p: quartile_analysis(rows, outcomes[p]) for p, rows in pops.items()}
    sessions = {p: session_stratification(rows, outcomes[p])
                for p, rows in pops.items()}
    p21 = {p: runners[p]["P_SECOND_GIVEN_FIRST"] for p in pops}
    decisions = {
        "D01": decision(pops["D01"], outcomes["D01"], runners["D01"],
                        quart["D01"], other_population_p21=None,
                        own_p21=p21["D01"]),
        "T1": decision(pops["T1"], outcomes["T1"], runners["T1"], quart["T1"],
                       other_population_p21=p21["D01"], own_p21=p21["T1"]),
    }

    def best_policy(p):
        rows_, out_ = pops[p], outcomes[p]
        best = None
        for pid in POLICY_IDS:
            if pid.startswith("C0_"):
                continue
            d = paired_delta(rows_, out_, pid, "C0_2R")
            if d["meets_pair_floor"] and d["mean_delta_r"] is not None:
                if best is None or d["mean_delta_r"] > best[1]:
                    best = (pid, d["mean_delta_r"], d["pair_n"])
        return {"policy": best[0] if best else None,
                "mean_paired_delta_vs_C0_2R": best[1] if best else None,
                "pair_n": best[2] if best else None,
                "rule": PREREGISTRATION["best_policy_rule"],
                "fraction_not_promoted": True} if best else None

    return {"pops": pops, "outcomes": outcomes, "summaries": summaries,
            "pathwise": pathwise, "runners": runners, "quartiles": quart,
            "sessions": sessions, "decisions": decisions,
            "best": {p: best_policy(p) for p in pops}}


def fingerprint(agg: dict) -> str:
    payload = {"summaries": agg["summaries"], "pathwise": agg["pathwise"],
               "runners": agg["runners"], "quartiles": agg["quartiles"],
               "sessions": agg["sessions"], "decisions": agg["decisions"],
               "outcomes": agg["outcomes"]}
    return sha256_json(json.loads(json.dumps(payload, sort_keys=True,
                                             default=str)))


def mutate_after(bars, timeframe, as_of):
    span = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
    return tuple(
        b if b.timestamp + span <= as_of else
        MarketBar(timestamp=b.timestamp, open=b.open * 1.1, high=b.high * 1.1,
                  low=b.low * 1.1, close=b.close * 1.1)
        for b in bars)


def main() -> int:
    zip_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        ROOT / "data" / "external" / "histdata_fx_2017"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    ok, resolution = resolve_v0_5_authority()
    write("v0_5_authority_resolution.json", resolution)
    if not ok:
        print("STATUS=BLOCKED_V0_5_AUTHORITY_AMBIGUOUS", file=sys.stderr)
        return 6

    write("preregistration.json", PREREGISTRATION)
    write("target_policy_contracts.json", {
        "policies": POLICY_CONTRACTS, "policy_ids": POLICY_IDS,
        "registry_sha256": TARGET_POLICY_REGISTRY_SHA256,
        "v0_5_target_contracts_reused_verbatim": True,
        "v0_5_registry_sha256": tv5.TARGET_V0_5_REGISTRY_SHA256})
    write("partial_runner_contracts.json", {
        "fractions": POLICY_CONTRACTS["fractions"],
        "fraction_rule": POLICY_CONTRACTS["fraction_rule"],
        "runner_rule": POLICY_CONTRACTS["runner_rule"],
        "R0": POLICY_CONTRACTS["R0"], "R1": POLICY_CONTRACTS["R1"],
        "r0_r1_never_mixed": True,
        "no_spread_adjusted_breakeven": "no authoritative spread contract "
                                        "exists; plain entry-price BE only"})

    try:
        computed = compute(zip_dir)
    except (BlockedDataAuthority, FileNotFoundError) as exc:
        print(f"BLOCKED_DATA_AUTHORITY: {exc}", file=sys.stderr)
        return 2

    repro_ok, repro = check_v0_5_reproduction(computed["records"])
    write("parent_reproduction.json", {
        "authoritative_v0_5_sha": AUTHORITATIVE_V0_5_SHA,
        "checks": repro, "all_match": repro_ok})
    if not repro_ok:
        print("STATUS=BLOCKED_V0_5_REPRODUCTION", file=sys.stderr)
        return 3

    agg = aggregate(computed["entries"])
    fp1 = fingerprint(agg)
    agg2 = aggregate(compute(zip_dir)["entries"])
    fp2 = fingerprint(agg2)
    determinism = {"run_1_sha256": fp1, "run_2_sha256": fp2,
                   "byte_identical": fp1 == fp2,
                   "scope": "policy outcomes, summaries, pathwise deltas, "
                            "runner metrics, stratifications, decisions "
                            "(two full independent computations)"}
    if fp1 != fp2:
        write("determinism_report.json", determinism)
        print("STATUS=NONDETERMINISTIC", file=sys.stderr)
        return 4

    # causality audit: selection invariance (targets) — policies consume only
    # the frozen selections + post-entry price path; runner gating is
    # structural (unit-tested: no credit without realized first objective).
    audit = {"invariants": [
        "natural target selection unchanged under post-entry mutation (x1.1) "
        "and truncation across M15/H4/D1",
        "runner begins only after the first objective is actually reached "
        "(structural; enforced in policy_outcome and unit-tested)",
        "stop counted FIRST on every bar; BE counted FIRST for R1 runners",
        "unavailable objective => NOT_APPLICABLE/NULL, never a loss",
    ], "samples": []}
    by_symbol = {}
    for pe in computed["entries"]:
        by_symbol.setdefault(pe.base.symbol, []).append(pe)
    for symbol in SYMBOLS:
        rows = by_symbol[symbol]
        frames = computed["frames_by_symbol"][symbol]
        step = max(1, len(rows) // (AUDIT_SAMPLES_PER_SYMBOL + 1))
        for pe in rows[step::step][:AUDIT_SAMPLES_PER_SYMBOL]:
            rec = pe.base
            geometry = EntryGeometry(Direction(rec.direction), rec.entry_price,
                                     rec.stop_price)
            expected = {f: (t.price, t.created_time.isoformat()) if t else None
                        for f, t in rec.targets.items()}
            variants = {}
            for name in ("truncated", "mutated"):
                vframes = {}
                for tf in ("M15", "H4", "D1"):
                    vframes[tf] = bars_closed_at(frames[tf], tf, rec.entry_time) \
                        if name == "truncated" else \
                        mutate_after(frames[tf], tf, rec.entry_time)
                vctx = tv5.build_symbol_context(vframes)
                cands = tv5._natural_candidates(vctx, geometry, rec.entry_time)
                variants[name] = {f: (c[0], c[1].isoformat()) if c else None
                                  for f, c in cands.items()}
            audit["samples"].append({
                "symbol": symbol, "entry_time": rec.entry_time.isoformat(),
                "truncation_invariant": variants["truncated"] == expected,
                "future_mutation_invariant": variants["mutated"] == expected})
    audit["all_passed"] = all(s["truncation_invariant"]
                              and s["future_mutation_invariant"]
                              for s in audit["samples"])
    if not audit["all_passed"]:
        write("causality_audit.json", audit)
        print("CAUSALITY AUDIT FAILED", file=sys.stderr)
        return 5

    # ------------------------------------------------------------- PHASE 9
    economic_authority = {
        "EXIT_CONTRACT_COMPLETE": "NO",
        "exit_contract_gaps": [
            "C0 control has no committed single frozen TP level (the frozen "
            "funnel measures a 1R..5R ladder, it does not commit an exit)",
            "no frozen authority defines a forced exit price at the 96-bar "
            "horizon for unresolved windows / open runners",
        ],
        "FRICTION_AUTHORITY_COMPLETE": "NO",
        "friction_gaps": [
            "ag_edgelab.friction is a parametric contract; no pinned "
            "authoritative spread/commission/slippage values exist for "
            "EURUSD/GBPUSD/USDJPY/XAUUSD 2017; inventing values is forbidden",
        ],
        "REALIZED_ECONOMICS_RUN": "NO",
        "consequence": "structural diagnostics only; unresolved outcomes stay "
                       "NULL; nothing here is verified economics",
    }
    write("economic_authority.json", economic_authority)
    write("economic_results.json", {
        "REALIZED_ECONOMICS_RUN": "NO",
        "reason": "EXIT_CONTRACT_COMPLETE=NO and FRICTION_AUTHORITY_COMPLETE=NO "
                  "(fail-closed); see economic_authority.json",
        "structural_results_instead": "policy_structural_results.json"})

    # ------------------------------------------------------------ artifacts
    d01_entries = agg["pops"]["D01"]
    write_jsonl("entry_policy_ledger.jsonl",
                entry_policy_rows(d01_entries, agg["outcomes"]["D01"]))
    write_jsonl("objective_sequence_ledger.jsonl",
                objective_sequence_rows(d01_entries))
    write("policy_structural_results.json", agg["summaries"])
    write("runner_results.json", agg["runners"])
    write("pathwise_policy_comparison.json", agg["pathwise"])
    write("d01_policy_results.json", {
        "summaries": agg["summaries"]["D01"], "runner": agg["runners"]["D01"],
        "decision": agg["decisions"]["D01"], "best": agg["best"]["D01"]})
    write("t1_policy_results.json", {
        "summaries": agg["summaries"]["T1"], "runner": agg["runners"]["T1"],
        "decision": agg["decisions"]["T1"], "best": agg["best"]["T1"],
        "note": "T1 is a research treatment; never assumed superior; never "
                "pooled with D01 for selection"})
    write("risk_quartile_analysis.json", agg["quartiles"])
    write("session_stratification.json", agg["sessions"])
    write("causality_audit.json", audit)
    write("determinism_report.json", determinism)

    d01_dec = agg["decisions"]["D01"]
    t1_dec = agg["decisions"]["T1"]
    primary = d01_dec["PRIMARY_DIAGNOSIS"]
    secondary = sorted(set(d01_dec["SECONDARY_DIAGNOSES"]
                           + [d for d in t1_dec["SECONDARY_DIAGNOSES"]
                              + [t1_dec["PRIMARY_DIAGNOSIS"]]
                              if d.startswith("F_")]))
    write("root_cause_analysis.json", {
        "D01": d01_dec, "T1": t1_dec,
        "PRIMARY_DIAGNOSIS": primary,
        "SECONDARY_DIAGNOSES": secondary,
        "decision_authority": "D01 is the control population; T1 informs "
                              "F only; populations never pooled"})

    freeze = {"decision": "NO_FREEZE", "candidate_contract": None,
              "candidate_contract_sha256": None,
              "oos_opened": False,
              "rule": PREREGISTRATION["decision_rules"]["freeze_rule"]}
    if primary == "C_NATURAL_TARGET_PLUS_RUNNER_SUPPORTED_FOR_FURTHER_TESTING":
        fams = [f for f, okf in d01_dec["runner_family_wins"].items() if okf]
        contract = {"family": fams, "fractions": list(FRACTIONS),
                    "runner_family": "R0",
                    "fraction_selection": "DEFERRED — never selected in DEV",
                    "target_contracts": tv5.TARGET_V0_5_REGISTRY_SHA256}
        freeze = {"decision": "FREEZE_CANDIDATE_FOR_FUTURE_OOS_VERIFICATION",
                  "candidate_contract": contract,
                  "candidate_contract_sha256": sha256_json(contract),
                  "oos_opened": False, "rule": freeze["rule"]}
    elif primary == "B_NATURAL_SINGLE_TARGET_SUPPORTED_FOR_FURTHER_TESTING":
        contract = {"family": "C1", "rule": POLICY_CONTRACTS["C1"],
                    "target_contracts": tv5.TARGET_V0_5_REGISTRY_SHA256}
        freeze = {"decision": "FREEZE_CANDIDATE_FOR_FUTURE_OOS_VERIFICATION",
                  "candidate_contract": contract,
                  "candidate_contract_sha256": sha256_json(contract),
                  "oos_opened": False, "rule": freeze["rule"]}
    write("candidate_freeze_decision.json", freeze)

    nxt = {"C_NATURAL_TARGET_PLUS_RUNNER_SUPPORTED_FOR_FURTHER_TESTING":
           "FREEZE_RUNNER_POLICY_CONTRACT_THEN_OOS_VERIFICATION_MISSION",
           "B_NATURAL_SINGLE_TARGET_SUPPORTED_FOR_FURTHER_TESTING":
           "FREEZE_C1_CONTRACT_THEN_OOS_VERIFICATION_MISSION",
           "D_RUNNER_CONTINUATION_TOO_WEAK": "KEEP_FIXED_TARGET_RESEARCH",
           "E_TARGET_POLICY_DEPENDS_ON_SL_GEOMETRY":
           "SL_TARGET_GEOMETRY_EXPERIMENT",
           "F_T1_DIRECTION_FILTER_HARMS_RUNNER_CONTINUATION":
           "TRIGGER_RUNNER_INTERACTION_RESEARCH",
           "G_INSUFFICIENT_EVIDENCE": "INSUFFICIENT_EVIDENCE"}
    final = {
        "mission": "UNIVERSAL FUNNEL V0.6 — NATURAL TARGET + RUNNER RESEARCH",
        "experiment_id": EXPERIMENT_ID, "version": EXPERIMENT_VERSION,
        "authoritative_v0_5_sha": AUTHORITATIVE_V0_5_SHA,
        "v0_5_authority_resolved": True,
        "v0_5_reproduced": True,
        "entry_n": {"D01": len(d01_entries), "T1": len(agg["pops"]["T1"])},
        "policy_means_d01": {pid: agg["summaries"]["D01"][pid]["mean_structural_r"]
                             for pid in POLICY_IDS},
        "policy_means_t1": {pid: agg["summaries"]["T1"][pid]["mean_structural_r"]
                            for pid in POLICY_IDS},
        "best_structural_policy": agg["best"],
        "p_second_given_first": {p: agg["runners"][p]["P_SECOND_GIVEN_FIRST"]
                                 for p in ("D01", "T1")},
        "runner_extended_reach": {
            p: agg["runners"][p]["runner_extended_objective_rate"]
            for p in ("D01", "T1")},
        "target_policy_depends_on_sl_geometry": {
            p: agg["quartiles"][p]["TARGET_POLICY_DEPENDS_ON_SL_GEOMETRY"]
            for p in ("D01", "T1")},
        "economics": economic_authority,
        "decisions": agg["decisions"],
        "PRIMARY_DIAGNOSIS": primary,
        "SECONDARY_DIAGNOSES": secondary,
        "NEXT_RECOMMENDED_RESEARCH": nxt[primary],
        "candidate_freeze": freeze["decision"],
        "causality": "PASS", "determinism": "PASS",
        "guards": {"strategy_rules_changed": False, "entry_changed": False,
                   "sl_changed": False, "trigger_changed": False,
                   "location_changed": False, "confirmation_changed": False,
                   "partial_percentage_optimized": False,
                   "policy_promoted": False, "edge_verified_claimed": False,
                   "oos_opened": False, "holdout_touched": False,
                   "execution_capability_added": False, "v0_7_created": False},
        "status": "V0_6_TARGET_POLICY_RESEARCH_COMPLETE",
    }
    final["final_report_sha256"] = sha256_json(
        json.loads(json.dumps(final, sort_keys=True, default=str)))
    write("final_report.json", final)

    fmt = lambda v: "NULL" if v is None else f"{v:+.3f}"
    md = ["# Universal Funnel V0.6 — Natural Target + Runner Research", "",
          f"EXPERIMENT: {EXPERIMENT_ID} @ {EXPERIMENT_VERSION} · authoritative "
          f"V0.5 {AUTHORITATIVE_V0_5_SHA[:12]} (resolved + reproduced) · "
          f"STATUS: **{final['status']}**", "",
          "## Mean structural R by policy (NULL-safe, resolved outcomes only)",
          "", "| policy | D01 mean R | D01 resolved | T1 mean R | T1 resolved |",
          "|---|---|---|---|---|"]
    for pid in POLICY_IDS:
        sd, st = agg["summaries"]["D01"][pid], agg["summaries"]["T1"][pid]
        md.append(f"| {pid} | {fmt(sd['mean_structural_r'])} | "
                  f"{sd['resolved_n']} | {fmt(st['mean_structural_r'])} | "
                  f"{st['resolved_n']} |")
    md += ["", "## Verdict", "",
           f"- PRIMARY_DIAGNOSIS (D01 control): **{primary}**",
           f"- SECONDARY: {secondary or 'none'}",
           f"- T1 decision: {t1_dec['PRIMARY_DIAGNOSIS']}",
           f"- BEST_STRUCTURAL_POLICY (descriptive, fraction never promoted): "
           f"D01 {agg['best']['D01']} · T1 {agg['best']['T1']}",
           f"- P(2nd|1st): D01 {agg['runners']['D01']['P_SECOND_GIVEN_FIRST']:.3f} "
           f"· T1 {agg['runners']['T1']['P_SECOND_GIVEN_FIRST']:.3f}",
           f"- SL-geometry dependence: "
           f"{final['target_policy_depends_on_sl_geometry']}",
           f"- Economics: NOT RUN (exit contract + friction authority fail-closed)",
           f"- Candidate freeze: {freeze['decision']}",
           f"- NEXT: **{final['NEXT_RECOMMENDED_RESEARCH']}**", "",
           "## Guards", "",
           "upstream frozen · no partial-% optimization · no promotion · "
           "no economics claims · no OOS · no holdout · no V0.7", ""]
    (OUT_DIR / "final_report.md").write_text("\n".join(md), encoding="utf-8")
    print(f"  wrote {(OUT_DIR / 'final_report.md').relative_to(ROOT)}")

    names = sorted(p.name for p in OUT_DIR.iterdir()
                   if p.is_file() and p.name != "artifact_manifest.json")
    write("artifact_manifest.json", {
        "experiment_id": EXPERIMENT_ID,
        "artifacts": {n: hashlib.sha256((OUT_DIR / n).read_bytes()).hexdigest()
                      for n in names}})
    print(f"\nSTATUS={final['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
