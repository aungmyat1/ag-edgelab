from __future__ import annotations

from ag_edgelab.contracts.dataset import DatasetRole
from ag_edgelab.optimization.contracts import DatasetExposure, FunnelVariant


class OptimizationGovernanceError(RuntimeError):
    pass


def assert_optimization_allowed(role: DatasetRole, exposure: DatasetExposure) -> None:
    # Optimization is deliberately DEVELOPMENT-only. VALIDATION is evidence,
    # not a tuning surface, even before it has been inspected.
    if role != DatasetRole.DEVELOPMENT:
        raise OptimizationGovernanceError(f"optimization requires DEVELOPMENT role, got {role.value}")
    if exposure != DatasetExposure.DEVELOPMENT:
        raise OptimizationGovernanceError(f"optimization requires DEVELOPMENT exposure, got {exposure.value}")


def next_exposure(current: DatasetExposure, inspected: bool, role: DatasetRole) -> DatasetExposure:
    # BURNED_HOLDOUT is absorbing: no caller-selected role can downgrade it.
    if current == DatasetExposure.BURNED_HOLDOUT:
        return DatasetExposure.BURNED_HOLDOUT
    if not inspected:
        return current
    if role in {DatasetRole.OOS, DatasetRole.SEALED_OOS, DatasetRole.FORWARD}:
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
