"""SYNTHETIC fixtures for the V2.1 engine (Mission 3B-A).

Every bar here is hand-made. No market corpus is read by this module, and the
policy it exports is labelled SYNTHETIC_FIXTURE_ONLY so the data authorization
gate refuses it against a real partition.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Sequence

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.strategies import asian_liquidity_displacement_v2_1 as V
from ag_edgelab.strategies import v2_1_engine as E

UTC = timezone.utc
DAY = "2016-03-01"
T0 = datetime(2016, 3, 1, 7, 0, tzinfo=UTC)
SYMBOL = "USDJPY"
REF_HIGH, REF_LOW = 101.0, 99.0


def bar(i: int, o: float, h: float, lo: float, c: float) -> MarketBar:
    return MarketBar(timestamp=T0 + timedelta(minutes=5 * i),
                     open=o, high=h, low=lo, close=c, volume=1.0)


# ---------------------------------------------------------------------------
# The SYNTHETIC policy. It declares a reading for every open contract
# question purely so fixtures can run; it carries no research authority.
# ---------------------------------------------------------------------------

def _enumerate(*_a, **_k):
    return ()


def _context_eligible(opp: E.Opportunity) -> tuple[bool, str]:
    if not opp.bars:
        return False, "CONTEXT_NO_ENTRY_WINDOW_BARS"
    return True, "PASS"


def _location_eligible(opp: E.Opportunity) -> tuple[bool, str]:
    if opp.reference_range <= 0:
        return False, "LOCATION_DEGENERATE_REFERENCE_RANGE"
    return True, "PASS"


def _select_initial_branch(opp: E.Opportunity) -> str:
    """SYNTHETIC reading: the first interaction bar's close picks the branch."""
    for b in opp.bars:
        if opp.boundary == "HIGH" and b.high > opp.boundary_price:
            return (V.Branch.B.value if b.close > opp.boundary_price
                    else V.Branch.A.value)
        if opp.boundary == "LOW" and b.low < opp.boundary_price:
            return (V.Branch.B.value if b.close < opp.boundary_price
                    else V.Branch.A.value)
    return V.Branch.A.value


def _prior_day_levels(opp: E.Opportunity, *, entry_timestamp, bull):
    """SYNTHETIC: a fixed level either side, stamped before the window opens."""
    known = opp.bars[0].timestamp if opp.bars else entry_timestamp
    level = REF_HIGH + 2.0 if bull else REF_LOW - 2.0
    return [V.TargetCandidate(authority="PRIOR_DAY_HIGH_LOW", level=level,
                              known_at=known)]


def _swing_liquidity_levels(opp: E.Opportunity, *, entry_timestamp, bull):
    return []


SYNTHETIC_POLICY = E.ReplayPolicy(
    provenance=E.SYNTHETIC_PROVENANCE,
    enumerate_opportunities=_enumerate,
    context_eligible=_context_eligible,
    location_eligible=_location_eligible,
    select_initial_branch=_select_initial_branch,
    prior_day_levels=_prior_day_levels,
    swing_liquidity_levels=_swing_liquidity_levels,
    resolves_ambiguities=tuple(a["id"] for a in E.CONTRACT_AMBIGUITIES),
)


# ---------------------------------------------------------------------------
# Bar sets
# ---------------------------------------------------------------------------

def bars_a_success() -> list[MarketBar]:
    """Sweep high at 0, reclaim at 2, MSS at 4 -> bearish reversal entry."""
    return [
        bar(0, 100.9, 101.5, 100.8, 100.95),   # closes INSIDE -> branch A first
        bar(1, 100.95, 101.3, 100.9, 101.1),
        bar(2, 101.1, 101.15, 100.7, 100.8),
        bar(3, 100.8, 100.9, 100.6, 100.7),
        bar(4, 100.7, 100.75, 100.4, 100.45),
        bar(5, 100.45, 100.5, 100.2, 100.3),
    ]


def bars_b_success() -> list[MarketBar]:
    """Breakout 0, acceptance 1, retest 3, continuation 4 -> bullish entry."""
    return [
        bar(0, 100.9, 101.3, 100.85, 101.2),
        bar(1, 101.2, 101.4, 101.1, 101.35),
        bar(2, 101.35, 101.5, 101.2, 101.4),
        bar(3, 101.4, 101.45, 100.95, 101.1),
        bar(4, 101.1, 101.6, 101.05, 101.55),
        bar(5, 101.55, 101.7, 101.4, 101.6),
    ]


def bars_a_fails_then_b() -> list[MarketBar]:
    """Sweep closing INSIDE (so A is tried first), then price holds beyond the
    boundary so A never reclaims -> RECLAIM_TIMEOUT -> permitted B handover."""
    out = [bar(0, 100.9, 101.5, 100.8, 100.9)]           # A selected, sweep
    out += [bar(i, 101.2, 101.4, 101.1, 101.3)           # never closes inside
            for i in range(1, V.RECLAIM_MAX_BARS + 1)]
    nxt = len(out)
    out += [bar(nxt, 101.3, 101.35, 100.95, 101.2),      # retest exact touch
            bar(nxt + 1, 101.2, 101.9, 101.15, 101.85)]  # continuation
    return out


def bars_low_sweep_a() -> list[MarketBar]:
    """Sweep of the LOW boundary, reclaim, MSS at 4 -> bullish reversal."""
    return [
        bar(0, 99.1, 99.3, 98.8, 99.2),      # sweep low, closes inside
        bar(1, 99.2, 99.4, 99.1, 99.35),     # reclaim
        bar(2, 99.35, 99.5, 99.3, 99.45),
        bar(3, 99.45, 99.6, 99.4, 99.55),
        bar(4, 99.55, 99.9, 99.5, 99.85),    # MSS bar
        bar(5, 99.85, 99.95, 99.8, 99.9),
    ]


def bars_b_fails_then_a() -> list[MarketBar]:
    """Breakout accepted, then closes back inside -> A handover."""
    return [
        bar(0, 100.9, 101.3, 100.85, 101.2),
        bar(1, 101.2, 101.4, 101.1, 101.35),
        bar(2, 101.35, 101.5, 100.5, 100.6),   # close back inside
        bar(3, 100.6, 100.7, 100.4, 100.5),
        bar(4, 100.5, 100.55, 100.2, 100.25),
        bar(5, 100.25, 100.3, 100.0, 100.1),
    ]


def bars_no_event() -> list[MarketBar]:
    return [bar(i, 100.2, 100.4, 100.0, 100.3) for i in range(6)]


def forward_bull_target() -> list[MarketBar]:
    return [bar(10 + i, 101.6, 103.2, 101.5, 103.1) for i in range(3)]


def forward_bear_target() -> list[MarketBar]:
    return [bar(10 + i, 100.3, 100.4, 98.8, 98.9) for i in range(3)]


def forward_stop_bear() -> list[MarketBar]:
    return [bar(10 + i, 100.5, 101.9, 100.4, 101.8) for i in range(3)]


# ---------------------------------------------------------------------------
# Scenarios — the nine cases Phase 3 mandates
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    name: str
    expectation: str
    opportunities: list[E.Opportunity] = field(default_factory=list)
    mss_at: int | None = None
    continuation_at: int | None = None


def opp(bars: Sequence[MarketBar], *, boundary: str = "HIGH", seq: int = 0,
        session: str = "ASIAN_LONDON", date: str = DAY,
        forward: Sequence[MarketBar] = ()) -> E.Opportunity:
    return E.Opportunity(
        symbol=SYMBOL, trading_date=date, session=session, boundary=boundary,
        boundary_price=REF_HIGH if boundary == "HIGH" else REF_LOW,
        reference_high=REF_HIGH, reference_low=REF_LOW,
        event_sequence=seq, bars=tuple(bars), forward_bars=tuple(forward))


def build_scenarios() -> list[Scenario]:
    a_bars, b_bars = bars_a_success(), bars_b_success()
    ab = bars_a_fails_then_b()
    return [
        Scenario("A_SUCCEEDS", "branch A reaches ENTRY_AVAILABLE and locks",
                 [opp(a_bars, forward=forward_bear_target())], mss_at=4),
        Scenario("B_SUCCEEDS", "branch B reaches ENTRY_AVAILABLE and locks",
                 [opp(b_bars, forward=forward_bull_target())],
                 continuation_at=4),
        Scenario("A_FAILS_THEN_B_HANDOVER",
                 "A times out on reclaim, one permitted handover to B",
                 [opp(ab, forward=forward_bull_target())],
                 continuation_at=len(ab) - 1),
        Scenario("B_FAILS_THEN_A_HANDOVER",
                 "B rejected by close back inside, one permitted handover to A",
                 [opp(bars_b_fails_then_a(), forward=forward_bear_target())],
                 mss_at=4),
        Scenario("A_SUCCEEDS_THEN_B_LATER_APPEARS",
                 "second event on a locked tuple is DUPLICATE_SUPPRESSED",
                 [opp(a_bars, seq=0, forward=forward_bear_target()),
                  opp(b_bars, seq=1, forward=forward_bull_target())],
                 mss_at=4, continuation_at=4),
        Scenario("B_SUCCEEDS_THEN_A_LATER_APPEARS",
                 "second event on a locked tuple is DUPLICATE_SUPPRESSED",
                 [opp(b_bars, seq=0, forward=forward_bull_target()),
                  opp(a_bars, seq=1, forward=forward_bear_target())],
                 mss_at=4, continuation_at=4),
        Scenario("DUPLICATE_REPEATED_CANDLE",
                 "identical event replayed twice yields one accepted trade",
                 [opp(a_bars, seq=0, forward=forward_bear_target()),
                  opp(a_bars, seq=0, forward=forward_bear_target())],
                 mss_at=4),
        Scenario("DUPLICATE_BOUNDARY_TOUCH",
                 "the opposite boundary is a different lock key, not a duplicate",
                 [opp(a_bars, boundary="HIGH", seq=0, forward=forward_bear_target()),
                  opp(bars_low_sweep_a(), boundary="LOW", seq=0,
                      forward=forward_bull_target())],
                 mss_at=4),
        Scenario("SESSION_ROLLOVER",
                 "a new session on the same day is a fresh lock key",
                 [opp(a_bars, session="ASIAN_LONDON", forward=forward_bear_target()),
                  opp(b_bars, session="LONDON_NEWYORK", forward=forward_bull_target())],
                 mss_at=4, continuation_at=4),
    ]


def run_synthetic_engine(scenario: Scenario) -> tuple[E.V21Engine, list]:
    """Drive one scenario end to end with the synthetic policy."""
    engine = E.V21Engine(SYNTHETIC_POLICY, allow_synthetic=True)
    mss = (lambda i: i == scenario.mss_at) if scenario.mss_at is not None else (lambda i: False)
    cont = ((lambda i: i == scenario.continuation_at)
            if scenario.continuation_at is not None else (lambda i: False))
    records = [engine.evaluate(o, mss_confirmed_at=mss, continuation_confirmed_at=cont)
               for o in scenario.opportunities]
    return engine, records
