from datetime import datetime, timezone

import pytest

from ag_edgelab.optimization.contracts import DatasetExposure
from ag_edgelab.verification.evidence import FrictionModelRecord, FRICTION_IMPLEMENTATION_SHA256
from ag_edgelab.verification.provenance import (
    ContentAddressedStore, EngineRecord, ExposureEvent, ExposureLedger,
    FrozenVariantRecord, UnknownProvenanceError,
)


def test_unknown_content_hash_fails_closed():
    store = ContentAddressedStore.build({})
    with pytest.raises(UnknownProvenanceError):
        store.resolve("a" * 64)


def test_frozen_variant_binds_preregistered_regimes():
    friction_model = FrictionModelRecord(model_id="normalized-r", version="1", implementation_sha256=FRICTION_IMPLEMENTATION_SHA256)
    record = FrozenVariantRecord(
        strategy_id="S", strategy_version="1", strategy_sha256="a"*64,
        friction_model_sha256=friction_model.sha256,
        funnel_sha256="b"*64, parameters_sha256="c"*64,
        claimed_regimes=("TREND", "RANGE"), regime_classifier_sha256="d"*64,
        frozen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    store = ContentAddressedStore.build({record.sha256: record})
    assert store.resolve(record.sha256).claimed_regimes == ("TREND", "RANGE")


def test_burned_holdout_cannot_downgrade():
    with pytest.raises(ValueError):
        ExposureEvent(
            dataset_sha256="a"*64,
            previous=DatasetExposure.BURNED_HOLDOUT,
            current=DatasetExposure.UNSEEN,
            observed_at=datetime.now(timezone.utc),
        )


def test_exposure_ledger_is_hash_chained():
    first = ExposureEvent(
        dataset_sha256="a"*64, previous=DatasetExposure.UNSEEN,
        current=DatasetExposure.BURNED_HOLDOUT,
        observed_at=datetime(2026,1,1,tzinfo=timezone.utc),
    )
    ledger = ExposureLedger((first,))
    assert ledger.state("a"*64) == DatasetExposure.BURNED_HOLDOUT
    assert ledger.proof_sha256("a"*64) == first.sha256
    with pytest.raises(ValueError):
        ExposureLedger((first, ExposureEvent(
            dataset_sha256="a"*64, previous=DatasetExposure.BURNED_HOLDOUT,
            current=DatasetExposure.BURNED_HOLDOUT,
            observed_at=datetime(2026,1,2,tzinfo=timezone.utc),
            previous_event_sha256="f"*64,
        )))


def test_engine_registry_carries_independence_group():
    ref = EngineRecord(engine_id="reference", code_sha256="a"*64, independence_group="engine-a")
    ind = EngineRecord(engine_id="independent", code_sha256="b"*64, independence_group="engine-b")
    store = ContentAddressedStore.build({ref.sha256: ref, ind.sha256: ind})
    assert store.resolve(ref.sha256).independence_group != store.resolve(ind.sha256).independence_group
