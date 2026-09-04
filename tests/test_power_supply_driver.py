import pytest

from src.config.app_config import default_power_supply_profile, power_supply_profiles
from src.drivers.base_instrument import InstrumentStatus
from src.drivers.power_supply import PowerSupplyController
from src.drivers.simulation import SimulatedPowerSupplyTransport, SimulationEngine
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


def test_set_current_within_limit_reaches_simulated_hardware():
    driver, sm, engine = make_driver(max_current=2.0)
    driver.set_current(1.5, context="test")
    assert engine.present_current_a == pytest.approx(1.5)
    assert driver.last_commanded_current_a == pytest.approx(1.5)


def test_set_current_above_limit_is_rejected_and_never_reaches_hardware():
    driver, sm, engine = make_driver(max_current=2.0)
    with pytest.raises(SafetyViolationError):
        driver.set_current(2.5, context="test")
    assert engine.present_current_a == 0.0  # unchanged: command never transmitted


def test_negative_current_within_limit_is_allowed():
    driver, sm, engine = make_driver(max_current=2.0)
    driver.set_current(-2.0, context="test")
    assert engine.present_current_a == pytest.approx(-2.0)


def test_disable_output_resets_tracked_current_to_zero():
    driver, sm, engine = make_driver(max_current=2.0)
    driver.set_current(1.0, context="test")
    driver.enable_output()
    driver.disable_output()
    assert driver.last_commanded_current_a == 0.0
    assert engine.output_enabled is False


def test_emergency_stop_blocks_further_current_commands():
    driver, sm, engine = make_driver(max_current=2.0)
    driver.set_current(1.0, context="test")
    sm.trigger_emergency_stop()
    with pytest.raises(SafetyViolationError):
        driver.set_current(0.5, context="test")


def test_optional_hardware_limit_failure_does_not_corrupt_connected_status():
    """Regression test: a real command profile's set_current_limit command
    won't be understood by the plain simulated transport (which only knows
    the GENERIC_PLACEHOLDER vocabulary). That failure is best-effort and
    must not leave the driver stuck reporting Error status when the
    connection itself is actually fine."""
    profile = power_supply_profiles()["HP_AGILENT_E3631A_P6V"]
    engine = SimulationEngine(comm_delay_s=0.0)
    transport = SimulatedPowerSupplyTransport(engine)
    sm = SafetyManager()
    sm.set_max_current(1.5)
    driver = PowerSupplyController(profile, transport, sm)
    driver.open_connection()
    assert driver.status == InstrumentStatus.CONNECTED

    driver.set_hardware_current_limit(1.5)  # command not understood by this transport

    assert driver.status == InstrumentStatus.CONNECTED
    assert driver.is_connected
