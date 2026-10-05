"""FRICTION_AUTHORITY_R1 — venue friction authority regressions.

Everything here defends one of two properties: cost arithmetic is right,
or missing evidence stays missing. The second is the one that actually
protects the research, because a friction bug that silently zeroes a
component does not crash — it just makes every strategy look profitable.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ag_edgelab.friction.authority import (
    AccountClass, AuthorityStatus, CommissionMode, CommissionSpec,
    DEFAULT_SLIPPAGE_REQUIREMENT, ExitKind, ExitLeg, FRICTION_AUTHORITY_ID,
    FrictionAuthorityContract, FrictionAuthorityIncomplete,
    FrictionComponentMissing, FrictionRegime, HISTORICAL_FRICTION_LIMITATION,
    HistoricalCostPolicy, PipConvention, PREREGISTERED_SCENARIOS,
    QuoteDefect, ScenarioContract, ScenarioName, ScenarioRule, Session, Side,
    SlippageAuthority, SlippageEvidenceKind, SpreadConvention, SpreadEvidence,
    SpreadObservation, SwapApplicability, SwapMode, SwapSpec,
    SymbolContractMissing, SymbolMetadataMismatch, SymbolRegistry, SymbolSpec,
    TradePlan, VenueIdentity, VenueIdentityMismatch, assert_regime_compatible,
    assert_symbol_metadata_matches, compute_costs, default_pip_convention,
    determine_swap_applicability, economic_verification_ready, empty_spec,
    session_for, summarise,
)
from ag_edgelab.friction.authority.capture_schema import (
    BundleInvalid, CAPTURE_SCHEMA_VERSION, QUOTE_CSV_COLUMNS, build_manifest,
    manifest_root, verify_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "friction_authority_r1"
SCRIPTS = ROOT / "scripts"
UTC = timezone.utc

SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")


# ---------------------------------------------------------------------------
# fixtures: fully-specified contracts used purely as arithmetic test vectors
# ---------------------------------------------------------------------------

def fx5(symbol: str, tick_value: float = 1.0) -> SymbolSpec:
    """A 5-digit FX contract (EURUSD/GBPUSD shape)."""
    return SymbolSpec(
        symbol=symbol, broker_symbol=symbol, digits=5, point=0.00001,
        trade_tick_size=0.00001, trade_tick_value=tick_value,
        contract_size=100000.0, currency_base=symbol[:3],
        currency_profit=symbol[3:], currency_margin=symbol[:3],
        source="TEST_VECTOR")


def jpy3(tick_value: float = 0.68) -> SymbolSpec:
    """A 3-digit JPY cross. tick_value is broker-converted to USD."""
    return SymbolSpec(
        symbol="USDJPY", broker_symbol="USDJPY", digits=3, point=0.001,
        trade_tick_size=0.001, trade_tick_value=tick_value,
        contract_size=100000.0, currency_base="USD", currency_profit="JPY",
        currency_margin="USD", source="TEST_VECTOR")


def gold2(tick_value: float = 1.0) -> SymbolSpec:
    """XAUUSD: 2 digits, 100 oz contract, no meaningful 'pip'."""
    return SymbolSpec(
        symbol="XAUUSD", broker_symbol="XAUUSD", digits=2, point=0.01,
        trade_tick_size=0.01, trade_tick_value=tick_value,
        contract_size=100.0, currency_base="XAU", currency_profit="USD",
        currency_margin="USD", source="TEST_VECTOR")


def complete_commission(symbol: str = "EURUSD", value: float = 3.5,
                        mode: CommissionMode = CommissionMode.PER_LOT_PER_SIDE
                        ) -> CommissionSpec:
    return CommissionSpec(
        symbol=symbol, mode=mode, value=value, currency="USD",
        scales_linearly_with_closed_volume=True,
        status=AuthorityStatus.CAPTURED, source="TEST_VECTOR")


def complete_slippage(median: float = 0.0, p90: float = 0.0) -> SlippageAuthority:
    return SlippageAuthority(
        status=AuthorityStatus.CAPTURED,
        evidence_kind=SlippageEvidenceKind.EXECUTED_FILL_HISTORY,
        sample_size=500, median_points=median, p90_points=p90,
        source="TEST_VECTOR")


def disabled_swap(symbol: str = "EURUSD") -> SwapSpec:
    return SwapSpec(symbol=symbol, swap_mode=SwapMode.DISABLED,
                    status=AuthorityStatus.DECLARED_BY_VENUE,
                    source="TEST_VECTOR")


def priced(plan: TradePlan, *, spec: SymbolSpec, spread: float = 0.00010,
           commission: CommissionSpec | None = None,
           slippage: SlippageAuthority | None = None,
           swap: SwapSpec | None = None,
           applicability: SwapApplicability = SwapApplicability.NOT_APPLICABLE,
           convention: SpreadConvention = SpreadConvention.FULL_SPREAD_ON_ENTRY):
    return compute_costs(
        plan, spec=spec, spread_price=spread,
        commission=commission or complete_commission(spec.symbol),
        slippage=slippage or complete_slippage(),
        swap=swap or disabled_swap(spec.symbol),
        swap_applicability=applicability, spread_convention=convention)


# ---------------------------------------------------------------------------
# §16.1  bid <= ask
# ---------------------------------------------------------------------------

class TestQuoteValidity:
    def test_normal_quote_is_valid_and_has_no_defects(self):
        obs = SpreadObservation(datetime(2026, 10, 5, 9, tzinfo=UTC),
                                "EURUSD", bid=1.10000, ask=1.10010)
        assert obs.is_valid
        assert obs.defects() == ()
        assert obs.spread_price == pytest.approx(0.00010)

    def test_crossed_quote_is_flagged_and_invalid(self):
        obs = SpreadObservation(datetime(2026, 10, 5, 9, tzinfo=UTC),
                                "EURUSD", bid=1.10020, ask=1.10000)
        assert QuoteDefect.CROSSED in obs.defects()
        assert not obs.is_valid

    def test_zero_spread_is_counted_but_not_invalid(self):
        obs = SpreadObservation(datetime(2026, 10, 5, 9, tzinfo=UTC),
                                "EURUSD", bid=1.10000, ask=1.10000)
        assert QuoteDefect.ZERO_SPREAD in obs.defects()
        assert obs.is_valid, "a locked market is real, not a measurement error"

    def test_nonpositive_price_is_invalid(self):
        obs = SpreadObservation(datetime(2026, 10, 5, 9, tzinfo=UTC),
                                "EURUSD", bid=0.0, ask=1.10000)
        assert QuoteDefect.NONPOSITIVE in obs.defects()
        assert not obs.is_valid

    def test_crossed_quotes_are_excluded_from_statistics_and_counted(self):
        spec = fx5("EURUSD")
        base = datetime(2026, 10, 5, 9, tzinfo=UTC)
        rows = [SpreadObservation(base + timedelta(seconds=i), "EURUSD",
                                  1.10000, 1.10010) for i in range(10)]
        rows.append(SpreadObservation(base, "EURUSD", 1.10020, 1.10000))
        dist = summarise(rows, spec=spec, session="ALL")
        assert dist.n == 10
        assert dist.invalid_quote_count == 1

    @settings(max_examples=200, deadline=None)
    @given(bid=st.floats(0.5, 2.0, allow_nan=False),
           spread=st.floats(0.0, 0.01, allow_nan=False))
    def test_valid_quotes_always_have_nonnegative_spread(self, bid, spread):
        obs = SpreadObservation(datetime(2026, 10, 5, tzinfo=UTC), "EURUSD",
                                bid=bid, ask=bid + spread)
        assert obs.is_valid
        assert obs.spread_price >= 0.0


# ---------------------------------------------------------------------------
# §16.2  spread arithmetic
# ---------------------------------------------------------------------------

class TestSpreadArithmetic:
    def test_spread_price_points_and_pips_agree(self):
        spec = fx5("EURUSD")
        obs = SpreadObservation(datetime(2026, 10, 5, 9, tzinfo=UTC),
                                "EURUSD", bid=1.10000, ask=1.10012)
        assert obs.spread_price == pytest.approx(0.00012)
        assert obs.spread_points(spec) == pytest.approx(12.0)
        assert obs.spread_pips(spec) == pytest.approx(1.2)

    def test_mid_is_between_bid_and_ask(self):
        obs = SpreadObservation(datetime(2026, 10, 5, 9, tzinfo=UTC),
                                "EURUSD", bid=1.10000, ask=1.10010)
        assert obs.bid <= obs.mid <= obs.ask

    def test_quantiles_are_nearest_rank_not_interpolated(self):
        spec = fx5("EURUSD")
        base = datetime(2026, 10, 5, 9, tzinfo=UTC)
        spreads = [0.00010, 0.00011, 0.00012, 0.00013, 0.00020]
        rows = [SpreadObservation(base + timedelta(seconds=i), "EURUSD",
                                  1.10000, 1.10000 + s)
                for i, s in enumerate(spreads)]
        dist = summarise(rows, spec=spec, session="ALL")
        observed = {round(s / spec.pip_size, 6) for s in spreads}
        for q in (dist.p25, dist.p50, dist.p75, dist.p90, dist.p95, dist.p99):
            assert q in observed, "quantiles must be observed values"

    def test_outliers_are_counted_and_retained(self):
        spec = fx5("EURUSD")
        base = datetime(2026, 10, 5, 9, tzinfo=UTC)
        rows = [SpreadObservation(base + timedelta(seconds=i), "EURUSD",
                                  1.10000, 1.10001) for i in range(100)]
        rows.append(SpreadObservation(base + timedelta(seconds=999), "EURUSD",
                                      1.10000, 1.10500))
        dist = summarise(rows, spec=spec, session="ALL")
        assert dist.n == 101, "the spike must stay in the sample"
        assert dist.outlier_count == 1
        assert dist.maximum == pytest.approx(50.0)

    def test_session_bucketing_is_reproducible(self):
        cases = {0: Session.ASIAN, 6: Session.ASIAN, 7: Session.LONDON,
                 11: Session.LONDON, 12: Session.OVERLAP, 15: Session.OVERLAP,
                 16: Session.NEW_YORK, 20: Session.NEW_YORK,
                 21: Session.OTHER, 23: Session.OTHER}
        for hour, expected in cases.items():
            ts = datetime(2026, 10, 5, hour, 30, tzinfo=UTC)
            assert session_for(ts) is expected

    def test_distributions_are_sliced_per_session(self):
        spec = fx5("EURUSD")
        ev = SpreadEvidence("EURUSD")
        for hour, spread in ((2, 0.00030), (9, 0.00012), (14, 0.00009)):
            for i in range(5):
                ts = datetime(2026, 10, 5, hour, i, tzinfo=UTC)
                ev.observations.append(SpreadObservation(
                    ts, "EURUSD", 1.10000, 1.10000 + spread,
                    session=session_for(ts)))
        dists = ev.distributions(spec)
        assert dists["ASIAN"].p50 > dists["LONDON"].p50 > dists["OVERLAP"].p50
        assert dists["ALL"].n == 15


# ---------------------------------------------------------------------------
# §16.3  EURUSD / GBPUSD / USDJPY pip conversion
# ---------------------------------------------------------------------------

class TestPipConversion:
    @pytest.mark.parametrize("symbol", ["EURUSD", "GBPUSD"])
    def test_five_digit_fx_pip_is_ten_points(self, symbol):
        spec = fx5(symbol)
        assert spec.convention is PipConvention.FX_FRACTIONAL
        assert spec.pip_size == pytest.approx(0.0001)
        assert spec.price_to_pips(0.00010) == pytest.approx(1.0)
        assert spec.price_to_points(0.00010) == pytest.approx(10.0)
        assert spec.pips_to_price(1.0) == pytest.approx(0.0001)

    def test_usdjpy_pip_is_hundredth_not_ten_thousandth(self):
        spec = jpy3()
        assert spec.convention is PipConvention.FX_FRACTIONAL
        assert spec.pip_size == pytest.approx(0.01)
        assert spec.price_to_pips(0.010) == pytest.approx(1.0)
        assert spec.price_to_points(0.010) == pytest.approx(10.0)

    def test_usdjpy_money_uses_broker_tick_value_not_derivation(self):
        """The classic USDJPY bug: profit accrues in JPY, not USD.

        A naive ``contract_size * price_delta`` gives JPY. The broker's
        ``trade_tick_value`` is already converted to the account currency,
        so the authority must use it verbatim.
        """
        spec = jpy3(tick_value=0.68)
        money = spec.price_to_money(0.010, 1.0)          # 1 pip, 1 lot
        assert money == pytest.approx(6.8)
        naive_jpy = 100000.0 * 0.010
        assert naive_jpy == pytest.approx(1000.0)
        assert money != pytest.approx(naive_jpy)

    def test_four_digit_fx_pip_equals_point(self):
        spec = SymbolSpec(symbol="EURUSD", digits=4, point=0.0001,
                          trade_tick_size=0.0001, trade_tick_value=10.0,
                          contract_size=100000.0, currency_base="EUR",
                          currency_profit="USD", currency_margin="EUR")
        assert spec.convention is PipConvention.FX_WHOLE
        assert spec.pip_size == pytest.approx(0.0001)
        assert spec.price_to_pips(0.0001) == pytest.approx(1.0)

    def test_pip_round_trip_is_lossless(self):
        for spec in (fx5("EURUSD"), fx5("GBPUSD"), jpy3()):
            assert spec.price_to_pips(spec.pips_to_price(2.5)) == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# §16.4  XAUUSD point/price conversion
# ---------------------------------------------------------------------------

class TestGoldConversion:
    def test_gold_has_no_pip_and_says_so(self):
        spec = gold2()
        assert spec.convention is PipConvention.INSTRUMENT_UNITS
        assert not spec.has_pips
        with pytest.raises(SymbolContractMissing, match="not defined"):
            _ = spec.pip_size

    def test_gold_point_conversion(self):
        spec = gold2()
        assert spec.price_to_points(0.30) == pytest.approx(30.0)
        assert spec.points_to_price(30.0) == pytest.approx(0.30)

    def test_gold_money_conversion_uses_tick_value(self):
        spec = gold2(tick_value=1.0)
        # 100 oz contract, $0.01 tick, $1.00 per tick => $1 per cent per lot.
        assert spec.price_to_money(1.00, 1.0) == pytest.approx(100.0)
        assert spec.price_to_money(0.30, 0.5) == pytest.approx(15.0)

    def test_gold_distribution_reports_instrument_units(self):
        spec = gold2()
        base = datetime(2026, 10, 5, 9, tzinfo=UTC)
        rows = [SpreadObservation(base + timedelta(seconds=i), "XAUUSD",
                                  2000.00, 2000.25) for i in range(10)]
        dist = summarise(rows, spec=spec, session="ALL")
        assert dist.unit == "instrument_units"
        assert dist.p50 == pytest.approx(0.25)

    def test_default_convention_forces_metals_to_instrument_units(self):
        for sym in ("XAUUSD", "XAGUSD", "XPTUSD"):
            assert default_pip_convention(sym, 5) is PipConvention.INSTRUMENT_UNITS


# ---------------------------------------------------------------------------
# §16.5  commission units
# ---------------------------------------------------------------------------

class TestCommissionUnits:
    def test_per_side_charges_twice_for_a_round_trip(self):
        spec = complete_commission(value=3.5,
                                   mode=CommissionMode.PER_LOT_PER_SIDE)
        assert spec.cost_for(volume_lots=1.0, sides=1) == pytest.approx(3.5)
        assert spec.cost_for(volume_lots=1.0, sides=2) == pytest.approx(7.0)

    def test_round_turn_is_halved_per_side(self):
        spec = complete_commission(value=7.0,
                                   mode=CommissionMode.PER_LOT_ROUND_TURN)
        assert spec.cost_for(volume_lots=1.0, sides=1) == pytest.approx(3.5)
        assert spec.cost_for(volume_lots=1.0, sides=2) == pytest.approx(7.0)

    def test_per_side_and_round_turn_agree_on_total(self):
        per_side = complete_commission(value=3.5,
                                       mode=CommissionMode.PER_LOT_PER_SIDE)
        round_turn = complete_commission(value=7.0,
                                         mode=CommissionMode.PER_LOT_ROUND_TURN)
        assert (per_side.cost_for(volume_lots=2.0, sides=2)
                == pytest.approx(round_turn.cost_for(volume_lots=2.0, sides=2)))

    def test_commission_scales_with_volume(self):
        spec = complete_commission(value=3.5)
        assert spec.cost_for(volume_lots=0.1, sides=2) == pytest.approx(0.7)
        assert spec.cost_for(volume_lots=10.0, sides=2) == pytest.approx(70.0)

    def test_percent_of_notional_requires_a_notional(self):
        spec = CommissionSpec(
            symbol="XAUUSD", mode=CommissionMode.PERCENT_OF_NOTIONAL_PER_SIDE,
            value=0.01, currency="USD",
            scales_linearly_with_closed_volume=True,
            status=AuthorityStatus.CAPTURED, source="TEST_VECTOR")
        with pytest.raises(FrictionComponentMissing, match="notional"):
            spec.cost_for(volume_lots=1.0, sides=1)
        assert spec.cost_for(volume_lots=1.0, sides=1,
                             notional=200000.0) == pytest.approx(20.0)

    def test_missing_commission_raises_and_never_returns_zero(self):
        spec = CommissionSpec(symbol="EURUSD")
        assert spec.status is AuthorityStatus.MISSING
        assert not spec.is_complete
        with pytest.raises(FrictionComponentMissing, match="MISSING"):
            spec.cost_for(volume_lots=1.0, sides=2)

    def test_incomplete_commission_is_not_usable_even_with_a_value(self):
        spec = CommissionSpec(symbol="EURUSD",
                              mode=CommissionMode.PER_LOT_PER_SIDE,
                              value=3.5, status=AuthorityStatus.CAPTURED)
        assert not spec.is_complete
        assert "currency" in spec.missing_fields()
        with pytest.raises(FrictionComponentMissing):
            spec.cost_for(volume_lots=1.0, sides=2)

    def test_genuine_zero_commission_account_is_distinct_from_missing(self):
        spec = CommissionSpec(
            symbol="EURUSD", mode=CommissionMode.ZERO_COMMISSION_SPREAD_MARKUP,
            value=0.0, currency="USD",
            scales_linearly_with_closed_volume=True,
            status=AuthorityStatus.CAPTURED, source="account statement")
        assert spec.is_complete
        assert spec.cost_for(volume_lots=1.0, sides=2) == 0.0


# ---------------------------------------------------------------------------
# §16.6 / §16.7  partial-exit and runner commission; spread not double counted
# ---------------------------------------------------------------------------

class TestPartialAndRunnerCosts:
    def _plan(self, exits):
        return TradePlan(symbol="EURUSD", side=Side.LONG, entry_price=1.10000,
                         stop_price=1.09800, volume_lots=1.0, exits=exits)

    def test_partial_exit_commission_sums_to_full_exit_commission(self):
        spec = fx5("EURUSD")
        full = priced(self._plan((ExitLeg(1.0, 1.10400, ExitKind.FULL_TARGET),)),
                      spec=spec)
        split = priced(self._plan((
            ExitLeg(0.5, 1.10200, ExitKind.TARGET_PARTIAL),
            ExitLeg(0.5, 1.10600, ExitKind.RUNNER))), spec=spec)
        assert split.commission_money == pytest.approx(full.commission_money)

    def test_runner_commission_is_charged_on_runner_volume_only(self):
        spec = fx5("EURUSD")
        res = priced(self._plan((
            ExitLeg(0.7, 1.10200, ExitKind.TARGET_PARTIAL),
            ExitLeg(0.3, 1.10900, ExitKind.RUNNER))), spec=spec)
        legs = {leg["leg"]: leg for leg in res.legs}
        assert legs["RUNNER"]["commission_money"] == pytest.approx(3.5 * 0.3)
        assert legs["TARGET_PARTIAL"]["commission_money"] == pytest.approx(3.5 * 0.7)
        assert legs["ENTRY"]["commission_money"] == pytest.approx(3.5)

    def test_partial_exits_do_not_double_count_spread(self):
        """The invariant: spread cost depends on volume, not exit count."""
        spec = fx5("EURUSD")
        shapes = {
            "one": (ExitLeg(1.0, 1.10400, ExitKind.FULL_TARGET),),
            "two": (ExitLeg(0.5, 1.10200, ExitKind.TARGET_PARTIAL),
                    ExitLeg(0.5, 1.10600, ExitKind.RUNNER)),
            "four": tuple(ExitLeg(0.25, 1.10200 + i * 0.001,
                                  ExitKind.TARGET_PARTIAL) for i in range(4)),
        }
        totals = {k: priced(self._plan(v), spec=spec).spread_money
                  for k, v in shapes.items()}
        assert len(set(round(v, 10) for v in totals.values())) == 1, totals
        assert totals["one"] == pytest.approx(10.0)

    def test_both_spread_conventions_agree_on_round_trip_total(self):
        spec = fx5("EURUSD")
        plan = self._plan((ExitLeg(0.5, 1.10200, ExitKind.TARGET_PARTIAL),
                           ExitLeg(0.5, 1.10600, ExitKind.RUNNER)))
        on_entry = priced(plan, spec=spec,
                          convention=SpreadConvention.FULL_SPREAD_ON_ENTRY)
        per_leg = priced(plan, spec=spec,
                         convention=SpreadConvention.HALF_SPREAD_PER_LEG)
        assert on_entry.spread_money == pytest.approx(per_leg.spread_money)

    def test_half_spread_convention_splits_the_charge_across_legs(self):
        spec = fx5("EURUSD")
        plan = self._plan((ExitLeg(0.5, 1.10200, ExitKind.TARGET_PARTIAL),
                           ExitLeg(0.5, 1.10600, ExitKind.RUNNER)))
        res = priced(plan, spec=spec,
                     convention=SpreadConvention.HALF_SPREAD_PER_LEG)
        legs = {leg["leg"]: leg for leg in res.legs}
        assert legs["ENTRY"]["spread_money"] == pytest.approx(5.0)
        assert legs["TARGET_PARTIAL"]["spread_money"] == pytest.approx(2.5)
        assert legs["RUNNER"]["spread_money"] == pytest.approx(2.5)

    def test_gross_r_is_unchanged_by_exit_shape_when_outcome_matches(self):
        spec = fx5("EURUSD")
        full = priced(self._plan((ExitLeg(1.0, 1.10400, ExitKind.FULL_TARGET),)),
                      spec=spec)
        split = priced(self._plan((
            ExitLeg(0.5, 1.10200, ExitKind.TARGET_PARTIAL),
            ExitLeg(0.5, 1.10600, ExitKind.RUNNER))), spec=spec)
        assert full.gross_r == pytest.approx(2.0)
        assert split.gross_r == pytest.approx(full.gross_r)
        assert split.net_r == pytest.approx(full.net_r)

    def test_net_r_is_strictly_worse_than_gross_r_when_costs_exist(self):
        spec = fx5("EURUSD")
        res = priced(self._plan((ExitLeg(1.0, 1.10400, ExitKind.FULL_TARGET),)),
                     spec=spec)
        assert res.net_r < res.gross_r
        assert res.total_cost_money == pytest.approx(17.0)
        assert res.net_r == pytest.approx((400.0 - 17.0) / 200.0)

    def test_losing_trade_costs_make_the_loss_bigger(self):
        spec = fx5("EURUSD")
        res = priced(self._plan((ExitLeg(1.0, 1.09800, ExitKind.STOP),)),
                     spec=spec)
        assert res.gross_r == pytest.approx(-1.0)
        assert res.net_r < -1.0

    @pytest.mark.parametrize("kind", list(ExitKind))
    def test_every_exit_kind_is_priceable(self, kind):
        spec = fx5("EURUSD")
        res = priced(self._plan((ExitLeg(1.0, 1.10100, kind),)), spec=spec)
        assert res.legs[-1]["leg"] == str(kind)

    def test_forced_close_leg_can_carry_its_own_slippage(self):
        spec = fx5("EURUSD")
        res = priced(self._plan((
            ExitLeg(0.5, 1.10200, ExitKind.TARGET_PARTIAL),
            ExitLeg(0.5, 1.09950, ExitKind.FORCED_CLOSE,
                    slippage_points_override=5.0))), spec=spec)
        legs = {leg["leg"]: leg for leg in res.legs}
        assert legs["FORCED_CLOSE"]["slippage_points"] == 5.0
        assert legs["TARGET_PARTIAL"]["slippage_points"] == 0.0
        assert res.slippage_money == pytest.approx(
            spec.price_to_money(spec.points_to_price(5.0), 0.5))

    def test_unclosed_volume_is_rejected(self):
        spec = fx5("EURUSD")
        with pytest.raises(ValueError, match="does not close"):
            priced(self._plan((ExitLeg(0.5, 1.10200, ExitKind.TARGET_PARTIAL),)),
                   spec=spec)

    def test_short_side_pnl_is_mirrored(self):
        spec = fx5("EURUSD")
        plan = TradePlan(symbol="EURUSD", side=Side.SHORT, entry_price=1.10000,
                         stop_price=1.10200, volume_lots=1.0,
                         exits=(ExitLeg(1.0, 1.09600, ExitKind.FULL_TARGET),))
        res = priced(plan, spec=spec)
        assert res.gross_r == pytest.approx(2.0)

    def test_gold_partial_runner_prices_in_instrument_units(self):
        spec = gold2()
        plan = TradePlan(symbol="XAUUSD", side=Side.LONG, entry_price=2000.00,
                         stop_price=1995.00, volume_lots=1.0,
                         exits=(ExitLeg(0.5, 2005.00, ExitKind.TARGET_PARTIAL),
                                ExitLeg(0.5, 2015.00, ExitKind.RUNNER)))
        res = priced(plan, spec=spec, spread=0.25,
                     commission=complete_commission("XAUUSD"),
                     swap=disabled_swap("XAUUSD"))
        assert res.risk_money == pytest.approx(500.0)
        assert res.gross_money == pytest.approx(250.0 + 750.0)
        assert res.spread_money == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# §16.8  swap applicability
# ---------------------------------------------------------------------------

class TestSwapApplicability:
    def test_unknown_contract_keeps_swap_active(self):
        verdict, reason = determine_swap_applicability(
            strategy_contract_closes_before_rollover=None,
            contract_is_frozen=False)
        assert verdict is SwapApplicability.UNDETERMINED
        assert "remains active" in reason

    def test_unfrozen_contract_cannot_waive_swap(self):
        verdict, _ = determine_swap_applicability(
            strategy_contract_closes_before_rollover=True,
            contract_is_frozen=False)
        assert verdict is SwapApplicability.UNDETERMINED

    def test_frozen_intraday_contract_waives_swap(self):
        verdict, reason = determine_swap_applicability(
            strategy_contract_closes_before_rollover=True,
            contract_is_frozen=True, max_holding_minutes=240)
        assert verdict is SwapApplicability.NOT_APPLICABLE
        assert "240" in reason

    def test_frozen_overnight_contract_keeps_swap(self):
        verdict, _ = determine_swap_applicability(
            strategy_contract_closes_before_rollover=False,
            contract_is_frozen=True)
        assert verdict is SwapApplicability.APPLICABLE

    def test_undetermined_swap_with_rollovers_fails_closed(self):
        spec = fx5("EURUSD")
        plan = TradePlan(symbol="EURUSD", side=Side.LONG, entry_price=1.10000,
                         stop_price=1.09800, volume_lots=1.0, rollovers_held=2,
                         exits=(ExitLeg(1.0, 1.10400, ExitKind.FULL_TARGET),))
        with pytest.raises(FrictionComponentMissing, match="UNDETERMINED"):
            priced(plan, spec=spec,
                   applicability=SwapApplicability.UNDETERMINED)

    def test_applicable_swap_without_authority_fails_closed(self):
        spec = fx5("EURUSD")
        plan = TradePlan(symbol="EURUSD", side=Side.LONG, entry_price=1.10000,
                         stop_price=1.09800, volume_lots=1.0, rollovers_held=1,
                         exits=(ExitLeg(1.0, 1.10400, ExitKind.FULL_TARGET),))
        with pytest.raises(FrictionComponentMissing, match="SWAP_AUTHORITY"):
            priced(plan, spec=spec, swap=SwapSpec(symbol="EURUSD"),
                   applicability=SwapApplicability.APPLICABLE)

    def test_negative_swap_rate_is_a_cost(self):
        spec = fx5("EURUSD")
        swap = SwapSpec(symbol="EURUSD", swap_long=-4.0, swap_short=1.2,
                        swap_mode=SwapMode.POINTS,
                        status=AuthorityStatus.DECLARED_BY_VENUE,
                        source="TEST_VECTOR")
        plan = TradePlan(symbol="EURUSD", side=Side.LONG, entry_price=1.10000,
                         stop_price=1.09800, volume_lots=1.0, rollovers_held=3,
                         exits=(ExitLeg(1.0, 1.10400, ExitKind.FULL_TARGET),))
        res = priced(plan, spec=spec, swap=swap,
                     applicability=SwapApplicability.APPLICABLE)
        assert res.swap_money == pytest.approx(12.0)

    def test_positive_swap_rate_is_a_credit(self):
        spec = fx5("EURUSD")
        swap = SwapSpec(symbol="EURUSD", swap_long=-4.0, swap_short=1.5,
                        swap_mode=SwapMode.POINTS,
                        status=AuthorityStatus.DECLARED_BY_VENUE,
                        source="TEST_VECTOR")
        plan = TradePlan(symbol="EURUSD", side=Side.SHORT, entry_price=1.10000,
                         stop_price=1.10200, volume_lots=1.0, rollovers_held=2,
                         exits=(ExitLeg(1.0, 1.09600, ExitKind.FULL_TARGET),))
        res = priced(plan, spec=spec, swap=swap,
                     applicability=SwapApplicability.APPLICABLE)
        assert res.swap_money == pytest.approx(-3.0)

    def test_unconvertible_swap_mode_refuses_to_approximate(self):
        spec = fx5("EURUSD")
        swap = SwapSpec(symbol="EURUSD", swap_long=-0.5, swap_short=0.1,
                        swap_mode=SwapMode.INTEREST,
                        status=AuthorityStatus.DECLARED_BY_VENUE,
                        source="TEST_VECTOR")
        plan = TradePlan(symbol="EURUSD", side=Side.LONG, entry_price=1.10000,
                         stop_price=1.09800, volume_lots=1.0, rollovers_held=1,
                         exits=(ExitLeg(1.0, 1.10400, ExitKind.FULL_TARGET),))
        with pytest.raises(FrictionComponentMissing, match="refusing to approximate"):
            priced(plan, spec=spec, swap=swap,
                   applicability=SwapApplicability.APPLICABLE)

    def test_disabled_swap_mode_is_a_captured_zero(self):
        swap = disabled_swap()
        assert swap.is_complete
        assert swap.swap_mode is SwapMode.DISABLED

    def test_missing_swap_without_rollovers_is_harmless(self):
        spec = fx5("EURUSD")
        plan = TradePlan(symbol="EURUSD", side=Side.LONG, entry_price=1.10000,
                         stop_price=1.09800, volume_lots=1.0, rollovers_held=0,
                         exits=(ExitLeg(1.0, 1.10400, ExitKind.FULL_TARGET),))
        res = priced(plan, spec=spec, swap=SwapSpec(symbol="EURUSD"),
                     applicability=SwapApplicability.APPLICABLE)
        assert res.swap_money == 0.0


# ---------------------------------------------------------------------------
# §16.9  NULL friction fail-closed
# ---------------------------------------------------------------------------

class TestFailClosed:
    def test_empty_symbol_spec_refuses_every_conversion(self):
        spec = empty_spec("EURUSD")
        assert not spec.is_complete
        for call in (lambda: spec.price_to_points(0.0001),
                     lambda: spec.points_to_price(1.0),
                     lambda: spec.price_to_money(0.0001, 1.0),
                     lambda: spec.pip_size):
            with pytest.raises(SymbolContractMissing):
                call()

    def test_missing_slippage_raises_rather_than_zeroing(self):
        spec = fx5("EURUSD")
        plan = TradePlan(symbol="EURUSD", side=Side.LONG, entry_price=1.10000,
                         stop_price=1.09800, volume_lots=1.0,
                         exits=(ExitLeg(1.0, 1.10400, ExitKind.FULL_TARGET),))
        with pytest.raises(FrictionComponentMissing, match="SLIPPAGE_AUTHORITY"):
            compute_costs(plan, spec=spec, spread_price=0.00010,
                          commission=complete_commission(),
                          slippage=SlippageAuthority(),
                          swap=disabled_swap(),
                          swap_applicability=SwapApplicability.NOT_APPLICABLE)

    def test_slippage_can_be_waived_only_explicitly(self):
        spec = fx5("EURUSD")
        plan = TradePlan(symbol="EURUSD", side=Side.LONG, entry_price=1.10000,
                         stop_price=1.09800, volume_lots=1.0,
                         exits=(ExitLeg(1.0, 1.10400, ExitKind.FULL_TARGET),))
        res = compute_costs(plan, spec=spec, spread_price=0.00010,
                            commission=complete_commission(),
                            slippage=SlippageAuthority(),
                            swap=disabled_swap(),
                            swap_applicability=SwapApplicability.NOT_APPLICABLE,
                            require_slippage=False)
        assert res.slippage_money == 0.0

    def test_missing_slippage_authority_explains_why_quotes_cannot_help(self):
        auth = SlippageAuthority(
            future_evidence_requirement=DEFAULT_SLIPPAGE_REQUIREMENT)
        with pytest.raises(FrictionComponentMissing, match="FILLS"):
            auth.cost_points()
        blob = auth.as_dict()
        assert blob["status"] == "MISSING"
        assert blob["future_evidence_requirement"]
        assert "not estimable from spread evidence" in \
            blob["why_quotes_are_insufficient"]

    def test_no_invented_slippage_constant_anywhere_in_the_package(self):
        """Guard against a 0.1/0.2 pip default creeping back in."""
        pkg = ROOT / "src" / "ag_edgelab" / "friction" / "authority"
        for path in pkg.glob("*.py"):
            text = path.read_text()
            for bad in ("slippage_points: float = 0.1",
                        "slippage_points: float = 0.2",
                        "DEFAULT_SLIPPAGE_PIPS", "ASSUMED_SLIPPAGE"):
                assert bad not in text, f"{path.name} contains {bad!r}"

    def test_incomplete_authority_rejects_economic_verification(self):
        contract = FrictionAuthorityContract(
            symbols={s: empty_spec(s) for s in SYMBOLS},
            commissions={s: CommissionSpec(symbol=s) for s in SYMBOLS},
            swaps={s: SwapSpec(symbol=s) for s in SYMBOLS})
        assert not contract.is_complete
        with pytest.raises(FrictionAuthorityIncomplete, match="must not default to zero"):
            contract.assert_usable_for_economics()

    def test_blockers_name_every_missing_component(self):
        contract = FrictionAuthorityContract(
            symbols={"EURUSD": empty_spec("EURUSD")},
            commissions={"EURUSD": CommissionSpec(symbol="EURUSD")},
            swaps={"EURUSD": SwapSpec(symbol="EURUSD")})
        joined = " ".join(contract.blockers())
        for token in ("VENUE_IDENTITY", "SPREAD_AUTHORITY=MISSING",
                      "COMMISSION_AUTHORITY=MISSING", "SLIPPAGE_AUTHORITY=MISSING",
                      "SWAP_AUTHORITY=MISSING"):
            assert token in joined

    def test_readiness_reports_blockers_per_symbol(self):
        ok, blockers = economic_verification_ready(
            spec=empty_spec("EURUSD"), spread_observations=0,
            commission=CommissionSpec(symbol="EURUSD"),
            slippage=SlippageAuthority(), swap=SwapSpec(symbol="EURUSD"),
            swap_applicability=SwapApplicability.UNDETERMINED)
        assert not ok
        assert len(blockers) >= 4

    def test_complete_authority_passes_the_gate(self):
        contract = _complete_contract()
        assert contract.is_complete, contract.blockers()
        contract.assert_usable_for_economics()

    def test_symbol_registry_refuses_unknown_symbols(self):
        reg = SymbolRegistry(venue="VT_MARKETS", account_class="LIVE")
        reg.add(fx5("EURUSD"))
        assert reg.get("EURUSD").symbol == "EURUSD"
        with pytest.raises(SymbolContractMissing, match="Refusing to assume"):
            reg.get("AUDCAD")

    def test_zero_tick_size_is_rejected(self):
        spec = SymbolSpec(symbol="EURUSD", digits=5, point=0.00001,
                          trade_tick_size=0.0, trade_tick_value=1.0,
                          contract_size=100000.0, currency_base="EUR",
                          currency_profit="USD", currency_margin="EUR")
        with pytest.raises(SymbolContractMissing, match="trade_tick_size is zero"):
            spec.price_to_money(0.0001, 1.0)


def _complete_contract() -> FrictionAuthorityContract:
    specs = {"EURUSD": fx5("EURUSD"), "GBPUSD": fx5("GBPUSD"),
             "USDJPY": jpy3(), "XAUUSD": gold2()}
    return FrictionAuthorityContract(
        venue=VenueIdentity(broker="VT Markets Ltd", server="VTMarkets-Live 3",
                            account_class=AccountClass.LIVE,
                            account_type="RAW_ECN", account_currency="USD",
                            terminal_build=4260),
        symbols=specs,
        commissions={s: complete_commission(s) for s in specs},
        swaps={s: disabled_swap(s) for s in specs},
        slippage=complete_slippage(0.2, 0.8),
        swap_applicability=SwapApplicability.APPLICABLE,
        spread_evidence={s: {"n": 1000, "status": "CAPTURED", "p50": 0.1}
                         for s in specs},
        capture_started_utc="2026-10-05T00:00:00Z",
        capture_ended_utc="2026-10-05T23:00:00Z")


# ---------------------------------------------------------------------------
# §16.10  scenario hashing
# ---------------------------------------------------------------------------

class TestScenarioContract:
    def test_hash_is_deterministic(self):
        assert ScenarioContract().hash() == ScenarioContract().hash()

    def test_hash_is_sha256_shaped(self):
        assert re.fullmatch(r"[0-9a-f]{64}", ScenarioContract().hash())

    def test_changing_a_quantile_changes_the_hash(self):
        base = ScenarioContract()
        tweaked = ScenarioContract(rules=(
            ScenarioRule(name=ScenarioName.BASELINE, spread_quantile="P75"),
            PREREGISTERED_SCENARIOS[1]))
        assert base.hash() != tweaked.hash()

    def test_changing_a_multiplier_changes_the_hash(self):
        base = ScenarioContract()
        tweaked = ScenarioContract(rules=(
            PREREGISTERED_SCENARIOS[0],
            ScenarioRule(name=ScenarioName.STRESSED, spread_quantile="P95",
                         spread_multiplier=1.5)))
        assert base.hash() != tweaked.hash()

    def test_baseline_and_stressed_are_both_preregistered(self):
        names = {r.name for r in PREREGISTERED_SCENARIOS}
        assert names == {ScenarioName.BASELINE, ScenarioName.STRESSED}

    def test_stressed_is_not_cheaper_than_baseline(self):
        order = {"P50": 0, "P75": 1, "P90": 2, "P95": 3, "P99": 4}
        rules = {r.name: r for r in PREREGISTERED_SCENARIOS}
        assert (order[rules[ScenarioName.STRESSED].spread_quantile]
                > order[rules[ScenarioName.BASELINE].spread_quantile])

    def test_candidate_pnl_is_a_forbidden_selection_input(self):
        contract = ScenarioContract()
        forbidden = set(contract.forbidden_selection_inputs)
        assert {"candidate PnL", "OOS results", "holdout results"} <= forbidden
        assert not (set(contract.selection_inputs) & forbidden)

    def test_scenarios_reference_only_observed_quantiles(self):
        for rule in PREREGISTERED_SCENARIOS:
            assert rule.spread_quantile in {"P25", "P50", "P75", "P90", "P95", "P99"}
            assert rule.spread_multiplier == 1.0


# ---------------------------------------------------------------------------
# §16.11  friction evidence hashing
# ---------------------------------------------------------------------------

def _make_bundle(tmp_path: Path, *, rows: int = 5) -> Path:
    bundle = tmp_path / "bundle"
    (bundle / "quotes").mkdir(parents=True)
    meta = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "tool_version": "test/1.0.0", "broker": "VT Markets Ltd",
        "server": "VTMarkets-Demo", "account_class": "DEMO",
        "account_type": "RAW", "account_currency": "USD",
        "terminal_build": 4260,
        "capture_started_utc": "2026-10-05T08:00:00Z",
        "capture_ended_utc": "2026-10-05T09:00:00Z",
        "symbols": ["EURUSD"],
    }
    (bundle / "capture_metadata.json").write_text(json.dumps(meta))
    (bundle / "symbol_metadata.json").write_text(
        json.dumps({"EURUSD": fx5("EURUSD").as_dict()}))
    (bundle / "commission.json").write_text(
        json.dumps({"EURUSD": complete_commission().as_dict()}))
    (bundle / "swap.json").write_text(
        json.dumps({"EURUSD": disabled_swap().as_dict()}))
    (bundle / "slippage.json").write_text(
        json.dumps(SlippageAuthority().as_dict()))
    lines = [",".join(QUOTE_CSV_COLUMNS)]
    for i in range(rows):
        ts = f"2026-10-05T08:{i:02d}:00Z"
        lines.append(f"{ts},EURUSD,1.10000,1.10010,0.0001,10.0,LONDON")
    (bundle / "quotes" / "EURUSD.csv").write_text("\n".join(lines) + "\n")
    manifest = build_manifest(bundle)
    (bundle / "BUNDLE_MANIFEST.json").write_text(json.dumps(manifest))
    return bundle


class TestEvidenceHashing:
    def test_clean_bundle_verifies(self, tmp_path):
        report = verify_bundle(_make_bundle(tmp_path))
        assert report["verified"]
        assert re.fullmatch(r"[0-9a-f]{64}", report["manifest_root_sha256"])

    def test_tampered_quote_file_is_detected(self, tmp_path):
        bundle = _make_bundle(tmp_path)
        path = bundle / "quotes" / "EURUSD.csv"
        path.write_text(path.read_text().replace("1.10010", "1.10002"))
        with pytest.raises(BundleInvalid, match="hash mismatch"):
            verify_bundle(bundle)

    def test_tampered_metadata_is_detected(self, tmp_path):
        bundle = _make_bundle(tmp_path)
        path = bundle / "capture_metadata.json"
        path.write_text(path.read_text().replace("DEMO", "LIVE"))
        with pytest.raises(BundleInvalid, match="hash mismatch"):
            verify_bundle(bundle)

    def test_added_file_is_detected(self, tmp_path):
        bundle = _make_bundle(tmp_path)
        (bundle / "quotes" / "GBPUSD.csv").write_text("x\n")
        with pytest.raises(BundleInvalid, match="unmanifested"):
            verify_bundle(bundle)

    def test_removed_file_is_detected(self, tmp_path):
        bundle = _make_bundle(tmp_path)
        (bundle / "quotes" / "EURUSD.csv").unlink()
        with pytest.raises(BundleInvalid, match="not present"):
            verify_bundle(bundle)

    def test_missing_required_member_is_detected(self, tmp_path):
        bundle = _make_bundle(tmp_path)
        (bundle / "commission.json").unlink()
        (bundle / "BUNDLE_MANIFEST.json").write_text(
            json.dumps(build_manifest(bundle)))
        with pytest.raises(BundleInvalid, match="missing required files"):
            verify_bundle(bundle)

    def test_forged_root_hash_is_detected(self, tmp_path):
        bundle = _make_bundle(tmp_path)
        manifest = json.loads((bundle / "BUNDLE_MANIFEST.json").read_text())
        manifest["manifest_root_sha256"] = "0" * 64
        (bundle / "BUNDLE_MANIFEST.json").write_text(json.dumps(manifest))
        with pytest.raises(BundleInvalid, match="root mismatch"):
            verify_bundle(bundle)

    def test_unmanifested_bundle_is_rejected(self, tmp_path):
        bundle = _make_bundle(tmp_path)
        (bundle / "BUNDLE_MANIFEST.json").unlink()
        with pytest.raises(BundleInvalid, match="not hash-verifiable"):
            verify_bundle(bundle)

    def test_schema_version_is_enforced(self, tmp_path):
        bundle = _make_bundle(tmp_path)
        meta = json.loads((bundle / "capture_metadata.json").read_text())
        meta["schema_version"] = "SOMETHING_ELSE_V9"
        (bundle / "capture_metadata.json").write_text(json.dumps(meta))
        (bundle / "BUNDLE_MANIFEST.json").write_text(
            json.dumps(build_manifest(bundle)))
        with pytest.raises(BundleInvalid, match="schema version"):
            verify_bundle(bundle)

    def test_manifest_root_is_order_independent(self):
        a = {"x": "aa", "y": "bb"}
        b = {"y": "bb", "x": "aa"}
        assert manifest_root(a) == manifest_root(b)

    def test_manifest_root_changes_with_content(self):
        assert manifest_root({"x": "aa"}) != manifest_root({"x": "ab"})

    def test_authority_hash_is_deterministic_and_content_addressed(self):
        a, b = _complete_contract(), _complete_contract()
        assert a.hash() == b.hash()
        assert re.fullmatch(r"[0-9a-f]{64}", a.hash())
        c = _complete_contract()
        c.commissions["EURUSD"] = complete_commission("EURUSD", value=4.0)
        assert c.hash() != a.hash()

    def test_authority_hash_changes_with_spread_evidence(self):
        a = _complete_contract()
        b = _complete_contract()
        b.spread_evidence["EURUSD"] = {"n": 1001, "status": "CAPTURED",
                                       "p50": 0.1}
        assert a.hash() != b.hash()


# ---------------------------------------------------------------------------
# §16.12 / §16.13  venue identity and symbol metadata mismatch
# ---------------------------------------------------------------------------

class TestIdentityMismatch:
    def _venue(self, **over) -> VenueIdentity:
        base = dict(broker="VT Markets Ltd", server="VTMarkets-Live 3",
                    account_class=AccountClass.LIVE, account_currency="USD")
        base.update(over)
        return VenueIdentity(**base)

    def test_identical_venues_match(self):
        self._venue().assert_matches(self._venue())

    def test_different_broker_is_rejected(self):
        with pytest.raises(VenueIdentityMismatch, match="broker"):
            self._venue().assert_matches(self._venue(broker="Other Broker Ltd"))

    def test_different_server_is_rejected(self):
        with pytest.raises(VenueIdentityMismatch, match="server"):
            self._venue().assert_matches(self._venue(server="VTMarkets-Live 7"))

    def test_demo_evidence_cannot_price_a_live_account(self):
        with pytest.raises(VenueIdentityMismatch, match="account_class"):
            self._venue().assert_matches(
                self._venue(account_class=AccountClass.DEMO))

    def test_different_account_currency_is_rejected(self):
        with pytest.raises(VenueIdentityMismatch, match="account_currency"):
            self._venue().assert_matches(self._venue(account_currency="EUR"))

    def test_unknown_venue_is_incomplete(self):
        assert not VenueIdentity().is_complete
        assert self._venue().is_complete

    def test_matching_symbol_metadata_passes(self):
        assert_symbol_metadata_matches(fx5("EURUSD"), fx5("EURUSD"))

    def test_changed_digits_is_rejected(self):
        runtime = SymbolSpec(**{**fx5("EURUSD").__dict__, "digits": 4})
        with pytest.raises(SymbolMetadataMismatch, match="digits"):
            assert_symbol_metadata_matches(fx5("EURUSD"), runtime)

    def test_changed_contract_size_is_rejected(self):
        runtime = SymbolSpec(**{**fx5("EURUSD").__dict__,
                                "contract_size": 10000.0})
        with pytest.raises(SymbolMetadataMismatch, match="contract_size"):
            assert_symbol_metadata_matches(fx5("EURUSD"), runtime)

    def test_changed_tick_value_is_rejected(self):
        with pytest.raises(SymbolMetadataMismatch, match="trade_tick_value"):
            assert_symbol_metadata_matches(fx5("EURUSD"),
                                           fx5("EURUSD", tick_value=10.0))

    def test_a_field_appearing_or_vanishing_is_rejected(self):
        with pytest.raises(SymbolMetadataMismatch):
            assert_symbol_metadata_matches(fx5("EURUSD"), empty_spec("EURUSD"))

    def test_symbol_name_mismatch_is_rejected(self):
        with pytest.raises(SymbolMetadataMismatch, match="symbol mismatch"):
            assert_symbol_metadata_matches(fx5("EURUSD"), fx5("GBPUSD"))

    def test_cosmetic_fields_do_not_trigger_a_mismatch(self):
        runtime = SymbolSpec(**{**fx5("EURUSD").__dict__,
                                "captured_at": "2026-10-06T00:00:00Z",
                                "source": "other"})
        assert_symbol_metadata_matches(fx5("EURUSD"), runtime)


# ---------------------------------------------------------------------------
# §12  historical applicability
# ---------------------------------------------------------------------------

class TestHistoricalApplicability:
    def test_current_authority_cannot_be_applied_to_the_dataset_period(self):
        with pytest.raises(ValueError, match="refusing to apply"):
            assert_regime_compatible(
                FrictionRegime.VENUE_CURRENT_FRICTION_AUTHORITY,
                dataset_period="2011-06-01/2018-06-06",
                capture_period="2026-10-05/2026-10-06")

    def test_matching_periods_are_allowed(self):
        assert_regime_compatible(
            FrictionRegime.VENUE_CURRENT_FRICTION_AUTHORITY,
            dataset_period="2026-10-05/2026-10-06",
            capture_period="2026-10-05/2026-10-06")

    def test_research_model_is_allowed_across_periods(self):
        assert_regime_compatible(
            FrictionRegime.RESEARCH_CONSERVATIVE_MODEL,
            dataset_period="2011-06-01/2018-06-06",
            capture_period="2026-10-05/2026-10-06")

    def test_research_policy_declares_it_is_not_a_measurement(self):
        policy = HistoricalCostPolicy().as_dict()
        assert policy["is_measurement"] is False
        assert policy["multiplier"] >= 1.0
        assert policy["regime"] == "RESEARCH_CONSERVATIVE_MODEL"
        assert policy["falsifiable_by"]

    def test_research_policy_is_conservative_relative_to_current_evidence(self):
        policy = HistoricalCostPolicy()
        assert policy.anchor_quantile in {"P90", "P95", "P99"}
        assert policy.multiplier > 1.0

    def test_limitation_text_names_both_regimes(self):
        for token in ("VENUE_CURRENT_FRICTION_AUTHORITY",
                      "HISTORICAL_FRICTION_TRUTH", "2026", "2011"):
            assert token in HISTORICAL_FRICTION_LIMITATION

    def test_three_regimes_are_distinct(self):
        assert len({str(r) for r in FrictionRegime}) == 3


# ---------------------------------------------------------------------------
# capture tool: read-only by construction
# ---------------------------------------------------------------------------

def _executable_source(path: Path) -> str:
    """Source with comments and string literals removed.

    Prose in a docstring that *names* a forbidden primitive is not a call
    to it, so the guard must look at code only.
    """
    import io
    import tokenize

    pieces: list[str] = []
    with path.open("rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            pieces.append(tok.string)
    return " ".join(pieces)


class TestCaptureToolIsReadOnly:
    PATH = SCRIPTS / "capture_vtmarkets_friction.py"
    SOURCE = (SCRIPTS / "capture_vtmarkets_friction.py").read_text()

    @pytest.mark.parametrize("primitive", [
        "order_send", "order_check", "position_close", "positions_modify",
        "TRADE_ACTION_DEAL", "TRADE_ACTION_PENDING",
    ])
    def test_no_ordering_primitive_is_present(self, primitive):
        assert primitive not in _executable_source(self.PATH), (
            f"{primitive!r} would make the capture tool capable of trading; "
            "this mission is read-only")

    def test_only_reader_functions_are_called(self):
        called = set(re.findall(r"mt5\s*\.\s*(\w+)\s*\(",
                                _executable_source(self.PATH)))
        # Every entry is a READER. symbols_get enumerates the published
        # instrument list (needed to resolve broker names instead of
        # guessing suffixes) and copy_ticks_range reads historical ticks.
        # Neither can create, modify or cancel an order.
        allowed = {"initialize", "shutdown", "last_error", "account_info",
                   "terminal_info", "symbol_info", "symbol_info_tick",
                   "symbol_select", "history_deals_get", "history_orders_get",
                   "symbols_get", "copy_ticks_range"}
        assert called <= allowed, f"non-reader MT5 calls: {called - allowed}"
        assert called, "the guard must actually be seeing MT5 calls"

    def test_module_imports_without_metatrader5(self):
        sys.path.insert(0, str(SCRIPTS))
        try:
            import capture_vtmarkets_friction as cap
            assert cap.TOOL_VERSION
            assert cap.DEFAULT_SYMBOLS == SYMBOLS
        finally:
            sys.path.remove(str(SCRIPTS))

    def test_running_without_metatrader5_exits_cleanly(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "capture_vtmarkets_friction.py"),
             "--out", "/tmp/should_not_be_created_friction"],
            capture_output=True, text=True, timeout=120)
        assert proc.returncode == 2
        assert "MetaTrader5 is not installed" in proc.stderr
        assert not Path("/tmp/should_not_be_created_friction").exists()

    def test_documents_that_credentials_are_never_requested(self):
        text = self.SOURCE.lower()
        for secret in ("password", "investor_password", "api_key", "token="):
            assert secret not in text


class TestCaptureAdapters:
    """The MT5 -> dataclass conversion, covered without a terminal."""

    class FakeInfo:
        name = "EURUSD"
        digits = 5
        point = 1e-05
        trade_tick_size = 1e-05
        trade_tick_value = 1.0
        trade_contract_size = 100000.0
        currency_base = "EUR"
        currency_profit = "USD"
        currency_margin = "EUR"
        volume_min = 0.01
        volume_step = 0.01
        volume_max = 100.0
        swap_long = -7.5
        swap_short = 2.1
        swap_mode = 1
        swap_rollover3days = 3

    class FakeDeal:
        def __init__(self, volume, commission, symbol="EURUSD", type_=0,
                     price=1.10000, order=1):
            self.volume, self.commission = volume, commission
            self.symbol, self.type, self.price, self.order = (
                symbol, type_, price, order)

    class FakeOrder:
        def __init__(self, ticket, price_open):
            self.ticket, self.price_open = ticket, price_open

    @staticmethod
    def _cap():
        sys.path.insert(0, str(SCRIPTS))
        try:
            import capture_vtmarkets_friction as cap
            return cap
        finally:
            if str(SCRIPTS) in sys.path:
                sys.path.remove(str(SCRIPTS))

    def test_symbol_spec_copies_tick_value_verbatim(self):
        cap = self._cap()
        spec = cap.symbol_spec_from_mt5(self.FakeInfo(), symbol="EURUSD",
                                        captured_at="2026-10-05T00:00:00Z")
        assert spec.is_complete
        assert spec.trade_tick_value == 1.0
        assert spec.convention is PipConvention.FX_FRACTIONAL

    def test_partial_symbol_info_leaves_fields_none(self):
        cap = self._cap()

        class Sparse:
            name = "XAUUSD"
            digits = 2
            point = 0.01

        spec = cap.symbol_spec_from_mt5(Sparse(), symbol="XAUUSD",
                                        captured_at="2026-10-05T00:00:00Z")
        assert not spec.is_complete
        assert spec.trade_tick_value is None
        assert "trade_tick_value" in spec.missing_fields()

    def test_swap_mode_integers_are_named(self):
        cap = self._cap()
        swap = cap.swap_spec_from_mt5(self.FakeInfo(), symbol="EURUSD")
        assert swap.swap_mode is SwapMode.POINTS
        assert swap.swap_long == -7.5
        assert swap.is_complete

    def test_unknown_swap_mode_stays_unknown(self):
        cap = self._cap()

        class Weird:
            swap_long, swap_short, swap_mode, swap_rollover3days = 0, 0, 99, 3

        swap = cap.swap_spec_from_mt5(Weird(), symbol="EURUSD")
        assert swap.swap_mode is SwapMode.UNKNOWN
        assert not swap.is_complete

    def test_commission_is_missing_without_deals(self):
        cap = self._cap()
        spec = cap.commission_from_deals([], symbol="EURUSD", currency="USD")
        assert spec.status is AuthorityStatus.MISSING
        assert "MISSING" in spec.note

    def test_commission_is_measured_from_stable_deals(self):
        cap = self._cap()
        deals = [self.FakeDeal(1.0, -3.5), self.FakeDeal(0.5, -1.75),
                 self.FakeDeal(2.0, -7.0)]
        spec = cap.commission_from_deals(deals, symbol="EURUSD", currency="USD")
        assert spec.is_complete
        assert spec.mode is CommissionMode.PER_LOT_PER_SIDE
        assert spec.value == pytest.approx(3.5)
        assert spec.scales_linearly_with_closed_volume is True

    def test_unstable_commission_is_reported_missing_not_averaged(self):
        cap = self._cap()
        deals = [self.FakeDeal(1.0, -3.5), self.FakeDeal(1.0, -9.0)]
        spec = cap.commission_from_deals(deals, symbol="EURUSD", currency="USD")
        assert spec.status is AuthorityStatus.MISSING
        assert "not stable" in spec.note

    def test_all_zero_commission_is_a_captured_markup_account(self):
        cap = self._cap()
        deals = [self.FakeDeal(1.0, 0.0), self.FakeDeal(2.0, 0.0)]
        spec = cap.commission_from_deals(deals, symbol="EURUSD", currency="USD")
        assert spec.is_complete
        assert spec.mode is CommissionMode.ZERO_COMMISSION_SPREAD_MARKUP

    def test_slippage_is_missing_without_fills(self):
        cap = self._cap()
        auth = cap.slippage_from_deals([], [])
        assert auth.status is AuthorityStatus.MISSING
        assert auth.future_evidence_requirement

    def test_slippage_is_measured_from_matched_fills(self):
        cap = self._cap()
        deals = [self.FakeDeal(1.0, -3.5, price=1.10002, order=1),
                 self.FakeDeal(1.0, -3.5, price=1.10004, order=2)]
        orders = [self.FakeOrder(1, 1.10000), self.FakeOrder(2, 1.10000)]
        auth = cap.slippage_from_deals(deals, orders)
        assert auth.status is AuthorityStatus.CAPTURED
        assert auth.evidence_kind is SlippageEvidenceKind.EXECUTED_FILL_HISTORY
        assert auth.sample_size == 2
        assert auth.median_points > 0


# ---------------------------------------------------------------------------
# ingest round trip
# ---------------------------------------------------------------------------

class TestIngestRoundTrip:
    def test_bundle_ingest_produces_distributions_and_a_hash(self, tmp_path):
        sys.path.insert(0, str(SCRIPTS))
        try:
            import build_friction_authority as build
        finally:
            sys.path.remove(str(SCRIPTS))
        bundle = _make_bundle(tmp_path, rows=20)
        merged = build.load_bundles([bundle])
        assert merged["venue"].broker == "VT Markets Ltd"
        assert merged["venue"].account_class is AccountClass.DEMO
        assert merged["specs"]["EURUSD"].is_complete
        ev = merged["evidence"]["EURUSD"]
        assert len(ev.observations) == 20
        dist = ev.distributions(merged["specs"]["EURUSD"])
        assert dist["ALL"].n == 20
        assert dist["ALL"].p50 == pytest.approx(1.0)

    def test_bundles_from_different_venues_are_rejected(self, tmp_path):
        sys.path.insert(0, str(SCRIPTS))
        try:
            import build_friction_authority as build
        finally:
            sys.path.remove(str(SCRIPTS))
        a = _make_bundle(tmp_path / "a")
        b = _make_bundle(tmp_path / "b")
        meta = json.loads((b / "capture_metadata.json").read_text())
        meta["server"] = "OtherBroker-Live"
        (b / "capture_metadata.json").write_text(json.dumps(meta))
        (b / "BUNDLE_MANIFEST.json").write_text(
            json.dumps(build_manifest(b)))
        with pytest.raises(VenueIdentityMismatch):
            build.load_bundles([a, b])

    def test_end_to_end_build_with_evidence_establishes_the_authority(
            self, tmp_path, monkeypatch):
        """The MISSING state must be the evidence talking, not a dead path.

        Feed the pipeline a complete bundle and the status has to flip to
        FRICTION_AUTHORITY_ESTABLISHED with real distributions. Without
        this, 'everything is MISSING' could just mean 'nothing works'.
        """
        sys.path.insert(0, str(SCRIPTS))
        try:
            import build_friction_authority as build
        finally:
            sys.path.remove(str(SCRIPTS))

        bundle = tmp_path / "bundle"
        (bundle / "quotes").mkdir(parents=True)
        meta = {
            "schema_version": CAPTURE_SCHEMA_VERSION, "tool_version": "t/1",
            "broker": "VT Markets Ltd", "server": "VTMarkets-Live 3",
            "account_class": "LIVE", "account_type": "RAW",
            "account_currency": "USD", "terminal_build": 4260,
            "capture_started_utc": "2026-10-05T07:00:00Z",
            "capture_ended_utc": "2026-10-05T17:00:00Z",
            "symbols": list(SYMBOLS),
        }
        specs = {"EURUSD": fx5("EURUSD"), "GBPUSD": fx5("GBPUSD"),
                 "USDJPY": jpy3(), "XAUUSD": gold2()}
        (bundle / "capture_metadata.json").write_text(json.dumps(meta))
        (bundle / "symbol_metadata.json").write_text(
            json.dumps({s: v.as_dict() for s, v in specs.items()}))
        (bundle / "commission.json").write_text(json.dumps(
            {s: complete_commission(s).as_dict() for s in specs}))
        (bundle / "swap.json").write_text(json.dumps(
            {s: disabled_swap(s).as_dict() for s in specs}))
        (bundle / "slippage.json").write_text(
            json.dumps(complete_slippage(0.2, 0.9).as_dict()))
        quotes = {"EURUSD": (1.10000, 0.00010), "GBPUSD": (1.26000, 0.00014),
                  "USDJPY": (150.000, 0.012), "XAUUSD": (2000.00, 0.25)}
        for symbol, (bid, spread) in quotes.items():
            lines = [",".join(QUOTE_CSV_COLUMNS)]
            for hour in (3, 9, 14, 18, 22):      # one per session bucket
                for i in range(10):
                    ts = f"2026-10-05T{hour:02d}:{i:02d}:00Z"
                    wobble = spread * (1 + i / 20.0)
                    lines.append(f"{ts},{symbol},{bid},{bid + wobble:.5f},"
                                 f"{wobble},0,{''}")
            (bundle / "quotes" / f"{symbol}.csv").write_text(
                "\n".join(lines) + "\n")
        (bundle / "BUNDLE_MANIFEST.json").write_text(
            json.dumps(build_manifest(bundle)))

        out = tmp_path / "artifacts"
        monkeypatch.setattr(build, "OUT_DIR", out)
        rc = build.main(["--bundle", str(bundle),
                         "--strategy-closes-before-rollover", "yes",
                         "--strategy-contract-frozen"])
        assert rc == 0

        report = json.loads((out / "final_report.json").read_text())
        assert report["STATUS"] == "FRICTION_AUTHORITY_ESTABLISHED", \
            report["BLOCKERS"]
        assert report["FRICTION_AUTHORITY_COMPLETE"] == "YES"
        assert report["ECONOMIC_VERIFICATION_READY"] == "YES"
        assert report["SPREAD_AUTHORITY"] == "CAPTURED"
        assert report["COMMISSION_AUTHORITY"] == "CAPTURED"
        assert report["SLIPPAGE_AUTHORITY"] == "CAPTURED"
        assert report["SWAP_AUTHORITY"] == "NOT_APPLICABLE"
        assert report["ACCOUNT_CLASS"] == "LIVE"
        assert report["BLOCKERS"] == []

        for symbol in SYMBOLS:
            block = report["SPREAD"][symbol]
            assert block["N"] == 50
            assert block["P50"] is not None
            assert block["P95"] >= block["P90"] >= block["P50"]
        assert report["SPREAD"]["XAUUSD"]["unit"] == "instrument_units"
        assert report["SPREAD"]["EURUSD"]["unit"] == "pips"

        dists = json.loads((out / "spread_distribution.json").read_text())
        sessions = set(dists["symbols"]["EURUSD"]["sessions"])
        assert {"ASIAN", "LONDON", "OVERLAP", "NEW_YORK", "OTHER"} <= sessions

        # the whole point of the exercise: a priced round trip
        spread_p50 = dists["symbols"]["EURUSD"]["sessions"]["ALL"]["P50"]
        spec = specs["EURUSD"]
        plan = TradePlan(symbol="EURUSD", side=Side.LONG, entry_price=1.10000,
                         stop_price=1.09800, volume_lots=1.0,
                         exits=(ExitLeg(0.5, 1.10200, ExitKind.TARGET_PARTIAL),
                                ExitLeg(0.5, 1.10600, ExitKind.RUNNER)))
        res = compute_costs(
            plan, spec=spec, spread_price=spec.pips_to_price(spread_p50),
            commission=complete_commission("EURUSD"),
            slippage=complete_slippage(0.2, 0.9), swap=disabled_swap(),
            swap_applicability=SwapApplicability.NOT_APPLICABLE)
        assert res.gross_r == pytest.approx(2.0)
        assert res.net_r < res.gross_r

    def test_quote_csv_header_is_enforced(self, tmp_path):
        bundle = _make_bundle(tmp_path)
        path = bundle / "quotes" / "EURUSD.csv"
        path.write_text("wrong,header\n1,2\n")
        (bundle / "BUNDLE_MANIFEST.json").write_text(
            json.dumps(build_manifest(bundle)))
        from ag_edgelab.friction.authority.capture_schema import read_quote_csv
        with pytest.raises(BundleInvalid, match="header"):
            read_quote_csv(path)


# ---------------------------------------------------------------------------
# artifacts
# ---------------------------------------------------------------------------

REQUIRED_ARTIFACTS = (
    "friction_source_inventory.json", "vtmarkets_symbol_metadata.json",
    "spread_capture_manifest.json", "spread_distribution.json",
    "commission_authority.json", "slippage_authority.json",
    "swap_authority.json", "partial_runner_cost_contract.json",
    "friction_authority_contract.json", "friction_authority_hash.json",
    "economic_scenario_contract.json", "friction_readiness.json",
    "test_results.txt", "final_report.json", "final_report.md",
    "artifact_manifest.json",
)


class TestArtifacts:
    @pytest.mark.parametrize("name", REQUIRED_ARTIFACTS)
    def test_artifact_exists(self, name):
        assert (ARTIFACTS / name).is_file(), f"missing artifact {name}"

    @pytest.mark.parametrize("name", [a for a in REQUIRED_ARTIFACTS
                                      if a.endswith(".json")])
    def test_artifact_is_valid_json(self, name):
        json.loads((ARTIFACTS / name).read_text())

    def test_authority_hash_matches_the_contract(self):
        contract = json.loads(
            (ARTIFACTS / "friction_authority_contract.json").read_text())
        recorded = json.loads(
            (ARTIFACTS / "friction_authority_hash.json").read_text())
        assert (contract["FRICTION_AUTHORITY_SHA256"]
                == recorded["FRICTION_AUTHORITY_SHA256"])
        assert recorded["friction_authority_id"] == FRICTION_AUTHORITY_ID

    def test_authority_hash_is_reproducible_from_the_payload(self):
        import hashlib
        blob = json.loads(
            (ARTIFACTS / "friction_authority_contract.json").read_text())
        recorded = blob.pop("FRICTION_AUTHORITY_SHA256")
        blob.pop("blockers", None)
        digest = hashlib.sha256(json.dumps(
            blob, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert digest == recorded

    def test_missing_components_are_reported_as_missing(self):
        report = json.loads((ARTIFACTS / "final_report.json").read_text())
        for key in ("SPREAD_AUTHORITY", "COMMISSION_AUTHORITY",
                    "SLIPPAGE_AUTHORITY", "SWAP_AUTHORITY"):
            assert report[key] in {"MISSING", "CAPTURED", "DECLARED_BY_VENUE",
                                   "NOT_APPLICABLE"}
        if report["FRICTION_AUTHORITY_COMPLETE"] == "NO":
            assert report["ECONOMIC_VERIFICATION_READY"] == "NO"
            assert report["BLOCKERS"]

    def test_no_orders_were_placed(self):
        report = json.loads((ARTIFACTS / "final_report.json").read_text())
        assert report["ORDERS_PLACED"] == 0
        inventory = json.loads(
            (ARTIFACTS / "friction_source_inventory.json").read_text())
        assert inventory["access_mode"] == "READ_ONLY"
        assert inventory["credentials_requested"] is False

    def test_all_four_symbols_are_reported(self):
        report = json.loads((ARTIFACTS / "final_report.json").read_text())
        assert set(report["SPREAD"]) == set(SYMBOLS)
        for block in report["SPREAD"].values():
            assert set(block) >= {"N", "P50", "P90", "P95"}

    def test_spread_distribution_declares_its_policies(self):
        blob = json.loads((ARTIFACTS / "spread_distribution.json").read_text())
        assert "nearest-rank" in blob["quantile_method"]
        assert "COUNTED, never" in blob["outlier_policy"]
        assert "does not" in blob["quantile_selection_policy"]

    def test_commission_artifact_refuses_industry_defaults(self):
        blob = json.loads((ARTIFACTS / "commission_authority.json").read_text())
        assert "no industry-typical figure is substituted" in \
            blob["no_default_policy"]
        assert len(blob["questions_the_authority_must_answer"]) == 4

    def test_slippage_artifact_is_separate_from_spread(self):
        blob = json.loads((ARTIFACTS / "slippage_authority.json").read_text())
        assert blob["separate_from_spread"] is True
        if blob["status"] == "MISSING":
            assert blob["future_evidence_requirement"]

    def test_partial_runner_contract_demonstrates_its_invariants(self):
        blob = json.loads(
            (ARTIFACTS / "partial_runner_cost_contract.json").read_text())
        inv = blob["worked_example_illustrative"]["demonstrated_invariants"]
        assert inv["spread_identical_across_exit_shapes"] is True
        assert inv["commission_identical_across_exit_shapes"] is True
        assert blob["worked_example_illustrative"]["is_venue_evidence"] is False
        assert set(blob["exit_shapes_priced"]) == {
            "single_full_exit", "partial_then_runner", "stop_exit",
            "horizon_exit", "forced_close"}

    def test_scenario_contract_artifact_carries_its_hash(self):
        blob = json.loads(
            (ARTIFACTS / "economic_scenario_contract.json").read_text())
        assert re.fullmatch(r"[0-9a-f]{64}", blob["scenario_contract_sha256"])
        assert blob["preregistered_before_any_candidate_pnl"] is True
        assert {r["name"] for r in blob["rules"]} == {"BASELINE", "STRESSED"}

    def test_historical_limitation_is_recorded_in_artifacts(self):
        blob = json.loads(
            (ARTIFACTS / "economic_scenario_contract.json").read_text())
        hist = blob["historical_applicability"]
        assert hist["dataset_period"] == "2011-06-01/2018-06-06"
        assert hist["research_policy"]["is_measurement"] is False
        assert "HISTORICAL_FRICTION_TRUTH" in hist["limitation"]

    def test_artifact_manifest_hashes_match_the_files(self):
        """Every artifact hash in the manifest matches the file on disk.

        ``test_results.txt`` is exempt from the hash comparison: it is the
        transcript of this very run, so requiring it to match a hash
        sealed before the run is circular. Its presence and non-emptiness
        are checked instead, and the manifest still records the hash it
        had at seal time.
        """
        import hashlib
        manifest = json.loads(
            (ARTIFACTS / "artifact_manifest.json").read_text())
        names = {e["name"] for e in manifest["artifacts"]}
        checked = 0
        for entry in manifest["artifacts"]:
            path = ARTIFACTS / entry["name"]
            assert path.is_file(), entry["name"]
            if entry["name"] == "test_results.txt":
                assert path.stat().st_size > 0
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest == entry["sha256"], f"{entry['name']} changed"
            checked += 1
        assert "artifact_manifest.json" not in names
        assert "test_results.txt" in names
        assert checked >= 14, "the manifest must cover every other artifact"

    def test_final_report_md_renders_every_symbol(self):
        text = (ARTIFACTS / "final_report.md").read_text()
        for symbol in SYMBOLS:
            assert symbol in text
        assert "No orders were placed" in text


# ---------------------------------------------------------------------------
# governance preservation
# ---------------------------------------------------------------------------

class TestGovernancePreserved:
    def test_data_authority_r1_artifacts_are_intact(self):
        prior = ROOT / "artifacts" / "data_authority_r1"
        assert prior.is_dir()
        assert len(list(prior.glob("*.json"))) >= 15

    def test_oos_access_log_still_has_exactly_two_events(self):
        log = json.loads(
            (ROOT / "config" / "governance" / "oos_access_log.json").read_text())
        events = log["events"] if isinstance(log, dict) else log
        assert len(events) == 2
        assert all(e.get("holdout_touched") is False for e in events)

    def test_c3_rejection_is_preserved(self):
        ledger = json.loads(
            (ROOT / "config" / "governance" / "candidate_ledger.json").read_text())
        blob = json.dumps(ledger)
        assert "TARGET_POLICY_C3_V1" in blob
        assert "REJECTED_OOS" in blob

    def test_this_mission_added_no_dependency(self):
        text = (ROOT / "pyproject.toml").read_text()
        assert "MetaTrader5" not in text, (
            "the capture tool imports MetaTrader5 lazily and must never become "
            "a declared dependency of this package")

    def test_friction_authority_uses_only_stdlib_and_local_imports(self):
        """No new third-party dependency can hide in this package."""
        import ast

        # Standard library only. The point of this guard is that no
        # THIRD-PARTY dependency can hide in the authority package, so
        # stdlib additions are listed here explicitly as they are used.
        stdlib_ok = {"csv", "contextlib", "dataclasses", "datetime", "enum",
                     "hashlib", "json", "pathlib", "re", "statistics",
                     "typing"}
        pkg = ROOT / "src" / "ag_edgelab" / "friction" / "authority"
        seen: set[str] = set()
        for path in sorted(pkg.glob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    roots = [(node.module or "").split(".")[0]]
                else:
                    continue
                for root in roots:
                    if root in {"ag_edgelab", "__future__", ""}:
                        continue
                    seen.add(root)
                    assert root in stdlib_ok, f"{path.name} imports {root}"
        assert seen, "the guard must actually be resolving imports"

    def test_existing_friction_model_is_untouched(self):
        """The prior R-space friction module keeps working unchanged."""
        from ag_edgelab.friction import model
        assert hasattr(model, "apply_friction")
        assert hasattr(model, "FrictionScenario")
