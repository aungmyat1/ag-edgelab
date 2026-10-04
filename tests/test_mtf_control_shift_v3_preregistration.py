import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_v3_preregistration_is_structurally_zero_and_not_replayed():
    report = json.loads((ROOT / "artifacts/mtf_control_shift_v1/v3_hypothesis_report.json").read_text())
    assert report["location_pass"] == 170
    assert report["v2_structural_eligible"] == 18
    assert report["v3_structural_eligible"] == 0
    assert report["same_session_date"] == 0
    assert report["prior_session_date"] == 18
    assert report["future_date_invalid"] == 0
    assert report["economic_replay_started"] is False
    assert report["oos_opened"] is False
    assert report["holdout_touched"] is False


def test_v3_diff_from_v2_is_identity_plus_date_coupling():
    v2 = (ROOT / "strategies/ST_MTF_CONTROL_SHIFT_V2.yaml").read_text()
    v3 = (ROOT / "strategies/ST_MTF_CONTROL_SHIFT_V3.yaml").read_text()
    normalize = lambda s: "\n".join(x for x in s.splitlines() if not any(k in x for k in ("strategy_id:", "version:", "h1_shift_requires_active_session_date:")))
    assert normalize(v2) == normalize(v3)
    assert "max_h1_shift_age_bars: 24" in v2
    assert "max_h1_shift_age_bars: 24" in v3
    assert "h1_shift_requires_active_session_date: true" in v3
    assert hashlib.sha256((ROOT / "strategies/ST_MTF_CONTROL_SHIFT_V3.yaml").read_bytes()).hexdigest() == "65862fa02e6b38d0b1a3f06489c81ff3313384b392fa11df075674ac54f7c918"


def test_v3_date_authority_is_utc_and_holdout_closed():
    p = json.loads((ROOT / "artifacts/mtf_control_shift_v1/v3_preregistration.json").read_text())
    sem = p["timestamp_date_semantics"]
    assert sem["timezone_authority"].startswith("UTC")
    assert sem["equality"]
    assert sem["dst_behavior"]
    assert p["development_window"]["holdout_touched"] is False
