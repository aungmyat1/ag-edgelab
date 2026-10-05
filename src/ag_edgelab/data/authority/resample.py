"""Deterministic M1 -> M5/M15/H1/H4/D1 derivation with recorded lineage.

CONTRACT
--------
* Buckets are UTC floors aligned to 00:00 UTC. Every supported timeframe
  divides 1440 minutes, so no bucket ever straddles a UTC day — and hence
  never straddles a calendar year. Per-year derivation is therefore exact
  and identical to deriving from the concatenated multi-year series.

* Emission policy ``ANY_OBSERVATION``: a bucket becomes a bar iff at least
  one source M1 bar exists inside it. Rationale — spot FX genuinely does
  not trade every minute (weekends, holidays, thin Asia hours). A threshold
  policy would DELETE real observations; forward filling would INVENT them.
  Neither is acceptable, so the bar reports exactly what traded and the
  per-bucket coverage is published separately in the audit.

* Nothing is forward filled, interpolated, or back-filled. A bucket with no
  observation produces no row.

* OHLC composition: open = first source open, high = max, low = min,
  close = last source close. ``tick_volume``/``real_volume`` are summed only
  when every contributing bar supplies them; otherwise NULL (never 0).
  ``spread`` is the tick-weighted mean of the source means when every
  contributing bar supplies both spread and tick_volume; otherwise NULL.
  ``bid``/``ask`` are taken from the LAST contributing bar (closing quote).

* Causality: a bar with open time ``T`` and span ``S`` is observable only
  from ``T + S``. :func:`closed_bars_asof` is the only accessor that should
  ever feed a strategy, and it is defined so that truncating the source at
  any point never changes an already-closed bar (truncation invariance).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from ag_edgelab.data.authority.schema import (
    CanonicalBar,
    SchemaViolation,
    canonical_dataset_hash,
)

TIMEFRAME_MINUTES: dict[str, int] = {
    "M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440,
}

DERIVED_TIMEFRAMES: tuple[str, ...] = ("M5", "M15", "H1", "H4", "D1")

EMISSION_POLICY = "ANY_OBSERVATION_NO_FILL"
BOUNDARY_CONVENTION = "UTC_FLOOR_OPEN"

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def floor_utc(ts: datetime, minutes: int) -> datetime:
    """Floor an aware UTC timestamp to a ``minutes`` bucket from 00:00 UTC."""
    ts = ts.astimezone(timezone.utc)
    total = int((ts - _EPOCH).total_seconds()) // 60
    return _EPOCH + timedelta(minutes=(total // minutes) * minutes)


@dataclass(frozen=True)
class CoverageAudit:
    """Per-timeframe coverage statistics — published, never acted on."""

    timeframe: str
    buckets_emitted: int
    expected_slots_per_bucket: int
    fully_covered_buckets: int
    min_slots_present: int
    median_slots_present: int
    buckets_below_half: int

    def as_dict(self) -> dict:
        return {
            "timeframe": self.timeframe,
            "buckets_emitted": self.buckets_emitted,
            "expected_source_slots_per_bucket": self.expected_slots_per_bucket,
            "fully_covered_buckets": self.fully_covered_buckets,
            "min_source_slots_present": self.min_slots_present,
            "median_source_slots_present": self.median_slots_present,
            "buckets_below_half_coverage": self.buckets_below_half,
            "note": (
                "Coverage is reported, not enforced: low-coverage buckets are "
                "genuine thin-liquidity periods, not defects, and are neither "
                "dropped nor filled."
            ),
        }


@dataclass(frozen=True)
class TimeframeLineage:
    """RAW -> M1 -> TF provenance for one derived dataset."""

    symbol: str
    raw_parent_sha256: str
    source_timeframe: str
    source_dataset_sha256: str
    output_timeframe: str
    output_dataset_sha256: str
    rows: int
    emission_policy: str
    boundary_convention: str
    timezone: str
    aggregation_rule: str

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "lineage": f"RAW({self.raw_parent_sha256[:12]}) -> "
                       f"{self.source_timeframe}({self.source_dataset_sha256[:12]}) -> "
                       f"{self.output_timeframe}({self.output_dataset_sha256[:12]})",
            "raw_parent_sha256": self.raw_parent_sha256,
            "source_timeframe": self.source_timeframe,
            "source_dataset_sha256": self.source_dataset_sha256,
            "output_timeframe": self.output_timeframe,
            "output_dataset_sha256": self.output_dataset_sha256,
            "rows": self.rows,
            "emission_policy": self.emission_policy,
            "boundary_convention": self.boundary_convention,
            "timezone": self.timezone,
            "aggregation_rule": self.aggregation_rule,
        }


def resample(
    source: Sequence[CanonicalBar],
    *,
    source_timeframe: str,
    target_timeframe: str,
) -> tuple[tuple[CanonicalBar, ...], CoverageAudit]:
    """Aggregate ``source`` bars into ``target_timeframe`` buckets."""
    if source_timeframe not in TIMEFRAME_MINUTES:
        raise SchemaViolation(f"unknown source timeframe {source_timeframe!r}")
    if target_timeframe not in TIMEFRAME_MINUTES:
        raise SchemaViolation(f"unknown target timeframe {target_timeframe!r}")
    src_minutes = TIMEFRAME_MINUTES[source_timeframe]
    tgt_minutes = TIMEFRAME_MINUTES[target_timeframe]
    if tgt_minutes <= src_minutes or tgt_minutes % src_minutes:
        raise SchemaViolation(
            f"cannot derive {target_timeframe} from {source_timeframe}: target "
            "must be a strict integer multiple of the source")
    expected = tgt_minutes // src_minutes

    groups: dict[datetime, list[CanonicalBar]] = {}
    previous: datetime | None = None
    for bar in source:
        if previous is not None and bar.timestamp_utc <= previous:
            raise SchemaViolation(
                "resample input must be strictly chronological; got "
                f"{bar.timestamp_utc.isoformat()} after {previous.isoformat()}")
        previous = bar.timestamp_utc
        groups.setdefault(floor_utc(bar.timestamp_utc, tgt_minutes), []).append(bar)

    out: list[CanonicalBar] = []
    present_counts: list[int] = []
    for open_time in sorted(groups):
        members = groups[open_time]          # already chronological
        present_counts.append(len(members))
        volumes = [m.tick_volume for m in members]
        reals = [m.real_volume for m in members]
        spreads = [m.spread for m in members]
        tick_volume = sum(volumes) if all(v is not None for v in volumes) else None
        real_volume = (round(sum(reals), 6)
                       if all(v is not None for v in reals) else None)
        if all(s is not None for s in spreads) and tick_volume:
            weighted = sum(s * v for s, v in zip(spreads, volumes))
            spread = round(weighted / tick_volume, 10)
        else:
            spread = None
        last = members[-1]
        out.append(CanonicalBar(
            timestamp_utc=open_time,
            symbol=members[0].symbol,
            open=members[0].open,
            high=max(m.high for m in members),
            low=min(m.low for m in members),
            close=last.close,
            tick_volume=tick_volume,
            real_volume=real_volume,
            spread=spread,
            bid=last.bid,
            ask=last.ask,
        ))

    present_counts.sort()
    audit = CoverageAudit(
        timeframe=target_timeframe,
        buckets_emitted=len(out),
        expected_slots_per_bucket=expected,
        fully_covered_buckets=sum(1 for c in present_counts if c >= expected),
        min_slots_present=present_counts[0] if present_counts else 0,
        median_slots_present=(present_counts[len(present_counts) // 2]
                              if present_counts else 0),
        buckets_below_half=sum(1 for c in present_counts if c * 2 < expected),
    )
    return tuple(out), audit


def derive_all(
    m1: Sequence[CanonicalBar],
    *,
    symbol: str,
    raw_parent_sha256: str,
    m1_dataset_sha256: str,
) -> tuple[dict[str, tuple[CanonicalBar, ...]],
           dict[str, TimeframeLineage],
           dict[str, CoverageAudit]]:
    """Derive every supported timeframe from one M1 lineage."""
    frames: dict[str, tuple[CanonicalBar, ...]] = {}
    lineages: dict[str, TimeframeLineage] = {}
    audits: dict[str, CoverageAudit] = {}
    for timeframe in DERIVED_TIMEFRAMES:
        bars, audit = resample(m1, source_timeframe="M1", target_timeframe=timeframe)
        frames[timeframe] = bars
        audits[timeframe] = audit
        lineages[timeframe] = TimeframeLineage(
            symbol=symbol,
            raw_parent_sha256=raw_parent_sha256,
            source_timeframe="M1",
            source_dataset_sha256=m1_dataset_sha256,
            output_timeframe=timeframe,
            output_dataset_sha256=canonical_dataset_hash(bars),
            rows=len(bars),
            emission_policy=EMISSION_POLICY,
            boundary_convention=BOUNDARY_CONVENTION,
            timezone="UTC",
            aggregation_rule=(
                "open=first, high=max, low=min, close=last; tick_volume and "
                "real_volume summed only when every member supplies them; "
                "spread = tick-weighted mean of member means; bid/ask from the "
                "last member. No fill, no interpolation."
            ),
        )
    return frames, lineages, audits


# ---------------------------------------------------------------------------
# causal accessors
# ---------------------------------------------------------------------------

def closed_bars_asof(
    bars: Sequence[CanonicalBar], *, timeframe: str, asof: datetime,
) -> tuple[CanonicalBar, ...]:
    """Bars whose bucket has fully CLOSED at or before ``asof``.

    Guarantees (tested):
      * no returned bar can still change if more source data arrives;
      * ``closed_bars_asof(resample(m1[:k]))`` is a prefix of
        ``closed_bars_asof(resample(m1))`` for every k — truncation
        invariance;
      * never returns the still-forming bucket.
    """
    if timeframe not in TIMEFRAME_MINUTES:
        raise SchemaViolation(f"unknown timeframe {timeframe!r}")
    span = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
    asof = asof.astimezone(timezone.utc)
    return tuple(b for b in bars if b.timestamp_utc + span <= asof)


def resample_closed_asof(
    source: Sequence[CanonicalBar],
    *,
    source_timeframe: str,
    target_timeframe: str,
    asof: datetime,
) -> tuple[CanonicalBar, ...]:
    """Derive-and-expose in one causal step (no still-forming bucket leaks)."""
    asof = asof.astimezone(timezone.utc)
    tgt_minutes = TIMEFRAME_MINUTES[target_timeframe]
    forming_open = floor_utc(asof, tgt_minutes)
    eligible = [b for b in source if b.timestamp_utc < forming_open]
    bars, _ = resample(eligible, source_timeframe=source_timeframe,
                       target_timeframe=target_timeframe)
    return closed_bars_asof(bars, timeframe=target_timeframe, asof=asof)


def lineage_chain_hash(lineages: Sequence[TimeframeLineage]) -> str:
    """Stable digest over a lineage set — pinned in the lineage manifest."""
    digest = hashlib.sha256()
    for item in sorted(lineages, key=lambda l: (l.symbol, l.output_timeframe)):
        digest.update(
            f"{item.symbol}|{item.raw_parent_sha256}|{item.source_dataset_sha256}|"
            f"{item.output_timeframe}|{item.output_dataset_sha256}\n".encode("utf-8"))
    return digest.hexdigest()
