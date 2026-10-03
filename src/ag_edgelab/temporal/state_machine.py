"""Deterministic temporal stage machine with SEQUENCE ordering semantics.

A candidate advances through declared stages in strict order. Every stage
carries a deterministic expiry measured in bars of the driving timeframe;
an event arriving after its stage window expired cannot advance the
candidate. Wrong-ordering events are rejected with a stable rejection code.
The machine never rewinds; completed candidates are terminal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ag_edgelab.funnels.runner import StageMode

CANONICAL_MODE = StageMode.SEQUENCE


class StageExpired(Exception):
    pass


class OutOfOrderTransition(Exception):
    def __init__(self, expected: str, received: str, rejection_code: str) -> None:
        super().__init__(f"expected stage {expected}, received {received}")
        self.expected = expected
        self.received = received
        self.rejection_code = rejection_code


class MachineStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class TemporalStage:
    stage_id: str
    max_bars_in_stage: int  # deterministic expiry, bars of driving timeframe

    def __post_init__(self) -> None:
        if self.max_bars_in_stage < 1:
            raise ValueError("stage expiry must be at least one bar")


@dataclass(frozen=True)
class TransitionRecord:
    stage_id: str
    observed_at: datetime  # event close time (information availability)
    driving_bar_index: int
    attributes: tuple[tuple[str, str], ...] = ()


class TemporalStateMachine:
    def __init__(self, machine_id: str, stages: tuple[TemporalStage, ...]) -> None:
        if not stages:
            raise ValueError("at least one stage is required")
        ids = [stage.stage_id for stage in stages]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate stage id")
        self.machine_id = machine_id
        self.mode = CANONICAL_MODE
        self._stages = stages
        self._position = 0
        self._entered_at_index: int | None = None
        self._transitions: list[TransitionRecord] = []
        self.status = MachineStatus.ACTIVE
        self.rejection_code: str | None = None

    @property
    def transitions(self) -> tuple[TransitionRecord, ...]:
        return tuple(self._transitions)

    @property
    def current_stage(self) -> TemporalStage | None:
        if self.status != MachineStatus.ACTIVE:
            return None
        return self._stages[self._position]

    def arm(self, driving_bar_index: int) -> None:
        """Start the first stage's expiry window at machine creation time."""
        if self._transitions:
            raise ValueError("cannot arm a machine that already transitioned")
        self._entered_at_index = driving_bar_index

    def reject(self, code: str) -> None:
        self.status = MachineStatus.REJECTED
        self.rejection_code = code

    def advance(self, stage_id: str, *, observed_at: datetime, driving_bar_index: int) -> TransitionRecord:
        """Record the next expected stage event. Any other event rejects."""
        if self.status != MachineStatus.ACTIVE:
            raise OutOfOrderTransition("TERMINAL", stage_id, f"MACHINE_{self.status.value}")
        stage = self._stages[self._position]
        if stage_id != stage.stage_id:
            code = f"OUT_OF_ORDER_EXPECTED_{stage.stage_id}"
            self.reject(code)
            raise OutOfOrderTransition(stage.stage_id, stage_id, code)
        if self._entered_at_index is not None and driving_bar_index - self._entered_at_index > stage.max_bars_in_stage:
            self.status = MachineStatus.EXPIRED
            self.rejection_code = f"EXPIRED_{stage.stage_id}"
            raise StageExpired(f"{stage.stage_id} exceeded {stage.max_bars_in_stage} bars")
        record = TransitionRecord(
            stage_id=stage_id,
            observed_at=observed_at,
            driving_bar_index=driving_bar_index,
        )
        self._transitions.append(record)
        self._position += 1
        self._entered_at_index = driving_bar_index
        if self._position == len(self._stages):
            self.status = MachineStatus.COMPLETE
        return record

    def expire_check(self, driving_bar_index: int) -> bool:
        """Deterministically expire the machine if the open stage window ran out."""
        if self.status != MachineStatus.ACTIVE or self._entered_at_index is None:
            return False
        stage = self._stages[self._position]
        if driving_bar_index - self._entered_at_index > stage.max_bars_in_stage:
            self.status = MachineStatus.EXPIRED
            self.rejection_code = f"EXPIRED_{stage.stage_id}"
            return True
        return False
