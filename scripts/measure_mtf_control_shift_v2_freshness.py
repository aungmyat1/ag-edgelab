from __future__ import annotations
import json, sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0,'src')
from ag_edgelab.data.fx_histdata import *
from mtf_control_shift.models import Candle
from mtf_control_shift.structure import control_shift_zones

UTC=timezone.utc; OUT=Path('artifacts/mtf_control_shift_v1')

def c(b): return Candle(b.timestamp,b.open,b.high,b.low,b.close)
def load_cases(): return [json.loads(x) for x in (OUT/'trigger_cases.jsonl').read_text().splitlines() if x.strip()]
def main():
 cases=load_cases(); bysym={};
 for s in SYMBOLS:
  p=Path('data/raw/fx_histdata')/f'HISTDATA_COM_ASCII_{s}_M1_2017.zip'; raw=_check(p,s); m=load_m1(p,s,end=datetime(2017,9,1,tzinfo=UTC)); bars,_=derive_all(m,s,raw); bysym[s]=bars
 rows=[]
 for case in cases:
  s=case['symbol']; T=datetime.fromisoformat(case['timestamp']); h1=tuple(c(x) for x in closed(bysym[s]['H1'],'H1',T)); direction='BULLISH' if case['direction']=='LONG' else 'BEARISH'; shifts=control_shift_zones(h1,direction)
  if not shifts:
   # This is not expected for this audit population; retain an explicit null rather than inventing an age.
   row={**case,'shift_created_time':None,'shift_age_h1_bars':None,'current_v1_eligible':False,'reason':'NO_HISTORICAL_MATCHING_CONTROL_SHIFT'}
  else:
   z=shifts[-1]; idx=next(i for i,x in enumerate(h1) if x.time==z.created_time); age=len(h1)-idx
   row={**case,'shift_created_time':z.created_time.isoformat(),'shift_age_h1_bars':age,'current_v1_eligible':age<=4,'reason':'SHIFT_TOO_OLD' if age>4 else 'V1_ELIGIBLE'}
  rows.append(row)
 ages=[r['shift_age_h1_bars'] for r in rows if r['shift_age_h1_bars'] is not None]
 hist=Counter(ages); total=len(rows); cumulative=0; histogram=[]
 for age in sorted(hist):
  n=hist[age]; cumulative+=n; histogram.append({'age':age,'count':n,'percentage':n/total*100,'cumulative_count':cumulative,'cumulative_percentage':cumulative/total*100})
 vals=sorted(ages)
 def quantile(q):
  if not vals:return None
  pos=(len(vals)-1)*q; lo=int(pos); hi=min(lo+1,len(vals)-1); return vals[lo]+(vals[hi]-vals[lo])*(pos-lo)
 coverage={str(k):{'eligible_n':sum(a<=k for a in ages),'eligible_pct':sum(a<=k for a in ages)/total*100} for k in (4,6,8,12,16,24)}
 result={'parent_strategy':'ST_MTF_CONTROL_SHIFT_V1@1.0.0','location_pass_n':total,'shift_too_old_n':sum(a>4 for a in ages),'age_histogram':histogram,'quantiles':{'P25':quantile(.25),'P50':quantile(.5),'P75':quantile(.75),'P90':quantile(.9),'P95':quantile(.95),'MAX':max(vals) if vals else None},'coverage':coverage,'observations':rows,'holdout_touched':False,'v1_eligibility_definition':'shift_age_h1_bars <= 4'}
 (OUT/'v2_freshness_measurement.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({k:result[k] for k in ('location_pass_n','shift_too_old_n','age_histogram','quantiles','coverage')},indent=2))
def _check(p,s):
 import hashlib
 h=hashlib.sha256(p.read_bytes()).hexdigest()
 if h!=EXPECTED_RAW_SHA256[s]:raise RuntimeError('RAW_DATA_HASH_MISMATCH')
 return h
if __name__=='__main__':main()
