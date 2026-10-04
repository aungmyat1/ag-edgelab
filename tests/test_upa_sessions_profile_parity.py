"""Universal price-action V0.3 — market profiles, FX sessions, crypto
session-not-applicable contract, and cross-asset structural parity."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ag_edgelab.contracts.market import MarketBar
from ag_edgelab.universal.parity import structural_parity, synthetic_structural_bars
from ag_edgelab.universal.direction import Direction, structural_direction
from ag_edgelab.universal.profile import (CRYPTO_REFERENCE_PROFILE, FX_ASIAN_SESSION_PROFILE,
                                          FX_REFERENCE_PROFILE, MarketProfile, MarketType,
                                          SessionBehavior)
from ag_edgelab.universal.report import (ConfirmationSection, EconomicsSection,
                                         FunnelDiagnosticReportV3, SESSION_CONTEXT_NOT_APPLICABLE,
                                         TargetSection, TriggerSection)
from ag_edgelab.universal.sessions import (FxSession, SESSION_DEFINITIONS, active_sessions,
                                           compute_session_snapshots, crypto_time_metadata,
                                           time_since_session_open_minutes)

Z = timezone.utc


def _sections():
    return dict(
        trigger=TriggerSection(direction={}, location={}),
        confirmation=ConfirmationSection(setup={}, entry={}),
        target=TargetSection(capability={}, natural_target={}),
        economics=EconomicsSection(authoritative=False),
    )


# ---------------------------------------------------------------------------
# Market profiles
# ---------------------------------------------------------------------------

def test_fx_profile_session_enabled():
    assert FX_REFERENCE_PROFILE.market_type == MarketType.FX
    assert FX_REFERENCE_PROFILE.session_behavior == SessionBehavior.OPTIONAL_DIAGNOSTIC
    # Asian strategy: session structure IS the strategy => REQUIRED.
    assert FX_ASIAN_SESSION_PROFILE.session_behavior == SessionBehavior.REQUIRED


def test_crypto_profile_session_not_applicable():
    assert CRYPTO_REFERENCE_PROFILE.market_type == MarketType.CRYPTO
    assert CRYPTO_REFERENCE_PROFILE.session_behavior == SessionBehavior.NOT_APPLICABLE


def test_crypto_profile_cannot_require_sessions():
    with pytest.raises(ValueError, match="must not REQUIRE"):
        MarketProfile(market_type=MarketType.CRYPTO, symbols=("BTCUSDT",),
                      base_timeframe="M5", higher_timeframes=("H4",),
                      session_behavior=SessionBehavior.REQUIRED,
                      friction_authority="X")


def test_crypto_session_absence_does_not_fail_contract():
    """Intentional non-applicability serializes as the literal NOT_APPLICABLE."""
    report = FunnelDiagnosticReportV3(
        strategy_id="CRYPTO_REF", market_type=MarketType.CRYPTO,
        session_behavior=SessionBehavior.NOT_APPLICABLE,
        session_context=SESSION_CONTEXT_NOT_APPLICABLE, **_sections())
    assert report.session_context == "NOT_APPLICABLE"
    # ...but silently-missing session evidence is rejected (never serialized
    # as absent evidence).
    with pytest.raises(ValueError, match="NOT_APPLICABLE"):
        FunnelDiagnosticReportV3(
            strategy_id="CRYPTO_REF", market_type=MarketType.CRYPTO,
            session_behavior=SessionBehavior.NOT_APPLICABLE,
            session_context={}, **_sections())


def test_fx_report_requires_structured_session_context():
    with pytest.raises(ValueError, match="structured session_context"):
        FunnelDiagnosticReportV3(
            strategy_id="FX_REF", market_type=MarketType.FX,
            session_behavior=SessionBehavior.OPTIONAL_DIAGNOSTIC,
            session_context="NOT_APPLICABLE", **_sections())


# ---------------------------------------------------------------------------
# FX session module
# ---------------------------------------------------------------------------

def test_session_definitions_are_declared_not_silent():
    for definition in SESSION_DEFINITIONS:
        assert "PREREGISTERED_UPA_V0_3" in definition.source
    assert {d.session for d in SESSION_DEFINITIONS} == set(FxSession)


def test_active_sessions_and_overlap():
    assert active_sessions(datetime(2026, 3, 2, 3, 0, tzinfo=Z)) == (FxSession.ASIAN,)
    overlap = active_sessions(datetime(2026, 3, 2, 14, 0, tzinfo=Z))
    assert set(overlap) == {FxSession.LONDON, FxSession.NEW_YORK}


def test_session_snapshot_features_and_sweep():
    bars = []
    t0 = datetime(2026, 3, 2, tzinfo=Z)
    # Day 1 Asian: range 100..110.
    for i in range(96):
        ts = t0 + timedelta(minutes=5 * i)
        bars.append(MarketBar(timestamp=ts, open=105, high=110, low=100, close=105, volume=1))
    # Day 2 Asian: sweeps day-1 low (trades 98, closes back above 100).
    for i in range(96):
        ts = t0 + timedelta(days=1, minutes=5 * i)
        low = 98.0 if i == 10 else 101.0
        bars.append(MarketBar(timestamp=ts, open=104, high=108, low=low, close=104, volume=1))
    snaps = compute_session_snapshots(tuple(bars), FxSession.ASIAN)
    assert len(snaps) == 2
    first, second = snaps
    assert first.high == 110 and first.low == 100 and first.midpoint == 105 and first.range == 10
    assert second.previous_high == 110 and second.previous_low == 100
    assert second.swept_previous_low and not second.swept_previous_high
    assert second.expansion_vs_previous == (108 - 98) / 10
    assert time_since_session_open_minutes(t0 + timedelta(hours=3), FxSession.ASIAN) == 180.0
    assert time_since_session_open_minutes(t0 + timedelta(hours=9), FxSession.ASIAN) is None


def test_crypto_time_metadata_is_diagnostic_never_gating():
    meta = crypto_time_metadata(datetime(2026, 3, 6, 14, 30, tzinfo=Z))
    assert meta == {"utc_hour": 14, "weekday": "FRIDAY",
                    "volatility_window": "UTC_08_16", "gating": "NEVER"}


# ---------------------------------------------------------------------------
# Cross-asset structural parity (mission section 20)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pattern,expected", [
    ("BULL", Direction.BULL), ("BEAR", Direction.BEAR), ("NEUTRAL", Direction.NEUTRAL)])
def test_cross_asset_structural_parity(pattern, expected):
    """H4 HH/HL must yield the same state for EURUSD and BTCUSDT geometry."""
    result = structural_parity(
        pattern, "H4",
        symbol_a="EURUSD", base_a=1.1000, scale_a=0.0010,
        symbol_b="BTCUSDT", base_b=60000.0, scale_b=500.0)
    assert result.parity
    assert result.direction_a == expected and result.direction_b == expected


def test_parity_same_bars_same_engine_object_code_path():
    """Parity comes from shared code, not duplicated engines: the exact same
    function produces both states."""
    fx = synthetic_structural_bars("BULL", 1.1000, 0.0010)
    crypto = synthetic_structural_bars("BULL", 60000.0, 500.0)
    assert structural_direction(fx, "H4").direction == structural_direction(crypto, "H4").direction
