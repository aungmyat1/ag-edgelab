from __future__ import annotations
import json, sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0,'src')
from ag_edgelab.data.fx_histdata import *
from mtf_control_shift.models import Candle
from mtf_control_shift.engine import evaluate
from mtf_control_shift.structure import (structure_bias, latest_fresh_zone, zone_touched,
    zones, confirmed_swings, control_shift_zones, _active_before)

UTC=timezone.utc
DEV=(datetime(2017,3,1,tzinfo=UTC),datetime(2017,9,1,tzinfo=UTC))
SESSIONS={'ASIAN_LONDON':(6,9),'LONDON_NEWYORK':(11,14)}
OUT=Path('artifacts/mtf_control_shift_v1')

def c(b): return Candle(b.timestamp,b.open,b.high,b.low,b.close)
def keyz(z): return (z.kind,z.origin_time.isoformat(),z.created_time.isoformat(),z.low,z.high,z.bos_level)
def zone_cross_reference(h1,bias):
    # Independent parity reference of the frozen source control_shift_zones function.
    zs=zones(h1); wanted='DEMAND' if bias=='BULLISH' else 'SUPPLY'; opposite='SUPPLY' if bias=='BULLISH' else 'DEMAND'; out=[]
    for z in zs:
        if z.kind != wanted: continue
        created=next(i for i,x in enumerate(h1) if x.time==z.created_time)
        prior=[p for p in zs if p.kind==opposite and p.created_time<z.created_time and _active_before(h1,p,created)]
        if not prior: continue
        p=prior[-1]; close=h1[created].close
        if (bias=='BULLISH' and close>p.high) or (bias=='BEARISH' and close<p.low): out.append(z)
    return tuple(out)

def failure_reason(h1,bias,all_shifts,recent_shifts):
    if len(h1)<5: return 'H1_CONTEXT_NOT_READY'
    if recent_shifts: return 'TRUE_H1_CONTROL_SHIFT'
    if all_shifts: return 'SHIFT_TOO_OLD'
    swings=confirmed_swings(h1)
    if not any(x.kind=='HIGH' for x in swings) or not any(x.kind=='LOW' for x in swings): return 'NO_CONFIRMED_H1_SWING'
    zs=zones(h1); wanted='DEMAND' if bias=='BULLISH' else 'SUPPLY'; opposite='SUPPLY' if bias=='BULLISH' else 'DEMAND'
    wanted_z=[z for z in zs if z.kind==wanted]
    if not wanted_z: return 'NO_CONTROL_CANDLE'
    # Every wanted zone already has directional FVG, BOS, and origin OB under source semantics.
    # Distinguish absence of an active opposing control level from a failed close-through.
    has_active=False; has_nonbreak=False
    for z in wanted_z:
        i=next(j for j,x in enumerate(h1) if x.time==z.created_time)
        prior=[p for p in zs if p.kind==opposite and p.created_time<z.created_time and _active_before(h1,p,i)]
        if prior:
            has_active=True
            if (bias=='BULLISH' and h1[i].close<=prior[-1].high) or (bias=='BEARISH' and h1[i].close>=prior[-1].low): has_nonbreak=True
    if has_nonbreak: return 'CLOSE_NOT_BEYOND_CONTROL'
    if not has_active: return 'CONTROL_NOT_BROKEN'
    return 'OTHER_DEFINED_REASON'

def main():
    cases=[]; reasons=Counter(); parity=Counter(); units=0
    for symbol in SYMBOLS:
        path=Path('data/raw/fx_histdata')/f'HISTDATA_COM_ASCII_{symbol}_M1_2017.zip'
        raw=_validate(path,symbol); m=load_m1(path,symbol,end=DEV[1]); bars,_=derive_all(m,symbol,raw)
        for mb in bars['M15']:
            T=mb.timestamp+timedelta(minutes=15)
            if not (DEV[0]<=T<DEV[1]): continue
            for session,(start,end) in SESSIONS.items():
                if not (start<=mb.timestamp.hour<end): continue
                d1=tuple(c(x) for x in closed(bars['D1'],'D1',T)); h4=tuple(c(x) for x in closed(bars['H4'],'H4',T)); h1=tuple(c(x) for x in closed(bars['H1'],'H1',T)); m15=tuple(c(x) for x in closed(bars['M15'],'M15',T))
                if not d1 or not h4 or not h1 or not m15: continue
                dbias=structure_bias(d1); hbias=structure_bias(h4)
                if dbias=='NEUTRAL' or hbias=='NEUTRAL' or dbias!=hbias: continue
                bias=dbias; poi=latest_fresh_zone(h4,'DEMAND' if bias=='BULLISH' else 'SUPPLY')
                if poi is None or not zone_touched(h1,poi,4): continue
                units+=1
                all_src=control_shift_zones(h1,bias); cutoff=h1[max(0,len(h1)-4)].time; recent=tuple(z for z in all_src if z.created_time>=cutoff)
                ref=zone_cross_reference(h1,bias)
                ref_recent=tuple(z for z in ref if z.created_time>=cutoff)
                source_result='TRUE_H1_CONTROL_SHIFT' if recent else 'NO_VALID_H1_CONTROL_SHIFT'
                # Causal truncation invariant: both evaluations are built from the
                # same full normalized arrays but only bars whose complete bucket
                # closed by T are admitted. The second construction is independent
                # and must produce the same decision.
                clipped=(
                    tuple(c(x) for x in closed(bars['D1'],'D1',T)),
                    tuple(c(x) for x in closed(bars['H4'],'H4',T)),
                    tuple(c(x) for x in closed(bars['H1'],'H1',T)),
                    tuple(c(x) for x in closed(bars['M15'],'M15',T)),
                )
                causal_ok=all(all(getattr(x,'time') + timedelta(minutes=span) <= T for x in series) for series,span in zip(clipped,(1440,240,60,15)))
                source_decision=evaluate(symbol,session,d1,h4,h1,m15)
                clipped_decision=evaluate(symbol,session,*clipped)
                causal_ok = causal_ok and source_decision == clipped_decision
                edge_dec=source_decision
                edge_result='TRUE_H1_CONTROL_SHIFT' if edge_dec.h1_shift_zone else 'NO_VALID_H1_CONTROL_SHIFT'
                if tuple(map(keyz,all_src))!=tuple(map(keyz,ref)) or tuple(map(keyz,recent))!=tuple(map(keyz,ref_recent)):
                    parity['SOURCE_PARITY_MISMATCH']+=1; pclass='SOURCE_FAIL_EDGELAB_FAIL_REFERENCE_MISMATCH'
                elif source_result==edge_result:
                    parity['MATCH']+=1; pclass='MATCH'
                else:
                    parity['SOURCE_PASS_EDGELAB_FAIL']+=1; pclass='SOURCE_PASS_EDGELAB_FAIL'
                reason=failure_reason(h1,bias,all_src,recent)
                if reason=='TRUE_H1_CONTROL_SHIFT': reason='TRUE_H1_CONTROL_SHIFT'
                reasons[reason]+=1
                cases.append({'analysis_unit_id':f'{symbol}_{session}_{T.isoformat()}','symbol':symbol,'session':session,'timestamp':T.isoformat(),'direction':'LONG' if bias=='BULLISH' else 'SHORT','h4_poi':{'kind':poi.kind,'low':poi.low,'high':poi.high,'created_time':poi.created_time.isoformat()},'h1_bars_available':len(h1),'source_expected_result':source_result,'edgelab_result':edge_result,'source_shift_count':len(recent),'reference_shift_count':len(ref_recent),'parity':pclass,'failure_reason':reason,'causality':'PASS' if causal_ok else 'FAIL'})
    # Deterministic sample: first 30 in chronological/symbol/session iteration order; retain all cases.
    OUT.joinpath('trigger_cases.jsonl').write_text('\n'.join(json.dumps(x) for x in cases)+'\n')
    causality=Counter(x['causality'] for x in cases)
    OUT.joinpath('trigger_audit.json').write_text(json.dumps({'campaign':'ST_MTF_CONTROL_SHIFT_V1@1.0.0','location_pass_count':len(cases),'cases_audited':len(cases),'deterministic_sample_ids':[x['analysis_unit_id'] for x in cases[:30]],'failure_reasons':{k:{'count':v,'pct':v/len(cases) if cases else None} for k,v in sorted(reasons.items())},'parity':dict(parity),'causality':dict(causality),'independent_adapter_present':False,'parity_note':'The EdgeLab campaign calls the byte-exact frozen source engine directly; the independent reference function above is a semantic parity check, not a second production adapter.','holdout_touched':False},indent=2)+'\n')
    print(json.dumps({'cases':len(cases),'reasons':reasons,'parity':parity},indent=2))
def _validate(p,s):
 import hashlib
 got=hashlib.sha256(p.read_bytes()).hexdigest()
 if got!=EXPECTED_RAW_SHA256[s]: raise RuntimeError(f'RAW_DATA_HASH_MISMATCH {s}')
 return got
if __name__=='__main__': main()
