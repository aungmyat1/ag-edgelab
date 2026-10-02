from __future__ import annotations

import hashlib
import inspect


def classify_market_state(state) -> str:
    """The frozen v1 classifier maps a positive candle to TREND, otherwise RANGE."""
    return "TREND" if state.close > state.open else "RANGE"


def regime_classifier_implementation_sha256() -> str:
    return hashlib.sha256(inspect.getsource(classify_market_state).encode("utf-8")).hexdigest()
