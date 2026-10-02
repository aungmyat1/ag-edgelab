import pytest

from ag_edgelab.contracts.dataset import DatasetRole
from ag_edgelab.experiments.sealing import assert_exploration_allowed


def test_development_allows_exploration():
    assert_exploration_allowed(dataset_role=DatasetRole.DEVELOPMENT)


@pytest.mark.parametrize("role", [DatasetRole.OOS, DatasetRole.SEALED_OOS])
def test_oos_rejects_exploration(role):
    with pytest.raises(PermissionError):
        assert_exploration_allowed(dataset_role=role)
