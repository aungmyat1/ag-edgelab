"""Preregistered research hypotheses — the ONLY combinations evaluated.

No searching beyond this registry; its canonical hash seals the
preregistration. MA is compared, never assumed to improve anything.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ag_edgelab.data.fingerprint import sha256_json
from ag_edgelab.universal.direction import DirectionMode
from ag_edgelab.universal.location import LocationFamily


class PriceActionHypothesis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hypothesis_id: str
    description: str
    direction_mode: DirectionMode
    location_families: tuple[LocationFamily, ...]  # empty = direction only
    requires_liquidity_context: bool = False

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


PA_HYPOTHESES: tuple[PriceActionHypothesis, ...] = (
    PriceActionHypothesis(
        hypothesis_id="PA01", description="HTF direction only",
        direction_mode=DirectionMode.STRUCTURE_ONLY, location_families=()),
    PriceActionHypothesis(
        hypothesis_id="PA02", description="HTF direction + structural location",
        direction_mode=DirectionMode.STRUCTURE_ONLY,
        location_families=(LocationFamily.STRUCTURAL_LEVEL,)),
    PriceActionHypothesis(
        hypothesis_id="PA03", description="HTF direction + supply/demand location",
        direction_mode=DirectionMode.STRUCTURE_ONLY,
        location_families=(LocationFamily.SUPPLY_DEMAND,)),
    PriceActionHypothesis(
        hypothesis_id="PA04", description="HTF direction + liquidity location",
        direction_mode=DirectionMode.STRUCTURE_ONLY,
        location_families=(LocationFamily.LIQUIDITY_LEVEL,)),
    PriceActionHypothesis(
        hypothesis_id="PA05", description="HTF direction + premium/discount location",
        direction_mode=DirectionMode.STRUCTURE_ONLY,
        location_families=(LocationFamily.PREMIUM_DISCOUNT,)),
    PriceActionHypothesis(
        hypothesis_id="PA06", description="HTF direction + structural location + liquidity context",
        direction_mode=DirectionMode.STRUCTURE_ONLY,
        location_families=(LocationFamily.STRUCTURAL_LEVEL,),
        requires_liquidity_context=True),
    PriceActionHypothesis(
        hypothesis_id="PA07", description="structure + MA50/200 + location",
        direction_mode=DirectionMode.STRUCTURE_PLUS_MA,
        location_families=(LocationFamily.STRUCTURAL_LEVEL, LocationFamily.SUPPLY_DEMAND)),
)

# MA direction-family comparison set (mission section 7): structure only,
# MA only, structure + MA. Evaluated side by side, never optimized.
MA_COMPARISON_MODES: tuple[DirectionMode, ...] = (
    DirectionMode.STRUCTURE_ONLY,
    DirectionMode.MA_ONLY,
    DirectionMode.STRUCTURE_PLUS_MA,
)

HYPOTHESIS_REGISTRY_SHA256 = sha256_json(
    {"hypotheses": [h.model_dump(mode="python") for h in PA_HYPOTHESES],
     "ma_modes": [m.value for m in MA_COMPARISON_MODES]})


def hypothesis_by_id(hypothesis_id: str) -> PriceActionHypothesis:
    for hypothesis in PA_HYPOTHESES:
        if hypothesis.hypothesis_id == hypothesis_id:
            return hypothesis
    raise KeyError(f"unregistered hypothesis: {hypothesis_id} (no ad-hoc combinations)")
