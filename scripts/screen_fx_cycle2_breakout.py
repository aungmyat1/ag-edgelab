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
CONSERVATIVE_COST_POINTS_RT=23.0

def dt(s): return datetime.fromisoformat(s.strip()).replace(tzinfo=timezone.utc)
def load(path):
    with open(path,newline="",encoding="utf-8") as f:
        return [dict(time=dt(r["timestamp_utc"]),open=float(r["open"]),high=float(r["high"]),low=float(r["low"]),close=float(r["close"]),volume=float(r.get("tick_volume") or 0)) for r in csv.DictReader(f)]
def ema(v,p):
    a=2/(p+1);cur=None;o=[]
    for i,x in enumerate(v):
        cur=x if cur is None else a*x+(1-a)*cur;o.append(cur if i+1>=p else None)
    return o
def atr(rows,p=14):
    t=[]
    for i,r in enumerate(rows):
        pc=rows[i-1]["close"] if i else r["close"]
        t.append(max(r["high"]-r["low"],abs(r["high"]-pc),abs(r["low"]-pc)))
    o=[];s=0
    for i,x in enumerate(t):
        s+=x
        if i>=p:s-=t[i-p]
        o.append(s/p if i+1>=p else None)
    return o
def h4(rows):
    d={}
    for r in rows:
        k=r["time"].replace(hour=(r["time"].hour//4)*4,minute=0,second=0,microsecond=0);d.setdefault(k,[]).append(r)
    return [dict(time=k,open=g[0]["open"],high=max(x["high"] for x in g),low=min(x["low"] for x in g),close=g[-1]["close"],volume=sum(x["volume"] for x in g)) for k,g in sorted(d.items())]
def evaluate(rows,lookback,atr_mult,rr):
    h=h4(rows);ef=ema([x["close"] for x in h],20);es=ema([x["close"] for x in h],50);a=atr(rows,14)
    bars=tuple(MarketBar(timestamp=x["time"],open=x["open"],high=x["high"],low=x["low"],close=x["close"],volume=x["volume"]) for x in rows)
    eng=ReferenceReplayEngine({"EURUSD":bars});cur=-1;blocked=None;rs=[]
    for i in range(max(lookback,14),len(rows)-1):
        r=rows[i]
        if blocked and r["time"]<=blocked:continue
        if not (6<=r["time"].hour<16):continue
        while cur+1<len(h) and h[cur+1]["time"].timestamp()+4*3600<=r["time"].timestamp():cur+=1
        if cur<49 or ef[cur] is None or es[cur] is None or a[i] is None:continue
        if ef[cur]>es[cur]:
            side=Side.LONG;level=max(x["high"] for x in rows[i-lookback:i]);trigger=r["close"]>level
        elif ef[cur]<es[cur]:
            side=Side.SHORT;level=min(x["low"] for x in rows[i-lookback:i]);trigger=r["close"]<level
        else:continue
        if not trigger:continue
        er=rows[i+1];entry=er["open"];risk=atr_mult*a[i]
        stop=entry-risk if side==Side.LONG else entry+risk
        target=entry+rr*risk if side==Side.LONG else entry-rr*risk
        intent=OrderIntent(candidate_id=f"FX2-{i}",instrument="EURUSD",created_at=er["time"],side=side,order_type=OrderType.MARKET,entry_price=entry,stop_price=stop,targets=(Target(price=target,allocation=1),))
        res=eng.execute_one(intent)
        if res.status!=ExecutionStatus.CLOSED or res.gross_r is None or res.exit_time is None:continue
        cost_r=(CONSERVATIVE_COST_POINTS_RT*POINT)/risk
        rs.append(float(res.gross_r)-cost_r);blocked=res.exit_time
    return asdict(compute_performance(rs))
def main():
    p=argparse.ArgumentParser();p.add_argument("--h1",required=True);p.add_argument("--out",default="artifacts/fx_cycle2_breakout_dev.json");a=p.parse_args()
    rows=load(a.h1);grid=[]
    for lb in (12,24,48):
      for am in (1.5,2.0,3.0):
       for rr in (2.0,3.0,4.0):
        m=evaluate(rows,lb,am,rr);ok=m["trades"]>=30 and m["expectancy_r"] is not None and m["expectancy_r"]>0 and m["profit_factor"] is not None and m["profit_factor"]>1
        grid.append({"parameters":{"lookback_h1":lb,"atr_mult":am,"rr":rr},"metrics":m,"qualifies":ok})
    e=[x for x in grid if x["qualifies"]];e.sort(key=lambda x:(-(x["metrics"]["expectancy_r"] or -999),-(x["metrics"]["profit_factor"] or -999),x["parameters"]["lookback_h1"],x["parameters"]["atr_mult"],x["parameters"]["rr"]))
    selected=e[0] if e else None
    payload={"strategy_id":"FX_H4_H1_BREAKOUT_V1","development_role":"CONSUMED_DEVELOPMENT","reserved_oos":"SSC1D_WP1_OOS_EURUSD_2024Q1_H1","conservative_cost_points_round_trip":CONSERVATIVE_COST_POINTS_RT,"candidate_count":len(grid),"eligible_count":len(e),"selected_candidate":selected,"oos_accessed":False,"all_candidates":grid}
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"candidate_count":len(grid),"eligible_count":len(e),"selected":selected,"oos_accessed":False},indent=2))
if __name__=="__main__":main()
