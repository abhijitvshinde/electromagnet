import pytest

from src.calibration.calibration_manager import CalibrationManager
from src.measurement.sweep import build_validation_table, generate_field_values, summarize_sequence
from src.safety.safety_manager import SafetyManager


def _calibrated_manager(max_current=2.0):
    sm = SafetyManager()
    sm.set_max_current(max_current)
    cal = CalibrationManager(sm)
    cal.add_point(0.0, 0.0, direction="increasing")
    cal.add_point(1.0, 500.0, direction="increasing")
    cal.add_point(0.0, 0.0, direction="decreasing")
    cal.add_point(1.0, 500.0, direction="decreasing")
    return cal, sm


def test_generate_forward_field_values():
    pairs = generate_field_values(0, 100, 25, mode="forward")
    assert [p[0] for p in pairs] == pytest.approx([0, 25, 50, 75, 100])
    assert all(p[1] == "forward" for p in pairs)


def test_generate_reverse_field_values():
    pairs = generate_field_values(0, 100, 25, mode="reverse")
    assert [p[0] for p in pairs] == pytest.approx([100, 75, 50, 25, 0])


def test_generate_forward_reverse_doubles_points():
    pairs = generate_field_values(0, 100, 25, mode="forward_reverse")
    assert len(pairs) == 10


def test_custom_list_mode():
    pairs = generate_field_values(0, 0, 1, mode="custom", custom_values=[10, 20, 30])
    assert [p[0] for p in pairs] == [10, 20, 30]


def test_repeats_multiplies_sequence():
    pairs = generate_field_values(0, 100, 50, mode="forward", repeats=3)
    assert len(pairs) == 9


def test_build_validation_table_all_valid_sequence():
    cal, sm = _calibrated_manager(max_current=2.0)
    pairs = generate_field_values(0, 400, 100, mode="forward")
    rows = build_validation_table(pairs, cal, sm)
    assert all(r.is_valid for r in rows)
    summary = summarize_sequence(rows)
    assert summary.all_valid
    assert summary.total_points == len(rows)


def test_build_validation_table_flags_out_of_calibration_range():
    cal, sm = _calibrated_manager(max_current=2.0)
    pairs = generate_field_values(0, 800, 100, mode="forward")  # 800 Oe exceeds 500 Oe calibrated range
    rows = build_validation_table(pairs, cal, sm)
    summary = summarize_sequence(rows)
    assert not summary.all_valid
    assert any(not r.within_calibration_range for r in rows)


def test_build_validation_table_allows_extrapolation_when_enabled():
    cal, sm = _calibrated_manager(max_current=2.0)
    pairs = generate_field_values(0, 550, 550, mode="forward")  # 550 Oe is 10% beyond the 500 Oe calibrated max
    rows = build_validation_table(pairs, cal, sm, allow_extrapolation=True, extrapolation_margin_fraction=0.2)
    summary = summarize_sequence(rows)
    assert summary.all_valid
    assert any(r.extrapolated for r in rows)
    assert not any(r.within_calibration_range and r.extrapolated for r in rows)


def test_build_validation_table_flags_current_above_max():
    cal, sm = _calibrated_manager(max_current=0.2)  # max current well below what 500 Oe needs
    pairs = generate_field_values(0, 400, 200, mode="forward")
    rows = build_validation_table(pairs, cal, sm)
    summary = summarize_sequence(rows)
    assert not summary.all_valid
    assert any(not r.within_current_limit for r in rows)
