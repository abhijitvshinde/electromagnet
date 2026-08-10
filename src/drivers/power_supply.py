"""Power supply driver.

This is the ONLY class in the application permitted to transmit a
current-setting SCPI command. Every call to :meth:`set_current` routes
through :class:`~src.safety.safety_manager.SafetyManager` first; there is
no code path that reaches the transport without that check.
"""
from __future__ import annotations

from src.safety.safety_manager import SafetyManager

from .base_instrument import BaseInstrumentDriver, InstrumentCommunicationError, Transport
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
        """
        try:
            self._write_cmd("set_current_limit", value=value)
            self._log(f"Hardware current limit set to {value:.6f} A")
        except InstrumentCommunicationError as exc:
            self._log(f"Could not set hardware current limit: {exc}", level="warning")

    def set_voltage_limit(self, value: float) -> None:
        self._write_cmd("set_voltage_limit", value=value)

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
