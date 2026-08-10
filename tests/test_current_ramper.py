import pytest

from src.config.app_config import default_power_supply_profile
from src.drivers.power_supply import PowerSupplyController
from src.drivers.simulation import SimulatedPowerSupplyTransport, SimulationEngine
from src.measurement.ramping import AbortRequested, CurrentRamper, RampConfig
from src.safety.safety_manager import SafetyManager, SafetyViolationError


def make_driver(max_current=2.0):
    engine = SimulationEngine(comm_delay_s=0.0)
    transport = SimulatedPowerSupplyTransport(engine)
    profile = default_power_supply_profile()
    sm = SafetyManager()
    sm.set_max_current(max_current)
    driver = PowerSupplyController(profile, transport, sm)
    driver.open_connection()
    return driver, sm, engine


def test_ramp_to_target_reaches_exact_value():
    driver, sm, engine = make_driver(max_current=2.0)
    ramper = CurrentRamper(driver, RampConfig(current_step_a=0.3, step_delay_s=0.0, stabilization_time_s=0.0))
    ramper.ramp_to(1.0, context="test")
    assert driver.last_commanded_current_a == pytest.approx(1.0)
    assert engine.present_current_a == pytest.approx(1.0)


def test_ramp_to_zero_from_nonzero_current():
    driver, sm, engine = make_driver(max_current=2.0)
    ramper = CurrentRamper(driver, RampConfig(current_step_a=0.3, step_delay_s=0.0, stabilization_time_s=0.0))
    ramper.ramp_to(1.2, context="setup")
    ramper.ramp_to_zero()
    assert driver.last_commanded_current_a == 0.0
    assert engine.present_current_a == 0.0


def test_ramp_never_exceeds_max_current_even_with_large_step():
    driver, sm, engine = make_driver(max_current=1.0)
    ramper = CurrentRamper(driver, RampConfig(current_step_a=5.0, step_delay_s=0.0, stabilization_time_s=0.0))
    with pytest.raises(SafetyViolationError):
        ramper.ramp_to(1.0 + 0.5, context="oversized target should be rejected before any step")


def test_ramp_can_be_aborted_mid_sequence():
    driver, sm, engine = make_driver(max_current=2.0)
    ramper = CurrentRamper(driver, RampConfig(current_step_a=0.1, step_delay_s=0.0, stabilization_time_s=0.0))
    call_count = {"n": 0}

    def should_abort():
        call_count["n"] += 1
        return call_count["n"] > 2

    with pytest.raises(AbortRequested):
        ramper.ramp_to(1.0, context="test", should_abort=should_abort)
    assert driver.last_commanded_current_a < 1.0
