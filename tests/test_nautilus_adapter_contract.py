import sys
import types

import pytest

from ag_edgelab.engines.nautilus.adapter import NautilusAdapter, NautilusCompatibilityError


class FakeConfig:
    pass


class FakeEngine:
    def __init__(self, config):
        self.config = config


def install_fake(monkeypatch, version):
    root = types.ModuleType("nautilus_trader")
    root.__version__ = version
    backtest = types.ModuleType("nautilus_trader.backtest")
    backtest.BacktestEngine = FakeEngine
    config = types.ModuleType("nautilus_trader.config")
    config.BacktestEngineConfig = FakeConfig
    monkeypatch.setitem(sys.modules, "nautilus_trader", root)
    monkeypatch.setitem(sys.modules, "nautilus_trader.backtest", backtest)
    monkeypatch.setitem(sys.modules, "nautilus_trader.config", config)


def test_adapter_builds_backtest_engine_through_lazy_boundary(monkeypatch):
    install_fake(monkeypatch, "2.0.0rc1")
    engine = NautilusAdapter().build_backtest_engine()
    assert isinstance(engine, FakeEngine)
    assert isinstance(engine.config, FakeConfig)


def test_adapter_rejects_wrong_major(monkeypatch):
    install_fake(monkeypatch, "1.220.0")
    with pytest.raises(NautilusCompatibilityError, match="unsupported"):
        NautilusAdapter().assert_compatible()
