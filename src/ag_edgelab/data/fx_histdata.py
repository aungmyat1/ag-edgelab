from __future__ import annotations

"""Pinned HistData ASCII M1 acquisition and causal FX timeframe derivation.

This is the generic data layer extracted from the PR #10 SESSION_TRADE_V2
pipeline.  It contains no SESSION_TRADE strategy logic.
"""

import csv, hashlib, io, json, zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ag_edgelab.contracts.market import MarketBar

NY = ZoneInfo("America/New_York")
UTC = timezone.utc
M15_REQUIRED = 13
SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")
EXPECTED_RAW_SHA256 = {
    "EURUSD": "0dcd66dc67d7af4716404a5315d376ee1e7eaebe292afbda3c1003d2dfa16f57",
    "GBPUSD": "e5ba3800e37fae0e326dbaa234952ca04e8f378c08b036530a2811206110c10b",
    "USDJPY": "477a1f515586f06d67cb75b3662260160e1e29e63c51804a30a5e7d69b09df5f",
    "XAUUSD": "a39c1ccaaeb022c83309685107c9e619c2bcff8b2fd94fbd7405a721a4fe70ff",
}
MIRROR = "parrondo/deeptrading"
SOURCE_TZ = "America/New_York"
NORMALIZED_TZ = "UTC"

@dataclass(frozen=True)
class Derivation:
    symbol: str
    timeframe: str
    source_raw_sha256: str
    aggregation_contract_version: str
    first_timestamp: str | None
    last_timestamp: str | None
    bar_count: int
    dataset_sha256: str
    incomplete_buckets_rejected: int


def _hash_bars(bars: tuple[MarketBar, ...]) -> str:
    payload = "\n".join(f"{b.timestamp.isoformat()},{b.open:.12g},{b.high:.12g},{b.low:.12g},{b.close:.12g}" for b in bars) + "\n"
    return hashlib.sha256(payload.encode()).hexdigest()


def _validate_raw_path(path: Path, symbol: str) -> str:
    expected_name = f"HISTDATA_COM_ASCII_{symbol}_M1_2017.zip"
    if path.name != expected_name:
        raise ValueError(f"wrong archive name for {symbol}: {path.name}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != EXPECTED_RAW_SHA256[symbol]:
        raise ValueError(f"RAW_DATA_HASH_MISMATCH {symbol}: {digest} != {EXPECTED_RAW_SHA256[symbol]}")
    return digest


def load_m1(path: Path, symbol: str, *, end: datetime | None = None) -> tuple[MarketBar, ...]:
    raw_sha = _validate_raw_path(path, symbol)
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"{symbol}: corrupt or ambiguous archive members")
        with zf.open(names[0]) as fh:
            rows = list(csv.reader(io.TextIOWrapper(fh, encoding="utf-8"), delimiter=";"))
    bars=[]
    for row in rows:
        if not row: continue
        if len(row) < 5: raise ValueError(f"{symbol}: malformed row")
        try:
            ts = datetime.strptime(row[0], "%Y%m%d %H%M%S").replace(tzinfo=NY).astimezone(UTC)
            if end is not None and ts >= end.astimezone(UTC):
                continue
            o,h,l,c = map(float, row[1:5])
            bars.append(MarketBar(timestamp=ts, open=o, high=h, low=l, close=c))
        except Exception as exc:
            raise ValueError(f"{symbol}: malformed observation {row[:5]}") from exc
    stamps=[b.timestamp for b in bars]
    if len(stamps) != len(set(stamps)): raise ValueError(f"{symbol}: duplicate timestamp")
    if stamps != sorted(stamps): raise ValueError(f"{symbol}: non-monotonic timestamp")
    return tuple(bars)


def _floor(ts: datetime, minutes: int) -> datetime:
    ts=ts.astimezone(UTC).replace(second=0,microsecond=0)
    return ts.replace(minute=(ts.minute//minutes)*minutes) if minutes < 60 else ts.replace(hour=((ts.hour*60+ts.minute)//minutes)*(minutes//60), minute=0)


def _aggregate(source: tuple[MarketBar,...], minutes: int, required: int) -> tuple[tuple[MarketBar,...], int]:
    buckets={}
    for b in source: buckets.setdefault(_floor(b.timestamp,minutes),[]).append(b)
    out=[]; rejected=0; expected=minutes
    for key, group in sorted(buckets.items()):
        unique={b.timestamp for b in group}
        if len(unique) < required: rejected += 1; continue
        # For H1/H4/D1 this is only called on complete lower-timeframe bars.
        ordered=sorted(group,key=lambda b:b.timestamp)
        out.append(MarketBar(timestamp=key,open=ordered[0].open,high=max(x.high for x in ordered),low=min(x.low for x in ordered),close=ordered[-1].close))
    return tuple(out), rejected


def derive_all(m1: tuple[MarketBar,...], symbol: str, raw_sha: str):
    m15, rej15 = _aggregate(m1,15,M15_REQUIRED)
    h1, rej1 = _aggregate(m15,60,4)
    h4, rej4 = _aggregate(h1,240,4)
    # HistData's FX/CFD session has a documented daily reopen/close gap;
    # five complete UTC H4 bars are the maximum available on normal trading
    # days.  This is a coverage rule, not a fill: no absent bucket is made.
    d1, rejd = _aggregate(h4,1440,5)
    result={"M1":m1,"M15":m15,"H1":h1,"H4":h4,"D1":d1}
    lineage={}
    for tf,bars,rej in (("M1",m1,0),("M15",m15,rej15),("H1",h1,rej1),("H4",h4,rej4),("D1",d1,rejd)):
        lineage[tf]=Derivation(symbol,tf,raw_sha,"FX_HISTDATA_CAUSAL_UTC_V1",bars[0].timestamp.isoformat() if bars else None,bars[-1].timestamp.isoformat() if bars else None,len(bars),_hash_bars(bars),rej)
    return result,lineage


def closed(bars: tuple[MarketBar,...], timeframe: str, asof: datetime) -> tuple[MarketBar,...]:
    spans={"M15":15,"H1":60,"H4":240,"D1":1440}
    span=timedelta(minutes=spans[timeframe]); return tuple(b for b in bars if b.timestamp+span <= asof)


def manifest_entry(symbol: str, path: Path, lineages: dict[str,Derivation], coverage_start: str, coverage_end: str) -> dict:
    raw_sha=_validate_raw_path(path,symbol)
    return {"symbol":symbol,"provider":"HISTDATA","mirror_repository":MIRROR,"mirror_path":f"data/raw/{symbol.lower()}/"+path.name,"filename":path.name,"raw_sha256":raw_sha,"source_timezone":SOURCE_TZ,"normalized_timezone":NORMALIZED_TZ,"coverage_start":coverage_start,"coverage_end":coverage_end,"derived":{k:vars(v) for k,v in lineages.items()}}
