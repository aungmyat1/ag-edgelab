from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from packaging.version import Version


class NautilusCompatibilityError(RuntimeError):
    pass


@dataclass(frozen=True)
class NautilusAdapter:
    """Thin compatibility boundary around NautilusTrader.

    EdgeLab owns strategy funnels, datasets, evidence, statistics and
    qualification. Nautilus owns only independent event-driven simulation.
    This adapter intentionally does not expose live-node construction.
    """

    required_major: int = 2

    name: str = "NAUTILUS_TRADER"

    def installed_version(self) -> str:
        module = import_module("nautilus_trader")
        version = getattr(module, "__version__", None)
        if not version:
            raise NautilusCompatibilityError("nautilus_trader.__version__ is unavailable")
        return str(version)

    def assert_compatible(self) -> str:
        version = self.installed_version()
        parsed = Version(version)
        if parsed.major != self.required_major:
            raise NautilusCompatibilityError(
                f"NautilusTrader major version {parsed.major} is unsupported; expected {self.required_major}.x"
            )
        return version

    def build_backtest_engine(self):
        self.assert_compatible()
        backtest = import_module("nautilus_trader.backtest")
        config = import_module("nautilus_trader.config")
        return backtest.BacktestEngine(config.BacktestEngineConfig())
