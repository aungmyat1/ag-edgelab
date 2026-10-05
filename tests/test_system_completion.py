import pytest
from ag_edgelab.system_completion import *


def test_identity_changes_when_any_contract_changes():
    values = dict(strategy_code_hash='a', parameter_hash='b', funnel_hash='c', entry_contract_hash='d', sl_contract_hash='e', target_contract_hash='f', session_contract_hash='g', symbol_universe=('EURUSD',), decision_timeframe='H1', execution_timeframe='M5', dev_dataset_authority='data', dev_partition_hash='p', friction_contract_hash='fr', preregistration_hash='pre', verifier_version='1')
    one = FrozenCandidateIdentity(**values)
    two = FrozenCandidateIdentity(**{**values, 'target_contract_hash': 'changed'})
    assert one.candidate_identity_sha256 != two.candidate_identity_sha256


def test_unknown_contamination_is_not_fresh_and_oos_denied():
    r = ContaminationRegistry([ContaminationRecord('fam','old','2020','2021',ExposureType.UNKNOWN_EXPOSURE,'now','unknown',ReusePolicy.UNKNOWN)])
    assert not r.is_fresh('fam', '2020-01', '2020-12')
    with pytest.raises(GovernanceError):
        authorize_oos(candidate_frozen=True, candidate_hash_valid=True, pre_oos_pass=True, dataset_role='OOS', family_fresh=False, already_consumed=False, preregistration_hash='x')


def test_scenario_does_not_unlock_edge_verification():
    f = FrictionAuthority(FrictionEvidence.MEASURED, FrictionEvidence.MEASURED, FrictionEvidence.SCENARIO, FrictionEvidence.NOT_APPLICABLE)
    assert not f.edge_verification_ready()


def test_readiness_never_authorizes_execution():
    result = readiness_audit({'REPO_HEALTH': ReadinessState.PASS})
    assert result['LIVE_EXECUTION_AUTHORIZED'] == 'NO'
