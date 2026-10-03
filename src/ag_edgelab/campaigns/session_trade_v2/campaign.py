from __future__ import annotations

"""Campaign orchestration: frozen candidate -> DEV/OOS economic matrices.

Pipeline per partition (DEVELOPMENT first; OOS only after the DEV result is
frozen; the sealed holdout is never readable)::

    frozen identity check
      -> per (symbol, session, trading date):
           completeness-gated window slice
           -> frozen upstream evaluate()  (A -> B -> C priority, own rules)
           -> adapter -> OrderIntent + provenance
      -> campaign replay (conservative fills, partial legs, BE, expiry)
      -> per-trade friction (frozen symbol authority)
      -> 24-cell matrix + aggregates
      -> first-pass DEV screen classification (canonical thresholds)

The strategy is never modified, tuned or re-parameterized here.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping

from ag_edgelab.campaigns.session_trade_v2 import friction as friction_mod
from ag_edgelab.campaigns.session_trade_v2.adapter import SessionEvaluation, adapt_decision, to_candles
from ag_edgelab.campaigns.session_trade_v2.dataset import (
    PARTITIONS,
    HoldoutAccessError,
    evaluable_trading_dates,
    partition_bounds,
    slice_partition,
)
from ag_edgelab.campaigns.session_trade_v2.frozen import evaluate
from ag_edgelab.campaigns.session_trade_v2.identity import verify_identity
from ag_edgelab.campaigns.session_trade_v2.metrics import (
    CellInput,
    CellMetrics,
    compute_aggregate_metrics,
    compute_cell_metrics,
)
from ag_edgelab.campaigns.session_trade_v2.replay import CampaignReplayEngine
from ag_edgelab.campaigns.session_trade_v2.windows import (
    BRANCHES,
    SESSIONS,
    SYMBOLS,
    WindowSlice,
    build_window_slice,
    session_window,
)
from ag_edgelab.contracts.market import MarketBar


@dataclass(frozen=True)
class SessionRecord:
    """One session evaluation (signal, no-trade, or data-invalid)."""

    symbol: str
    session: str
    trading_date: str
    outcome: str          # SIGNAL | NO_TRADE | DATA_INVALID
    reason: str | None
    setup: str | None
    evaluation: SessionEvaluation | None = None


@dataclass(frozen=True)
class CampaignResult:
    role: str
    identity: dict
    started_at: str
    ended_at: str
    cells: tuple[CellMetrics, ...]
    aggregates: dict
    session_records: tuple[SessionRecord, ...]
    friction_authority: dict
    partition: dict

    @property
    def cell_by_key(self) -> dict[tuple[str, str, str], CellMetrics]:
        return {(c.branch, c.symbol, c.session): c for c in self.cells}


def evaluate_window(
    window_start: datetime,
    window_end: datetime,
    symbol_bars_full: Mapping[str, tuple[MarketBar, ...]],
) -> tuple[tuple[SessionRecord, ...], tuple, dict[str, float]]:
    """Evaluate every session cycle fully contained in [window_start, window_end).

    This is the SINGLE evaluation implementation: ``run_campaign`` (partition
    runs) and the supplementary walk-forward fold windows both go through it,
    so fold statistics can never diverge from partition statistics.

    The sealed holdout is off-limits: any window intersecting it fails closed.
    """
    holdout_start, holdout_end = PARTITIONS["SEALED_HOLDOUT"]
    if window_start < holdout_end and window_end > holdout_start:
        raise HoldoutAccessError(
            "evaluate_window: window intersects the sealed holdout partition"
        )

    dates = evaluable_trading_dates((window_start, window_end))
    symbol_bars = {
        symbol: tuple(b for b in bars if window_start <= b.timestamp < window_end)
        for symbol, bars in symbol_bars_full.items()
    }

    engine = CampaignReplayEngine(symbol_bars)

    records: list[SessionRecord] = []
    pairs: list = []  # (OrderIntent, metadata) awaiting replay

    for symbol in SYMBOLS:
        bars = symbol_bars.get(symbol, ())
        for trading_date in dates:
            for session in SESSIONS:
                win = session_window(session, trading_date)
                slice_ = build_window_slice(session, trading_date, bars)
                if not slice_.valid:
                    records.append(
                        SessionRecord(symbol, session, trading_date.isoformat(),
                                      "DATA_INVALID", slice_.reason, None)
                    )
                    continue
                try:
                    decision = evaluate(
                        symbol, session,
                        to_candles(slice_.reference_bars),
                        to_candles(slice_.trade_bars),
                    )
                except ValueError as exc:
                    records.append(
                        SessionRecord(symbol, session, trading_date.isoformat(),
                                      "DATA_INVALID", f"DATA_INVALID_ENGINE_REJECT_{exc}", None)
                    )
                    continue
                evaluation = adapt_decision(symbol, win, decision, trading_date.isoformat())
                records.append(
                    SessionRecord(symbol, session, trading_date.isoformat(),
                                  evaluation.outcome, evaluation.reason, evaluation.setup,
                                  evaluation)
                )
                if evaluation.intent is not None:
                    pairs.append((evaluation.intent, evaluation.intent_metadata))

    trades = engine.execute(tuple(pairs))

    # per-trade friction (R) for every filled trade
    friction_by_trade: dict[str, float] = {}
    for t in trades:
        if t.filled and t.entry_price is not None and t.risk_distance:
            friction_by_trade[t.trade_id] = friction_mod.friction_r(
                t.instrument, t.entry_price, t.risk_distance
            )
    return tuple(records), trades, friction_by_trade


def run_campaign(
    role: str,
    symbol_bars_full: Mapping[str, tuple[MarketBar, ...]],
    run_started_at: datetime | None = None,
    run_ended_at: datetime | None = None,
    gate_cells: tuple[tuple[str, str, str], ...] = (),
) -> CampaignResult:
    """Run the full matrix for one partition role.

    The campaign slices the supplied bars to the partition itself: callers
    cannot smuggle bars from other partitions (the sealed holdout fails
    closed inside ``slice_partition``).

    ``gate_cells`` (optional, OOS runs): the frozen DEV-survivor cell keys.
    When supplied, ``aggregates['gate_pooled']`` / ``aggregates['gate_by_branch']``
    pool ONLY those cells' trades for the promotion gates, while the full
    24-cell matrix stays in the result (failing sub-cells are never hidden).
    """
    identity = verify_identity().as_dict()

    bounds = partition_bounds(role)
    dates = evaluable_trading_dates(bounds)
    weeks = (bounds[1] - bounds[0]).total_seconds() / (7 * 86400.0)

    records, trades, friction_by_trade = evaluate_window(
        bounds[0], bounds[1], symbol_bars_full
    )

    # group into the 24-cell matrix
    cells: list[CellMetrics] = []
    pooled: dict[tuple[str, str, str], list] = {}
    for branch in BRANCHES:
        for symbol in SYMBOLS:
            for session in SESSIONS:
                cell_trades = tuple(
                    t for t in trades
                    if t.setup == branch and t.instrument == symbol and t.session == session
                )
                session_records = [r for r in records if r.symbol == symbol and r.session == session]
                data_invalid = sum(1 for r in session_records if r.outcome == "DATA_INVALID")
                no_trade_reasons: dict[str, int] = {}
                for r in session_records:
                    if r.outcome == "NO_TRADE" and r.reason:
                        no_trade_reasons[r.reason] = no_trade_reasons.get(r.reason, 0) + 1
                cell_input = CellInput(
                    branch=branch,
                    symbol=symbol,
                    session=session,
                    trades=cell_trades,
                    friction_r_by_trade=friction_by_trade,
                    sessions_evaluated=len(session_records),
                    data_invalid_sessions=data_invalid,
                    no_trade_reasons=no_trade_reasons,
                    weeks=weeks,
                )
                cells.append(compute_cell_metrics(cell_input))
                pooled[(branch, symbol, session)] = cell_trades

    # aggregates over pooled per-trade streams (cells remain first-class)
    def pool(keys) -> tuple:
        out = []
        for k in keys:
            out.extend(pooled.get(k, ()))
        return tuple(out)

    all_keys = [(b, s, sess) for b in BRANCHES for s in SYMBOLS for sess in SESSIONS]
    aggregates: dict = {
        "by_branch": {
            b: compute_aggregate_metrics(
                pool([k for k in all_keys if k[0] == b]), friction_by_trade,
                f"BRANCH_{b}", weeks,
            )
            for b in BRANCHES
        },
        "by_symbol": {
            s: compute_aggregate_metrics(
                pool([k for k in all_keys if k[1] == s]), friction_by_trade,
                f"SYMBOL_{s}", weeks,
            )
            for s in SYMBOLS
        },
        "by_session": {
            sess: compute_aggregate_metrics(
                pool([k for k in all_keys if k[2] == sess]), friction_by_trade,
                f"SESSION_{sess}", weeks,
            )
            for sess in SESSIONS
        },
        "combined": compute_aggregate_metrics(pool(all_keys), friction_by_trade,
                                              "COMBINED", weeks),
    }
    if gate_cells:
        gate = [tuple(k) for k in gate_cells]
        aggregates["gate_cells"] = [list(k) for k in gate]
        aggregates["gate_pooled"] = compute_aggregate_metrics(
            pool(gate), friction_by_trade, "GATE_POOLED", weeks
        )
        aggregates["gate_by_branch"] = {
            b: compute_aggregate_metrics(
                pool([k for k in gate if k[0] == b]), friction_by_trade,
                f"GATE_{b}", weeks,
            )
            for b in {k[0] for k in gate}
        }

    friction_authority = {
        sym: {
            "spread_rt": f.spread_rt,
            "commission_usd_rt": f.commission_usd_rt,
            "slippage_rt": f.slippage_rt,
            "evidence": f.evidence,
        }
        for sym, f in friction_mod.SYMBOL_FRICTION.items()
    }

    return CampaignResult(
        role=role,
        identity=identity,
        started_at=run_started_at.isoformat() if run_started_at else "",
        ended_at=run_ended_at.isoformat() if run_ended_at else "",
        cells=tuple(cells),
        aggregates=aggregates,
        session_records=tuple(records),
        friction_authority=friction_authority,
        partition={
            "role": role,
            "start": bounds[0].isoformat(),
            "end": bounds[1].isoformat(),
            "trading_dates": len(dates),
            "first_date": dates[0].isoformat() if dates else None,
            "last_date": dates[-1].isoformat() if dates else None,
            "defined_partitions": {k: (v[0].isoformat(), v[1].isoformat()) for k, v in PARTITIONS.items()},
        },
    )
