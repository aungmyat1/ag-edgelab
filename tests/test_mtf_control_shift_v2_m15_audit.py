import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_all_v2_h1_shift_cases_are_reconciled():
    report = json.loads((ROOT / "artifacts/mtf_control_shift_v1/v2_m15_refinement_audit.json").read_text())
    assert report["h1_shift_pass"] == 18
    assert report["cases_audited"] == 18
    assert report["parity"] == {"MATCH": 18}
    assert report["causality"] == {"PASS": 18}
    assert report["failure_reasons"]["SESSION_WINDOW_EXPIRED"]["count"] == 18


def test_m15_audit_does_not_add_entry_or_execution_semantics():
    source = (ROOT / "scripts/run_mtf_control_shift_v2_m15_audit.py").read_text()
    assert "order_send" not in source
    assert "limit" not in source.lower()


def test_m15_source_gate_is_session_creation_time_not_retest():
    source = (ROOT / "src/mtf_control_shift/engine.py").read_text()
    assert "z.created_time >= h1_shift.created_time" in source
    assert "_in_window(z.created_time, cycle)" in source
