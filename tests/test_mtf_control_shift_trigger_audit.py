import json
from pathlib import Path

from mtf_control_shift.engine import H1_SHIFT_MAX_AGE_BARS
from mtf_control_shift.structure import SWING_STRENGTH, OB_LOOKBACK


ROOT = Path(__file__).parents[1]
AUDIT = ROOT / "artifacts/mtf_control_shift_v1/trigger_audit.json"


def test_trigger_audit_is_complete_and_deterministic():
    report = json.loads(AUDIT.read_text())
    assert report["location_pass_count"] == 170
    assert report["cases_audited"] == 170
    assert sum(v["count"] for v in report["failure_reasons"].values()) == 170
    assert report["parity"] == {"MATCH": 170}
    assert report["causality"] == {"PASS": 170}
    assert report["holdout_touched"] is False


def test_audit_uses_frozen_trigger_parameters():
    assert SWING_STRENGTH == 2
    assert OB_LOOKBACK == 6
    assert H1_SHIFT_MAX_AGE_BARS == 4


def test_audit_has_no_execution_authority():
    source = (ROOT / "scripts/run_mtf_control_shift_v1_trigger_audit.py").read_text()
    assert "order_send" not in source
    assert "execution_gateway" not in source
