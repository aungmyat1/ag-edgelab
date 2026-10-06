"""Deterministic negative synthetic facts for Funnel Optimizer V1 proofs.

This module is test/infrastructure evidence only.  Its outcomes are deliberately
constructed and are never a market dataset, a friction scenario, or an edge
claim.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ag_edgelab.contracts.dataset import DatasetRole
from ag_edgelab.optimization.funnel_optimizer import (Opportunity, RelaxedReplay,
                                                       RuleSemantics, boolean_rule,
                                                       threshold_rule)

UTC = timezone.utc
SYNTHETIC_FIXTURE_ID = "SYNTHETIC_FUNNEL_NEGATIVE_V1"


def rules():
    return (
        boolean_rule("CONTEXT", feature="context"),
        boolean_rule("SWEEP", feature="sweep", depends_on=("CONTEXT",),
                     semantics=RuleSemantics.REQUIRES_FULL_REPLAY),
        threshold_rule("BODY_RATIO", feature="body_ratio", threshold=0.6,
                       depends_on=("SWEEP",)),
    )


def opportunities():
    start = datetime(2016, 3, 1, 7, tzinfo=UTC)
    rows = []
    # Every symbol/session/year stratum has a parent that selects negative
    # reference outcomes while nearby eligible opportunities are positive.
    for symbol_index, symbol in enumerate(("EURUSD", "GBPUSD")):
        offset = symbol_index * 30
        facts = (
            ({"context": True, "sweep": True, "body_ratio": 0.90}, -1.0, -0.2),
            ({"context": True, "sweep": True, "body_ratio": 0.40}, 0.8, None),
            ({"context": True, "sweep": False, "body_ratio": 0.90}, 0.4, None),
            ({"context": False, "sweep": True, "body_ratio": 0.90}, 0.2, None),
            ({"context": True, "sweep": True}, 0.5, None),
            ({"context": True, "sweep": True, "body_ratio": 0.70}, -0.7, -1.1),
            ({"context": True, "sweep": True, "body_ratio": 0.65}, None, None),
        )
        for index, (features, reference_r, actual_r) in enumerate(facts):
            rows.append(Opportunity(
                event_id=f"SYN-{symbol}-{index:02d}",
                candidate_id=f"SYNTHETIC_NEGATIVE_PARENT-{symbol}",
                timestamp_utc=start + timedelta(minutes=offset + index),
                symbol=symbol,
                session="LONDON",
                dataset_id="SYNTHETIC_DEVELOPMENT_ONLY_V1",
                strategy_id=SYNTHETIC_FIXTURE_ID,
                engine_id="SYNTHETIC_FACTS_V1",
                feature_values=features,
                reference_outcome_r=reference_r,
                actual_outcome_r=actual_r,
            ))
    return tuple(reversed(rows))  # tests order normalization deterministically


def build_event_table():
    return RelaxedReplay(rules(), engine_id="FUNNEL_OPTIMIZER_RELAXED_V1").evaluate(
        opportunities(), dataset_role=DatasetRole.DEVELOPMENT)
