import pytest

from src.measurement.ramping import generate_ramp_steps


def test_ramp_up_generates_expected_intermediate_steps():
    steps = generate_ramp_steps(0.0, 1.0, 0.25)
    assert steps == pytest.approx([0.25, 0.5, 0.75, 1.0])


def test_ramp_down_generates_expected_intermediate_steps():
    steps = generate_ramp_steps(1.0, 0.0, 0.25)
    assert steps == pytest.approx([0.75, 0.5, 0.25, 0.0])


def test_ramp_always_ends_exactly_on_target_even_with_uneven_step():
    steps = generate_ramp_steps(0.0, 1.0, 0.3)
    assert steps[-1] == pytest.approx(1.0)
    assert steps[:-1] == pytest.approx([0.3, 0.6, 0.9])


def test_ramp_with_start_equal_to_end_returns_single_point():
    steps = generate_ramp_steps(0.5, 0.5, 0.1)
    assert steps == [0.5]


def test_ramp_step_must_be_positive():
    with pytest.raises(ValueError):
        generate_ramp_steps(0.0, 1.0, 0.0)
    with pytest.raises(ValueError):
        generate_ramp_steps(0.0, 1.0, -0.1)


def test_negative_to_positive_ramp():
    steps = generate_ramp_steps(-1.0, 1.0, 0.5)
    assert steps == pytest.approx([-0.5, 0.0, 0.5, 1.0])
