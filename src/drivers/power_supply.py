"""Power supply driver.

This is the ONLY class in the application permitted to transmit a
current-setting SCPI command. Every call to :meth:`set_current` routes
through :class:`~src.safety.safety_manager.SafetyManager` first; there is
no code path that reaches the transport without that check.
"""
from __future__ import annotations

from src.safety.safety_manager import SafetyManager

from .base_instrument import (
    BaseInstrumentDriver,
    InstrumentCommunicationError,
    Transport,
)
from src.config.app_config import InstrumentProfile


class PowerSupplyController(BaseInstrumentDriver):
    def __init__(
        self,
        profile: InstrumentProfile,
        transport: Transport,
        safety_manager: SafetyManager,
        logger=None,
    ) -> None:
        super().__init__(profile, transport, logger)
        self.safety_manager = safety_manager
        self._output_enabled_local: bool = False
        self.last_commanded_current_a: float = 0.0
        self.last_voltage_limit: float | None = None
        # Software-only monitoring threshold -- NEVER sent to the instrument.
        # Callers (GUI/MeasurementController) poll get_actual_voltage() and
        # compare against this themselves, triggering an emergency stop if
        # it's exceeded, instead of relying on the instrument's own OVP.
        self.voltage_monitoring_threshold: float | None = None

    # ------------------------------------------------------------------
    def set_current(self, value: float, context: str = "manual") -> float:
        """Validate ``value`` against the Safety Manager, then send it.

        This is the single choke point for every current command in the
        application (manual control, calibration, ramping, sweeps, resume,
        error recovery). ``context`` is a short human-readable string used
        only for logging/error messages (e.g. "calibration point 3").
        """
        validated = self.safety_manager.validate_current(value, context=context)
        self._write_cmd("set_current", value=validated)
        self.last_commanded_current_a = validated
        self._log(f"Current command sent: {validated:.6f} A ({context})")
        return validated

    def enable_output(self) -> None:
        self._write_cmd("output_on")
        self._output_enabled_local = True
        self._log("Power supply output ENABLED")

    def disable_output(self) -> None:
        self._write_cmd("output_off")
        self._output_enabled_local = False
        self.last_commanded_current_a = 0.0
        self._log("Power supply output DISABLED")

    @property
    def output_enabled(self) -> bool:
        return self._output_enabled_local

    def set_hardware_current_limit(self, value: float) -> None:
        """Best-effort configuration of the instrument's own current limit.

        The application's own SafetyManager limit is enforced regardless
        of whether this succeeds or whether the instrument supports it.

        A write "succeeding" only means the bytes went out over GPIB -- an
        instrument that doesn't recognize this command (e.g. this specific
        profile's OCP mnemonic being wrong for this firmware) would still
        accept the write and just silently queue a SCPI error, rather than
        failing the write itself. Explicitly check for that immediately
        (rather than leaving it to surface later, unattributed, whenever
        something else happens to drain the queue) so a genuinely
        unsupported command is visible in the log the first time it's
        tried, not invisible on every connect.
        """
        try:
            self._write_cmd("set_current_limit", value=value, critical=False)
            self.check_for_errors(context="hardware current limit (best-effort)")
            self._log(f"Hardware current limit set to {value:.6f} A")
        except InstrumentCommunicationError as exc:
            self._log(f"Could not set hardware current limit: {exc}", level="warning")

    def set_voltage_limit(self, value: float) -> None:
        """Set the CV operating setpoint (the ceiling the supply can reach
        while still regulating on current). This is NOT a passive "never
        exceed" ceiling by itself -- if the commanded current needs this
        much voltage, the supply will genuinely sit at exactly this value.
        Set it generously above what your intended current range actually
        needs so current always stays in control.
        """
        self._write_cmd("set_voltage_limit", value=value)
        self.last_voltage_limit = value

    def set_voltage_monitoring_threshold(self, value: float | None) -> None:
        """Record a software-only voltage ceiling. Nothing is sent to the
        instrument -- the caller is responsible for polling
        :meth:`get_actual_voltage` and reacting (e.g. emergency stop) if it
        is exceeded. Pass None to disable monitoring.
        """
        self.voltage_monitoring_threshold = value
        self._log(
            f"Voltage monitoring threshold set to {value:.6f} V (software-only, not sent to instrument)"
            if value is not None else "Voltage monitoring threshold cleared"
        )

    def get_actual_voltage(self) -> float | None:
        """Read back the measured output voltage, if the profile supports it."""
        if "get_actual_voltage" not in self.profile.commands:
            return None
        try:
            response = self._query_cmd("get_actual_voltage", critical=False)
            return float(response.strip().split(",")[0])
        except (InstrumentCommunicationError, ValueError) as exc:
            self._log(f"Could not read actual voltage: {exc}", level="warning")
            return None

    def clear_protection_trips(self) -> None:
        """Clear a latched overvoltage/overcurrent protection trip, if the
        profile supports it.

        On some instruments (confirmed: Agilent E3634A), a tripped OVP/OCP
        circuit disables the output and a plain output_on command alone
        will NOT restore it -- an explicit clear is required first. This
        is a no-op for profiles that don't define these commands.
        """
        for key, label in (
            ("clear_overvoltage_protection", "overvoltage"),
            ("clear_overcurrent_protection", "overcurrent"),
        ):
            if key in self.profile.commands:
                self._write_cmd(key, critical=False)
                self._log(f"Sent clear command for {label} protection")

    def get_actual_current(self) -> float | None:
        """Read back the measured current, if the instrument supports it."""
        if not self.profile.extra.get("supports_actual_current_readback", False):
            return None
        try:
            response = self._query_cmd("get_current_actual")
            return float(response.strip().split(",")[0])
        except (InstrumentCommunicationError, ValueError) as exc:
            self._log(f"Could not read actual current: {exc}", level="warning")
            return None

    def get_setpoint_current(self) -> float | None:
        try:
            response = self._query_cmd("get_current_setpoint")
            return float(response.strip().split(",")[0])
        except (InstrumentCommunicationError, ValueError):
            return None

    def get_output_state(self) -> bool | None:
        try:
            response = self._query_cmd("get_output_state").strip()
            return response in ("1", "ON", "On", "on")
        except InstrumentCommunicationError:
            return None
