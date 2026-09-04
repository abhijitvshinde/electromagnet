"""Regression test for a real incident: an instrument can accept a write
over GPIB (no transport-level exception) while its own SCPI parser
silently rejects the command (e.g. a profile mismatch -- commands meant
for a different instrument model). A transport-level success must not be
mistaken for the instrument actually having applied the command."""
from __future__ import annotations

import pytest

from src.config.app_config import InstrumentProfile
from src.drivers.base_instrument import InstrumentCommunicationError, Transport
from src.drivers.power_supply import PowerSupplyController
from src.measurement.ramping import CurrentRamper, RampConfig
from src.safety.safety_manager import SafetyManager

_PROFILE = InstrumentProfile(
    name="TEST",
    manufacturer="Test",
    model="Test",
    description="",
    commands={
        "identify": "*IDN?",
        "set_current": "BOGUS:SEL P6V;CURR {value:.6f}",
        "output_on": "OUTP ON",
        "output_off": "OUTP OFF",
        "get_error_queue": "SYST:ERR?",
    },
)


class RejectingTransport(Transport):
    """Accepts every write without raising, but SYST:ERR? reports the
    instrument actually rejected the previous command -- mirrors a real
    E3634A rejecting an E3631A-specific INST:SEL prefix it doesn't
    support, while the GPIB write itself completes normally."""

    def __init__(self) -> None:
        self._open = False
        self.writes: list[str] = []
        self._pending_errors: list[str] = []

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def write(self, command: str) -> None:
        self.writes.append(command)
        if "BOGUS:SEL" in command:
            self._pending_errors = ['-113,"Undefined header"', '-224,"Illegal parameter value"']

    def query(self, command: str) -> str:
        if command == "*IDN?":
            return "TEST,TEST,0,0"
        if command == "SYST:ERR?":
            if self._pending_errors:
                return self._pending_errors.pop(0)
            return "+0,No error"
        raise InstrumentCommunicationError(f"unexpected command {command!r}")


def test_check_for_errors_raises_when_instrument_rejected_the_command():
    transport = RejectingTransport()
    sm = SafetyManager()
    sm.set_max_current(1.0)
    ps = PowerSupplyController(_PROFILE, transport, sm)
    ps.open_connection()

    ps.set_current(0.5, context="test")
    assert transport.writes[-1] == "BOGUS:SEL P6V;CURR 0.500000"  # the write itself "succeeded"

    with pytest.raises(InstrumentCommunicationError, match="Undefined header"):
        ps.check_for_errors(context="test")


def test_ramp_with_verify_no_error_catches_silently_rejected_command():
    transport = RejectingTransport()
    sm = SafetyManager()
    sm.set_max_current(1.0)
    ps = PowerSupplyController(_PROFILE, transport, sm)
    ps.open_connection()
    ramper = CurrentRamper(ps, RampConfig(current_step_a=0.5, step_delay_s=0.0, stabilization_time_s=0.0))

    with pytest.raises(InstrumentCommunicationError, match="Undefined header"):
        ramper.ramp_to(0.5, context="test", verify_no_error=True)


def test_ramp_without_verify_no_error_does_not_catch_it():
    """Documents the tradeoff: verify_no_error=False (the default, used
    for fast per-step ramping) will NOT catch a rejected command -- only
    an explicit verification call does."""
    transport = RejectingTransport()
    sm = SafetyManager()
    sm.set_max_current(1.0)
    ps = PowerSupplyController(_PROFILE, transport, sm)
    ps.open_connection()
    ramper = CurrentRamper(ps, RampConfig(current_step_a=0.5, step_delay_s=0.0, stabilization_time_s=0.0))

    ramper.ramp_to(0.5, context="test")  # does not raise, even though rejected
    assert ps.last_commanded_current_a == 0.5  # software believes it, instrument did not apply it
