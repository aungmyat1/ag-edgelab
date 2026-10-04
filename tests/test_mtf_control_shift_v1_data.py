from datetime import datetime, timezone

from ag_edgelab.data.fx_histdata import (
    EXPECTED_RAW_SHA256, M15_REQUIRED, MIRROR, NY, closed, derive_all,
)
from ag_edgelab.contracts.market import MarketBar


def test_pr10_raw_identity_is_pinned():
    assert MIRROR == "parrondo/deeptrading"
    assert EXPECTED_RAW_SHA256 == {
        "EURUSD": "0dcd66dc67d7af4716404a5315d376ee1e7eaebe292afbda3c1003d2dfa16f57",
        "GBPUSD": "e5ba3800e37fae0e326dbaa234952ca04e8f378c08b036530a2811206110c10b",
        "USDJPY": "477a1f515586f06d67cb75b3662260160e1e29e63c51804a30a5e7d69b09df5f",
        "XAUUSD": "a39c1ccaaeb022c83309685107c9e619c2bcff8b2fd94fbd7405a721a4fe70ff",
    }


def test_new_york_dst_normalization_is_explicit():
    winter = datetime(2017, 1, 3, 12, tzinfo=NY).astimezone(timezone.utc)
    summer = datetime(2017, 7, 3, 12, tzinfo=NY).astimezone(timezone.utc)
    assert winter.hour == 17
    assert summer.hour == 16


def test_closed_accessor_hides_incomplete_bar():
    bars = (MarketBar(timestamp=datetime(2017, 3, 1, 2, tzinfo=timezone.utc), open=1, high=2, low=0, close=1),)
    assert len(closed(bars, "H1", datetime(2017, 3, 1, 2, 59, tzinfo=timezone.utc))) == 0
    assert len(closed(bars, "H1", datetime(2017, 3, 1, 3, 0, tzinfo=timezone.utc))) == 1


def test_no_forward_fill_and_m15_contract_is_named():
    assert M15_REQUIRED == 13
    # A derivation is only made from observed bars; a missing slot is not copied.
    m1 = tuple(MarketBar(timestamp=datetime(2017, 1, 2, 0, i, tzinfo=timezone.utc), open=1, high=2, low=0, close=1) for i in range(12))
    result, lineage = derive_all(m1, "EURUSD", EXPECTED_RAW_SHA256["EURUSD"])
    assert result["M15"] == ()
    assert lineage["M15"].incomplete_buckets_rejected == 1
