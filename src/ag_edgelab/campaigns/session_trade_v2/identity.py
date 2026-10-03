from __future__ import annotations

"""Frozen source identity for the SESSION_TRADE_V2 economic-verification campaign.

The candidate under test is pinned to the exact upstream implementation from
the strategy source repository.  The files under ``frozen/`` are byte-exact
copies of the upstream artifacts; their sha256 hashes are pinned below and
verified before any campaign stage may execute (see :func:`verify_identity`).

Upstream identity (authoritative record)::

    source_repo   = aungmyat1/AG-profit-trading-assit
    source_pr     = 33
    source_branch = feat/session-trade-v2-unified
    source_commit = e1ffe9f1e5ccfb9a336f1b4ae4289d41901ec5d2
    strategy_id   = SESSION_TRADE_V2
    strategy_version = 2.0.0

If any frozen artifact hash drifts, the campaign must refuse to run: testing a
modified strategy under the same identity is forbidden.
"""

from dataclasses import dataclass
from pathlib import Path

from ag_edgelab.data.fingerprint import sha256_file

FROZEN_DIR = Path(__file__).parent / "frozen"

SOURCE_REPO = "aungmyat1/AG-profit-trading-assit"
SOURCE_PR = 33
SOURCE_BRANCH = "feat/session-trade-v2-unified"
SOURCE_COMMIT = "e1ffe9f1e5ccfb9a336f1b4ae4289d41901ec5d2"
STRATEGY_ID = "SESSION_TRADE_V2"
STRATEGY_VERSION = "2.0.0"

#: sha256 of each frozen source artifact, byte-exact from the source commit.
FROZEN_ARTIFACT_SHA256 = {
    "engine.py": "d7e0289c75c7cdb7386fb5f2e7e73151455cfed7605fda21841ce359fa2d0acb",
    "models.py": "db43c06df3da1a67276f63124bca4c8724e15c1b53d192c55ede8ce1da3ecb43",
    "SESSION_TRADE_V2.yaml": "3c7ea2eb68938172f9a91fcde732f7b4c9c2b0bc54c4b7e01adcc72cd52a861b",
    "SESSION_TRADE_V2_SPEC.md": "edf74dccc28bdbfc6c2a032b20ffe6b88c9ca086c833fbfcb368db3c04500219",
}

#: Execution authority is frozen OFF for this research-only campaign.
EXECUTION_AUTHORITY = {
    "demo_authorized": False,
    "live_authorized": False,
    "allow_order_send": False,
}


class IdentityError(RuntimeError):
    """Raised when the frozen candidate identity cannot be confirmed."""


@dataclass(frozen=True)
class CandidateIdentity:
    source_repo: str
    source_pr: int
    source_branch: str
    source_commit: str
    strategy_id: str
    strategy_version: str
    artifact_sha256: dict[str, str]

    @property
    def candidate_id(self) -> str:
        return f"{self.strategy_id}_v{self.strategy_version}_{self.source_commit[:12]}"

    def as_dict(self) -> dict:
        return {
            "source_repo": self.source_repo,
            "source_pr": self.source_pr,
            "source_branch": self.source_branch,
            "source_commit": self.source_commit,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "candidate_id": self.candidate_id,
            "artifact_sha256": dict(self.artifact_sha256),
            "execution_authority": dict(EXECUTION_AUTHORITY),
        }


def verify_identity() -> CandidateIdentity:
    """Fail closed unless every frozen artifact still hashes to its pinned value."""
    for name, expected in FROZEN_ARTIFACT_SHA256.items():
        path = FROZEN_DIR / name
        if not path.is_file():
            raise IdentityError(f"frozen artifact missing: {name}")
        actual = sha256_file(path)
        if actual != expected:
            raise IdentityError(
                f"frozen artifact hash drift for {name}: expected {expected}, got {actual}; "
                "refusing to test a modified strategy under the SESSION_TRADE_V2@2.0.0 identity"
            )
    return CandidateIdentity(
        source_repo=SOURCE_REPO,
        source_pr=SOURCE_PR,
        source_branch=SOURCE_BRANCH,
        source_commit=SOURCE_COMMIT,
        strategy_id=STRATEGY_ID,
        strategy_version=STRATEGY_VERSION,
        artifact_sha256=dict(FROZEN_ARTIFACT_SHA256),
    )
