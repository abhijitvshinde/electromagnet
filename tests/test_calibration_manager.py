import pytest

from src.calibration.calibration_manager import CalibrationManager, CalibrationRangeError
from src.safety.safety_manager import SafetyManager, SafetyViolationError


def make_manager(max_current=5.0):
    sm = SafetyManager()
    sm.set_max_current(max_current)
    return CalibrationManager(sm), sm


def test_piecewise_linear_interpolation_midpoint():
    cal, _ = make_manager()
    cal.add_point(0.0, 0.0, direction="increasing")
    cal.add_point(1.0, 100.0, direction="increasing")
    current = cal.current_for_field(50.0, direction="increasing")
    assert current == pytest.approx(0.5)


def test_does_not_extrapolate_outside_calibrated_range():
    cal, _ = make_manager()
    cal.add_point(0.0, 0.0, direction="increasing")
    cal.add_point(1.0, 100.0, direction="increasing")
    with pytest.raises(CalibrationRangeError):
        cal.current_for_field(150.0, direction="increasing")


def test_field_requiring_current_above_max_is_rejected():
    cal, sm = make_manager(max_current=0.5)
    cal.add_point(0.0, 0.0, direction="increasing")
    cal.add_point(1.0, 100.0, direction="increasing")
    with pytest.raises(SafetyViolationError):
        cal.current_for_field(80.0, direction="increasing")


def test_validate_field_request_reports_status_without_raising():
    cal, sm = make_manager(max_current=0.5)
    cal.add_point(0.0, 0.0, direction="increasing")
    cal.add_point(1.0, 100.0, direction="increasing")

    ok, current, status = cal.validate_field_request(80.0, direction="increasing")
    assert not ok
    assert current is None
    assert "EXCEEDS MAX CURRENT" in status

    ok2, current2, status2 = cal.validate_field_request(1000.0, direction="increasing")
    assert not ok2
    assert "OUTSIDE CALIBRATION RANGE" in status2


def test_validation_detects_duplicate_currents():
    cal, _ = make_manager()
    cal.add_point(1.0, 100.0, direction="increasing")
    cal.add_point(1.0, 105.0, direction="increasing")
    issues = cal.validate()
    assert any("Duplicate current" in i for i in issues)


def test_validation_detects_non_monotonic_curve():
    cal, _ = make_manager()
    cal.add_point(0.0, 0.0, direction="increasing")
    cal.add_point(1.0, 100.0, direction="increasing")
    cal.add_point(2.0, 50.0, direction="increasing")
    issues = cal.validate()
    assert any("not monotonic" in i for i in issues)


def test_validation_flags_current_exceeding_max():
    cal, sm = make_manager(max_current=1.0)
    cal.add_point(0.0, 0.0, direction="increasing")
    cal.add_point(2.0, 100.0, direction="increasing")
    issues = cal.validate()
    assert any("exceeds maximum allowable current" in i for i in issues)


def test_average_of_increasing_and_decreasing_curves():
    cal, _ = make_manager()
    cal.add_point(0.0, 0.0, direction="increasing")
    cal.add_point(1.0, 100.0, direction="increasing")
    cal.add_point(0.0, 10.0, direction="decreasing")
    cal.add_point(1.0, 110.0, direction="decreasing")
    current = cal.current_for_field(55.0, direction="average")
    inc = cal.current_for_field(55.0, direction="increasing")
    dec = cal.current_for_field(55.0, direction="decreasing")
    assert current == pytest.approx((inc + dec) / 2.0)
