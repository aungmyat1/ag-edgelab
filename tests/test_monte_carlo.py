from ag_edgelab.statistics.monte_carlo import shuffle_risk_summary


def test_monte_carlo_shuffle_is_seed_deterministic():
    trade_rs = [1.0, -1.0, 2.0, -0.5, -1.0, 1.5]
    first = shuffle_risk_summary(trade_rs, simulations=250, seed=7)
    second = shuffle_risk_summary(trade_rs, simulations=250, seed=7)

    assert first == second
    assert first.drawdown_p95_r is not None
    assert first.drawdown_p50_r <= first.drawdown_p95_r