from ag_edgelab.friction.model import FrictionScenario, apply_friction, stress_curve


def test_friction_cost_is_deducted_in_r():
    scenario = FrictionScenario("BASE", spread_r=0.05, commission_r=0.02, slippage_r=0.01)
    assert round(apply_friction(0.20, scenario), 9) == 0.12


def test_stress_curve_can_destroy_thin_edge():
    curve = stress_curve([0.1, 0.1, 0.1], [
        FrictionScenario("IDEAL"),
        FrictionScenario("STRESS", spread_r=0.12),
    ])
    assert curve["IDEAL"]["expectancy_r"] > 0
    assert curve["STRESS"]["expectancy_r"] < 0
