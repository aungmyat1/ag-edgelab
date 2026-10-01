from __future__ import annotations

import math
from enum import StrEnum
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field

from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.optimization.stability import assess_parameter_stability
from ag_edgelab.statistics.bootstrap import bootstrap_expectancy_ci
from ag_edgelab.statistics.performance import compute_performance
from ag_edgelab.verification.evidence import FrictionEvidenceRecord, StabilityEvidenceRecord, TradeListRecord, ValidationBundleRecord, WalkForwardEvidenceRecord
from ag_edgelab.verification.provenance import FrozenVariantRecord, UnknownProvenanceError, VerificationResolvers

HEX64=r"^[0-9a-f]{64}$"; REQUIRED_FRICTION_GRID=(1.0,1.25,1.5)

class EdgeVerdict(StrEnum):
    EDGE_VERIFIED="EDGE_VERIFIED"; NO_EDGE="NO_EDGE"; INSUFFICIENT_EVIDENCE="INSUFFICIENT_EVIDENCE"

class VerificationPolicy(BaseModel):
    model_config=ConfigDict(frozen=True,extra="forbid")
    policy_id:str; min_oos_trades:int=30; min_oos_expectancy_r:float=0.0; min_oos_profit_factor:float=1.0; max_drawdown_r:float=20.0
    min_bootstrap_ci_low_r:float=0.0; min_walk_forward_folds:int=3; min_positive_walk_forward_fraction:float=.6; min_regime_sample:int=10
    required_friction_multipliers:tuple[float,...]=REQUIRED_FRICTION_GRID; max_parity_trade_count_delta:int=1; max_parity_expectancy_delta_r:float=.02
    @property
    def sha256(self): return sha256_json(self.model_dump(mode="python"))

CANONICAL_POLICY_V1=VerificationPolicy(policy_id="EDGE_VERIFICATION_V1")
CANONICAL_POLICY_V1_SHA256="7eb2b129c6523f90a2fb041c2a6dcbe0287012307d96054bb3acee62c76beef8"
if CANONICAL_POLICY_V1.sha256!=CANONICAL_POLICY_V1_SHA256: raise RuntimeError("canonical policy hash drift")
POLICY_REGISTRY=MappingProxyType({CANONICAL_POLICY_V1.policy_id:CANONICAL_POLICY_V1})

class EdgeValidationArtifact(BaseModel):
    model_config=ConfigDict(frozen=True,extra="forbid")
    evidence_id:str=Field(pattern=HEX64); policy_sha256:str=Field(pattern=HEX64); verdict:EdgeVerdict
    gate_results:tuple[tuple[str,bool],...]; reasons:tuple[str,...]; verifier_version:str="EDGE_VERIFIER_V2"; seal_sha256:str=Field(pattern=HEX64)


def _artifact(evidence_id,verdict,gates,reasons):
    pairs=tuple(sorted(gates.items())); payload={"evidence_id":evidence_id,"policy_sha256":CANONICAL_POLICY_V1_SHA256,"verdict":verdict.value,"gate_results":pairs,"reasons":tuple(reasons),"verifier_version":"EDGE_VERIFIER_V2"}
    return EdgeValidationArtifact(**payload,seal_sha256=sha256_json(payload))

def _resolve(store,sha,typ):
    obj=store.resolve(sha)
    if not isinstance(obj,typ): raise UnknownProvenanceError(f"wrong evidence type for {sha}")
    return obj

def _same_identity(a:TradeListRecord,b:TradeListRecord): return a.dataset_sha256==b.dataset_sha256 and a.strategy_sha256==b.strategy_sha256

def verify_edge(evidence_id:str,resolvers:VerificationResolvers)->EdgeValidationArtifact:
    """ID-only authority: every metric is recomputed from content-addressed raw trade lists."""
    gates={}; reasons=[]
    try:
        bundle=_resolve(resolvers.evidence,evidence_id,ValidationBundleRecord)
        variant=resolvers.variants.resolve(bundle.variant_sha256)
        if not isinstance(variant,FrozenVariantRecord): raise UnknownProvenanceError("variant record type mismatch")
        oos=_resolve(resolvers.evidence,bundle.oos_trade_list_sha256,TradeListRecord)
        friction=_resolve(resolvers.evidence,bundle.friction_sha256,FrictionEvidenceRecord)
        wf=_resolve(resolvers.evidence,bundle.walk_forward_sha256,WalkForwardEvidenceRecord)
        stability=_resolve(resolvers.evidence,bundle.stability_sha256,StabilityEvidenceRecord)
        pref=_resolve(resolvers.evidence,bundle.parity_reference_trade_list_sha256,TradeListRecord)
        pind=_resolve(resolvers.evidence,bundle.parity_independent_trade_list_sha256,TradeListRecord)
        open_event=resolvers.exposure.open_event(oos.dataset_sha256)
    except (UnknownProvenanceError,ValueError,TypeError) as exc:
        return _artifact(evidence_id,EdgeVerdict.INSUFFICIENT_EVIDENCE,{"AUTHORITATIVE_EVIDENCE":False},(type(exc).__name__,))

    identity=(oos.strategy_sha256==variant.strategy_sha256 and bundle.variant_sha256==variant.sha256 and variant.frozen_at<=open_event.observed_at)
    gates["FROZEN_BEFORE_OPEN"]=identity
    gates["UNSEEN_FROM_LEDGER"]=resolvers.exposure.was_unseen_when_opened(oos.dataset_sha256)

    p=compute_performance(oos.rs); boot=bootstrap_expectancy_ci(oos.rs,samples=5000,seed=0)
    gates["OOS_POPULATION"]=p.trades>=CANONICAL_POLICY_V1.min_oos_trades

    # Regimes are derived only from stored OOS trades and must exactly match preregistration.
    observed=set(t.regime for t in oos.trades); claimed=set(variant.claimed_regimes)
    regime_complete=observed==claimed
    regime_metrics={name:compute_performance(tuple(t.r for t in oos.trades if t.regime==name)) for name in variant.claimed_regimes}
    gates["REGIME_COHERENCE"]=regime_complete and all(m.trades>=CANONICAL_POLICY_V1.min_regime_sample for m in regime_metrics.values())

    # Friction: resolve every stored list; exact canonical grid; same identities/trade IDs; 1x must equal OOS raw outcomes.
    fpoints={}; friction_coherent=tuple(m for m,_ in friction.points)==CANONICAL_POLICY_V1.required_friction_multipliers
    for mult,sha in friction.points:
        try: tl=_resolve(resolvers.evidence,sha,TradeListRecord)
        except UnknownProvenanceError: friction_coherent=False; continue
        friction_coherent &= _same_identity(oos,tl) and tuple(t.trade_id for t in tl.trades)==tuple(t.trade_id for t in oos.trades)
        fpoints[mult]=compute_performance(tl.rs)
    friction_coherent &= 1.0 in fpoints and tuple(_resolve(resolvers.evidence,dict(friction.points)[1.0],TradeListRecord).rs)==tuple(oos.rs)
    gates["FRICTION_COHERENCE"]=bool(friction_coherent)

    # Walk-forward metrics are recomputed from each fold's stored test trade list.
    wf_metrics=[]; wf_coherent=len(wf.folds)>=CANONICAL_POLICY_V1.min_walk_forward_folds
    for fold in wf.folds:
        try: tl=_resolve(resolvers.evidence,fold.trade_list_sha256,TradeListRecord)
        except UnknownProvenanceError: wf_coherent=False; continue
        wf_coherent &= tl.strategy_sha256==variant.strategy_sha256
        wf_metrics.append(compute_performance(tl.rs))
    gates["WALK_FORWARD_COHERENCE"]=bool(wf_coherent)

    # Stability is recomputed from stored neighborhood trade lists.
    neighborhood={}; stability_coherent=True
    for value,sha in stability.neighborhoods:
        try: tl=_resolve(resolvers.evidence,sha,TradeListRecord)
        except UnknownProvenanceError: stability_coherent=False; continue
        neighborhood[value]=compute_performance(tl.rs).expectancy_r
    try: stability_result=assess_parameter_stability(neighborhood,stability.center)
    except (ValueError,TypeError): stability_coherent=False; stability_result=None
    gates["STABILITY_COHERENCE"]=bool(stability_coherent)

    # Parity uses only two owner-approved engines and their stored trade lists.
    parity_coherent=_same_identity(pref,pind) and pref.dataset_sha256==oos.dataset_sha256 and pref.strategy_sha256==variant.strategy_sha256
    try:
        er=resolvers.engines.resolve(pref.engine_id); ei=resolvers.engines.resolve(pind.engine_id)
        parity_coherent &= er.code_sha256==pref.engine_code_sha256 and ei.code_sha256==pind.engine_code_sha256 and er.independence_group!=ei.independence_group
    except UnknownProvenanceError: parity_coherent=False
    pr=compute_performance(pref.rs); pi=compute_performance(pind.rs)
    gates["PARITY_COHERENCE"]=bool(parity_coherent)

    completeness=(gates["FROZEN_BEFORE_OPEN"] and gates["UNSEEN_FROM_LEDGER"] and gates["OOS_POPULATION"] and gates["REGIME_COHERENCE"] and gates["FRICTION_COHERENCE"] and gates["WALK_FORWARD_COHERENCE"] and gates["STABILITY_COHERENCE"] and gates["PARITY_COHERENCE"])
    if not completeness:
        return _artifact(evidence_id,EdgeVerdict.INSUFFICIENT_EVIDENCE,gates,tuple(k for k,v in gates.items() if not v))

    # Coherent economics: negative base evidence is NO_EDGE, not missing evidence.
    base_positive=(p.expectancy_r is not None and p.expectancy_r>CANONICAL_POLICY_V1.min_oos_expectancy_r and p.profit_factor is not None and p.profit_factor>CANONICAL_POLICY_V1.min_oos_profit_factor and p.max_drawdown_r<=CANONICAL_POLICY_V1.max_drawdown_r)
    if not base_positive:
        gates["OOS_ECONOMICS"]=False
        return _artifact(evidence_id,EdgeVerdict.NO_EDGE,gates,("OOS_ECONOMICS",))
    gates["OOS_ECONOMICS"]=True

    gates["BOOTSTRAP"]=boot.low is not None and boot.low>CANONICAL_POLICY_V1.min_bootstrap_ci_low_r
    fvals=[fpoints[m].expectancy_r for m in CANONICAL_POLICY_V1.required_friction_multipliers]
    gates["FRICTION_STRESS"]=all(v is not None and v>0 for v in fvals) and all(b<=a+1e-12 for a,b in zip(fvals,fvals[1:]))
    gates["REGIME_EVIDENCE"]=all(m.expectancy_r is not None and m.expectancy_r>0 for m in regime_metrics.values())
    positives=sum(m.expectancy_r is not None and m.expectancy_r>0 for m in wf_metrics)/len(wf_metrics)
    gates["WALK_FORWARD"]=positives>=CANONICAL_POLICY_V1.min_positive_walk_forward_fraction
    gates["PARAMETER_STABILITY"]=stability_result is not None and stability_result.stable
    gates["INDEPENDENT_PARITY"]=(abs(pr.trades-pi.trades)<=CANONICAL_POLICY_V1.max_parity_trade_count_delta and pr.expectancy_r is not None and pi.expectancy_r is not None and abs(pr.expectancy_r-pi.expectancy_r)<=CANONICAL_POLICY_V1.max_parity_expectancy_delta_r)
    failed=tuple(k for k,v in gates.items() if not v)
    return _artifact(evidence_id,EdgeVerdict.EDGE_VERIFIED if not failed else EdgeVerdict.NO_EDGE,gates,failed)


def validate_artifact(artifact:EdgeValidationArtifact,resolvers:VerificationResolvers)->bool:
    return verify_edge(artifact.evidence_id,resolvers).model_dump(mode="python")==artifact.model_dump(mode="python")
