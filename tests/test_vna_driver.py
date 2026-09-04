"""Regression tests for VNAController, covering real-hardware bugs found
while bringing up a Keysight N5242B PNA-X:

1. *OPC? can return a signed numeric ('+1') rather than bare '1' --
   trigger_sweep_and_wait must recognize both.
2. A genuine communication failure while polling for sweep completion must
   propagate, not be silently treated as "sweep complete".
"""
from __future__ import annotations

import pytest

from src.config.app_config import InstrumentProfile
from src.drivers.base_instrument import InstrumentCommunicationError, Transport
from src.drivers.vna import VNAController, VNASweepConfig

_PROFILE = InstrumentProfile(
    name="TEST",
    manufacturer="Test",
    model="Test",
    description="",
    commands={
        "identify": "*IDN?",
        "select_channel": "SELECT_CHANNEL {channel}",
        "set_start_freq": "SET_START {value_hz}",
        "set_stop_freq": "SET_STOP {value_hz}",
        "set_num_points": "SET_POINTS {points}",
        "set_source_power": "SET_POWER {value_dbm}",
        "set_if_bandwidth": "SET_IFBW {value_hz}",
        "set_averaging_state": "SET_AVG_STATE {state}",
        "set_trigger_mode": "SET_TRIG {mode}",
        "trigger_single_sweep": "TRIGGER",
        "query_sweep_complete": "OPC?",
    },
)


class ScriptedTransport(Transport):
    """A transport whose query() responses are scripted in advance."""

    def __init__(self, opc_responses: list) -> None:
        self._open = False
        self._opc_responses = list(opc_responses)
        self.written: list[str] = []

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def write(self, command: str) -> None:
        self.written.append(command)

    def query(self, command: str) -> str:
        if command == "*IDN?":
            return "TEST,TEST,0,0"
        if command == "OPC?":
            if not self._opc_responses:
                raise InstrumentCommunicationError("no more scripted responses")
            item = self._opc_responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        raise InstrumentCommunicationError(f"unexpected command {command!r}")


def _configured_vna(opc_responses: list) -> VNAController:
    transport = ScriptedTransport(opc_responses)
    vna = VNAController(_PROFILE, transport)
    vna.open_connection()
    config = VNASweepConfig(
        start_freq_hz=1e9, stop_freq_hz=2e9, num_points=11,
        source_power_dbm=-10.0, if_bandwidth_hz=1000.0, sweep_time_s=None,
        averaging_enabled=False, averages=1, channel=1, trigger_mode="SINGLE",
    )
    vna.configure(config)
    return vna


def test_opc_response_with_explicit_plus_sign_is_recognized():
    """Regression: Keysight N5242B returns '+1', not '1'."""
    vna = _configured_vna(["+1"])
    vna.trigger_sweep_and_wait(timeout_s=2.0)  # must not raise / time out


def test_opc_response_bare_one_still_works():
    vna = _configured_vna(["1"])
    vna.trigger_sweep_and_wait(timeout_s=2.0)


def test_opc_response_not_yet_complete_then_done():
    vna = _configured_vna(["0", "0", "+1"])
    vna.trigger_sweep_and_wait(timeout_s=2.0)


def test_times_out_if_never_reports_complete():
    vna = _configured_vna(["0"] * 1000)
    with pytest.raises(InstrumentCommunicationError, match="Timed out"):
        vna.trigger_sweep_and_wait(timeout_s=0.2)


def test_communication_failure_while_polling_propagates_not_silently_succeeds():
    """Regression: a real comm failure during polling must not be treated
    as sweep-complete."""
    vna = _configured_vna([InstrumentCommunicationError("GPIB timeout")])
    with pytest.raises(InstrumentCommunicationError, match="GPIB timeout"):
        vna.trigger_sweep_and_wait(timeout_s=2.0)


class DataScriptedTransport(ScriptedTransport):
    """Extends ScriptedTransport with scripted responses for an S11 data
    query too, and counts device-clear calls."""

    def __init__(self, opc_responses: list, data_responses: list) -> None:
        super().__init__(opc_responses)
        self._data_responses = list(data_responses)
        self.clears = 0

    def clear(self) -> None:
        self.clears += 1

    def query(self, command: str) -> str:
        if command == "GET_SDATA_S11":
            if not self._data_responses:
                raise InstrumentCommunicationError("no more scripted data responses")
            item = self._data_responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return super().query(command)


def test_get_s_parameter_retries_once_after_transient_query_failure():
    """Regression: a data-fetch query that fails once (e.g. an ASCII
    transfer of many points exceeding the VISA timeout even though the
    sweep itself already completed -- confirmed on real hardware to leave
    the instrument reporting SCPI -420 'Query UNTERMINATED' afterward)
    should be retried once after a device clear, rather than failing the
    whole measurement point immediately."""
    profile = InstrumentProfile(
        name="TEST", manufacturer="Test", model="Test", description="",
        commands={**_PROFILE.commands, "select_measurement_s11": "SELECT_S11", "get_sdata_s11": "GET_SDATA_S11"},
    )
    good_response = ",".join(["1.0", "2.0"] * 11)  # 11 points configured below
    transport = DataScriptedTransport(
        opc_responses=["+1"],
        data_responses=[InstrumentCommunicationError("VI_ERROR_TMO"), good_response],
    )
    vna = VNAController(profile, transport)
    vna.open_connection()
    config = VNASweepConfig(
        start_freq_hz=1e9, stop_freq_hz=2e9, num_points=11,
        source_power_dbm=-10.0, if_bandwidth_hz=1000.0, sweep_time_s=None,
        averaging_enabled=False, averages=1, channel=1, trigger_mode="SINGLE",
    )
    vna.configure(config)

    result = vna.get_s_parameter("S11")

    assert len(result.real) == 11
    assert transport.clears == 1


def test_get_s_parameter_raises_if_retry_also_fails():
    profile = InstrumentProfile(
        name="TEST", manufacturer="Test", model="Test", description="",
        commands={**_PROFILE.commands, "select_measurement_s11": "SELECT_S11", "get_sdata_s11": "GET_SDATA_S11"},
    )
    transport = DataScriptedTransport(
        opc_responses=["+1"],
        data_responses=[InstrumentCommunicationError("VI_ERROR_TMO"), InstrumentCommunicationError("VI_ERROR_TMO")],
    )
    vna = VNAController(profile, transport)
    vna.open_connection()
    config = VNASweepConfig(
        start_freq_hz=1e9, stop_freq_hz=2e9, num_points=11,
        source_power_dbm=-10.0, if_bandwidth_hz=1000.0, sweep_time_s=None,
        averaging_enabled=False, averages=1, channel=1, trigger_mode="SINGLE",
    )
    vna.configure(config)

    with pytest.raises(InstrumentCommunicationError, match="VI_ERROR_TMO"):
        vna.get_s_parameter("S11")
    assert transport.clears == 1
