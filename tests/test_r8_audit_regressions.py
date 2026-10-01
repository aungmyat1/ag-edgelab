from datetime import datetime, timezone, timedelta
import pytest
from pydantic import ValidationError
from ag_edgelab.optimization.contracts import DatasetExposure
from ag_edgelab.verification.evidence import TradeOutcome, TradeListRecord, FrictionEvidenceRecord, WalkForwardFoldRecord, WalkForwardEvidenceRecord
from ag_edgelab.verification.provenance import ContentAddressedStore, EngineRecord, EngineRegistry, ExposureEvent, ExposureLedger

Z=timezone.utc

def test_nonfinite_raw_outcome_rejected():
    with pytest.raises(ValidationError): TradeOutcome(trade_id="x",r=float("nan"),regime="R")
    with pytest.raises(ValidationError): TradeOutcome(trade_id="x",r=float("inf"),regime="R")

def test_content_address_cannot_lie():
    x=EngineRecord(engine_id="e",code_sha256="a"*64,independence_group="g")
    with pytest.raises(ValueError): ContentAddressedStore.build({"b"*64:x})

def test_engine_pair_must_be_owner_approved_and_independent():
    a=EngineRecord(engine_id="a",code_sha256="a"*64,independence_group="g")
    with pytest.raises(ValueError): EngineRegistry.owner_approved_pair((a,a))
    b=EngineRecord(engine_id="b",code_sha256="b"*64,independence_group="h",owner_approved=False)
    with pytest.raises(ValueError): EngineRegistry.owner_approved_pair((a,b))

def test_duplicate_trade_ids_rejected():
    t=TradeOutcome(trade_id="x",r=1,regime="R")
    with pytest.raises(ValidationError): TradeListRecord(dataset_sha256="a"*64,strategy_sha256="b"*64,engine_id="e",engine_code_sha256="c"*64,trades=(t,t))

def test_duplicate_or_invalid_friction_grid_rejected():
    with pytest.raises(ValidationError): FrictionEvidenceRecord(points=((1.0,"a"*64),(1.0,"b"*64)))
    with pytest.raises(ValidationError): FrictionEvidenceRecord(points=((float("inf"),"a"*64),))

def test_walk_forward_overlap_and_reverse_rejected():
    s=datetime(2025,1,1,tzinfo=Z)
    with pytest.raises(ValidationError): WalkForwardFoldRecord(fold_id="x",train_start=s,train_end=s+timedelta(days=2),test_start=s+timedelta(days=1),test_end=s+timedelta(days=3),trade_list_sha256="a"*64)
    a=WalkForwardFoldRecord(fold_id="a",train_start=s,train_end=s+timedelta(days=1),test_start=s+timedelta(days=1),test_end=s+timedelta(days=3),trade_list_sha256="a"*64)
    b=WalkForwardFoldRecord(fold_id="b",train_start=s+timedelta(days=3),train_end=s+timedelta(days=4),test_start=s+timedelta(days=2),test_end=s+timedelta(days=5),trade_list_sha256="b"*64)
    with pytest.raises(ValidationError): WalkForwardEvidenceRecord(folds=(a,b))

def test_burned_holdout_is_absorbing_and_chain_is_checked():
    with pytest.raises(ValidationError): ExposureEvent(dataset_sha256="a"*64,previous=DatasetExposure.BURNED_HOLDOUT,current=DatasetExposure.UNSEEN,observed_at=datetime.now(Z))
    first=ExposureEvent(dataset_sha256="a"*64,previous=DatasetExposure.UNSEEN,current=DatasetExposure.BURNED_HOLDOUT,observed_at=datetime.now(Z))
    second=ExposureEvent(dataset_sha256="a"*64,previous=DatasetExposure.BURNED_HOLDOUT,current=DatasetExposure.BURNED_HOLDOUT,observed_at=datetime.now(Z),previous_event_sha256="f"*64)
    with pytest.raises(ValueError): ExposureLedger((first,second))
