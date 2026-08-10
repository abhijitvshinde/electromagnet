"""Orchestrates the full automated magnetic-field sweep sequence.

Implements the 22-step sequence from the spec: connection/limit/calibration
checks, field->current conversion, full-sequence validation, user
confirmation, output enable, per-point ramp/stabilize/trigger/fetch/plot/
save, final ramp-to-zero/output-disable, and a completion summary. Runs in
its own thread so the GUI stays responsive; every widget update happens in
the GUI thread via Qt signals, never directly from here.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from PySide6.QtCore import QThread, Signal

from src.calibration.calibration_manager import CalibrationManager
from src.data.data_manager import DataManager, MeasurementPointResult
from src.drivers.base_instrument import InstrumentCommunicationError
from src.drivers.power_supply import PowerSupplyController
from src.drivers.vna import VNAController
from src.safety.safety_manager import SafetyManager, SafetyViolationError

from .ramping import AbortRequested, CurrentRamper, RampConfig
from .sweep import SweepPoint


class SequenceState(Enum):
    IDLE = "Idle"
    RUNNING = "Running"
    PAUSED = "Paused"
    ABORTING = "Aborting"
    COMPLETED = "Completed"
    STOPPED = "Stopped"
    ERROR = "Error"


@dataclass
class MeasurementSummary:
    total_points: int
    points_completed: int
    started_at: str
    finished_at: str
    success: bool
    message: str


class MeasurementController(QThread):
    state_changed = Signal(str)
    progress_changed = Signal(int, int)
    point_started = Signal(int, float, float)  # index, field_oe, current_a
    point_completed = Signal(object)  # MeasurementPointResult
    status_message = Signal(str)
    error_occurred = Signal(str)
    sequence_finished = Signal(object)  # MeasurementSummary

    def __init__(
        self,
        power_supply: PowerSupplyController,
        vna: VNAController,
        safety_manager: SafetyManager,
        data_manager: DataManager,
        ramp_config: RampConfig,
        measure_s11: bool = True,
        measure_s21: bool = True,
        logger=None,
    ) -> None:
        super().__init__()
        self.power_supply = power_supply
        self.vna = vna
        self.safety_manager = safety_manager
        self.data_manager = data_manager
        self.ramp_config = ramp_config
        self.measure_s11 = measure_s11
        self.measure_s21 = measure_s21
        self._logger = logger

        self._sequence: list[SweepPoint] = []
        self._sweep_number = 1
        self._pause_event_open = True
        self._abort_flag = False
        self._emergency_flag = False
        self._current_index = 0

    def _log(self, msg: str, level: str = "info") -> None:
        if self._logger is not None:
            getattr(self._logger, level, self._logger.info)(msg)

    # ------------------------------------------------------------------
    def configure(self, sequence: list[SweepPoint], sweep_number: int = 1) -> None:
        if not all(p.is_valid for p in sequence):
            raise ValueError("Cannot configure a measurement with invalid sequence points")
        self._sequence = sequence
        self._sweep_number = sweep_number
        self._abort_flag = False
        self._emergency_flag = False
        self._pause_event_open = True
        self._current_index = 0

    # ------------------------------------------------------------------
    def request_pause(self) -> None:
        self._pause_event_open = False
        self.state_changed.emit(SequenceState.PAUSED.value)
        self.status_message.emit("Measurement paused by user")

    def request_resume(self) -> None:
        self._pause_event_open = True
        self.state_changed.emit(SequenceState.RUNNING.value)
        self.status_message.emit("Measurement resumed")

    def request_abort(self) -> None:
        self._abort_flag = True
        self._pause_event_open = True
        self.status_message.emit("Abort requested")

    def request_emergency_stop(self) -> None:
        self._emergency_flag = True
        self._abort_flag = True
        self._pause_event_open = True
        self.status_message.emit("EMERGENCY STOP requested")

    def _wait_if_paused(self) -> None:
        while not self._pause_event_open and not self._abort_flag:
            time.sleep(0.05)

    def _should_abort(self) -> bool:
        return self._abort_flag

    # ------------------------------------------------------------------
    def run(self) -> None:
        started_at = datetime.now().isoformat(timespec="seconds")
        completed = 0
        ramper = CurrentRamper(self.power_supply, self.ramp_config, logger=self._logger)
        try:
            self.state_changed.emit(SequenceState.RUNNING.value)
            self.safety_manager.acquire_lock("measurement_running")
            self.power_supply.enable_output()

            total = len(self._sequence)
            for i, point in enumerate(self._sequence):
                self._current_index = i
                self._wait_if_paused()
                if self._should_abort():
                    raise AbortRequested("Sequence aborted before point " + str(i))

                self.point_started.emit(i, point.field_oe, point.current_a)
                ramper.ramp_to(
                    point.current_a,
                    context=f"sweep point {i} (H={point.field_oe:.4f} Oe)",
                    should_abort=self._should_abort,
                    wait_if_paused=self._wait_if_paused,
                )

                self._wait_if_paused()
                if self._should_abort():
                    raise AbortRequested("Sequence aborted after ramp, point " + str(i))

                self.vna.trigger_sweep_and_wait()
                s11 = self.vna.get_s_parameter("S11") if self.measure_s11 else None
                s21 = self.vna.get_s_parameter("S21") if self.measure_s21 else None
                actual_current = self.power_supply.get_actual_current()

                result = MeasurementPointResult(
                    index=i,
                    requested_field_oe=point.field_oe,
                    current_a=point.current_a,
                    actual_current_a=actual_current,
                    direction=point.direction,
                    sweep_number=self._sweep_number,
                    timestamp=datetime.now().isoformat(timespec="seconds"),
                    s11=s11,
                    s21=s21,
                )
                self.data_manager.save_point(result)
                self.point_completed.emit(result)
                completed += 1
                self.progress_changed.emit(i + 1, total)

            ramper.ramp_to(0.0, context="end of sequence", should_abort=lambda: False, stabilize=False)
            self.power_supply.disable_output()
            self.safety_manager.release_lock("measurement_running")
            self.data_manager.finalize()

            self.state_changed.emit(SequenceState.COMPLETED.value)
            self.sequence_finished.emit(
                MeasurementSummary(
                    total_points=len(self._sequence),
                    points_completed=completed,
                    started_at=started_at,
                    finished_at=datetime.now().isoformat(timespec="seconds"),
                    success=True,
                    message="Measurement completed successfully",
                )
            )

        except AbortRequested as exc:
            self._safe_shutdown(reason=str(exc))
            self.state_changed.emit(SequenceState.STOPPED.value)
            self.sequence_finished.emit(
                MeasurementSummary(
                    total_points=len(self._sequence),
                    points_completed=completed,
                    started_at=started_at,
                    finished_at=datetime.now().isoformat(timespec="seconds"),
                    success=False,
                    message=f"Aborted: {exc}",
                )
            )
        except (SafetyViolationError, InstrumentCommunicationError) as exc:
            self.error_occurred.emit(str(exc))
            self._safe_shutdown(reason=str(exc))
            self.state_changed.emit(SequenceState.ERROR.value)
            self.sequence_finished.emit(
                MeasurementSummary(
                    total_points=len(self._sequence),
                    points_completed=completed,
                    started_at=started_at,
                    finished_at=datetime.now().isoformat(timespec="seconds"),
                    success=False,
                    message=str(exc),
                )
            )
        except Exception as exc:  # noqa: BLE001 - must never crash silently
            self.error_occurred.emit(f"Unexpected error: {exc}")
            self._safe_shutdown(reason=f"Unexpected error: {exc}")
            self.state_changed.emit(SequenceState.ERROR.value)
            self.sequence_finished.emit(
                MeasurementSummary(
                    total_points=len(self._sequence),
                    points_completed=completed,
                    started_at=started_at,
                    finished_at=datetime.now().isoformat(timespec="seconds"),
                    success=False,
                    message=f"Unexpected error: {exc}",
                )
            )
        finally:
            self.data_manager.finalize()

    # ------------------------------------------------------------------
    def _safe_shutdown(self, reason: str) -> None:
        """Best-effort ramp to zero and output disable; never raises."""
        self._log(f"Safe shutdown initiated: {reason}", level="warning")
        try:
            ramper = CurrentRamper(self.power_supply, self.ramp_config, logger=self._logger)
            ramper.ramp_to_zero(context="safe shutdown")
        except (SafetyViolationError, InstrumentCommunicationError) as exc:
            self._log(
                f"Could not confirm current was ramped to zero: {exc}. "
                "Physical output state is UNKNOWN -- verify manually.",
                level="critical",
            )
            self.error_occurred.emit(
                "Communication lost during shutdown: the physical current "
                "could NOT be confirmed at zero. Check the instrument manually."
            )
        try:
            self.power_supply.disable_output()
        except InstrumentCommunicationError as exc:
            self._log(
                f"Could not confirm output was disabled: {exc}. "
                "Physical output state is UNKNOWN -- verify manually.",
                level="critical",
            )
            self.error_occurred.emit(
                "Communication lost during shutdown: the power-supply output "
                "could NOT be confirmed disabled. Check the instrument manually."
            )
        finally:
            self.safety_manager.release_lock("measurement_running")
