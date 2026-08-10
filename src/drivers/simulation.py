"""Simulated transports for software development without physical instruments.

Both simulated transports share a :class:`SimulationEngine` so that the
simulated VNA's resonance dip actually shifts with the simulated power
supply's present current, giving a realistic end-to-end dry run: this
mirrors a ferromagnetic-resonance style experiment where an absorption
feature in S11/S21 moves with the applied field.

These transports understand only the placeholder command vocabulary
defined in ``config/power_supply_profiles.json`` /
``config/vna_profiles.json``. They exist purely for development and
testing of the application logic and are not a substitute for validating
against a real instrument's programming manual.
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field

import numpy as np

from .base_instrument import InstrumentCommunicationError, Transport


@dataclass
class SimulationEngine:
    """Shared physical-world state for all simulated instruments."""

    present_current_a: float = 0.0
    setpoint_current_a: float = 0.0
    output_enabled: bool = False
    comm_delay_s: float = 0.01
    random_error_rate: float = 0.0
    rng: random.Random = field(default_factory=lambda: random.Random(1234))

    # crude ferromagnetic-resonance-like model: resonance frequency and
    # depth depend on the present current (a stand-in for applied field)
    base_resonance_hz: float = 2.0e9
    hz_per_amp: float = 3.0e8
    linewidth_hz: float = 4.0e7
    dip_depth_db: float = 25.0
    noise_db: float = 0.35

    def maybe_fail(self) -> None:
        if self.random_error_rate > 0 and self.rng.random() < self.random_error_rate:
            raise InstrumentCommunicationError("Simulated random communication error")


class SimulatedPowerSupplyTransport(Transport):
    """Recognizes the power-supply placeholder command vocabulary."""

    def __init__(self, engine: SimulationEngine) -> None:
        self.engine = engine
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        time.sleep(self.engine.comm_delay_s)
        self._open = True

    def close(self) -> None:
        self._open = False

    def write(self, command: str) -> None:
        if not self._open:
            raise InstrumentCommunicationError("Simulated transport not open")
        self.engine.maybe_fail()
        time.sleep(self.engine.comm_delay_s)

        m = re.match(r"PLACEHOLDER_SET_CURRENT\s+([-\d.eE+]+)", command)
        if m:
            self.engine.setpoint_current_a = float(m.group(1))
            self.engine.present_current_a = self.engine.setpoint_current_a
            return
        if command.startswith("PLACEHOLDER_SET_CURRENT_LIMIT"):
            return
        if command.startswith("PLACEHOLDER_SET_VOLTAGE_LIMIT"):
            return
        if command.startswith("PLACEHOLDER_OUTPUT_ON"):
            self.engine.output_enabled = True
            return
        if command.startswith("PLACEHOLDER_OUTPUT_OFF"):
            self.engine.output_enabled = False
            self.engine.setpoint_current_a = 0.0
            self.engine.present_current_a = 0.0
            return
        if command in ("*RST", "*CLS"):
            return
        raise InstrumentCommunicationError(f"Simulated power supply: unknown command {command!r}")

    def query(self, command: str) -> str:
        if not self._open:
            raise InstrumentCommunicationError("Simulated transport not open")
        self.engine.maybe_fail()
        time.sleep(self.engine.comm_delay_s)

        if command == "*IDN?":
            return "SIMULATED,PowerSupply,SN-SIM-0001,FW1.0"
        if command == "PLACEHOLDER_GET_CURRENT_SETPOINT?":
            return f"{self.engine.setpoint_current_a:.6f}"
        if command == "PLACEHOLDER_GET_CURRENT_ACTUAL?":
            noise = self.engine.rng.gauss(0, 0.0015)
            return f"{self.engine.present_current_a + noise:.6f}"
        if command == "PLACEHOLDER_GET_OUTPUT_STATE?":
            return "1" if self.engine.output_enabled else "0"
        if command == "SYST:ERR?":
            return "0,No error"
        raise InstrumentCommunicationError(f"Simulated power supply: unknown query {command!r}")


class SimulatedVNATransport(Transport):
    """Recognizes the VNA placeholder command vocabulary and fabricates
    a shifting Lorentzian absorption dip in S11/S21 that tracks the
    simulated electromagnet current."""

    def __init__(self, engine: SimulationEngine) -> None:
        self.engine = engine
        self._open = False
        self.start_freq_hz = 1.0e9
        self.stop_freq_hz = 3.0e9
        self.num_points = 401
        self.source_power_dbm = -10.0
        self.if_bandwidth_hz = 1000.0
        self.averaging_enabled = False
        self.averages = 1
        self.sweep_time_s = 0.05
        self._last_sweep: dict[str, np.ndarray] = {}

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        time.sleep(self.engine.comm_delay_s)
        self._open = True

    def close(self) -> None:
        self._open = False

    def _frequencies(self) -> np.ndarray:
        return np.linspace(self.start_freq_hz, self.stop_freq_hz, self.num_points)

    def _simulate_sweep(self) -> None:
        freqs = self._frequencies()
        f0 = self.engine.base_resonance_hz + self.engine.hz_per_amp * self.engine.present_current_a
        gamma = self.engine.linewidth_hz
        lorentzian = (gamma ** 2) / ((freqs - f0) ** 2 + gamma ** 2)

        s21_db = -0.5 - self.engine.dip_depth_db * lorentzian
        s11_db = -20 + 6 * lorentzian

        n_avg = max(1, self.averages) if self.averaging_enabled else 1
        noise_scale = self.engine.noise_db / np.sqrt(n_avg)
        s21_db = s21_db + self.engine.rng.gauss(0, 1) * 0 + np.array(
            [self.engine.rng.gauss(0, noise_scale) for _ in freqs]
        )
        s11_db = s11_db + np.array([self.engine.rng.gauss(0, noise_scale) for _ in freqs])

        s21_mag = 10 ** (s21_db / 20.0)
        s11_mag = 10 ** (s11_db / 20.0)
        s21_phase = -360.0 * freqs / freqs[-1] + 40 * lorentzian
        s11_phase = 180.0 * np.sin(2 * np.pi * (freqs - freqs[0]) / (freqs[-1] - freqs[0]))

        self._last_sweep = {
            "freqs": freqs,
            "s21_real": s21_mag * np.cos(np.radians(s21_phase)),
            "s21_imag": s21_mag * np.sin(np.radians(s21_phase)),
            "s11_real": s11_mag * np.cos(np.radians(s11_phase)),
            "s11_imag": s11_mag * np.sin(np.radians(s11_phase)),
        }

    def write(self, command: str) -> None:
        if not self._open:
            raise InstrumentCommunicationError("Simulated transport not open")
        self.engine.maybe_fail()
        time.sleep(self.engine.comm_delay_s)

        m = re.match(r"PLACEHOLDER_SET_START_FREQ\s+([-\d.eE+]+)", command)
        if m:
            self.start_freq_hz = float(m.group(1))
            return
        m = re.match(r"PLACEHOLDER_SET_STOP_FREQ\s+([-\d.eE+]+)", command)
        if m:
            self.stop_freq_hz = float(m.group(1))
            return
        m = re.match(r"PLACEHOLDER_SET_NUM_POINTS\s+(\d+)", command)
        if m:
            self.num_points = int(m.group(1))
            return
        m = re.match(r"PLACEHOLDER_SET_SOURCE_POWER\s+([-\d.eE+]+)", command)
        if m:
            self.source_power_dbm = float(m.group(1))
            return
        m = re.match(r"PLACEHOLDER_SET_IFBW\s+([-\d.eE+]+)", command)
        if m:
            self.if_bandwidth_hz = float(m.group(1))
            return
        m = re.match(r"PLACEHOLDER_SET_SWEEP_TIME\s+([-\d.eE+]+)", command)
        if m:
            self.sweep_time_s = float(m.group(1))
            return
        m = re.match(r"PLACEHOLDER_SET_AVG_STATE\s+(\d)", command)
        if m:
            self.averaging_enabled = bool(int(m.group(1)))
            return
        m = re.match(r"PLACEHOLDER_SET_AVG_COUNT\s+(\d+)", command)
        if m:
            self.averages = int(m.group(1))
            return
        if command in (
            "PLACEHOLDER_CLEAR_AVG",
            "PLACEHOLDER_SELECT_MEAS S11",
            "PLACEHOLDER_SELECT_MEAS S21",
            "*RST",
            "*CLS",
        ) or command.startswith("PLACEHOLDER_SELECT_CHANNEL") or command.startswith(
            "PLACEHOLDER_SET_TRIGGER_MODE"
        ):
            return
        if command == "PLACEHOLDER_TRIGGER_SWEEP":
            time.sleep(self.sweep_time_s)
            self._simulate_sweep()
            return
        raise InstrumentCommunicationError(f"Simulated VNA: unknown command {command!r}")

    def query(self, command: str) -> str:
        if not self._open:
            raise InstrumentCommunicationError("Simulated transport not open")
        self.engine.maybe_fail()
        time.sleep(self.engine.comm_delay_s)

        if command == "*IDN?":
            return "SIMULATED,VectorNetworkAnalyzer,SN-SIM-0002,FW1.0"
        if command == "PLACEHOLDER_QUERY_OPC?":
            return "1"
        if command == "SYST:ERR?":
            return "0,No error"
        if command == "PLACEHOLDER_GET_FREQ_DATA":
            if not self._last_sweep:
                self._simulate_sweep()
            return ",".join(f"{v:.6f}" for v in self._last_sweep["freqs"])
        if command == "PLACEHOLDER_GET_SDATA S11":
            if not self._last_sweep:
                self._simulate_sweep()
            re_, im_ = self._last_sweep["s11_real"], self._last_sweep["s11_imag"]
            return ",".join(f"{r:.8f},{i:.8f}" for r, i in zip(re_, im_))
        if command == "PLACEHOLDER_GET_SDATA S21":
            if not self._last_sweep:
                self._simulate_sweep()
            re_, im_ = self._last_sweep["s21_real"], self._last_sweep["s21_imag"]
            return ",".join(f"{r:.8f},{i:.8f}" for r, i in zip(re_, im_))
        raise InstrumentCommunicationError(f"Simulated VNA: unknown query {command!r}")
