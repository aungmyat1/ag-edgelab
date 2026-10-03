"""Canonical MarketBar CSV serialization.

Byte-stable, dependency-free representation used for dataset artifacts:
header `timestamp,open,high,low,close,volume`; timestamps are UTC ISO-8601
with `+00:00` offset; floats use `repr` shortest round-trip formatting.
The SHA-256 of these exact bytes is the artifact hash recorded in manifests.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from ag_edgelab.contracts.market import MarketBar

HEADER = "timestamp,open,high,low,close,volume"


def _fmt_float(value: float) -> str:
    return repr(float(value))


def dumps_bars(bars: tuple[MarketBar, ...]) -> str:
    lines = [HEADER]
    for bar in bars:
        ts = bar.timestamp.astimezone(timezone.utc).isoformat()
        volume = "" if bar.volume is None else _fmt_float(bar.volume)
        lines.append(
            f"{ts},{_fmt_float(bar.open)},{_fmt_float(bar.high)},{_fmt_float(bar.low)},{_fmt_float(bar.close)},{volume}"
        )
    return "\n".join(lines) + "\n"


def loads_bars(text: str) -> tuple[MarketBar, ...]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != HEADER:
        raise ValueError("not a canonical MarketBar CSV document")
    out: list[MarketBar] = []
    for line in lines[1:]:
        raw = line.strip()
        if not raw:
            continue
        parts = raw.split(",")
        if len(parts) != 6:
            raise ValueError(f"malformed bar row: {raw!r}")
        ts, open_, high, low, close, volume = parts
        parsed = datetime.fromisoformat(ts)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        out.append(
            MarketBar(
                timestamp=parsed.astimezone(timezone.utc),
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume) if volume not in ("", "None") else None,
            )
        )
    return tuple(out)


def write_bars_csv(path: str | Path, bars: tuple[MarketBar, ...]) -> tuple[str, str]:
    """Write canonical CSV; return (path, sha256_of_bytes)."""
    payload = dumps_bars(bars)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8", newline="")
    return str(target), hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_bars_csv(path: str | Path) -> tuple[tuple[MarketBar, ...], str]:
    raw = Path(path).read_bytes()
    return loads_bars(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
