"""Deterministic direction and target diagnostics for the Daily-Bias Lab.

This module is deliberately strategy-agnostic.  It supplies causal, closed-bar
primitives; it does not implement or mutate an Asian-session strategy.  Every
function that accepts ``asof_index`` only observes bars through that index.
Equal pivots are not silently resolved, and unresolved concepts are represented
by ``None``/``CONTRACT_INCOMPLETE`` by the caller rather than fitted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
from math import isfinite
from typing import Any, Mapping, Sequence


class Direction(StrEnum):
    BULL = "BULL"
    BEAR = "BEAR"
    NEUTRAL = "NEUTRAL"


class Location(StrEnum):
    PREMIUM = "PREMIUM"
    DISCOUNT = "DISCOUNT"
    MIDRANGE = "MIDRANGE"
    UNAVAILABLE = "UNAVAILABLE"


class Phase(StrEnum):
    CONTINUATION = "CONTINUATION"
    PULLBACK = "PULLBACK"
    NEUTRAL = "NEUTRAL"
    UNAVAILABLE = "UNAVAILABLE"


class LiquidityState(StrEnum):
    INTACT = "INTACT"
    SWEPT = "SWEPT"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class SwingPoint:
    index: int
    timestamp: datetime
    kind: str
    price: float
    label: str | None
    confirmation_index: int

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["timestamp"] = self.timestamp.isoformat()
        return value


@dataclass(frozen=True)
class BosEvent:
    index: int
    timestamp: datetime
    direction: Direction
    broken_swing_index: int
    broken_price: float

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["timestamp"] = self.timestamp.isoformat()
        value["direction"] = self.direction.value
        return value


@dataclass(frozen=True)
class StructureState:
    direction: Direction
    as_of_index: int
    swing_points: tuple[SwingPoint, ...]
    bos_events: tuple[BosEvent, ...]
    latest_high: SwingPoint | None
    latest_low: SwingPoint | None
    invalidation_reference: float | None
    invalidation_type: str | None

    @property
    def bullish(self) -> bool:
        return self.direction == Direction.BULL

    @property
    def bearish(self) -> bool:
        return self.direction == Direction.BEAR

    def as_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction.value,
            "as_of_index": self.as_of_index,
            "swing_points": [x.as_dict() for x in self.swing_points],
            "bos_events": [x.as_dict() for x in self.bos_events],
            "latest_high": None if self.latest_high is None else self.latest_high.as_dict(),
            "latest_low": None if self.latest_low is None else self.latest_low.as_dict(),
            "invalidation_reference": self.invalidation_reference,
            "invalidation_type": self.invalidation_type,
        }


@dataclass(frozen=True)
class ActiveSwingRange:
    swing_low: SwingPoint
    swing_high: SwingPoint
    equilibrium: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "swing_low": self.swing_low.as_dict(),
            "swing_high": self.swing_high.as_dict(),
            "equilibrium": self.equilibrium,
        }


@dataclass(frozen=True)
class PriorDayLevels:
    previous_date: date | None
    pdh: float | None
    pdl: float | None
    pdh_state: LiquidityState
    pdl_state: LiquidityState

    def as_dict(self) -> dict[str, Any]:
        return {
            "previous_utc_trading_date": None if self.previous_date is None else self.previous_date.isoformat(),
            "pdh": self.pdh,
            "pdl": self.pdl,
            "pdh_state": self.pdh_state.value,
            "pdl_state": self.pdl_state.value,
        }


@dataclass(frozen=True)
class LiquidityContext:
    levels: PriorDayLevels
    nearest_objective: float | None
    nearest_objective_name: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "levels": self.levels.as_dict(),
            "nearest_objective": self.nearest_objective,
            "nearest_objective_name": self.nearest_objective_name,
        }


@dataclass(frozen=True)
class MAState:
    timeframe: str
    fast_period: int
    slow_period: int
    fast: float | None
    slow: float | None
    state: Direction
    insufficient_history: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "fast_period": self.fast_period,
            "slow_period": self.slow_period,
            "ma50": self.fast,
            "ma200": self.slow,
            "state": self.state.value,
            "insufficient_history": self.insufficient_history,
        }


@dataclass(frozen=True)
class BiasDecision:
    hypothesis: str
    direction: Direction
    decision_time: datetime | None
    evidence: Mapping[str, Any]
    invalidation_reference: float | None
    invalidation_type: str | None
    macro_direction: Direction
    immediate_direction: Direction
    phase: Phase
    location: Location
    liquidity_objective: float | None
    status: str = "RUN"

    def as_dict(self) -> dict[str, Any]:
        return {
            "hypothesis": self.hypothesis,
            "direction": self.direction.value,
            "bias_direction": self.direction.value,
            "decision_time": None if self.decision_time is None else self.decision_time.isoformat(),
            "evidence": _jsonable(dict(self.evidence)),
            "invalidation_reference": self.invalidation_reference,
            "invalidation_type": self.invalidation_type,
            "macro_direction": self.macro_direction.value,
            "immediate_direction": self.immediate_direction.value,
            "phase": self.phase.value,
            "location": self.location.value,
            "liquidity_objective": self.liquidity_objective,
            "status": self.status,
        }


@dataclass(frozen=True)
class TargetGeometry:
    target_id: str
    direction: Direction
    entry_price: float
    stop_price: float
    target_price: float | None
    initial_risk_distance: float | None
    target_distance: float | None
    target_r: float | None
    status: str
    selected_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {
            "direction": self.direction.value,
            "selected_at": None if self.selected_at is None else self.selected_at.isoformat(),
        }


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "as_dict"):
        return value.as_dict()
    return value


def _closed_bars(bars: Sequence[Any], asof_index: int | None) -> tuple[Any, ...]:
    if not bars:
        return ()
    end = len(bars) - 1 if asof_index is None else min(int(asof_index), len(bars) - 1)
    if end < 0:
        return ()
    return tuple(bars[: end + 1])


def _validate_bar_timestamps(bars: Sequence[Any]) -> None:
    previous: datetime | None = None
    for bar in bars:
        timestamp = bar.timestamp
        if timestamp.tzinfo is None:
            raise ValueError("causal diagnostics require timezone-aware timestamps")
        if previous is not None and timestamp < previous:
            raise ValueError("bars must be chronological")
        previous = timestamp


def confirmed_swing_points(
    bars: Sequence[Any],
    order: int = 2,
    asof_index: int | None = None,
) -> tuple[SwingPoint, ...]:
    """Return strict, right-bar-confirmed swing points.

    A high/low at ``i`` is usable at ``i + order`` only.  Equal neighboring
    highs/lows are not classified, avoiding an unstated equal-liquidity
    tolerance.  This is intentionally independent of the full dataset.
    """
    if order < 1:
        raise ValueError("swing order must be positive")
    closed = _closed_bars(bars, asof_index)
    _validate_bar_timestamps(closed)
    points: list[SwingPoint] = []
    prior_high: SwingPoint | None = None
    prior_low: SwingPoint | None = None
    for i in range(order, len(closed) - order):
        bar = closed[i]
        left = closed[i - order : i]
        right = closed[i + 1 : i + order + 1]
        is_high = all(bar.high > other.high for other in (*left, *right))
        is_low = all(bar.low < other.low for other in (*left, *right))
        if is_high:
            label = None if prior_high is None else ("HH" if bar.high > prior_high.price else "LH")
            point = SwingPoint(i, bar.timestamp, "HIGH", float(bar.high), label, i + order)
            points.append(point)
            prior_high = point
        if is_low:
            label = None if prior_low is None else ("HL" if bar.low > prior_low.price else "LL")
            point = SwingPoint(i, bar.timestamp, "LOW", float(bar.low), label, i + order)
            points.append(point)
            prior_low = point
    return tuple(sorted(points, key=lambda point: (point.confirmation_index, point.index, point.kind)))


def _structure_direction(points: Sequence[SwingPoint]) -> Direction:
    highs = [x for x in points if x.kind == "HIGH" and x.label is not None]
    lows = [x for x in points if x.kind == "LOW" and x.label is not None]
    if not highs or not lows:
        return Direction.NEUTRAL
    high_label = highs[-1].label
    low_label = lows[-1].label
    if high_label == "HH" and low_label == "HL":
        return Direction.BULL
    if high_label == "LH" and low_label == "LL":
        return Direction.BEAR
    return Direction.NEUTRAL


def _bos_events(closed: Sequence[Any], points: Sequence[SwingPoint]) -> tuple[BosEvent, ...]:
    events: list[BosEvent] = []
    for point in points:
        for index in range(point.confirmation_index + 1, len(closed)):
            bar = closed[index]
            if point.kind == "HIGH" and bar.close > point.price:
                events.append(BosEvent(index, bar.timestamp, Direction.BULL, point.index, point.price))
                break
            if point.kind == "LOW" and bar.close < point.price:
                events.append(BosEvent(index, bar.timestamp, Direction.BEAR, point.index, point.price))
                break
    return tuple(sorted(events, key=lambda event: (event.index, event.broken_swing_index, event.direction.value)))


def structure_state(
    bars: Sequence[Any],
    order: int = 2,
    asof_index: int | None = None,
) -> StructureState:
    """Compute confirmed HH/HL/LH/LL, BOS, and structural invalidation."""
    closed = _closed_bars(bars, asof_index)
    points = confirmed_swing_points(closed, order=order)
    highs = [x for x in points if x.kind == "HIGH"]
    lows = [x for x in points if x.kind == "LOW"]
    latest_high = highs[-1] if highs else None
    latest_low = lows[-1] if lows else None
    direction = _structure_direction(points)
    if direction == Direction.BULL and latest_low is not None:
        invalidation_reference, invalidation_type = latest_low.price, "PROTECTED_SWING_LOW"
    elif direction == Direction.BEAR and latest_high is not None:
        invalidation_reference, invalidation_type = latest_high.price, "PROTECTED_SWING_HIGH"
    else:
        invalidation_reference, invalidation_type = None, None
    return StructureState(
        direction=direction,
        as_of_index=(len(closed) - 1 if closed else -1),
        swing_points=points,
        bos_events=_bos_events(closed, points),
        latest_high=latest_high,
        latest_low=latest_low,
        invalidation_reference=invalidation_reference,
        invalidation_type=invalidation_type,
    )


def active_swing_range(
    bars: Sequence[Any], order: int = 2, asof_index: int | None = None
) -> ActiveSwingRange | None:
    """Return the most recent confirmed high/low envelope if it is valid."""
    state = structure_state(bars, order=order, asof_index=asof_index)
    if state.latest_high is None or state.latest_low is None:
        return None
    if state.latest_high.price <= state.latest_low.price:
        return None
    return ActiveSwingRange(
        swing_low=state.latest_low,
        swing_high=state.latest_high,
        equilibrium=(state.latest_high.price + state.latest_low.price) / 2.0,
    )


def classify_premium_discount(price: float, equilibrium: float) -> Location:
    if price > equilibrium:
        return Location.PREMIUM
    if price < equilibrium:
        return Location.DISCOUNT
    return Location.MIDRANGE


def prior_day_levels(bars: Sequence[Any], asof: datetime | None = None) -> PriorDayLevels:
    """Build PDH/PDL from the previous observed UTC trading date.

    The previous date is selected only from bars closed no later than ``asof``;
    weekends/gaps are skipped by selecting the previous observed UTC date.
    A sweep is strictly beyond the level (equality is not a sweep).
    """
    _validate_bar_timestamps(bars)
    if not bars and asof is None:
        return PriorDayLevels(None, None, None, LiquidityState.UNAVAILABLE, LiquidityState.UNAVAILABLE)
    if asof is None:
        asof = bars[-1].timestamp
    if asof.tzinfo is None:
        raise ValueError("asof must be timezone-aware")
    closed = tuple(bar for bar in bars if bar.timestamp <= asof)
    current_date = asof.astimezone(timezone.utc).date()
    grouped: dict[date, list[Any]] = {}
    for bar in closed:
        day = bar.timestamp.astimezone(timezone.utc).date()
        if day < current_date:
            grouped.setdefault(day, []).append(bar)
    if not grouped:
        return PriorDayLevels(None, None, None, LiquidityState.UNAVAILABLE, LiquidityState.UNAVAILABLE)
    previous = max(grouped)
    source = grouped[previous]
    pdh = max(float(bar.high) for bar in source)
    pdl = min(float(bar.low) for bar in source)
    current = [bar for bar in closed if bar.timestamp.astimezone(timezone.utc).date() == current_date]
    pdh_swept = any(float(bar.high) > pdh for bar in current)
    pdl_swept = any(float(bar.low) < pdl for bar in current)
    return PriorDayLevels(
        previous_date=previous,
        pdh=pdh,
        pdl=pdl,
        pdh_state=LiquidityState.SWEPT if pdh_swept else LiquidityState.INTACT,
        pdl_state=LiquidityState.SWEPT if pdl_swept else LiquidityState.INTACT,
    )


def liquidity_context(
    bars: Sequence[Any],
    asof: datetime | None = None,
    price: float | None = None,
    direction: Direction = Direction.NEUTRAL,
) -> LiquidityContext:
    levels = prior_day_levels(bars, asof=asof)
    if price is None and bars:
        eligible = [bar for bar in bars if asof is None or bar.timestamp <= asof]
        price = float(eligible[-1].close) if eligible else None
    objective: float | None = None
    name: str | None = None
    if direction == Direction.BULL and levels.pdh is not None and price is not None and levels.pdh > price:
        objective, name = levels.pdh, "PDH"
    elif direction == Direction.BEAR and levels.pdl is not None and price is not None and levels.pdl < price:
        objective, name = levels.pdl, "PDL"
    return LiquidityContext(levels, objective, name)


def _sma(bars: Sequence[Any], period: int) -> float | None:
    if len(bars) < period:
        return None
    return sum(float(bar.close) for bar in bars[-period:]) / period


def ma_direction(
    bars: Sequence[Any], timeframe: str, fast_period: int = 50, slow_period: int = 200
) -> MAState:
    """Frozen 50/200 simple-moving-average direction context."""
    if fast_period != 50 or slow_period != 200:
        raise ValueError("the direction MA hypothesis freezes periods at 50 and 200")
    fast = _sma(bars, fast_period)
    slow = _sma(bars, slow_period)
    if fast is None or slow is None:
        state = Direction.NEUTRAL
    elif fast > slow:
        state = Direction.BULL
    elif fast < slow:
        state = Direction.BEAR
    else:
        state = Direction.NEUTRAL
    return MAState(timeframe, fast_period, slow_period, fast, slow, state, fast is None or slow is None)


def phase_for(macro: Direction, immediate: Direction) -> Phase:
    if macro == Direction.NEUTRAL or immediate == Direction.NEUTRAL:
        return Phase.NEUTRAL
    if macro == immediate:
        return Phase.CONTINUATION
    return Phase.PULLBACK


def _last_time(*frames: Sequence[Any]) -> datetime | None:
    available = [frame[-1].timestamp for frame in frames if frame]
    return min(available) if available else None


def _decision(
    hypothesis: str,
    direction: Direction,
    macro: Direction,
    immediate: Direction,
    location: Location,
    evidence: Mapping[str, Any],
    htf_state: StructureState | None,
    decision_time: datetime | None,
    liquidity_objective: float | None = None,
    status: str = "RUN",
    invalidation_state: StructureState | None = None,
    fallback_invalidation_reference: float | None = None,
    fallback_invalidation_type: str | None = None,
) -> BiasDecision:
    reference_state = invalidation_state or htf_state
    if direction != Direction.NEUTRAL and reference_state is not None and reference_state.invalidation_reference is not None:
        reference, kind = reference_state.invalidation_reference, reference_state.invalidation_type
    elif direction != Direction.NEUTRAL:
        reference, kind = fallback_invalidation_reference, fallback_invalidation_type
    else:
        reference, kind = None, None
    return BiasDecision(
        hypothesis=hypothesis,
        direction=direction,
        decision_time=decision_time,
        evidence=evidence,
        invalidation_reference=reference,
        invalidation_type=kind,
        macro_direction=macro,
        immediate_direction=immediate,
        phase=phase_for(macro, immediate),
        location=location,
        liquidity_objective=liquidity_objective,
        status=status,
    )


def _neutral(hypothesis: str, reason: str, time: datetime | None = None) -> BiasDecision:
    return _decision(
        hypothesis, Direction.NEUTRAL, Direction.NEUTRAL, Direction.NEUTRAL,
        Location.UNAVAILABLE, {"reason": reason}, None, time,
    )


def evaluate_direction_hypothesis(
    hypothesis: str,
    frames: Mapping[str, Sequence[Any]],
    *,
    price: float | None = None,
    asof: Mapping[str, int] | None = None,
    swing_order: int = 2,
) -> BiasDecision:
    """Evaluate MD01-MD12 without combining hypotheses post hoc.

    ``frames`` must contain already-derived closed bars.  ``asof`` optionally
    clips each timeframe independently, which is useful for causality tests.
    ``MD04_D1`` and ``MD04_H4`` are the two preregistered MA variants.
    """
    asof = asof or {}
    def clipped(name: str) -> tuple[Any, ...]:
        return _closed_bars(frames.get(name, ()), asof.get(name))

    h4, d1, h1 = clipped("H4"), clipped("D1"), clipped("H1")
    h4s = structure_state(h4, order=swing_order) if h4 else None
    d1s = structure_state(d1, order=swing_order) if d1 else None
    h1s = structure_state(h1, order=swing_order) if h1 else None
    all_time = _last_time(h4, d1, h1)
    px = price if price is not None else (float(h4[-1].close) if h4 else None)
    h4_range = active_swing_range(h4, order=swing_order) if h4 else None
    location = classify_premium_discount(px, h4_range.equilibrium) if px is not None and h4_range else Location.UNAVAILABLE
    macro = h4s.direction if h4s else Direction.NEUTRAL
    immediate = h1s.direction if h1s else Direction.NEUTRAL
    evidence: dict[str, Any] = {}
    hypothesis = hypothesis.upper()

    if hypothesis == "MD01":
        if h4s is None:
            return _neutral(hypothesis, "H4 structure unavailable", all_time)
        direction = h4s.direction
        evidence = {"h4_structure": h4s.as_dict()}
        return _decision(hypothesis, direction, direction, direction, location, evidence, h4s, all_time)
    if hypothesis == "MD02":
        if h4s is None or d1s is None:
            return _neutral(hypothesis, "D1 or H4 structure unavailable", all_time)
        direction = h4s.direction if h4s.direction == d1s.direction else Direction.NEUTRAL
        evidence = {"d1_structure": d1s.as_dict(), "h4_structure": h4s.as_dict()}
        return _decision(hypothesis, direction, direction, direction, location, evidence, h4s, all_time)
    if hypothesis == "MD03":
        if h4s is None or h1s is None:
            return _neutral(hypothesis, "H1 or H4 structure unavailable", all_time)
        direction = h4s.direction if h4s.direction == h1s.direction else Direction.NEUTRAL
        evidence = {"h4_structure": h4s.as_dict(), "h1_structure": h1s.as_dict()}
        return _decision(hypothesis, direction, direction, direction, location, evidence, h4s, all_time)
    if hypothesis in {"MD04", "MD04_D1", "MD04_H4"}:
        tf = "H4" if hypothesis == "MD04_H4" else "D1"
        frame = clipped(tf)
        ma = ma_direction(frame, tf) if frame else MAState(tf, 50, 200, None, None, Direction.NEUTRAL, True)
        evidence = {"ma": ma.as_dict()}
        ma_invalidation = "MA50_NOT_ABOVE_MA200" if ma.state == Direction.BULL else "MA50_NOT_BELOW_MA200" if ma.state == Direction.BEAR else None
        return _decision(
            hypothesis, ma.state, ma.state, ma.state, location, evidence, h4s, all_time,
            fallback_invalidation_reference=ma.slow,
            fallback_invalidation_type=ma_invalidation,
        )
    if hypothesis == "MD05":
        ma = ma_direction(d1, "D1") if d1 else MAState("D1", 50, 200, None, None, Direction.NEUTRAL, True)
        direction = h4s.direction if h4s and h4s.direction == ma.state else Direction.NEUTRAL
        evidence = {"h4_structure": None if h4s is None else h4s.as_dict(), "ma": ma.as_dict()}
        return _decision(hypothesis, direction, direction, direction, location, evidence, h4s, all_time)
    if hypothesis == "MD06":
        direction = Direction.NEUTRAL
        if h4s and h4s.direction == Direction.BULL and location == Location.DISCOUNT:
            direction = Direction.BULL
        elif h4s and h4s.direction == Direction.BEAR and location == Location.PREMIUM:
            direction = Direction.BEAR
        evidence = {"h4_structure": None if h4s is None else h4s.as_dict(), "location": location.value}
        return _decision(hypothesis, direction, macro, immediate, location, evidence, h4s, all_time)
    if hypothesis == "MD07":
        direction = immediate
        evidence = {"h1_structure": None if h1s is None else h1s.as_dict()}
        return _decision(hypothesis, direction, macro, immediate, location, evidence, h1s, all_time, invalidation_state=h1s)
    if hypothesis == "MD08":
        evidence = {"h4_structure": None if h4s is None else h4s.as_dict(), "h1_structure": None if h1s is None else h1s.as_dict()}
        return _decision(hypothesis, macro, macro, immediate, location, evidence, h4s, all_time)
    if hypothesis in {"MD09", "MD10", "MD11", "MD12"}:
        if h4s is None or h1s is None or h4_range is None:
            return _neutral(hypothesis, "required structure/location unavailable", all_time)
        location_direction = (
            Direction.BULL if h4s.direction == Direction.BULL and location == Location.DISCOUNT
            else Direction.BEAR if h4s.direction == Direction.BEAR and location == Location.PREMIUM
            else Direction.NEUTRAL
        )
        core_direction = location_direction if location_direction == immediate else Direction.NEUTRAL
        levels_context = liquidity_context(h4, asof=h4[-1].timestamp if h4 else None, price=px, direction=core_direction)
        evidence = {
            "h4_structure": h4s.as_dict(),
            "h1_structure": h1s.as_dict(),
            "active_range": h4_range.as_dict(),
            "location": location.value,
        }
        if hypothesis in {"MD10", "MD11"}:
            evidence["liquidity_context"] = levels_context.as_dict()
            if levels_context.levels.previous_date is None:
                return _neutral(hypothesis, "prior-day liquidity unavailable", all_time)
        if hypothesis == "MD12":
            ma = ma_direction(d1, "D1") if d1 else MAState("D1", 50, 200, None, None, Direction.NEUTRAL, True)
            evidence["ma"] = ma.as_dict()
            if ma.state != h4s.direction:
                core_direction = Direction.NEUTRAL
        return _decision(
            hypothesis, core_direction, macro, immediate, location, evidence, h4s, all_time,
            levels_context.nearest_objective if hypothesis in {"MD10", "MD11"} else None,
        )
    return _neutral(hypothesis, "unknown preregistered hypothesis", all_time)


def classify_alignment(
    direction: Direction | str,
    macro_direction: Direction | str,
    immediate_direction: Direction | str,
) -> str:
    """Classify a trigger against macro and immediate direction separately."""
    direction = Direction(direction)
    macro_direction = Direction(macro_direction)
    immediate_direction = Direction(immediate_direction)
    if direction == Direction.NEUTRAL:
        return "NEUTRAL"
    if direction == macro_direction == immediate_direction:
        return "ALIGNED"
    if direction == macro_direction and immediate_direction != direction:
        return "MACRO_ALIGNED_INTERNAL_COUNTER"
    if direction == immediate_direction and macro_direction != direction:
        return "MACRO_COUNTER_INTERNAL_ALIGNED"
    if direction != macro_direction and direction != immediate_direction:
        return "COUNTER_DIRECTION"
    return "NEUTRAL"


def natural_target_r(entry_price: float, stop_price: float, target_price: float) -> float | None:
    risk = abs(float(entry_price) - float(stop_price))
    if risk <= 0 or not all(isfinite(float(x)) for x in (entry_price, stop_price, target_price)):
        return None
    return abs(float(target_price) - float(entry_price)) / risk


def target_geometry(
    target_id: str,
    direction: Direction,
    entry_price: float,
    stop_price: float,
    target_price: float | None,
    selected_at: datetime | None = None,
) -> TargetGeometry:
    risk = abs(entry_price - stop_price)
    distance = None if target_price is None else abs(target_price - entry_price)
    target_r = None if target_price is None else natural_target_r(entry_price, stop_price, target_price)
    status = "VALID" if risk > 0 and target_price is not None and target_r is not None else "MISSING_TARGET"
    return TargetGeometry(target_id, direction, entry_price, stop_price, target_price, risk or None, distance, target_r, status, selected_at)


def fixed_target_geometry(
    target_id: str,
    direction: Direction,
    entry_price: float,
    stop_price: float,
    multiple: float,
    selected_at: datetime | None = None,
) -> TargetGeometry:
    if multiple <= 0:
        raise ValueError("fixed target R must be positive")
    risk = abs(entry_price - stop_price)
    if risk <= 0 or direction == Direction.NEUTRAL:
        return target_geometry(target_id, direction, entry_price, stop_price, None, selected_at)
    target = entry_price + risk * multiple if direction == Direction.BULL else entry_price - risk * multiple
    return target_geometry(target_id, direction, entry_price, stop_price, target, selected_at)


def fixed_target_capability(
    bars_after_entry: Sequence[Any],
    direction: Direction,
    entry_price: float,
    stop_price: float,
    multiple: float,
) -> str:
    """Evaluate fixed-target reach before stop, with same-bar ambiguity explicit."""
    geometry = fixed_target_geometry("FIXED", direction, entry_price, stop_price, multiple)
    if geometry.target_price is None:
        return "MISSING_TARGET"
    for bar in bars_after_entry:
        target_hit = (bar.high >= geometry.target_price) if direction == Direction.BULL else (bar.low <= geometry.target_price)
        stop_hit = (bar.low <= stop_price) if direction == Direction.BULL else (bar.high >= stop_price)
        if target_hit and stop_hit:
            return "AMBIGUOUS_SAME_BAR"
        if target_hit:
            return "TARGET"
        if stop_hit:
            return "STOP"
    return "UNRESOLVED"


__all__ = [
    "ActiveSwingRange", "BiasDecision", "BosEvent", "Direction", "LiquidityContext",
    "LiquidityState", "Location", "MAState", "Phase", "PriorDayLevels", "StructureState",
    "SwingPoint", "TargetGeometry", "active_swing_range", "classify_alignment",
    "classify_premium_discount", "confirmed_swing_points", "evaluate_direction_hypothesis",
    "fixed_target_capability", "fixed_target_geometry", "liquidity_context", "ma_direction",
    "natural_target_r", "phase_for", "prior_day_levels", "structure_state", "target_geometry",
]
