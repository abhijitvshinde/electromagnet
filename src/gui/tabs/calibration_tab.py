"""Tab 3: Current-to-Field Calibration.

Supports both loading an existing calibration file and running a manual,
user-confirmed calibration sequence (ramp to current -> stabilize -> user
measures field externally -> user enters and confirms the value -> save
-> move on). Every calibration current is validated against the maximum
current limit before it is ever sent.
"""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from src.calibration.calibration_controller import CalibrationController
from src.drivers.base_instrument import InstrumentCommunicationError
from src.gui.app_context import AppContext
from src.measurement.ramping import CurrentRamper, RampConfig
from src.safety.safety_manager import SafetyViolationError
from src.safety.voltage_monitor import VoltageMonitor


class CalibrationTab(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller: CalibrationController | None = None
        self._last_manual_set_current: float | None = None
        self._last_manual_actual_current: float | None = None
        self._voltage_monitor: VoltageMonitor | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(self._build_load_box())
        layout.addWidget(self._build_manual_point_box())
        layout.addWidget(self._build_create_box())
        layout.addWidget(self._build_controls_box())

        split = QHBoxLayout()
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["#", "Commanded I (A)", "Actual I (A)", "Field (Oe)", "Polarity", "Direction", "Timestamp"]
        )
        split.addWidget(self.table, 2)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel("bottom", "Current", units="A")
        self.plot_widget.setLabel("left", "Magnetic Field", units="Oe")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        split.addWidget(self.plot_widget, 2)
        layout.addLayout(split)

        self.status_label = QLabel("No calibration sequence running.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.range_label = QLabel()
        layout.addWidget(self.range_label)

        self.issues_box = QTextEdit()
        self.issues_box.setReadOnly(True)
        self.issues_box.setMaximumHeight(90)
        layout.addWidget(self.issues_box)

        self._refresh_table()

    def _build_load_box(self) -> QGroupBox:
        box = QGroupBox("Option 1: Load Existing Calibration")
        row = QHBoxLayout(box)
        self.load_path_edit = QLineEdit()
        row.addWidget(self.load_path_edit)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_load)
        row.addWidget(browse_btn)
        load_btn = QPushButton("Load Calibration")
        load_btn.clicked.connect(self._load_calibration)
        row.addWidget(load_btn)
        save_btn = QPushButton("Save Calibration")
        save_btn.clicked.connect(self._save_calibration)
        row.addWidget(save_btn)
        return box

    def _build_manual_point_box(self) -> QGroupBox:
        """Directly type in one (current, field) pair -- e.g. from an
        external measurement already made -- without driving the power
        supply through the guided ramp/confirm sequence at all."""
        box = QGroupBox("Manually Enter Current/Field Point")
        grid = QGridLayout(box)

        grid.addWidget(QLabel("Current (A):"), 0, 0)
        self.manual_current_spin = QDoubleSpinBox()
        self.manual_current_spin.setRange(-10000, 10000)
        self.manual_current_spin.setDecimals(6)
        grid.addWidget(self.manual_current_spin, 0, 1)

        set_current_btn = QPushButton("Set Current")
        set_current_btn.setToolTip(
            "Ramps the power supply to this current (safety-validated, same code path as "
            "everything else). Measure the field externally with the current applied, then "
            "enter it and click Add Point."
        )
        set_current_btn.clicked.connect(self._set_manual_current)
        grid.addWidget(set_current_btn, 0, 2)

        grid.addWidget(QLabel("Field (Oe):"), 0, 3)
        self.manual_field_spin = QDoubleSpinBox()
        self.manual_field_spin.setRange(-1e7, 1e7)
        self.manual_field_spin.setDecimals(4)
        grid.addWidget(self.manual_field_spin, 0, 4)

        grid.addWidget(QLabel("Direction:"), 0, 5)
        self.manual_direction_combo = QComboBox()
        self.manual_direction_combo.addItems(["unspecified", "increasing", "decreasing"])
        grid.addWidget(self.manual_direction_combo, 0, 6)

        grid.addWidget(QLabel("Notes:"), 1, 0)
        self.manual_notes_edit = QLineEdit()
        grid.addWidget(self.manual_notes_edit, 1, 1, 1, 3)

        add_btn = QPushButton("Add Point")
        add_btn.clicked.connect(self._add_manual_point)
        grid.addWidget(add_btn, 1, 4)

        delete_btn = QPushButton("Delete Selected Point")
        delete_btn.clicked.connect(self._delete_selected_point)
        grid.addWidget(delete_btn, 1, 5, 1, 2)

        self.manual_status_label = QLabel(
            "Set a current, measure the field externally, enter it above, then Add Point."
        )
        self.manual_status_label.setWordWrap(True)
        grid.addWidget(self.manual_status_label, 2, 0, 1, 7)

        self.manual_voltage_label = QLabel("Present voltage (actual): -")
        self.manual_voltage_label.setToolTip(
            "The instrument's real metered output voltage (MEAS:VOLT:DC?), not a "
            "setpoint/compliance ceiling -- the front panel display may show the "
            "latter in some states, which is not the same thing."
        )
        grid.addWidget(self.manual_voltage_label, 3, 0, 1, 7)

        return box

    def _set_manual_current(self) -> None:
        """Ramp the power supply to the typed-in current so the user can
        measure the resulting field externally before recording the point.
        Uses the exact same safety-validated ramping code as everything
        else in the application."""
        if not self.ctx.safety_manager.is_configured:
            QMessageBox.warning(self, "Set Maximum Current", "Set the maximum allowable current first.")
            return
        if self.ctx.power_supply is None or not self.ctx.power_supply.is_connected:
            QMessageBox.warning(self, "Not Connected", "Connect the power supply first.")
            return
        if self.controller is not None and self.controller.isRunning():
            QMessageBox.warning(
                self, "Calibration Sequence Running",
                "An automated calibration sequence is currently running. Abort it first.",
            )
            return

        # Stop any monitor left running from a previous Set Current click
        # BEFORE touching GPIB again: its background query (every 500ms)
        # can otherwise land between our own write and query below, leaving
        # an unread response in the instrument's output buffer that then
        # causes the NEXT unrelated query to fail with -410 "Query
        # INTERRUPTED". It's restarted fresh further down regardless.
        self._stop_voltage_monitor()

        current = self.manual_current_spin.value()

        if current != 0.0 and self.ctx.power_supply.voltage_monitoring_threshold is None:
            proceed = QMessageBox.question(
                self, "No Voltage Monitoring Threshold Set",
                "No voltage monitoring threshold / compliance voltage has been set "
                "(Safety tab -> 'Set Monitoring Threshold & Compliance Voltage'). "
                "Without it, the app cannot automatically detect an overvoltage "
                "condition and emergency-stop, AND the power supply likely has no "
                "compliance voltage configured -- meaning Set Current below may have "
                "no physical effect at all (output stays near 0V).\n\n"
                "Proceed anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if proceed != QMessageBox.Yes:
                return
        if not self.ctx.safety_manager.is_within_limit(current):
            QMessageBox.critical(
                self, "Safety Violation",
                f"Current {current:.6f} A exceeds the maximum allowable current "
                f"({self.ctx.safety_manager.max_current:.6f} A). Current was not sent.",
            )
            return

        try:
            # Drain and discard whatever's already sitting in the error
            # queue BEFORE this command -- error queues persist until
            # explicitly read out, so without this, a check afterward could
            # report a stale error from something entirely unrelated (e.g.
            # earlier testing) as if this click caused it.
            try:
                self.ctx.power_supply.check_for_errors(context="pre-existing backlog, discarded")
            except InstrumentCommunicationError:
                pass

            # Always (re)send output-on rather than trusting our own
            # tracked flag, which reflects the last command WE sent, not
            # live hardware state -- a protection trip can silently disable
            # the physical output without us ever finding out otherwise.
            self.ctx.power_supply.enable_output()
            # Ramp gradually rather than jumping instantly to the target.
            # CONFIRMED on real hardware: an instant step into an inductive
            # electromagnet coil induces a voltage spike (V = L*di/dt) large
            # enough to trip the supply's OVP, which shorts the output back
            # near 0V within about a second -- silently, with no SCPI error
            # queued. This is exactly the failure mode gradual ramping
            # exists to prevent; a fast ramp (small step, short delay) here
            # avoids the spike while still reaching the target quickly.
            ramp_config = RampConfig(
                current_step_a=self.ramp_step_spin.value(),
                step_delay_s=self.ramp_delay_spin.value(),
                stabilization_time_s=self.stabilization_spin.value(),
            )
            CurrentRamper(self.ctx.power_supply, ramp_config, logger=self.ctx.logger).ramp_to(
                current, context="manual calibration point"
            )
            # The write succeeding only means the bytes went out over GPIB --
            # it does NOT mean the instrument accepted/held the value (e.g. a
            # protection trip can silently drop it back to 0A). Check now,
            # rather than reporting false success like before.
            self.ctx.power_supply.check_for_errors(context="Set Current")
        except (SafetyViolationError, InstrumentCommunicationError) as exc:
            QMessageBox.critical(self, "Could Not Set Current", str(exc))
            return

        self._last_manual_set_current = current
        self._last_manual_actual_current = self.ctx.power_supply.get_actual_current()
        # Show the instrument's real metered output voltage immediately,
        # regardless of whether a monitoring threshold/monitor is active --
        # this is what was causing confusion when read off the front panel
        # (which can show a setpoint/ceiling rather than the live value).
        actual_voltage = self.ctx.power_supply.get_actual_voltage()
        if actual_voltage is not None:
            self.manual_voltage_label.setText(f"Present voltage (actual): {actual_voltage:.4f} V")

        if self._last_manual_actual_current is not None and current != 0.0:
            deviation = abs(self._last_manual_actual_current - current)
            # Flag it if the reading is off by more than 10% of the
            # commanded value (with a small absolute floor for tiny
            # commanded currents where 10% would be unrealistically tight).
            tolerance = max(0.1 * abs(current), 0.002)
            if deviation > tolerance:
                output_state = self.ctx.power_supply.get_output_state()
                state_line = (
                    f"The instrument reports its output as {'ENABLED' if output_state else 'DISABLED'} "
                    "right now, even though we just sent Output On."
                    if output_state is not None else
                    "Could not read back the instrument's own output-enabled state."
                )
                QMessageBox.warning(
                    self, "Current Not Holding",
                    f"Commanded {current:.6f} A, but the instrument reports actual current "
                    f"of only {self._last_manual_actual_current:.6f} A. No SCPI error was "
                    f"queued. {state_line}\n\n"
                    "This looks like a protection trip (OVP/OCP) or insufficient compliance "
                    "voltage on the instrument's own CV setpoint, not an app-level error. Try "
                    "Clear Protection Trip on the Connection tab, and confirm you've clicked "
                    "'Set Monitoring Threshold & Compliance Voltage' on the Safety tab with "
                    "the power supply connected (it sends the compliance-voltage setpoint "
                    "automatically -- reconnecting resets it on this instrument, so it must "
                    "be reapplied after every reconnect).",
                )

        self._start_voltage_monitor()

        msg = f"Current set to {current:.6f} A"
        if self._last_manual_actual_current is not None:
            msg += f" (actual measured: {self._last_manual_actual_current:.6f} A)"
        msg += ". Measure the field externally, enter it above, then click Add Point."
        if self._voltage_monitor is not None and self._voltage_monitor.is_running:
            msg += " Voltage monitoring is active."
        self.manual_status_label.setText(msg)

    def _start_voltage_monitor(self) -> None:
        """(Re)start polling the actual output voltage against the
        software monitoring threshold while this current is held."""
        self._stop_voltage_monitor()
        if self.ctx.power_supply is None:
            return
        self._voltage_monitor = VoltageMonitor(
            self.ctx.power_supply, self.ctx.safety_manager, logger=self.ctx.logger
        )
        self._voltage_monitor.threshold_exceeded.connect(self._on_voltage_threshold_exceeded)
        self._voltage_monitor.voltage_read.connect(self._on_voltage_reading)
        self._voltage_monitor.start()

    def _on_voltage_reading(self, actual: float) -> None:
        """Live update from the running VoltageMonitor's poll -- only fires
        while a monitoring threshold is set (that's what gates the monitor
        actually running at all); see the one-off read in
        _set_manual_current for the always-available alternative."""
        self.manual_voltage_label.setText(f"Present voltage (actual): {actual:.4f} V")

    def _stop_voltage_monitor(self) -> None:
        if self._voltage_monitor is not None:
            self._voltage_monitor.stop()
            self._voltage_monitor = None

    def _on_voltage_threshold_exceeded(self, actual: float, threshold: float) -> None:
        self.manual_status_label.setText(
            f"EMERGENCY STOP: output voltage reached {actual:.3f} V, exceeding the "
            f"{threshold:.3f} V monitoring threshold."
        )
        QMessageBox.critical(
            self, "VOLTAGE EMERGENCY STOP",
            f"The output voltage reached {actual:.3f} V, exceeding the software "
            f"monitoring threshold of {threshold:.3f} V.\n\n"
            "An emergency stop was triggered automatically: the current was ramped "
            "to zero (if communication allowed) and the output was disabled.",
        )

    def _add_manual_point(self) -> None:
        current = self.manual_current_spin.value()
        field = self.manual_field_spin.value()

        if not self.ctx.safety_manager.is_configured:
            QMessageBox.warning(self, "Set Maximum Current", "Set the maximum allowable current first.")
            return
        if not self.ctx.safety_manager.is_within_limit(current):
            QMessageBox.critical(
                self, "Safety Violation",
                f"Current {current:.6f} A exceeds the maximum allowable current "
                f"({self.ctx.safety_manager.max_current:.6f} A). Point was not added.",
            )
            return

        # If this current was just applied via "Set Current", carry over the
        # actual measured current readback (if the instrument supports it).
        actual_current = None
        if self._last_manual_set_current is not None and abs(current - self._last_manual_set_current) < 1e-9:
            actual_current = self._last_manual_actual_current

        self.ctx.calibration_manager.add_point(
            commanded_current_a=current,
            field_oe=field,
            actual_current_a=actual_current,
            direction=self.manual_direction_combo.currentText(),
            notes=self.manual_notes_edit.text(),
        )
        self._stop_voltage_monitor()
        self._refresh_table()
        self.manual_notes_edit.clear()
        self.manual_status_label.setText(
            "Point added. Set a new current, measure the field, enter it above, then Add Point."
        )

    def _delete_selected_point(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "No Selection", "Select a row in the table first.")
            return
        points = self.ctx.calibration_manager.points
        if row >= len(points):
            return
        index = points[row].index
        self.ctx.calibration_manager.delete_point(index)
        self._refresh_table()

    def _build_create_box(self) -> QGroupBox:
        box = QGroupBox("Option 2: Create New Calibration Manually")
        grid = QGridLayout(box)

        grid.addWidget(QLabel("Mode:"), 0, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Start/Stop/Step", "Custom List"])
        grid.addWidget(self.mode_combo, 0, 1)

        grid.addWidget(QLabel("Start (A):"), 0, 2)
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(-10000, 10000)
        self.start_spin.setDecimals(4)
        grid.addWidget(self.start_spin, 0, 3)

        grid.addWidget(QLabel("Stop (A):"), 0, 4)
        self.stop_spin = QDoubleSpinBox()
        self.stop_spin.setRange(-10000, 10000)
        self.stop_spin.setDecimals(4)
        grid.addWidget(self.stop_spin, 0, 5)

        grid.addWidget(QLabel("Step (A):"), 0, 6)
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.0001, 10000)
        self.step_spin.setDecimals(4)
        self.step_spin.setValue(0.1)
        grid.addWidget(self.step_spin, 0, 7)

        grid.addWidget(QLabel("Custom list (comma-separated A):"), 1, 0, 1, 2)
        self.custom_list_edit = QLineEdit()
        grid.addWidget(self.custom_list_edit, 1, 2, 1, 6)

        grid.addWidget(QLabel("Direction label:"), 2, 0)
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["increasing", "decreasing", "unspecified"])
        grid.addWidget(self.direction_combo, 2, 1)

        grid.addWidget(QLabel("Stabilization time (s):"), 2, 2)
        self.stabilization_spin = QDoubleSpinBox()
        self.stabilization_spin.setRange(0, 3600)
        self.stabilization_spin.setValue(self.ctx.settings.default_stabilization_time_s)
        grid.addWidget(self.stabilization_spin, 2, 3)

        grid.addWidget(QLabel("Ramp step (A):"), 2, 4)
        self.ramp_step_spin = QDoubleSpinBox()
        self.ramp_step_spin.setRange(0.0001, 10000)
        self.ramp_step_spin.setDecimals(4)
        self.ramp_step_spin.setValue(self.ctx.settings.default_current_step_a)
        grid.addWidget(self.ramp_step_spin, 2, 5)

        grid.addWidget(QLabel("Ramp delay (s):"), 2, 6)
        self.ramp_delay_spin = QDoubleSpinBox()
        self.ramp_delay_spin.setRange(0, 60)
        self.ramp_delay_spin.setValue(self.ctx.settings.default_step_delay_s)
        grid.addWidget(self.ramp_delay_spin, 2, 7)

        return box

    def _build_controls_box(self) -> QGroupBox:
        box = QGroupBox("Calibration Sequence Controls")
        row1 = QHBoxLayout()
        self.start_cal_btn = QPushButton("Start Calibration")
        self.start_cal_btn.clicked.connect(self._start_calibration)
        row1.addWidget(self.start_cal_btn)

        row1.addWidget(QLabel("Measured field (Oe):"))
        self.field_entry_spin = QDoubleSpinBox()
        self.field_entry_spin.setRange(-1e7, 1e7)
        self.field_entry_spin.setDecimals(4)
        row1.addWidget(self.field_entry_spin)

        self.confirm_btn = QPushButton("Confirm Field Value")
        self.confirm_btn.clicked.connect(self._confirm_field)
        self.confirm_btn.setEnabled(False)
        row1.addWidget(self.confirm_btn)

        self.repeat_btn = QPushButton("Repeat Current Point")
        self.repeat_btn.clicked.connect(lambda: self.controller and self.controller.repeat_current_point())
        self.repeat_btn.setEnabled(False)
        row1.addWidget(self.repeat_btn)

        self.previous_btn = QPushButton("Previous Point")
        self.previous_btn.clicked.connect(lambda: self.controller and self.controller.previous_point())
        self.previous_btn.setEnabled(False)
        row1.addWidget(self.previous_btn)

        row2 = QHBoxLayout()
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(lambda: self.controller and self.controller.request_pause())
        self.resume_btn = QPushButton("Resume")
        self.resume_btn.clicked.connect(lambda: self.controller and self.controller.request_resume())
        self.abort_btn = QPushButton("Abort")
        self.abort_btn.clicked.connect(self._abort)
        self.ramp_zero_btn = QPushButton("Ramp Current to Zero")
        self.ramp_zero_btn.clicked.connect(self._ramp_to_zero_manual)
        self.estop_btn = QPushButton("EMERGENCY STOP")
        self.estop_btn.setStyleSheet("background-color:#c62828; color:white; font-weight:bold;")
        self.estop_btn.clicked.connect(self._emergency_stop)
        for b in (self.pause_btn, self.resume_btn, self.abort_btn, self.ramp_zero_btn, self.estop_btn):
            row2.addWidget(b)

        v = QVBoxLayout(box)
        v.addLayout(row1)
        v.addLayout(row2)
        return box

    # ------------------------------------------------------------------
    def _browse_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load Calibration", "", "Calibration Files (*.csv *.json)")
        if path:
            self.load_path_edit.setText(path)

    def _load_calibration(self) -> None:
        path = self.load_path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "No File", "Choose a calibration file first.")
            return
        try:
            if path.lower().endswith(".json"):
                issues = self.ctx.calibration_manager.load_json(path)
            else:
                issues = self.ctx.calibration_manager.load_csv(path)
            self._refresh_table()
            self.issues_box.setPlainText("\n".join(issues) if issues else "No issues found.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Load Failed", str(exc))

    def _save_calibration(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Calibration", "calibration.csv", "CSV Files (*.csv)")
        if path:
            self.ctx.calibration_manager.save_csv(path)
            QMessageBox.information(self, "Saved", f"Calibration saved to {path}")

    # ------------------------------------------------------------------
    def _start_calibration(self) -> None:
        if not self.ctx.safety_manager.is_configured:
            QMessageBox.warning(self, "Set Maximum Current", "Set the maximum allowable current first.")
            return
        if self.ctx.power_supply is None or not self.ctx.power_supply.is_connected:
            QMessageBox.warning(self, "Not Connected", "Connect the power supply first.")
            return

        if self.mode_combo.currentText() == "Custom List":
            try:
                currents = [float(x) for x in self.custom_list_edit.text().split(",") if x.strip()]
            except ValueError:
                QMessageBox.warning(self, "Invalid List", "Custom list must be comma-separated numbers.")
                return
        else:
            start, stop, step = self.start_spin.value(), self.stop_spin.value(), self.step_spin.value()
            if step <= 0:
                QMessageBox.warning(self, "Invalid Step", "Step must be positive.")
                return
            n = int(round(abs(stop - start) / step)) + 1
            sign = 1.0 if stop >= start else -1.0
            currents = [start + sign * step * i for i in range(n)]
            currents[-1] = stop

        rows = self.ctx.safety_manager.validate_sequence(currents, context="calibration sequence")
        if not all(r.within_current_limit for r in rows):
            QMessageBox.critical(
                self, "Safety Violation",
                "One or more calibration currents exceed the maximum allowable "
                "current. Calibration will not start.",
            )
            return

        ramp_config = RampConfig(
            current_step_a=self.ramp_step_spin.value(),
            step_delay_s=self.ramp_delay_spin.value(),
            stabilization_time_s=self.stabilization_spin.value(),
        )
        self.controller = CalibrationController(
            self.ctx.power_supply, self.ctx.calibration_manager, ramp_config, logger=self.ctx.logger
        )
        self.controller.point_ready.connect(self._on_point_ready)
        self.controller.status_message.connect(self.status_label.setText)
        self.controller.error_occurred.connect(lambda m: QMessageBox.critical(self, "Calibration Error", m))
        self.controller.state_changed.connect(self._on_state_changed)
        self.controller.finished_ok.connect(self._on_finished)
        self.controller.configure(currents, self.direction_combo.currentText())
        self.ctx.safety_manager.acquire_lock("calibration_running")
        self.start_cal_btn.setEnabled(False)
        self.controller.start()

    def _on_point_ready(self, index: int, current: float) -> None:
        self.status_label.setText(
            f"Point {index + 1}: current {current:.6f} A applied and stabilized. "
            "Enter the measured magnetic field corresponding to the presently "
            "applied current, then click Confirm Field Value."
        )
        self.confirm_btn.setEnabled(True)
        self.repeat_btn.setEnabled(True)
        self.previous_btn.setEnabled(True)

    def _confirm_field(self) -> None:
        if self.controller is not None:
            self.controller.confirm_field(self.field_entry_spin.value())
            self._refresh_table()

    def _on_state_changed(self, state: str) -> None:
        self._refresh_table()

    def _on_finished(self, success: bool) -> None:
        self.ctx.safety_manager.release_lock("calibration_running")
        self.start_cal_btn.setEnabled(True)
        self.confirm_btn.setEnabled(False)
        self.repeat_btn.setEnabled(False)
        self.previous_btn.setEnabled(False)
        self._refresh_table()
        self.status_label.setText("Calibration completed." if success else "Calibration stopped/aborted.")

    def _abort(self) -> None:
        self._stop_voltage_monitor()
        if self.controller is not None:
            self.controller.request_abort()

    def _ramp_to_zero_manual(self) -> None:
        self._stop_voltage_monitor()
        if self.ctx.power_supply is None:
            return
        ramp_config = RampConfig(
            current_step_a=self.ramp_step_spin.value(), step_delay_s=self.ramp_delay_spin.value()
        )
        CurrentRamper(self.ctx.power_supply, ramp_config, logger=self.ctx.logger).ramp_to_zero(
            context="manual ramp to zero (calibration tab)"
        )

    def _emergency_stop(self) -> None:
        self._stop_voltage_monitor()
        self.ctx.safety_manager.trigger_emergency_stop()
        if self.controller is not None:
            self.controller.request_emergency_stop()

    # ------------------------------------------------------------------
    def _refresh_table(self) -> None:
        points = self.ctx.calibration_manager.points
        self.table.setRowCount(len(points))
        for row, p in enumerate(points):
            values = [
                str(p.index + 1), f"{p.commanded_current_a:.6f}",
                f"{p.actual_current_a:.6f}" if p.actual_current_a is not None else "-",
                f"{p.field_oe:.4f}", p.polarity, p.direction, p.timestamp,
            ]
            for col, val in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(val))

        self.plot_widget.clear()
        if points:
            currents = [p.commanded_current_a for p in points]
            fields = [p.field_oe for p in points]
            self.plot_widget.plot(currents, fields, pen=None, symbol="o", symbolSize=8)

        issues = self.ctx.calibration_manager.validate()
        self.issues_box.setPlainText("\n".join(issues) if issues else "No issues found.")
        cur_range = self.ctx.calibration_manager.current_range()
        field_range = self.ctx.calibration_manager.field_range()
        range_txt = []
        if cur_range:
            range_txt.append(f"Calibrated current range: {cur_range[0]:.4f} to {cur_range[1]:.4f} A")
        if field_range:
            range_txt.append(f"Calibrated field range: {field_range[0]:.4f} to {field_range[1]:.4f} Oe")
        self.range_label.setText("  |  ".join(range_txt))
