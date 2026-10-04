from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Sequence

from .engine import evaluate
from .models import Candle, Zone


def _zone(z: Zone | None) -> dict[str, Any] | None:
    if z is None:
        return None
    return {
        "kind": z.kind,
        "low": z.low,
        "high": z.high,
        "mid": z.midpoint,
        "origin_time": z.origin_time.isoformat(),
        "created_time": z.created_time.isoformat(),
        "fvg": {"low": z.fvg_low, "high": z.fvg_high},
        "bos_level": z.bos_level,
    }


def build_ticket(
    symbol: str,
    cycle: str,
    session_date: date,
    d1: Sequence[Candle],
    h4: Sequence[Candle],
    h1: Sequence[Candle],
    m15: Sequence[Candle],
    *,
    data_source: str = "MT5_VT_MARKETS_DEMO",
    evaluated_at: datetime | None = None,
    expected_round_trip_cost: float | None = None,
) -> Dict[str, Any]:
    """Build a non-executable research ticket from the frozen strategy decision."""
    evaluated_at = evaluated_at or datetime.now(timezone.utc)
    d = evaluate(symbol, cycle, d1, h4, h1, m15)
    ticket: Dict[str, Any] = {
        "label": "RESEARCH SHADOW TICKET -- NOT A BROKER ORDER",
        "strategy_id": d.strategy_id,
        "strategy_version": d.strategy_version,
        "symbol": symbol,
        "cycle": cycle,
        "session_date": session_date.isoformat(),
        "data_source": data_source,
        "evaluated_at": evaluated_at.astimezone(timezone.utc).isoformat(),
        "delivery_mode": "ARCHIVE_ONLY",
        "execution_authority": "NONE",
        "demo_authorized": False,
        "live_authorized": False,
        "allow_order_send": False,
        "position_size_authorized": False,
        "decision": "READY" if d.status == "SIGNAL" else d.status,
        "reason_code": d.reason_code,
        "bias": d.bias,
        "false_shift_class": d.false_shift_class,
        "zones": {
            "h4_poi": _zone(d.h4_zone),
            "h1_control_shift": _zone(d.h1_shift_zone),
            "m15_entry": _zone(d.m15_entry_zone),
        },
    }
    if d.status == "SIGNAL":
        cost_r = None
        if expected_round_trip_cost is not None and d.risk_distance:
            cost_r = expected_round_trip_cost / d.risk_distance
        ticket.update({
            "direction": d.direction,
            "entry_order_type": d.entry_order_type,
            "entry": d.entry,
            "stop_loss": d.stop_loss,
            "risk_distance": d.risk_distance,
            "risk_per_trade_pct_intent": 0.5,
            "position_size": "NOT_CALCULATED_RESEARCH_SHADOW",
            "targets": [
                {"leg": 1, "volume_pct": 0.50, "type": "FIXED_R_2", "price": d.tp1,
                 "action_on_fill": "MOVE_RUNNER_TO_BREAKEVEN"},
                {"leg": 2, "volume_pct": 0.50, "type": "HTF_STRUCTURAL_TARGET", "price": d.tp2},
            ],
            "signal_timestamp": d.signal_timestamp.isoformat() if d.signal_timestamp else None,
            "expiry_timestamp": d.expiry_timestamp.isoformat() if d.expiry_timestamp else None,
            "expected_round_trip_cost": expected_round_trip_cost,
            "expected_cost_r": cost_r,
            "friction_status": "EVALUATED" if cost_r is not None else "NOT_EVALUATED",
            "no_overnight": True,
        })
    return ticket
