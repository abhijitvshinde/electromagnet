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
from src.gui.app_context import AppContext
from src.measurement.ramping import RampConfig


class CalibrationTab(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller: CalibrationController | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(self._build_load_box())
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
        if self.controller is not None:
            self.controller.request_abort()

    def _ramp_to_zero_manual(self) -> None:
        if self.ctx.power_supply is None:
            return
        from src.measurement.ramping import CurrentRamper

        ramp_config = RampConfig(
            current_step_a=self.ramp_step_spin.value(), step_delay_s=self.ramp_delay_spin.value()
        )
        CurrentRamper(self.ctx.power_supply, ramp_config, logger=self.ctx.logger).ramp_to_zero(
            context="manual ramp to zero (calibration tab)"
        )

    def _emergency_stop(self) -> None:
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
