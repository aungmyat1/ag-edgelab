"""Prove a source's timezone frame instead of believing its documentation.

STOP condition 16 of DATA_AUTHORITY_R1 is "timezone authority ambiguous".
A provider README asserting "UTC" is not authority; it is a claim. This
module turns the claim into a falsifiable measurement using a property of
the FX market that no provider controls:

    The spot FX week opens at 17:00 America/New_York on Sunday and closes
    at 17:00 America/New_York on Friday. America/New_York observes US DST.

Consequences, and how they discriminate:

* If the source clock is **UTC** (or any fixed offset), the observed weekly
  open hour MOVES across the year — 22:00 in EST, 21:00 in EDT — and the
  move happens exactly on the US DST transition dates.
* If the source clock is **exchange-local**, the observed weekly open hour
  is CONSTANT at 17:00 all year.
* If the source clock is a fixed offset other than UTC, the opens are still
  split 2-way but land on different hours.

The venue boundary is itself a convention (spot FX uses New York, CME
metals use Chicago), so the identification is JOINT: every
(offset, session contract) pair is scored and a unique winner is required.
A symbol whose data fits no declared contract is reported AMBIGUOUS rather
than forced onto one — see :mod:`ag_edgelab.data.authority.session`.

``prove_fixed_offset_frame`` returns the unique frame or reports
``AMBIGUOUS``; it never defaults to UTC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence
from ag_edgelab.data.authority.session import (
    CANDIDATE_SESSION_CONTRACTS, SessionContract,
)

#: Candidate whole-hour frames considered during identification.
CANDIDATE_OFFSET_HOURS: tuple[int, ...] = tuple(range(-12, 15))

PROVEN = "PROVEN"
AMBIGUOUS = "AMBIGUOUS"
REFUTED = "REFUTED"


@dataclass(frozen=True)
class FrameScore:
    offset_hours: int
    session_contract_id: str
    weeks_matching_boundary: int
    weeks_total: int

    @property
    def fraction(self) -> float:
        return self.weeks_matching_boundary / self.weeks_total if self.weeks_total else 0.0

    def as_dict(self) -> dict:
        return {
            "offset_hours": self.offset_hours,
            "session_contract": self.session_contract_id,
            "weeks_matching": self.weeks_matching_boundary,
            "weeks_total": self.weeks_total,
            "fraction": round(self.fraction, 6),
        }


@dataclass(frozen=True)
class TimezoneProof:
    """Result of jointly identifying a source clock frame and venue session."""

    status: str
    offset_hours: int | None
    session_contract_id: str | None
    source_clock_open_hours: tuple[int, ...]
    follows_venue_dst_in_source_clock: bool
    weeks_examined: int
    match_fraction: float
    runner_up_fraction: float
    admissible_offsets: tuple[int, ...] = field(default_factory=tuple)
    scores: tuple[FrameScore, ...] = field(default_factory=tuple)
    detail: str = ""

    @property
    def is_utc(self) -> bool:
        return self.status == PROVEN and self.offset_hours == 0

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "identified_offset_hours": self.offset_hours,
            "identified_frame": (
                None if self.offset_hours is None
                else ("UTC" if self.offset_hours == 0 else f"UTC{self.offset_hours:+d}")
            ),
            "identified_session_contract": self.session_contract_id,
            "source_clock_weekly_open_hours": list(self.source_clock_open_hours),
            "source_clock_follows_venue_dst": self.follows_venue_dst_in_source_clock,
            "admissible_offsets": list(self.admissible_offsets),
            "weeks_examined": self.weeks_examined,
            "best_match_fraction": round(self.match_fraction, 6),
            "runner_up_match_fraction": round(self.runner_up_fraction, 6),
            "method": (
                "JOINT_FRAME_AND_SESSION_IDENTIFICATION: every (whole-hour UTC "
                "offset, declared venue session contract) pair is scored by how "
                "many observed weekly first-observations land on that venue's "
                "declared weekly open; a unique winner is required."
            ),
            "top_scores": [s.as_dict() for s in self.scores],
            "detail": self.detail,
        }


#: A trading week is separated from the next by the weekend. FX weekends
#: are ~48h; the longest in-week holiday halts observed in this corpus are
#: ~25h. 36h therefore splits weekends without splitting holidays.
WEEK_SEPARATION_HOURS = 36


def weekly_first_observations(
    naive_source_times: Iterable[datetime],
    *,
    separation_hours: int = WEEK_SEPARATION_HOURS,
) -> tuple[datetime, ...]:
    """First observation of each trading week, in the source's own clock.

    Weeks are segmented by the WEEKEND GAP rather than by a calendar rule.
    A calendar rule would have to assume where the week boundary falls in
    the source's clock, which is precisely the unknown this module is
    trying to identify — on a clock offset far enough from UTC, a
    Saturday-start calendar rule silently picks up the previous week's
    closing observation and corrupts the proof.

    Gap segmentation has no such assumption: whatever the clock, the
    market is shut for about two days and then reopens.
    """
    stamps = sorted(naive_source_times)
    if not stamps:
        return ()
    opens = [stamps[0]]
    threshold = timedelta(hours=separation_hours)
    for previous, current in zip(stamps, stamps[1:]):
        if current - previous >= threshold:
            opens.append(current)
    return tuple(opens)


def _score_frame(opens: Sequence[datetime], offset_hours: int,
                 contract: SessionContract) -> int:
    tz = timezone(timedelta(hours=offset_hours))
    venue = contract.tz
    hits = 0
    for naive in opens:
        local = naive.replace(tzinfo=tz).astimezone(venue)
        # The weekly open is the first observation AT OR AFTER the declared
        # boundary; allow it to land anywhere inside the opening hour.
        if local.weekday() == contract.open_weekday and local.hour == contract.open_hour:
            hits += 1
    return hits


def prove_fixed_offset_frame(
    naive_source_times: Iterable[datetime],
    *,
    contracts: Sequence[SessionContract] = CANDIDATE_SESSION_CONTRACTS,
    min_weeks: int = 20,
    min_match_fraction: float = 0.90,
    min_margin: float = 0.25,
) -> TimezoneProof:
    """Jointly identify the source clock offset and the venue session.

    ``naive_source_times`` are timestamps exactly as the provider wrote
    them (tzinfo is ignored/stripped). The result is PROVEN only when one
    (offset, contract) pair explains at least ``min_match_fraction`` of
    weekly opens AND beats every pair carrying a DIFFERENT offset by
    ``min_margin``. Ties between contracts that agree on the offset do not
    block the proof: the clock frame is still unambiguous.
    """
    stamps = [ts.replace(tzinfo=None) for ts in naive_source_times]
    opens = weekly_first_observations(stamps)
    weeks = len(opens)
    open_hours = tuple(sorted({o.hour for o in opens}))

    if weeks < min_weeks:
        return TimezoneProof(
            status=AMBIGUOUS, offset_hours=None, session_contract_id=None,
            source_clock_open_hours=open_hours,
            follows_venue_dst_in_source_clock=False, weeks_examined=weeks,
            match_fraction=0.0, runner_up_fraction=0.0,
            detail=f"only {weeks} trading weeks observed; need >= {min_weeks} "
                   "to span a DST transition and identify the frame")

    scores = tuple(
        FrameScore(offset_hours=off, session_contract_id=contract.contract_id,
                   weeks_matching_boundary=_score_frame(opens, off, contract),
                   weeks_total=weeks)
        for off in CANDIDATE_OFFSET_HOURS
        for contract in contracts
    )
    ranked = sorted(scores,
                    key=lambda s: (-s.weeks_matching_boundary, abs(s.offset_hours),
                                   s.offset_hours, s.session_contract_id))
    best = ranked[0]
    # The clock frame is what matters; only a rival OFFSET can make it ambiguous.
    rival = next((s for s in ranked[1:] if s.offset_hours != best.offset_hours), None)
    rival_fraction = rival.fraction if rival else 0.0

    # A clock that itself followed the venue DST would hold the open hour fixed.
    follows_venue_dst = len(open_hours) == 1
    admissible = tuple(sorted({
        sc.offset_hours for sc in scores if sc.fraction >= min_match_fraction}))
    # Keep every competitive frame so the corpus-level resolver can compare
    # contracts at the winning offset, not just the global top few.
    kept = [sc for sc in ranked if sc.fraction >= min(min_match_fraction, 0.5)]
    ranked = (kept or ranked[:5])[:16]

    if best.fraction < min_match_fraction:
        return TimezoneProof(
            status=REFUTED, offset_hours=None, session_contract_id=None,
            source_clock_open_hours=open_hours,
            follows_venue_dst_in_source_clock=follows_venue_dst,
            weeks_examined=weeks, match_fraction=best.fraction,
            runner_up_fraction=rival_fraction, admissible_offsets=admissible,
            scores=tuple(ranked),
            detail="no (whole-hour offset, declared session contract) pair "
                   "explains the observed weekly opens — the source clock is "
                   "not a fixed-offset frame, or the instrument's venue session "
                   "is not among the declared contracts; "
                   "TIMEZONE_AUTHORITY_AMBIGUOUS")

    if best.fraction - rival_fraction < min_margin:
        return TimezoneProof(
            status=AMBIGUOUS, offset_hours=None, session_contract_id=None,
            source_clock_open_hours=open_hours,
            follows_venue_dst_in_source_clock=follows_venue_dst,
            weeks_examined=weeks, match_fraction=best.fraction,
            runner_up_fraction=rival_fraction, admissible_offsets=admissible,
            scores=tuple(ranked),
            detail=f"offset not uniquely identified: UTC{best.offset_hours:+d} "
                   f"({best.fraction:.3f}) vs UTC{rival.offset_hours:+d} "
                   f"({rival_fraction:.3f}) — TIMEZONE_AUTHORITY_AMBIGUOUS")

    return TimezoneProof(
        status=PROVEN, offset_hours=best.offset_hours,
        session_contract_id=best.session_contract_id,
        source_clock_open_hours=open_hours,
        follows_venue_dst_in_source_clock=follows_venue_dst,
        weeks_examined=weeks, match_fraction=best.fraction,
        runner_up_fraction=rival_fraction, admissible_offsets=admissible,
        scores=tuple(ranked),
        detail=(
            f"{best.weeks_matching_boundary}/{weeks} weekly opens land on the "
            f"{best.session_contract_id} boundary under UTC{best.offset_hours:+d}; "
            f"the source-clock open hour takes values {list(open_hours)}, i.e. it "
            "MOVES with the venue's DST, which a venue-local clock could not do; "
            f"the best rival offset explains only {rival_fraction:.3f}"
        ),
    )


def dst_transition_consistency(
    naive_source_times: Iterable[datetime],
    offset_hours: int,
    contract: SessionContract,
) -> dict:
    """Diagnostic: weekly open hour under venue DST vs venue standard time.

    Shows the flip tracks the venue's DST calendar rather than occurring at
    an arbitrary point in the year. ``disjoint_as_required`` is the whole
    claim in one boolean: the two hour-sets must not intersect.
    """
    stamps = [ts.replace(tzinfo=None) for ts in naive_source_times]
    opens = weekly_first_observations(stamps)
    tz = timezone(timedelta(hours=offset_hours))
    venue = contract.tz
    rows = []
    for naive in opens:
        local = naive.replace(tzinfo=tz).astimezone(venue)
        rows.append({
            "source_clock_hour": naive.hour,
            "venue_is_dst": bool(local.dst()),
            "on_boundary": (local.weekday() == contract.open_weekday
                            and local.hour == contract.open_hour),
        })
    dst_hours = sorted({r["source_clock_hour"] for r in rows if r["venue_is_dst"]})
    std_hours = sorted({r["source_clock_hour"] for r in rows if not r["venue_is_dst"]})
    return {
        "session_contract": contract.contract_id,
        "venue_timezone": contract.venue_timezone,
        "weeks": len(rows),
        "source_clock_open_hours_when_venue_dst": dst_hours,
        "source_clock_open_hours_when_venue_standard": std_hours,
        "disjoint_as_required": bool(dst_hours) and bool(std_hours)
                                and not set(dst_hours) & set(std_hours),
        "weeks_on_declared_boundary": sum(1 for r in rows if r["on_boundary"]),
    }


# ---------------------------------------------------------------------------
# corpus-level identification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CorpusFrameProof:
    """One clock frame for a whole corpus, resolved across instruments.

    Some instruments are individually degenerate. XAUUSD is the canonical
    case: (UTC+0, CME Chicago 17:00) and (UTC+1, spot-FX New York 17:00)
    predict EXACTLY the same observations, because Chicago is one hour
    behind New York. No amount of gold data can separate them.

    The corpus can. Every instrument in this dataset is produced by one
    provider, through one converter, into one clock, so a single offset
    must explain all of them. Intersecting each instrument's ADMISSIBLE
    offsets leaves the corpus frame; the per-instrument venue session is
    then read off at that offset.
    """

    status: str
    offset_hours: int | None
    per_symbol_admissible: dict[str, tuple[int, ...]]
    resolved_session_contracts: dict[str, str]
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "corpus_offset_hours": self.offset_hours,
            "corpus_frame": (None if self.offset_hours is None else
                             "UTC" if self.offset_hours == 0
                             else f"UTC{self.offset_hours:+d}"),
            "per_symbol_admissible_offsets": {
                k: list(v) for k, v in sorted(self.per_symbol_admissible.items())},
            "resolved_session_contracts": dict(sorted(
                self.resolved_session_contracts.items())),
            "method": (
                "CORPUS_OFFSET_INTERSECTION: one provider and one converter imply "
                "one clock, so the corpus offset is the intersection of each "
                "instrument's admissible offsets. Individually degenerate "
                "instruments are resolved by instruments that are not."
            ),
            "detail": self.detail,
        }


def prove_corpus_frame(proofs: dict[str, TimezoneProof]) -> CorpusFrameProof:
    """Intersect per-symbol admissible offsets into one corpus clock frame."""
    if not proofs:
        return CorpusFrameProof(AMBIGUOUS, None, {}, {}, "no per-symbol proofs supplied")
    admissible = {sym: tuple(p.admissible_offsets) for sym, p in proofs.items()}
    common: set[int] | None = None
    for offsets in admissible.values():
        common = set(offsets) if common is None else (common & set(offsets))
    common = common or set()

    if len(common) != 1:
        return CorpusFrameProof(
            AMBIGUOUS if common else REFUTED, None, admissible, {},
            f"intersection of admissible offsets is {sorted(common)}; a unique "
            "corpus clock frame could not be established — "
            "TIMEZONE_AUTHORITY_AMBIGUOUS")

    offset = common.pop()
    contracts: dict[str, str] = {}
    for symbol, proof in proofs.items():
        at_offset = [s for s in proof.scores if s.offset_hours == offset]
        if not at_offset:
            contracts[symbol] = "UNRESOLVED"
            continue
        best = max(at_offset, key=lambda s: s.weeks_matching_boundary)
        rivals = [s for s in at_offset
                  if s.session_contract_id != best.session_contract_id]
        contracts[symbol] = (
            best.session_contract_id
            if all(best.weeks_matching_boundary > r.weeks_matching_boundary
                   for r in rivals)
            else "AMBIGUOUS_SESSION_CONTRACT")
    return CorpusFrameProof(
        PROVEN, offset, admissible, contracts,
        f"every instrument admits UTC{offset:+d} and no other offset is admitted "
        "by all of them; with the clock fixed, each instrument's venue session "
        "contract is uniquely determined")
