"""Vector Network Analyzer driver.

Retrieves complex S11/S21 data. The default parsing assumes the common
ASCII comma-separated real,imag-pair SDATA format used by many VNAs. If
your instrument only supports IEEE-488.2 binary block transfers, replace
:meth:`VNAController._parse_ascii_vector` with a binary-block parser and
set ``supports_binary_transfer: true`` plus the byte order in
``config/vna_profiles.json`` -- see docs/SCPI_REPLACEMENT_GUIDE.md.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from .base_instrument import BaseInstrumentDriver, InstrumentCommunicationError, Transport
from src.config.app_config import InstrumentProfile


@dataclass
class VNASweepConfig:
    start_freq_hz: float
    stop_freq_hz: float
    num_points: int
    source_power_dbm: float
    if_bandwidth_hz: float
    sweep_time_s: float | None
    averaging_enabled: bool
    averages: int
    channel: int
    trigger_mode: str
    measure_s11: bool = True
    measure_s21: bool = True

    @property
    def frequency_spacing_hz(self) -> float:
        if self.num_points <= 1:
            return 0.0
        return (self.stop_freq_hz - self.start_freq_hz) / (self.num_points - 1)

    def frequency_array(self) -> np.ndarray:
        return np.linspace(self.start_freq_hz, self.stop_freq_hz, self.num_points)


@dataclass
class SParameterResult:
    frequencies_hz: np.ndarray
    real: np.ndarray
    imag: np.ndarray

    @property
    def magnitude_linear(self) -> np.ndarray:
        return np.sqrt(self.real ** 2 + self.imag ** 2)

    @property
    def magnitude_db(self) -> np.ndarray:
        mag = self.magnitude_linear
        with np.errstate(divide="ignore"):
            return 20.0 * np.log10(np.clip(mag, 1e-15, None))

    @property
    def phase_deg(self) -> np.ndarray:
        return np.degrees(np.arctan2(self.imag, self.real))


class VNAController(BaseInstrumentDriver):
    def __init__(self, profile: InstrumentProfile, transport: Transport, logger=None) -> None:
        super().__init__(profile, transport, logger)
        self._config: VNASweepConfig | None = None

    @property
    def config(self) -> VNASweepConfig | None:
        return self._config

    def configure(self, config: VNASweepConfig) -> None:
        ch = config.channel
        self._write_cmd("select_channel", channel=ch)
        self._write_cmd("set_start_freq", channel=ch, value_hz=config.start_freq_hz)
        self._write_cmd("set_stop_freq", channel=ch, value_hz=config.stop_freq_hz)
        self._write_cmd("set_num_points", channel=ch, points=config.num_points)
        self._write_cmd("set_source_power", channel=ch, value_dbm=config.source_power_dbm)
        self._write_cmd("set_if_bandwidth", channel=ch, value_hz=config.if_bandwidth_hz)
        if config.sweep_time_s:
            self._write_cmd("set_sweep_time", channel=ch, value_s=config.sweep_time_s)
        self._write_cmd("set_averaging_state", channel=ch, state=1 if config.averaging_enabled else 0)
        if config.averaging_enabled:
            self._write_cmd("set_averaging_count", channel=ch, count=config.averages)
            self._write_cmd("clear_averaging", channel=ch)
        self._write_cmd("set_trigger_mode", channel=ch, mode=config.trigger_mode)
        self._config = config
        self._log(
            "VNA configured: "
            f"{config.start_freq_hz / 1e9:.4f}-{config.stop_freq_hz / 1e9:.4f} GHz, "
            f"{config.num_points} pts, spacing {config.frequency_spacing_hz / 1e3:.3f} kHz, "
            f"IFBW {config.if_bandwidth_hz:.1f} Hz, power {config.source_power_dbm:.1f} dBm, "
            f"avg={config.averaging_enabled}({config.averages})"
        )

    def trigger_sweep_and_wait(self, timeout_s: float = 30.0) -> None:
        if self._config is None:
            raise InstrumentCommunicationError("VNA has not been configured")
        self._write_cmd("trigger_single_sweep", channel=self._config.channel)
        start = time.monotonic()
        while True:
            try:
                resp = self._query_cmd("query_sweep_complete").strip()
                if resp.startswith("1"):
                    return
            except InstrumentCommunicationError:
                return
            if time.monotonic() - start > timeout_s:
                raise InstrumentCommunicationError("Timed out waiting for VNA sweep to complete")
            time.sleep(0.02)

    def get_s_parameter(self, which: str) -> SParameterResult:
        if which not in ("S11", "S21"):
            raise ValueError("which must be 'S11' or 'S21'")
        if self._config is None:
            raise InstrumentCommunicationError("VNA has not been configured")

        ch = self._config.channel
        select_key = "select_measurement_s11" if which == "S11" else "select_measurement_s21"
        data_key = "get_sdata_s11" if which == "S11" else "get_sdata_s21"
        self._write_cmd(select_key, channel=ch)
        raw = self._query_cmd(data_key, channel=ch)
        values = self._parse_ascii_vector(raw)
        if len(values) != 2 * self._config.num_points:
            raise InstrumentCommunicationError(
                f"Unexpected {which} data length: got {len(values)} values for "
                f"{self._config.num_points} points"
            )
        real = values[0::2]
        imag = values[1::2]
        freqs = self._config.frequency_array()
        return SParameterResult(freqs, real, imag)

    @staticmethod
    def _parse_ascii_vector(raw: str) -> np.ndarray:
        raw = raw.strip()
        parts = [p for p in raw.replace("\n", " ").split(",") if p.strip() != ""]
        try:
            return np.array([float(p) for p in parts], dtype=float)
        except ValueError as exc:
            raise InstrumentCommunicationError(f"Could not parse VNA ASCII data: {exc}") from exc
