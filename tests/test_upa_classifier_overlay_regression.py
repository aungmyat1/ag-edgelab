"""Universal price-action V0.3 — rule classifier, Asian V2 overlay (proxy
population), deterministic hashes and existing-strategy regression pins."""
from __future__ import annotations

from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.strategies import crypto_mtf_smc as smc
from ag_edgelab.strategies.reference_branching import (SYNTHETIC_IMPLEMENTATION_SHA256,
                                                       build_reference_variants,
                                                       run_reference_variant,
                                                       synthetic_development_opportunities)
from ag_edgelab.universal.asian_overlay import (ASIAN_V2_STATUS, analyze_range_preemption,
                                                overlay_branch_candidates)
from ag_edgelab.universal.classifier import (AMBIGUOUS, REPOSITORY_RULE_AUTHORITY_MAP,
                                             RuleFunction, classify_rule)
from ag_edgelab.universal.confirmation import SetupAlignment
from ag_edgelab.universal.direction import Direction
from ag_edgelab.universal.hypotheses import (HYPOTHESIS_REGISTRY_SHA256, PA_HYPOTHESES,
                                             hypothesis_by_id)
from ag_edgelab.universal.campaign import make_synthetic_fx_bars, run_campaign
from ag_edgelab.universal.profile import FX_REFERENCE_PROFILE

# ---------------------------------------------------------------------------
# Rule classifier
# ---------------------------------------------------------------------------

def test_rule_classification_explicit_metadata_wins():
    result = classify_rule("ANY_RULE", "V1", metadata={"function": "TRIGGER_LOCATION"})
    assert result.status == "CLASSIFIED"
    assert result.function == RuleFunction.TRIGGER_LOCATION
    assert result.basis == "EXPLICIT_METADATA" and not result.requires_owner_review


def test_rule_classification_registered_authority_map():
    result = classify_rule("H1_POI_ACTIVE", "V1")
    assert result.function == RuleFunction.TRIGGER_LOCATION
    assert result.basis == "REGISTERED_AUTHORITY_MAP"
    assert classify_rule("EXIT", "V1").function == RuleFunction.EXIT_MANAGEMENT
    assert classify_rule("RR_GATE_V1", "V1").function == RuleFunction.RISK
    assert classify_rule("ASIAN_SESSION_V1", "V1").function == RuleFunction.SESSION_CONTEXT


def test_ambiguous_rule_fails_closed():
    result = classify_rule("MYSTERY_RULE_42", "V7")
    assert result.status == AMBIGUOUS and result.function is None
    assert result.requires_owner_review
    # Invalid declared metadata also fails closed, never guessed from names.
    bad = classify_rule("MYSTERY_RULE_42", "V7", metadata={"function": "MAGIC"})
    assert bad.status == AMBIGUOUS and bad.requires_owner_review


def test_classifier_does_not_use_keywords():
    # A rule whose NAME screams "sweep" is still ambiguous without metadata
    # or an explicit authority-map entry.
    result = classify_rule("SUPER_SWEEP_TRIGGER_LONDON", "V1", authority_map={})
    assert result.status == AMBIGUOUS


# ---------------------------------------------------------------------------
# Asian V2 overlay (proxy population; strategy never modified)
# ---------------------------------------------------------------------------

def _runs():
    v1, v1_1, registry = build_reference_variants()
    opportunities = synthetic_development_opportunities()
    runs_v1 = run_reference_variant(v1, registry, opportunities)
    runs_v2 = run_reference_variant(v1_1, registry, opportunities)
    return v1, v1_1, runs_v1, runs_v2


AUTHORITY = {  # direction authority joined (exists BEFORE setup evaluation)
    "trend-buy": Direction.BULL,
    "trend-sell": Direction.BULL,      # short setup under BULL => COUNTER
    "normal-range": Direction.BULL,
    "sweep-boundary": Direction.NEUTRAL,
    "strong-sweep": Direction.BULL,
}


def test_overlay_reports_aligned_counter_neutral_for_branches():
    _, _, runs_v1, _ = _runs()
    overlay = overlay_branch_candidates(runs_v1, AUTHORITY)
    assert overlay.status == ASIAN_V2_STATUS
    assert "NOT_PRESENT_IN_REPOSITORY" in overlay.status
    assert overlay.aligned_n == 3   # trend-buy, normal-range, strong-sweep (long)
    assert overlay.counter_n == 1   # trend-sell under BULL authority — recorded
    assert overlay.neutral_n == 1   # sweep-boundary (NEUTRAL authority)
    assert set(overlay.by_branch) == {"SWEEP", "RANGE", "TREND"}
    counter = next(c for c in overlay.candidates if c.alignment == SetupAlignment.COUNTER_DIRECTION)
    assert counter.trade_direction == "SHORT" and counter.authority == Direction.BULL


def test_range_preemption_population_recomputed():
    _, _, runs_v1, runs_v2 = _runs()
    overlay = overlay_branch_candidates(runs_v1, AUTHORITY)
    analysis = analyze_range_preemption(runs_v1, runs_v2, overlay)
    # sweep-boundary: strength 0.6 => SWEEP under V1 (0.5), RANGE under V2 (0.8).
    preempted = [r for r in analysis.records if r.preempted_to_range]
    assert analysis.preempted_n == 1
    assert preempted[0].candidate_id == "sweep-boundary"
    assert preempted[0].branch_under_v1 == "SWEEP" and preempted[0].branch_under_v2 == "RANGE"
    # It is NEUTRAL-aligned and precedes the later ALIGNED strong-sweep
    # candidate => counted as suppressing a better-aligned candidate.
    assert analysis.preempted_neutral_n == 1 and analysis.suppressing_n == 1
    assert "INSUFFICIENT_EVIDENCE_FOR_ASIAN_V2" in analysis.evidence_sufficiency


def test_overlay_does_not_alter_the_underlying_strategy():
    v1, v1_1, runs_v1, runs_v2 = _runs()
    sha_before = (v1.sha256, v1_1.sha256)
    overlay = overlay_branch_candidates(runs_v1, AUTHORITY)
    analyze_range_preemption(runs_v1, runs_v2, overlay)
    v1b, v1_1b, _ = build_reference_variants()
    assert (v1b.sha256, v1_1b.sha256) == sha_before


# ---------------------------------------------------------------------------
# Deterministic hashes + existing strategy identity regression
# ---------------------------------------------------------------------------

def test_hypothesis_registry_is_preregistered_and_hashed():
    assert [h.hypothesis_id for h in PA_HYPOTHESES] == [f"PA{i:02d}" for i in range(1, 8)]
    assert HYPOTHESIS_REGISTRY_SHA256 == sha256_json(
        {"hypotheses": [h.model_dump(mode="python") for h in PA_HYPOTHESES],
         "ma_modes": ["STRUCTURE_ONLY", "MA_ONLY", "STRUCTURE_PLUS_MA"]})
    assert hypothesis_by_id("PA03").location_families
    try:
        hypothesis_by_id("PA99")
        raise AssertionError("unregistered hypothesis must not resolve")
    except KeyError:
        pass


def test_campaign_is_deterministic_hash_stable():
    bars = make_synthetic_fx_bars(days=12, seed=7)
    first = run_campaign(bars, FX_REFERENCE_PROFILE, "FX_DET")
    second = run_campaign(bars, FX_REFERENCE_PROFILE, "FX_DET")
    digest_a = sha256_json(first.report.model_dump(mode="python"))
    digest_b = sha256_json(second.report.model_dump(mode="python"))
    assert digest_a == digest_b
    assert first.report.schema_version == "FunnelDiagnosticReportV3"


def test_existing_strategy_hashes_unchanged():
    """Regression pins: V0.3 must not alter any existing strategy identity."""
    v1, v1_1, _ = build_reference_variants()
    assert v1.sha256 == "d234a13b0026fbde40779be82e087add004a0ea4a48dd360244817724221c122"
    assert v1_1.sha256 == "deabeb1bd201f0f6496f975de44a19a0b773e0b9e7df54b221a276e4a042f3de"
    assert SYNTHETIC_IMPLEMENTATION_SHA256 == \
        "bdc9a997e86774bf61a6c330319f4308c4131a1bd2af9056725e83bc2be8a841"
    assert smc.STRATEGY_ID == "ST_CRYPTO_MTF_SMC_V1"
    assert smc.STRATEGY_VERSION == "0.1.0-research"
    assert smc.EDGE_VERIFIED is False


def test_authority_map_covers_repository_reference_rules():
    for rule_id in ("MARKET_STATE", "TREND_DIRECTION", "SWEEP", "TREND_BUY",
                    "TREND_SELL", "RANGE_SETUP", "SWEEP_SETUP"):
        assert rule_id in REPOSITORY_RULE_AUTHORITY_MAP
