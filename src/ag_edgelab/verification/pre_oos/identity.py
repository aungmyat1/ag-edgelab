"""Candidate identity gate — no robustness verdict without a frozen subject.

A robustness claim is about a specific, immutable artefact. If the thing
being measured can drift between the measurement and the OOS run, the
measurement certifies nothing. So before any axis is computed the gate
demands a complete identity and re-derives the hash from the declared
content.

The failure mode this blocks is mundane and common: a candidate is
"frozen", robustness is measured, then a parameter is nudged, and the
OOS window is spent on something the robustness evidence never described.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ag_edgelab.data.fingerprint import sha256_json

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

#: Every field required before a verdict may be issued. preregistration
#: is conditionally required (see CandidateIdentity.missing_fields).
REQUIRED_IDENTITY_FIELDS: tuple[str, ...] = (
    "candidate_id", "candidate_version", "candidate_sha256",
    "strategy_rule_hash", "dataset_manifest_hash", "engine_version",
    "entry_contract_hash", "sl_contract_hash", "target_contract_hash",
)

HASH_FIELDS: tuple[str, ...] = (
    "candidate_sha256", "strategy_rule_hash", "dataset_manifest_hash",
    "entry_contract_hash", "sl_contract_hash", "target_contract_hash",
)


class CandidateIdentityInvalid(RuntimeError):
    """Identity is incomplete, malformed, or does not reproduce."""


@dataclass(frozen=True)
class CandidateIdentity:
    """The frozen subject of a robustness evaluation."""

    candidate_id: str | None = None
    candidate_version: str | None = None
    candidate_sha256: str | None = None
    strategy_rule_hash: str | None = None
    dataset_manifest_hash: str | None = None
    engine_version: str | None = None
    entry_contract_hash: str | None = None
    sl_contract_hash: str | None = None
    target_contract_hash: str | None = None
    preregistration_hash: str | None = None
    preregistration_applicable: bool = False
    #: The canonical contract content, used to re-derive candidate_sha256.
    contract_content: dict | None = None
    contract_hash_authority: str = "ag_edgelab.data.fingerprint.sha256_json"

    def missing_fields(self) -> tuple[str, ...]:
        out = [f for f in REQUIRED_IDENTITY_FIELDS if not getattr(self, f)]
        if self.preregistration_applicable and not self.preregistration_hash:
            out.append("preregistration_hash")
        return tuple(out)

    def malformed_hashes(self) -> tuple[str, ...]:
        bad = []
        for fname in HASH_FIELDS:
            value = getattr(self, fname)
            if value and not SHA256_RE.match(value):
                bad.append(fname)
        if (self.preregistration_applicable and self.preregistration_hash
                and not SHA256_RE.match(self.preregistration_hash)):
            bad.append("preregistration_hash")
        return tuple(bad)

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields() and not self.malformed_hashes()

    def reproduce_hash(self) -> str | None:
        """Re-derive ``candidate_sha256`` from the declared content."""
        if self.contract_content is None:
            return None
        return sha256_json(self.contract_content)

    def as_dict(self) -> dict:
        reproduced = self.reproduce_hash()
        return {
            "candidate_id": self.candidate_id,
            "candidate_version": self.candidate_version,
            "candidate_sha256": self.candidate_sha256,
            "strategy_rule_hash": self.strategy_rule_hash,
            "dataset_manifest_hash": self.dataset_manifest_hash,
            "engine_version": self.engine_version,
            "entry_contract_hash": self.entry_contract_hash,
            "sl_contract_hash": self.sl_contract_hash,
            "target_contract_hash": self.target_contract_hash,
            "preregistration_hash": self.preregistration_hash,
            "preregistration_applicable": self.preregistration_applicable,
            "contract_hash_authority": self.contract_hash_authority,
            "content_supplied": self.contract_content is not None,
            "reproduced_sha256": reproduced,
            "hash_reproduced": (reproduced == self.candidate_sha256
                                if reproduced is not None else None),
            "complete": self.is_complete,
            "missing_fields": list(self.missing_fields()),
            "malformed_hashes": list(self.malformed_hashes()),
        }


def assert_identity(identity: CandidateIdentity) -> None:
    """Fail closed unless the identity is complete and reproduces."""
    missing = identity.missing_fields()
    if missing:
        raise CandidateIdentityInvalid(
            f"CANDIDATE_IDENTITY_INVALID: missing {list(missing)}. A "
            "robustness verdict describes one immutable artefact; without a "
            "complete identity there is nothing to bind the verdict to.")
    malformed = identity.malformed_hashes()
    if malformed:
        raise CandidateIdentityInvalid(
            f"CANDIDATE_IDENTITY_INVALID: {list(malformed)} are not sha256 "
            "digests.")
    if identity.contract_content is not None:
        reproduced = identity.reproduce_hash()
        if reproduced != identity.candidate_sha256:
            raise CandidateIdentityInvalid(
                f"CANDIDATE_IDENTITY_INVALID: declared candidate_sha256 "
                f"{identity.candidate_sha256} does not reproduce from the "
                f"supplied contract content (recomputed {reproduced}). The "
                "content and the identity disagree, so the subject of this "
                "evaluation is undefined.")
