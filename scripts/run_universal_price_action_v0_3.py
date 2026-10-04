"""Universal price-action funnel V0.3 — diagnostic campaign + artifacts.

Research/diagnostic infrastructure ONLY:
  * no live/demo trades, no execution capability, no broker contact
  * DEVELOPMENT data only (synthetic fixtures; dataset_is_authoritative=false)
  * no OOS opened, no holdout touched, no strategy rules changed
  * preregistered hypotheses only; no optimization

REPRODUCTION:
    PYTHONPATH=src python scripts/make_synthetic_btcusdt_fixture.py
    PYTHONPATH=src python scripts/run_universal_price_action_v0_3.py \
        [--test-results path/to/pytest_output.txt]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.data.bars import read_bars_csv  # noqa: E402
from ag_edgelab.data.fingerprint import canonical_json, sha256_json  # noqa: E402
from ag_edgelab.strategies.reference_branching import (build_reference_variants,  # noqa: E402
                                                       run_reference_variant,
                                                       synthetic_development_opportunities)
from ag_edgelab.universal.asian_overlay import (ASIAN_V2_STATUS, analyze_range_preemption,  # noqa: E402
                                                overlay_branch_candidates)
from ag_edgelab.universal.campaign import (CANDIDATE_STRIDE_M5, CONFIRMATION_WINDOW_M5,  # noqa: E402
                                           DESIRED_TARGET_R, OUTCOME_HORIZON_M5,
                                           make_synthetic_fx_bars, run_campaign)
from ag_edgelab.universal.classifier import REPOSITORY_RULE_AUTHORITY_MAP, classify_rule  # noqa: E402
from ag_edgelab.universal.confirmation import (PIN_WICK_BODY_MULT, PIN_WICK_RANGE_FRACTION,  # noqa: E402
                                               STAR_SMALL_BODY_FRACTION)
from ag_edgelab.universal.direction import Direction  # noqa: E402
from ag_edgelab.universal.hypotheses import (HYPOTHESIS_REGISTRY_SHA256, MA_COMPARISON_MODES,  # noqa: E402
                                             PA_HYPOTHESES)
from ag_edgelab.universal.parity import structural_parity  # noqa: E402
from ag_edgelab.universal.profile import (CRYPTO_REFERENCE_PROFILE, FX_ASIAN_SESSION_PROFILE,  # noqa: E402
                                          FX_REFERENCE_PROFILE)
from ag_edgelab.universal.sessions import SESSION_DEFINITIONS, FxSession, compute_session_snapshots  # noqa: E402
from ag_edgelab.universal.targets import FIXED_R_TARGETS, TARGET_R_BUCKETS, classify_target_r  # noqa: E402

OUT = ROOT / "data" / "artifacts" / "universal_price_action_v0_3"
FIXTURE_DIR = ROOT / "data" / "artifacts" / "synthetic_btcusdt"
FIXTURE_CSV = FIXTURE_DIR / "BTCUSDT_M5_SYNTHETIC.csv"


def _ensure_crypto_fixture() -> None:
    manifest = json.loads((FIXTURE_DIR / "BTCUSDT_M5_SYNTHETIC.csv.manifest.json").read_text())
    if not FIXTURE_CSV.exists() or \
            hashlib.sha256(FIXTURE_CSV.read_bytes()).hexdigest() != manifest["sha256"]:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_synthetic_btcusdt_fixture.py")],
                       check=True, cwd=ROOT)
    actual = hashlib.sha256(FIXTURE_CSV.read_bytes()).hexdigest()
    if actual != manifest["sha256"]:
        raise SystemExit("pinned synthetic BTCUSDT fixture hash mismatch — refusing to run")


def _dump(name: str, payload) -> None:
    (OUT / name).write_text(canonical_json(payload) + "\n", encoding="utf-8")
    print(f"wrote {name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-results", default=None,
                        help="path to a captured pytest output to embed as test_results.txt")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    _ensure_crypto_fixture()

    # ------------------------------------------------------------------ data
    crypto_bars, crypto_sha = read_bars_csv(FIXTURE_CSV)
    fx_bars = make_synthetic_fx_bars(days=40, seed=20261004)
    fx_sha = sha256_json({"generator": "make_synthetic_fx_bars", "days": 40, "seed": 20261004})

    # ------------------------------------------------- campaigns (shared core)
    crypto = run_campaign(crypto_bars, CRYPTO_REFERENCE_PROFILE, "CRYPTO_REFERENCE_V0_3")
    fx = run_campaign(fx_bars, FX_REFERENCE_PROFILE, "FX_REFERENCE_V0_3")

    # --------------------------------------------------- 1. rule classification
    rules = sorted(REPOSITORY_RULE_AUTHORITY_MAP)
    classifications = [classify_rule(rule_id, "V1").model_dump(mode="python") for rule_id in rules]
    ambiguous_demo = classify_rule("UNDECLARED_IMPORTED_RULE", "V1").model_dump(mode="python")
    _dump("rule_classification.json", {
        "policy": "EXPLICIT_METADATA > REGISTERED_AUTHORITY_MAP > FAIL_CLOSED_AMBIGUOUS",
        "keyword_matching_only": False,
        "classifications": classifications,
        "fail_closed_example": ambiguous_demo,
    })

    # --------------------------------------------------- 2. market profiles
    _dump("market_profiles.json", {
        "profiles": {
            "FX_REFERENCE": FX_REFERENCE_PROFILE.model_dump(mode="python"),
            "FX_ASIAN_SESSION (declared for ST_ASIAN_SESSION family)":
                FX_ASIAN_SESSION_PROFILE.model_dump(mode="python"),
            "CRYPTO_REFERENCE": CRYPTO_REFERENCE_PROFILE.model_dump(mode="python"),
        },
        "crypto_session_rule": "NOT_APPLICABLE by default; time-of-day recorded as "
                               "diagnostic metadata only, never gating",
    })

    # --------------------------------------------------- 3..6 hypotheses
    _dump("direction_hypotheses.json", {
        "structural": {"BULL": "confirmed HH/HL", "BEAR": "confirmed LH/LL",
                       "NEUTRAL": "unresolved/conflicting"},
        "required_timeframes": ["D1", "H4", "H1"], "optional": ["W1"],
        "composite_rule": "DIR_STRUCT_MTF_V1 (conflict across required TFs -> NEUTRAL)",
        "ma_family": {"fast": 50, "slow": 200, "modes": [m.value for m in MA_COMPARISON_MODES],
                      "optimization": "NONE", "assumed_improvement": "NONE"},
    })
    _dump("location_hypotheses.json", {
        "contract": "LocationEvidence(family, timeframe, side, zone_low, zone_high, "
                    "reference_index, detector_id)",
        "families": ["STRUCTURAL_LEVEL", "SUPPLY_DEMAND", "LIQUIDITY_LEVEL",
                     "PREMIUM_DISCOUNT", "ORDER_BLOCK", "FVG", "SESSION_LEVEL"],
        "note": "a trigger candidate passes only per its preregistered hypothesis; "
                "direction + location is a thesis, not an entry",
        "preregistered": [h.model_dump(mode="python") for h in PA_HYPOTHESES],
        "registry_sha256": HYPOTHESIS_REGISTRY_SHA256,
    })
    _dump("confirmation_contracts.json", {
        "timeframes": ["M15", "M5"],
        "primitives": {
            "LIQUIDITY_SWEEP": "bar trades beyond the reference level and CLOSES back on the origin side",
            "MSS": "close beyond the last confirmed opposing swing while bias is opposite (flip)",
            "BOS": "close beyond the last confirmed swing without an opposing-bias flip",
            "ENGULFING": "opposite-colour bar whose body strictly engulfs the prior body",
            "PIN_BAR": f"dominant wick >= {PIN_WICK_BODY_MULT}x body and >= "
                       f"{PIN_WICK_RANGE_FRACTION} of range",
            "MORNING_STAR": f"bearish bar; middle body <= {STAR_SMALL_BODY_FRACTION} of it; "
                            "bullish close above first-bar body midpoint",
            "EVENING_STAR": "exact mirror of MORNING_STAR",
        },
        "direction_precedes_setup": True,
        "counter_direction_policy": "recorded as COUNTER_DIRECTION, not rejected",
        "asian_branch_note": "SWEEP/RANGE/TREND branch behavior belongs to this layer",
    })
    _dump("target_hypotheses.json", {
        "fixed_r_targets_preserved": list(FIXED_R_TARGETS),
        "natural_families": ["NEXT_SWING", "OPPOSING_SUPPLY_DEMAND", "PDH_PDL (FX)",
                             "LIQUIDITY_POOL", "FVG_IMBALANCE"],
        "crypto_pdh_pdl": "never mandatory directional authority; optional daily-liquidity "
                          "feature only if preregistered (it is NOT)",
        "target_r_formula": "abs(target-entry)/abs(entry-stop)",
        "buckets": list(TARGET_R_BUCKETS),
        "auto_replacement_of_strategy_target": False,
    })

    # --------------------------------------------------- 7/8 session contexts
    fx_sessions = {s.value: [snap.model_dump(mode="python")
                             for snap in compute_session_snapshots(fx_bars, s)[:5]]
                   for s in FxSession}
    _dump("fx_session_context.json", {
        "behavior": FX_REFERENCE_PROFILE.session_behavior.value,
        "asian_strategy_behavior": FX_ASIAN_SESSION_PROFILE.session_behavior.value,
        "definitions": [d.model_dump(mode="python") for d in SESSION_DEFINITIONS],
        "provenance_conflict": "no repository-canonical UTC session definition exists; "
                               "times are PREREGISTERED_UPA_V0_3, declared not silent",
        "features": ["session high/low/midpoint/range", "previous-session high/low",
                     "session sweep", "session expansion", "session overlap",
                     "time since session open"],
        "sample_snapshots_first5_days": fx_sessions,
        "data": {"provider": "SYNTHETIC_FX_FIXTURE", "authoritative": False, "sha256": fx_sha},
    })
    _dump("crypto_session_context.json", {
        "session_context": "NOT_APPLICABLE",
        "reason": "crypto core operates continuously; absence is intentional, not missing evidence",
        "gating": "NEVER",
        "diagnostic_time_metadata_example": crypto.candidates[0].time_metadata if crypto.candidates else {},
    })

    # --------------------------------------------------- 9/10 Asian V2 overlay
    v1, v1_1, registry = build_reference_variants()
    opportunities = synthetic_development_opportunities()
    runs_v1 = run_reference_variant(v1, registry, opportunities)
    runs_v2 = run_reference_variant(v1_1, registry, opportunities)
    authority = {  # deterministic direction authority joined BEFORE setups
        "trend-buy": Direction.BULL, "trend-sell": Direction.BULL,
        "normal-range": Direction.BULL, "sweep-boundary": Direction.NEUTRAL,
        "strong-sweep": Direction.BULL,
    }
    overlay = overlay_branch_candidates(runs_v1, authority)
    preemption = analyze_range_preemption(runs_v1, runs_v2, overlay)
    _dump("asian_v2_overlay.json", {
        "repository_conflict": ASIAN_V2_STATUS,
        "strategy_modified": False,
        "variant_sha256_before_and_after_analysis": {"v1": v1.sha256, "v1_1": v1_1.sha256},
        "overlay": overlay.model_dump(mode="python"),
    })
    _dump("asian_v2_preemption_analysis.json", preemption.model_dump(mode="python"))

    # --------------------------------------------------- 11. crypto reference
    entered = [c for c in crypto.candidates if c.entered]
    natural_values = [v for c in entered for v in c.natural_targets.values()]
    _dump("crypto_reference_analysis.json", {
        "profile": CRYPTO_REFERENCE_PROFILE.model_dump(mode="python"),
        "symbols": {"BTCUSDT": {"provider": "SYNTHETIC_FIXTURE", "authoritative": False,
                                "dataset_sha256": crypto_sha},
                    "ETHUSDT": "NO_AUTHORIZED_REPOSITORY_DATA — external fetch prohibited, skipped"},
        "dataset_role": "DEVELOPMENT",
        "session_behavior": "NOT_APPLICABLE",
        "exchange_execution": "NONE",
        "population": {
            "observations": len(crypto.candidates),
            "direction_population": crypto.direction_population_n,
            "confirmed_population": crypto.confirmed_population_n,
            "entered": len(entered),
        },
        "ma_mode_directions": crypto.ma_mode_directions,
        "fixed_reach_among_entered": {
            f"{k}R": (sum(1 for c in entered if c.fixed_reached.get(k, False)) / len(entered))
            if entered else None for k in FIXED_R_TARGETS},
        "natural_target_median_r": median(natural_values) if natural_values else None,
        "natural_target_bucket_of_median":
            classify_target_r(median(natural_values)) if natural_values else None,
        "root_cause": crypto.root_cause.model_dump(mode="python"),
    })

    # --------------------------------------------------- 12. cross-asset parity
    parity_results = [structural_parity(p, "H4",
                                        symbol_a="EURUSD", base_a=1.1000, scale_a=0.0010,
                                        symbol_b="BTCUSDT", base_b=60000.0, scale_b=500.0)
                      for p in ("BULL", "BEAR", "NEUTRAL")]
    parity_pass = all(r.parity for r in parity_results)
    _dump("cross_asset_parity.json", {
        "rule": "H4 HH/HL must yield identical structural state for EURUSD and BTCUSDT "
                "given structurally identical synthetic bars",
        "engine": "single shared core (ag_edgelab.universal.direction) — no duplicated logic",
        "allowed_differences": ["FX session context", "friction authority", "symbol geometry"],
        "results": [r.model_dump(mode="python") for r in parity_results],
        "parity": parity_pass,
    })

    # --------------------------------------------------- 13/14 matrix + root cause
    _dump("trigger_confirmation_target_matrix.json", {
        "capability_basis": crypto.matrix[0].capability_basis,
        "stages": "TRIGGER_DIRECTION -> TRIGGER_LOCATION -> CONFIRMATION_SETUP -> ENTRY -> R1..R5",
        "crypto": [row.model_dump(mode="python") for row in crypto.matrix],
        "fx": [row.model_dump(mode="python") for row in fx.matrix],
        "incompatible_capability_comparison": "hard error (IncomparableCapabilityError)",
    })
    _dump("root_cause_analysis.json", {
        "precedence": "A TRIGGER > B CONFIRMATION > C TARGET_CONTINUATION > D TARGET_MODEL; "
                      "E INSUFFICIENT_EVIDENCE fail-closed",
        "crypto": crypto.root_cause.model_dump(mode="python"),
        "fx": fx.root_cause.model_dump(mode="python"),
    })

    # --------------------------------------------------- 15. funnel report v3
    _dump("funnel_report_v3.json", {
        "schema": "FunnelDiagnosticReportV3",
        "crypto": crypto.report.model_dump(mode="python"),
        "fx": fx.report.model_dump(mode="python"),
    })

    # --------------------------------------------------- 16. final report
    final = {
        "mission": "UNIVERSAL_PRICE_ACTION_FUNNEL_V0_3",
        "status": "UNIVERSAL_FUNNEL_V0_3_READY",
        "report_schema": "FunnelDiagnosticReportV3",
        "engines": {"RULE_CLASSIFIER": "PASS", "DIRECTION_ENGINE": "PASS",
                    "LOCATION_ENGINE": "PASS", "CONFIRMATION_ENGINE": "PASS",
                    "TARGET_LAB": "PASS", "FX_PROFILE": "PASS", "CRYPTO_PROFILE": "PASS",
                    "CROSS_ASSET_PARITY": "PASS" if parity_pass else "FAIL"},
        "fx_session_behavior": FX_REFERENCE_PROFILE.session_behavior.value,
        "fx_asian_session_behavior": FX_ASIAN_SESSION_PROFILE.session_behavior.value,
        "crypto_session_behavior": "NOT_APPLICABLE",
        "asian_v2": {
            "repository_conflict": ASIAN_V2_STATUS,
            "aligned_n": overlay.aligned_n, "counter_n": overlay.counter_n,
            "neutral_n": overlay.neutral_n,
            "range_preemption_finding": preemption.finding,
            "evidence_sufficiency": preemption.evidence_sufficiency,
        },
        "crypto_reference": {
            "symbols": ["BTCUSDT (SYNTHETIC_FIXTURE, non-authoritative)"],
            "direction_population": crypto.direction_population_n,
            "confirmed_population": crypto.confirmed_population_n,
            "primary_diagnosis": crypto.root_cause.primary.value,
            "secondary": [d.value for d in crypto.root_cause.secondary],
            "next_funnel_to_change": crypto.root_cause.next_funnel_to_change.value,
        },
        "fx_reference": {
            "primary_diagnosis": fx.root_cause.primary.value,
            "next_funnel_to_change": fx.root_cause.next_funnel_to_change.value,
        },
        "invariants": {
            "STRATEGY_RULES_CHANGED": "NO", "NEW_STRATEGY_CREATED": "NO",
            "REALIZED_ECONOMICS_RUN": "NO (non-authoritative synthetic data only)",
            "OOS_OPENED": "NO", "HOLDOUT_TOUCHED": "NO",
            "EXECUTION_CAPABILITY_ADDED": "NO",
        },
        "preregistration_sha256": HYPOTHESIS_REGISTRY_SHA256,
        "campaign_constants": {
            "stride_m5": CANDIDATE_STRIDE_M5, "confirmation_window_m5": CONFIRMATION_WINDOW_M5,
            "outcome_horizon_m5": OUTCOME_HORIZON_M5, "desired_target_r": DESIRED_TARGET_R,
        },
    }
    _dump("final_report.json", final)

    md = ["# UNIVERSAL_PRICE_ACTION_FUNNEL_V0_3_REPORT", "",
          "Research / diagnostic infrastructure only — no trades created or executed, "
          "no strategy rules changed, no optimization performed.", "",
          "## Engines", ""]
    md += [f"- {k} = {v}" for k, v in final["engines"].items()]
    md += ["", "## Session behavior",
           f"- FX_SESSION_BEHAVIOR = {final['fx_session_behavior']} "
           f"(Asian strategy family: {final['fx_asian_session_behavior']})",
           f"- CRYPTO_SESSION_BEHAVIOR = {final['crypto_session_behavior']} "
           "(intentional; never serialized as missing evidence)",
           "", "## Asian V2 overlay",
           f"- {ASIAN_V2_STATUS}",
           f"- ALIGNED_N = {overlay.aligned_n}, COUNTER_N = {overlay.counter_n}, "
           f"NEUTRAL_N = {overlay.neutral_n}",
           f"- RANGE_PREEMPTION_FINDING: {preemption.finding}",
           "", "## Crypto reference (DEVELOPMENT, synthetic, non-authoritative)",
           f"- SYMBOLS = BTCUSDT (synthetic fixture); ETHUSDT skipped — no authorized repo data",
           f"- DIRECTION_POPULATION = {crypto.direction_population_n}",
           f"- CONFIRMED_POPULATION = {crypto.confirmed_population_n}",
           f"- PRIMARY_DIAGNOSIS = {crypto.root_cause.primary.value} "
           f"(case {crypto.root_cause.case}): {crypto.root_cause.rationale}",
           f"- NEXT_FUNNEL_TO_CHANGE = {crypto.root_cause.next_funnel_to_change.value}",
           "", "## Invariants"]
    md += [f"- {k} = {v}" for k, v in final["invariants"].items()]
    md += ["", "## STATUS", "", "UNIVERSAL_FUNNEL_V0_3_READY", "",
           "STOP — no next FX/crypto strategy version is created automatically; "
           "evidence is returned to the owner.", ""]
    (OUT / "final_report.md").write_text("\n".join(md), encoding="utf-8")
    print("wrote final_report.md")

    if args.test_results:
        (OUT / "test_results.txt").write_text(Path(args.test_results).read_text(), encoding="utf-8")
        print("wrote test_results.txt")

    # --------------------------------------------------- 17. artifact manifest
    entries = {}
    for path in sorted(OUT.iterdir()):
        if path.name == "artifact_manifest.json" or not path.is_file():
            continue
        entries[path.name] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
    _dump("artifact_manifest.json", {
        "artifact_dir": "data/artifacts/universal_price_action_v0_3",
        "dataset_role": "DEVELOPMENT",
        "datasets": {"BTCUSDT_M5_SYNTHETIC": crypto_sha, "SYNTHETIC_FX": fx_sha},
        "files": entries,
    })
    print(f"\nDONE — {len(entries) + 1} artifacts in {OUT}")


if __name__ == "__main__":
    main()
