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

def load_month(year_month):
    url=f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/5m/BTCUSDT-5m-{year_month}.zip"
    r=requests.get(url,timeout=60); r.raise_for_status()
    z=zipfile.ZipFile(io.BytesIO(r.content)); name=z.namelist()[0]
    out=[]
    with z.open(name) as fh:
        text=io.TextIOWrapper(fh)
        for row in csv.reader(text):
            ts=int(row[0])
            seconds = ts / 1_000_000 if ts > 100_000_000_000_000 else ts / 1000
            out.append(dict(time=datetime.fromtimestamp(seconds,tz=timezone.utc),open=float(row[1]),high=float(row[2]),low=float(row[3]),close=float(row[4]),volume=float(row[5])))
    return out

def ema(vals,p):
    a=2/(p+1); cur=None; out=[]
    for i,v in enumerate(vals):
        cur=v if cur is None else a*v+(1-a)*cur
        out.append(cur if i+1>=p else None)
    return out

def atr(rows,p=14):
    tr=[]
    for i,r in enumerate(rows):
        pc=rows[i-1]["close"] if i else r["close"]
        tr.append(max(r["high"]-r["low"],abs(r["high"]-pc),abs(r["low"]-pc)))
    out=[]; s=0
    for i,v in enumerate(tr):
        s+=v
        if i>=p:s-=tr[i-p]
        out.append(s/p if i+1>=p else None)
    return out

def aggregate_h1(rows):
    d={}
    for r in rows:
        k=r["time"].replace(minute=0,second=0,microsecond=0); d.setdefault(k,[]).append(r)
    out=[]
    for k,g in sorted(d.items()):
        out.append(dict(time=k,open=g[0]["open"],high=max(x["high"] for x in g),low=min(x["low"] for x in g),close=g[-1]["close"],volume=sum(x["volume"] for x in g)))
    return out

def evaluate(rows,atr_mult,rr,body_min):
    h1=aggregate_h1(rows); hf=ema([r["close"] for r in h1],20); hs=ema([r["close"] for r in h1],50)
    mf=ema([r["close"] for r in rows],20); ma=atr(rows,14)
    bars=tuple(MarketBar(timestamp=r["time"],open=r["open"],high=r["high"],low=r["low"],close=r["close"],volume=r["volume"]) for r in rows)
    engine=ReferenceReplayEngine({"BTCUSDT":bars}); rs=[]; cursor=-1; blocked=None
    for i in range(1,len(rows)-1):
        r=rows[i]
        if blocked and r["time"]<=blocked: continue
        while cursor+1<len(h1) and h1[cursor+1]["time"].timestamp()+3600<=r["time"].timestamp(): cursor+=1
        if cursor<49 or mf[i] is None or mf[i-1] is None or ma[i] is None: continue
        if hf[cursor]>hs[cursor]:
            side=Side.LONG; cross=rows[i-1]["close"]<=mf[i-1] and r["close"]>mf[i]; body=(r["close"]-r["open"])>=body_min*ma[i]
        elif hf[cursor]<hs[cursor]:
            side=Side.SHORT; cross=rows[i-1]["close"]>=mf[i-1] and r["close"]<mf[i]; body=(r["open"]-r["close"])>=body_min*ma[i]
        else: continue
        if not cross or not body: continue
        er=rows[i+1]; entry=er["open"]; risk=atr_mult*ma[i]
        stop=entry-risk if side==Side.LONG else entry+risk
        target=entry+rr*risk if side==Side.LONG else entry-rr*risk
        intent=OrderIntent(candidate_id=f"B{i}",instrument="BTCUSDT",created_at=er["time"],side=side,order_type=OrderType.MARKET,entry_price=entry,stop_price=stop,targets=(Target(price=target,allocation=1),))
        res=engine.execute_one(intent)
        if res.status!=ExecutionStatus.CLOSED or res.gross_r is None or res.exit_time is None: continue
        friction_r=(entry*(2*FEE_PER_SIDE+2*SLIPPAGE_PER_SIDE))/risk
        rs.append(float(res.gross_r)-friction_r); blocked=res.exit_time
    return asdict(compute_performance(rs))

def main():
    p=argparse.ArgumentParser(); p.add_argument("--month",default="2026-08"); p.add_argument("--out",default="artifacts/crypto_btc_spot_dev.json"); a=p.parse_args()
    rows=load_month(a.month); grid=[]
    for am in (1.0,1.5,2.0):
      for rr in (1.5,2.0,2.5):
       for bm in (0.0,0.2,0.4):
        m=evaluate(rows,am,rr,bm); ok=m["trades"]>=30 and m["expectancy_r"] is not None and m["expectancy_r"]>0 and m["profit_factor"] is not None and m["profit_factor"]>1
        grid.append({"parameters":{"atr_mult":am,"rr":rr,"body_atr_min":bm},"metrics":m,"qualifies":ok})
    e=[x for x in grid if x["qualifies"]]; e.sort(key=lambda x:(-(x["metrics"]["expectancy_r"] or -999),-(x["metrics"]["profit_factor"] or -999)))
    selected=e[0] if e else None
    payload={"strategy_id":"CRYPTO_BTC_TREND_PULLBACK_V1","venue":"BINANCE_SPOT","development_month":a.month,"fee_per_side":FEE_PER_SIDE,"slippage_per_side":SLIPPAGE_PER_SIDE,"candidate_count":len(grid),"eligible_count":len(e),"selected_candidate":selected,"oos_accessed":False,"all_candidates":grid}
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"candidate_count":len(grid),"eligible_count":len(e),"selected":selected,"oos_accessed":False},indent=2))
if __name__=="__main__":main()
