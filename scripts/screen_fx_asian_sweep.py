from __future__ import annotations
import argparse,csv,json
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
from ag_edgelab.contracts.intent import OrderIntent,OrderType,Side,Target
from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.contracts.trade import ExecutionStatus
from ag_edgelab.engines.reference.replay import ReferenceReplayEngine
from ag_edgelab.statistics.performance import compute_performance

POINT=0.00001
COMMISSION_POINTS_RT=6.0
SLIPPAGE_POINTS_RT=2.0

def dt(s): return datetime.fromisoformat(s.strip()).replace(tzinfo=timezone.utc)
def load(path):
    with open(path,newline="",encoding="utf-8") as f:
        return [dict(time=dt(r["timestamp_utc"]),open=float(r["open"]),high=float(r["high"]),low=float(r["low"]),
                     close=float(r["close"]),spread=float(r.get("spread") or 0),volume=float(r.get("tick_volume") or 0))
                for r in csv.DictReader(f)]

def evaluate(rows,sweep_points,buffer_points,target_mode):
    bars=tuple(MarketBar(timestamp=r["time"],open=r["open"],high=r["high"],low=r["low"],close=r["close"],volume=r["volume"]) for r in rows)
    engine=ReferenceReplayEngine({"EURUSD":bars})
    by_day={}
    for r in rows: by_day.setdefault(r["time"].date(),[]).append(r)
    rs=[]; trades=[]
    for day,dayrows in sorted(by_day.items()):
        asian=[r for r in dayrows if 0 <= r["time"].hour < 6]
        london=[r for r in dayrows if 6 <= r["time"].hour < 11]
        if len(asian)<20 or not london: continue
        ah=max(r["high"] for r in asian); al=min(r["low"] for r in asian); mid=(ah+al)/2
        signal=None; side=None
        for r in london:
            high_sweep=r["high"] >= ah+sweep_points*POINT and r["close"] < ah
            low_sweep=r["low"] <= al-sweep_points*POINT and r["close"] > al
            if high_sweep and not low_sweep: signal=r; side=Side.SHORT; break
            if low_sweep and not high_sweep: signal=r; side=Side.LONG; break
        if signal is None: continue
        idx=rows.index(signal)
        if idx+1>=len(rows): continue
        entryrow=rows[idx+1]
        if entryrow["time"].date()!=day: continue
        entry=entryrow["open"]
        stop=(signal["high"]+buffer_points*POINT) if side==Side.SHORT else (signal["low"]-buffer_points*POINT)
        risk=abs(entry-stop)
        if risk<=0: continue
        if target_mode=="MID":
            target=mid
        elif target_mode=="OPPOSITE":
            target=al if side==Side.SHORT else ah
        elif target_mode=="1.5R":
            target=entry-1.5*risk if side==Side.SHORT else entry+1.5*risk
        else:
            target=entry-2.0*risk if side==Side.SHORT else entry+2.0*risk
        # target must be beyond entry in intended direction
        if (side==Side.LONG and target<=entry) or (side==Side.SHORT and target>=entry): continue
        intent=OrderIntent(candidate_id=f"{day}-{side.value}",instrument="EURUSD",created_at=entryrow["time"],
            side=side,order_type=OrderType.MARKET,entry_price=entry,stop_price=stop,
            targets=(Target(price=target,allocation=1.0),))
        result=engine.execute_one(intent)
        if result.status!=ExecutionStatus.CLOSED or result.gross_r is None: continue
        friction=((entryrow["spread"]+COMMISSION_POINTS_RT+SLIPPAGE_POINTS_RT)*POINT)/risk
        net=float(result.gross_r)-friction
        rs.append(net); trades.append({"day":str(day),"side":side.value,"gross_r":result.gross_r,"friction_r":friction,"net_r":net})
    return {"metrics":asdict(compute_performance(rs)),"trades":trades}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--m15",required=True); p.add_argument("--out",default="artifacts/fx_asian_sweep_dev.json"); a=p.parse_args()
    rows=load(a.m15); grid=[]
    for sweep in (0,2,5):
      for buffer in (2,5,10):
       for target in ("MID","OPPOSITE","1.5R","2R"):
        r=evaluate(rows,sweep,buffer,target); m=r["metrics"]
        ok=m["trades"]>=20 and m["expectancy_r"] is not None and m["expectancy_r"]>0 and m["profit_factor"] is not None and m["profit_factor"]>1
        grid.append({"parameters":{"sweep_points":sweep,"buffer_points":buffer,"target":target},"metrics":m,"qualifies":ok,"trades":r["trades"]})
    elig=[x for x in grid if x["qualifies"]]
    elig.sort(key=lambda x:(-(x["metrics"]["expectancy_r"] or -999),-(x["metrics"]["profit_factor"] or -999),x["parameters"]["sweep_points"],x["parameters"]["buffer_points"],x["parameters"]["target"]))
    selected=elig[0] if elig else None
    payload={"strategy_id":"FX_ASIAN_RANGE_SWEEP_V1","dataset_role":"DEVELOPMENT_CONSUMED","search_space":{"sweep_points":[0,2,5],"buffer_points":[2,5,10],"target":["MID","OPPOSITE","1.5R","2R"],"asian_utc":[0,6],"london_utc":[6,11]},"candidate_count":len(grid),"eligible_count":len(elig),"selected_candidate":selected,"oos_accessed":False,"all_candidates":[{"parameters":x["parameters"],"metrics":x["metrics"],"qualifies":x["qualifies"]} for x in grid]}
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"candidate_count":len(grid),"eligible_count":len(elig),"selected":None if not selected else {"parameters":selected["parameters"],"metrics":selected["metrics"]},"oos_accessed":False},indent=2))
if __name__=="__main__": main()
