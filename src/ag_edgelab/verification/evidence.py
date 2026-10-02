from __future__ import annotations

import json
import math
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ag_edgelab.contracts.dataset import DatasetRole
from ag_edgelab.data.fingerprint import canonical_json, sha256_json
from ag_edgelab.friction.model import normalized_r_stress_implementation_sha256
from ag_edgelab.verification.regimes import regime_classifier_implementation_sha256
from ag_edgelab.verification.time import UTCDateTime

HEX64 = r"^[0-9a-f]{64}$"


class DatasetRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    dataset_sha256: str = Field(pattern=HEX64)
    start: UTCDateTime
    end: UTCDateTime
    role: DatasetRole | None = None

    @model_validator(mode="after")
    def valid_window(self) -> "DatasetRecord":
        if not self.start < self.end:
            raise ValueError("dataset window must be increasing")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


class TradeOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    trade_id: str = Field(min_length=1)
    executed_at: UTCDateTime
    r: float = Field(allow_inf_nan=False)
    # Diagnostic only. Production classification uses market_state_sha256 below.
    regime: str = Field(min_length=1)
    market_state_sha256: str | None = Field(default=None, pattern=HEX64)
    gross_r: float | None = Field(default=None, allow_inf_nan=False)
    spread_cost_r: float | None = Field(default=None, allow_inf_nan=False, ge=0)
    commission_cost_r: float | None = Field(default=None, allow_inf_nan=False, ge=0)
    slippage_cost_r: float | None = Field(default=None, allow_inf_nan=False, ge=0)
    funding_cost_r: float | None = Field(default=None, allow_inf_nan=False, ge=0)

    @model_validator(mode="after")
    def baseline_cost_consistent(self) -> "TradeOutcome":
        costs = (self.spread_cost_r, self.commission_cost_r, self.slippage_cost_r, self.funding_cost_r)
        if self.gross_r is not None and all(cost is not None for cost in costs):
            if not math.isclose(self.gross_r - sum(costs), self.r, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError("net R must equal gross R less baseline friction costs")
        return self


class TradeListRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    dataset_sha256: str = Field(pattern=HEX64)
    strategy_sha256: str = Field(pattern=HEX64)
    engine_id: str = Field(min_length=1)
    engine_code_sha256: str = Field(pattern=HEX64)
    parameter_set_sha256: str | None = Field(default=None, pattern=HEX64)
    population_definition_sha256: str | None = Field(default=None, pattern=HEX64)
    trades: tuple[TradeOutcome, ...]

    @model_validator(mode="after")
    def unique_and_ordered(self) -> "TradeListRecord":
        ids = [t.trade_id for t in self.trades]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate trade ids")
        times = [t.executed_at for t in self.trades]
        if times != sorted(times):
            raise ValueError("trade list must be chronological")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))

    @property
    def rs(self) -> tuple[float, ...]:
        return tuple(t.r for t in self.trades)


REGIME_CLASSIFIER_IMPLEMENTATION_SHA256 = regime_classifier_implementation_sha256()


class RegimeClassifierRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    classifier_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    implementation_sha256: str = Field(pattern=HEX64)
    required_input_schema: tuple[str, ...] = ("dataset_sha256", "trade_id", "observed_at", "open", "close")
    classification_rule: str = "close > open => TREND; otherwise => RANGE"
    allowed_regimes: tuple[str, ...] = ("TREND", "RANGE")

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


class MarketStateRecord(BaseModel):
    """Content-addressed OHLC observation bound to one trade and dataset."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    dataset_sha256: str = Field(pattern=HEX64)
    trade_id: str = Field(min_length=1)
    observed_at: UTCDateTime
    open: float = Field(allow_inf_nan=False)
    high: float = Field(allow_inf_nan=False)
    low: float = Field(allow_inf_nan=False)
    close: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_ohlc(self) -> "MarketStateRecord":
        if self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close, self.high):
            raise ValueError("invalid market-state OHLC")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


FRICTION_FORMULA = "baseline_net_r - (multiplier - 1) * sum(normalized_cost_components_r)"
FRICTION_IMPLEMENTATION_SHA256 = normalized_r_stress_implementation_sha256()


class FrictionModelRecord(BaseModel):
    """Frozen normalized-R cost semantics used to derive stressed net outcomes."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    model_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    implementation_sha256: str = Field(pattern=HEX64)
    cost_unit: str = "R"
    cost_components: tuple[str, ...] = ("spread", "commission", "slippage", "funding")
    baseline_semantics: str = "r_is_gross_less_all_baseline_costs"
    stress_formula: str = FRICTION_FORMULA

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


class FrictionEvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    baseline_trade_list_sha256: str = Field(pattern=HEX64)
    model_sha256: str = Field(pattern=HEX64)
    multipliers: tuple[float, ...]

    @model_validator(mode="after")
    def valid(self) -> "FrictionEvidenceRecord":
        ms = list(self.multipliers)
        if any(not math.isfinite(m) or m < 1.0 for m in ms) or len(ms) != len(set(ms)):
            raise ValueError("invalid friction grid")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


class WalkForwardFoldRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    fold_id: str = Field(min_length=1)
    train_start: UTCDateTime
    train_end: UTCDateTime
    test_start: UTCDateTime
    test_end: UTCDateTime
    trade_list_sha256: str = Field(pattern=HEX64)
    train_dataset_sha256: str = Field(pattern=HEX64)
    test_dataset_sha256: str = Field(pattern=HEX64)
    variant_sha256: str = Field(pattern=HEX64)
    engine_id: str = Field(min_length=1)
    engine_code_sha256: str = Field(pattern=HEX64)
    population_definition_sha256: str = Field(pattern=HEX64)

    @model_validator(mode="after")
    def chronological(self) -> "WalkForwardFoldRecord":
        if not self.train_start < self.train_end <= self.test_start < self.test_end:
            raise ValueError("invalid chronological fold")
        return self


class WalkForwardEvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    folds: tuple[WalkForwardFoldRecord, ...]

    @model_validator(mode="after")
    def nonoverlap(self) -> "WalkForwardEvidenceRecord":
        if len({fold.fold_id for fold in self.folds}) != len(self.folds):
            raise ValueError("walk-forward fold ids must be unique")
        for a, b in zip(self.folds, self.folds[1:]):
            if b.test_start < a.test_end:
                raise ValueError("walk-forward test windows overlap")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


class StabilityEvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    base_variant_sha256: str = Field(pattern=HEX64)
    base_parameter_set_sha256: str = Field(pattern=HEX64)
    development_dataset_sha256: str = Field(pattern=HEX64)
    population_definition_sha256: str = Field(pattern=HEX64)
    engine_id: str = Field(min_length=1)
    engine_code_sha256: str = Field(pattern=HEX64)
    created_at: UTCDateTime
    center_parameter_set_sha256: str = Field(pattern=HEX64)
    center_trade_list_sha256: str = Field(pattern=HEX64)
    parameter_name: str = Field(min_length=1)
    neighbors: tuple["ParameterNeighborRecord", ...]

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


class ParameterSetRecord(BaseModel):
    """Immutable canonical JSON parameter map for one strategy family/schema."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    strategy_family_id: str = Field(min_length=1)
    parameter_schema_version: str = Field(min_length=1)
    parameters_json: str = Field(min_length=2)

    @model_validator(mode="after")
    def canonical_parameter_object(self) -> "ParameterSetRecord":
        value = json.loads(self.parameters_json)
        if not isinstance(value, dict) or not value or canonical_json(value) != self.parameters_json:
            raise ValueError("parameters_json must be a non-empty canonical JSON object")
        return self

    @classmethod
    def create(cls, strategy_family_id: str, parameter_schema_version: str, parameters: dict) -> "ParameterSetRecord":
        return cls(
            strategy_family_id=strategy_family_id,
            parameter_schema_version=parameter_schema_version,
            parameters_json=canonical_json(parameters),
        )

    @property
    def parameters(self) -> dict:
        return json.loads(self.parameters_json)

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


class PopulationDefinitionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    dataset_sha256: str = Field(pattern=HEX64)
    start: UTCDateTime
    end: UTCDateTime

    @model_validator(mode="after")
    def valid_window(self) -> "PopulationDefinitionRecord":
        if not self.start < self.end:
            raise ValueError("population window must be increasing")
        return self

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


class ParameterNeighborRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mutation_id: str = Field(min_length=1)
    parameter_set_sha256: str = Field(pattern=HEX64)
    changed_parameter: str = Field(min_length=1)
    old_value_json: str
    new_value_json: str
    trade_list_sha256: str = Field(pattern=HEX64)

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))


StabilityEvidenceRecord.model_rebuild()


class ValidationBundleRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    variant_sha256: str = Field(pattern=HEX64)
    oos_trade_list_sha256: str = Field(pattern=HEX64)
    friction_sha256: str = Field(pattern=HEX64)
    walk_forward_sha256: str = Field(pattern=HEX64)
    stability_sha256: str = Field(pattern=HEX64)
    parity_reference_trade_list_sha256: str = Field(pattern=HEX64)
    parity_independent_trade_list_sha256: str = Field(pattern=HEX64)

    @property
    def sha256(self) -> str:
        return sha256_json(self.model_dump(mode="python"))
