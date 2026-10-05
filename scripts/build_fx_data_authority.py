#!/usr/bin/env python3
"""Build the EdgeLab multi-year FX data authority (DATA_AUTHORITY_R1).

Strategy-free. This script acquires nothing, evaluates nothing and tunes
nothing: it turns pinned raw archives into hashed, classified, canonical
datasets plus the manifests that make them auditable.

Stages
------
``normalize``  one (symbol, year) at a time:
               raw identity -> canonical M1 -> timezone proof ->
               derived timeframes -> quality classification -> CAS write.
               Restartable; already-completed slices are skipped.
``assemble``   fold the per-slice records into the mission artifacts.

Raw archives and normalized datasets never enter git. Git receives only
manifests, hashes, schemas and small reports.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.data.authority.cas import CasStore                      # noqa: E402
from ag_edgelab.data.authority.quality import assess_year               # noqa: E402
from ag_edgelab.data.authority.rawobj import (                          # noqa: E402
    RawObject, hash_archive_members, member_index_document, utc_now,
)
from ag_edgelab.data.authority.resample import (                        # noqa: E402
    DERIVED_TIMEFRAMES, derive_all,
)
from ag_edgelab.data.authority.schema import (                          # noqa: E402
    CANONICAL_SCHEMA_VERSION, canonical_dataset_hash, dumps_canonical,
)
from ag_edgelab.data.authority.sources.dukascopy_tick import (          # noqa: E402
    SOURCE_ID, TICK_FILE_RE, normalize_archive_to_m1,
)
from ag_edgelab.data.authority.session import resolve_session_contract  # noqa: E402
from ag_edgelab.data.authority.timezone_proof import (                  # noqa: E402
    dst_transition_consistency, prove_fixed_offset_frame,
    weekly_first_observations,
)

PINS = ROOT / "config" / "data_authority" / "dukascopy_fx31337_pins.json"
EXTERNAL = ROOT / "data" / "external"
ARCHIVES = EXTERNAL / "dukascopy_fx"
CAS_ROOT = EXTERNAL / "cas"
STAGE = ROOT / "artifacts" / "data_authority_r1" / "_stage"


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def archive_path(symbol: str, year: int, commit: str) -> Path:
    return ARCHIVES / f"{symbol}_{year}_{commit[:12]}.tar.gz"


def build_slice(pin: dict) -> dict:
    """Normalize one (symbol, year). Pure function of the pinned archive."""
    symbol, year, commit = pin["symbol"], int(pin["year"]), pin["commit"]
    archive = archive_path(symbol, year, commit)
    if not archive.is_file():
        raise FileNotFoundError(
            f"BLOCKED_DATA_AUTHORITY: raw archive missing for {symbol} {year} "
            f"at {archive}; run scripts/acquire_dukascopy_fx_multiyear.sh")

    cas = CasStore(CAS_ROOT)

    def is_tick(relative: str) -> bool:
        match = TICK_FILE_RE.search(relative)
        return bool(match and match["symbol"] == symbol and int(match["year"]) == year)

    raw_tree, members = hash_archive_members(archive, include=is_tick)
    index_entry = cas.store_entry(
        f"RAW_MEMBER_INDEX_{symbol}_{year}",
        member_index_document(members),
        schema_version="EDGELAB_RAW_MEMBER_INDEX_V1",
        description=f"per-file sha256 index of {symbol} {year} tick archive",
    )

    result = normalize_archive_to_m1(archive, symbol, year)
    m1 = result.bars
    if not m1:
        raise RuntimeError(f"BLOCKED_DATA_AUTHORITY: {symbol} {year} produced no bars")

    coverage_start, coverage_end = m1[0].timestamp_utc, m1[-1].timestamp_utc
    raw = RawObject(
        raw_id=f"{SOURCE_ID}:{symbol}:{year}",
        source_id=SOURCE_ID,
        symbol=symbol,
        sha256=raw_tree,
        byte_size=sum(m.byte_size for m in members),
        member_count=len(members),
        source=f"{pin['repo']}@{commit} ({pin['ref']}) — Dukascopy public tick "
               f"archive mirrored by fx31337/fx-data-download-action",
        upstream_ref=f"git:{pin['repo']}:{commit}",
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        retrieval_timestamp=datetime.fromtimestamp(archive.stat().st_mtime, timezone.utc)
            .replace(microsecond=0),
        timezone="UTC (proven — see timezone_proof)",
        format="CSV tick: 'YYYY.MM.DD HH:MM:SS.mmm,bid,ask,bid_volume,ask_volume', CRLF",
        local_path=str(archive.relative_to(ROOT)),
        member_index_sha256=index_entry.sha256,
    )

    proof = prove_fixed_offset_frame(result.naive_source_timestamps)
    # Resolve the venue session from THIS slice's own observations rather
    # than a static per-symbol table: venues change schedules, and this
    # corpus contains exactly that case (XAUUSD moves from the New York
    # spot-gold week to the CME Globex metals week between 2011 and 2012).
    resolution = resolve_session_contract(
        weekly_first_observations(result.naive_source_timestamps), symbol=symbol)
    contract = resolution.contract
    dst = dst_transition_consistency(result.naive_source_timestamps, 0, contract)

    m1_doc = dumps_canonical(m1)
    m1_hash = canonical_dataset_hash(m1)
    m1_entry = cas.store_entry(
        f"FXM_{symbol}_{year}_M1", m1_doc,
        schema_version=CANONICAL_SCHEMA_VERSION,
        description=f"canonical M1 bars, {symbol} {year}, derived from ticks")
    assert m1_entry.sha256 == m1_hash

    frames, lineages, audits = derive_all(
        m1, symbol=symbol, raw_parent_sha256=raw_tree, m1_dataset_sha256=m1_hash)

    datasets = {"M1": {
        "dataset_sha256": m1_hash,
        "rows": len(m1),
        "byte_size": m1_entry.byte_size,
        "storage_location": m1_entry.storage_location,
    }}
    for timeframe in DERIVED_TIMEFRAMES:
        bars = frames[timeframe]
        entry = cas.store_entry(
            f"FXM_{symbol}_{year}_{timeframe}", dumps_canonical(bars),
            schema_version=CANONICAL_SCHEMA_VERSION,
            description=f"canonical {timeframe} bars, {symbol} {year}")
        datasets[timeframe] = {
            "dataset_sha256": entry.sha256,
            "rows": len(bars),
            "byte_size": entry.byte_size,
            "storage_location": entry.storage_location,
        }
        assert entry.sha256 == lineages[timeframe].output_dataset_sha256

    quality = {
        timeframe: assess_year(
            frames.get(timeframe, m1), symbol=symbol, year=year,
            timeframe=timeframe, contract=contract
        ).as_dict()
        for timeframe in ("M1",) + DERIVED_TIMEFRAMES
    }

    return {
        "symbol": symbol,
        "year": year,
        "raw": raw.as_dict(),
        "raw_member_index": index_entry.as_dict(),
        "normalization": result.as_dict(),
        "session_contract": resolution.as_dict(),
        "timezone_proof": proof.as_dict(),
        "dst_consistency": dst,
        "datasets": datasets,
        "timeframe_lineage": {tf: lineages[tf].as_dict() for tf in DERIVED_TIMEFRAMES},
        "coverage_audit": {tf: audits[tf].as_dict() for tf in DERIVED_TIMEFRAMES},
        "quality": quality,
        "built_at": _iso(utc_now()),
    }


def _worker(pin: dict) -> tuple[str, str]:
    target = STAGE / f"{pin['symbol']}_{pin['year']}.json"
    try:
        payload = build_slice(pin)
    except Exception:                                   # noqa: BLE001
        return (f"{pin['symbol']} {pin['year']}", "FAILED\n" + traceback.format_exc())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    normalization = payload["normalization"]
    return (f"{pin['symbol']} {pin['year']}",
            f"OK m1={normalization['m1_bars']:,} ticks={normalization['ticks_ingested']:,} "
            f"tz={payload['timezone_proof']['status']}")


def stage_requality(pins: list[dict]) -> int:
    """Recompute quality + session resolution from the stored datasets.

    The canonical datasets are immutable and content addressed, so the
    classification layer can be re-derived without re-reading 5.8 GB of raw
    ticks. Dataset hashes are untouched; only the report changes.
    """
    from ag_edgelab.data.authority.schema import loads_canonical
    from ag_edgelab.data.authority.session import resolve_session_contract
    from ag_edgelab.data.authority.timezone_proof import weekly_first_observations

    cas = CasStore(CAS_ROOT)
    updated = 0
    for pin in pins:
        symbol, year = pin["symbol"], pin["year"]
        target = STAGE / f"{symbol}_{year}.json"
        if not target.is_file():
            continue
        record = json.loads(target.read_text(encoding="utf-8"))
        frames = {
            tf: loads_canonical(cas.get_text(record["datasets"][tf]["dataset_sha256"]))
            for tf in ("M1",) + DERIVED_TIMEFRAMES
        }
        provider_clock = [b.timestamp_utc.replace(tzinfo=None) for b in frames["M1"]]
        resolution = resolve_session_contract(
            weekly_first_observations(provider_clock), symbol=symbol)
        record["session_contract"] = resolution.as_dict()
        record["quality"] = {
            tf: assess_year(frames[tf], symbol=symbol, year=year, timeframe=tf,
                            contract=resolution.contract).as_dict()
            for tf in ("M1",) + DERIVED_TIMEFRAMES
        }
        target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
        updated += 1
        m1 = record["quality"]["M1"]
        print(f"[ re ] {symbol} {year}  {resolution.contract.contract_id:24s} "
              f"year_cov={m1['coverage_pct']:6.2f}% "
              f"span_cov={m1['observed_span_coverage_pct']:6.2f}%")
    print(f"requality: {updated} slice(s) updated")
    return 0


def stage_normalize(pins: list[dict], workers: int, force: bool) -> int:
    STAGE.mkdir(parents=True, exist_ok=True)
    todo = [p for p in pins
            if force or not (STAGE / f"{p['symbol']}_{p['year']}.json").is_file()]
    print(f"normalize: {len(todo)} slice(s) to build, {len(pins) - len(todo)} cached",
          flush=True)
    failures = 0
    if not todo:
        return 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_worker, pin): pin for pin in todo}
        for done in as_completed(futures):
            label, status = done.result()
            if status.startswith("FAILED"):
                failures += 1
                print(f"[FAIL] {label}\n{status}", flush=True)
            else:
                print(f"[ ok ] {label}  {status}", flush=True)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage",
                        choices=("normalize", "requality", "assemble", "all"),
                        default="all")
    parser.add_argument("--workers", type=int,
                        default=max(1, min(2, (os.cpu_count() or 2))))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--years", default="")
    args = parser.parse_args()

    pins = json.loads(PINS.read_text(encoding="utf-8"))["pins"]
    if args.symbols:
        wanted = set(args.symbols.split(","))
        pins = [p for p in pins if p["symbol"] in wanted]
    if args.years:
        years = {int(y) for y in args.years.split(",")}
        pins = [p for p in pins if int(p["year"]) in years]

    if args.stage in ("normalize", "all"):
        failures = stage_normalize(pins, args.workers, args.force)
        if failures:
            print(f"STATUS=BLOCKED_DATA_AUTHORITY ({failures} slice failures)",
                  file=sys.stderr)
            return 2
    if args.stage == "requality":
        return stage_requality(pins)

    if args.stage in ("assemble", "all"):
        from assemble_fx_data_authority import assemble   # noqa: PLC0415
        return assemble()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
