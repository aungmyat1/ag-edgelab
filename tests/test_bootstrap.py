from ag_edgelab.statistics.bootstrap import bootstrap_expectancy_ci


def test_bootstrap_is_seed_deterministic():
    a = bootstrap_expectancy_ci([1.0, -1.0, 2.0, -0.5], samples=500, seed=42)
    b = bootstrap_expectancy_ci([1.0, -1.0, 2.0, -0.5], samples=500, seed=42)
    assert a == b
    assert a.low is not None and a.high is not None
    assert a.low <= a.estimate <= a.high
