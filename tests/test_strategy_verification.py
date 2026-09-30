import json
from pathlib import Path

import pytest

from ag_edgelab.validation.evidence import EdgeVerdict, EconomicSummary, StrategyVerification


def test_fx_verification_is_economically_verified_no_edge():
    payload = json.loads(Path("experiments/verifications/fx_ssc_gen001.json").read_text())
    record = StrategyVerification.model_validate(payload)
    assert record.verdict == EdgeVerdict.NO_EDGE
    assert record.economically_verified is True
    assert record.economic is not None
    assert record.economic.expectancy_r < 0


def test_crypto_verification_refuses_to_claim_edge_without_economics():
    payload = json.loads(Path("experiments/verifications/crypto_btc_sweep_retest_v2.json").read_text())
    record = StrategyVerification.model_validate(payload)
    assert record.verdict == EdgeVerdict.INSUFFICIENT_EVIDENCE
    assert record.economically_verified is False
    assert record.deterministic is True
    assert record.economic is None


def test_edge_supported_requires_positive_expectancy():
    with pytest.raises(ValueError, match="positive expectancy"):
        StrategyVerification.edge_supported(
            verification_id="X", asset_class="FX", strategy_id="S", strategy_version="1",
            instrument="EURUSD", economic=EconomicSummary(trades=10, expectancy_r=-0.01),
        )
