"""Asian Session V2 overlay — direction alignment joined onto EXISTING
SWEEP/RANGE/TREND branch candidates. The underlying strategy is never
modified by this analysis.

REPOSITORY CONFLICT (reported, not silently reinterpreted): the mission
references `ST_ASIAN_SESSION_BRANCH_V2`, but no such strategy exists in
this repository — `ST_ASIAN_SESSION_V1` appears only as a documentation
reference structure without code, candidates or session times. The only
executable repository population with SWEEP/RANGE/TREND branch semantics is
`SYNTHETIC_BRANCHING_REFERENCE` (strategies/reference_branching.py). This
overlay therefore runs against that population as a DECLARED PROXY and the
Asian-V2-specific finding is reported as INSUFFICIENT_EVIDENCE for the real
strategy until its owner lands V2 in the repository.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from ag_edgelab.contracts.branching import FunnelRunResult
from ag_edgelab.universal.confirmation import SetupAlignment, classify_alignment
from ag_edgelab.universal.direction import Direction

ASIAN_V2_STATUS = (
    "ST_ASIAN_SESSION_BRANCH_V2_NOT_PRESENT_IN_REPOSITORY — overlay executed "
    "against SYNTHETIC_BRANCHING_REFERENCE as a declared proxy population"
)

BRANCHES = ("SWEEP", "RANGE", "TREND")

_NODE_TO_BRANCH = {  # terminal node ids of the reference branching funnel
    "sweep_setup": "SWEEP",
    "range_setup": "RANGE",
    "trend_buy": "TREND",
    "trend_sell": "TREND",
}


class OverlayCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    branch: str                    # SWEEP | RANGE | TREND
    trade_direction: str           # LONG | SHORT | NONE
    authority: Direction
    alignment: SetupAlignment


class OverlayResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    candidates: tuple[OverlayCandidate, ...]
    aligned_n: int
    counter_n: int
    neutral_n: int
    by_branch: Mapping[str, Mapping[str, int]]


def _trade_side_to_direction(side: str) -> Direction:
    return {"LONG": Direction.BULL, "SHORT": Direction.BEAR}.get(side, Direction.NEUTRAL)


def overlay_branch_candidates(
    runs: Sequence[FunnelRunResult],
    authority_by_candidate: Mapping[str, Direction],
    status: str = ASIAN_V2_STATUS,
) -> OverlayResult:
    """Join direction authority onto existing branch candidates (read-only).

    COUNTER_DIRECTION setups stay in the diagnostic population — recording
    them is exactly what lets EdgeLab test whether direction alignment adds
    economic capability (mission section 11).
    """
    candidates: list[OverlayCandidate] = []
    by_branch: dict[str, dict[str, int]] = {b: {a.value: 0 for a in SetupAlignment} for b in BRANCHES}
    for run in runs:
        terminal = next((e for e in run.events if e.node_id in _NODE_TO_BRANCH), None)
        if terminal is None:
            continue
        branch = _NODE_TO_BRANCH[terminal.node_id]
        trade_side = run.trades[0].direction if run.trades else "NONE"
        authority = authority_by_candidate.get(run.candidate_id, Direction.NEUTRAL)
        alignment = classify_alignment(authority, _trade_side_to_direction(trade_side))
        candidates.append(OverlayCandidate(
            candidate_id=run.candidate_id, branch=branch, trade_direction=trade_side,
            authority=authority, alignment=alignment))
        by_branch[branch][alignment.value] += 1
    aligned = sum(1 for c in candidates if c.alignment == SetupAlignment.ALIGNED)
    counter = sum(1 for c in candidates if c.alignment == SetupAlignment.COUNTER_DIRECTION)
    neutral = sum(1 for c in candidates if c.alignment == SetupAlignment.NEUTRAL)
    return OverlayResult(status=status, candidates=tuple(candidates),
                         aligned_n=aligned, counter_n=counter, neutral_n=neutral,
                         by_branch=by_branch)


class PreemptionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    branch_under_v1: str
    branch_under_v2: str
    preempted_to_range: bool       # SWEEP under one variant, RANGE under the other
    alignment: SetupAlignment
    pullback_direction: str        # "WITH_AUTHORITY" | "AGAINST_AUTHORITY" | "UNKNOWN"
    suppresses_later_aligned: bool


class PreemptionAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    records: tuple[PreemptionRecord, ...]
    range_population_n: int
    preempted_n: int
    preempted_aligned_n: int
    preempted_counter_n: int
    preempted_neutral_n: int
    suppressing_n: int
    finding: str
    evidence_sufficiency: str


def _branch_of(run: FunnelRunResult) -> str | None:
    terminal = next((e for e in run.events if e.node_id in _NODE_TO_BRANCH), None)
    return None if terminal is None else _NODE_TO_BRANCH[terminal.node_id]


def analyze_range_preemption(
    runs_v1: Sequence[FunnelRunResult],
    runs_v2: Sequence[FunnelRunResult],
    overlay: OverlayResult,
    status: str = ASIAN_V2_STATUS,
) -> PreemptionAnalysis:
    """Recompute the Range-preemption population across the two frozen variants.

    A candidate is "preempted to Range" when one variant routes it SWEEP and
    the other routes it RANGE (the range branch fires where a sweep branch
    otherwise would). For each such candidate we record direction alignment,
    whether the range trade runs with or against the authority (pullback
    direction), and whether it precedes a later better-ALIGNED SWEEP/TREND
    candidate in the same population (suppression). Read-only: V2 is not
    altered by this analysis.
    """
    v1_by_id = {r.candidate_id: r for r in runs_v1}
    overlay_by_id = {c.candidate_id: c for c in overlay.candidates}
    ordered = [r.candidate_id for r in runs_v1]

    records: list[PreemptionRecord] = []
    for run_v2 in runs_v2:
        cid = run_v2.candidate_id
        run_v1 = v1_by_id.get(cid)
        if run_v1 is None:
            continue
        b1, b2 = _branch_of(run_v1), _branch_of(run_v2)
        if b1 is None or b2 is None:
            continue
        preempted = {b1, b2} == {"SWEEP", "RANGE"}
        joined = overlay_by_id.get(cid)
        alignment = joined.alignment if joined else SetupAlignment.NEUTRAL
        if joined is None or joined.authority == Direction.NEUTRAL or joined.trade_direction == "NONE":
            pullback = "UNKNOWN"
        elif alignment == SetupAlignment.ALIGNED:
            pullback = "WITH_AUTHORITY"
        else:
            pullback = "AGAINST_AUTHORITY"
        # Suppression: this candidate lands on RANGE in either variant while a
        # LATER candidate in the same ordered population is an ALIGNED
        # SWEEP/TREND candidate.
        suppresses = False
        if "RANGE" in (b1, b2):
            position = ordered.index(cid)
            for later_id in ordered[position + 1:]:
                later = overlay_by_id.get(later_id)
                if later and later.branch in ("SWEEP", "TREND") and later.alignment == SetupAlignment.ALIGNED:
                    suppresses = alignment != SetupAlignment.ALIGNED
                    break
        if preempted or "RANGE" in (b1, b2):
            records.append(PreemptionRecord(
                candidate_id=cid, branch_under_v1=b1 or "NONE", branch_under_v2=b2 or "NONE",
                preempted_to_range=preempted, alignment=alignment,
                pullback_direction=pullback, suppresses_later_aligned=suppresses))

    preempted = [r for r in records if r.preempted_to_range]
    finding = (
        f"{len(preempted)} candidate(s) flip between SWEEP and RANGE across the frozen "
        f"variants; of these {sum(1 for r in preempted if r.alignment == SetupAlignment.ALIGNED)} "
        f"align with direction authority and "
        f"{sum(1 for r in preempted if r.suppresses_later_aligned)} suppress a later "
        f"better-aligned SWEEP/TREND candidate. Proxy population — no claim is made "
        f"about ST_ASIAN_SESSION_BRANCH_V2 itself."
    )
    return PreemptionAnalysis(
        status=status, records=tuple(records),
        range_population_n=len(records), preempted_n=len(preempted),
        preempted_aligned_n=sum(1 for r in preempted if r.alignment == SetupAlignment.ALIGNED),
        preempted_counter_n=sum(1 for r in preempted if r.alignment == SetupAlignment.COUNTER_DIRECTION),
        preempted_neutral_n=sum(1 for r in preempted if r.alignment == SetupAlignment.NEUTRAL),
        suppressing_n=sum(1 for r in preempted if r.suppresses_later_aligned),
        finding=finding,
        evidence_sufficiency="INSUFFICIENT_EVIDENCE_FOR_ASIAN_V2 (proxy synthetic population)")
