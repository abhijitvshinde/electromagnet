"""Drives the manual current-to-field calibration sequence.

For each requested current: ramp gradually to it, hold it stable, and
then BLOCK until the user has externally measured the field and entered
it in the GUI (:meth:`confirm_field`). The sequence never auto-advances
past this point, matching the spec's explicit requirement that a
manually entered field value must be user-confirmed before the software
moves on.
"""
from __future__ import annotations

import time
from datetime import datetime
from enum import Enum

from PySide6.QtCore import QThread, Signal

from src.calibration.calibration_manager import CalibrationManager
from src.drivers.base_instrument import InstrumentCommunicationError
from src.drivers.power_supply import PowerSupplyController
from src.safety.safety_manager import SafetyViolationError

from src.measurement.ramping import AbortRequested, CurrentRamper, RampConfig


class CalibrationState(Enum):
    IDLE = "Idle"
    RUNNING = "Running"
    WAITING_FOR_FIELD = "Waiting for measured field"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    STOPPED = "Stopped"
    ERROR = "Error"


class CalibrationController(QThread):
    state_changed = Signal(str)
    point_ready = Signal(int, float)  # index, commanded current
    status_message = Signal(str)
    error_occurred = Signal(str)
    finished_ok = Signal(bool)

    def __init__(
        self,
        power_supply: PowerSupplyController,
        calibration_manager: CalibrationManager,
        ramp_config: RampConfig,
        logger=None,
    ) -> None:
        super().__init__()
        self.power_supply = power_supply
        self.calibration_manager = calibration_manager
        self.ramp_config = ramp_config
        self._logger = logger

        self._currents: list[float] = []
        self._direction_label = "unspecified"
        self._pause_event_open = True
        self._abort_flag = False
        self._confirmed = False
        self._nav_action: str | None = None
        self._confirmed_field_value: float | None = None

    def _log(self, msg: str, level: str = "info") -> None:
        if self._logger is not None:
            getattr(self._logger, level, self._logger.info)(msg)

    # ------------------------------------------------------------------
    def configure(self, currents: list[float], direction_label: str = "unspecified") -> None:
        self._currents = list(currents)
        self._direction_label = direction_label
        self._pause_event_open = True
        self._abort_flag = False

    def request_pause(self) -> None:
        self._pause_event_open = False
        self.state_changed.emit(CalibrationState.PAUSED.value)

    def request_resume(self) -> None:
        self._pause_event_open = True
        self.state_changed.emit(CalibrationState.RUNNING.value)

    def request_abort(self) -> None:
        self._abort_flag = True
        self._pause_event_open = True
        self._nav_action = "abort"
        self._confirmed = True

    def confirm_field(self, value: float) -> None:
        self._confirmed_field_value = value
        self._nav_action = "confirm"
        self._confirmed = True

    def repeat_current_point(self) -> None:
        self._nav_action = "repeat"
        self._confirmed = True

    def previous_point(self) -> None:
        self._nav_action = "previous"
        self._confirmed = True

    def _wait_if_paused(self) -> None:
        while not self._pause_event_open and not self._abort_flag:
            time.sleep(0.05)

    # ------------------------------------------------------------------
    def run(self) -> None:
        ramper = CurrentRamper(self.power_supply, self.ramp_config, logger=self._logger)
        idx = 0
        try:
            self.state_changed.emit(CalibrationState.RUNNING.value)
            self.power_supply.enable_output()

            while idx < len(self._currents):
                self._wait_if_paused()
                if self._abort_flag:
                    raise AbortRequested("Calibration aborted")

                current = self._currents[idx]
                ramper.ramp_to(
                    current,
                    context=f"calibration point {idx}",
                    should_abort=lambda: self._abort_flag,
                    wait_if_paused=self._wait_if_paused,
                )

                self.status_message.emit(
                    "Enter the measured magnetic field corresponding to the "
                    "presently applied current."
                )
                self.state_changed.emit(CalibrationState.WAITING_FOR_FIELD.value)
                self._confirmed = False
                self._nav_action = None
                self.point_ready.emit(idx, current)

                while not self._confirmed:
                    time.sleep(0.05)
                    if self._abort_flag:
                        raise AbortRequested("Calibration aborted while waiting for field entry")

                action = self._nav_action
                if action == "confirm":
                    actual = self.power_supply.get_actual_current()
                    self.calibration_manager.add_point(
                        commanded_current_a=current,
                        field_oe=self._confirmed_field_value,
                        actual_current_a=actual,
                        direction=self._direction_label,
                    )
                    idx += 1
                    self.state_changed.emit(CalibrationState.RUNNING.value)
                elif action == "repeat":
                    self.state_changed.emit(CalibrationState.RUNNING.value)
                    continue
                elif action == "previous":
                    idx = max(0, idx - 1)
                    self.state_changed.emit(CalibrationState.RUNNING.value)
                else:
                    idx += 1

            self._graceful_stop()
            self.state_changed.emit(CalibrationState.COMPLETED.value)
            self.finished_ok.emit(True)

        except AbortRequested as exc:
            self._log(str(exc), level="warning")
            self._graceful_stop()
            self.state_changed.emit(CalibrationState.STOPPED.value)
            self.finished_ok.emit(False)
        except (SafetyViolationError, InstrumentCommunicationError) as exc:
            self.error_occurred.emit(str(exc))
            self._graceful_stop()
            self.state_changed.emit(CalibrationState.ERROR.value)
            self.finished_ok.emit(False)
        except Exception as exc:  # noqa: BLE001
            self.error_occurred.emit(f"Unexpected error: {exc}")
            self._graceful_stop()
            self.state_changed.emit(CalibrationState.ERROR.value)
            self.finished_ok.emit(False)

    def _graceful_stop(self) -> None:
        try:
            ramper = CurrentRamper(self.power_supply, self.ramp_config, logger=self._logger)
            ramper.ramp_to_zero(context="calibration sequence end")
        except (SafetyViolationError, InstrumentCommunicationError) as exc:
            self._log(f"Could not confirm ramp to zero: {exc}", level="critical")
        try:
            self.power_supply.disable_output()
        except InstrumentCommunicationError as exc:
            self._log(f"Could not confirm output disabled: {exc}", level="critical")
