"""Spread evidence: individual quote observations and their distributions.

A single "typical spread" number is the most common way friction analysis
goes wrong. Spread is a distribution with a long right tail that fattens
exactly when a strategy is most likely to be trading — news, session
opens, the rollover window. Collapsing it to one value understates cost
precisely where it matters, so this module keeps the whole distribution
and tags every observation with its session.

Quality handling follows the data authority's rule: classify, never
silently repair. A crossed quote (bid > ask) is recorded and excluded
from statistics with a reason, not quietly dropped or reordered.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from enum import StrEnum

from ag_edgelab.friction.authority.symbols import SymbolSpec

SPREAD_OBSERVATION_SCHEMA_VERSION = "EDGELAB_SPREAD_OBSERVATION_V1"


class Session(StrEnum):
    """Session bucket of an observation, by UTC hour.

    Diagnostic only — these are conventional market hours used to slice
    the evidence, not a trading rule. Boundaries are declared here so the
    bucketing is reproducible rather than ad hoc.
    """

    ASIAN = "ASIAN"                  # 00:00-07:00 UTC
    LONDON = "LONDON"                # 07:00-12:00 UTC
    OVERLAP = "OVERLAP"              # 12:00-16:00 UTC (London + New York)
    NEW_YORK = "NEW_YORK"            # 16:00-21:00 UTC
    OTHER = "OTHER"                  # 21:00-24:00 UTC (rollover / thin)


SESSION_BOUNDS_UTC: tuple[tuple[Session, int, int], ...] = (
    (Session.ASIAN, 0, 7),
    (Session.LONDON, 7, 12),
    (Session.OVERLAP, 12, 16),
    (Session.NEW_YORK, 16, 21),
    (Session.OTHER, 21, 24),
)


def session_for(ts: datetime) -> Session:
    hour = ts.astimezone(timezone.utc).hour
    for session, lo, hi in SESSION_BOUNDS_UTC:
        if lo <= hour < hi:
            return session
    return Session.OTHER


class QuoteDefect(StrEnum):
    CROSSED = "CROSSED"              # bid > ask
    ZERO_SPREAD = "ZERO_SPREAD"      # bid == ask
    NONPOSITIVE = "NONPOSITIVE"      # bid or ask <= 0
    STALE_DUPLICATE = "STALE_DUPLICATE"


@dataclass(frozen=True)
class SpreadObservation:
    """One bid/ask snapshot. Raw evidence, never adjusted."""

    timestamp_utc: datetime
    symbol: str
    bid: float
    ask: float
    session: Session | None = None
    source: str = ""

    @property
    def spread_price(self) -> float:
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        return (self.ask + self.bid) / 2.0

    def defects(self) -> tuple[QuoteDefect, ...]:
        found: list[QuoteDefect] = []
        if self.bid <= 0 or self.ask <= 0:
            found.append(QuoteDefect.NONPOSITIVE)
        if self.ask < self.bid:
            found.append(QuoteDefect.CROSSED)
        elif self.ask == self.bid:
            found.append(QuoteDefect.ZERO_SPREAD)
        return tuple(found)

    @property
    def is_valid(self) -> bool:
        """Usable for statistics: positive prices and bid <= ask.

        A zero spread is NOT a defect that invalidates the quote — some
        venues genuinely print locked markets — but it is counted
        separately so it cannot hide inside a median.
        """
        return not ({QuoteDefect.NONPOSITIVE, QuoteDefect.CROSSED}
                    & set(self.defects()))

    def spread_points(self, spec: SymbolSpec) -> float:
        return spec.price_to_points(self.spread_price)

    def spread_pips(self, spec: SymbolSpec) -> float:
        return spec.price_to_pips(self.spread_price)

    def as_row(self, spec: SymbolSpec | None = None) -> dict:
        row = {
            "timestamp_utc": self.timestamp_utc.astimezone(timezone.utc)
                                 .isoformat().replace("+00:00", "Z"),
            "symbol": self.symbol,
            "bid": self.bid,
            "ask": self.ask,
            "spread_price": round(self.spread_price, 10),
            "session": str(self.session or session_for(self.timestamp_utc)),
            "source": self.source,
        }
        if spec is not None and spec.point is not None:
            row["spread_points"] = round(self.spread_points(spec), 6)
            row["spread_pips_or_instrument_units"] = (
                round(self.spread_pips(spec), 6) if spec.has_pips
                else round(self.spread_price, 10))
            row["quote_unit"] = "pips" if spec.has_pips else "instrument_units"
        return row


def _quantile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank quantile — deterministic and interpolation-free.

    Interpolated quantiles invent values that never occurred. For cost
    evidence an actually-observed spread is preferable to an average of
    two neighbours.
    """
    if not sorted_values:
        raise ValueError("no values")
    rank = max(1, min(len(sorted_values),
                      int(-(-q * len(sorted_values) // 1))))  # ceil
    return sorted_values[rank - 1]


@dataclass
class SpreadDistribution:
    """Order statistics for one (symbol, session) cell."""

    symbol: str
    session: str
    unit: str
    n: int = 0
    minimum: float | None = None
    p25: float | None = None
    p50: float | None = None
    p75: float | None = None
    p90: float | None = None
    p95: float | None = None
    p99: float | None = None
    maximum: float | None = None
    mean: float | None = None
    zero_spread_count: int = 0
    invalid_quote_count: int = 0
    outlier_count: int = 0
    outlier_threshold: float | None = None
    first_observation_utc: str | None = None
    last_observation_utc: str | None = None

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "session": self.session,
            "unit": self.unit,
            "N": self.n,
            "MIN": self.minimum,
            "P25": self.p25,
            "P50": self.p50,
            "P75": self.p75,
            "P90": self.p90,
            "P95": self.p95,
            "P99": self.p99,
            "MAX": self.maximum,
            "MEAN": self.mean,
            "zero_spread_count": self.zero_spread_count,
            "invalid_quote_count": self.invalid_quote_count,
            "outlier_count": self.outlier_count,
            "outlier_threshold": self.outlier_threshold,
            "first_observation_utc": self.first_observation_utc,
            "last_observation_utc": self.last_observation_utc,
        }


#: An observation above this multiple of the median is flagged as an
#: outlier. It is COUNTED and RETAINED — a spread spike is real cost, not
#: a measurement error, and discarding the tail is how friction analysis
#: flatters itself.
OUTLIER_MEDIAN_MULTIPLE = 10.0


def summarise(
    observations: list[SpreadObservation],
    *,
    spec: SymbolSpec,
    session: str,
    outlier_multiple: float = OUTLIER_MEDIAN_MULTIPLE,
) -> SpreadDistribution:
    """Order statistics for one cell. Outliers are counted, never removed."""
    unit = "pips" if spec.has_pips else "instrument_units"
    dist = SpreadDistribution(symbol=spec.symbol, session=session, unit=unit)

    valid = [o for o in observations if o.is_valid]
    dist.invalid_quote_count = len(observations) - len(valid)
    dist.zero_spread_count = sum(
        1 for o in valid if QuoteDefect.ZERO_SPREAD in o.defects())
    if not valid:
        return dist

    stamps = sorted(o.timestamp_utc for o in valid)
    dist.first_observation_utc = stamps[0].astimezone(timezone.utc) \
        .isoformat().replace("+00:00", "Z")
    dist.last_observation_utc = stamps[-1].astimezone(timezone.utc) \
        .isoformat().replace("+00:00", "Z")

    values = sorted(
        (o.spread_pips(spec) if spec.has_pips else o.spread_price) for o in valid)
    dist.n = len(values)
    dist.minimum = round(values[0], 6)
    dist.maximum = round(values[-1], 6)
    dist.mean = round(statistics.fmean(values), 6)
    for label, q in (("p25", 0.25), ("p50", 0.50), ("p75", 0.75),
                     ("p90", 0.90), ("p95", 0.95), ("p99", 0.99)):
        setattr(dist, label, round(_quantile(values, q), 6))

    median = dist.p50 or 0.0
    if median > 0:
        dist.outlier_threshold = round(median * outlier_multiple, 6)
        dist.outlier_count = sum(1 for v in values if v > dist.outlier_threshold)
    return dist


@dataclass
class SpreadEvidence:
    """All observations for one symbol, sliced by session."""

    symbol: str
    observations: list[SpreadObservation] = field(default_factory=list)

    def by_session(self) -> dict[str, list[SpreadObservation]]:
        buckets: dict[str, list[SpreadObservation]] = {}
        for obs in self.observations:
            key = str(obs.session or session_for(obs.timestamp_utc))
            buckets.setdefault(key, []).append(obs)
        return buckets

    def distributions(self, spec: SymbolSpec) -> dict[str, SpreadDistribution]:
        out = {"ALL": summarise(self.observations, spec=spec, session="ALL")}
        for session, rows in sorted(self.by_session().items()):
            out[session] = summarise(rows, spec=spec, session=session)
        return out
