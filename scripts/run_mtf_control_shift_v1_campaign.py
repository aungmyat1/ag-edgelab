from __future__ import annotations
import csv, json, math
from collections import Counter, defaultdict
from datetime import datetime, timezone, time, timedelta
from pathlib import Path
import sys
sys.path.insert(0,"src")
from ag_edgelab.data.fx_histdata import *
from mtf_control_shift.models import Candle
from mtf_control_shift.engine import evaluate
from mtf_control_shift.structure import latest_fresh_zone, zone_touched, control_shift_zones, classify_false_shift

UTC=timezone.utc
WARMUP=(datetime(2017,1,1,tzinfo=UTC),datetime(2017,3,1,tzinfo=UTC))
DEV=(datetime(2017,3,1,tzinfo=UTC),datetime(2017,9,1,tzinfo=UTC))
OOS=(datetime(2017,9,1,tzinfo=UTC),datetime(2017,12,1,tzinfo=UTC))
SESSIONS={"ASIAN_LONDON":(time(6),time(9)),"LONDON_NEWYORK":(time(11),time(14))}
OUT=Path("artifacts/mtf_control_shift_v1")

def candle(b): return Candle(b.timestamp,b.open,b.high,b.low,b.close)
def in_session(ts,s):
 t=ts.time(); a,b=SESSIONS[s]; return a<=t<b

def cost_r(symbol, entry, risk):
 # Frozen PR #10 evidence authority; this is a per-trade round-turn model.
 if symbol=="EURUSD": spread,slip,comm,cs,quote=.3e-4,2*.1e-4,7,100000,False
 elif symbol=="GBPUSD": spread,slip,comm,cs,quote=.4e-4,2*.1e-4,7,100000,False
 elif symbol=="USDJPY": spread,slip,comm,cs,quote=.4e-2,2*.1e-1,7,100000,True
 else: spread,slip,comm,cs,quote=.30,2*.05,7,100,False
 cp=comm*entry/cs if quote else comm/cs
 return (spread+slip+cp)/risk

def stats(rows):
 vals=[r["net_r"] for r in rows if r["status"]=="CLOSED"]
 gross=[r["gross_r"] for r in rows if r["status"]=="CLOSED"]
 wins=[x for x in vals if x>0]; losses=[x for x in vals if x<0]
 pf=sum(wins)/abs(sum(losses)) if losses else (math.inf if wins else None)
 peak=dd=0; run=mxrun=0
 for x in vals:
  peak=max(peak,peak+x); dd=min(dd,peak-(peak+x)); run=run+1 if x<0 else 0; mxrun=max(mxrun,run)
 return {"signals":len(rows),"fills":sum(r.get("filled",False) for r in rows),"unfilled":sum(not r.get("filled",False) for r in rows),"expired":sum(r["status"]=="EXPIRED" for r in rows),"forced_flat":sum(r.get("exit_reason")=="FORCED_FLAT" for r in rows),"closed":len(vals),"wins":sum(x>0 for x in vals),"losses":sum(x<0 for x in vals),"breakeven":sum(x==0 for x in vals),"gross_r":sum(gross) if gross else None,"net_r":sum(vals) if vals else None,"gross_expectancy":sum(gross)/len(gross) if gross else None,"net_expectancy":sum(vals)/len(vals) if vals else None,"net_pf":pf,"win_rate":sum(x>0 for x in vals)/len(vals) if vals else None,"max_dd_r":dd if vals else None,"max_losing_streak":mxrun,"tp1_hits":sum(r.get("tp1",False) for r in rows),"tp2_hits":sum(r.get("tp2",False) for r in rows),"runner_be":sum(r.get("runner_be",False) for r in rows),"total_friction_r":sum(r.get("friction_r",0) for r in rows if r.get("filled")),"average_friction_r":sum(r.get("friction_r",0) for r in rows if r.get("filled"))/max(1,sum(r.get("filled",False) for r in rows))}

def replay_symbol(symbol, bars, period):
 start,end=period; m1=bars["M1"]; bykey={(b.timestamp):b for b in m1}; rows=[]; quota=set(); funnel=Counter(); false=Counter()
 for mb in bars["M15"]:
  signal_time=mb.timestamp+timedelta(minutes=15)
  if not (start<=signal_time<end): continue
  for session in SESSIONS:
   if not in_session(mb.timestamp,session): continue
   day=mb.timestamp.date(); key=(day,session)
   if key in quota: continue
   h1=closed(bars["H1"],"H1",signal_time); h4=closed(bars["H4"],"H4",signal_time); d1=closed(bars["D1"],"D1",signal_time); m15=closed(bars["M15"],"M15",signal_time)
   if not d1 or not h4 or not h1 or not m15: funnel["CONTEXT_UNAVAILABLE"]+=1; continue
   db=[candle(x) for x in d1]; hb=[candle(x) for x in h4]; h1c=[candle(x) for x in h1]; mc=[candle(x) for x in m15]
   # Funnel observations are based on the frozen source's own decision.
   try: dec=evaluate(symbol,session,db,hb,h1c,mc)
   except ValueError: funnel["DATA_INVALID"]+=1; continue
   if dec.bias: funnel["D1_H4_ALIGNED"]+=1
   if dec.h4_zone: funnel["FRESH_H4_POI"]+=1
   if dec.reason_code=="HTF_POI_NOT_REACHED": funnel["HTF_POI_NOT_REACHED"]+=1
   if dec.h4_zone and zone_touched(h1c,dec.h4_zone,4): funnel["H4_POI_REACHED"]+=1
   if dec.h1_shift_zone: funnel["TRUE_H1_CONTROL_SHIFT"]+=1
   if dec.false_shift_class: false[dec.false_shift_class]+=1
   if dec.m15_entry_zone: funnel["M15_REFINEMENT"]+=1
   if dec.status=="SIGNAL":
    funnel["VALID_GEOMETRY"]+=1; quota.add(key)
    expiry=dec.expiry_timestamp; post=[b for b in m1 if b.timestamp>signal_time and b.timestamp<expiry]
    fill=None
    for b in post:
     if (dec.direction=="LONG" and b.high>=dec.entry) or (dec.direction=="SHORT" and b.low<=dec.entry): fill=b; break
    row={"symbol":symbol,"session":session,"signal_time":signal_time.isoformat(),"direction":dec.direction,"entry":dec.entry,"risk":dec.risk_distance,"status":"SIGNAL","filled":bool(fill),"tp1":False,"tp2":False,"runner_be":False,"friction_r":0}
    if fill is None: row["status"]="EXPIRED"; rows.append(row); continue
    funnel["LIMIT_FILLED"]+=1; row["status"]="OPEN"; row["fill_time"]=fill.timestamp.isoformat(); row["friction_r"]=cost_r(symbol,dec.entry,dec.risk_distance)
    remaining=0.5; gross=0.0; exit_reason=None; exit_time=fill.timestamp
    for b in [x for x in m1 if x.timestamp>=fill.timestamp and x.timestamp<=datetime.combine(fill.timestamp.date(),time(21),tzinfo=UTC)]:
     if dec.direction=="LONG": sl=b.low<=dec.stop_loss; tp1=b.high>=dec.tp1; tp2=b.high>=dec.tp2; be=b.low>=dec.entry # placeholder
     else: sl=b.high>=dec.stop_loss; tp1=b.low<=dec.tp1; tp2=b.low<=dec.tp2; be=b.high<=dec.entry
     # Conservative: protective stop first, then target events.
     if remaining==0.5 and sl: gross=-1.0; exit_reason="SL"; exit_time=b.timestamp; break
     if remaining==0.5 and tp1:
      gross+=1.0; row["tp1"]=True; row["runner_be"]=False; remaining=0.5
      # continue runner with BE; same-bar stop after TP1 is conservative BE.
      if be: gross+=0; row["runner_be"]=True; exit_reason="TP1_BE"; exit_time=b.timestamp; break
     if remaining==0.5 and row["tp1"] and tp2:
      gross+=0.5*((dec.tp2-dec.entry)/dec.risk_distance if dec.direction=="LONG" else (dec.entry-dec.tp2)/dec.risk_distance); row["tp2"]=True; exit_reason="TP2"; exit_time=b.timestamp; break
    if exit_reason is None:
     ff=next((x for x in m1 if x.timestamp>=datetime.combine(fill.timestamp.date(),time(21),tzinfo=UTC)),None)
     if ff is None: ff=post[-1] if post else fill
     move=(ff.close-dec.entry)/dec.risk_distance if dec.direction=="LONG" else (dec.entry-ff.close)/dec.risk_distance
     gross=(0.5*2.0+0.5*move) if row["tp1"] else move; exit_reason="FORCED_FLAT"; exit_time=ff.timestamp; funnel["FORCED_FLAT"]+=1
    row.update({"status":"CLOSED","gross_r":gross,"net_r":gross-row["friction_r"],"exit_reason":exit_reason,"exit_time":exit_time.isoformat()}); rows.append(row)
 return rows,funnel,false

def main():
 all_rows=[]; matrix=[]; lineages={}; raw_manifest={}; total_funnel=Counter(); total_false=Counter()
 for symbol in SYMBOLS:
  path=Path("data/raw/fx_histdata")/f"HISTDATA_COM_ASCII_{symbol}_M1_2017.zip"; raw=_validate_raw_path_local(path,symbol); m=load_m1(path,symbol,end=DEV[1]); bars,lin=derive_all(m,symbol,raw); lineages[symbol]={k:vars(v) for k,v in lin.items()}; raw_manifest[symbol]=manifest_entry(symbol,path,lin, m[0].timestamp.isoformat(),m[-1].timestamp.isoformat())
  rows,fun,false=replay_symbol(symbol,bars,DEV); all_rows += rows; total_funnel.update(fun); total_false.update(false)
  for sess in SESSIONS:
   rr=[r for r in rows if r["session"]==sess]; st=stats(rr); st.update({"symbol":symbol,"session":sess,"status":"SURVIVES_DEV_SCREEN" if st["net_expectancy"] is not None and st["net_expectancy"]>0 else ("INSUFFICIENT_SAMPLE" if not rr else "FAILS_DEV_SCREEN")}); matrix.append(st)
 (OUT/"dataset_manifest.json").write_text(json.dumps({"source":"PR_10_HISTDATA_2017","raw_data_identity_reused_from_stv2":True,"symbols":raw_manifest,"lineage":lineages,"M15_DERIVATION_AUTHORITY":"REUSED_FROM_PR10","holdout_touched":False},indent=2,default=str)+"\n")
 (OUT/"dev_result.json").write_text(json.dumps({"status":"COMPLETE","partition":"DEV","matrix":matrix},indent=2,default=str)+"\n")
 with (OUT/"dev_matrix.csv").open("w",newline="") as f:
  fields=list(matrix[0]); w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(matrix)
 (OUT/"ledger.jsonl").write_text("\n".join(json.dumps(x,default=str) for x in all_rows)+"\n")
 (OUT/"funnel_analysis.json").write_text(json.dumps({"status":"COMPLETE","totals":dict(total_funnel)},indent=2)+"\n")
 (OUT/"false_choch_analysis.json").write_text(json.dumps({"status":"COMPLETE","totals":dict(total_false)},indent=2)+"\n")
 print(json.dumps({"matrix":matrix,"trades":len(all_rows),"funnel":dict(total_funnel),"false_choch":dict(total_false),"lineage":lineages},indent=2,default=str))
def _validate_raw_path_local(p,s):
 import hashlib
 got=hashlib.sha256(p.read_bytes()).hexdigest()
 if got!=EXPECTED_RAW_SHA256[s]: raise RuntimeError("RAW_DATA_HASH_MISMATCH")
 return got
if __name__=='__main__': main()
