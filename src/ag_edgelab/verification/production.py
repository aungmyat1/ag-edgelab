from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field

from ag_edgelab.contracts.dataset import DatasetRole
from ag_edgelab.data.fingerprint import canonical_json, sha256_json
from ag_edgelab.friction.model import apply_normalized_r_stress
from ag_edgelab.optimization.contracts import DatasetExposure
from ag_edgelab.optimization.stability import assess_parameter_stability
from ag_edgelab.statistics.bootstrap import bootstrap_expectancy_ci
from ag_edgelab.statistics.performance import compute_performance
from ag_edgelab.verification.evidence import DatasetRecord, FRICTION_FORMULA, FRICTION_IMPLEMENTATION_SHA256, REGIME_CLASSIFIER_IMPLEMENTATION_SHA256, FrictionEvidenceRecord, FrictionModelRecord, MarketStateRecord, ParameterSetRecord, PopulationDefinitionRecord, RegimeClassifierRecord, StabilityEvidenceRecord, TradeListRecord, ValidationBundleRecord, WalkForwardEvidenceRecord
from ag_edgelab.verification.provenance import FrozenVariantRecord, UnknownProvenanceError, VerificationResolvers
from ag_edgelab.verification.regimes import classify_market_state

HEX64 = r"^[0-9a-f]{64}$"
REQUIRED_FRICTION_GRID = (1.0, 1.25, 1.5)
CANONICAL_ALLOWED_OOS_ROLES = frozenset((DatasetRole.OOS,))


class EdgeVerdict(StrEnum):
    EDGE_VERIFIED = "EDGE_VERIFIED"
    NO_EDGE = "NO_EDGE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class VerificationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    policy_id: str
    min_oos_trades: int = 30
    min_oos_expectancy_r: float = 0.0
    min_oos_profit_factor: float = 1.0
    max_drawdown_r: float = 20.0
    min_bootstrap_ci_low_r: float = 0.0
    min_walk_forward_folds: int = 3
    min_walk_forward_trades_per_fold: int = 30
    min_positive_walk_forward_fraction: float = .6
    min_regime_sample: int = 10
    required_friction_multipliers: tuple[float, ...] = REQUIRED_FRICTION_GRID
    max_parity_trade_count_delta: int = 1
    max_parity_expectancy_delta_r: float = .02

    @property
    def sha256(self):
        return sha256_json(self.model_dump(mode="python"))


CANONICAL_POLICY_V1 = VerificationPolicy(policy_id="EDGE_VERIFICATION_V1")
CANONICAL_POLICY_V1_SHA256 = "7ca7ec59c7868bc93b4c5cf5ee58babd51ab99a18876f2cfef647445532f33b3"
if CANONICAL_POLICY_V1.sha256 != CANONICAL_POLICY_V1_SHA256:
    raise RuntimeError("canonical policy hash drift")
POLICY_REGISTRY = MappingProxyType({CANONICAL_POLICY_V1.policy_id: CANONICAL_POLICY_V1})


class EdgeValidationArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    evidence_id: str = Field(pattern=HEX64)
    policy_sha256: str = Field(pattern=HEX64)
    verdict: EdgeVerdict
    gate_results: tuple[tuple[str, bool], ...]
    reasons: tuple[str, ...]
    verifier_version: str = "EDGE_VERIFIER_V3"
    seal_sha256: str = Field(pattern=HEX64)


@dataclass(frozen=True)
class VerificationContext:
    """Immutable, invocation-scoped authority assembled by the server."""
    resolvers: VerificationResolvers


@dataclass(frozen=True)
class EdgeVerifier:
    context: VerificationContext

    def verify_edge(self, evidence_id: str) -> EdgeValidationArtifact:
        return verify_edge(evidence_id, self.context)

    def validate_artifact(self, artifact: EdgeValidationArtifact) -> bool:
        return validate_artifact(artifact, self.context)


def _artifact(evidence_id, verdict, gates, reasons):
    pairs = tuple(sorted(gates.items()))
    payload = {
        "evidence_id": evidence_id,
        "policy_sha256": CANONICAL_POLICY_V1_SHA256,
        "verdict": verdict.value,
        "gate_results": pairs,
        "reasons": tuple(reasons),
        "verifier_version": "EDGE_VERIFIER_V3",
    }
    return EdgeValidationArtifact(**payload, seal_sha256=sha256_json(payload))


_INVALID_EVIDENCE_ID = sha256_json({"invalid_evidence_id": True})


def _resolve(store, sha, typ):
    obj = store.resolve(sha)
    if not isinstance(obj, typ):
        raise UnknownProvenanceError(f"wrong evidence type for {sha}")
    return obj


def _same_identity(a: TradeListRecord, b: TradeListRecord):
    return a.dataset_sha256 == b.dataset_sha256 and a.strategy_sha256 == b.strategy_sha256


def _same_population(a: TradeListRecord, b: TradeListRecord):
    return tuple((t.trade_id, t.executed_at) for t in a.trades) == tuple((t.trade_id, t.executed_at) for t in b.trades)


def _trades_within(trades, start, end):
    return all(start <= t.executed_at < end for t in trades)


def _stability_provenance(resolvers, bundle, variant, experiment, holdout_open):
    """Resolve and validate every center/neighbor run before computing stability."""
    try:
        center_params = _resolve(resolvers.evidence, variant.parameters_sha256, ParameterSetRecord)
        base_params = _resolve(resolvers.evidence, experiment.base_parameter_set_sha256, ParameterSetRecord)
        center_param_record = _resolve(resolvers.evidence, experiment.center_parameter_set_sha256, ParameterSetRecord)
        population = _resolve(resolvers.evidence, experiment.population_definition_sha256, PopulationDefinitionRecord)
        dataset = _resolve(resolvers.datasets, experiment.development_dataset_sha256, DatasetRecord)
        center_trades = _resolve(resolvers.evidence, experiment.center_trade_list_sha256, TradeListRecord)
        engine = resolvers.engines.resolve(experiment.engine_id)
        exposure = resolvers.exposure.state(experiment.development_dataset_sha256)
    except (UnknownProvenanceError, ValueError, TypeError):
        return False, None

    coherent = (
        experiment.base_variant_sha256 == bundle.variant_sha256
        and experiment.base_parameter_set_sha256 == variant.parameters_sha256
        and experiment.center_parameter_set_sha256 == variant.parameters_sha256
        and center_params.sha256 == base_params.sha256 == center_param_record.sha256
        and center_params.strategy_family_id == variant.strategy_id
        and center_params.parameter_schema_version == base_params.parameter_schema_version == center_param_record.parameter_schema_version
        and center_params.parameters == base_params.parameters == center_param_record.parameters
        and population.dataset_sha256 == experiment.development_dataset_sha256
        and population.start == dataset.start and population.end == dataset.end
        and dataset.role == DatasetRole.DEVELOPMENT
        and exposure == DatasetExposure.DEVELOPMENT
        and variant.frozen_at <= experiment.created_at < holdout_open.observed_at
        and engine.owner_approved
        and engine.code_sha256 == experiment.engine_code_sha256
        and center_trades.dataset_sha256 == experiment.development_dataset_sha256
        and center_trades.parameter_set_sha256 == variant.parameters_sha256
        and center_trades.population_definition_sha256 == experiment.population_definition_sha256
        and center_trades.strategy_sha256 == variant.strategy_sha256
        and center_trades.engine_id == experiment.engine_id
        and center_trades.engine_code_sha256 == experiment.engine_code_sha256
        and _trades_within(center_trades.trades, population.start, population.end)
    )
    if not coherent:
        return False, None

    center_values = center_params.parameters
    if experiment.parameter_name not in center_values:
        return False, None
    center_value = center_values[experiment.parameter_name]
    if isinstance(center_value, bool) or not isinstance(center_value, (int, float)) or not math.isfinite(center_value):
        return False, None
    neighborhood = {float(center_value): compute_performance(center_trades.rs).expectancy_r}
    used_param_sets = {center_params.sha256}
    used_trade_lists = {center_trades.sha256}

    for neighbor in experiment.neighbors:
        try:
            params = _resolve(resolvers.evidence, neighbor.parameter_set_sha256, ParameterSetRecord)
            trade_list = _resolve(resolvers.evidence, neighbor.trade_list_sha256, TradeListRecord)
        except (UnknownProvenanceError, ValueError, TypeError):
            return False, None
        if params.sha256 in used_param_sets or trade_list.sha256 in used_trade_lists:
            return False, None
        used_param_sets.add(params.sha256)
        used_trade_lists.add(trade_list.sha256)
        values = params.parameters
        changed = [key for key in set(center_values) | set(values)
                   if key not in center_values or key not in values
                   or canonical_json(center_values[key]) != canonical_json(values[key])]
        if (
            len(changed) != 1 or changed[0] != experiment.parameter_name
            or neighbor.changed_parameter != changed[0]
            or params.strategy_family_id != center_params.strategy_family_id
            or params.parameter_schema_version != center_params.parameter_schema_version
            or neighbor.old_value_json != canonical_json(center_values[changed[0]])
            or neighbor.new_value_json != canonical_json(values[changed[0]])
            or neighbor.old_value_json == neighbor.new_value_json
            or trade_list.dataset_sha256 != experiment.development_dataset_sha256
            or trade_list.parameter_set_sha256 != params.sha256
            or trade_list.population_definition_sha256 != experiment.population_definition_sha256
            or trade_list.strategy_sha256 != variant.strategy_sha256
            or trade_list.engine_id != experiment.engine_id
            or trade_list.engine_code_sha256 != experiment.engine_code_sha256
            or not _trades_within(trade_list.trades, population.start, population.end)
            or not _same_population(center_trades, trade_list)
        ):
            return False, None
        value = values[experiment.parameter_name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return False, None
        numeric_value = float(value)
        if numeric_value in neighborhood:
            return False, None
        neighborhood[numeric_value] = compute_performance(trade_list.rs).expectancy_r

    try:
        result = assess_parameter_stability(neighborhood, float(center_value))
    except (ValueError, TypeError):
        return False, None
    return True, result


def verify_edge(evidence_id: str, context: VerificationContext) -> EdgeValidationArtifact:
    """Verify untrusted evidence using explicit immutable server authority."""
    if not isinstance(evidence_id, str) or re.fullmatch(HEX64, evidence_id) is None:
        return _artifact(
            _INVALID_EVIDENCE_ID,
            EdgeVerdict.INSUFFICIENT_EVIDENCE,
            {"EVIDENCE_ID": False},
            ("INVALID_EVIDENCE_ID",),
        )
    if not isinstance(context, VerificationContext):
        return _artifact(evidence_id, EdgeVerdict.INSUFFICIENT_EVIDENCE, {"SERVER_AUTHORITY": False}, ("SERVER_AUTHORITY",))
    try:
        return _verify_edge(evidence_id, context.resolvers)
    except (TypeError, ValueError, OverflowError):
        # Defensive public boundary for malformed evidence that bypassed model validation.
        return _artifact(evidence_id, EdgeVerdict.INSUFFICIENT_EVIDENCE, {"TEMPORAL_EVIDENCE": False}, ("INVALID_EVIDENCE",))


def _verify_edge(evidence_id: str, resolvers: VerificationResolvers) -> EdgeValidationArtifact:
    gates = {}
    try:
        bundle = _resolve(resolvers.evidence, evidence_id, ValidationBundleRecord)
        variant = resolvers.variants.resolve(bundle.variant_sha256)
        if not isinstance(variant, FrozenVariantRecord):
            raise UnknownProvenanceError("variant record type mismatch")
        classifier = _resolve(resolvers.evidence, variant.regime_classifier_sha256, RegimeClassifierRecord)
        oos = _resolve(resolvers.evidence, bundle.oos_trade_list_sha256, TradeListRecord)
        dataset = _resolve(resolvers.datasets, oos.dataset_sha256, DatasetRecord)
        friction = _resolve(resolvers.evidence, bundle.friction_sha256, FrictionEvidenceRecord)
        friction_model = _resolve(resolvers.evidence, variant.friction_model_sha256, FrictionModelRecord)
        wf = _resolve(resolvers.evidence, bundle.walk_forward_sha256, WalkForwardEvidenceRecord)
        stability = _resolve(resolvers.evidence, bundle.stability_sha256, StabilityEvidenceRecord)
        pref = _resolve(resolvers.evidence, bundle.parity_reference_trade_list_sha256, TradeListRecord)
        pind = _resolve(resolvers.evidence, bundle.parity_independent_trade_list_sha256, TradeListRecord)
        open_event = resolvers.exposure.open_event(oos.dataset_sha256)
    except (UnknownProvenanceError, ValueError, TypeError) as exc:
        return _artifact(evidence_id, EdgeVerdict.INSUFFICIENT_EVIDENCE, {"AUTHORITATIVE_EVIDENCE": False}, (type(exc).__name__,))

    try:
        exposure_state = resolvers.exposure.state(oos.dataset_sha256)
    except UnknownProvenanceError:
        exposure_state = None
    if dataset.role not in CANONICAL_ALLOWED_OOS_ROLES or exposure_state != DatasetExposure.BURNED_HOLDOUT:
        return _artifact(evidence_id, EdgeVerdict.INSUFFICIENT_EVIDENCE,
                         {"OOS_DATASET_ROLE": False}, ("INVALID_OOS_DATASET_ROLE_OR_EXPOSURE",))

    identity = (
        oos.strategy_sha256 == variant.strategy_sha256
        and bundle.variant_sha256 == variant.sha256
        and variant.frozen_at <= open_event.observed_at
    )
    gates["FROZEN_BEFORE_OPEN"] = identity
    gates["UNSEEN_FROM_LEDGER"] = resolvers.exposure.was_unseen_when_opened(oos.dataset_sha256)
    gates["OOS_WINDOW"] = _trades_within(oos.trades, dataset.start, dataset.end)

    p = compute_performance(oos.rs)
    boot = bootstrap_expectancy_ci(oos.rs, samples=5000, seed=0)
    gates["OOS_POPULATION"] = p.trades >= CANONICAL_POLICY_V1.min_oos_trades

    classifier_coherent = (
        classifier.classifier_id == "ohlc-direction"
        and classifier.version == "1"
        and classifier.implementation_sha256 == REGIME_CLASSIFIER_IMPLEMENTATION_SHA256
        and classifier.required_input_schema == ("dataset_sha256", "trade_id", "observed_at", "open", "close")
        and classifier.classification_rule == "close > open => TREND; otherwise => RANGE"
        and classifier.allowed_regimes == ("TREND", "RANGE")
        and set(variant.claimed_regimes) == set(classifier.allowed_regimes)
    )
    regime_groups = {name: [] for name in classifier.allowed_regimes}
    seen_state_hashes = set()
    for trade in oos.trades:
        if trade.market_state_sha256 is None or trade.market_state_sha256 in seen_state_hashes:
            classifier_coherent = False
            continue
        seen_state_hashes.add(trade.market_state_sha256)
        try:
            market_state = _resolve(resolvers.evidence, trade.market_state_sha256, MarketStateRecord)
        except UnknownProvenanceError:
            classifier_coherent = False
            continue
        state_bound = (
            market_state.dataset_sha256 == oos.dataset_sha256
            and market_state.trade_id == trade.trade_id
            and market_state.observed_at == trade.executed_at
            and dataset.start <= market_state.observed_at < dataset.end
        )
        if not state_bound:
            classifier_coherent = False
            continue
        regime = classify_market_state(market_state)
        if regime not in regime_groups:
            classifier_coherent = False
            continue
        regime_groups[regime].append(trade.r)
    regime_metrics = {name: compute_performance(tuple(rs)) for name, rs in regime_groups.items()}
    gates["REGIME_COHERENCE"] = classifier_coherent and all(
        m.trades >= CANONICAL_POLICY_V1.min_regime_sample for m in regime_metrics.values()
    )

    friction_coherent = (
        friction.baseline_trade_list_sha256 == oos.sha256
        and friction.model_sha256 == variant.friction_model_sha256
        and friction.multipliers == CANONICAL_POLICY_V1.required_friction_multipliers
        and friction_model.model_id == "normalized-r"
        and friction_model.version == "1"
        and friction_model.implementation_sha256 == FRICTION_IMPLEMENTATION_SHA256
        and friction_model.cost_unit == "R"
        and friction_model.cost_components == ("spread", "commission", "slippage", "funding")
        and friction_model.baseline_semantics == "r_is_gross_less_all_baseline_costs"
        and friction_model.stress_formula == FRICTION_FORMULA
    )
    friction_costs = []
    for trade in oos.trades:
        costs = (trade.spread_cost_r, trade.commission_cost_r, trade.slippage_cost_r, trade.funding_cost_r)
        if trade.gross_r is None or any(c is None or not math.isfinite(c) or c < 0 for c in costs):
            friction_coherent = False
            friction_costs.append(None)
            continue
        total_cost = sum(costs)
        if not math.isfinite(trade.gross_r) or not math.isfinite(total_cost) or not math.isclose(
            trade.gross_r - total_cost, trade.r, rel_tol=0.0, abs_tol=1e-12
        ):
            friction_coherent = False
        friction_costs.append(total_cost)
    fpoints = {}
    if all(cost is not None for cost in friction_costs):
        for mult in friction.multipliers:
            stressed_rs = tuple(apply_normalized_r_stress(t.r, cost, mult) for t, cost in zip(oos.trades, friction_costs))
            if any(not math.isfinite(value) for value in stressed_rs):
                friction_coherent = False
            else:
                fpoints[mult] = compute_performance(stressed_rs)
    gates["FRICTION_COHERENCE"] = bool(friction_coherent)

    wf_metrics = []
    policy = CANONICAL_POLICY_V1
    wf_coherent = len(wf.folds) >= policy.min_walk_forward_folds
    for fold in wf.folds:
        try:
            tl = _resolve(resolvers.evidence, fold.trade_list_sha256, TradeListRecord)
            train_dataset = _resolve(resolvers.datasets, fold.train_dataset_sha256, DatasetRecord)
            test_dataset = _resolve(resolvers.datasets, fold.test_dataset_sha256, DatasetRecord)
            population = _resolve(resolvers.evidence, fold.population_definition_sha256, PopulationDefinitionRecord)
            engine = resolvers.engines.resolve(fold.engine_id)
            train_exposure = resolvers.exposure.state(fold.train_dataset_sha256)
            test_exposure = resolvers.exposure.state(fold.test_dataset_sha256)
        except UnknownProvenanceError:
            wf_coherent = False
            continue
        wf_coherent &= (
            fold.variant_sha256 == variant.sha256
            and train_dataset.start <= fold.train_start < fold.train_end <= train_dataset.end
            and test_dataset.start <= fold.test_start < fold.test_end <= test_dataset.end
            and train_dataset.role == DatasetRole.DEVELOPMENT
            and test_dataset.role in (DatasetRole.VALIDATION, DatasetRole.OOS)
            and train_exposure == DatasetExposure.DEVELOPMENT
            and test_exposure in (DatasetExposure.OBSERVED_VALIDATION, DatasetExposure.BURNED_HOLDOUT)
            and population.dataset_sha256 == fold.test_dataset_sha256
            and population.start == fold.test_start and population.end == fold.test_end
            and engine.owner_approved and engine.code_sha256 == fold.engine_code_sha256
            and tl.dataset_sha256 == fold.test_dataset_sha256
            and tl.engine_id == fold.engine_id and tl.engine_code_sha256 == fold.engine_code_sha256
            and tl.strategy_sha256 == variant.strategy_sha256
            and _trades_within(tl.trades, fold.test_start, fold.test_end)
            and len(tl.trades) >= policy.min_walk_forward_trades_per_fold
        )
        wf_metrics.append(compute_performance(tl.rs))
    gates["WALK_FORWARD_COHERENCE"] = bool(wf_coherent)

    stability_coherent, stability_result = _stability_provenance(
        resolvers, bundle, variant, stability, open_event
    )
    gates["STABILITY_COHERENCE"] = bool(stability_coherent)

    parity_coherent = (
        bundle.parity_reference_trade_list_sha256 == bundle.oos_trade_list_sha256
        and pref.sha256 == oos.sha256
        and _same_identity(pref, pind)
        and _same_population(pref, pind)
        and pref.dataset_sha256 == oos.dataset_sha256
        and pref.strategy_sha256 == variant.strategy_sha256
    )
    try:
        er = resolvers.engines.resolve(pref.engine_id)
        ei = resolvers.engines.resolve(pind.engine_id)
        parity_coherent &= (
            er.code_sha256 == pref.engine_code_sha256
            and ei.code_sha256 == pind.engine_code_sha256
            and er.independence_group != ei.independence_group
        )
    except UnknownProvenanceError:
        parity_coherent = False
    pr = compute_performance(pref.rs)
    pi = compute_performance(pind.rs)
    per_trade_parity = (
        len(pref.trades) == len(pind.trades)
        and all(abs(a.r - b.r) <= CANONICAL_POLICY_V1.max_parity_expectancy_delta_r for a, b in zip(pref.trades, pind.trades))
    )
    gates["PARITY_COHERENCE"] = bool(parity_coherent and per_trade_parity)

    completeness = all(gates[k] for k in (
        "FROZEN_BEFORE_OPEN", "UNSEEN_FROM_LEDGER", "OOS_WINDOW", "OOS_POPULATION",
        "REGIME_COHERENCE", "FRICTION_COHERENCE", "WALK_FORWARD_COHERENCE",
        "STABILITY_COHERENCE", "PARITY_COHERENCE"
    ))
    if not completeness:
        return _artifact(evidence_id, EdgeVerdict.INSUFFICIENT_EVIDENCE, gates, tuple(k for k, v in gates.items() if not v))

    base_positive = (
        p.expectancy_r is not None
        and p.expectancy_r > CANONICAL_POLICY_V1.min_oos_expectancy_r
        and p.profit_factor is not None
        and p.profit_factor > CANONICAL_POLICY_V1.min_oos_profit_factor
        and p.max_drawdown_r <= CANONICAL_POLICY_V1.max_drawdown_r
    )
    if not base_positive:
        gates["OOS_ECONOMICS"] = False
        return _artifact(evidence_id, EdgeVerdict.NO_EDGE, gates, ("OOS_ECONOMICS",))
    gates["OOS_ECONOMICS"] = True

    gates["BOOTSTRAP"] = boot.low is not None and boot.low > CANONICAL_POLICY_V1.min_bootstrap_ci_low_r
    fvals = [fpoints[m].expectancy_r for m in CANONICAL_POLICY_V1.required_friction_multipliers]
    gates["FRICTION_STRESS"] = all(v is not None and v > 0 for v in fvals) and all(
        b <= a + 1e-12 for a, b in zip(fvals, fvals[1:])
    )
    gates["REGIME_EVIDENCE"] = all(m.expectancy_r is not None and m.expectancy_r > 0 for m in regime_metrics.values())
    positives = sum(m.expectancy_r is not None and m.expectancy_r > 0 for m in wf_metrics) / len(wf_metrics)
    gates["WALK_FORWARD"] = positives >= policy.min_positive_walk_forward_fraction
    gates["PARAMETER_STABILITY"] = stability_result is not None and stability_result.stable
    gates["INDEPENDENT_PARITY"] = (
        abs(pr.trades - pi.trades) <= CANONICAL_POLICY_V1.max_parity_trade_count_delta
        and pr.expectancy_r is not None
        and pi.expectancy_r is not None
        and abs(pr.expectancy_r - pi.expectancy_r) <= CANONICAL_POLICY_V1.max_parity_expectancy_delta_r
        and per_trade_parity
    )
    failed = tuple(k for k, v in gates.items() if not v)
    return _artifact(evidence_id, EdgeVerdict.EDGE_VERIFIED if not failed else EdgeVerdict.NO_EDGE, gates, failed)


def validate_artifact(artifact: EdgeValidationArtifact, context: VerificationContext) -> bool:
    return verify_edge(artifact.evidence_id, context).model_dump(mode="python") == artifact.model_dump(mode="python")
