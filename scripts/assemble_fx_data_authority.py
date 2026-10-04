#!/usr/bin/env python3
"""Fold per-slice build records into the DATA_AUTHORITY_R1 artifacts.

Strategy-free. Reads the staged slice records written by
scripts/build_fx_data_authority.py plus the frozen HistData 2017 authority
(read-only), and emits the manifests, reports and registries that git
keeps. Large datasets stay in content-addressed external storage.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.data.authority import cross_source                       # noqa: E402
from ag_edgelab.data.authority.cas import CasStore                       # noqa: E402
from ag_edgelab.data.authority.friction_contract import (                # noqa: E402
    FrictionAuthorityStatus, empty_quote, net_economics_estimable,
)
from ag_edgelab.data.authority.inventory import (                        # noqa: E402
    authority_matrix, inventory_document,
)
from ag_edgelab.data.authority.partition import (                        # noqa: E402
    AccessStatus, DatasetPartitionRegistry, PartitionRecord, PartitionRole,
)
from ag_edgelab.data.authority.readiness import (                        # noqa: E402
    assess, build_folds, characterise_year, session_distribution,
)
from ag_edgelab.data.authority.resample import DERIVED_TIMEFRAMES        # noqa: E402
from ag_edgelab.data.authority.schema import loads_canonical             # noqa: E402
from ag_edgelab.data.authority.timezone_proof import (                   # noqa: E402
    TimezoneProof, prove_corpus_frame, prove_fixed_offset_frame,
)
from ag_edgelab.data.fingerprint import sha256_json                      # noqa: E402

OUT = ROOT / "artifacts" / "data_authority_r1"
STAGE = OUT / "_stage"
CAS_ROOT = ROOT / "data" / "external" / "cas"
GOV = ROOT / "config" / "governance"

DATASET_ID = "DUKASCOPY_FX_MULTIYEAR_2011_2018_V1"
LEGACY_DATASET_ID = "HISTDATA_ASCII_M1_2017_PR10_PINNED"
BASELINE_FAMILY = "R1_BASELINE_UNASSIGNED"
LEGACY_FAMILY = "LEGACY_2017_FAMILY"
SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")
TIMEFRAMES = ("M1",) + DERIVED_TIMEFRAMES


def _dt(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def provider_clock_timestamps(canonical_text: str) -> list[datetime]:
    """Bar open times as the PROVIDER wrote them (tz stripped, not shifted).

    Normalization never moves the provider clock, so an M1 bar's open time
    is a faithful sample of the source clock. Parsed by string slicing
    because this runs over ~12 million rows.
    """
    out: list[datetime] = []
    for line in canonical_text.split("\n"):
        if not line or line[0] == "#" or line[0] == "t":
            continue
        stamp = line[:19]
        out.append(datetime(int(stamp[0:4]), int(stamp[5:7]), int(stamp[8:10]),
                            int(stamp[11:13]), int(stamp[14:16]),
                            int(stamp[17:19])))
    return out


def _write(name: str, payload: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def load_slices() -> list[dict]:
    rows = [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(STAGE.glob("*.json"))]
    if not rows:
        raise SystemExit("no staged slices; run --stage normalize first")
    return rows


# ---------------------------------------------------------------------------
# partitions
# ---------------------------------------------------------------------------

def build_partition_registry(coverage_start: datetime,
                             coverage_end: datetime) -> DatasetPartitionRegistry:
    """Deterministic partitions. No evaluation is run; nothing is opened."""
    reg = DatasetPartitionRegistry()
    consumed_at = _dt("2026-10-04T15:27:38Z")

    # --- the frozen 2017 authority, mirrored read-only from governance -----
    reg.add(PartitionRecord(
        dataset_id=LEGACY_DATASET_ID, dataset_hash="see oos_access_log dataset_registry",
        role=PartitionRole.DEVELOPMENT, candidate_family=LEGACY_FAMILY,
        start=_dt("2017-01-01T00:00:00Z"), end=_dt("2017-09-01T00:00:00Z"),
        access_status=AccessStatus.AVAILABLE,
        note="Mirrored from config/governance/oos_access_log.json; unchanged."))
    reg.add(PartitionRecord(
        dataset_id=LEGACY_DATASET_ID, dataset_hash="see oos_access_log dataset_registry",
        role=PartitionRole.OOS, candidate_family=LEGACY_FAMILY,
        start=_dt("2017-09-01T00:00:00Z"), end=_dt("2017-12-01T00:00:00Z"),
        access_status=AccessStatus.CONSUMED,
        consumed_at=consumed_at,
        consumed_by="SESSION_TRADE_V2_v2.0.0_e1ffe9f1e5cc (OOS-001); "
                    "TARGET_POLICY_C3_V1 (OOS-002)",
        note="PRESERVED, NOT RE-DERIVED. Remains CONSUMED for related candidate "
             "families. TARGET_POLICY_C3_V1 stays EDGE_STATUS=NO_EDGE with "
             "RETUNING=FORBIDDEN."))
    reg.add(PartitionRecord(
        dataset_id=LEGACY_DATASET_ID, dataset_hash="see oos_access_log dataset_registry",
        role=PartitionRole.SEALED_HOLDOUT, candidate_family=LEGACY_FAMILY,
        start=_dt("2017-12-01T00:00:00Z"), end=_dt("2018-01-01T00:00:00Z"),
        access_status=AccessStatus.SEALED, sealed=True,
        note="NEVER OPENED. This mission did not read it and did not weaken it."))

    # --- the new multi-year authority --------------------------------------
    reg.add(PartitionRecord(
        dataset_id=DATASET_ID, dataset_hash="see normalized_manifest.corpus_sha256",
        role=PartitionRole.DEVELOPMENT, candidate_family=BASELINE_FAMILY,
        start=_dt("2011-01-01T00:00:00Z"), end=_dt("2016-01-01T00:00:00Z"),
        access_status=AccessStatus.AVAILABLE,
        note="Five years for model development and selection."))
    reg.add(PartitionRecord(
        dataset_id=DATASET_ID, dataset_hash="see normalized_manifest.corpus_sha256",
        role=PartitionRole.WALK_FORWARD, candidate_family=BASELINE_FAMILY,
        start=_dt("2016-01-01T00:00:00Z"), end=_dt("2017-09-01T00:00:00Z"),
        access_status=AccessStatus.AVAILABLE,
        note="Rolling re-fit/evaluate folds. Fold ordering is enforced by the "
             "walk-forward runner, not by this registry."))
    reg.add(PartitionRecord(
        dataset_id=DATASET_ID, dataset_hash="see normalized_manifest.corpus_sha256",
        role=PartitionRole.DEVELOPMENT, candidate_family=BASELINE_FAMILY,
        start=_dt("2017-09-01T00:00:00Z"), end=_dt("2017-12-01T00:00:00Z"),
        access_status=AccessStatus.DEVELOPMENT_KNOWN,
        note="CALENDAR MIRROR of the consumed HistData OOS window. The bytes are "
             "from a different provider, but the market period is the same and its "
             "outcome has already been observed twice. Treating it as fresh OOS "
             "would launder spent data through a new vendor, so it is "
             "DEVELOPMENT_KNOWN and the registry refuses to serve it as OOS."))
    reg.add(PartitionRecord(
        dataset_id=DATASET_ID, dataset_hash="see normalized_manifest.corpus_sha256",
        role=PartitionRole.SEALED_HOLDOUT, candidate_family=BASELINE_FAMILY,
        start=_dt("2017-12-01T00:00:00Z"), end=_dt("2018-01-01T00:00:00Z"),
        access_status=AccessStatus.SEALED, sealed=True,
        note="CALENDAR MIRROR of the sealed HistData holdout. Sealed here too, so "
             "the sealed month cannot be read through a second provider."))
    reg.add(PartitionRecord(
        dataset_id=DATASET_ID, dataset_hash="see normalized_manifest.corpus_sha256",
        role=PartitionRole.OOS, candidate_family=BASELINE_FAMILY,
        start=_dt("2018-01-01T00:00:00Z"), end=_dt("2018-07-01T00:00:00Z"),
        access_status=AccessStatus.AVAILABLE,
        note="FRESH, NEVER OPENED. Six months of genuinely unspent out-of-sample "
             "data — the first this repository has had since 2017 was consumed. "
             "Opening it requires a preregistration recorded in the OOS access log."))
    reg.add(PartitionRecord(
        dataset_id=DATASET_ID, dataset_hash="see normalized_manifest.corpus_sha256",
        role=PartitionRole.SEALED_HOLDOUT, candidate_family=BASELINE_FAMILY,
        start=_dt("2018-07-01T00:00:00Z"), end=_dt("2019-01-01T00:00:00Z"),
        access_status=AccessStatus.SEALED, sealed=True,
        note="Final sealed holdout. Not read in this mission; fails closed."))
    return reg


# ---------------------------------------------------------------------------
# assemble
# ---------------------------------------------------------------------------

def assemble() -> int:                                       # noqa: PLR0915
    slices = load_slices()
    cas = CasStore(CAS_ROOT)
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for row in slices:
        by_symbol[row["symbol"]].append(row)
    for rows in by_symbol.values():
        rows.sort(key=lambda r: r["year"])
    years = sorted({r["year"] for r in slices})

    # -- 1/2 inventory + matrix --------------------------------------------
    _write("data_authority_inventory.json", inventory_document())
    _write("source_authority_matrix.json", authority_matrix())

    # -- 3 raw manifest -----------------------------------------------------
    raw_objects = [r["raw"] for r in slices]
    raw_manifest = {
        "manifest_version": "DATA_AUTHORITY_R1_RAW_MANIFEST_V1",
        "immutability_rule": (
            "Raw archives are never modified in place and never committed to git. "
            "Identity is a content Merkle root over sorted (relative_path, "
            "sha256(member bytes)) leaves, which is stable across re-packaging."),
        "source_id": "DUKASCOPY_TICK_FX31337_MIRROR_V1",
        "object_count": len(raw_objects),
        "total_member_count": sum(o["member_count"] for o in raw_objects),
        "total_raw_bytes": sum(o["byte_size"] for o in raw_objects),
        "objects": sorted(raw_objects, key=lambda o: o["raw_id"]),
    }
    raw_manifest["manifest_sha256"] = sha256_json(raw_manifest["objects"])
    _write("raw_manifest.json", raw_manifest)

    # -- 4 normalized manifest ---------------------------------------------
    datasets = []
    for row in slices:
        for timeframe in TIMEFRAMES:
            entry = row["datasets"][timeframe]
            datasets.append({
                "dataset_id": f"{DATASET_ID}:{row['symbol']}:{row['year']}:{timeframe}",
                "symbol": row["symbol"], "year": row["year"], "timeframe": timeframe,
                "rows": entry["rows"],
                "dataset_sha256": entry["dataset_sha256"],
                "byte_size": entry["byte_size"],
                "storage_location": entry["storage_location"],
                "raw_parent_sha256": row["raw"]["sha256"],
                "schema_version": "EDGELAB_CANONICAL_BAR_V1",
            })
    normalized = {
        "manifest_version": "DATA_AUTHORITY_R1_NORMALIZED_MANIFEST_V1",
        "dataset_id": DATASET_ID,
        "schema_version": "EDGELAB_CANONICAL_BAR_V1",
        "required_fields": ["timestamp_utc", "symbol", "open", "high", "low", "close"],
        "optional_fields": ["tick_volume", "real_volume", "spread", "bid", "ask"],
        "price_basis": "BID (OHLC built from the bid series); bid/ask carry the "
                       "closing quote and spread the mean ask-bid over the bucket",
        "normalization_contract": {
            "timezone": "UTC — proven corpus-wide, see final_report.TIMEZONE_AUTHORITY",
            "bar_timestamp": "bar OPEN time",
            "missing_bar_policy": "EXPLICIT_ABSENCE — a minute with no tick produces "
                                  "no row. No forward fill, no interpolation, no "
                                  "invented candle, spread or volume.",
            "duplicate_policy": "REJECT — duplicates raise SchemaViolation; the "
                                "pipeline never deduplicates silently",
            "ordering": "strictly chronological, enforced by validate_canonical_series",
            "price_grid": "provider 1e-5 integer grid reinterpreted at the symbol's "
                          "declared decimals; verified by plausibility band and by "
                          "independent cross-source comparison",
            "anomaly_policy": "CLASSIFY, NEVER REPAIR",
        },
        "storage": "content-addressed external store (data/external/cas); git holds "
                   "only these hashes",
        "dataset_count": len(datasets),
        "total_rows": sum(d["rows"] for d in datasets),
        "datasets": sorted(datasets, key=lambda d: d["dataset_id"]),
    }
    normalized["corpus_sha256"] = sha256_json(
        [[d["dataset_id"], d["dataset_sha256"]] for d in normalized["datasets"]])
    _write("normalized_manifest.json", normalized)

    # -- 5 timeframe lineage -------------------------------------------------
    lineage_rows = []
    for row in slices:
        for timeframe in DERIVED_TIMEFRAMES:
            item = dict(row["timeframe_lineage"][timeframe])
            item["year"] = row["year"]
            item["coverage_audit"] = row["coverage_audit"][timeframe]
            lineage_rows.append(item)
    lineage = {
        "manifest_version": "DATA_AUTHORITY_R1_TIMEFRAME_LINEAGE_V1",
        "chain": "RAW(tick archive) -> M1(canonical) -> M5/M15/H1/H4/D1",
        "rule": "Every higher timeframe descends from the SAME M1 lineage and the "
                "same raw parent. No higher timeframe is taken from an independent "
                "provider feed.",
        "leakage_prevention": (
            "Buckets are UTC floors aligned to 00:00 and every timeframe divides "
            "1440 minutes, so no bucket straddles a day or a year. A bar with open "
            "T and span S is observable only from T+S; closed_bars_asof() is the "
            "only accessor that should feed a strategy and it is truncation "
            "invariant."),
        "row_count": len(lineage_rows),
        "rows": sorted(lineage_rows,
                       key=lambda r: (r["symbol"], r["year"], r["output_timeframe"])),
    }
    _write("timeframe_lineage.json", lineage)

    # -- 6 quality report ----------------------------------------------------
    quality_rows = []
    for row in slices:
        for timeframe in TIMEFRAMES:
            quality_rows.append(row["quality"][timeframe])
    m1_rows = [q for q in quality_rows if q["timeframe"] == "M1"]
    worst_coverage = min((q["coverage_pct"] for q in m1_rows), default=0.0)
    quality = {
        "report_version": "DATA_AUTHORITY_R1_DATA_QUALITY_REPORT_V1",
        "repair_policy": "NONE — suspicious observations are CLASSIFIED, never "
                         "silently repaired, dropped or forward filled",
        "missing_bar_definition": (
            "Measured against the instrument's DECLARED venue session contract "
            "(spot FX 17:00 America/New_York Sun-Fri; XAUUSD CME Globex 17:00 "
            "America/Chicago with a daily 16:00-17:00 halt), not a naive 24/7 grid."),
        "aggregate_m1": {
            "slices": len(m1_rows),
            "total_bars": sum(q["bar_count"] for q in m1_rows),
            "worst_coverage_pct": worst_coverage,
            "best_coverage_pct": max((q["coverage_pct"] for q in m1_rows), default=0.0),
            "total_duplicate_timestamps": sum(q["duplicate_timestamps"] for q in m1_rows),
            "total_invalid_ohlc": sum(q["invalid_ohlc"] for q in m1_rows),
            "total_timezone_anomalies": sum(q["timezone_anomalies"] for q in m1_rows),
            "total_grid_misalignments": sum(q["grid_misalignments"] for q in m1_rows),
            "total_non_monotonic": sum(q["non_monotonic_timestamps"] for q in m1_rows),
            "total_price_precision_anomalies": sum(
                q["price_precision_anomalies"] for q in m1_rows),
            "total_weekend_observations": sum(q["weekend_observations"] for q in m1_rows),
            "total_session_boundary_anomalies": sum(
                q["session_boundary_anomalies"] for q in m1_rows),
            "worst_gap_minutes": max((q["largest_gap_minutes"] for q in m1_rows),
                                     default=0),
        },
        "normalization_anomalies": {
            f"{r['symbol']}_{r['year']}": r["normalization"]["anomalies"]
            for r in slices
        },
        "per_slice": sorted(quality_rows,
                            key=lambda q: (q["symbol"], q["year"], q["timeframe"])),
    }
    _write("data_quality_report.json", quality)

    # -- 7 cross-source comparison ------------------------------------------
    comparisons = []
    hist_dir = ROOT / "data" / "external" / "histdata_fx_2017"
    try:
        from ag_edgelab.data.fx_histdata_2017 import (
            aggregate_m15, load_histdata_m1, verify_source_identity,
        )
        from ag_edgelab.data.authority.schema import CanonicalBar
        for symbol in SYMBOLS:
            zip_path = hist_dir / f"HISTDATA_COM_ASCII_{symbol}_M1_2017.zip"
            slice_row = next((r for r in slices
                              if r["symbol"] == symbol and r["year"] == 2017), None)
            if not zip_path.is_file() or slice_row is None:
                comparisons.append({
                    "symbol": symbol, "status": "NOT_COMPARED",
                    "reason": "HistData zip or 2017 slice unavailable in this run"})
                continue
            verify_source_identity(zip_path, symbol)       # fails closed
            hist_m1 = load_histdata_m1(zip_path)
            hist_m15 = aggregate_m15(hist_m1)
            hist_canon = [
                CanonicalBar(timestamp_utc=b.timestamp, symbol=symbol, open=b.open,
                             high=b.high, low=b.low, close=b.close)
                for b in hist_m15 if b.timestamp.year == 2017]
            duka_m15 = loads_canonical(
                cas.get_text(slice_row["datasets"]["M15"]["dataset_sha256"]))
            result = cross_source.compare(
                duka_m15, hist_canon, symbol=symbol, timeframe="M15",
                source_a="DUKASCOPY_TICK_FX31337_MIRROR_V1",
                source_b="HISTDATA_ASCII_M1_2017_PR10_PINNED")
            comparisons.append(result.as_dict())
    except Exception as exc:                                # noqa: BLE001
        comparisons.append({"status": "COMPARISON_ERROR", "detail": repr(exc)})

    blocked = [c for c in comparisons if c.get("verdict") == cross_source.SCALE_DISAGREEMENT]
    _write("cross_source_comparison.json", {
        "report_version": "DATA_AUTHORITY_R1_CROSS_SOURCE_COMPARISON_V1",
        "purpose": "Diagnostic only. Neither source was altered, re-based or blended, "
                   "and no dataset hash changed as a result of this comparison.",
        "overlap_window": "2017 (the only year both authorities cover)",
        "timeframe": "M15",
        "note": "HistData M15 uses the frozen >=13/15-minute rule; the Dukascopy M15 "
                "uses ANY_OBSERVATION. Different inclusion rules are expected and are "
                "NOT errors — that is precisely why timestamp agreement is reported "
                "separately from price agreement.",
        "scale_guard": "SCALE_DISAGREEMENT on any symbol is a hard stop",
        "scale_disagreements": len(blocked),
        "comparisons": comparisons,
    })

    # -- 8 partition registry ------------------------------------------------
    coverage_start = min(_dt(r["raw"]["coverage_start"]) for r in slices)
    coverage_end = max(_dt(r["raw"]["coverage_end"]) for r in slices)
    registry = build_partition_registry(coverage_start, coverage_end)
    reg_doc = registry.as_dict()
    reg_doc["datasets"] = {
        DATASET_ID: {
            "coverage_start_utc": _iso(coverage_start),
            "coverage_end_utc": _iso(coverage_end),
            "symbols": list(SYMBOLS),
            "corpus_sha256": normalized["corpus_sha256"],
        },
        LEGACY_DATASET_ID: {
            "status": "FROZEN — mirrored read-only from "
                      "config/governance/oos_access_log.json; unchanged by this mission",
        },
    }
    _write("dataset_partition_registry.json", reg_doc)

    # -- 9/10 readiness ------------------------------------------------------
    dev_start = _dt("2011-01-01T00:00:00Z")
    wf_end = _dt("2017-09-01T00:00:00Z")
    fold_report = {}
    usable_total = []
    vol_by_year: dict[str, list[float]] = {}
    regimes = []
    sessions: dict[str, dict[str, int]] = {}

    for symbol in SYMBOLS:
        rows = by_symbol.get(symbol, [])
        if not rows:
            continue
        d1_stamps: list[datetime] = []
        h1_stamps: list[datetime] = []
        for row in rows:
            d1 = loads_canonical(cas.get_text(row["datasets"]["D1"]["dataset_sha256"]))
            d1_stamps.extend(b.timestamp_utc for b in d1)
            regime = characterise_year(d1, symbol=symbol, year=row["year"])
            if regime:
                regimes.append(regime.as_dict())
                vol_by_year.setdefault(symbol, []).append(
                    regime.realized_vol_annualized_pct)
            h1 = loads_canonical(cas.get_text(row["datasets"]["H1"]["dataset_sha256"]))
            h1_stamps.extend(b.timestamp_utc for b in h1)
        folds = build_folds(h1_stamps, start=dev_start, end=wf_end)
        usable = sum(1 for f in folds if f.usable)
        usable_total.append(usable)
        fold_report[symbol] = {
            "folds_total": len(folds),
            "folds_usable": usable,
            "timeframe": "H1",
            "folds": [f.as_dict() for f in folds],
        }
        sessions[symbol] = session_distribution(h1_stamps)

    verdict = assess(
        years=years, symbols=SYMBOLS, min_coverage_pct=worst_coverage,
        usable_folds=min(usable_total) if usable_total else 0,
        vol_by_year=vol_by_year)

    _write("walk_forward_readiness.json", {
        "report_version": "DATA_AUTHORITY_R1_WALK_FORWARD_READINESS_V1",
        "disclaimer": "DATA readiness only. No strategy was run, fitted, scored or "
                      "selected to produce these numbers; folds are counted, not "
                      "evaluated.",
        "fold_design": {"train_months": 12, "test_months": 3, "step_months": 3,
                        "min_train_bars": 2000, "min_test_bars": 400,
                        "span": "[2011-01-01, 2017-09-01) = DEVELOPMENT + WALK_FORWARD"},
        "WALK_FORWARD_DATA_READY": verdict.walk_forward,
        "per_symbol": fold_report,
    })

    _write("regime_readiness.json", {
        "report_version": "DATA_AUTHORITY_R1_REGIME_READINESS_V1",
        "disclaimer": "DATA readiness only. Volatility, trend and session statistics "
                      "are properties of the price series; they are not edge claims "
                      "and no strategy produced them.",
        "REGIME_DATA_READY": verdict.regime,
        "MULTIYEAR_FX_DATA_READY": verdict.multiyear,
        "method": {
            "realized_volatility": "annualized population stdev of D1 log returns "
                                   "x sqrt(252), in percent",
            "efficiency_ratio": "|last close - first close| / sum(|close deltas|); "
                                ">=0.30 TRENDING, <=0.10 RANGING, else MIXED",
        },
        "per_symbol_year": sorted(regimes, key=lambda r: (r["symbol"], r["year"])),
        "session_distribution_h1_bars": sessions,
        "readiness_reasons": verdict.reasons,
    })

    # -- 11 friction ---------------------------------------------------------
    quotes = tuple(empty_quote(s, "VT Markets", "RAW_ECN") for s in SYMBOLS)
    friction = FrictionAuthorityStatus(
        framework_ready=True,
        value_authority_complete=net_economics_estimable(quotes),
        symbols=SYMBOLS, venue="VT Markets", account_type="RAW_ECN",
        quotes=quotes,
        blockers=(
            "No MT5 terminal and no broker credentials exist in this environment, "
            "and none may be requested.",
            "Outbound network reaches GitHub and PyPI only; no broker endpoint is "
            "reachable.",
            "Commission, swap, contract size, tick size and tick value are broker "
            "facts. They cannot be derived from a price feed at any precision.",
        ))
    friction_doc = friction.as_dict()
    friction_doc.update({
        "record_version": "DATA_AUTHORITY_R1_FRICTION_AUTHORITY_GAP_V1",
        "supersedes": "config/governance/friction_authority_gap.json is PRESERVED "
                      "unchanged; this record adds the prepared schema and the "
                      "measured-spread evidence lane.",
        "framework_components": {
            "cost_application": "src/ag_edgelab/friction/model.py — FrictionScenario "
                                "in R space, funding schedules, "
                                "NET_ECONOMIC_QUALIFICATION gate",
            "venue_quote_schema": "src/ag_edgelab/data/authority/friction_contract.py "
                                  "— FrictionQuote with the exact section 11 fields",
        },
        "what_this_mission_DID_add": (
            "A genuinely MEASURED spread series: the Dukascopy source is tick-native "
            "with bid and ask, so every canonical bar carries an observed mean spread "
            "in the `spread` column. That is real market evidence and it is already "
            "hashed into the datasets."),
        "why_that_is_still_NOT_a_friction_authority": (
            "Spread is one of five cost components. Commission, swap long/short, "
            "contract size and tick value remain NULL, and the measured spread is "
            "Dukascopy's ECN aggregate rather than the execution venue's. "
            "FRICTION_AUTHORITY_COMPLETE=NO."),
        "null_means": "NOT MEASURED. Never zero. assert_estimable() raises while any "
                      "required field is NULL, so no net claim can be produced by "
                      "accident.",
    })
    _write("friction_authority_gap.json", friction_doc)

    # -- 12 crypto review ----------------------------------------------------
    _write("crypto_data_adapter_review.json", crypto_review())

    # -- 13 timezone authority ----------------------------------------------
    # Recomputed here from the M1 datasets themselves rather than reused from
    # the per-slice records: pooling every year gives ~8x more weekly opens
    # per symbol, and it keeps the published proof independent of whatever
    # code version happened to build an individual slice.
    proofs: dict[str, TimezoneProof] = {}
    for symbol in SYMBOLS:
        rows = by_symbol.get(symbol, [])
        if not rows:
            continue
        provider_clock: list[datetime] = []
        for row in rows:
            text = cas.get_text(row["datasets"]["M1"]["dataset_sha256"])
            provider_clock.extend(provider_clock_timestamps(text))
        proofs[symbol] = prove_fixed_offset_frame(provider_clock)
    corpus = prove_corpus_frame(proofs)
    tz_doc = {
        "report_version": "DATA_AUTHORITY_R1_TIMEZONE_AUTHORITY_V1",
        "corpus_proof": corpus.as_dict(),
        "per_symbol_proofs": {
            sym: {
                "status": p.status,
                "admissible_offsets": list(p.admissible_offsets),
                "weeks_examined": p.weeks_examined,
                "best_match_fraction": round(p.match_fraction, 6),
                "source_clock_weekly_open_hours": list(p.source_clock_open_hours),
                "detail": p.detail,
            } for sym, p in sorted(proofs.items())},
        "proof_basis": (
            "Recomputed at assembly time from every M1 bar open time in the "
            "corpus. Per-slice proofs are retained below only as a cross-check."),
        "per_slice_status": {
            f"{r['symbol']}_{r['year']}": r["timezone_proof"]["status"]
            for r in slices},
        "dst_consistency": {
            f"{r['symbol']}_{r['year']}": r["dst_consistency"] for r in slices},
    }
    _write("timezone_authority.json", tz_doc)

    # -- 14 content-addressed evidence registry ------------------------------
    cas_entries = []
    for row in slices:
        tag = f"{row['symbol']}_{row['year']}"
        m1 = row["datasets"]["M1"]
        cas_entries.append({
            "artifact_id": f"DUKASCOPY_M1_{tag}",
            "sha256": m1["dataset_sha256"],
            "byte_size": m1["byte_size"],
            "schema_version": "EDGELAB_CANONICAL_BAR_V1",
            "producer_commit": "DATA_AUTHORITY_R1",
            "candidate_id": "NONE_DATA_AUTHORITY",
            "dataset_role": "NORMALIZED_M1_AUTHORITY",
            "storage_location": f"cas:{m1['dataset_sha256']}",
            "description": f"Canonical M1 bars for {row['symbol']} {row['year']} "
                           f"({m1['rows']:,} rows) derived from raw tick archive "
                           f"{row['raw']['sha256'][:12]}.",
        })
        idx = row["raw"]["member_index_sha256"]
        cas_entries.append({
            "artifact_id": f"DUKASCOPY_RAW_MEMBER_INDEX_{tag}",
            "sha256": idx,
            "byte_size": row["raw"].get("member_index_byte_size", 0),
            "schema_version": "EDGELAB_RAW_MEMBER_INDEX_V1",
            "producer_commit": "DATA_AUTHORITY_R1",
            "candidate_id": "NONE_DATA_AUTHORITY",
            "dataset_role": "RAW_MEMBER_INDEX",
            "storage_location": f"cas:{idx}",
            "description": f"Per-member sha256 index for {row['raw']['member_count']} raw "
                           f"tick files of {row['symbol']} {row['year']}; the "
                           f"Merkle root {row['raw']['sha256'][:12]} is its identity.",
        })
    registry_path = GOV / "external_artifact_registry.json"
    reg_json = json.loads(registry_path.read_text(encoding="utf-8"))
    reg_json["content_addressed"] = sorted(cas_entries,
                                           key=lambda e: e["artifact_id"])
    reg_json["content_addressed_policy"] = (
        "Datasets too large for git, held in an external content-addressed store. "
        "The sha256 IS the address, so a pointer cannot drift from its content. "
        "Absence reports UNMATERIALIZED (a clean checkout has no store); "
        "corruption always fails closed. Use "
        "`scripts/verify_external_artifacts.py --require-materialized` to assert "
        "the bytes are actually in hand.")
    registry_path.write_text(json.dumps(reg_json, indent=2) + "\n", encoding="utf-8")

    # -- 15 artifact manifest + final report ---------------------------------
    names = sorted(p.name for p in OUT.glob("*.json"))
    manifest = {
        "manifest_version": "DATA_AUTHORITY_R1_ARTIFACT_MANIFEST_V1",
        "git_holds": "manifests, hashes, schemas, small reports, code",
        "external_holds": "raw tick archives, canonical bar datasets, raw member "
                          "indexes — all content-addressed, none committed",
        "artifacts": [
            {
                "name": name,
                "sha256": sha256_json(json.loads((OUT / name).read_text("utf-8"))),
                "byte_size": (OUT / name).stat().st_size,
            }
            for name in names if name != "artifact_manifest.json"
        ],
    }
    _write("artifact_manifest.json", manifest)

    final = build_final_report(
        slices=slices, normalized=normalized, raw_manifest=raw_manifest,
        quality=quality, comparisons=comparisons, corpus=corpus, verdict=verdict,
        registry=registry, friction=friction_doc, years=years,
        usable_folds=min(usable_total) if usable_total else 0,
        cas_entry_count=len(cas_entries))
    _write("final_report.json", final)
    (OUT / "final_report.md").write_text(render_markdown(final), encoding="utf-8")

    names = sorted(p.name for p in OUT.glob("*.json"))
    manifest["artifacts"] = [
        {"name": n, "sha256": sha256_json(json.loads((OUT / n).read_text("utf-8"))),
         "byte_size": (OUT / n).stat().st_size}
        for n in names if n != "artifact_manifest.json"]
    _write("artifact_manifest.json", manifest)

    print(f"assembled {len(names) + 1} artifacts into {OUT.relative_to(ROOT)}")
    print(f"  MULTIYEAR={verdict.multiyear} WALK_FORWARD={verdict.walk_forward} "
          f"REGIME={verdict.regime}")
    print(f"  corpus timezone: {corpus.status} "
          f"{corpus.as_dict()['corpus_frame']}")
    print(f"  cross-source scale disagreements: {len(blocked)}")
    return 2 if blocked else 0


def crypto_review() -> dict:
    gap = json.loads((GOV / "data_authority_gap.json").read_text(encoding="utf-8"))
    efforts = gap["crypto_coverage"]["real_data_efforts_reviewed"]
    required = {
        "real_public_data": "Bytes from a real public venue archive, retrieved and "
                            "hashed in this environment.",
        "deterministic_pagination": "Cursor/segment walk that provably terminates and "
                                    "yields the same set every run.",
        "duplicate_detection": "Duplicates REJECTED, not silently deduplicated.",
        "missing_bar_detection": "Expected-vs-actual bar inventory against the 24/7 "
                                 "grid, every gap dated and classified.",
        "utc_normalization": "Epoch-ms open time, bar-open convention frozen.",
        "provenance": "Venue, endpoint, retrieval timestamp, immutable pin.",
        "hashing": "sha256 of raw bytes before derivation; dataset hash after.",
        "no_synthetic_as_edge_evidence": "Synthetic fixtures structurally excluded "
                                         "from evidence paths.",
        "funding_authority": "Real funding history for perpetual economics.",
    }
    status = {
        "real_public_data": ("FAIL", "data.binance.vision and api.bybit.com are "
                                     "unreachable from this sandbox; zero crypto "
                                     "bytes were retrieved, so nothing could be "
                                     "hashed or verified."),
        "deterministic_pagination": ("PASS_ON_REVIEW", "Bybit branch uses cursor "
                                     "pagination with oldest-1 continuation; Binance "
                                     "branch uses whole-month archives. Reviewed as "
                                     "code only — not executed."),
        "duplicate_detection": ("PARTIAL", "Both branches dedupe by timestamp key "
                                "rather than rejecting duplicates. The R1 contract "
                                "requires rejection: a duplicate is a provider defect "
                                "to be reported, not smoothed over."),
        "missing_bar_detection": ("FAIL", "Neither branch performs any gap or "
                                  "completeness validation; holes are skipped "
                                  "silently."),
        "utc_normalization": ("PASS_ON_REVIEW", "Open-time ms normalization present; "
                              "the bar-open convention is not frozen in a contract."),
        "provenance": ("FAIL", "No retrieval timestamp, no immutable pin, no manifest."),
        "hashing": ("FAIL", "No sha256 of downloaded archive bytes in either branch."),
        "no_synthetic_as_edge_evidence": ("PASS", "data/artifacts/synthetic_btcusdt is "
                                          "a CI fixture and is recorded as "
                                          "non-citable in the governance gap record."),
        "funding_authority": ("PARTIAL", "Bybit branch fetches funding history with a "
                              "conservative synthetic fallback. A synthetic fallback "
                              "cannot back a net economic claim under this contract."),
    }
    missing = [k for k, (verdict, _) in status.items()
               if verdict in ("FAIL", "PARTIAL")]
    return {
        "report_version": "DATA_AUTHORITY_R1_CRYPTO_DATA_ADAPTER_REVIEW_V1",
        "scope": "CONTRACT REVIEW ONLY. No crypto adapter was merged, no crypto data "
                 "was acquired, and no crypto strategy verification was run.",
        "CRYPTO_DATA_ADAPTER_READY": "NO",
        "required_contracts": required,
        "assessment": {k: {"verdict": v[0], "detail": v[1]} for k, v in status.items()},
        "exact_missing_contracts": sorted(missing),
        "branches_reviewed": efforts,
        "promotion_preconditions": [
            "Network access to a real crypto venue archive from the executing "
            "environment (the hard blocker today).",
            "Raw byte sha256 recorded BEFORE any derivation, with an immutable pin.",
            "Gap inventory against the 24/7 grid with every hole dated and classified.",
            "Duplicate timestamps REJECTED rather than deduplicated.",
            "Real funding history for any perpetual economic claim; no synthetic "
            "fallback may back a net number.",
            "Reuse of the R1 canonical schema, CAS and partition registry rather than "
            "a parallel crypto-only pipeline.",
        ],
    }


def build_final_report(*, slices, normalized, raw_manifest, quality, comparisons,
                       corpus, verdict, registry, friction, years, usable_folds,
                       cas_entry_count) -> dict:
    m1 = [q for q in quality["per_slice"] if q["timeframe"] == "M1"]
    symbols = sorted({r["symbol"] for r in slices})
    anomaly_totals: dict[str, int] = {}
    for counts in quality["normalization_anomalies"].values():
        for key, value in counts.items():
            if isinstance(value, int):
                anomaly_totals[key] = anomaly_totals.get(key, 0) + value
    compared = [c for c in comparisons if c.get("verdict")]
    return {
        "report_version": "DATA_AUTHORITY_R1_FINAL_REPORT_V1",
        "TASK_CLASS": "SYSTEM_DEVELOPMENT / DATA_AUTHORITY",
        "STATUS": "DATA_AUTHORITY_ESTABLISHED",
        "FX_DATA_AUTHORITY": "DUKASCOPY_TICK_FX31337_MIRROR_V1",
        "DATASET_ID": DATASET_ID,
        "SYMBOLS": symbols,
        "COVERAGE": {
            "years": years,
            "span": f"{min(years)}-01-01 .. {max(years)}-12-31",
            "symbol_years": len(slices),
            "m1_bars_total": sum(q["bar_count"] for q in m1),
            "all_timeframe_rows_total": normalized["total_rows"],
            "ticks_processed": sum(r["normalization"]["ticks_ingested"] for r in slices),
            "raw_bytes": raw_manifest["total_raw_bytes"],
            "raw_member_files": raw_manifest["total_member_count"],
            "worst_in_session_coverage_pct": quality["aggregate_m1"][
                "worst_coverage_pct"],
            "best_in_session_coverage_pct": quality["aggregate_m1"][
                "best_coverage_pct"],
        },
        "RAW_HASHES_VERIFIED": "YES",
        "TIMEZONE_AUTHORITY": {
            "frame": corpus.as_dict()["corpus_frame"],
            "status": corpus.status,
            "method": "joint (clock offset, venue session) identification per "
                      "instrument, then corpus-wide offset intersection",
            "detail": corpus.detail,
            "resolved_session_contracts": corpus.resolved_session_contracts,
        },
        "MISSING_BAR_POLICY": "EXPLICIT_ABSENCE_NO_FILL",
        "TIMEFRAME_LINEAGE": "RAW -> M1 -> M5/M15/H1/H4/D1 (single lineage, "
                             "UTC-floored buckets, completed bars only)",
        "INTEGRITY": {
            "duplicate_timestamps": quality["aggregate_m1"][
                "total_duplicate_timestamps"],
            "invalid_ohlc": quality["aggregate_m1"]["total_invalid_ohlc"],
            "timezone_anomalies": quality["aggregate_m1"]["total_timezone_anomalies"],
            "grid_misalignments": quality["aggregate_m1"]["total_grid_misalignments"],
            "non_monotonic_timestamps": quality["aggregate_m1"][
                "total_non_monotonic"],
            "price_precision_anomalies": quality["aggregate_m1"][
                "total_price_precision_anomalies"],
            "normalization_anomaly_totals": anomaly_totals,
        },
        "CROSS_SOURCE": {
            "comparator": "HISTDATA_ASCII_M1_2017_PR10_PINNED (frozen, unmodified)",
            "symbols_compared": len(compared),
            "verdicts": {c["symbol"]: c["verdict"] for c in compared},
            "median_relative_close_diff": {
                c["symbol"]: c["median_relative_close_diff"] for c in compared},
            "scale_disagreements": sum(
                1 for c in compared
                if c["verdict"] == cross_source.SCALE_DISAGREEMENT),
            "action_taken": "NONE — diagnostic only, neither source altered",
        },
        "MULTIYEAR_FX_DATA_READY": verdict.multiyear,
        "WALK_FORWARD_DATA_READY": verdict.walk_forward,
        "REGIME_DATA_READY": verdict.regime,
        "WALK_FORWARD_USABLE_FOLDS_MIN_ACROSS_SYMBOLS": usable_folds,
        "FRICTION_FRAMEWORK_READY": friction["FRICTION_FRAMEWORK_READY"],
        "FRICTION_AUTHORITY_COMPLETE": friction["FRICTION_AUTHORITY_COMPLETE"],
        "CRYPTO_DATA_ADAPTER_READY": "NO",
        "PARTITIONS": {
            "count": len(registry.records),
            "overlaps": 0,
            "fresh_oos_window": "[2018-01-01, 2018-07-01) — AVAILABLE, never opened",
            "sealed_windows": [
                r.as_dict()["window_utc"] for r in registry.records if r.sealed],
        },
        "GOVERNANCE_PRESERVED": {
            "PREVIOUS_OOS_LOG_PRESERVED": "YES",
            "C3_REJECTION_PRESERVED": "YES",
            "TARGET_POLICY_C3_V1": "EDGE_STATUS=NO_EDGE, OOS_STATUS=CONSUMED, "
                                   "RETUNING=FORBIDDEN",
            "CONSUMED_OOS_WINDOW": "[2017-09-01, 2017-12-01) remains CONSUMED; the "
                                   "same calendar period in the new dataset is "
                                   "registered DEVELOPMENT_KNOWN so it cannot be "
                                   "re-sold as fresh OOS via a second provider",
            "SEALED_HOLDOUT": "[2017-12-01, 2018-01-01) never opened; mirrored as "
                              "SEALED in the new dataset too",
        },
        "SAFETY_BOUNDARY": {
            "STRATEGY_RULES_CHANGED": "NO", "NEW_STRATEGY_CREATED": "NO",
            "PARAMETER_OPTIMIZATION": "NO", "OOS_OPENED": "NO",
            "HOLDOUT_TOUCHED": "NO", "EXECUTION_CAPABILITY_ADDED": "NO",
            "SYNTHETIC_USED_AS_EDGE_EVIDENCE": "NO",
            "STRATEGIES_RUN": "NO",
        },
        "CONTENT_ADDRESSED_ENTRIES": cas_entry_count,
        "PRIMARY_BLOCKER": "FRICTION_VALUE_AUTHORITY — commission, swap and contract "
                           "specifications require broker access that does not exist "
                           "in this environment. Net/economic claims remain "
                           "NOT_ESTIMABLE.",
        "NEXT": [
            "Capture an authoritative VT Markets RAW_ECN friction snapshot into the "
            "prepared FrictionQuote schema; that single input flips "
            "FRICTION_AUTHORITY_COMPLETE and unlocks net economic evaluation.",
            "Preregister any candidate BEFORE touching the fresh "
            "[2018-01-01, 2018-07-01) OOS window, and record it in "
            "config/governance/oos_access_log.json.",
            "Keep [2017-09-01, 2017-12-01) classified DEVELOPMENT_KNOWN for every "
            "new candidate family.",
            "If crypto is wanted, close the exact contracts listed in "
            "crypto_data_adapter_review.json rather than merging an adapter.",
        ],
    }


def render_markdown(f: dict) -> str:
    cov = f["COVERAGE"]
    tz = f["TIMEZONE_AUTHORITY"]
    integ = f["INTEGRITY"]
    xs = f["CROSS_SOURCE"]
    lines = [
        "# EDGELAB_DATA_AUTHORITY_R1 — Final Report",
        "",
        f"**STATUS:** {f['STATUS']}  ",
        f"**TASK_CLASS:** {f['TASK_CLASS']}",
        "",
        "## What was built",
        "",
        "A multi-year, hash-pinned, timezone-proven FX bar authority covering "
        f"**{', '.join(f['SYMBOLS'])}** over **{cov['span']}** "
        f"({cov['symbol_years']} symbol-years).",
        "",
        f"- **{cov['ticks_processed']:,} raw ticks** streamed from "
        f"{cov['raw_member_files']:,} archive members ({cov['raw_bytes'] / 1e9:.2f} GB)",
        f"- **{cov['m1_bars_total']:,} canonical M1 bars**, "
        f"{cov['all_timeframe_rows_total']:,} rows across all six timeframes",
        f"- In-session coverage {cov['worst_in_session_coverage_pct']:.2f}%"
        f" – {cov['best_in_session_coverage_pct']:.2f}%",
        "",
        "## Timezone authority",
        "",
        f"**{tz['frame']} — {tz['status']}**",
        "",
        "A single instrument cannot distinguish a clock from a venue session: "
        "(UTC+0, Chicago 17:00) and (UTC+1, New York 17:00) predict identical "
        "observations. Each instrument is therefore only narrowed to a set of "
        "admissible offsets, and the corpus intersection picks the unique one.",
        "",
        f"> {tz['detail']}",
        "",
        "Resolved venue sessions:",
        "",
    ]
    for sym, contract in sorted(tz["resolved_session_contracts"].items()):
        lines.append(f"- `{sym}` → {contract}")
    lines += [
        "",
        "## Integrity",
        "",
        "| Check | Count |",
        "| --- | ---: |",
        f"| Duplicate timestamps | {integ['duplicate_timestamps']} |",
        f"| Invalid OHLC bars | {integ['invalid_ohlc']} |",
        f"| Timezone anomalies | {integ['timezone_anomalies']} |",
        f"| Grid misalignments | {integ['grid_misalignments']} |",
        f"| Non-monotonic timestamps | {integ['non_monotonic_timestamps']} |",
        f"| Price precision anomalies | {integ['price_precision_anomalies']} |",
        "",
        f"Missing-bar policy: **{f['MISSING_BAR_POLICY']}** — a minute with no tick "
        "produces no row. Nothing is forward filled, interpolated or invented.",
        "",
        "## Cross-source check",
        "",
        f"Comparator: {xs['comparator']}.",
        "",
        "| Symbol | Verdict | Median relative close difference |",
        "| --- | --- | ---: |",
    ]
    for sym in sorted(xs["verdicts"]):
        lines.append(f"| {sym} | {xs['verdicts'][sym]} | "
                     f"{xs['median_relative_close_diff'][sym]:.2e} |")
    lines += [
        "",
        f"Scale disagreements: **{xs['scale_disagreements']}**. "
        f"{xs['action_taken']}.",
        "",
        "## Readiness (DATA only — not edge claims)",
        "",
        f"- `MULTIYEAR_FX_DATA_READY` = **{f['MULTIYEAR_FX_DATA_READY']}**",
        f"- `WALK_FORWARD_DATA_READY` = **{f['WALK_FORWARD_DATA_READY']}** "
        f"({f['WALK_FORWARD_USABLE_FOLDS_MIN_ACROSS_SYMBOLS']} usable folds on the "
        "weakest symbol)",
        f"- `REGIME_DATA_READY` = **{f['REGIME_DATA_READY']}**",
        f"- `FRICTION_FRAMEWORK_READY` = **{f['FRICTION_FRAMEWORK_READY']}**",
        f"- `FRICTION_AUTHORITY_COMPLETE` = **{f['FRICTION_AUTHORITY_COMPLETE']}**",
        f"- `CRYPTO_DATA_ADAPTER_READY` = **{f['CRYPTO_DATA_ADAPTER_READY']}**",
        "",
        "## Governance",
        "",
    ]
    for key, value in f["GOVERNANCE_PRESERVED"].items():
        lines.append(f"- **{key}**: {value}")
    lines += ["", "## Safety boundary", ""]
    for key, value in f["SAFETY_BOUNDARY"].items():
        lines.append(f"- {key} = **{value}**")
    lines += [
        "",
        "## Primary blocker",
        "",
        f["PRIMARY_BLOCKER"],
        "",
        "## Next",
        "",
    ]
    lines.extend(f"{i}. {item}" for i, item in enumerate(f["NEXT"], 1))
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(assemble())
