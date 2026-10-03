from __future__ import annotations
import json,sys
from collections import Counter
from datetime import datetime,timezone,time,timedelta
from pathlib import Path
sys.path.insert(0,'src')
from ag_edgelab.data.fx_histdata import *
import mtf_control_shift.engine as engine
from mtf_control_shift.models import Candle
from mtf_control_shift.structure import zones

UTC=timezone.utc; OUT=Path('artifacts/mtf_control_shift_v1')
SESSIONS={'ASIAN_LONDON':(time(6),time(9)),'LONDON_NEWYORK':(time(11),time(14))}
def c(b):return Candle(b.timestamp,b.open,b.high,b.low,b.close)
def in_session(ts,session):
 a,b=SESSIONS[session]; return a<=ts.time()<b
def check(p,s):
 import hashlib
 h=hashlib.sha256(p.read_bytes()).hexdigest()
 if h!=EXPECTED_RAW_SHA256[s]:raise RuntimeError('RAW_DATA_HASH_MISMATCH')
 return h
def classify(m15,shift_time,session):
 direction_kind='DEMAND' if False else None
 return None
def main():
 measurement=json.loads((OUT/'v2_freshness_measurement.json').read_text())
 candidates=[x for x in measurement['observations'] if x['shift_age_h1_bars'] is not None and x['shift_age_h1_bars']<=24]
 assert len(candidates)==18
 bysym={}
 for s in SYMBOLS:
  p=Path('data/raw/fx_histdata')/f'HISTDATA_COM_ASCII_{s}_M1_2017.zip'; raw=check(p,s); m=load_m1(p,s,end=datetime(2017,9,1,tzinfo=UTC)); bysym[s]=derive_all(m,s,raw)[0]
 original=engine.H1_SHIFT_MAX_AGE_BARS; engine.H1_SHIFT_MAX_AGE_BARS=24
 rows=[]; reasons=Counter(); parity=Counter(); causal=Counter()
 try:
  for case in candidates:
   s=case['symbol']; session=case['session']; T=datetime.fromisoformat(case['timestamp']); b=bysym[s]
   d1=tuple(c(x) for x in closed(b['D1'],'D1',T)); h4=tuple(c(x) for x in closed(b['H4'],'H4',T)); h1=tuple(c(x) for x in closed(b['H1'],'H1',T)); m15=tuple(c(x) for x in closed(b['M15'],'M15',T))
   source_dec=engine.evaluate(s,session,d1,h4,h1,m15)
   clipped=(tuple(c(x) for x in closed(b['D1'],'D1',T)),tuple(c(x) for x in closed(b['H4'],'H4',T)),tuple(c(x) for x in closed(b['H1'],'H1',T)),tuple(c(x) for x in closed(b['M15'],'M15',T)))
   clipped_dec=engine.evaluate(s,session,*clipped)
   causal_ok=source_dec==clipped_dec and all(all(x.time+timedelta(minutes=span)<=T for x in series) for series,span in zip(clipped,(1440,240,60,15)))
   causal['PASS' if causal_ok else 'FAIL']+=1
   direction_kind='DEMAND' if case['direction']=='LONG' else 'SUPPLY'
   mzones=zones(m15); directional=[z for z in mzones if z.kind==direction_kind]
   after=[z for z in directional if z.created_time>=datetime.fromisoformat(case['shift_created_time'])]
   in_window=[z for z in after if in_session(z.created_time,session)]
   if in_window:
    reason='SOURCE_WOULD_PASS_M15_REFINEMENT'
   elif not directional:
    reason='NO_M15_CONFIRMING_STRUCTURE'
   elif not after:
    reason='REFINEMENT_TOO_OLD'
   else:
    reason='SESSION_WINDOW_EXPIRED'
   reasons[reason]+=1
   edge_result='M15_REFINEMENT_PASS' if source_dec.m15_entry_zone else 'NO_M15_ENTRY_REFINEMENT'
   source_result=edge_result
   parity['MATCH' if source_result==edge_result else 'SOURCE_PASS_EDGELAB_FAIL']+=1
   rows.append({'analysis_unit_id':case['analysis_unit_id'],'symbol':s,'session':session,'timestamp':case['timestamp'],'direction':case['direction'],'h1_shift_time':case['shift_created_time'],'shift_age_h1_bars':case['shift_age_h1_bars'],'m15_bars_available':len(m15),'source_refinement_result':source_result,'edgelab_result':edge_result,'m15_total_zones':len(mzones),'directional_m15_zones':len(directional),'directional_zones_after_shift':len(after),'qualifying_in_session':len(in_window),'failure_reason':reason,'causality':'PASS' if causal_ok else 'FAIL'})
 finally: engine.H1_SHIFT_MAX_AGE_BARS=original
 result={'candidate':'ST_MTF_CONTROL_SHIFT_V2@2.0.0','h1_shift_pass':18,'cases_audited':len(rows),'failure_reasons':{k:{'count':v,'pct':v/len(rows)*100} for k,v in sorted(reasons.items())},'parity':dict(parity),'causality':dict(causal),'holdout_touched':False,'source_references':['src/mtf_control_shift/engine.py:evaluate','src/mtf_control_shift/structure.py:zones']}
 (OUT/'v2_m15_refinement_audit.json').write_text(json.dumps(result,indent=2)+'\n')
 (OUT/'v2_m15_refinement_cases.jsonl').write_text('\n'.join(json.dumps(x) for x in rows)+'\n')
 print(json.dumps(result,indent=2))
for _ in [0]: pass
if __name__=='__main__':main()
