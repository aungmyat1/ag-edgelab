from datetime import datetime, timezone

import pytest

from ag_edgelab.contracts.dataset import DatasetArtifact, DatasetManifest, DatasetRange, DatasetRole


def manifest(**overrides):
    payload = dict(
        dataset_id="EURUSD_DEV_001", instrument="EURUSD", broker_symbol="EURUSD-VIP",
        asset_class="FX", provider="MT5_EXPORT", broker="VT_MARKETS",
        source_timezone="Europe/Athens", normalized_timezone="UTC",
        timeframes=("M15", "M1"),
        date_range=DatasetRange(
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 2, 1, tzinfo=timezone.utc),
        ),
        role=DatasetRole.DEVELOPMENT,
        artifacts=(
            DatasetArtifact(timeframe="M15", path="m15.parquet", sha256="a" * 64, rows=100),
            DatasetArtifact(timeframe="M1", path="m1.parquet", sha256="b" * 64, rows=1500),
        ),
    )
    payload.update(overrides)
    return DatasetManifest(**payload)


def test_dataset_manifest_hash_is_stable():
    a = manifest(metadata={"b": "2", "a": "1"})
    b = manifest(metadata={"a": "1", "b": "2"})
    assert a.manifest_sha256 == b.manifest_sha256


def test_sealed_oos_must_be_sealed():
    with pytest.raises(ValueError, match="must be sealed"):
        manifest(role=DatasetRole.SEALED_OOS, sealed=False)


def test_artifacts_must_match_declared_timeframes():
    with pytest.raises(ValueError, match="cover exactly"):
        manifest(timeframes=("M15",))


def test_range_must_be_ordered():
    with pytest.raises(ValueError, match="precedes"):
        DatasetRange(
            start=datetime(2026, 2, 1, tzinfo=timezone.utc),
            end=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
