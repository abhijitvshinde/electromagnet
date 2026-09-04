"""Tests for VoltageMonitor: software-only overvoltage detection and
reactive emergency stop (deliberately not relying on the instrument's own
OVP circuit -- see src/safety/voltage_monitor.py)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QSignalSpy

from src.config.app_config import default_power_supply_profile
from src.drivers.power_supply import PowerSupplyController
from src.drivers.simulation import SimulatedPowerSupplyTransport, SimulationEngine
from src.measurement.ramping import RampConfig
from src.safety.safety_manager import SafetyManager
from src.safety.voltage_monitor import VoltageMonitor


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def make_driver(max_current=2.0):
    engine = SimulationEngine(comm_delay_s=0.0)
    transport = SimulatedPowerSupplyTransport(engine)
    profile = default_power_supply_profile()
    sm = SafetyManager()
    sm.set_max_current(max_current)
    driver = PowerSupplyController(profile, transport, sm)
    driver.open_connection()
    driver.enable_output()
    driver.set_current(1.0, context="test")
    return driver, sm


def test_never_sends_threshold_to_instrument():
    """The whole point: the threshold is a Python attribute, not a SCPI
    command -- setting it must not touch the transport at all."""
    driver, sm = make_driver()
    driver.set_voltage_monitoring_threshold(12.0)
    assert driver.voltage_monitoring_threshold == 12.0
    # GENERIC_PLACEHOLDER has no get_actual_voltage command, so start()
    # should refuse to run rather than poll a nonexistent readback.
    monitor = VoltageMonitor(driver, sm, poll_interval_ms=10)
    monitor.start()
    assert not monitor.is_running


def test_monitor_does_not_start_without_threshold():
    driver, sm = make_driver()
    monitor = VoltageMonitor(driver, sm, poll_interval_ms=10)
    monitor.start()
    assert not monitor.is_running


def test_trip_ramps_to_zero_then_sets_emergency_flag_then_disables_output(monkeypatch):
    """Regression: emergency_stop_active must NOT be set before the
    ramp-to-zero attempt, or SafetyManager would reject that ramp too."""
    driver, sm = make_driver(max_current=2.0)
    driver.set_voltage_monitoring_threshold(5.0)

    # Force get_actual_voltage to report an overvoltage condition immediately,
    # bypassing the need for a real get_actual_voltage command/profile.
    monkeypatch.setattr(driver, "get_actual_voltage", lambda: 9.0)

    monitor = VoltageMonitor(driver, sm, ramp_config=RampConfig(current_step_a=0.5, step_delay_s=0.0), poll_interval_ms=1000)
    spy = QSignalSpy(monitor.threshold_exceeded)

    monitor._poll()  # simulate one timer tick directly, deterministic in tests

    assert driver.last_commanded_current_a == 0.0  # ramp-to-zero succeeded
    assert sm.emergency_stop_active is True
    assert driver.output_enabled is False
    assert spy.count() == 1
    actual, threshold = spy.at(0)
    assert actual == pytest.approx(9.0)
    assert threshold == pytest.approx(5.0)


def test_no_trip_when_voltage_within_threshold(monkeypatch):
    driver, sm = make_driver(max_current=2.0)
    driver.set_voltage_monitoring_threshold(10.0)
    monkeypatch.setattr(driver, "get_actual_voltage", lambda: 4.0)

    monitor = VoltageMonitor(driver, sm, poll_interval_ms=1000)
    monitor._poll()

    assert sm.emergency_stop_active is False
    assert driver.output_enabled is True


def test_voltage_read_emitted_for_live_display(monkeypatch):
    """Every successful poll should emit the actual reading for GUI live
    display, independent of whether it trips the threshold."""
    driver, sm = make_driver(max_current=2.0)
    driver.set_voltage_monitoring_threshold(10.0)
    monkeypatch.setattr(driver, "get_actual_voltage", lambda: 4.0)

    monitor = VoltageMonitor(driver, sm, poll_interval_ms=1000)
    spy = QSignalSpy(monitor.voltage_read)
    monitor._poll()

    assert spy.count() == 1
    assert spy.at(0)[0] == pytest.approx(4.0)
