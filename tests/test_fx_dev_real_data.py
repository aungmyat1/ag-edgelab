"""Real HistData 2017 tests — run only when the pinned zips are present.

CI stays green without the archives: every test here is skipped unless
``data/external/histdata_fx_2017`` holds the hash-pinned zips (acquire via
``scripts/acquire_histdata_fx_2017.sh``). Nothing synthetic substitutes for
the real identity checks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ag_edgelab.data.fx_histdata_2017 import (PARTITIONS, aggregate_m15,
                                              derive_fx_timeframe, load_histdata_m1,
                                              quality_gate_m1, slice_partition,
                                              verify_source_identity)

UTC = timezone.utc
ZIP_DIR = Path(__file__).resolve().parents[1] / "data" / "external" / "histdata_fx_2017"
EURUSD_ZIP = ZIP_DIR / "HISTDATA_COM_ASCII_EURUSD_M1_2017.zip"

pytestmark = pytest.mark.skipif(
    not EURUSD_ZIP.is_file(),
    reason="pinned HistData zips absent; run scripts/acquire_histdata_fx_2017.sh")


@pytest.fixture(scope="module")
def eurusd_m1():
    verify_source_identity(EURUSD_ZIP, "EURUSD")
    return load_histdata_m1(EURUSD_ZIP)


class TestRealIdentityAndQuality:
    def test_identity_matches_pr10_pin(self):
        sha = verify_source_identity(EURUSD_ZIP, "EURUSD")
        assert sha == "0dcd66dc67d7af4716404a5315d376ee1e7eaebe292afbda3c1003d2dfa16f57"

    def test_known_row_count(self, eurusd_m1):
        assert len(eurusd_m1) == 371635  # frozen PR #10 quality report

    def test_quality_gates_pass_on_real_feed(self, eurusd_m1):
        report = quality_gate_m1(eurusd_m1, "EURUSD")
        assert report["m1_duplicate_timestamps"] == 0

    def test_all_timestamps_utc_inside_2017_window(self, eurusd_m1):
        assert eurusd_m1[0].timestamp >= datetime(2016, 12, 31, tzinfo=UTC)
        assert eurusd_m1[-1].timestamp < datetime(2018, 1, 1, tzinfo=UTC)


class TestRealDerivation:
    @pytest.fixture(scope="class")
    def dev_frames(self, eurusd_m1):
        m15 = aggregate_m15(slice_partition(eurusd_m1, "DEVELOPMENT"))
        frames = {"M15": m15}
        for tf in ("H1", "H4", "D1"):
            frames[tf], _ = derive_fx_timeframe(m15, tf, "EURUSD")
        return frames

    def test_dev_slice_respects_partition(self, dev_frames):
        start, end = PARTITIONS["DEVELOPMENT"]
        m15 = dev_frames["M15"]
        assert m15 and start <= m15[0].timestamp and m15[-1].timestamp < end

    def test_mtf_cardinality_is_sane(self, dev_frames):
        assert len(dev_frames["M15"]) > len(dev_frames["H1"]) > len(dev_frames["H4"]) \
            > len(dev_frames["D1"]) > 100

    def test_no_weekend_d1_bars(self, dev_frames):
        # FX has no Saturday trading; a Saturday D1 bar would mean fill/lookahead
        assert all(b.timestamp.weekday() != 5 for b in dev_frames["D1"])

    def test_campaign_runs_on_real_subwindow(self, dev_frames):
        from ag_edgelab.universal.fx_dev_campaign import (decisions_from_truncated_frames,
                                                          run_fx_symbol_campaign)
        start, _ = PARTITIONS["DEVELOPMENT"]
        end = datetime(2017, 4, 1, tzinfo=UTC)
        sub = {tf: tuple(b for b in bars if b.timestamp < end)
               for tf, bars in dev_frames.items()}
        result = run_fx_symbol_campaign(sub, "EURUSD", start, end)
        counts = [r["n"] for r in result.funnel]
        assert counts[0] > 0 and all(a >= b for a, b in zip(counts, counts[1:]))
        obs = result.observations[len(result.observations) // 2]
        assert decisions_from_truncated_frames(sub, obs.observed_at, obs.price) \
            == obs.directions
