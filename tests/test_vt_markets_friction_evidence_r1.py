"""Tests for VT_MARKETS_FRICTION_EVIDENCE_R1.

The capture half of this mission cannot run here — MetaTrader5 is
Windows-only and there is no terminal. What CAN be tested on any
platform is every pure part: symbol resolution, immutable daily
bundles, tick conversion, distribution arithmetic and the read-only
guarantees. Those are also the parts most likely to be silently wrong
on the owner's machine, so they are covered hard.

Synthetic fixtures appear below. They are unit fixtures for the
plumbing, never evidence about any venue or any strategy.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ag_edgelab.friction.authority import daily
from ag_edgelab.friction.authority.capture_schema import BundleInvalid, verify_bundle
from ag_edgelab.friction.authority.quotes import session_for
from ag_edgelab.friction.authority.resolution import (
    CANONICAL_FX, EXTENDED_SYMBOL_FIELDS, ResolutionStatus, discover_crypto,
    normalize, raw_symbol_info, resolve_all, resolve_one,
)
from ag_edgelab.universal.trigger_v0_4 import session_label

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
ARTIFACTS = REPO / "artifacts" / "vt_markets_friction_evidence_r1"


def sym(name, *, visible=True, select=True, path=None):
    return {"name": name, "visible": visible, "select": select,
            "path": path or f"Forex\\{name}"}


# ---------------------------------------------------------------------------
# §1 symbol resolution
# ---------------------------------------------------------------------------

def test_normalize_strips_decoration():
    assert normalize("EURUSD-VIP") == "EURUSDVIP"
    assert normalize("eurusd.r") == "EURUSDR"
    assert normalize("") == ""


def test_plain_names_resolve_exactly():
    r = resolve_one("EURUSD", [sym("EURUSD"), sym("GBPUSD")])
    assert r.status is ResolutionStatus.RESOLVED
    assert r.broker_symbol == "EURUSD"


@pytest.mark.parametrize("broker", [
    "EURUSD-VIP", "EURUSD.r", "EURUSDx", "EURUSD.pro", "EURUSD_raw", "EURUSDm",
])
def test_any_published_suffix_resolves(broker):
    r = resolve_one("EURUSD", [sym(broker)])
    assert r.broker_symbol == broker


def test_suffix_is_never_invented():
    """Nothing resolves if the terminal publishes nothing matching."""
    r = resolve_one("EURUSD", [sym("GBPUSD-VIP"), sym("USDJPY-VIP")])
    assert r.status is ResolutionStatus.NOT_FOUND
    assert r.broker_symbol is None
    assert "guessed" in r.note or "constructed" in r.note


def test_numeric_suffix_is_treated_as_a_different_contract():
    r = resolve_one("EURUSD", [sym("EURUSD2"), sym("EURUSD500")])
    assert r.status is ResolutionStatus.NOT_FOUND


def test_ambiguity_is_reported_with_every_candidate():
    r = resolve_one("EURUSD", [sym("EURUSD.r", visible=False), sym("EURUSD-VIP")])
    assert r.status is ResolutionStatus.RESOLVED_AMBIGUOUS
    assert len(r.candidates) == 2
    assert r.broker_symbol == "EURUSD-VIP"      # visible wins over hidden


def test_exact_match_beats_a_decorated_one():
    r = resolve_one("EURUSD", [sym("EURUSD-VIP"), sym("EURUSD")])
    assert r.broker_symbol == "EURUSD"


def test_resolution_is_order_independent():
    a = [sym("EURUSD-VIP"), sym("EURUSD.r", visible=False)]
    assert (resolve_one("EURUSD", a).broker_symbol
            == resolve_one("EURUSD", list(reversed(a))).broker_symbol)


def test_gold_alias_resolves_to_xauusd():
    r = resolve_one("XAUUSD", [sym("GOLD-VIP")])
    assert r.broker_symbol == "GOLD-VIP"


def test_crypto_is_discovered_not_assumed():
    found = discover_crypto([sym("BTCUSD-VIP"), sym("ETHUSD-VIP"),
                             sym("EURUSD-VIP"), sym("XRPUSDT")])
    names = {c.broker_symbol for c in found}
    assert names == {"BTCUSD-VIP", "ETHUSD-VIP", "XRPUSDT"}


def test_resolve_all_reports_unresolved_rather_than_substituting():
    out = resolve_all(CANONICAL_FX, [sym("EURUSD-VIP"), sym("GBPUSD-VIP")])
    assert out["all_resolved"] is False
    assert set(out["unresolved"]) == {"USDJPY", "XAUUSD"}
    assert "USDJPY" not in out["mapping"]


def test_empty_terminal_resolves_nothing():
    out = resolve_all(CANONICAL_FX, [])
    assert out["mapping"] == {}
    assert len(out["unresolved"]) == 4


# ---------------------------------------------------------------------------
# §3 raw symbol_info
# ---------------------------------------------------------------------------

class FakeInfo:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_every_required_symbol_field_is_requested():
    for required in ("digits", "point", "trade_tick_size", "trade_tick_value",
                     "trade_tick_value_profit", "trade_tick_value_loss",
                     "trade_contract_size", "currency_base", "currency_profit",
                     "currency_margin", "volume_min", "volume_max",
                     "volume_step", "swap_long", "swap_short", "swap_mode",
                     "swap_rollover3days", "trade_stops_level",
                     "trade_freeze_level"):
        assert required in EXTENDED_SYMBOL_FIELDS


def test_absent_fields_are_none_never_zero():
    snap = raw_symbol_info(FakeInfo(digits=5, point=1e-5),
                           broker_symbol="EURUSD-VIP")
    assert snap["digits"] == 5
    assert snap["trade_tick_value"] is None
    assert snap["swap_long"] is None
    assert 0 not in (snap["trade_tick_value"], snap["swap_long"])
    assert snap["_complete"] is False
    assert "trade_tick_value" in snap["_missing_fields"]


def test_complete_snapshot_reports_complete():
    snap = raw_symbol_info(
        FakeInfo(**{f: 1 for f in EXTENDED_SYMBOL_FIELDS}),
        broker_symbol="EURUSD")
    assert snap["_complete"] is True
    assert snap["_missing_fields"] == []


# ---------------------------------------------------------------------------
# §5 immutable daily bundles
# ---------------------------------------------------------------------------

def test_bundle_name_is_date_stamped():
    assert daily.bundle_name(datetime(2026, 10, 6, tzinfo=UTC)) == \
        "friction_capture_20261006"
    assert daily.bundle_name(datetime(2026, 10, 6, tzinfo=UTC), 3) == \
        "friction_capture_20261006_003"


def test_repeated_runs_append_rather_than_overwrite(tmp_path):
    day = datetime(2026, 10, 6, tzinfo=UTC)
    first = daily.next_bundle_dir(tmp_path, day)
    first.mkdir()
    second = daily.next_bundle_dir(tmp_path, day)
    assert first != second
    assert second.name.endswith("_002")


def test_sealing_twice_with_identical_content_is_idempotent(tmp_path):
    b = tmp_path / "friction_capture_20261006"
    b.mkdir()
    (b / "capture_metadata.json").write_text("{}")
    assert daily.seal_bundle(b)["manifest_root_sha256"] == \
        daily.seal_bundle(b)["manifest_root_sha256"]


def test_resealing_modified_evidence_raises(tmp_path):
    b = tmp_path / "friction_capture_20261006"
    b.mkdir()
    (b / "capture_metadata.json").write_text("{}")
    daily.seal_bundle(b)
    (b / "capture_metadata.json").write_text('{"tampered": true}')
    with pytest.raises(daily.BundleSealed):
        daily.seal_bundle(b)


def test_registry_is_append_only(tmp_path):
    b = tmp_path / "friction_capture_20261006"
    b.mkdir()
    meta = {"symbols": ["EURUSD"], "quote_counts": {"EURUSD": 3},
            "capture_started_utc": "2026-10-06T00:00:00Z",
            "capture_ended_utc": "2026-10-06T01:00:00Z"}
    (b / "capture_metadata.json").write_text(json.dumps(meta))
    m = daily.seal_bundle(b)
    row = daily.row_for(b, m, meta)
    daily.append_registry(tmp_path, row)
    daily.append_registry(tmp_path, row)            # idempotent
    assert daily.load_registry(tmp_path)["bundle_count"] == 1

    forged = daily.RegistryRow(
        bundle=row.bundle, manifest_root_sha256="f" * 64, byte_size=1,
        file_count=1, capture_started_utc=None, capture_ended_utc=None,
        symbols=(), sample_count=0, quote_counts={})
    with pytest.raises(daily.RegistryViolation):
        daily.append_registry(tmp_path, forged)


def test_registry_records_the_required_fields(tmp_path):
    b = tmp_path / "friction_capture_20261006"
    b.mkdir()
    meta = {"symbols": ["EURUSD", "XAUUSD"],
            "quote_counts": {"EURUSD": 10, "XAUUSD": 7},
            "capture_started_utc": "2026-10-06T00:00:00Z",
            "capture_ended_utc": "2026-10-06T01:00:00Z"}
    (b / "capture_metadata.json").write_text(json.dumps(meta))
    row = daily.row_for(b, daily.seal_bundle(b), meta).as_dict()
    for field in ("manifest_root_sha256", "byte_size", "capture_started_utc",
                  "capture_ended_utc", "symbols", "sample_count"):
        assert field in row
    assert row["sample_count"] == 17


def test_tampering_is_caught_by_verification(tmp_path):
    b = tmp_path / "friction_capture_20261006"
    b.mkdir()
    meta = {"symbols": [], "quote_counts": {}}
    (b / "capture_metadata.json").write_text(json.dumps(meta))
    daily.append_registry(tmp_path, daily.row_for(b, daily.seal_bundle(b), meta))
    assert daily.verify_registry(tmp_path)["all_verified"] is True
    (b / "capture_metadata.json").write_text('{"tampered": 1}')
    v = daily.verify_registry(tmp_path)
    assert v["all_verified"] is False and v["problems"]


def test_capture_lock_blocks_a_concurrent_run(tmp_path):
    with daily.capture_lock(tmp_path):
        with pytest.raises(daily.CaptureLocked):
            with daily.capture_lock(tmp_path):
                pass


def test_capture_lock_releases(tmp_path):
    with daily.capture_lock(tmp_path):
        pass
    with daily.capture_lock(tmp_path):
        pass                                        # no raise


# ---------------------------------------------------------------------------
# §4 tick conversion + session authority
# ---------------------------------------------------------------------------

def _cap():
    sys.path.insert(0, str(SCRIPTS))
    try:
        import capture_vtmarkets_friction as cap
        return cap
    finally:
        sys.path.remove(str(SCRIPTS))


class FakeTick:
    def __init__(self, bid, ask, time_msc):
        self.bid, self.ask, self.time_msc = bid, ask, time_msc


def test_ticks_convert_from_milliseconds_utc():
    cap = _cap()
    rows, skipped = cap.ticks_to_observations(
        [FakeTick(1.1000, 1.1001, 1_600_000_000_000)], symbol="EURUSD")
    assert skipped == 0 and len(rows) == 1
    ts, bid, ask = rows[0]
    assert ts.tzinfo is not None and ts.year == 2020
    assert (bid, ask) == (1.1000, 1.1001)


def test_one_sided_ticks_are_skipped_not_fabricated():
    cap = _cap()
    rows, skipped = cap.ticks_to_observations(
        [FakeTick(1.1, 0.0, 1_600_000_000_000),
         FakeTick(0.0, 1.1, 1_600_000_000_001),
         FakeTick(1.1000, 1.1001, 1_600_000_000_002)], symbol="EURUSD")
    assert len(rows) == 1 and skipped == 2


def test_empty_tick_history_is_handled():
    cap = _cap()
    assert _cap().ticks_to_observations(None, symbol="EURUSD") == ([], 0)


def test_the_two_session_authorities_genuinely_disagree():
    """Documented conflict — if this ever stops failing, re-check the report."""
    seven = datetime(2017, 1, 3, 7, 30, tzinfo=UTC)
    twelve = datetime(2017, 1, 3, 12, 30, tzinfo=UTC)
    assert session_label(seven) == "ASIAN" and str(session_for(seven)) == "LONDON"
    assert session_label(twelve) == "LONDON" and str(session_for(twelve)) == "OVERLAP"


def test_no_third_session_scheme_was_invented():
    src = (REPO / "src/ag_edgelab/friction/authority/daily.py").read_text()
    src += (REPO / "src/ag_edgelab/friction/authority/resolution.py").read_text()
    assert "LONDON_NEWYORK_OVERLAP" not in src
    assert "SESSION_BOUNDS" not in src


def test_quotes_carry_both_session_labels():
    src = (SCRIPTS / "capture_vtmarkets_friction.py").read_text()
    assert "session_governed_v03" in src
    assert "session_label(ts)" in src


# ---------------------------------------------------------------------------
# read-only guarantees (mission FORBIDDEN list)
# ---------------------------------------------------------------------------

def _executable_source(path: Path) -> str:
    import io
    import tokenize
    out = []
    with path.open("rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    return " ".join(out)


@pytest.mark.parametrize("primitive", [
    "order_send", "order_check", "TRADE_ACTION_DEAL", "TRADE_ACTION_PENDING",
    "TRADE_ACTION_SLTP", "TRADE_ACTION_MODIFY", "TRADE_ACTION_REMOVE",
    "TRADE_ACTION_CLOSE_BY", "position_close", "positions_modify",
])
def test_no_ordering_primitive_anywhere_in_the_capture_path(primitive):
    for path in (SCRIPTS / "capture_vtmarkets_friction.py",
                 SCRIPTS / "build_vt_markets_friction_evidence.py",
                 REPO / "src/ag_edgelab/friction/authority/resolution.py",
                 REPO / "src/ag_edgelab/friction/authority/daily.py"):
        assert primitive not in _executable_source(path), f"{path.name}"


def test_capture_tool_calls_only_reader_mt5_functions():
    src = _executable_source(SCRIPTS / "capture_vtmarkets_friction.py")
    called = set(re.findall(r"mt5\s*\.\s*(\w+)\s*\(", src))
    allowed = {"initialize", "shutdown", "last_error", "account_info",
               "terminal_info", "symbol_info", "symbol_info_tick",
               "symbol_select", "symbols_get", "copy_ticks_range",
               "history_deals_get", "history_orders_get"}
    assert called <= allowed, f"non-reader MT5 calls: {called - allowed}"


def test_login_is_redacted_never_persisted():
    src = (SCRIPTS / "capture_vtmarkets_friction.py").read_text()
    assert '"account_login": "REDACTED"' in src
    assert "login_redacted" in src


def test_capture_exits_cleanly_without_metatrader5(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "capture_vtmarkets_friction.py"),
         "--root", str(tmp_path / "nope")],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2
    assert "MetaTrader5 is not installed" in proc.stderr
    assert not (tmp_path / "nope").exists()


# ---------------------------------------------------------------------------
# §6 distributions + §7/§8 authority honesty
# ---------------------------------------------------------------------------

def _builder():
    sys.path.insert(0, str(SCRIPTS))
    try:
        import build_vt_markets_friction_evidence as b
        return b
    finally:
        sys.path.remove(str(SCRIPTS))


def test_percentiles_are_ordered_and_bounded():
    b = _builder()
    rows = [{"bid": "1.1000", "ask": f"1.100{i % 9 + 1}",
             "session_governed_v03": "LONDON"} for i in range(200)]
    d = b.distributions({"EURUSD": rows})["EURUSD"]
    s = d["by_session"]["ALL"]
    assert s["MIN"] <= s["P25"] <= s["P50"] <= s["P75"] <= s["P90"] <= s["MAX"]
    assert s["N"] == 200


def test_invalid_and_zero_spreads_are_counted_separately():
    b = _builder()
    rows = [
        {"bid": "1.1000", "ask": "1.1000", "session_governed_v03": "LONDON"},
        {"bid": "1.1002", "ask": "1.1000", "session_governed_v03": "LONDON"},
        {"bid": "0", "ask": "1.1", "session_governed_v03": "LONDON"},
        {"bid": "1.1000", "ask": "1.1001", "session_governed_v03": "LONDON"},
    ]
    d = b.distributions({"EURUSD": rows})["EURUSD"]
    assert d["ZERO_SPREAD_N"] == 1
    assert d["INVALID_QUOTE_N"] == 2            # crossed + nonpositive
    assert d["by_session"]["ALL"]["N"] == 2     # zero kept, invalid excluded


def test_outliers_are_flagged_not_removed():
    b = _builder()
    rows = [{"bid": "1.1000", "ask": "1.1001",
             "session_governed_v03": "LONDON"} for _ in range(50)]
    rows.append({"bid": "1.1000", "ask": "1.2000",
                 "session_governed_v03": "LONDON"})
    d = b.distributions({"EURUSD": rows})["EURUSD"]
    assert d["OUTLIER_N"] >= 1
    assert d["by_session"]["ALL"]["N"] == 51    # still counted


def test_no_bundles_yields_missing_not_zero():
    b = _builder()
    status = b.authority_status({"quotes": {}}, {})
    assert status["SPREAD_AUTHORITY"] == "MISSING"
    assert status["FRICTION_AUTHORITY_COMPLETE"] is False
    assert status["missing_is_not_zero"] is True


def test_commission_and_slippage_are_never_defaulted():
    b = _builder()
    status = b.authority_status({"quotes": {}}, {})
    assert status["COMMISSION_AUTHORITY"] == "MISSING"
    assert status["SLIPPAGE_AUTHORITY"] == "MISSING"
    assert "industry default" in status["rationale"]["COMMISSION"]
    assert "cannot establish" in status["rationale"]["SLIPPAGE"]


def test_slippage_is_not_inferred_from_spread():
    src = (SCRIPTS / "build_vt_markets_friction_evidence.py").read_text()
    assert "Quote history" in src and "cannot establish it" in src


# ---------------------------------------------------------------------------
# end-to-end over a synthetic bundle (plumbing fixture, not venue evidence)
# ---------------------------------------------------------------------------

def test_sealed_bundle_round_trips_through_ingest(tmp_path):
    b = _builder()
    bundle = tmp_path / "friction_capture_20261006"
    (bundle / "quotes").mkdir(parents=True)
    meta = {"schema_version": "VT_MARKETS_FRICTION_CAPTURE_V1",
            "tool_version": "capture_vtmarkets_friction/2.0.0",
            "broker": "VT Markets", "server": "VTMarkets-Demo",
            "account_class": "DEMO", "account_type": 0,
            "account_currency": "USD", "terminal_build": 4000,
            "symbols": ["EURUSD"], "quote_counts": {"EURUSD": 3},
            "capture_started_utc": "2026-10-06T00:00:00Z",
            "capture_ended_utc": "2026-10-06T01:00:00Z"}
    (bundle / "capture_metadata.json").write_text(json.dumps(meta))
    for name in ("symbol_metadata", "commission", "swap", "slippage"):
        (bundle / f"{name}.json").write_text("{}")
    (bundle / "quotes" / "EURUSD.csv").write_text(
        "timestamp_utc,symbol,bid,ask,spread_price,spread_points,session,"
        "session_governed_v03\n"
        "2026-10-06T09:00:00Z,EURUSD,1.1000,1.1001,0.0001,1.0,LONDON,LONDON\n"
        "2026-10-06T09:00:01Z,EURUSD,1.1000,1.1002,0.0002,2.0,LONDON,LONDON\n"
        "2026-10-06T14:00:00Z,EURUSD,1.1000,1.1003,0.0003,3.0,OVERLAP,"
        "LONDON_NEWYORK_OVERLAP\n")
    daily.append_registry(tmp_path, daily.row_for(bundle, daily.seal_bundle(bundle), meta))

    loaded = b.load_bundles(tmp_path)
    assert loaded["verified"] == 1 and loaded["registry_all_verified"]
    dist = b.distributions(loaded["quotes"])["EURUSD"]
    assert dist["N"] == 3
    assert set(dist["by_session"]) == {"ALL", "LONDON", "LONDON_NEWYORK_OVERLAP"}
    assert b.authority_status(loaded, {"EURUSD": dist})["SPREAD_AUTHORITY"] == "CAPTURED"


def test_a_tampered_bundle_is_refused_by_ingest(tmp_path):
    b = _builder()
    bundle = tmp_path / "friction_capture_20261006"
    bundle.mkdir()
    (bundle / "capture_metadata.json").write_text(json.dumps({
        "schema_version": "VT_MARKETS_FRICTION_CAPTURE_V1",
        "tool_version": "t", "broker": "VT Markets", "server": "S",
        "account_class": "DEMO", "account_type": 0, "account_currency": "USD",
        "terminal_build": 4000, "symbols": [],
        "capture_started_utc": "2026-10-06T00:00:00Z",
        "capture_ended_utc": "2026-10-06T01:00:00Z"}))
    for name in ("symbol_metadata", "commission", "swap", "slippage"):
        (bundle / f"{name}.json").write_text("{}")
    daily.seal_bundle(bundle)
    (bundle / "commission.json").write_text('{"forged": true}')
    loaded = b.load_bundles(tmp_path)
    assert loaded["verified"] == 0
    assert loaded["errors"]


# ---------------------------------------------------------------------------
# artifacts
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not ARTIFACTS.is_dir(), reason="report not generated")
@pytest.mark.parametrize("name", [
    "capture_environment.json", "session_authority_conflict.json",
    "symbol_resolution.json", "capture_registry_status.json",
    "spread_distribution.json", "friction_authority_status.json",
    "final_report.json", "final_report.md", "artifact_manifest.json",
])
def test_artifact_present(name):
    assert (ARTIFACTS / name).is_file()


@pytest.mark.skipif(not (ARTIFACTS / "final_report.json").is_file(),
                    reason="report not generated")
def test_report_claims_no_order_calls_and_no_mutation():
    r = json.loads((ARTIFACTS / "final_report.json").read_text())
    assert r["ORDER_CALLS_EXECUTED"] == "NO"
    assert r["BROKER_MUTATION"] == "NO"
    assert r["FRICTION_AUTHORITY_COMPLETE"] is False
    for s in CANONICAL_FX:
        assert r[f"{s}_SPREAD_N"] == 0


@pytest.mark.skipif(not (ARTIFACTS / "session_authority_conflict.json").is_file(),
                    reason="report not generated")
def test_session_conflict_is_reported_not_resolved_silently():
    c = json.loads((ARTIFACTS / "session_authority_conflict.json").read_text())
    assert c["conflict_detected"] is True
    assert c["disagreeing_hours"] == [7, 12]
    assert c["prompt_matches_neither"] is True
