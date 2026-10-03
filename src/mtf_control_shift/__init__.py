"""Deterministic research-only MTF control-shift strategy.

No broker imports. No position sizing. No execution authority.
"""
from .engine import evaluate
from .models import Candle, Decision, Zone
from .ticket import build_ticket

__all__ = ["Candle", "Zone", "Decision", "evaluate", "build_ticket"]
