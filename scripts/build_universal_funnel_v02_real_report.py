from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ag_edgelab.analytics.unified import build_funnel_diagnostic_report
from ag_edgelab.contracts.funnel import FunnelStage, FunnelStageResult, RuleResult
from ag_edgelab.ledger.candidate import CandidateRecord

ROOT = Path(__file__).parents[1]
ART = ROOT / "artifacts/mtf_control_shift_v1"
UTC = timezone.utc


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _result(candidate: str, stage: FunnelStage, at: datetime, passed: bool, *, features=None, reason=None):
    features = dict(features or {})
    rule = RuleResult(
        rule_id=f"REAL_V2_{stage.value}_TEMPORAL",
        rule_version="1",
        rule_hash="d" * 64,
        passed=passed,
        evaluated_at=at,
        features=features,
        failure_reason=reason,
        rejection_code=reason,
    )
    return FunnelStageResult(
        candidate_id=candidate, stage=stage, passed=passed, as_of=at,
        rule_results=(rule,), failure_reason=reason,
        rejection_codes=(reason,) if reason else (),
    )


def build_records() -> tuple[CandidateRecord, ...]:
    locations = [json.loads(line) for line in (ART / "trigger_cases.jsonl").read_text().splitlines() if line.strip()]
    shifts = {json.loads(line)["analysis_unit_id"]: json.loads(line) for line in (ART / "v2_m15_refinement_cases.jsonl").read_text().splitlines() if line.strip()}
    records = []
    for row in locations:
        cid = row["analysis_unit_id"]
        location_time = _dt(row["timestamp"])
        location_cycle = f"{location_time.date().isoformat()}|{row['session']}"
        stages = [
            _result(cid, FunnelStage.CONTEXT, location_time, True, features={"cycle_id": location_cycle, "session": row["session"]}),
            _result(cid, FunnelStage.LOCATION, location_time, True, features={"cycle_id": location_cycle, "session": row["session"]}),
        ]
        if cid in shifts:
            shift = shifts[cid]
            trigger_time = _dt(shift["h1_shift_time"])
            trigger_cycle = f"{trigger_time.date().isoformat()}|{row['session']}"
            stages.append(_result(cid, FunnelStage.TRIGGER, trigger_time, True, features={"cycle_id": trigger_cycle, "session": row["session"]}))
            # Confirmation was evaluated at the current observation but did not pass.
            stages.append(_result(cid, FunnelStage.GEOMETRY, location_time, False, features={"logical_stage": "CONFIRMATION", "cycle_id": location_cycle}, reason="SESSION_WINDOW_EXPIRED"))
        else:
            stages.append(_result(cid, FunnelStage.TRIGGER, location_time, False, features={"cycle_id": location_cycle, "session": row["session"]}, reason="NO_VALID_H1_CONTROL_SHIFT"))
        records.append(CandidateRecord(
            candidate_id=cid, instrument=row["symbol"], strategy_id="ST_MTF_CONTROL_SHIFT_V2", strategy_version="2.0.0",
            strategy_sha256="56b6032fc949564e0ff8d147eb794560088fb0d90eac3bc549de504f01a6cc91",
            dataset_sha256="PR10_HISTDATA_2017", stage_results=tuple(stages),
        ))
    return tuple(records)


def main() -> None:
    records = build_records()
    manifest = ART / "dataset_manifest.json"
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    report = build_funnel_diagnostic_report(
        records,
        strategy_identity={"strategy_id": "ST_MTF_CONTROL_SHIFT_V2", "version": "2.0.0", "sha256": "56b6032fc949564e0ff8d147eb794560088fb0d90eac3bc549de504f01a6cc91"},
        dataset_identity={"source": "PR_10_HISTDATA_2017", "manifest_sha256": manifest_sha, "raw_identity_reused_from_stv2": True},
        dataset_role="DEVELOPMENT",
        evidence_refs=(
            "artifacts/mtf_control_shift_v1/trigger_cases.jsonl",
            "artifacts/mtf_control_shift_v1/v2_m15_refinement_cases.jsonl",
            "artifacts/mtf_control_shift_v1/v2_m15_refinement_audit.json",
            "artifacts/mtf_control_shift_v1/v2_temporal_coupling.json",
        ),
        economics={"signals": 0, "fills": 0, "closed": 0, "gross_R": None, "friction_R": 0, "net_R": None, "expectancy_R": None, "PF": None, "win_rate": None, "max_drawdown_R": None, "MFE_R": None, "MAE_R": None},
    )
    (ART / "universal_funnel_report_v2.json").write_text(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n")
    print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
