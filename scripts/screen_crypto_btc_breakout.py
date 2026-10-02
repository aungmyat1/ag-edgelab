from __future__ import annotations
import argparse,csv,io,json,zipfile
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
import requests
from ag_edgelab.contracts.intent import OrderIntent,OrderType,Side,Target
from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.contracts.trade import ExecutionStatus
from ag_edgelab.engines.reference.replay import ReferenceReplayEngine
from ag_edgelab.statistics.performance import compute_performance

FEE_PER_SIDE=0.001
SLIPPAGE_PER_SIDE=0.0001

def load_month(month):
    url=f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-{month}.zip"
    r=requests.get(url,timeout=60); r.raise_for_status()
    z=zipfile.ZipFile(io.BytesIO(r.content)); out=[]
    with z.open(z.namelist()[0]) as fh:
        for row in csv.reader(io.TextIOWrapper(fh)):
            ts=int(row[0]); sec=ts/1_000_000 if ts>100_000_000_000_000 else ts/1000
            out.append(dict(time=datetime.fromtimestamp(sec,tz=timezone.utc),open=float(row[1]),high=float(row[2]),low=float(row[3]),close=float(row[4]),volume=float(row[5])))
    return out

def ema(v,p):
    a=2/(p+1); cur=None; o=[]
    for i,x in enumerate(v):
        cur=x if cur is None else a*x+(1-a)*cur
        o.append(cur if i+1>=p else None)
    return o

def atr(rows,p=14):
    tr=[]
    for i,r in enumerate(rows):
        pc=rows[i-1]["close"] if i else r["close"]
        tr.append(max(r["high"]-r["low"],abs(r["high"]-pc),abs(r["low"]-pc)))
    o=[]; s=0
    for i,x in enumerate(tr):
        s+=x
        if i>=p:s-=tr[i-p]
        o.append(s/p if i+1>=p else None)
    return o

def aggregate_h4(rows):
    d={}
    for r in rows:
        k=r["time"].replace(hour=(r["time"].hour//4)*4,minute=0,second=0,microsecond=0)
        d.setdefault(k,[]).append(r)
    out=[]
    for k,g in sorted(d.items()):
        out.append(dict(time=k,open=g[0]["open"],high=max(x["high"] for x in g),low=min(x["low"] for x in g),close=g[-1]["close"],volume=sum(x["volume"] for x in g)))
    return out

def evaluate(rows,lookback,atr_mult,rr):
    h4=aggregate_h4(rows); ef=ema([x["close"] for x in h4],20); es=ema([x["close"] for x in h4],50)
    a=atr(rows,14)
    bars=tuple(MarketBar(timestamp=x["time"],open=x["open"],high=x["high"],low=x["low"],close=x["close"],volume=x["volume"]) for x in rows)
    eng=ReferenceReplayEngine({"BTCUSDT":bars}); cursor=-1; blocked=None; rs=[]
    for i in range(max(lookback,14),len(rows)-1):
        r=rows[i]
        if blocked and r["time"]<=blocked: continue
        while cursor+1<len(h4) and h4[cursor+1]["time"].timestamp()+4*3600<=r["time"].timestamp(): cursor+=1
        if cursor<49 or ef[cursor] is None or es[cursor] is None or a[i] is None: continue
        if not (ef[cursor]>es[cursor]): continue
        prior_high=max(x["high"] for x in rows[i-lookback:i])
        if r["close"]<=prior_high: continue
        er=rows[i+1]; entry=er["open"]; risk=atr_mult*a[i]
        stop=entry-risk; target=entry+rr*risk
        intent=OrderIntent(candidate_id=f"BR-{i}",instrument="BTCUSDT",created_at=er["time"],side=Side.LONG,order_type=OrderType.MARKET,entry_price=entry,stop_price=stop,targets=(Target(price=target,allocation=1),))
        res=eng.execute_one(intent)
        if res.status!=ExecutionStatus.CLOSED or res.gross_r is None or res.exit_time is None: continue
        cost_r=(entry*(2*FEE_PER_SIDE+2*SLIPPAGE_PER_SIDE))/risk
        rs.append(float(res.gross_r)-cost_r); blocked=res.exit_time
    return asdict(compute_performance(rs))

def main():
    p=argparse.ArgumentParser(); p.add_argument("--months",nargs="+",default=["2026-05","2026-06","2026-07","2026-08"]); p.add_argument("--out",default="artifacts/crypto_btc_breakout_dev.json"); a=p.parse_args()
    rows=[]
    for m in a.months: rows.extend(load_month(m))
    rows.sort(key=lambda x:x["time"])
    grid=[]
    for lb in (12,24,48):
      for am in (1.5,2.0,3.0):
       for rr in (2.0,3.0,4.0):
        m=evaluate(rows,lb,am,rr)
        ok=m["trades"]>=20 and m["expectancy_r"] is not None and m["expectancy_r"]>0 and m["profit_factor"] is not None and m["profit_factor"]>1
        grid.append({"parameters":{"lookback_h1":lb,"atr_mult":am,"rr":rr},"metrics":m,"qualifies":ok})
    e=[x for x in grid if x["qualifies"]]; e.sort(key=lambda x:(-(x["metrics"]["expectancy_r"] or -999),-(x["metrics"]["profit_factor"] or -999),x["parameters"]["lookback_h1"],x["parameters"]["atr_mult"],x["parameters"]["rr"]))
    selected=e[0] if e else None
    payload={"strategy_id":"CRYPTO_BTC_H4_H1_BREAKOUT_V1","venue":"BINANCE_SPOT","development_months":a.months,"reserved_holdout":"2026-09","fee_per_side":FEE_PER_SIDE,"slippage_per_side":SLIPPAGE_PER_SIDE,"candidate_count":len(grid),"eligible_count":len(e),"selected_candidate":selected,"holdout_accessed":False,"all_candidates":grid}
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"candidate_count":len(grid),"eligible_count":len(e),"selected":selected,"holdout_accessed":False},indent=2))
if __name__=="__main__":main()
