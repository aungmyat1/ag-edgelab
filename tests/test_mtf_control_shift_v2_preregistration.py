import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_v2_preregistration_is_before_replay_and_holdout_closed():
    p = json.loads((ROOT / "artifacts/mtf_control_shift_v1/v2_preregistration.json").read_text())
    assert p["preregistration_status"] == "PREREGISTERED_BEFORE_ECONOMIC_REPLAY"
    assert p["economic_replay_started"] is False
    assert p["oos_opened"] is False
    assert p["development_window"]["holdout_touched"] is False


def test_v2_has_only_the_registered_age_change():
    v1 = (ROOT / "strategies/ST_MTF_CONTROL_SHIFT_V1.yaml").read_text()
    v2 = (ROOT / "strategies/ST_MTF_CONTROL_SHIFT_V2.yaml").read_text()
    assert "strategy_id: ST_MTF_CONTROL_SHIFT_V1" in v1
    assert "version: \"1.0.0\"" in v1
    assert "max_h1_shift_age_bars: 4" in v1
    assert "strategy_id: ST_MTF_CONTROL_SHIFT_V2" in v2
    assert "version: \"2.0.0\"" in v2
    assert "max_h1_shift_age_bars: 24" in v2
    # All non-identity/non-age lines remain byte-equivalent.
    normalize = lambda s: "\n".join(x for x in s.splitlines() if not any(k in x for k in ("strategy_id:", "version:", "max_h1_shift_age_bars:")))
    assert normalize(v1) == normalize(v2)
