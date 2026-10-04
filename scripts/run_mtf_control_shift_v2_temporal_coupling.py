from __future__ import annotations
import json,sys
from collections import Counter
from datetime import datetime,timezone,time,timedelta
from pathlib import Path
sys.path.insert(0,'src')
from ag_edgelab.data.fx_histdata import *
from mtf_control_shift.models import Candle
from mtf_control_shift.structure import zones
OUT=Path('artifacts/mtf_control_shift_v1'); UTC=timezone.utc
SESSIONS={'ASIAN_LONDON':(time(6),time(9)),'LONDON_NEWYORK':(time(11),time(14))}
def c(b):return Candle(b.timestamp,b.open,b.high,b.low,b.close)
def check(p,s):
 import hashlib
 h=hashlib.sha256(p.read_bytes()).hexdigest()
 if h!=EXPECTED_RAW_SHA256[s]:raise RuntimeError('RAW_DATA_HASH_MISMATCH')
 return h
def pct(n,d):return n/d*100 if d else None
def quant(vals,q):
 vals=sorted(vals)
 pos=(len(vals)-1)*q; lo=int(pos); hi=min(lo+1,len(vals)-1)
 return vals[lo]+(vals[hi]-vals[lo])*(pos-lo)
def bucket_after(x):
 if x<=0:return '<= 0'
 if x<=15:return '1-15'
 if x<=30:return '16-30'
 if x<=60:return '31-60'
 if x<=120:return '61-120'
 if x<=240:return '121-240'
 return '>240'
def bucket_remaining(x):
 if x>240:return '>240'
 if x>120:return '121-240'
 if x>60:return '61-120'
 if x>30:return '31-60'
 if x>15:return '16-30'
 if x>0:return '1-15'
 return '<=0'
def main():
 trigger={x['analysis_unit_id']:x for x in (json.loads(line) for line in (OUT/'trigger_cases.jsonl').read_text().splitlines() if line.strip())}
 m15cases=[json.loads(x) for x in (OUT/'v2_m15_refinement_cases.jsonl').read_text().splitlines() if x.strip()]
 bysym={}
 for s in SYMBOLS:
  p=Path('data/raw/fx_histdata')/f'HISTDATA_COM_ASCII_{s}_M1_2017.zip'; raw=check(p,s); m=load_m1(p,s,end=datetime(2017,9,1,tzinfo=UTC)); bysym[s]=derive_all(m,s,raw)[0]
 rows=[]
 for a in m15cases:
  s=a['symbol']; T=datetime.fromisoformat(a['timestamp']); b=bysym[s]; session=a['session']; start_t,end_t=SESSIONS[session]; session_start=datetime.combine(T.date(),start_t,tzinfo=UTC); session_end=datetime.combine(T.date(),end_t,tzinfo=UTC); shift=datetime.fromisoformat(a['h1_shift_time']); h1=tuple(c(x) for x in closed(b['H1'],'H1',T)); m15=tuple(c(x) for x in closed(b['M15'],'M15',T)); direction_kind='DEMAND' if a['direction']=='LONG' else 'SUPPLY'; directional=[z for z in zones(m15) if z.kind==direction_kind and z.created_time>=shift]; first=min(directional,key=lambda z:z.created_time) if directional else None
  tc=trigger[a['analysis_unit_id']]; poi=tc['h4_poi']; poi_low=poi['low']; poi_high=poi['high']; poi_created=datetime.fromisoformat(poi['created_time']); touch=[]
  for hb in h1:
   if hb.time<poi_created:continue
   if hb.high>=poi_low and hb.low<=poi_high: touch.append(hb.time)
  touch_time=touch[0].isoformat() if touch else None; zt=first.created_time if first else None; delay=(zt-shift).total_seconds()/60 if zt else None; after=max(0,(zt-session_end).total_seconds()/60) if zt else None; before=max(0,(session_start-zt).total_seconds()/60) if zt else None; remaining=(session_end-shift).total_seconds()/60
  rows.append({**a,'session_start':session_start.isoformat(),'session_end':session_end.isoformat(),'h1_shift_created_time':shift.isoformat(),'h4_poi_touch_time':touch_time,'first_directional_m15_zone_time_after_h1_shift':zt.isoformat() if zt else None,'h1_shift_to_session_end_minutes':remaining,'h1_shift_to_m15_zone_minutes':delay,'m15_zone_after_session_end_minutes':after,'m15_zone_before_session_start_minutes':before,'m15_zone_inside_original_session':bool(zt and zt<=session_end and zt>=session_start)})
 after=[r['m15_zone_after_session_end_minutes'] for r in rows]; before=[r['m15_zone_before_session_start_minutes'] for r in rows]; delays=[r['h1_shift_to_m15_zone_minutes'] for r in rows]; remain=[r['h1_shift_to_session_end_minutes'] for r in rows]
 hist=Counter(bucket_after(x) for x in after); h1hist=Counter(bucket_remaining(x) for x in remain); order=['<= 0','1-15','16-30','31-60','61-120','121-240','>240']; h1order=['>240','121-240','61-120','31-60','16-30','1-15','<=0']
 extensions={str(g):{'coverage_n':sum(r['m15_zone_before_session_start_minutes']==0 and r['m15_zone_after_session_end_minutes']<=g for r in rows),'coverage_pct':pct(sum(r['m15_zone_before_session_start_minutes']==0 and r['m15_zone_after_session_end_minutes']<=g for r in rows),18)} for g in (0,15,30,60,120,240)}
 report={'candidate':'ST_MTF_CONTROL_SHIFT_V2@2.0.0','cases':len(rows),'cases_detail':rows,'m15_after_session_distribution':{k:{'count':hist.get(k,0),'percentage':pct(hist.get(k,0),18)} for k in order},'h1_shift_timing_distribution':{k:{'count':h1hist.get(k,0),'percentage':pct(h1hist.get(k,0),18)} for k in h1order},'h1_shift_to_m15_zone_minutes':{'P25':quant(delays,.25),'P50':quant(delays,.5),'P75':quant(delays,.75),'P90':quant(delays,.9),'MAX':max(delays)},'m15_zone_after_session_end_minutes':{'P25':quant(after,.25),'P50':quant(after,.5),'P75':quant(after,.75),'P90':quant(after,.9),'MAX':max(after)},'m15_zone_before_session_start_minutes':{'P25':quant(before,.25),'P50':quant(before,.5),'P75':quant(before,.75),'P90':quant(before,.9),'MAX':max(before)},'h1_shift_to_session_end_minutes':{'P25':quant(remain,.25),'P50':quant(remain,.5),'P75':quant(remain,.75),'P90':quant(remain,.9),'MIN':min(remain)},'grace_window_coverage':extensions,'interpretation':{'primary_classification':'STALE_TRIGGER_SESSION_MISMATCH','v2_freshness_coupling_finding':'The 24-bar relaxation admits stale shifts from the prior day; their first directional M15 zones occur before the current session opens, so the trigger/confirmation pair is temporally mismatched. This is not a small post-session boundary mismatch.','v3_hypothesis_class':'TRIGGER_SESSION_TIMING','v3_not_implemented':True,'holdout_touched':False}}
 (OUT/'v2_temporal_coupling.json').write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps({k:report[k] for k in ('m15_after_session_distribution','h1_shift_timing_distribution','h1_shift_to_m15_zone_minutes','m15_zone_after_session_end_minutes','m15_zone_before_session_start_minutes','h1_shift_to_session_end_minutes','grace_window_coverage','interpretation')},indent=2))
if __name__=='__main__':main()
