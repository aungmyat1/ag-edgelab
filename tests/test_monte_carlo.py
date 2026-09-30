from ag_edgelab.statistics.monte_carlo import shuffle_risk_summary


def test_monte_carlo_shuffle_is_seed_deterministic():
    values = [1.0, -1.0, 2.0, -0.5, -1.0, 1.5]
    a = shuffle_risk_summary(values, simulations=250, seed=7)
    b = shuffle_risk_summary(values, simulations=250, seed=7)
    assert a == b
    assert a.drawdown_p95_r is not None
    assert a.drawdown_p50_r <= a.drawdown_p95_r
