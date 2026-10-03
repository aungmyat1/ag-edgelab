from __future__ import annotations

"""Per-cell economic metrics for the SESSION_TRADE_V2 campaign.

Reuses EdgeLab's ``compute_performance`` (R-based) and
``bootstrap_expectancy_ci``.  A cell is one (branch, symbol, session) tuple.
All R statistics are computed over CLOSED trades only; OPEN_AT_END trades are
censored (reported separately, never silently merged).

First-pass DEV screen thresholds reuse the frozen EdgeLab canonical policy
constants (``CANONICAL_POLICY_V1``: min 30 trades, expectancy > 0, PF > 1.0).
No new thresholds were invented for this campaign.
"""

import math
from dataclasses import dataclass, field
from datetime import timedelta

from ag_edgelab.campaigns.session_trade_v2.replay import CampaignTrade
from ag_edgelab.statistics.bootstrap import bootstrap_expectancy_ci
from ag_edgelab.statistics.performance import compute_performance

#: EdgeLab canonical verification policy constants reused for the DEV screen.
MIN_TRADES = 30
MIN_EXPECTANCY_R = 0.0
MIN_PROFIT_FACTOR = 1.0

CELL_STATUSES = (
    "SURVIVES_DEV_SCREEN",
    "FAILS_DEV_SCREEN",
    "INSUFFICIENT_SAMPLE",
    "FRICTION_UNQUALIFIED",
    "DATA_BLOCKED",
)

BE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class CellInput:
    branch: str
    symbol: str
    session: str
    trades: tuple[CampaignTrade, ...]          # all replayed proposals of this branch cell
    friction_r_by_trade: dict[str, float]
    sessions_evaluated: int = 0
    data_invalid_sessions: int = 0
    no_trade_reasons: dict[str, int] = field(default_factory=dict)
    weeks: float = 0.0


@dataclass(frozen=True)
class CellMetrics:
    branch: str
    symbol: str
    session: str
    status: str
    authoritative: bool
    status_detail: str
    sessions_evaluated: int
    data_invalid_sessions: int
    signals: int
    filled: int
    unfilled: int
    expired: int
    open_at_end: int
    closed: int
    wins: int
    losses: int
    breakeven_outcomes: int
    gross_r: float
    net_r: float
    gross_expectancy_r: float | None
    net_expectancy_r: float | None
    gross_profit_factor: float | None
    net_profit_factor: float | None
    win_rate: float | None
    average_win_r: float | None
    average_loss_r: float | None
    max_drawdown_r: float
    max_losing_streak: int
    tp1_4r_hit_rate: float | None
    runner_5r_hit_rate: float | None
    runner_breakeven_rate: float | None
    average_holding_hours: float | None
    trades_per_week: float | None
    cost_per_trade_r: float | None
    friction_drag_r: float
    same_bar_ambiguity_count: int
    no_trade_reasons: dict[str, int]
    net_expectancy_ci_low: float | None = None
    net_expectancy_ci_high: float | None = None
    proxy_label: str | None = None

    def as_row(self) -> dict:
        return {
            "branch": self.branch,
            "symbol": self.symbol,
            "session": self.session,
            "status": self.status,
            "authoritative": self.authoritative,
            "proxy_label": self.proxy_label,
            "status_detail": self.status_detail,
            "sessions_evaluated": self.sessions_evaluated,
            "data_invalid_sessions": self.data_invalid_sessions,
            "signals": self.signals,
            "filled": self.filled,
            "unfilled": self.unfilled,
            "expired": self.expired,
            "open_at_end": self.open_at_end,
            "closed": self.closed,
            "wins": self.wins,
            "losses": self.losses,
            "breakeven_outcomes": self.breakeven_outcomes,
            "gross_r": round(self.gross_r, 4),
            "net_r": round(self.net_r, 4),
            "gross_expectancy_r": None if self.gross_expectancy_r is None else round(self.gross_expectancy_r, 4),
            "net_expectancy_r": None if self.net_expectancy_r is None else round(self.net_expectancy_r, 4),
            "gross_profit_factor": None if self.gross_profit_factor is None else round(self.gross_profit_factor, 4),
            "net_profit_factor": None if self.net_profit_factor is None else round(self.net_profit_factor, 4),
            "win_rate": None if self.win_rate is None else round(self.win_rate, 4),
            "average_win_r": None if self.average_win_r is None else round(self.average_win_r, 4),
            "average_loss_r": None if self.average_loss_r is None else round(self.average_loss_r, 4),
            "max_drawdown_r": round(self.max_drawdown_r, 4),
            "max_losing_streak": self.max_losing_streak,
            "tp1_4r_hit_rate": None if self.tp1_4r_hit_rate is None else round(self.tp1_4r_hit_rate, 4),
            "runner_5r_hit_rate": None if self.runner_5r_hit_rate is None else round(self.runner_5r_hit_rate, 4),
            "runner_breakeven_rate": None if self.runner_breakeven_rate is None else round(self.runner_breakeven_rate, 4),
            "average_holding_hours": None if self.average_holding_hours is None else round(self.average_holding_hours, 2),
            "trades_per_week": None if self.trades_per_week is None else round(self.trades_per_week, 3),
            "cost_per_trade_r": None if self.cost_per_trade_r is None else round(self.cost_per_trade_r, 4),
            "friction_drag_r": round(self.friction_drag_r, 4),
            "same_bar_ambiguity_count": self.same_bar_ambiguity_count,
            "no_trade_reasons": dict(self.no_trade_reasons),
            "net_expectancy_ci_low": None if self.net_expectancy_ci_low is None else round(self.net_expectancy_ci_low, 4),
            "net_expectancy_ci_high": None if self.net_expectancy_ci_high is None else round(self.net_expectancy_ci_high, 4),
        }


def _closed_net_rs(trades: tuple[CampaignTrade, ...], friction: dict[str, float]) -> list[float]:
    return [t.gross_r - friction.get(t.trade_id, 0.0) for t in trades if t.closed and t.gross_r is not None]


def compute_cell_metrics(cell: CellInput) -> CellMetrics:
    trades = cell.trades
    filled = [t for t in trades if t.filled]
    closed = [t for t in trades if t.closed]
    open_at_end = [t for t in trades if t.status == "FILLED_OPEN_AT_END"]
    unfilled = [t for t in trades if t.status == "UNFILLED"]
    expired = [t for t in trades if t.status == "EXPIRED"]

    friction = cell.friction_r_by_trade
    net_rs = _closed_net_rs(trades, friction)
    gross_rs = [t.gross_r for t in closed if t.gross_r is not None]

    gross_perf = compute_performance(gross_rs)
    net_perf = compute_performance(net_rs)

    wins = sum(1 for r in net_rs if r > BE_TOLERANCE)
    losses = sum(1 for r in net_rs if r < -BE_TOLERANCE)
    breakeven = sum(1 for r in net_rs if abs(r) <= BE_TOLERANCE)

    total_friction = sum(friction.get(t.trade_id, 0.0) for t in filled)
    holding_hours = None
    holds = [t.holding_seconds for t in closed if t.holding_seconds is not None]
    if holds:
        holding_hours = (sum(holds) / len(holds)) / 3600.0

    tp1_rate = (sum(1 for t in closed if t.tp1_4r_hit) / len(closed)) if closed else None
    runner_5r_rate = (sum(1 for t in closed if t.runner_5r_hit) / len(closed)) if closed else None
    runner_be_rate = (sum(1 for t in closed if t.runner_breakeven) / len(closed)) if closed else None

    is_proxy = cell.branch == "C_TREND_EXPANSION"
    authoritative = not is_proxy

    if cell.sessions_evaluated == 0 or (
        cell.sessions_evaluated > 0 and cell.data_invalid_sessions == cell.sessions_evaluated
    ):
        status = "DATA_BLOCKED"
        detail = "no evaluable sessions with complete reference+trade windows"
    elif len(closed) < MIN_TRADES:
        status = "INSUFFICIENT_SAMPLE"
        detail = f"{len(closed)} closed trades < {MIN_TRADES} (EdgeLab canonical minimum)"
    elif (
        net_perf.expectancy_r is not None
        and net_perf.expectancy_r > MIN_EXPECTANCY_R
        and net_perf.profit_factor is not None
        and net_perf.profit_factor > MIN_PROFIT_FACTOR
    ):
        status = "SURVIVES_DEV_SCREEN"
        detail = "net expectancy > 0 and net PF > 1.0 at the canonical thresholds"
    else:
        status = "FAILS_DEV_SCREEN"
        detail = "net expectancy <= 0 or net PF <= 1.0 at the canonical thresholds"

    ci = bootstrap_expectancy_ci(net_rs, samples=5000, seed=0) if net_rs else None

    return CellMetrics(
        branch=cell.branch,
        symbol=cell.symbol,
        session=cell.session,
        status=status,
        authoritative=authoritative,
        status_detail=detail,
        sessions_evaluated=cell.sessions_evaluated,
        data_invalid_sessions=cell.data_invalid_sessions,
        signals=len(trades),
        filled=len(filled),
        unfilled=len(unfilled),
        expired=len(expired),
        open_at_end=len(open_at_end),
        closed=len(closed),
        wins=wins,
        losses=losses,
        breakeven_outcomes=breakeven,
        gross_r=gross_perf.total_r,
        net_r=net_perf.total_r,
        gross_expectancy_r=gross_perf.expectancy_r,
        net_expectancy_r=net_perf.expectancy_r,
        gross_profit_factor=gross_perf.profit_factor,
        net_profit_factor=net_perf.profit_factor,
        win_rate=net_perf.win_rate,
        average_win_r=(sum(r for r in net_rs if r > 0) / wins) if wins else None,
        average_loss_r=(sum(r for r in net_rs if r < 0) / losses) if losses else None,
        max_drawdown_r=net_perf.max_drawdown_r,
        max_losing_streak=net_perf.max_consecutive_losses,
        tp1_4r_hit_rate=tp1_rate,
        runner_5r_hit_rate=runner_5r_rate,
        runner_breakeven_rate=runner_be_rate,
        average_holding_hours=holding_hours,
        trades_per_week=(len(filled) / cell.weeks) if cell.weeks > 0 else None,
        cost_per_trade_r=(total_friction / len(filled)) if filled else None,
        friction_drag_r=total_friction,
        same_bar_ambiguity_count=sum(t.same_bar_ambiguities for t in trades),
        no_trade_reasons=dict(cell.no_trade_reasons),
        net_expectancy_ci_low=ci.low if ci else None,
        net_expectancy_ci_high=ci.high if ci else None,
        proxy_label="C_FIXED_EXIT_PROXY" if is_proxy else None,
    )


def compute_aggregate_metrics(
    trades: tuple[CampaignTrade, ...],
    friction_r_by_trade: dict[str, float],
    label: str,
    weeks: float,
) -> dict:
    """Pool the actual per-trade streams of several cells into one aggregate.

    Aggregates never hide sub-cell results: callers must keep the per-cell
    metrics alongside (the report always shows both).
    """
    filled = [t for t in trades if t.filled]
    closed = [t for t in trades if t.closed]
    net_rs = _closed_net_rs(trades, friction_r_by_trade)
    gross_rs = [t.gross_r for t in closed if t.gross_r is not None]
    net_perf = compute_performance(net_rs)
    gross_perf = compute_performance(gross_rs)
    total_friction = sum(friction_r_by_trade.get(t.trade_id, 0.0) for t in filled)
    wins = sum(1 for r in net_rs if r > BE_TOLERANCE)
    losses = sum(1 for r in net_rs if r < -BE_TOLERANCE)
    holds = [t.holding_seconds for t in closed if t.holding_seconds is not None]
    ci = bootstrap_expectancy_ci(net_rs, samples=5000, seed=0) if net_rs else None
    return {
        "label": label,
        "signals": len(trades),
        "filled": len(filled),
        "unfilled": sum(1 for t in trades if t.status == "UNFILLED"),
        "expired": sum(1 for t in trades if t.status == "EXPIRED"),
        "open_at_end": sum(1 for t in trades if t.status == "FILLED_OPEN_AT_END"),
        "closed": len(closed),
        "wins": wins,
        "losses": losses,
        "breakeven_outcomes": sum(1 for r in net_rs if abs(r) <= BE_TOLERANCE),
        "gross_r": round(gross_perf.total_r, 4),
        "net_r": round(net_perf.total_r, 4),
        "gross_expectancy_r": None if gross_perf.expectancy_r is None else round(gross_perf.expectancy_r, 4),
        "net_expectancy_r": None if net_perf.expectancy_r is None else round(net_perf.expectancy_r, 4),
        "gross_profit_factor": None if gross_perf.profit_factor is None else round(gross_perf.profit_factor, 4),
        "net_profit_factor": None if net_perf.profit_factor is None else round(net_perf.profit_factor, 4),
        "win_rate": None if net_perf.win_rate is None else round(net_perf.win_rate, 4),
        "max_drawdown_r": round(net_perf.max_drawdown_r, 4),
        "max_losing_streak": net_perf.max_consecutive_losses,
        "tp1_4r_hit_rate": (round(sum(1 for t in closed if t.tp1_4r_hit) / len(closed), 4)) if closed else None,
        "runner_5r_hit_rate": (round(sum(1 for t in closed if t.runner_5r_hit) / len(closed), 4)) if closed else None,
        "runner_breakeven_rate": (round(sum(1 for t in closed if t.runner_breakeven) / len(closed), 4)) if closed else None,
        "average_holding_hours": (round(sum(holds) / len(holds) / 3600.0, 2)) if holds else None,
        "trades_per_week": (round(len(filled) / weeks, 3)) if weeks > 0 else None,
        "cost_per_trade_r": (round(total_friction / len(filled), 4)) if filled else None,
        "friction_drag_r": round(total_friction, 4),
        "same_bar_ambiguity_count": sum(t.same_bar_ambiguities for t in trades),
        "net_expectancy_ci_low": None if ci is None or ci.low is None else round(ci.low, 4),
        "net_expectancy_ci_high": None if ci is None or ci.high is None else round(ci.high, 4),
    }
