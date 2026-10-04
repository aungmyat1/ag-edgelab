from datetime import date, datetime, timezone

import mtf_control_shift.engine as engine
import mtf_control_shift.ticket as ticket_mod
from mtf_control_shift.models import Candle, Decision, Zone
from mtf_control_shift.structure import fvg, zones

UTC = timezone.utc


def c(day, hour, o, h, l, cl):
    return Candle(datetime(2026, 10, day, hour, tzinfo=UTC), o, h, l, cl)


def test_strict_three_candle_bullish_fvg():
    xs = [c(1, 0, 10.0, 10.2, 9.8, 10.1), c(1, 1, 10.1, 10.4, 10.0, 10.3), c(1, 2, 10.5, 10.8, 10.3, 10.7)]
    assert fvg(xs, 2) == ("BULLISH", 10.2, 10.3)


def test_zone_requires_fvg_bos_and_opposite_origin_candle():
    xs = [
        c(1, 0, 10.0, 10.2, 9.8, 10.0),
        c(1, 1, 10.2, 11.0, 10.0, 10.8),
        c(1, 2, 10.8, 12.0, 10.7, 11.5),  # confirmed swing high after bars 3/4
        c(1, 3, 11.4, 11.5, 10.9, 11.1),
        c(1, 4, 11.1, 11.4, 10.8, 11.0),
        c(1, 5, 11.1, 11.3, 10.8, 10.9),  # bearish origin OB
        c(1, 6, 11.5, 11.8, 11.4, 11.7),
        c(1, 7, 11.6, 12.8, 11.4, 12.5),  # FVG vs bar 5 + close above 12
    ]
    found = zones(xs)
    demand = [z for z in found if z.kind == "DEMAND"]
    assert demand
    assert demand[-1].low == 10.8
    assert demand[-1].high == 11.3
    assert demand[-1].bos_level == 12.0


def _z(kind, low, high, hour):
    return Zone(kind, low, high, datetime(2026, 10, 3, hour, tzinfo=UTC),
                datetime(2026, 10, 3, hour, tzinfo=UTC), low + 0.1 * (high-low),
                high - 0.1 * (high-low), high if kind == "DEMAND" else low)


def test_engine_builds_deterministic_long_limit_geometry(monkeypatch):
    d1 = [c(1, 0, 1.0, 1.2, 0.9, 1.1)]
    h4 = [c(1, 4, 1.0, 1.2, 0.9, 1.1)]
    h1 = [c(3, 6, 1.0, 1.2, 0.9, 1.1)]
    m15 = [c(3, 7, 1.0, 1.2, 0.9, 1.1)]
    h4_zone = _z("DEMAND", 1.0000, 1.0100, 4)
    h1_zone = _z("DEMAND", 1.0050, 1.0150, 6)
    m15_zone = _z("DEMAND", 1.0100, 1.0200, 7)

    monkeypatch.setattr(engine, "structure_bias", lambda _: "BULLISH")
    monkeypatch.setattr(engine, "latest_fresh_zone", lambda *_: h4_zone)
    monkeypatch.setattr(engine, "zone_touched", lambda *_, **__: True)
    monkeypatch.setattr(engine, "control_shift_zones", lambda *_: (h1_zone,))
    monkeypatch.setattr(engine, "zones", lambda *_: (m15_zone,))
    monkeypatch.setattr(engine, "structural_target", lambda *args: 1.1000)

    d = engine.evaluate("EURUSD", "ASIAN_LONDON", d1, h4, h1, m15)
    assert d.status == "SIGNAL"
    assert d.direction == "LONG"
    assert d.entry_order_type == "LIMIT"
    assert round(d.entry, 6) == 1.015
    assert round(d.stop_loss, 6) == 1.009
    assert round(d.risk_distance, 6) == 0.006
    assert round(d.tp1, 6) == 1.027
    assert d.tp2 == 1.1000
    assert d.expiry_timestamp.hour == 9


def test_engine_requires_d1_h4_alignment(monkeypatch):
    d1 = [c(1, 0, 1.0, 1.2, 0.9, 1.1)]
    h4 = [c(1, 4, 1.0, 1.2, 0.9, 1.1)]
    h1 = [c(1, 6, 1.0, 1.2, 0.9, 1.1)]
    m15 = [c(1, 7, 1.0, 1.2, 0.9, 1.1)]
    monkeypatch.setattr(engine, "structure_bias", lambda xs: "BULLISH" if xs is d1 else "BEARISH")
    d = engine.evaluate("EURUSD", "ASIAN_LONDON", d1, h4, h1, m15)
    assert d.status == "NO_TRADE"
    assert d.reason_code == "HTF_BIAS_NOT_ALIGNED"


def test_engine_does_not_fallback_when_htf_target_missing(monkeypatch):
    d1 = [c(1, 0, 1.0, 1.2, 0.9, 1.1)]
    h4 = [c(1, 4, 1.0, 1.2, 0.9, 1.1)]
    h1 = [c(3, 11, 1.0, 1.2, 0.9, 1.1)]
    m15 = [c(3, 12, 1.0, 1.2, 0.9, 1.1)]
    z = _z("SUPPLY", 1.01, 1.02, 12)
    monkeypatch.setattr(engine, "structure_bias", lambda _: "BEARISH")
    monkeypatch.setattr(engine, "latest_fresh_zone", lambda *_: z)
    monkeypatch.setattr(engine, "zone_touched", lambda *_, **__: True)
    monkeypatch.setattr(engine, "control_shift_zones", lambda *_: (z,))
    monkeypatch.setattr(engine, "zones", lambda *_: (z,))
    monkeypatch.setattr(engine, "structural_target", lambda *args: None)
    d = engine.evaluate("USDJPY", "LONDON_NEWYORK", d1, h4, h1, m15)
    assert d.status == "NO_TRADE"
    assert d.reason_code == "NO_VALID_HTF_FINAL_TARGET"


def test_ticket_is_explicitly_non_executable(monkeypatch):
    now = datetime(2026, 10, 3, 7, tzinfo=UTC)
    sig = Decision(
        "ST_MTF_CONTROL_SHIFT_V1", "1.0.0", "EURUSD", "ASIAN_LONDON", "SIGNAL", "READY_RESEARCH_SHADOW",
        bias="BULLISH", direction="LONG", entry_order_type="LIMIT", entry=1.10, stop_loss=1.09,
        risk_distance=0.01, tp1=1.12, tp2=1.15, signal_timestamp=now,
        expiry_timestamp=datetime(2026, 10, 3, 9, tzinfo=UTC),
    )
    monkeypatch.setattr(ticket_mod, "evaluate", lambda *args, **kwargs: sig)
    xs = [c(1, 0, 1.0, 1.2, 0.9, 1.1)]
    t = ticket_mod.build_ticket("EURUSD", "ASIAN_LONDON", date(2026, 10, 3), xs, xs, xs, xs,
                                expected_round_trip_cost=0.001)
    assert t["decision"] == "READY"
    assert t["demo_authorized"] is False
    assert t["live_authorized"] is False
    assert t["allow_order_send"] is False
    assert t["position_size_authorized"] is False
    assert round(t["expected_cost_r"], 6) == 0.1
    assert t["targets"][0]["volume_pct"] == 0.50
    assert t["targets"][0]["type"] == "FIXED_R_2"


def test_supported_symbol_and_session_matrix_rejects_unknown():
    xs = [c(1, 0, 1.0, 1.2, 0.9, 1.1)]
    try:
        engine.evaluate("BTCUSD", "ASIAN_LONDON", xs, xs, xs, xs)
    except ValueError as exc:
        assert "unsupported symbol" in str(exc)
    else:
        raise AssertionError("unknown symbol must fail closed")
