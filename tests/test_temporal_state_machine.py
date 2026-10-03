from datetime import datetime, timedelta, timezone

import pytest

from ag_edgelab.funnels.runner import StageMode
from ag_edgelab.temporal.state_machine import (
    CANONICAL_MODE,
    MachineStatus,
    OutOfOrderTransition,
    StageExpired,
    TemporalStage,
    TemporalStateMachine,
)

Z = timezone.utc
T0 = datetime(2026, 6, 1, tzinfo=Z)
ORDER = ("HTF_ELIGIBLE", "H1_POI_ACTIVE", "M15_SSL_SWEEP", "M5_BULLISH_CHOCH", "ENTRY")


def _machine():
    stages = tuple(TemporalStage(s, max_bars_in_stage=10) for s in ORDER)
    return TemporalStateMachine("TEST-1", stages)


def test_canonical_mode_is_sequence():
    assert CANONICAL_MODE == StageMode.SEQUENCE
    assert _machine().mode == StageMode.SEQUENCE


def test_happy_path_advances_in_order():
    m = _machine()
    m.arm(0)
    for i, stage in enumerate(ORDER):
        m.advance(stage, observed_at=T0 + timedelta(minutes=5 * i), driving_bar_index=i)
    assert m.status == MachineStatus.COMPLETE
    assert [t.stage_id for t in m.transitions] == list(ORDER)


def test_wrong_order_rejects():
    m = _machine()
    m.arm(0)
    m.advance("HTF_ELIGIBLE", observed_at=T0, driving_bar_index=0)
    with pytest.raises(OutOfOrderTransition) as exc:
        m.advance("M5_BULLISH_CHOCH", observed_at=T0, driving_bar_index=1)
    assert exc.value.rejection_code == "OUT_OF_ORDER_EXPECTED_H1_POI_ACTIVE"
    assert m.status == MachineStatus.REJECTED
    # terminal: nothing can advance a rejected machine
    with pytest.raises(OutOfOrderTransition):
        m.advance("H1_POI_ACTIVE", observed_at=T0, driving_bar_index=2)


def test_skipping_first_stage_rejects():
    m = _machine()
    m.arm(0)
    with pytest.raises(OutOfOrderTransition):
        m.advance("M15_SSL_SWEEP", observed_at=T0, driving_bar_index=0)
    assert m.status == MachineStatus.REJECTED


def test_stage_expiry_is_deterministic():
    m = _machine()
    m.arm(0)
    m.advance("HTF_ELIGIBLE", observed_at=T0, driving_bar_index=0)
    # stage H1_POI_ACTIVE allows at most 10 bars between transitions
    with pytest.raises(StageExpired):
        m.advance("H1_POI_ACTIVE", observed_at=T0, driving_bar_index=11)
    assert m.status == MachineStatus.EXPIRED
    assert m.rejection_code == "EXPIRED_H1_POI_ACTIVE"


def test_expire_check_without_event():
    m = _machine()
    m.arm(0)
    m.advance("HTF_ELIGIBLE", observed_at=T0, driving_bar_index=0)
    assert m.expire_check(10) is False  # exactly at the boundary still alive
    assert m.expire_check(11) is True
    assert m.status == MachineStatus.EXPIRED


def test_first_stage_expires_when_never_observed():
    m = _machine()
    m.arm(3)
    assert m.expire_check(14) is True  # 14 - 3 > 10
    assert m.rejection_code == "EXPIRED_HTF_ELIGIBLE"


def test_same_bar_two_stage_advances_allowed():
    m = _machine()
    m.arm(0)
    m.advance("HTF_ELIGIBLE", observed_at=T0, driving_bar_index=0)
    m.advance("H1_POI_ACTIVE", observed_at=T0, driving_bar_index=0)
    assert m.current_stage.stage_id == "M15_SSL_SWEEP"


def test_duplicate_stage_ids_rejected():
    with pytest.raises(ValueError):
        TemporalStateMachine("X", (TemporalStage("A", 1), TemporalStage("A", 1)))
