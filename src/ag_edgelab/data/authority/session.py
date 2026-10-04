"""Declared venue session contracts.

The weekly boundary of a 24x5 instrument is a venue convention, not a
universal constant, and getting it wrong silently corrupts every
"missing bar" and "coverage %" number downstream:

* spot FX (EURUSD, GBPUSD, USDJPY) runs 17:00 America/New_York Sunday to
  17:00 America/New_York Friday;
* CME metals (XAUUSD) run 17:00 America/Chicago Sunday to 17:00
  America/Chicago Friday.

Both are wall-clock rules in a DST-observing exchange timezone, so the UTC
hour of the boundary moves twice a year. These contracts are DECLARED here
and then CONFIRMED against the data by
:mod:`ag_edgelab.data.authority.timezone_proof`, which scores every
(clock offset, session contract) pair and requires a unique winner. A
symbol whose data matches no declared contract is reported as ambiguous
rather than forced into one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SUNDAY = 6
FRIDAY = 4


@dataclass(frozen=True)
class SessionContract:
    """A weekly trading window expressed in an exchange wall clock."""

    contract_id: str
    venue_timezone: str
    open_weekday: int          # Python weekday(): Monday=0 ... Sunday=6
    open_hour: int
    close_weekday: int
    close_hour: int
    daily_break_start_hour: int | None = None
    daily_break_end_hour: int | None = None
    description: str = ""

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.venue_timezone)

    def as_dict(self) -> dict:
        return {
            "contract_id": self.contract_id,
            "venue_timezone": self.venue_timezone,
            "weekly_open": f"{_DAY[self.open_weekday]} {self.open_hour:02d}:00 "
                           f"{self.venue_timezone}",
            "weekly_close": f"{_DAY[self.close_weekday]} {self.close_hour:02d}:00 "
                            f"{self.venue_timezone}",
            "daily_break": (
                None if self.daily_break_start_hour is None
                else f"{self.daily_break_start_hour:02d}:00-"
                     f"{self.daily_break_end_hour:02d}:00 {self.venue_timezone}"),
            "description": self.description,
        }

    def windows(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        """Trading windows intersecting ``[start, end)``, as UTC half-open spans."""
        start = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)
        tz = self.tz
        out: list[tuple[datetime, datetime]] = []
        probe = (start.astimezone(tz) - timedelta(days=9)).date()
        last = (end.astimezone(tz) + timedelta(days=9)).date()
        span_days = (self.close_weekday - self.open_weekday) % 7 or 7
        while probe <= last:
            if probe.weekday() == self.open_weekday:
                open_local = datetime(probe.year, probe.month, probe.day,
                                      self.open_hour, tzinfo=tz)
                close_day = probe + timedelta(days=span_days)
                close_local = datetime(close_day.year, close_day.month, close_day.day,
                                       self.close_hour, tzinfo=tz)
                w_start = max(open_local.astimezone(timezone.utc), start)
                w_end = min(close_local.astimezone(timezone.utc), end)
                if w_start < w_end:
                    out.extend(self._split_daily_breaks(w_start, w_end, probe,
                                                        span_days, tz))
            probe += timedelta(days=1)
        out.sort()
        return out

    def _split_daily_breaks(self, w_start: datetime, w_end: datetime,
                            open_date, span_days: int, tz) -> list[tuple[datetime, datetime]]:
        """Remove the declared daily maintenance halt from a weekly window."""
        if self.daily_break_start_hour is None:
            return [(w_start, w_end)]
        cuts: list[tuple[datetime, datetime]] = []
        for offset in range(span_days + 1):
            day = open_date + timedelta(days=offset)
            b_start = datetime(day.year, day.month, day.day,
                               self.daily_break_start_hour, tzinfo=tz).astimezone(timezone.utc)
            b_end = datetime(day.year, day.month, day.day,
                             self.daily_break_end_hour, tzinfo=tz).astimezone(timezone.utc)
            if b_start < w_end and w_start < b_end:
                cuts.append((max(b_start, w_start), min(b_end, w_end)))
        cuts.sort()
        pieces: list[tuple[datetime, datetime]] = []
        cursor = w_start
        for c_start, c_end in cuts:
            if cursor < c_start:
                pieces.append((cursor, c_start))
            cursor = max(cursor, c_end)
        if cursor < w_end:
            pieces.append((cursor, w_end))
        return pieces


_DAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


SPOT_FX_NEW_YORK = SessionContract(
    contract_id="SPOT_FX_NY_1700",
    venue_timezone="America/New_York",
    open_weekday=SUNDAY, open_hour=17,
    close_weekday=FRIDAY, close_hour=17,
    description="Interbank spot FX week: Sunday 17:00 to Friday 17:00 New York "
                "(21:00 UTC under EDT, 22:00 UTC under EST).",
)

CME_METALS_CHICAGO = SessionContract(
    contract_id="CME_METALS_CHICAGO_1700",
    venue_timezone="America/Chicago",
    open_weekday=SUNDAY, open_hour=17,
    close_weekday=FRIDAY, close_hour=16,
    daily_break_start_hour=16, daily_break_end_hour=17,
    description="CME Globex metals: Sunday 17:00 open, Friday 16:00 close, and a "
                "daily 16:00-17:00 Chicago maintenance halt. The halt and the "
                "Friday close were CONFIRMED against the data (the 16:00 Chicago "
                "hour holds ~0.2% of a normal hour's bars) before being declared.",
)

CANDIDATE_SESSION_CONTRACTS: tuple[SessionContract, ...] = (
    SPOT_FX_NEW_YORK,
    CME_METALS_CHICAGO,
)

#: Declared contract per symbol. Confirmed against the data, never assumed.
SYMBOL_SESSION_CONTRACT: dict[str, SessionContract] = {
    "EURUSD": SPOT_FX_NEW_YORK,
    "GBPUSD": SPOT_FX_NEW_YORK,
    "USDJPY": SPOT_FX_NEW_YORK,
    "XAUUSD": CME_METALS_CHICAGO,
}


def contract_for(symbol: str) -> SessionContract:
    try:
        return SYMBOL_SESSION_CONTRACT[symbol]
    except KeyError:
        raise KeyError(
            f"no declared session contract for {symbol!r}; refusing to assume a "
            "weekly boundary, which would corrupt every coverage statistic"
        ) from None
