"""FX session module (optional) + crypto diagnostic time metadata.

PROVENANCE NOTE (explicit, not silent): the repository was audited for
canonical UTC session definitions before this module was written. None
exist in code (`ST_ASIAN_SESSION_V1` appears in docs only, without session
times). The UTC windows below are therefore PREREGISTERED by this V0.3
mission with source="PREREGISTERED_UPA_V0_3"; they are declared research
constants, not silently invented repository authority, and any later
repository-canonical definition supersedes them.

Crypto rule (mission section 5): sessions are NOT_APPLICABLE for the crypto
core. Time-of-day is recorded as diagnostic metadata only and must never
gate trades.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ag_edgelab.contracts.market import MarketBar

SESSION_DEFINITION_SOURCE = (
    "PREREGISTERED_UPA_V0_3 (no repository-canonical UTC session definition "
    "found; declared explicitly by the V0.3 mission, not silently created)"
)


class FxSession(StrEnum):
    ASIAN = "ASIAN"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"


class SessionDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session: FxSession
    start_utc_hour: int = Field(ge=0, le=23)
    end_utc_hour: int = Field(ge=1, le=24)
    source: str = SESSION_DEFINITION_SOURCE


SESSION_DEFINITIONS: tuple[SessionDefinition, ...] = (
    SessionDefinition(session=FxSession.ASIAN, start_utc_hour=0, end_utc_hour=8),
    SessionDefinition(session=FxSession.LONDON, start_utc_hour=8, end_utc_hour=16),
    SessionDefinition(session=FxSession.NEW_YORK, start_utc_hour=13, end_utc_hour=21),
)

# LONDON/NEW_YORK overlap by construction: 13:00-16:00 UTC.
LONDON_NY_OVERLAP_UTC = (13, 16)


def active_sessions(ts: datetime) -> tuple[FxSession, ...]:
    """All sessions whose window contains ts (UTC, start-inclusive, end-exclusive)."""
    hour = ts.astimezone(timezone.utc).hour
    return tuple(d.session for d in SESSION_DEFINITIONS if d.start_utc_hour <= hour < d.end_utc_hour)


class SessionSnapshot(BaseModel):
    """Deterministic session features for one session instance on one UTC day."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session: FxSession
    day: str  # YYYY-MM-DD (UTC)
    open_time: datetime
    close_time: datetime
    high: float
    low: float
    midpoint: float
    range: float
    previous_high: float | None = None
    previous_low: float | None = None
    swept_previous_high: bool = False
    swept_previous_low: bool = False
    expansion_vs_previous: float | None = None  # range / previous-instance range
    overlaps_london_ny: bool = False
    bar_count: int = 0


def _window(day: datetime, definition: SessionDefinition) -> tuple[datetime, datetime]:
    base = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return base + timedelta(hours=definition.start_utc_hour), base + timedelta(hours=definition.end_utc_hour)


def compute_session_snapshots(
    bars: tuple[MarketBar, ...],
    session: FxSession,
) -> tuple[SessionSnapshot, ...]:
    """Per-UTC-day snapshots for one session, computed from closed intraday bars.

    A bar belongs to the session when its OPEN timestamp falls inside the
    session window. Sweep flags describe whether THIS session traded beyond
    the previous same-session extreme and closed back inside it (close of
    the sweeping bar back on the origin side).
    """
    definition = next(d for d in SESSION_DEFINITIONS if d.session == session)
    by_day: dict[str, list[MarketBar]] = {}
    for bar in bars:
        ts = bar.timestamp.astimezone(timezone.utc)
        start, end = _window(ts, definition)
        if start <= ts < end:
            by_day.setdefault(ts.date().isoformat(), []).append(bar)

    snapshots: list[SessionSnapshot] = []
    previous: SessionSnapshot | None = None
    for day in sorted(by_day):
        rows = sorted(by_day[day], key=lambda b: b.timestamp)
        high = max(b.high for b in rows)
        low = min(b.low for b in rows)
        swept_high = swept_low = False
        if previous is not None:
            swept_high = any(b.high > previous.high and b.close < previous.high for b in rows)
            swept_low = any(b.low < previous.low and b.close > previous.low for b in rows)
        start, end = _window(rows[0].timestamp.astimezone(timezone.utc), definition)
        snapshot = SessionSnapshot(
            session=session,
            day=day,
            open_time=start,
            close_time=end,
            high=high,
            low=low,
            midpoint=(high + low) / 2.0,
            range=high - low,
            previous_high=None if previous is None else previous.high,
            previous_low=None if previous is None else previous.low,
            swept_previous_high=swept_high,
            swept_previous_low=swept_low,
            expansion_vs_previous=None if previous is None or previous.range <= 0 else (high - low) / previous.range,
            overlaps_london_ny=session in (FxSession.LONDON, FxSession.NEW_YORK),
            bar_count=len(rows),
        )
        snapshots.append(snapshot)
        previous = snapshot
    return tuple(snapshots)


def time_since_session_open_minutes(ts: datetime, session: FxSession) -> float | None:
    """Minutes since this session's open on ts's UTC day; None when not in session."""
    definition = next(d for d in SESSION_DEFINITIONS if d.session == session)
    ts = ts.astimezone(timezone.utc)
    start, end = _window(ts, definition)
    if not (start <= ts < end):
        return None
    return (ts - start).total_seconds() / 60.0


# ---------------------------------------------------------------------------
# Crypto: diagnostic time metadata ONLY — never a gate (mission section 5)
# ---------------------------------------------------------------------------

def crypto_time_metadata(ts: datetime) -> dict:
    """UTC hour / weekday / volatility window as DIAGNOSTIC metadata.

    This function must never be used to accept or reject a crypto candidate;
    it exists purely so time-of-day effects can be inspected after the fact.
    """
    utc = ts.astimezone(timezone.utc)
    window = "UTC_00_08" if utc.hour < 8 else ("UTC_08_16" if utc.hour < 16 else "UTC_16_24")
    return {
        "utc_hour": utc.hour,
        "weekday": utc.strftime("%A").upper(),
        "volatility_window": window,
        "gating": "NEVER",
    }
