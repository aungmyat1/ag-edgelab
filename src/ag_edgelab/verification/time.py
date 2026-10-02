from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import AfterValidator


def utc_datetime(value: datetime) -> datetime:
    """Require an aware timestamp and store its canonical UTC equivalent."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


UTCDateTime = Annotated[datetime, AfterValidator(utc_datetime)]
