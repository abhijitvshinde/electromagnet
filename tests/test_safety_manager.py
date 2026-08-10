import pytest

from src.safety.safety_manager import SafetyManager, SafetyViolationError


def test_max_current_must_be_configured_before_validation():
    sm = SafetyManager()
    with pytest.raises(SafetyViolationError):
        sm.validate_current(0.5)


def test_positive_and_negative_currents_within_limit_pass():
    sm = SafetyManager()
    sm.set_max_current(2.0)
    assert sm.validate_current(1.5) == 1.5
    assert sm.validate_current(-1.5) == -1.5


def test_boundary_value_equal_to_max_is_allowed():
    sm = SafetyManager()
    sm.set_max_current(2.0)
    assert sm.validate_current(2.0) == 2.0
    assert sm.validate_current(-2.0) == -2.0


def test_current_above_max_is_rejected():
    sm = SafetyManager()
    sm.set_max_current(2.0)
    with pytest.raises(SafetyViolationError):
        sm.validate_current(2.0001)
    with pytest.raises(SafetyViolationError):
        sm.validate_current(-2.0001)


def test_cannot_change_max_current_while_locked():
    sm = SafetyManager()
    sm.set_max_current(2.0)
    sm.acquire_lock("measurement_running")
    with pytest.raises(SafetyViolationError):
        sm.set_max_current(3.0)
    sm.release_lock("measurement_running")
    sm.set_max_current(3.0)
    assert sm.max_current == 3.0


def test_emergency_stop_blocks_all_current_commands():
    sm = SafetyManager()
    sm.set_max_current(2.0)
    sm.trigger_emergency_stop()
    with pytest.raises(SafetyViolationError):
        sm.validate_current(0.1)
    sm.clear_emergency_stop()
    assert sm.validate_current(0.1) == 0.1


def test_validate_sequence_flags_out_of_range_points_without_raising():
    sm = SafetyManager()
    sm.set_max_current(1.0)
    rows = sm.validate_sequence([0.5, 1.0, 1.5, -2.0])
    assert [r.within_current_limit for r in rows] == [True, True, False, False]
