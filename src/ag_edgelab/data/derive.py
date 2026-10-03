"""Deterministic higher-timeframe derivation from a single source timeframe.

Rules:
- All bucketing is by UTC timestamp, floored to the target boundary
  (boundary_convention = "FLOOR_OPEN", timezone = "UTC").
- A derived bar is only emitted when the bucket is COMPLETE, i.e. no further
  source bar can ever fall inside it given a gap-free or gap-documented
  source. Buckets with any missing source slot are emitted as
  PARTIAL/GAPPED only in audit output; they are never silently marked closed.
- A derived bar with open time T and span S becomes available at T+S (its
  close). ``closed_derived_bars`` is the only accessor strategies use, and it
  never exposes an incomplete bucket.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.bars import dumps_bars

TIMEFRAME_MINUTES: dict[str, int] = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}

FLOOR_OPEN = "FLOOR_OPEN"
UTC = "UTC"


class DerivedLineage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_dataset_hash: str
    source_timeframe: str
    output_timeframe: str
    aggregation_rule: str
    timezone: str
    boundary_convention: str
    output_hash: str
    rows: int


def floor_open(ts: datetime, minutes: int) -> datetime:
    """UTC floor of `ts` to a `minutes`-sized bucket aligned to 00:00 UTC."""
    ts = ts.astimezone(timezone.utc)
    midnight = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    bucket = int((ts - midnight).total_seconds() // (minutes * 60))
    return midnight + timedelta(minutes=bucket * minutes)


@dataclass(frozen=True)
class BucketAudit:
    open_time: datetime
    expected_slots: int
    present_slots: int
    complete: bool


def aggregate_bars(
    source: tuple[MarketBar, ...],
    source_timeframe: str,
    target_timeframe: str,
) -> tuple[tuple[MarketBar, ...], tuple[BucketAudit, ...]]:
    """Aggregate source bars into complete target buckets.

    Returns (bars, audit). Only buckets with every expected source slot
    present are emitted as bars; incomplete/gapped buckets appear only in
    the audit (documented, never forward-filled).
    """
    src_minutes = TIMEFRAME_MINUTES[source_timeframe]
    tgt_minutes = TIMEFRAME_MINUTES[target_timeframe]
    if tgt_minutes <= src_minutes or tgt_minutes % src_minutes != 0:
        raise ValueError(f"cannot derive {target_timeframe} from {source_timeframe}")
    slots_per_bucket = tgt_minutes // src_minutes

    buckets: dict[datetime, list[MarketBar]] = {}
    for bar in sorted(source, key=lambda b: b.timestamp):
        buckets.setdefault(floor_open(bar.timestamp, tgt_minutes), []).append(bar)

    out: list[MarketBar] = []
    audit: list[BucketAudit] = []
    for open_time in sorted(buckets):
        group = buckets[open_time]
        seen_opens = {floor_open(bar.timestamp, src_minutes) for bar in group}
        complete = len(seen_opens) == slots_per_bucket
        audit.append(
            BucketAudit(
                open_time=open_time,
                expected_slots=slots_per_bucket,
                present_slots=len(seen_opens),
                complete=complete,
            )
        )
        if not complete:
            continue
        ordered = sorted(group, key=lambda b: b.timestamp)
        volume = None if any(bar.volume is None for bar in ordered) else sum(float(bar.volume) for bar in ordered)
        out.append(
            MarketBar(
                timestamp=open_time,
                open=ordered[0].open,
                high=max(bar.high for bar in ordered),
                low=min(bar.low for bar in ordered),
                close=ordered[-1].close,
                volume=volume,
            )
        )
    return tuple(out), tuple(audit)


def derive_timeframe(
    source: tuple[MarketBar, ...],
    source_timeframe: str,
    target_timeframe: str,
    source_dataset_hash: str,
) -> tuple[tuple[MarketBar, ...], DerivedLineage, tuple[BucketAudit, ...]]:
    bars, audit = aggregate_bars(source, source_timeframe, target_timeframe)
    payload = dumps_bars(bars)
    lineage = DerivedLineage(
        source_dataset_hash=source_dataset_hash,
        source_timeframe=source_timeframe,
        output_timeframe=target_timeframe,
        aggregation_rule="UTC_FLOOR_BUCKET_OHLC_SUM_VOLUME_COMPLETE_BUCKETS_ONLY",
        timezone=UTC,
        boundary_convention=FLOOR_OPEN,
        output_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        rows=len(bars),
    )
    return bars, lineage, audit


def closed_derived_bars(
    source: tuple[MarketBar, ...],
    source_timeframe: str,
    target_timeframe: str,
    asof: datetime,
) -> tuple[MarketBar, ...]:
    """Derived bars available no later than `asof` (bucket close <= asof).

    Anti-lookahead primitive: contains no bar built from source bars opening
    at or after `asof`, and never exposes the still-forming bucket.
    """
    asof = asof.astimezone(timezone.utc)
    tgt_minutes = TIMEFRAME_MINUTES[target_timeframe]
    cutoff_open = floor_open(asof, tgt_minutes)  # bucket that is still forming
    eligible = tuple(bar for bar in source if bar.timestamp < cutoff_open)
    bars, _ = aggregate_bars(eligible, source_timeframe, target_timeframe)
    return tuple(bar for bar in bars if bar.timestamp + timedelta(minutes=tgt_minutes) <= asof)


def verify_lineage(lineage: DerivedLineage, bars: tuple[MarketBar, ...]) -> bool:
    payload = dumps_bars(bars)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest() == lineage.output_hash and len(bars) == lineage.rows
