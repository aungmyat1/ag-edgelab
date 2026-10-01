from __future__ import annotations

from dataclasses import dataclass

from ag_edgelab.contracts.dataset import DatasetRole
from ag_edgelab.optimization.contracts import DatasetExposure, FunnelVariant


class OptimizationGovernanceError(RuntimeError):
    pass


def assert_optimization_allowed(role: DatasetRole, exposure: DatasetExposure) -> None:
    if role in {DatasetRole.OOS, DatasetRole.SEALED_OOS, DatasetRole.FORWARD}:
        raise OptimizationGovernanceError(f"optimization forbidden on {role.value}")
    if exposure in {DatasetExposure.OBSERVED_VALIDATION, DatasetExposure.BURNED_HOLDOUT}:
        raise OptimizationGovernanceError(f"optimization forbidden after exposure={exposure.value}")


def next_exposure(current: DatasetExposure, inspected: bool, role: DatasetRole) -> DatasetExposure:
    if not inspected:
        return current
    if role in {DatasetRole.OOS, DatasetRole.SEALED_OOS}:
        return DatasetExposure.BURNED_HOLDOUT
    if role == DatasetRole.VALIDATION:
        return DatasetExposure.OBSERVED_VALIDATION
    return DatasetExposure.DEVELOPMENT


def assert_holdout_open_allowed(variant: FunnelVariant, role: DatasetRole, exposure: DatasetExposure) -> None:
    if role not in {DatasetRole.OOS, DatasetRole.SEALED_OOS}:
        raise OptimizationGovernanceError("holdout open requires OOS or SEALED_OOS role")
    if not variant.frozen:
        raise OptimizationGovernanceError("candidate must be frozen before holdout access")
    if exposure != DatasetExposure.UNSEEN:
        raise OptimizationGovernanceError("holdout is not unseen")
