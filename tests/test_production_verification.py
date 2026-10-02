from datetime import datetime, timezone, timedelta
import pytest
from pydantic import ValidationError

from ag_edgelab.optimization.contracts import DatasetExposure
from ag_edgelab.contracts.dataset import DatasetRole
from ag_edgelab.data.fingerprint import canonical_json
from ag_edgelab.verification.evidence import DatasetRecord, FRICTION_IMPLEMENTATION_SHA256, REGIME_CLASSIFIER_IMPLEMENTATION_SHA256, FrictionEvidenceRecord, FrictionModelRecord, MarketStateRecord, ParameterNeighborRecord, ParameterSetRecord, PopulationDefinitionRecord, RegimeClassifierRecord, StabilityEvidenceRecord, TradeListRecord, TradeOutcome, ValidationBundleRecord, WalkForwardEvidenceRecord, WalkForwardFoldRecord
from ag_edgelab.verification.production import CANONICAL_POLICY_V1, CANONICAL_POLICY_V1_SHA256, EdgeVerifier, EdgeVerdict, POLICY_REGISTRY, VerificationContext
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


def tl(engine, code, delta=0.0, n=80, dataset="d" * 64, start=OOS_START + timedelta(hours=1), cost_r=0.02, market_states=None, regime_failure=False, parameter_set_sha256=None, population_definition_sha256=None):
    return TradeListRecord(
        dataset_sha256=dataset,
        strategy_sha256=STRAT,
        engine_id=engine,
        engine_code_sha256=code,
        parameter_set_sha256=parameter_set_sha256,
        population_definition_sha256=population_definition_sha256,
        trades=trades(delta, n, start, cost_r, dataset if market_states is not None else None, market_states, regime_failure),
    )


def fixture(*, negative=False, omit_regime=False, cost_r=0.02, regime_failure=False):
    dataset = DatasetRecord(dataset_sha256="d" * 64, start=OOS_START, end=OOS_END, role="OOS")
    data_ref = dataset.sha256
    development_start = datetime(2025, 12, 1, tzinfo=Z)
    development_end = datetime(2026, 1, 20, tzinfo=Z)
    development_dataset = DatasetRecord(
        dataset_sha256="c" * 64, start=development_start, end=development_end, role="DEVELOPMENT"
    )
    development_ref = development_dataset.sha256
    population = PopulationDefinitionRecord(
        dataset_sha256=development_ref, start=development_start, end=development_end
    )
    re = EngineRecord(engine_id="ref", code_sha256="1" * 64, independence_group="A")
    ie = EngineRecord(engine_id="ind", code_sha256="2" * 64, independence_group="B")
    engines = EngineRegistry.owner_approved_pair((re, ie))
    friction_model = FrictionModelRecord(model_id="normalized-r", version="1", implementation_sha256=FRICTION_IMPLEMENTATION_SHA256)
    classifier = RegimeClassifierRecord(
        classifier_id="ohlc-direction", version="1",
        implementation_sha256=REGIME_CLASSIFIER_IMPLEMENTATION_SHA256,
    )
    center_parameters = ParameterSetRecord.create("S", "synthetic-v1", {"sensitivity": 1.2})
    variant = FrozenVariantRecord(
        strategy_id="S",
        strategy_version="1",
        strategy_sha256=STRAT,
        friction_model_sha256=friction_model.sha256,
        funnel_sha256="b" * 64,
        parameters_sha256=center_parameters.sha256,
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
    wf_datasets = []
    wf_populations = []
    wf_exposure = []
    for i, h in enumerate(("6", "7", "8")):
        start = datetime(2025, 1, 1, tzinfo=Z) + timedelta(days=i * 100)
        test_start = start + timedelta(days=40)
        test_end = start + timedelta(days=60)
        train_dataset = DatasetRecord(dataset_sha256=str(3 + i) * 64, start=start, end=test_start, role="DEVELOPMENT")
        test_dataset = DatasetRecord(dataset_sha256=h * 64, start=test_start, end=test_end, role="VALIDATION")
        wf_datasets.extend((train_dataset, test_dataset))
        population_i = PopulationDefinitionRecord(dataset_sha256=test_dataset.sha256, start=test_start, end=test_end)
        wf_populations.append(population_i)
        x = tl("ref", "1" * 64, d, n=40, dataset=test_dataset.sha256, start=test_start + timedelta(hours=1))
        fold_lists.append(x)
        wf_exposure.extend((
            ExposureEvent(dataset_sha256=train_dataset.sha256, previous=DatasetExposure.UNSEEN, current=DatasetExposure.DEVELOPMENT, observed_at=start),
            ExposureEvent(dataset_sha256=test_dataset.sha256, previous=DatasetExposure.UNSEEN, current=DatasetExposure.OBSERVED_VALIDATION, observed_at=test_end),
        ))
        folds.append(
            WalkForwardFoldRecord(
                fold_id=f"F{i}",
                train_start=start,
                train_end=test_start,
                test_start=test_start,
                test_end=test_end,
                trade_list_sha256=x.sha256,
                train_dataset_sha256=train_dataset.sha256,
                test_dataset_sha256=test_dataset.sha256,
                variant_sha256=variant.sha256,
                engine_id="ref",
                engine_code_sha256="1" * 64,
                population_definition_sha256=population_i.sha256,
            )
        )
    wf = WalkForwardEvidenceRecord(folds=tuple(folds))

    center_trade_list = tl(
        "ref", "1" * 64, d + .02, n=40, dataset=development_ref,
        start=development_start + timedelta(hours=1),
        parameter_set_sha256=center_parameters.sha256,
        population_definition_sha256=population.sha256,
    )
    neighbor_records = []
    stability_parameters = []
    stability_runs = [center_trade_list]
    neighbor_deltas = ((1.0, d), (1.4, d + .01))
    for i, (value, delta) in enumerate(neighbor_deltas):
        params = ParameterSetRecord.create("S", "synthetic-v1", {"sensitivity": value})
        stability_parameters.append(params)
        run = tl(
            "ref", "1" * 64, delta, n=40, dataset=development_ref,
            start=development_start + timedelta(hours=1),
            parameter_set_sha256=params.sha256,
            population_definition_sha256=population.sha256,
        )
        stability_runs.append(run)
        neighbor_records.append(ParameterNeighborRecord(
            mutation_id=f"sensitivity-{i}", parameter_set_sha256=params.sha256,
            changed_parameter="sensitivity", old_value_json="1.2",
            new_value_json=str(value), trade_list_sha256=run.sha256,
        ))
    stability = StabilityEvidenceRecord(
        base_variant_sha256=variant.sha256,
        base_parameter_set_sha256=center_parameters.sha256,
        development_dataset_sha256=development_ref,
        population_definition_sha256=population.sha256,
        engine_id="ref", engine_code_sha256="1" * 64,
        created_at=datetime(2026, 1, 15, tzinfo=Z),
        center_parameter_set_sha256=center_parameters.sha256,
        center_trade_list_sha256=center_trade_list.sha256,
        parameter_name="sensitivity", neighbors=tuple(neighbor_records),
    )

    records = [oos, ind, friction_model, classifier, *market_states, *fold_lists, *wf_populations,
               center_parameters, *stability_parameters, population, *stability_runs, friction, wf, stability]
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
    development_exposure = ExposureEvent(
        dataset_sha256=development_ref,
        previous=DatasetExposure.UNSEEN,
        current=DatasetExposure.DEVELOPMENT,
        observed_at=development_start,
    )
    opened = ExposureEvent(
        dataset_sha256=data_ref,
        previous=DatasetExposure.UNSEEN,
        current=DatasetExposure.BURNED_HOLDOUT,
        observed_at=OOS_START,
    )
    resolvers = VerificationResolvers(
        ContentAddressedStore.build({variant.sha256: variant}),
        store,
        ContentAddressedStore.build({x.sha256: x for x in (dataset, development_dataset, *wf_datasets)}),
        engines,
        ExposureLedger((development_exposure, opened, *wf_exposure)),
    )
    return bundle, resolvers


def readdress_oos_dataset_role(bundle, resolvers, role):
    original_oos = resolvers.evidence.resolve(bundle.oos_trade_list_sha256)
    dataset = resolvers.datasets.resolve(original_oos.dataset_sha256)
    changed_dataset = dataset.model_copy(update={"role": role})
    old_ref, new_ref = dataset.sha256, changed_dataset.sha256
    old_states = {key: value for key, value in resolvers.evidence._records.items()
                  if isinstance(value, MarketStateRecord) and value.dataset_sha256 == old_ref}
    changed_states = {key: value.model_copy(update={"dataset_sha256": new_ref})
                      for key, value in old_states.items()}
    state_hashes = {old: updated.sha256 for old, updated in changed_states.items()}
    old_trade_lists = {key: value for key, value in resolvers.evidence._records.items()
                       if isinstance(value, TradeListRecord) and value.dataset_sha256 == old_ref}
    changed_trade_lists = {}
    for key, trade_list in old_trade_lists.items():
        changed_trades = tuple(trade.model_copy(update={
            "market_state_sha256": state_hashes.get(trade.market_state_sha256, trade.market_state_sha256)
        }) for trade in trade_list.trades)
        changed_trade_lists[key] = trade_list.model_copy(update={
            "dataset_sha256": new_ref, "trades": changed_trades
        })
    changed_oos = changed_trade_lists[bundle.oos_trade_list_sha256]
    changed_ind = changed_trade_lists[bundle.parity_independent_trade_list_sha256]
    friction = resolvers.evidence.resolve(bundle.friction_sha256).model_copy(update={
        "baseline_trade_list_sha256": changed_oos.sha256
    })
    records = {key: value for key, value in resolvers.evidence._records.items()
               if key not in old_states and key not in old_trade_lists}
    records.update({item.sha256: item for item in (*changed_states.values(), *changed_trade_lists.values())})
    records[friction.sha256] = friction
    changed_bundle = bundle.model_copy(update={
        "oos_trade_list_sha256": changed_oos.sha256,
        "friction_sha256": friction.sha256,
        "parity_reference_trade_list_sha256": changed_oos.sha256,
        "parity_independent_trade_list_sha256": changed_ind.sha256,
    })
    records[changed_bundle.sha256] = changed_bundle
    datasets = {key: value for key, value in resolvers.datasets._records.items() if key != old_ref}
    datasets[new_ref] = changed_dataset
    events = tuple(event.model_copy(update={"dataset_sha256": new_ref})
                   if event.dataset_sha256 == old_ref else event for event in resolvers.exposure.events)
    changed_resolvers = VerificationResolvers(
        resolvers.variants, ContentAddressedStore.build(records), ContentAddressedStore.build(datasets),
        resolvers.engines, ExposureLedger(events),
    )
    return changed_bundle, changed_resolvers


_active_verifier = None


def use(resolvers):
    global _active_verifier
    _active_verifier = EdgeVerifier(VerificationContext(resolvers))


def verify_edge(evidence_id):
    return _active_verifier.verify_edge(evidence_id)


def validate_artifact(artifact):
    return _active_verifier.validate_artifact(artifact)


def test_verifier_authority_is_invocation_scoped_and_cannot_be_replaced():
    b_a, r_a = fixture()
    b_b, r_b = fixture(negative=True)
    verifier_a = EdgeVerifier(VerificationContext(r_a))
    verifier_b = EdgeVerifier(VerificationContext(r_b))
    a_first = verifier_a.verify_edge(b_a.sha256)
    b_result = verifier_b.verify_edge(b_b.sha256)
    a_second = verifier_a.verify_edge(b_a.sha256)
    assert a_first.verdict == EdgeVerdict.EDGE_VERIFIED
    assert b_result.verdict == EdgeVerdict.NO_EDGE
    assert a_second == a_first


def test_exposure_ledger_rejects_duplicate_or_backward_timestamps():
    start = ExposureEvent(dataset_sha256="e" * 64, previous=DatasetExposure.UNSEEN,
                          current=DatasetExposure.DEVELOPMENT, observed_at=OOS_START)
    duplicate = ExposureEvent(dataset_sha256=start.dataset_sha256, previous=DatasetExposure.DEVELOPMENT,
                              current=DatasetExposure.OBSERVED_VALIDATION, observed_at=OOS_START,
                              previous_event_sha256=start.sha256)
    with pytest.raises(ValueError, match="timestamps"):
        ExposureLedger((start, duplicate))


def test_policy_spoof_is_not_an_edge_verifier_input():
    class FakePolicy:
        @property
        def sha256(self):
            return CANONICAL_POLICY_V1_SHA256

        min_walk_forward_folds = 0
        min_walk_forward_trades_per_fold = 0
        min_positive_walk_forward_fraction = 0.0

    bundle, resolvers = fixture()
    wf = resolvers.evidence.resolve(bundle.walk_forward_sha256)
    short_wf = wf.model_copy(update={"folds": wf.folds[:2]})
    short_bundle = bundle.model_copy(update={"walk_forward_sha256": short_wf.sha256})
    records = dict(resolvers.evidence._records)
    records.update({short_wf.sha256: short_wf, short_bundle.sha256: short_bundle})
    authority = VerificationResolvers(resolvers.variants, ContentAddressedStore.build(records),
                                     resolvers.datasets, resolvers.engines, resolvers.exposure)
    verifier = EdgeVerifier(VerificationContext(authority))
    assert verifier.verify_edge(short_bundle.sha256).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE
    with pytest.raises(TypeError):
        VerificationContext(authority, FakePolicy())
    with pytest.raises(TypeError):
        verify_edge(short_bundle.sha256, VerificationContext(authority), policy=FakePolicy())


def verify_with_stability(bundle, resolvers, experiment, extra_records=(), datasets=None):
    records = dict(resolvers.evidence._records)
    records.update({record.sha256: record for record in extra_records})
    records[experiment.sha256] = experiment
    changed_bundle = bundle.model_copy(update={"stability_sha256": experiment.sha256})
    records[changed_bundle.sha256] = changed_bundle
    authority = VerificationResolvers(
        resolvers.variants, ContentAddressedStore.build(records),
        datasets or resolvers.datasets, resolvers.engines, resolvers.exposure,
    )
    use(authority)
    return verify_edge(changed_bundle.sha256)


def test_positive_raw_evidence_can_verify():
    b, r = fixture()
    use(r)
    oos = r.evidence.resolve(b.oos_trade_list_sha256)
    assert r.datasets.resolve(oos.dataset_sha256).role == DatasetRole.OOS
    a = verify_edge(b.sha256)
    assert a.verdict == EdgeVerdict.EDGE_VERIFIED
    assert dict(a.gate_results)["STABILITY_COHERENCE"]
    assert dict(a.gate_results)["PARAMETER_STABILITY"]
    assert validate_artifact(a)


def test_readdressed_development_dataset_cannot_verify_as_oos():
    bundle, resolvers = fixture()
    changed_bundle, changed_resolvers = readdress_oos_dataset_role(
        bundle, resolvers, DatasetRole.DEVELOPMENT
    )
    use(changed_resolvers)
    result = verify_edge(changed_bundle.sha256)
    assert result.verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE
    assert result.reasons == ("INVALID_OOS_DATASET_ROLE_OR_EXPOSURE",)


def test_coherent_negative_is_no_edge():
    b, r = fixture(negative=True)
    use(r)
    assert verify_edge(b.sha256).verdict == EdgeVerdict.NO_EDGE


def test_unknown_and_fabricated_strategy_ids_fail_closed():
    _, r = fixture()
    use(r)
    assert verify_edge("f" * 64).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_fabricated_positive_strategy_identity_fails_closed():
    bundle, resolvers = fixture()
    original = resolvers.variants.resolve(bundle.variant_sha256)
    fabricated = original.model_copy(update={"strategy_id": "NONEXISTENT", "strategy_sha256": "f" * 64})
    changed = bundle.model_copy(update={"variant_sha256": fabricated.sha256})
    variants = ContentAddressedStore.build({fabricated.sha256: fabricated})
    evidence = ContentAddressedStore.build({**dict(resolvers.evidence._records), changed.sha256: changed})
    use(VerificationResolvers(variants, evidence, resolvers.datasets, resolvers.engines, resolvers.exposure))
    assert verify_edge(changed.sha256).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_walk_forward_unknown_dataset_fails_closed():
    bundle, resolvers = fixture()
    wf = resolvers.evidence.resolve(bundle.walk_forward_sha256)
    first = wf.folds[0].model_copy(update={"test_dataset_sha256": "0" * 64})
    changed_wf = wf.model_copy(update={"folds": (first, *wf.folds[1:])})
    changed_bundle = bundle.model_copy(update={"walk_forward_sha256": changed_wf.sha256})
    records = dict(resolvers.evidence._records)
    records.update({changed_wf.sha256: changed_wf, changed_bundle.sha256: changed_bundle})
    use(VerificationResolvers(resolvers.variants, ContentAddressedStore.build(records), resolvers.datasets,
                              resolvers.engines, resolvers.exposure))
    assert verify_edge(changed_bundle.sha256).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


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
    assert CANONICAL_POLICY_V1.sha256 == CANONICAL_POLICY_V1_SHA256 == "7ca7ec59c7868bc93b4c5cf5ee58babd51ab99a18876f2cfef647445532f33b3"
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
    neighbor = stability.neighbors[0]
    sha = neighbor.trade_list_sha256
    borrowed = r.evidence.resolve(sha).model_copy(update={"strategy_sha256": "f" * 64})
    records = dict(r.evidence._records)
    records[borrowed.sha256] = borrowed
    altered_neighbor = neighbor.model_copy(update={"trade_list_sha256": borrowed.sha256})
    altered = stability.model_copy(update={"neighbors": (altered_neighbor,) + stability.neighbors[1:]})
    records[altered.sha256] = altered
    bad = b.model_copy(update={"stability_sha256": altered.sha256})
    records[bad.sha256] = bad
    rr = VerificationResolvers(r.variants, ContentAddressedStore.build(records), r.datasets, r.engines, r.exposure)
    use(rr)
    assert verify_edge(bad.sha256).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_unrelated_profitable_trade_list_cannot_be_borrowed_as_neighbor():
    b, r = fixture()
    experiment = r.evidence.resolve(b.stability_sha256)
    neighbor = experiment.neighbors[0].model_copy(update={"trade_list_sha256": b.oos_trade_list_sha256})
    altered = experiment.model_copy(update={"neighbors": (neighbor,) + experiment.neighbors[1:]})
    assert verify_with_stability(b, r, altered).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_stability_center_must_match_frozen_parameters():
    b, r = fixture()
    experiment = r.evidence.resolve(b.stability_sha256)
    altered = experiment.model_copy(update={"center_parameter_set_sha256": experiment.neighbors[0].parameter_set_sha256})
    assert verify_with_stability(b, r, altered).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_fake_mutation_with_undeclared_parameter_difference_fails_closed():
    b, r = fixture()
    experiment = r.evidence.resolve(b.stability_sha256)
    neighbor = experiment.neighbors[0]
    original_params = r.evidence.resolve(neighbor.parameter_set_sha256)
    fake_params = ParameterSetRecord.create(
        "S", "synthetic-v1", {"sensitivity": 1.0, "undeclared": 7}
    )
    original_run = r.evidence.resolve(neighbor.trade_list_sha256)
    fake_run = original_run.model_copy(update={"parameter_set_sha256": fake_params.sha256})
    fake_neighbor = neighbor.model_copy(update={
        "parameter_set_sha256": fake_params.sha256,
        "trade_list_sha256": fake_run.sha256,
    })
    altered = experiment.model_copy(update={"neighbors": (fake_neighbor,) + experiment.neighbors[1:]})
    result = verify_with_stability(b, r, altered, (fake_params, fake_run))
    assert original_params.parameters == {"sensitivity": 1.0}
    assert result.verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_neighbor_from_wrong_strategy_family_fails_closed():
    b, r = fixture()
    experiment = r.evidence.resolve(b.stability_sha256)
    neighbor = experiment.neighbors[0]
    params = ParameterSetRecord.create("OTHER", "synthetic-v1", {"sensitivity": 1.0})
    run = r.evidence.resolve(neighbor.trade_list_sha256).model_copy(update={"parameter_set_sha256": params.sha256})
    altered_neighbor = neighbor.model_copy(update={"parameter_set_sha256": params.sha256, "trade_list_sha256": run.sha256})
    altered = experiment.model_copy(update={"neighbors": (altered_neighbor,) + experiment.neighbors[1:]})
    assert verify_with_stability(b, r, altered, (params, run)).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_population_substitution_fails_closed():
    b, r = fixture()
    experiment = r.evidence.resolve(b.stability_sha256)
    population = r.evidence.resolve(experiment.population_definition_sha256)
    altered_population = PopulationDefinitionRecord(
        dataset_sha256=population.dataset_sha256,
        start=population.start + timedelta(days=1), end=population.end,
    )
    altered = experiment.model_copy(update={"population_definition_sha256": altered_population.sha256})
    assert verify_with_stability(b, r, altered, (altered_population,)).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_non_development_dataset_fails_closed():
    b, r = fixture()
    experiment = r.evidence.resolve(b.stability_sha256)
    original = r.datasets.resolve(experiment.development_dataset_sha256)
    validation = DatasetRecord(
        dataset_sha256=original.dataset_sha256, start=original.start,
        end=original.end, role="VALIDATION",
    )
    altered = experiment.model_copy(update={"development_dataset_sha256": validation.sha256})
    datasets = ContentAddressedStore.build({**dict(r.datasets._records), validation.sha256: validation})
    exposure_event = ExposureEvent(
        dataset_sha256=validation.sha256, previous=DatasetExposure.UNSEEN,
        current=DatasetExposure.OBSERVED_VALIDATION, observed_at=original.start,
    )
    rr = VerificationResolvers(r.variants, r.evidence, datasets, r.engines, ExposureLedger(r.exposure.events + (exposure_event,)))
    assert verify_with_stability(b, rr, altered).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_approved_alternate_engine_cannot_be_substituted_for_stability_runs():
    b, r = fixture()
    experiment = r.evidence.resolve(b.stability_sha256)
    altered = experiment.model_copy(update={"engine_id": "ind", "engine_code_sha256": "2" * 64})
    assert verify_with_stability(b, r, altered).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_stability_experiment_after_holdout_open_fails_closed():
    b, r = fixture()
    experiment = r.evidence.resolve(b.stability_sha256)
    altered = experiment.model_copy(update={"created_at": OOS_START + timedelta(days=1)})
    assert verify_with_stability(b, r, altered).verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE


def test_authoritative_but_unstable_parameter_neighborhood_returns_no_edge():
    b, r = fixture()
    experiment = r.evidence.resolve(b.stability_sha256)
    center_params = r.evidence.resolve(experiment.center_parameter_set_sha256)
    dev_start = r.datasets.resolve(experiment.development_dataset_sha256).start
    center = tl(
        "ref", "1" * 64, .99, n=40, dataset=experiment.development_dataset_sha256,
        start=dev_start + timedelta(hours=1), parameter_set_sha256=center_params.sha256,
        population_definition_sha256=experiment.population_definition_sha256,
    )
    neighbors = []
    runs = [center]
    for record, delta in zip(experiment.neighbors, (-.75, .01)):
        run = tl(
            "ref", "1" * 64, delta, n=40, dataset=experiment.development_dataset_sha256,
            start=dev_start + timedelta(hours=1), parameter_set_sha256=record.parameter_set_sha256,
            population_definition_sha256=experiment.population_definition_sha256,
        )
        runs.append(run)
        neighbors.append(record.model_copy(update={"trade_list_sha256": run.sha256}))
    altered = experiment.model_copy(update={"center_trade_list_sha256": center.sha256, "neighbors": tuple(neighbors)})
    result = verify_with_stability(b, r, altered, tuple(runs))
    gates = dict(result.gate_results)
    assert gates["STABILITY_COHERENCE"] is True
    assert gates["PARAMETER_STABILITY"] is False
    assert result.verdict == EdgeVerdict.NO_EDGE
