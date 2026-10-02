from __future__ import annotations

from ag_edgelab.contracts.dataset import DatasetRole
from ag_edgelab.contracts.experiment import ExperimentManifest, ExperimentStatus


def assert_exploration_allowed(*, dataset_role: DatasetRole) -> None:
    if dataset_role in {DatasetRole.OOS, DatasetRole.SEALED_OOS}:
        raise PermissionError(f"exploration is forbidden on {dataset_role.value}")


def assert_manifest_mutable(manifest: ExperimentManifest) -> None:
    if manifest.status in {ExperimentStatus.SEALED, ExperimentStatus.RUNNING, ExperimentStatus.COMPLETED}:
        raise PermissionError(f"experiment {manifest.experiment_id} is immutable at {manifest.status.value}")
