"""Software-side voltage monitoring and reactive emergency stop.

By deliberate design choice (see docs / config/power_supply_profiles.json
notes), this application does NOT push a calculated safety ceiling into
the power supply's own OVP circuit. Instead, the calculated value is kept
as a software-only threshold, and this monitor periodically polls the
instrument's actual output voltage and triggers a full emergency stop
itself if that threshold is ever exceeded -- the application is the
safety mechanism, not the instrument's own hardware protection.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

from src.drivers.base_instrument import InstrumentCommunicationError
from src.safety.safety_manager import SafetyManager, SafetyViolationError

# PowerSupplyController and RampConfig both (indirectly) import this package,
# so import them lazily -- at module level, only for type checkers -- to
# avoid a circular import at runtime.
if TYPE_CHECKING:
    from src.drivers.power_supply import PowerSupplyController
    from src.measurement.ramping import RampConfig


class VoltageMonitor(QObject):
    """Polls ``power_supply.get_actual_voltage()`` on a timer and compares
    it against ``power_supply.voltage_monitoring_threshold``.

    On breach: ramps to zero FIRST (while the SafetyManager's emergency-stop
    flag is not yet set, since once it is, no further current command --
    including zero -- is permitted), then raises the emergency-stop flag,
    then disables the output. This ordering matters: triggering emergency
    stop before attempting the ramp would make the ramp-to-zero itself
    impossible.
    """

    threshold_exceeded = Signal(float, float)  # (actual_voltage, threshold)
    voltage_read = Signal(float)  # actual_voltage, emitted on every successful poll

    def __init__(
        self,
        power_supply: PowerSupplyController,
        safety_manager: SafetyManager,
        ramp_config: RampConfig | None = None,
        poll_interval_ms: int = 500,
        logger=None,
    ) -> None:
        super().__init__()
        from src.measurement.ramping import RampConfig as _RampConfig  # local: avoids circular import

        self.power_supply = power_supply
        self.safety_manager = safety_manager
        self.ramp_config = ramp_config or _RampConfig()
        self._logger = logger
        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self._poll)
        self._tripped = False

    def _log(self, msg: str, level: str = "info") -> None:
        if self._logger is not None:
            getattr(self._logger, level, self._logger.info)(msg)

    # ------------------------------------------------------------------
    def start(self) -> None:
        """Begin polling, but only if a threshold and a real readback
        command are actually available -- silently does nothing otherwise
        (e.g. simulation / a profile without voltage readback)."""
        self._tripped = False
        if self.power_supply.voltage_monitoring_threshold is None:
            return
        if "get_actual_voltage" not in self.power_supply.profile.commands:
            self._log(
                "Voltage monitoring threshold is set but this profile has no "
                "get_actual_voltage command -- monitoring cannot run.",
                level="warning",
            )
            return
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    @property
    def is_running(self) -> bool:
        return self._timer.isActive()

    # ------------------------------------------------------------------
    def _poll(self) -> None:
        if self._tripped:
            return
        threshold = self.power_supply.voltage_monitoring_threshold
        if threshold is None:
            self._timer.stop()
            return

        actual = self.power_supply.get_actual_voltage()
        if actual is None:
            return  # readback failed once; try again next tick

        # This is the instrument's real metered output voltage
        # (MEAS:VOLT:DC?) -- emitted for any live display purposes,
        # independent of the trip check below.
        self.voltage_read.emit(actual)

        if actual > threshold:
            self._trip(actual, threshold)

    def _trip(self, actual: float, threshold: float) -> None:
        from src.measurement.ramping import CurrentRamper  # local: avoids circular import

        self._tripped = True
        self._timer.stop()
        self._log(
            f"VOLTAGE MONITORING THRESHOLD EXCEEDED: {actual:.3f} V > {threshold:.3f} V -- "
            "triggering emergency stop",
            level="critical",
        )

        # Ramp to zero FIRST: once trigger_emergency_stop() below sets the
        # flag, the SafetyManager rejects every current command, including
        # a ramp to zero -- so this must happen while it can still work.
        try:
            CurrentRamper(self.power_supply, self.ramp_config, logger=self._logger).ramp_to_zero(
                context="voltage monitoring emergency stop"
            )
        except (SafetyViolationError, InstrumentCommunicationError) as exc:
            self._log(
                f"Could not confirm ramp to zero during voltage emergency stop: {exc}. "
                "Physical current is UNKNOWN -- verify manually.",
                level="critical",
            )

        self.safety_manager.trigger_emergency_stop()

        try:
            self.power_supply.disable_output()
        except InstrumentCommunicationError as exc:
            self._log(
                f"Could not confirm output disabled during voltage emergency stop: {exc}. "
                "Physical output state is UNKNOWN -- verify manually.",
                level="critical",
            )

        self.threshold_exceeded.emit(actual, threshold)
