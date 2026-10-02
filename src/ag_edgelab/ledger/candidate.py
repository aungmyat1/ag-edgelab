from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict

from ag_edgelab.contracts.funnel import FunnelStageResult
from ag_edgelab.data.fingerprint import sha256_json


class CandidateRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    instrument: str
    strategy_id: str
    strategy_version: str
    strategy_sha256: str
    dataset_sha256: str
    stage_results: tuple[FunnelStageResult, ...]

    @property
    def passed(self) -> bool:
        return bool(self.stage_results) and all(x.passed for x in self.stage_results)

    @property
    def last_stage(self) -> str | None:
        return self.stage_results[-1].stage.value if self.stage_results else None

    @property
    def rejection_codes(self) -> tuple[str, ...]:
        return tuple(code for stage in self.stage_results for code in stage.rejection_codes)

    @property
    def record_sha256(self) -> str:
        return sha256_json(self.model_dump(mode="json"))


def write_jsonl(path: str | Path, rows: Iterable[CandidateRecord]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n")
    return str(target)
