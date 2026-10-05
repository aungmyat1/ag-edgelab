"""EdgeLab FX Data Authority R2 — multi-year HistData ASCII M1.

PURPOSE
-------
``config/governance/data_authority_gap.json`` records FX_STATUS =
SINGLE_YEAR_AUTHORITY_EXISTS and specifies a ``multi_year_data_authority_contract``
that any corpus beyond the 2017 lane must satisfy.  This module IS that corpus,
built to the seven requirements of that contract:

1. source_provenance   -- HistData.com "Generic ASCII" M1, one archive per
                          symbol-year, mirrored at github.com/riknv/fx-m1-data
                          (README: "extracted from histdata.com"), retrieved
                          through the GitHub contents API by
                          ``scripts/acquire_histdata_fx_multiyear.py``.
2. raw_hashes          -- sha256 of every zip AND of every inner csv, pinned in
                          ``data/external/histdata_fx_multiyear/manifest.json``
                          before any derivation.  Raw bytes stay out of git.
3. timezone_norm       -- source America/New_York, normalized to UTC by the
                          FROZEN PR #10 loader, bar-OPEN convention.  This
                          module imports that loader; it does not reimplement it.
4. gap_handling        -- the frozen >= 13/15 M1-minutes M15 bucket rule and the
                          0.75 MTF coverage fraction are inherited unchanged;
                          missing buckets stay missing and are inventoried per
                          symbol-year by the runner.
5. duplicate_handling  -- ``quality_gate_m1`` raises on any duplicate timestamp.
                          A symbol-year that fails it is EXCLUDED and recorded,
                          never silently de-duplicated.
6. resampling          -- causal only; M15 -> H1/H4/D1 via the frozen
                          ``derive_fx_timeframe``; per-frame hashes recorded.
7. partitioning        -- defined below and committed BEFORE any candidate work.

WHY THE MIRROR IS ADMISSIBLE
----------------------------
For the overlapping year 2017 the inner csv of every mirror archive is
byte-identical (sha256) to the inner csv of the PR #10 pinned zip, for all four
symbols.  The acquisition script proves this before admitting any other year and
stops with BLOCKED_DATA_AUTHORITY otherwise.  The mirror therefore carries the
same product, and the same loader semantics apply unchanged.

PARTITION POLICY
----------------
The 2017 authority splits the calendar year DEVELOPMENT [Jan 1, Sep 1) / OOS
[Sep 1, Dec 1) / SEALED_HOLDOUT [Dec 1, Jan 1).  R2 applies that SAME annual
shape to every admitted year.  Two consequences, both deliberate:

  * every added year contributes a DEV window with the identical calendar
    composition as 2017's, so year-over-year comparisons are not confounded by
    seasonality or window length;
  * Sep-Dec of every year stays UNTOUCHED, preserving a genuinely fresh
    multi-year OOS corpus plus a sealed holdout for a future, separately
    authorized evaluation.  Expanding DEV to whole calendar years would burn
    that forever and is NOT done here.

Only DEVELOPMENT is loadable.  ``assert_partition_accessible`` fails closed on
OOS as well as SEALED_HOLDOUT in this authority: no mission has authorization to
open either for any year.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fx_histdata_2017 import (
    M15_MINUTES_REQUIRED,
    MTF_COVERAGE_FRACTION,
    BlockedDataAuthority,
    PartitionError,
    aggregate_m15,
    derive_fx_timeframe,
    load_histdata_m1,
    quality_gate_m1,
)

UTC = timezone.utc

AUTHORITY_ID = "HISTDATA_ASCII_M1_MULTIYEAR_R2"
AUTHORITY_PARENT = "HISTDATA_ASCII_M1_2017_PR10_PINNED"
PARTITION_POLICY_ID = "FX_ANNUAL_PARTITION_POLICY_R2"
MIRROR = "github.com/riknv/fx-m1-data"
SOURCE_PRODUCT = "HistData.com Generic ASCII M1"
SOURCE_TZ = "America/New_York"
NORMALIZED_TZ = "UTC"

SYMBOLS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")

#: Whole-calendar-year archives published by the mirror, per symbol.
COVERAGE: dict[str, tuple[int, int]] = {
    "EURUSD": (2000, 2017),
    "GBPUSD": (2000, 2017),
    "USDJPY": (2000, 2017),
    "XAUUSD": (2009, 2017),
}

#: Years for which every one of the four symbols is published — the balanced
#: panel used for the symbol-fair secondary read.
BALANCED_PANEL = tuple(range(max(v[0] for v in COVERAGE.values()),
                             min(v[1] for v in COVERAGE.values()) + 1))

DEFAULT_DATA_DIR = Path("data/external/histdata_fx_multiyear")

#: The annual partition shape, identical to the PR #10 2017 split.
ANNUAL_PARTITIONS: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {
    #        (start month, day)   (end month, day)   end is exclusive
    "DEVELOPMENT": ((1, 1), (9, 1)),
    "OOS": ((9, 1), (12, 1)),
    "SEALED_HOLDOUT": ((12, 1), (13, 1)),  # 13 -> Jan 1 of the next year
}

LOADABLE_ROLES: frozenset[str] = frozenset({"DEVELOPMENT"})


class NonDevelopmentAccessError(PermissionError):
    """Raised on any attempt to load a non-DEVELOPMENT partition under R2."""


def partition_bounds(role: str, year: int) -> tuple[datetime, datetime]:
    """UTC [start, end) of ``role`` within ``year`` under the R2 annual policy."""
    if role not in ANNUAL_PARTITIONS:
        raise PartitionError(f"unknown partition role: {role}")
    (sm, sd), (em, ed) = ANNUAL_PARTITIONS[role]
    start = datetime(year, sm, sd, tzinfo=UTC)
    end = (datetime(year + 1, em - 12, ed, tzinfo=UTC) if em > 12
           else datetime(year, em, ed, tzinfo=UTC))
    return start, end


def assert_partition_accessible(role: str) -> None:
    """Fail closed: under R2 only DEVELOPMENT may ever be read.

    The OOS windows of every admitted year are FRESH (never consumed by any
    candidate) and the holdouts are sealed.  Neither is authorized here, so both
    raise rather than returning data.
    """
    if role not in ANNUAL_PARTITIONS:
        raise PartitionError(f"unknown partition role: {role}")
    if role not in LOADABLE_ROLES:
        raise NonDevelopmentAccessError(
            f"{role} is not loadable under {AUTHORITY_ID}: this authority grants "
            "DEVELOPMENT access only. Opening it requires a separate, explicitly "
            "authorized governance mission that amends config/governance/oos_access_log.json "
            "first. STATUS=BLOCKED_DATA_AUTHORITY")


# ---------------------------------------------------------------------------
# manifest / identity
# ---------------------------------------------------------------------------

def manifest_path(data_dir: Path | None = None) -> Path:
    return (data_dir or DEFAULT_DATA_DIR) / "manifest.json"


def load_manifest(data_dir: Path | None = None) -> dict:
    path = manifest_path(data_dir)
    if not path.exists():
        raise BlockedDataAuthority(
            f"multi-year manifest missing at {path}; run "
            "scripts/acquire_histdata_fx_multiyear.py first")
    manifest = json.loads(path.read_text())
    proof = manifest.get("cross_source_identity_proof", {})
    if proof.get("result") != "IDENTICAL_4_OF_4":
        raise BlockedDataAuthority(
            "multi-year manifest does not carry the 2017 cross-source identity proof; "
            "STATUS=BLOCKED_DATA_AUTHORITY")
    return manifest


def archive_path(symbol: str, year: int, data_dir: Path | None = None) -> Path:
    return (data_dir or DEFAULT_DATA_DIR) / f"DAT_ASCII_{symbol}_M1_{year}.zip"


def admitted_symbol_years() -> tuple[tuple[str, int], ...]:
    """Every (symbol, year) the mirror publishes as a whole-year archive."""
    return tuple((s, y) for s in SYMBOLS
                 for y in range(COVERAGE[s][0], COVERAGE[s][1] + 1))


def verify_source_identity(symbol: str, year: int, manifest: dict,
                           data_dir: Path | None = None) -> dict:
    """Hard identity check of one symbol-year archive against the manifest."""
    import hashlib

    key = f"{symbol}_{year}"
    pinned = manifest["files"].get(key)
    if pinned is None:
        raise BlockedDataAuthority(f"no pinned identity for {key}")
    path = archive_path(symbol, year, data_dir)
    if not path.exists():
        raise BlockedDataAuthority(f"archive missing: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != pinned["zip_sha256"]:
        raise BlockedDataAuthority(
            f"{key}: raw identity mismatch — expected {pinned['zip_sha256']}, got {digest}; "
            "STATUS=BLOCKED_DATA_AUTHORITY")
    return pinned


# ---------------------------------------------------------------------------
# frames
# ---------------------------------------------------------------------------

def build_dev_frames(symbol: str, year: int, aggregate_m5,
                     data_dir: Path | None = None,
                     ) -> tuple[dict[str, tuple[MarketBar, ...]], dict]:
    """Load one symbol-year and return DEVELOPMENT-sliced frames + quality.

    ``aggregate_m5`` is injected by the caller so the M5 rule stays owned by the
    frozen strategy module (``M5_MINUTES_REQUIRED``) rather than being restated
    here.  Every other derivation is the frozen PR #10 code path, imported above.
    """
    assert_partition_accessible("DEVELOPMENT")
    path = archive_path(symbol, year, data_dir)
    m1 = load_histdata_m1(path)
    quality = quality_gate_m1(m1, f"{symbol}:{year}")

    year_start = datetime(year, 1, 1, tzinfo=UTC)
    year_end = datetime(year + 1, 1, 1, tzinfo=UTC)
    m1_window = tuple(b for b in m1 if year_start <= b.timestamp < year_end)
    del m1

    m15_full = aggregate_m15(m1_window)
    m5_full = aggregate_m5(m1_window)
    out_of_year = quality["m1_rows"] - len(m1_window)
    del m1_window

    frames_full: dict[str, tuple[MarketBar, ...]] = {"M15": m15_full, "M5": m5_full}
    for tf in ("H1", "H4", "D1"):
        frames_full[tf], _ = derive_fx_timeframe(m15_full, tf, symbol)

    dev_start, dev_end = partition_bounds("DEVELOPMENT", year)
    frames = {tf: tuple(b for b in rows if dev_start <= b.timestamp < dev_end)
              for tf, rows in frames_full.items()}
    del frames_full

    quality.update({
        "symbol": symbol,
        "year": year,
        "dataset_role": "DEVELOPMENT",
        "authority_id": AUTHORITY_ID,
        "partition_utc": [dev_start.isoformat(), dev_end.isoformat()],
        "m1_rows_outside_calendar_year": out_of_year,
        "bars": {tf: len(rows) for tf, rows in sorted(frames.items())},
        "first_m15": frames["M15"][0].timestamp.isoformat() if frames["M15"] else None,
        "last_m15": frames["M15"][-1].timestamp.isoformat() if frames["M15"] else None,
        "m15_rule": f">= {M15_MINUTES_REQUIRED}/15 M1 minutes per bucket (PR#10 frozen); no forward fill",
        "mtf_coverage_fraction": MTF_COVERAGE_FRACTION,
        "timezone_rule": f"source {SOURCE_TZ} (DST) normalized to {NORMALIZED_TZ} before any logic",
        "warmup_source": "inside the same DEV window (never the adjacent OOS/holdout months)",
    })
    return frames, quality


def authority_contract() -> dict:
    """The committed description of this data authority (hashable)."""
    return {
        "authority_id": AUTHORITY_ID,
        "extends": AUTHORITY_PARENT,
        "product": SOURCE_PRODUCT,
        "mirror": MIRROR,
        "transport": "GitHub contents API (raw media type)",
        "symbols": list(SYMBOLS),
        "coverage_years": {s: list(v) for s, v in sorted(COVERAGE.items())},
        "balanced_panel_years": list(BALANCED_PANEL),
        "partition_policy_id": PARTITION_POLICY_ID,
        "annual_partitions_utc": {
            "DEVELOPMENT": "[YYYY-01-01, YYYY-09-01)",
            "OOS": "[YYYY-09-01, YYYY-12-01) — NOT LOADABLE under this authority",
            "SEALED_HOLDOUT": "[YYYY-12-01, YYYY+1-01-01) — NOT LOADABLE, sealed",
        },
        "loadable_roles": sorted(LOADABLE_ROLES),
        "source_timezone": SOURCE_TZ,
        "normalized_timezone": NORMALIZED_TZ,
        "bar_convention": "bar OPEN timestamp",
        "m15_rule": f">= {M15_MINUTES_REQUIRED}/15 M1 minutes per bucket; missing buckets never filled",
        "mtf_coverage_fraction": MTF_COVERAGE_FRACTION,
        "duplicate_policy": "zero tolerance — quality_gate_m1 raises; the symbol-year is excluded, never de-duplicated",
        "ohlc_policy": "zero tolerance — any OHLC-invalid M1 bar excludes the symbol-year",
        "cross_source_identity_proof": (
            "inner DAT_ASCII_{SYM}_M1_2017.csv sha256 == inner csv of the PR #10 pinned zip, 4/4 symbols"),
        "derivation_code": "ag_edgelab.data.fx_histdata_2017 (unmodified)",
    }
