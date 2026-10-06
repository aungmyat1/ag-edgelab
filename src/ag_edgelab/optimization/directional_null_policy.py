"""Frozen directional null policy for R3 (PHASE B4).

Retired as eligibility authority:

    OLD_SYMMETRIC_TWO_LEG_AVERAGE

The R3.2 audit proved it materially understates directional variance
(SD 0.039829R vs 0.083890R for the one-leg null).  It survives only as a
historical diagnostic and may never again justify an eligibility verdict.

Frozen primary null:

    PRIMARY_DIRECTIONAL_NULL = RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY

For each baseline opportunity: keep the opportunity timestamp, keep the
causal entry mechanics, keep the reference stop/target/horizon mechanics,
keep identical costs when costs become authorized, and choose exactly ONE
direction with a deterministic preregistered RNG.  LONG and SHORT are never
averaged into one null observation.

Frozen robustness null:

    ROBUSTNESS_DIRECTIONAL_NULL = MATCHED_DIRECTION_FREQUENCY_NULL

Preserves the parent LONG/SHORT counts exactly while randomizing which
opportunities carry each direction.

Seeds and replicate counts are frozen here BEFORE any GEN3 evaluation.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

from ag_edgelab.optimization.direction_causality_audit import (
    DirectionalNullMode, directional_null_draw,
)

PRIMARY_DIRECTIONAL_NULL = "RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY"
ROBUSTNESS_DIRECTIONAL_NULL = "MATCHED_DIRECTION_FREQUENCY_NULL"
RETIRED_ELIGIBILITY_NULL = "OLD_SYMMETRIC_TWO_LEG_AVERAGE"

NULL_REPLICATES = 2000
NULL_REPLICATES_MINIMUM = 1000
NULL_MASTER_SEED = 4030341158
NULL_SEED_DERIVATION = "sha256('R3_NULL' | campaign_id | replicate_index) -> int"

_ELIGIBILITY_NULL_MODES = (
    DirectionalNullMode.RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY,
    DirectionalNullMode.MATCHED_DIRECTION_FREQUENCY_NULL,
)


class RetiredNullAuthority(RuntimeError):
    """The retired symmetric two-leg average was used as eligibility authority."""


@dataclass(frozen=True)
class FrozenNullPolicy:
    primary_null: str = PRIMARY_DIRECTIONAL_NULL
    robustness_null: str = ROBUSTNESS_DIRECTIONAL_NULL
    replicates: int = NULL_REPLICATES
    master_seed: int = NULL_MASTER_SEED

    def __post_init__(self) -> None:
        if self.replicates < NULL_REPLICATES_MINIMUM:
            raise ValueError(f"NULL_REPLICATES must be >= {NULL_REPLICATES_MINIMUM}")
        if self.primary_null != PRIMARY_DIRECTIONAL_NULL:
            raise ValueError("primary directional null is frozen")
        if self.robustness_null != ROBUSTNESS_DIRECTIONAL_NULL:
            raise ValueError("robustness directional null is frozen")

    def seed_for(self, campaign_id: str, replicate_index: int) -> int:
        """Deterministic preregistered per-campaign, per-replicate seed."""
        if replicate_index < 0:
            raise ValueError("replicate_index must be non-negative")
        import hashlib
        digest = hashlib.sha256(
            f"R3_NULL|{campaign_id}|{replicate_index}".encode()).hexdigest()
        return (int(digest, 16) + self.master_seed) % (2 ** 31 - 1)


FROZEN_NULL_POLICY = FrozenNullPolicy()


def assert_eligibility_null_mode(mode: DirectionalNullMode) -> None:
    """Only the frozen one-leg nulls may carry eligibility authority."""
    if mode is DirectionalNullMode.OLD_SYMMETRIC_TWO_LEG_AVERAGE:
        raise RetiredNullAuthority(
            f"{RETIRED_ELIGIBILITY_NULL} is retired as eligibility authority; "
            "it is a historical diagnostic only")
    if mode not in _ELIGIBILITY_NULL_MODES:
        raise ValueError(f"unknown eligibility null mode: {mode}")


def draw_one_leg_null(
    population: Sequence,
    *,
    sample_n: int,
    long_count: int,
    matched_direction_frequencies: bool,
    rng: random.Random,
) -> tuple[float, tuple[tuple[str, str], ...]]:
    """One draw of the frozen directional null.

    ``RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY`` when
    ``matched_direction_frequencies`` is False; otherwise
    ``MATCHED_DIRECTION_FREQUENCY_NULL`` (exact parent LONG/SHORT counts).
    Both modes take exactly one leg per sampled opportunity; the retired
    symmetric average is unreachable here by construction.
    """
    mode = (DirectionalNullMode.MATCHED_DIRECTION_FREQUENCY_NULL
            if matched_direction_frequencies
            else DirectionalNullMode.RANDOM_DIRECTION_ONE_LEG_PER_OPPORTUNITY)
    if not 0 <= long_count <= sample_n:
        raise ValueError("long_count must lie within [0, sample_n]")
    return directional_null_draw(
        population, sample_n=sample_n, long_count=long_count, mode=mode, rng=rng)
