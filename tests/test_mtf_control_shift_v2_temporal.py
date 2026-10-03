import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_temporal_audit_covers_all_eighteen_cases():
    report = json.loads((ROOT / "artifacts/mtf_control_shift_v1/v2_temporal_coupling.json").read_text())
    assert report["cases"] == 18
    assert report["m15_after_session_distribution"]["<= 0"]["count"] == 18
    assert report["h1_shift_timing_distribution"][">240"]["count"] == 18
    assert report["grace_window_coverage"]["240"]["coverage_n"] == 0
    assert report["interpretation"]["primary_classification"] == "STALE_TRIGGER_SESSION_MISMATCH"


def test_temporal_audit_does_not_change_v2():
    pre = json.loads((ROOT / "artifacts/mtf_control_shift_v1/v2_preregistration.json").read_text())
    assert pre["new_strategy"]["strategy_id"] == "ST_MTF_CONTROL_SHIFT_V2"
    assert pre["single_changed_rule"]["new_value"] == 24
    source = (ROOT / "scripts/run_mtf_control_shift_v2_temporal_coupling.py").read_text()
    assert "order_send" not in source
    assert "execution_capability" not in source


def test_temporal_audit_preserves_holdout_boundary():
    report = json.loads((ROOT / "artifacts/mtf_control_shift_v1/v2_temporal_coupling.json").read_text())
    assert report["interpretation"]["holdout_touched"] is False
    assert all("2017-12" not in json.dumps(x) for x in report["cases_detail"])
