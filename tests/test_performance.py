from ag_edgelab.statistics.performance import compute_performance


def test_performance_metrics_use_r_and_drawdown():
    m = compute_performance([1.0, -1.0, -1.0, 2.0])
    assert m.trades == 4
    assert m.win_rate == 0.5
    assert m.expectancy_r == 0.25
    assert m.profit_factor == 1.5
    assert m.max_drawdown_r == 2.0
    assert m.max_consecutive_losses == 2
