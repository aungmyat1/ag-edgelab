from __future__ import annotations

"""Focused tests: source identity freeze, execution isolation, holdout seal."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from ag_edgelab.campaigns.session_trade_v2 import identity
from ag_edgelab.campaigns.session_trade_v2.dataset import (
    HoldoutAccessError,
    PARTITIONS,
    assert_partition_accessible,
    partition_bounds,
    slice_partition,
)

CAMPAIGN_DIR = Path(__file__).resolve().parents[1] / "src" / "ag_edgelab" / "campaigns" / "session_trade_v2"


# 1. source identity / hash freeze ------------------------------------------------

def test_identity_record_matches_frozen_source_of_truth():
    ident = identity.verify_identity()
    assert ident.source_repo == "aungmyat1/AG-profit-trading-assit"
    assert ident.source_pr == 33
    assert ident.source_commit == "e1ffe9f1e5ccfb9a336f1b4ae4289d41901ec5d2"
    assert ident.strategy_id == "SESSION_TRADE_V2"
    assert ident.strategy_version == "2.0.0"


def test_frozen_engine_is_byte_exact_copy_of_upstream(monkeypatch):
    # Any byte change to a frozen artifact must break verification.
    engine = identity.FROZEN_DIR / "engine.py"
    original = engine.read_bytes()
    try:
        engine.write_bytes(original + b"\n# tampered\n")
        with pytest.raises(identity.IdentityError, match="hash drift"):
            identity.verify_identity()
    finally:
        engine.write_bytes(original)
    assert identity.verify_identity().candidate_id.startswith("SESSION_TRADE_V2")


def test_frozen_engine_declares_frozen_ids():
    src = (identity.FROZEN_DIR / "engine.py").read_text()
    assert 'STRATEGY_ID = "SESSION_TRADE_V2"' in src
    assert 'STRATEGY_VERSION = "2.0.0"' in src


def test_execution_authority_frozen_off():
    assert identity.EXECUTION_AUTHORITY == {
        "demo_authorized": False,
        "live_authorized": False,
        "allow_order_send": False,
    }


# 26. no execution/order APIs reachable -------------------------------------------

FORBIDDEN_PATTERNS = (
    r"order_send\s*\(",          # an actual MT5 order_send() CALL (the frozen
                                 # "allow_order_send": False authority flag is allowed)
    r"MetaTrader5",
    r"\bmt5\b",
    r"import\s+requests",
    r"broker_login",
    r"\binitialize\s*\(",
)


def test_no_execution_or_broker_api_in_campaign_package():
    for path in sorted(CAMPAIGN_DIR.rglob("*.py")):
        text = path.read_text()
        for pattern in FORBIDDEN_PATTERNS:
            assert not re.search(pattern, text), f"{pattern} found in {path}"


def test_campaign_imports_no_network_module():
    code = "import ag_edgelab.campaigns.session_trade_v2.campaign, sys;" \
           "assert 'requests' not in sys.modules and 'MetaTrader5' not in sys.modules"
    env = {"PYTHONPATH": str(CAMPAIGN_DIR.parents[3] / "src"), "PATH": "/usr/bin:/bin"}
    subprocess.run([sys.executable, "-c", code], check=True, env=env)


# 27. holdout remains inaccessible during DEV --------------------------------------

def _bar(ts, close):
    from ag_edgelab.contracts.market import MarketBar
    return MarketBar(timestamp=ts, open=close, high=close, low=close, close=close)


def test_holdout_access_fails_closed():
    with pytest.raises(HoldoutAccessError):
        assert_partition_accessible("SEALED_HOLDOUT")


def test_slice_partition_rejects_holdout():
    from datetime import datetime, timezone

    ts = datetime(2017, 12, 15, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(HoldoutAccessError):
        slice_partition((_bar(ts, 1.0),), "SEALED_HOLDOUT")


def test_partitions_are_chronological_and_disjoint():
    roles = ["DEVELOPMENT", "OOS", "SEALED_HOLDOUT"]
    bounds = [partition_bounds(r) for r in roles]
    for (a0, a1), (b0, b1) in zip(bounds, bounds[1:]):
        assert a1 <= b0, "partitions must not overlap"
    assert bounds[0][0] < bounds[-1][1]
    assert set(PARTITIONS) == {"DEVELOPMENT", "OOS", "SEALED_HOLDOUT"}


def test_dev_partition_excludes_holdout_window():
    dev_start, dev_end = partition_bounds("DEVELOPMENT")
    holdout_start, holdout_end = partition_bounds("SEALED_HOLDOUT")
    assert dev_end <= holdout_start < holdout_end
