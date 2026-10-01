from datetime import datetime, timezone, timedelta

import pytest

from ag_edgelab.optimization.contracts import DatasetExposure
from ag_edgelab.verification.evidence import FrictionEvidenceRecord, StabilityEvidenceRecord, TradeListRecord, TradeOutcome, ValidationBundleRecord, WalkForwardEvidenceRecord, WalkForwardFoldRecord
from ag_edgelab.verification.production import CANONICAL_POLICY_V1, CANONICAL_POLICY_V1_SHA256, EdgeVerdict, POLICY_REGISTRY, validate_artifact, verify_edge
from ag_edgelab.verification.provenance import ContentAddressedStore, EngineRecord, EngineRegistry, ExposureEvent, ExposureLedger, FrozenVariantRecord, VerificationResolvers

Z=timezone.utc; DATA="d"*64; STRAT="a"*64

def trades(delta=0.0,n=80):
    out=[]
    for i in range(n):
        base=.5 if i%4 else -.5
        out.append(TradeOutcome(trade_id=f"t{i}",r=base+delta,regime="TREND" if i<40 else "RANGE"))
    return tuple(out)

def tl(engine,code,delta=0.0,n=80,dataset=DATA): return TradeListRecord(dataset_sha256=dataset,strategy_sha256=STRAT,engine_id=engine,engine_code_sha256=code,trades=trades(delta,n))

def fixture(*,negative=False,omit_regime=False):
    ref_engine=EngineRecord(engine_id="ref",code_sha256="1"*64,independence_group="A")
    ind_engine=EngineRecord(engine_id="ind",code_sha256="2"*64,independence_group="B")
    engines=EngineRegistry.owner_approved_pair((ref_engine,ind_engine))
    variant=FrozenVariantRecord(strategy_id="S",strategy_version="1",strategy_sha256=STRAT,funnel_sha256="b"*64,parameters_sha256="c"*64,claimed_regimes=("TREND",) if omit_regime else ("TREND","RANGE"),regime_classifier_sha256="e"*64,frozen_at=datetime(2026,1,1,tzinfo=Z))
    base_delta=-.5 if negative else 0.0
    oos=tl("ref","1"*64,base_delta); ref=oos; ind=tl("ind","2"*64,base_delta-.005)
    f1=oos; f125=tl("ref","1"*64,base_delta-.05); f15=tl("ref","1"*64,base_delta-.10)
    friction=FrictionEvidenceRecord(points=((1.0,f1.sha256),(1.25,f125.sha256),(1.5,f15.sha256)))
    fold_lists=[]; folds=[]
    for i in range(3):
        x=tl("ref","1"*64,base_delta,n=40,dataset=chr(102+i)*64); fold_lists.append(x)
        start=datetime(2025,1,1,tzinfo=Z)+timedelta(days=i*100)
        folds.append(WalkForwardFoldRecord(fold_id=f"F{i}",train_start=start,train_end=start+timedelta(days=40),test_start=start+timedelta(days=40),test_end=start+timedelta(days=60),trade_list_sha256=x.sha256))
    wf=WalkForwardEvidenceRecord(folds=tuple(folds))
    s_lists=[]; neighborhoods=[]
    for i,v in enumerate((1.0,1.2,1.4)):
        x=tl("ref","1"*64,base_delta+(0.0,.02,.01)[i],n=40,dataset=chr(107+i)*64); s_lists.append(x); neighborhoods.append((v,x.sha256))
    stability=StabilityEvidenceRecord(center=1.2,neighborhoods=tuple(neighborhoods))
    records=[oos,ind,f125,f15,*fold_lists,*s_lists,friction,wf,stability]
    store=ContentAddressedStore.build({x.sha256:x for x in records})
    bundle=ValidationBundleRecord(variant_sha256=variant.sha256,oos_trade_list_sha256=oos.sha256,friction_sha256=friction.sha256,walk_forward_sha256=wf.sha256,stability_sha256=stability.sha256,parity_reference_trade_list_sha256=ref.sha256,parity_independent_trade_list_sha256=ind.sha256)
    store=ContentAddressedStore.build({**dict(store._records),bundle.sha256:bundle})
    opened=ExposureEvent(dataset_sha256=DATA,previous=DatasetExposure.UNSEEN,current=DatasetExposure.BURNED_HOLDOUT,observed_at=datetime(2026,2,1,tzinfo=Z))
    r=VerificationResolvers(ContentAddressedStore.build({variant.sha256:variant}),store,engines,ExposureLedger((opened,)))
    return bundle,r

def test_positive_raw_evidence_can_verify():
    b,r=fixture(); a=verify_edge(b.sha256,r); assert a.verdict==EdgeVerdict.EDGE_VERIFIED; assert validate_artifact(a,r)

def test_coherent_negative_is_no_edge():
    b,r=fixture(negative=True); assert verify_edge(b.sha256,r).verdict==EdgeVerdict.NO_EDGE

def test_unknown_and_fabricated_strategy_ids_fail_closed():
    _,r=fixture(); assert verify_edge("f"*64,r).verdict==EdgeVerdict.INSUFFICIENT_EVIDENCE

def test_preregistered_regime_cannot_be_omitted():
    b,r=fixture(omit_regime=True); assert verify_edge(b.sha256,r).verdict==EdgeVerdict.INSUFFICIENT_EVIDENCE

def test_policy_hash_is_pinned_and_registry_immutable():
    assert CANONICAL_POLICY_V1.sha256==CANONICAL_POLICY_V1_SHA256=="7eb2b129c6523f90a2fb041c2a6dcbe0287012307d96054bb3acee62c76beef8"
    with pytest.raises(TypeError): POLICY_REGISTRY["x"]=CANONICAL_POLICY_V1

def test_boolean_frozen_unseen_inputs_do_not_exist():
    b,_=fixture(); assert "holdout_was_unseen" not in b.model_fields and "candidate_was_frozen" not in b.model_fields

def test_forged_artifact_fails_consumer_recompute():
    b,r=fixture(); a=verify_edge(b.sha256,r); forged=a.model_copy(update={"verdict":EdgeVerdict.NO_EDGE}); assert not validate_artifact(forged,r)

def test_unapproved_engine_fails_closed():
    b,r=fixture(); ind=_resolve_record(r,b.parity_independent_trade_list_sha256).model_copy(update={"engine_id":"fake"}); records=dict(r.evidence._records); records[ind.sha256]=ind
    bad=b.model_copy(update={"parity_independent_trade_list_sha256":ind.sha256}); records[bad.sha256]=bad
    rr=VerificationResolvers(r.variants,ContentAddressedStore.build(records),r.engines,r.exposure); assert verify_edge(bad.sha256,rr).verdict==EdgeVerdict.INSUFFICIENT_EVIDENCE

def _resolve_record(r,sha): return r.evidence.resolve(sha)

def test_missing_friction_trade_list_fails_closed():
    b,r=fixture(); f=_resolve_record(r,b.friction_sha256); broken=f.model_copy(update={"points":((1.0,b.oos_trade_list_sha256),(1.25,"9"*64),(1.5,dict(f.points)[1.5]))}); records=dict(r.evidence._records); records[broken.sha256]=broken
    bad=b.model_copy(update={"friction_sha256":broken.sha256}); records[bad.sha256]=bad
    rr=VerificationResolvers(r.variants,ContentAddressedStore.build(records),r.engines,r.exposure); assert verify_edge(bad.sha256,rr).verdict==EdgeVerdict.INSUFFICIENT_EVIDENCE

def test_holdout_without_unseen_to_burned_event_fails_closed():
    b,r=fixture(); event=ExposureEvent(dataset_sha256=DATA,previous=DatasetExposure.DEVELOPMENT,current=DatasetExposure.BURNED_HOLDOUT,observed_at=datetime(2026,2,1,tzinfo=Z)); rr=VerificationResolvers(r.variants,r.evidence,r.engines,ExposureLedger((event,))); assert verify_edge(b.sha256,rr).verdict==EdgeVerdict.INSUFFICIENT_EVIDENCE

def test_variant_frozen_after_open_fails_closed():
    b,r=fixture(); old=r.variants.resolve(b.variant_sha256); late=old.model_copy(update={"frozen_at":datetime(2026,3,1,tzinfo=Z)}); records=dict(r.evidence._records); bad=b.model_copy(update={"variant_sha256":late.sha256}); records[bad.sha256]=bad
    rr=VerificationResolvers(ContentAddressedStore.build({late.sha256:late}),ContentAddressedStore.build(records),r.engines,r.exposure); assert verify_edge(bad.sha256,rr).verdict==EdgeVerdict.INSUFFICIENT_EVIDENCE

def test_caller_cannot_submit_metrics_to_id_only_api():
    _,r=fixture()
    with pytest.raises(TypeError): verify_edge({"expectancy_r":999},r)
