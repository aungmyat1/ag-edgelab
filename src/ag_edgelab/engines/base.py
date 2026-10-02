from __future__ import annotations

from typing import Protocol

from ag_edgelab.contracts.intent import OrderIntent


class BacktestEngine(Protocol):
    """R1 interface: engines simulate fills; they never qualify strategies."""

    name: str
    version: str

    def execute(self, intents: tuple[OrderIntent, ...]) -> tuple[object, ...]: ...
