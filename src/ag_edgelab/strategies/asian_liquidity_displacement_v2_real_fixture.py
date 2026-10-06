"""Development-only real-fixture fact producer for frozen ALD V2.

The frozen parent strategy remains the sole owner of ALD V2's opportunity,
structure, session, entry, and stop semantics.  This adapter invokes that
parent replay without mutation, exposes its recorded stage facts as tri-state
optimizer cells, and separately evaluates the owner-approved
``FIXED_REFERENCE_2R_V1`` outcome model.

Only raw rows in an annual DEVELOPMENT window are parsed.  OOS and sealed
holdout rows are never converted into bars, frames, facts, or outcomes.
"""

from __future__ import annotations

import csv
import io
import json
import math
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

from ag_edgelab.contracts.dataset import DatasetRole
from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.data.fingerprint import sha256_file
from ag_edgelab.data.fx_histdata_2017 import (NY, aggregate_m15, derive_fx_timeframe,
                                              quality_gate_m1)
from ag_edgelab.data.fx_histdata_multiyear import NonDevelopmentAccessError, partition_bounds
from ag_edgelab.optimization.funnel_optimizer import (EventTable, Opportunity, ReferenceOutcomeStatus,
                                                       RelaxedReplay)
from ag_edgelab.strategies import asian_liquidity_displacement_v2 as V2
from ag_edgelab.strategies.asian_liquidity_displacement_v1 import aggregate_m5
from ag_edgelab.strategies.asian_liquidity_displacement_v2_relaxed import (V2_RELAXED_ENGINE_ID,
                                                                            legacy_stage_facts,
                                                                            v2_relaxed_rules)

UTC = timezone.utc
REFERENCE_MODEL_ID = "FIXED_REFERENCE_2R_V1"
REAL_FIXTURE_ENGINE_ID = "ALD_V2_REAL_OPPORTUNITY_FACT_PRODUCER_R2"


@dataclass(frozen=True)
class DevelopmentFrames:
    symbol: str
    year: int
    frames: Mapping[str, tuple[MarketBar, ...]]
    quality: Mapping[str, object]
    source_sha256: str


@dataclass(frozen=True)
class FixedReference2ROutcome:
    entry_price: float | None
    entry_time: datetime | None
    stop_price: float | None
    target_price: float | None
    exit_price: float | None
    exit_time: datetime | None
    outcome_r: float | None
    status: ReferenceOutcomeStatus
    exit_reason: str
    ambiguity_code: str | None = None

    @classmethod
    def not_evaluable(cls, *, entry_price: float | None = None,
                      entry_time: datetime | None = None,
                      stop_price: float | None = None,
                      target_price: float | None = None,
                      ambiguity_code: str | None = None) -> "FixedReference2ROutcome":
        return cls(entry_price, entry_time, stop_price, target_price, None, None,
                   None, ReferenceOutcomeStatus.NOT_EVALUABLE, "NOT_EVALUABLE", ambiguity_code)


@dataclass(frozen=True)
class RealFixtureProduction:
    table: EventTable
    frames: Mapping[tuple[str, int], DevelopmentFrames]
    parent_units: Mapping[str, V2.V2Unit]
    reference_model: str = REFERENCE_MODEL_ID

    @property
    def ambiguous_intrabar_rows(self) -> int:
        return sum(row.reference_ambiguity_code == "AMBIGUOUS_INTRABAR" for row in self.table.rows)


def assert_development_role(role: DatasetRole) -> None:
    if role is not DatasetRole.DEVELOPMENT:
        raise NonDevelopmentAccessError(
            f"{role.value} refused by {REAL_FIXTURE_ENGINE_ID}; only DEVELOPMENT is authorized")


def _fixture_file_map(preregistration: Mapping[str, object]) -> Mapping[tuple[str, int], Mapping[str, object]]:
    materialization = preregistration.get("materialization")
    if not isinstance(materialization, Mapping):
        raise ValueError("fixture preregistration has no materialization section")
    files = materialization.get("files")
    if not isinstance(files, list):
        raise ValueError("fixture preregistration has no files")
    out: dict[tuple[str, int], Mapping[str, object]] = {}
    for item in files:
        if not isinstance(item, Mapping):
            raise ValueError("malformed fixture file entry")
        key = (str(item["symbol"]), int(item["year"]))
        if key in out:
            raise ValueError(f"duplicate fixture file entry {key}")
        out[key] = item
    return out


def _parse_development_m1(zip_path: Path, *, year: int, symbol: str) -> tuple[MarketBar, ...]:
    """Parse only DEV bar rows from a HistData archive.

    The source is America/New_York.  The raw prefix check discards all
    September--December rows before CSV/OHLC parsing; the UTC check handles
    the small DST/boundary edge around the end of August.  This is intentionally
    separate from the broad legacy loader, which parses whole-year archives.
    """
    dev_start, dev_end = partition_bounds("DEVELOPMENT", year)
    bars: list[MarketBar] = []
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(name for name in archive.namelist() if name.endswith(".csv"))
        if len(names) != 1:
            raise ValueError(f"{zip_path.name}: expected exactly one CSV")
        with archive.open(names[0]) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8")
            for line in text:
                # HistData's first 15 bytes are YYYYMMDD HHMMSS.  Do not split
                # or inspect OHLCV outside the authorized local Jan--Aug lane.
                stamp = line[:15]
                if len(stamp) != 15 or stamp[:4] != str(year) or stamp[4:6] >= "09":
                    continue
                row = next(csv.reader((line,), delimiter=";"), ())
                if len(row) < 5:
                    raise ValueError(f"{symbol}:{year}: malformed DEVELOPMENT source row")
                timestamp = datetime.strptime(row[0], "%Y%m%d %H%M%S").replace(tzinfo=NY).astimezone(UTC)
                if not (dev_start <= timestamp < dev_end):
                    continue
                bars.append(MarketBar(timestamp=timestamp, open=float(row[1]), high=float(row[2]),
                                      low=float(row[3]), close=float(row[4])))
    bars.sort(key=lambda bar: bar.timestamp)
    return tuple(bars)


def load_development_frames(*, zip_path: str | Path, symbol: str, year: int,
                            expected_sha256: str, role: DatasetRole = DatasetRole.DEVELOPMENT) -> DevelopmentFrames:
    """Verify raw identity then build only DEVELOPMENT frames with frozen rules."""
    assert_development_role(role)
    path = Path(zip_path)
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise ValueError(f"{symbol}:{year}: raw fixture sha256 mismatch")
    m1 = _parse_development_m1(path, year=year, symbol=symbol)
    quality = quality_gate_m1(m1, f"{symbol}:{year}:DEVELOPMENT")
    m15 = aggregate_m15(m1)
    m5 = aggregate_m5(m1)
    frames: dict[str, tuple[MarketBar, ...]] = {"M15": m15, "M5": m5}
    for timeframe in ("H1", "H4", "D1"):
        frames[timeframe], _ = derive_fx_timeframe(m15, timeframe, symbol)
    quality = dict(quality) | {
        "dataset_role": "DEVELOPMENT",
        "development_window": [value.isoformat() for value in partition_bounds("DEVELOPMENT", year)],
        "oos_or_holdout_rows_parsed": 0,
        "bars": {name: len(rows) for name, rows in sorted(frames.items())},
    }
    return DevelopmentFrames(symbol, year, frames, quality, actual_sha256)


def fixed_reference_2r_v1(unit: V2.V2Unit, m5: Sequence[MarketBar]) -> FixedReference2ROutcome:
    """Evaluate the owner-approved reference model after a canonical V2 entry.

    The entry is the frozen parent confirmation-close price and starts on the
    next available M5 bar.  The frozen parent outcome horizon
    ``OUTCOME_HORIZON_M5_BARS`` is the existing opportunity expiry; a truncated
    horizon is not converted into an invented timeout.  Target/stop ties within
    one M5 candle are intentionally not resolved; no authoritative lower-frame
    ordering is wired into this R2 fixture path, so the row fails closed.
    """
    if not unit.passed("S7_ENTRY_AVAILABLE") or unit.entry is None or unit.stop is None or unit.confirm_time is None:
        return FixedReference2ROutcome.not_evaluable()
    if unit.direction not in {"BULL", "BEAR"}:
        return FixedReference2ROutcome.not_evaluable()
    risk = abs(unit.entry - unit.stop)
    if risk <= 0 or not math.isfinite(risk):
        return FixedReference2ROutcome.not_evaluable()
    try:
        confirmation_open = datetime.fromisoformat(unit.confirm_time).astimezone(UTC)
    except ValueError:
        return FixedReference2ROutcome.not_evaluable()
    entry_time = confirmation_open + timedelta(minutes=5)
    target = unit.entry + (2.0 * risk if unit.direction == "BULL" else -2.0 * risk)
    start_index = next((index for index, bar in enumerate(m5) if bar.timestamp >= entry_time), None)
    if start_index is None:
        return FixedReference2ROutcome.not_evaluable(
            entry_price=unit.entry, entry_time=entry_time, stop_price=unit.stop, target_price=target)
    forward = list(m5[start_index:start_index + V2.OUTCOME_HORIZON_M5_BARS])
    if not forward:
        return FixedReference2ROutcome.not_evaluable(
            entry_price=unit.entry, entry_time=entry_time, stop_price=unit.stop, target_price=target)
    for bar in forward:
        if unit.direction == "BULL":
            hit_stop, hit_target = bar.low <= unit.stop, bar.high >= target
        else:
            hit_stop, hit_target = bar.high >= unit.stop, bar.low <= target
        if hit_stop and hit_target:
            return FixedReference2ROutcome.not_evaluable(
                entry_price=unit.entry, entry_time=entry_time, stop_price=unit.stop,
                target_price=target, ambiguity_code="AMBIGUOUS_INTRABAR")
        if hit_stop:
            return FixedReference2ROutcome(unit.entry, entry_time, unit.stop, target,
                                           unit.stop, bar.timestamp, -1.0,
                                           ReferenceOutcomeStatus.EVALUABLE, "STOP")
        if hit_target:
            return FixedReference2ROutcome(unit.entry, entry_time, unit.stop, target,
                                           target, bar.timestamp, 2.0,
                                           ReferenceOutcomeStatus.EVALUABLE, "TARGET_2R")
    if len(forward) < V2.OUTCOME_HORIZON_M5_BARS:
        return FixedReference2ROutcome.not_evaluable(
            entry_price=unit.entry, entry_time=entry_time, stop_price=unit.stop, target_price=target)
    last = forward[-1]
    outcome = ((last.close - unit.entry) / risk if unit.direction == "BULL"
               else (unit.entry - last.close) / risk)
    return FixedReference2ROutcome(unit.entry, entry_time, unit.stop, target,
                                   last.close, last.timestamp + timedelta(minutes=5), outcome,
                                   ReferenceOutcomeStatus.EVALUABLE, "TIMEOUT")


def _opportunity_timestamp(unit: V2.V2Unit) -> datetime:
    if unit.event_time:
        return datetime.fromisoformat(unit.event_time).astimezone(UTC)
    day = datetime.fromisoformat(unit.day).replace(tzinfo=UTC)
    return day + timedelta(hours=V2.SESSION_PAIRS[unit.session][0])


def _opportunity_from_unit(unit: V2.V2Unit, *, dataset_id: str,
                            reference: FixedReference2ROutcome) -> Opportunity:
    return Opportunity(
        event_id=f"{unit.candidate_id}|REAL_FIXTURE_R2",
        candidate_id=unit.candidate_id,
        timestamp_utc=_opportunity_timestamp(unit),
        symbol=unit.symbol,
        session=unit.session,
        dataset_id=dataset_id,
        strategy_id=V2.STRATEGY_ID,
        engine_id=REAL_FIXTURE_ENGINE_ID,
        feature_values={"v2_stage_facts": legacy_stage_facts(unit)},
        reference_outcome_r=reference.outcome_r,
        actual_outcome_r=unit.realised_r,
        reference_entry_price=reference.entry_price,
        reference_entry_time=reference.entry_time,
        reference_stop_price=reference.stop_price,
        reference_target_price=reference.target_price,
        reference_exit_price=reference.exit_price,
        reference_exit_time=reference.exit_time,
        reference_exit_reason=reference.exit_reason,
        reference_ambiguity_code=reference.ambiguity_code,
    )


def produce_real_fixture(*, preregistration_path: str | Path,
                         root: str | Path = ".",
                         role: DatasetRole = DatasetRole.DEVELOPMENT) -> RealFixtureProduction:
    """Run frozen ALD V2 and reference outcomes on the registered DEV fixture."""
    assert_development_role(role)
    root_path = Path(root)
    preregistration = json.loads(Path(preregistration_path).read_text(encoding="utf-8"))
    fixture_files = _fixture_file_map(preregistration)
    materialization = preregistration["materialization"]
    assert isinstance(materialization, Mapping)
    dataset_hash = str(materialization["dataset_sha256"])
    dataset_id = f"{preregistration['candidate_fixture_id']}:{dataset_hash[:16]}"
    frames_by_pair: dict[tuple[str, int], DevelopmentFrames] = {}
    opportunities: list[Opportunity] = []
    parent_units: dict[str, V2.V2Unit] = {}
    for (symbol, year), item in sorted(fixture_files.items()):
        relative_path = Path(str(item["path"]))
        bundle = load_development_frames(
            zip_path=root_path / relative_path,
            symbol=symbol,
            year=year,
            expected_sha256=str(item["sha256"]),
            role=role,
        )
        frames_by_pair[(symbol, year)] = bundle
        start, end = partition_bounds("DEVELOPMENT", year)
        units = V2.replay_symbol(dict(bundle.frames), symbol, start, end)
        for unit in units:
            reference = fixed_reference_2r_v1(unit, bundle.frames["M5"])
            opportunity = _opportunity_from_unit(unit, dataset_id=dataset_id, reference=reference)
            opportunities.append(opportunity)
            parent_units[opportunity.event_id] = unit
    table = RelaxedReplay(v2_relaxed_rules(), engine_id=V2_RELAXED_ENGINE_ID).evaluate(
        opportunities, dataset_role=role)
    return RealFixtureProduction(table, frames_by_pair, parent_units)


def production_summary(production: RealFixtureProduction) -> dict[str, object]:
    """Machine-readable real-fixture counts; no economic interpretation."""
    table = production.table
    counts = {"PASS": 0, "FAIL": 0, "NOT_EVALUABLE": 0}
    for row in table.rows:
        for cell in row.rule_cells.values():
            counts[cell.state.value] += 1
    return {
        "reference_model": REFERENCE_MODEL_ID,
        "rows": len(table.rows),
        "symbols": sorted({row.symbol for row in table.rows}),
        "years": sorted({row.timestamp_utc.year for row in table.rows}),
        "opportunities": len(table.rows),
        "rule_cells": counts,
        "reference_outcome_rows": sum(row.reference_outcome_r is not None for row in table.rows),
        "not_evaluable_outcomes": sum(row.reference_outcome_status is ReferenceOutcomeStatus.NOT_EVALUABLE
                                        for row in table.rows),
        "ambiguous_intrabar_rows": production.ambiguous_intrabar_rows,
        "event_table_sha256": table.sha256,
        "frame_quality": {f"{symbol}_{year}": bundle.quality
                          for (symbol, year), bundle in sorted(production.frames.items())},
    }
