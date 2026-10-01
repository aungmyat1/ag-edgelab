from datetime import datetime, timezone, timedelta
import pytest
from pydantic import ValidationError

from ag_edgelab.optimization.contracts import DatasetExposure
from ag_edgelab.verification.evidence import DatasetRecord, FRICTION_IMPLEMENTATION_SHA256, REGIME_CLASSIFIER_IMPLEMENTATION_SHA256, FrictionEvidenceRecord, FrictionModelRecord, MarketStateRecord, RegimeClassifierRecord, StabilityEvidenceRecord, TradeListRecord, TradeOutcome, ValidationBundleRecord, WalkForwardEvidenceRecord, WalkForwardFoldRecord
from ag_edgelab.verification.production import CANONICAL_POLICY_V1, CANONICAL_POLICY_V1_SHA256, EdgeVerdict, POLICY_REGISTRY, _install_trusted_authority, validate_artifact, verify_edge
from ag_edgelab.verification.provenance import ContentAddressedStore, EngineRecord, EngineRegistry, ExposureEvent, ExposureLedger, FrozenVariantRecord, VerificationResolvers

Z = timezone.utc
STRAT = "a" * 64
OOS_START = datetime(2026, 2, 1, tzinfo=Z)
OOS_END = datetime(2026, 3, 1, tzinfo=Z)


def trades(delta=0.0, n=80, start=OOS_START + timedelta(hours=1), cost_r=0.02, dataset=None, market_states=None, regime_failure=False):
    outcomes = []
    for i in range(n):
        executed_at = start + timedelta(minutes=i)
        trade_id = f"t{i}"
        is_trend = i < n // 2
        market_state = None
        if dataset is not None:
            market_state = MarketStateRecord(
                dataset_sha256=dataset,
                trade_id=trade_id,
                observed_at=executed_at,
                open=100.0,
                high=101.0,
                low=99.0,
                close=101.0 if is_trend else 99.0,
            )
            market_states.append(market_state)
        outcome_r = ((.5 if i % 4 else -.5) + delta)
        if regime_failure and i >= n // 2:
            outcome_r = (.5 if (i - n // 2) % 2 else -.5) + delta
        outcomes.append(TradeOutcome(
            trade_id=trade_id,
            executed_at=executed_at,
            r=outcome_r,
            regime="TREND" if is_trend else "RANGE",
            market_state_sha256=market_state.sha256 if market_state else None,
            gross_r=outcome_r + cost_r,
            spread_cost_r=cost_r,
            commission_cost_r=0.0,
            slippage_cost_r=0.0,
            funding_cost_r=0.0,
        ))
    return tuple(outcomes)


def tl(engine, code, delta=0.0, n=80, dataset="d" * 64, start=OOS_START + timedelta(hours=1), cost_r=0.02, market_states=None, regime_failure=False):
    return TradeListRecord(
        dataset_sha256=dataset,
        strategy_sha256=STRAT,
        engine_id=engine,
        engine_code_sha256=code,
        trades=trades(delta, n, start, cost_r, dataset if market_states is not None else None, market_states, regime_failure),
    )


def fixture(*, negative=False, omit_regime=False, cost_r=0.02, regime_failure=False):
    dataset = DatasetRecord(dataset_sha256="d" * 64, start=OOS_START, end=OOS_END)
    data_ref = dataset.sha256
    re = EngineRecord(engine_id="ref", code_sha256="1" * 64, independence_group="A")
    ie = EngineRecord(engine_id="ind", code_sha256="2" * 64, independence_group="B")
    engines = EngineRegistry.owner_approved_pair((re, ie))
    friction_model = FrictionModelRecord(model_id="normalized-r", version="1", implementation_sha256=FRICTION_IMPLEMENTATION_SHA256)
    classifier = RegimeClassifierRecord(
        classifier_id="ohlc-direction", version="1",
        implementation_sha256=REGIME_CLASSIFIER_IMPLEMENTATION_SHA256,
    )
    variant = FrozenVariantRecord(
        strategy_id="S",
        strategy_version="1",
        strategy_sha256=STRAT,
        friction_model_sha256=friction_model.sha256,
        funnel_sha256="b" * 64,
        parameters_sha256="c" * 64,
        claimed_regimes=("TREND",) if omit_regime else ("TREND", "RANGE"),
        regime_classifier_sha256=classifier.sha256,
        frozen_at=datetime(2026, 1, 1, tzinfo=Z),
    )
    d = -.5 if negative else 0.0
    market_states = []
    oos = tl("ref", "1" * 64, d, dataset=data_ref, cost_r=cost_r, market_states=market_states, regime_failure=regime_failure)
    ind = tl("ind", "2" * 64, d - .005, dataset=data_ref, regime_failure=regime_failure)
    friction = FrictionEvidenceRecord(
        baseline_trade_list_sha256=oos.sha256,
        model_sha256=friction_model.sha256,
        multipliers=CANONICAL_POLICY_V1.required_friction_multipliers,
    )

    fold_lists = []
    folds = []
    for i, h in enumerate(("6", "7", "8")):
        start = datetime(2025, 1, 1, tzinfo=Z) + timedelta(days=i * 100)
        test_start = start + timedelta(days=40)
        x = tl("ref", "1" * 64, d, n=40, dataset=h * 64, start=test_start + timedelta(hours=1))
        fold_lists.append(x)
        folds.append(
            WalkForwardFoldRecord(
                fold_id=f"F{i}",
                train_start=start,
                train_end=test_start,
                test_start=test_start,
                test_end=start + timedelta(days=60),
                trade_list_sha256=x.sha256,
            )
        )
    wf = WalkForwardEvidenceRecord(folds=tuple(folds))

    s_lists = []
    neighborhoods = []
    for i, (v, h) in enumerate(zip((1.0, 1.2, 1.4), ("9", "a", "b"))):
        x = tl("ref", "1" * 64, d + (0, .02, .01)[i], n=40, dataset=h * 64)
        s_lists.append(x)
        neighborhoods.append((v, x.sha256))
    stability = StabilityEvidenceRecord(center=1.2, neighborhoods=tuple(neighborhoods))

    records = [oos, ind, friction_model, classifier, *market_states, *fold_lists, *s_lists, friction, wf, stability]
    store = ContentAddressedStore.build({x.sha256: x for x in records})
    bundle = ValidationBundleRecord(
        variant_sha256=variant.sha256,
        oos_trade_list_sha256=oos.sha256,
        friction_sha256=friction.sha256,
        walk_forward_sha256=wf.sha256,
        stability_sha256=stability.sha256,
        parity_reference_trade_list_sha256=oos.sha256,
        parity_independent_trade_list_sha256=ind.sha256,
    )
    store = ContentAddressedStore.build({**dict(store._records), bundle.sha256: bundle})
    opened = ExposureEvent(
        dataset_sha256=data_ref,
        previous=DatasetExposure.UNSEEN,
        current=DatasetExposure.BURNED_HOLDOUT,
        observed_at=OOS_START,
    )
    resolvers = VerificationResolvers(
        ContentAddressedStore.build({variant.sha256: variant}),
        store,
        ContentAddressedStore.build({dataset.sha256: dataset}),
        engines,
        ExposureLedger((opened,)),
    )
    return bundle, resolvers


def use(resolvers):
    _install_trusted_authority(resolvers)


def test_positive_raw_evidence_can_verify():
    b, r = fixture()
    use(r)
    a = verify_edge(b.sha256)
    assert a.verdict == EdgeVerdict.EDGE_VERIFIED
    assert validate_artifact(a)


def test_coherent_negative_is_no_edge():
    b, r = fixture(negative=True)
    use(r)
    assert verify_edge(b.sha256).verdict == EdgeVerdict.NO_EDGE


def test_unknown_and_fabricated_strategy_ids_fail_closed():
    _, r = fixture()
    use(r)
    assert verify_edge("f" * 64).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize("bad_id", ["invalid", "", None, 123, "F" * 64, "a" * 63, "a" * 65, "g" * 64])
def test_malformed_evidence_ids_fail_closed(bad_id):
    artifact = verify_edge(bad_id)
    assert artifact.verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE
    assert artifact.verdict not in (EdgeVerdict.EDGE_VERIFIED, EdgeVerdict.NO_EDGE)
    assert artifact.reasons == ("INVALID_EVIDENCE_ID",)


def test_mixed_naive_aware_evidence_fails_closed_without_comparison_error():
    b, r = fixture()
    variant = r.variants.resolve(b.variant_sha256).model_copy(update={"frozen_at": datetime(2026, 1, 1)})
    bad_bundle = b.model_copy(update={"variant_sha256": variant.sha256})
    records = dict(r.evidence._records)
    records[bad_bundle.sha256] = bad_bundle
    rr = VerificationResolvers(
        ContentAddressedStore.build({variant.sha256: variant}),
        ContentAddressedStore.build(records), r.datasets, r.engines, r.exposure,
    )
    use(rr)
    assert verify_edge(bad_bundle.sha256).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_aware_non_utc_evidence_normalizes_to_utc():
    offset = timezone(timedelta(hours=5, minutes=30))
    dataset = DatasetRecord(
        dataset_sha256="d" * 64,
        start=datetime(2026, 2, 1, 5, 30, tzinfo=offset),
        end=datetime(2026, 3, 1, 5, 30, tzinfo=offset),
    )
    assert dataset.start == OOS_START
    assert dataset.end == OOS_END
    assert dataset.start.tzinfo is timezone.utc


def test_valid_utc_evidence_still_verifies():
    b, r = fixture()
    use(r)
    assert verify_edge(b.sha256).verdict == EdgeVerdict.EDGE_VERIFIED


def _verify_with_oos(b, r, altered_oos):
    old_friction = r.evidence.resolve(b.friction_sha256)
    friction = old_friction.model_copy(update={"baseline_trade_list_sha256": altered_oos.sha256})
    records = dict(r.evidence._records)
    records[altered_oos.sha256] = altered_oos
    records[friction.sha256] = friction
    bundle = b.model_copy(update={
        "oos_trade_list_sha256": altered_oos.sha256,
        "parity_reference_trade_list_sha256": altered_oos.sha256,
        "friction_sha256": friction.sha256,
    })
    records[bundle.sha256] = bundle
    rr = VerificationResolvers(r.variants, ContentAddressedStore.build(records), r.datasets, r.engines, r.exposure)
    use(rr)
    return verify_edge(bundle.sha256)


def _verify_with_variant(b, r, altered_variant, extra_evidence=()):
    records = dict(r.evidence._records)
    records.update({item.sha256: item for item in extra_evidence})
    bundle = b.model_copy(update={"variant_sha256": altered_variant.sha256})
    records[bundle.sha256] = bundle
    rr = VerificationResolvers(
        ContentAddressedStore.build({altered_variant.sha256: altered_variant}),
        ContentAddressedStore.build(records), r.datasets, r.engines, r.exposure,
    )
    use(rr)
    return verify_edge(bundle.sha256)


def test_post_hoc_trade_labels_cannot_change_regime_grouping_or_verdict():
    b, r = fixture()
    original = r.evidence.resolve(b.oos_trade_list_sha256)
    use(r)
    original_verdict = verify_edge(b.sha256).verdict
    winner_labeled = original.model_copy(update={
        "trades": tuple(t.model_copy(update={"regime": "TREND" if t.r > 0 else "RANGE"}) for t in original.trades)
    })
    assert original_verdict == EdgeVerdict.EDGE_VERIFIED
    assert _verify_with_oos(b, r, winner_labeled).verdict == original_verdict


def test_frozen_classifier_substitution_fails_closed():
    b, r = fixture()
    variant = r.variants.resolve(b.variant_sha256)
    alternate = RegimeClassifierRecord(
        classifier_id="outcome-aware", version="1",
        implementation_sha256=REGIME_CLASSIFIER_IMPLEMENTATION_SHA256,
    )
    substituted = variant.model_copy(update={"regime_classifier_sha256": alternate.sha256})
    assert _verify_with_variant(b, r, substituted, (alternate,)).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_classifier_tampering_and_spoofed_identity_fail_closed():
    b, r = fixture()
    variant = r.variants.resolve(b.variant_sha256)
    classifier = r.evidence.resolve(variant.regime_classifier_sha256)
    tampered = classifier.model_copy(update={"classification_rule": "close < open => TREND; otherwise => RANGE"})
    with pytest.raises(ValueError):
        ContentAddressedStore.build({classifier.sha256: tampered})
    altered_variant = variant.model_copy(update={"regime_classifier_sha256": tampered.sha256})
    assert _verify_with_variant(b, r, altered_variant, (tampered,)).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_missing_frozen_classifier_fails_closed():
    b, r = fixture()
    variant = r.variants.resolve(b.variant_sha256).model_copy(update={"regime_classifier_sha256": "f" * 64})
    assert _verify_with_variant(b, r, variant).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_missing_market_state_evidence_fails_closed():
    b, r = fixture()
    oos = r.evidence.resolve(b.oos_trade_list_sha256)
    first = oos.trades[0].model_copy(update={"market_state_sha256": None})
    altered = oos.model_copy(update={"trades": (first,) + oos.trades[1:]})
    assert _verify_with_oos(b, r, altered).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize("substitution", ["dataset", "trade", "time"])
def test_wrong_market_state_population_trade_or_window_fails_closed(substitution):
    b, r = fixture()
    oos = r.evidence.resolve(b.oos_trade_list_sha256)
    original_trade = oos.trades[0]
    state = r.evidence.resolve(original_trade.market_state_sha256)
    changes = {
        "dataset": {"dataset_sha256": "f" * 64},
        "trade": {"trade_id": oos.trades[1].trade_id},
        "time": {"observed_at": original_trade.executed_at - timedelta(minutes=1)},
    }
    substituted_state = state.model_copy(update=changes[substitution])
    altered_trade = original_trade.model_copy(update={"market_state_sha256": substituted_state.sha256})
    altered_oos = oos.model_copy(update={"trades": (altered_trade,) + oos.trades[1:]})
    records = dict(r.evidence._records)
    records[substituted_state.sha256] = substituted_state
    rr = VerificationResolvers(r.variants, ContentAddressedStore.build(records), r.datasets, r.engines, r.exposure)
    assert _verify_with_oos(b, rr, altered_oos).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_authoritatively_classified_regime_economic_failure_is_no_edge():
    b, r = fixture(regime_failure=True)
    use(r)
    result = verify_edge(b.sha256)
    gates = dict(result.gate_results)
    assert gates["REGIME_COHERENCE"] is True
    assert gates["REGIME_EVIDENCE"] is False
    assert result.verdict == EdgeVerdict.NO_EDGE


def test_preregistered_regime_cannot_be_omitted():
    b, r = fixture(omit_regime=True)
    use(r)
    assert verify_edge(b.sha256).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_policy_hash_is_pinned_and_registry_immutable():
    assert CANONICAL_POLICY_V1.sha256 == CANONICAL_POLICY_V1_SHA256 == "7eb2b129c6523f90a2fb041c2a6dcbe0287012307d96054bb3acee62c76beef8"
    with pytest.raises(TypeError):
        POLICY_REGISTRY["x"] = CANONICAL_POLICY_V1


def test_forged_artifact_fails_consumer_recompute():
    b, r = fixture()
    use(r)
    a = verify_edge(b.sha256)
    assert not validate_artifact(a.model_copy(update={"verdict": EdgeVerdict.NO_EDGE}))


def test_unapproved_engine_fails_closed():
    b, r = fixture()
    ind = r.evidence.resolve(b.parity_independent_trade_list_sha256).model_copy(update={"engine_id": "fake"})
    records = dict(r.evidence._records)
    records[ind.sha256] = ind
    bad = b.model_copy(update={"parity_independent_trade_list_sha256": ind.sha256})
    records[bad.sha256] = bad
    rr = VerificationResolvers(r.variants, ContentAddressedStore.build(records), r.datasets, r.engines, r.exposure)
    use(rr)
    assert verify_edge(bad.sha256).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_missing_friction_trade_list_fails_closed():
    b, r = fixture()
    f = r.evidence.resolve(b.friction_sha256)
    broken = f.model_copy(update={"multipliers": (1.0, 1.25)})
    records = dict(r.evidence._records)
    records[broken.sha256] = broken
    bad = b.model_copy(update={"friction_sha256": broken.sha256})
    records[bad.sha256] = bad
    rr = VerificationResolvers(r.variants, ContentAddressedStore.build(records), r.datasets, r.engines, r.exposure)
    use(rr)
    assert verify_edge(bad.sha256).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def _verify_with_friction(b, r, changed):
    records = dict(r.evidence._records)
    records[changed.sha256] = changed
    bad = b.model_copy(update={"friction_sha256": changed.sha256})
    records[bad.sha256] = bad
    rr = VerificationResolvers(r.variants, ContentAddressedStore.build(records), r.datasets, r.engines, r.exposure)
    use(rr)
    return verify_edge(bad.sha256)


def test_arbitrary_stressed_trade_lists_are_rejected():
    b, r = fixture()
    friction = r.evidence.resolve(b.friction_sha256)
    with pytest.raises(ValidationError):
        FrictionEvidenceRecord.model_validate({
            **friction.model_dump(mode="python"),
            "points": ((1.0, b.oos_trade_list_sha256), (1.25, "9" * 64), (1.5, "8" * 64)),
        })
    use(r)
    assert verify_edge(b.sha256).verdict == EdgeVerdict.EDGE_VERIFIED


def test_tampered_friction_model_cannot_replace_frozen_model():
    b, r = fixture()
    variant = r.variants.resolve(b.variant_sha256)
    model = r.evidence.resolve(variant.friction_model_sha256)
    tampered = model.model_copy(update={"model_id": "tampered"})
    with pytest.raises(ValueError):
        ContentAddressedStore.build({model.sha256: tampered})
    friction = r.evidence.resolve(b.friction_sha256).model_copy(update={"model_sha256": tampered.sha256})
    records = dict(r.evidence._records)
    records[tampered.sha256] = tampered
    records[friction.sha256] = friction
    result = _verify_with_friction(b, VerificationResolvers(r.variants, ContentAddressedStore.build(records), r.datasets, r.engines, r.exposure), friction)
    assert result.verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_friction_population_substitution_fails_closed():
    b, r = fixture()
    friction = r.evidence.resolve(b.friction_sha256).model_copy(
        update={"baseline_trade_list_sha256": b.parity_independent_trade_list_sha256}
    )
    assert _verify_with_friction(b, r, friction).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_deterministically_unprofitable_friction_stress_returns_no_edge():
    b, r = fixture(cost_r=0.8)
    use(r)
    result = verify_edge(b.sha256)
    gates = dict(result.gate_results)
    assert gates["FRICTION_COHERENCE"] is True
    assert gates["FRICTION_STRESS"] is False
    assert result.verdict == EdgeVerdict.NO_EDGE


def test_missing_baseline_cost_primitives_fail_closed():
    b, r = fixture()
    oos = r.evidence.resolve(b.oos_trade_list_sha256)
    trade = oos.trades[0].model_copy(update={
        "gross_r": None,
        "spread_cost_r": None,
        "commission_cost_r": None,
        "slippage_cost_r": None,
        "funding_cost_r": None,
    })
    altered_oos = oos.model_copy(update={"trades": (trade,) + oos.trades[1:]})
    friction = r.evidence.resolve(b.friction_sha256).model_copy(update={"baseline_trade_list_sha256": altered_oos.sha256})
    bad = b.model_copy(update={
        "oos_trade_list_sha256": altered_oos.sha256,
        "friction_sha256": friction.sha256,
        "parity_reference_trade_list_sha256": altered_oos.sha256,
    })
    records = dict(r.evidence._records)
    records.update({altered_oos.sha256: altered_oos, friction.sha256: friction, bad.sha256: bad})
    rr = VerificationResolvers(r.variants, ContentAddressedStore.build(records), r.datasets, r.engines, r.exposure)
    use(rr)
    assert verify_edge(bad.sha256).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_holdout_without_unseen_to_burned_event_fails_closed():
    b, r = fixture()
    event = ExposureEvent(dataset_sha256=next(iter(r.datasets._records)), previous=DatasetExposure.DEVELOPMENT, current=DatasetExposure.BURNED_HOLDOUT, observed_at=OOS_START)
    rr = VerificationResolvers(r.variants, r.evidence, r.datasets, r.engines, ExposureLedger((event,)))
    use(rr)
    assert verify_edge(b.sha256).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_out_of_window_oos_trade_fails_closed():
    b, r = fixture()
    oos = r.evidence.resolve(b.oos_trade_list_sha256)
    altered = oos.model_copy(update={"trades": (oos.trades[0].model_copy(update={"executed_at": OOS_END + timedelta(days=1)}),) + oos.trades[1:]})
    records = dict(r.evidence._records)
    records[altered.sha256] = altered
    bad = b.model_copy(update={"oos_trade_list_sha256": altered.sha256, "parity_reference_trade_list_sha256": altered.sha256})
    records[bad.sha256] = bad
    rr = VerificationResolvers(r.variants, ContentAddressedStore.build(records), r.datasets, r.engines, r.exposure)
    use(rr)
    assert verify_edge(bad.sha256).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_parity_must_cover_same_oos_population():
    b, r = fixture()
    ind = r.evidence.resolve(b.parity_independent_trade_list_sha256)
    shortened = ind.model_copy(update={"trades": ind.trades[:1]})
    records = dict(r.evidence._records)
    records[shortened.sha256] = shortened
    bad = b.model_copy(update={"parity_independent_trade_list_sha256": shortened.sha256})
    records[bad.sha256] = bad
    rr = VerificationResolvers(r.variants, ContentAddressedStore.build(records), r.datasets, r.engines, r.exposure)
    use(rr)
    assert verify_edge(bad.sha256).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_stability_cannot_borrow_other_strategy():
    b, r = fixture()
    stability = r.evidence.resolve(b.stability_sha256)
    value, sha = stability.neighborhoods[0]
    borrowed = r.evidence.resolve(sha).model_copy(update={"strategy_sha256": "f" * 64})
    records = dict(r.evidence._records)
    records[borrowed.sha256] = borrowed
    altered = stability.model_copy(update={"neighborhoods": ((value, borrowed.sha256),) + stability.neighborhoods[1:]})
    records[altered.sha256] = altered
    bad = b.model_copy(update={"stability_sha256": altered.sha256})
    records[bad.sha256] = bad
    rr = VerificationResolvers(r.variants, ContentAddressedStore.build(records), r.datasets, r.engines, r.exposure)
    use(rr)
    assert verify_edge(bad.sha256).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE
