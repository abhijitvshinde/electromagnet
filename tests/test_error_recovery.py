"""Regression test: a -410 "Query INTERRUPTED" response while draining the
error queue must trigger a device clear and one retry, not be reported as
a real error about whatever command we were actually checking."""
from __future__ import annotations

import pytest

from src.config.app_config import InstrumentProfile
from src.drivers.base_instrument import BaseInstrumentDriver, InstrumentCommunicationError, Transport

_PROFILE = InstrumentProfile(
    name="TEST", manufacturer="Test", model="Test", description="",
    commands={"identify": "*IDN?", "get_error_queue": "SYST:ERR?"},
)


class ScriptedTransport(Transport):
    def __init__(self, responses: list[str]) -> None:
        self._open = False
        self._responses = list(responses)
        self.clear_calls = 0

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def write(self, command: str) -> None:
        pass

    def query(self, command: str) -> str:
        if command == "*IDN?":
            return "TEST,TEST,0,0"
        if not self._responses:
            return "+0,No error"
        return self._responses.pop(0)

    def clear(self) -> None:
        self.clear_calls += 1


def _connected_driver(responses: list[str]) -> tuple[BaseInstrumentDriver, ScriptedTransport]:
    transport = ScriptedTransport(responses)
    driver = BaseInstrumentDriver(_PROFILE, transport)
    driver.open_connection()
    return driver, transport


def test_query_interrupted_triggers_clear_and_retry_then_succeeds():
    driver, transport = _connected_driver(["-410,\"Query INTERRUPTED\"", "+0,No error"])
    errors = driver.check_for_errors(context="test")
    assert errors == []
    assert transport.clear_calls == 1


def test_real_error_after_clean_retry_still_raises():
    driver, transport = _connected_driver(['-410,"Query INTERRUPTED"', '-224,"Illegal parameter value"', "+0,No error"])
    with pytest.raises(InstrumentCommunicationError, match="Illegal parameter value"):
        driver.check_for_errors(context="test")
    assert transport.clear_calls == 1


def test_real_error_without_410_raises_directly_no_clear_needed():
    driver, transport = _connected_driver(['-224,"Illegal parameter value"', "+0,No error"])
    with pytest.raises(InstrumentCommunicationError, match="Illegal parameter value"):
        driver.check_for_errors(context="test")
    assert transport.clear_calls == 0
