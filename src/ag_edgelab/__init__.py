"""EdgeLab research-only verification laboratory."""
from .system_completion import (
    ContaminationRecord, ContaminationRegistry, ExposureType, FrictionAuthority,
    FrictionEvidence, FrozenCandidateIdentity, GovernanceError, ReadinessState,
    ReusePolicy, SearchRecord, SearchLedger, authorize_holdout, authorize_oos, readiness_audit,
    ticket_status, verification_verdict,
)

__all__ = ["ContaminationRecord", "ContaminationRegistry", "ExposureType", "FrictionAuthority", "FrictionEvidence", "FrozenCandidateIdentity", "GovernanceError", "ReadinessState", "ReusePolicy", "SearchRecord", "SearchLedger", "authorize_holdout", "authorize_oos", "readiness_audit", "ticket_status", "verification_verdict"]
