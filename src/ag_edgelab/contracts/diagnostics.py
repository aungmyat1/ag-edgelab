from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field


class FunnelDiagnosticReportV2(BaseModel):
    """Versioned, deterministic machine-readable Universal Funnel report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "FunnelDiagnosticReportV2"
    strategy_identity: Mapping[str, Any]
    dataset_identity: Mapping[str, Any]
    dataset_role: str
    flow: tuple[Mapping[str, Any], ...] = ()
    temporal: Mapping[str, Any] = Field(default_factory=dict)
    target_capability: Mapping[str, Any] = Field(default_factory=dict)
    economics: Mapping[str, Any] | None = None
    primary_diagnosis: str | None = None
    secondary_diagnoses: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    report_hash: str

    @classmethod
    def build(cls, **kwargs: Any) -> "FunnelDiagnosticReportV2":
        """Build with a content hash independent of mapping insertion order."""
        payload = dict(kwargs)
        payload.pop("report_hash", None)
        provisional = cls.model_construct(**payload, report_hash="")
        canonical = json.dumps(
            provisional.model_dump(mode="json", exclude={"report_hash"}),
            sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        return cls(**payload, report_hash=digest)
