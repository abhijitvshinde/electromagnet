"""Tab 6: Live Measurement -- the main measurement screen."""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from src.data.data_manager import MeasurementPointResult
from src.gui.app_context import AppContext
from src.measurement.measurement_controller import MeasurementController, MeasurementSummary
from src.measurement.ramping import RampConfig


class LiveMeasurementTab(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller: MeasurementController | None = None
        self._start_time: float | None = None
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._update_elapsed)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        status_box = QGroupBox("Live Status")
        grid = QGridLayout(status_box)
        self.ps_status_label = QLabel("Power Supply: Disconnected")
        self.vna_status_label = QLabel("VNA: Disconnected")
        self.max_current_label = QLabel("Max current: -")
        self.present_current_label = QLabel("Present current: -")
        self.present_field_label = QLabel("Present field: -")
        self.progress_bar = QProgressBar()
        self.elapsed_label = QLabel("Elapsed: 00:00:00")
        self.direction_label = QLabel("Direction: -")
        self.vna_sweep_label = QLabel("VNA sweep status: idle")
        self.output_path_label = QLabel("Output folder: -")
        self.warning_label = QLabel("")
        self.warning_label.setStyleSheet("color:#c62828; font-weight:bold;")
        self.warning_label.setWordWrap(True)

        widgets = [
            self.ps_status_label, self.vna_status_label, self.max_current_label,
            self.present_current_label, self.present_field_label, self.direction_label,
            self.vna_sweep_label, self.output_path_label,
        ]
        for i, w in enumerate(widgets):
            grid.addWidget(w, i // 2, i % 2)
        grid.addWidget(self.progress_bar, 4, 0, 1, 2)
        grid.addWidget(self.elapsed_label, 5, 0, 1, 2)
        grid.addWidget(self.warning_label, 6, 0, 1, 2)
        layout.addWidget(status_box)

        plots_row = QHBoxLayout()
        plots_row.addWidget(self.ctx.plot_manager.s11_plot_widget)
        plots_row.addWidget(self.ctx.plot_manager.s21_plot_widget)
        layout.addLayout(plots_row)

        plot_controls = QHBoxLayout()
        self.overlay_check = QCheckBox("Overlay traces (unchecked = latest trace only)")
        self.overlay_check.toggled.connect(self.ctx.plot_manager.set_overlay_mode)
        plot_controls.addWidget(self.overlay_check)
        clear_btn = QPushButton("Clear Plots")
        clear_btn.clicked.connect(self.ctx.plot_manager.clear)
        plot_controls.addWidget(clear_btn)
        autoscale_btn = QPushButton("Autoscale")
        autoscale_btn.clicked.connect(self.ctx.plot_manager.autoscale)
        plot_controls.addWidget(autoscale_btn)
        layout.addLayout(plot_controls)

        ramp_box = QGroupBox("Ramp && Stabilization (used for this measurement)")
        ramp_grid = QGridLayout(ramp_box)
        ramp_grid.addWidget(QLabel("Ramp step (A):"), 0, 0)
        self.ramp_step_spin = QDoubleSpinBox()
        self.ramp_step_spin.setRange(0.0001, 10000)
        self.ramp_step_spin.setDecimals(4)
        self.ramp_step_spin.setValue(self.ctx.settings.default_current_step_a)
        ramp_grid.addWidget(self.ramp_step_spin, 0, 1)
        ramp_grid.addWidget(QLabel("Ramp delay (s):"), 0, 2)
        self.ramp_delay_spin = QDoubleSpinBox()
        self.ramp_delay_spin.setRange(0, 60)
        self.ramp_delay_spin.setValue(self.ctx.settings.default_step_delay_s)
        ramp_grid.addWidget(self.ramp_delay_spin, 0, 3)
        ramp_grid.addWidget(QLabel("Stabilization (s):"), 0, 4)
        self.stabilization_spin = QDoubleSpinBox()
        self.stabilization_spin.setRange(0, 3600)
        self.stabilization_spin.setValue(self.ctx.settings.default_stabilization_time_s)
        ramp_grid.addWidget(self.stabilization_spin, 0, 5)
        layout.addWidget(ramp_box)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start Measurement")
        self.start_btn.clicked.connect(self._start_measurement)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(lambda: self.controller and self.controller.request_pause())
        self.resume_btn = QPushButton("Resume")
        self.resume_btn.clicked.connect(lambda: self.controller and self.controller.request_resume())
        self.abort_btn = QPushButton("Abort")
        self.abort_btn.clicked.connect(lambda: self.controller and self.controller.request_abort())
        self.ramp_zero_btn = QPushButton("Ramp to Zero")
        self.ramp_zero_btn.clicked.connect(self._manual_ramp_to_zero)
        self.estop_btn = QPushButton("EMERGENCY STOP")
        self.estop_btn.setStyleSheet("background-color:#c62828; color:white; font-weight:bold; font-size:14px;")
        self.estop_btn.clicked.connect(self._emergency_stop)
        for b in (self.start_btn, self.pause_btn, self.resume_btn, self.abort_btn,
                  self.ramp_zero_btn, self.estop_btn):
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        self.refresh_static()

    # ------------------------------------------------------------------
    def refresh_static(self) -> None:
        sm = self.ctx.safety_manager
        self.max_current_label.setText(
            f"Max current: ±{sm.max_current:.4f} A" if sm.is_configured else "Max current: NOT SET"
        )
        self.ps_status_label.setText(
            f"Power Supply: {self.ctx.power_supply.status.value}" if self.ctx.power_supply else "Power Supply: Disconnected"
        )
        self.vna_status_label.setText(
            f"VNA: {self.ctx.vna.status.value}" if self.ctx.vna else "VNA: Disconnected"
        )
        self.output_path_label.setText(
            f"Output folder: {self.ctx.data_manager.experiment_dir}" if self.ctx.data_manager.experiment_dir else "Output folder: (create an experiment on the Data tab)"
        )

    # ------------------------------------------------------------------
    def _start_measurement(self) -> None:
        self.refresh_static()
        ctx = self.ctx
        problems = []
        if not ctx.safety_manager.is_configured:
            problems.append("Maximum current is not set.")
        if ctx.power_supply is None or not ctx.power_supply.is_connected:
            problems.append("Power supply is not connected.")
        if ctx.vna is None or not ctx.vna.is_connected:
            problems.append("VNA is not connected.")
        if not ctx.calibration_manager.is_valid():
            problems.append("Calibration is missing or invalid.")
        if not ctx.sequence_valid or not ctx.sweep_sequence:
            problems.append("Field sweep sequence has not been built/validated on the Sweep tab.")
        if ctx.data_manager.experiment_dir is None:
            problems.append("No experiment folder created (see Data tab).")
        if ctx.vna_sweep_config is None:
            problems.append("VNA has not been configured (see VNA Settings tab).")

        if problems:
            QMessageBox.critical(self, "Cannot Start Measurement", "\n".join(f"- {p}" for p in problems))
            return

        summary_text = (
            f"{len(ctx.sweep_sequence)} field point(s) will be measured.\n"
            f"Output folder: {ctx.data_manager.experiment_dir}\n\nProceed?"
        )
        if QMessageBox.question(self, "Confirm Experiment", summary_text) != QMessageBox.Yes:
            return

        ramp_config = RampConfig(
            current_step_a=self.ramp_step_spin.value(),
            step_delay_s=self.ramp_delay_spin.value(),
            stabilization_time_s=self.stabilization_spin.value(),
        )
        self.controller = MeasurementController(
            ctx.power_supply, ctx.vna, ctx.safety_manager, ctx.data_manager, ramp_config,
            measure_s11=ctx.vna_sweep_config.measure_s11, measure_s21=ctx.vna_sweep_config.measure_s21,
            logger=ctx.logger,
        )
        self.controller.configure(ctx.sweep_sequence)
        self.controller.state_changed.connect(self._on_state_changed)
        self.controller.progress_changed.connect(self._on_progress)
        self.controller.point_started.connect(self._on_point_started)
        self.controller.point_completed.connect(self._on_point_completed)
        self.controller.error_occurred.connect(self._on_error)
        self.controller.sequence_finished.connect(self._on_finished)

        self.progress_bar.setMaximum(len(ctx.sweep_sequence))
        self.progress_bar.setValue(0)
        self._start_time = time.monotonic()
        self._timer.start()
        self.start_btn.setEnabled(False)
        self.controller.start()

    def _on_state_changed(self, state: str) -> None:
        self.vna_sweep_label.setText(f"VNA sweep status: {state}")

    def _on_progress(self, current: int, total: int) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    def _on_point_started(self, index: int, field_oe: float, current_a: float) -> None:
        self.present_field_label.setText(f"Present field: {field_oe:.4f} Oe (requested)")
        self.present_current_label.setText(f"Present current: {current_a:.6f} A (target)")
        row = self.ctx.sweep_sequence[index]
        self.direction_label.setText(f"Direction: {row.direction}")

    def _on_point_completed(self, result: MeasurementPointResult) -> None:
        if result.s11 is not None:
            self.ctx.plot_manager.update_s11(
                result.s11.frequencies_hz, result.s11.magnitude_db, result.requested_field_oe, result.current_a
            )
        if result.s21 is not None:
            self.ctx.plot_manager.update_s21(
                result.s21.frequencies_hz, result.s21.magnitude_db, result.requested_field_oe, result.current_a
            )
        if result.actual_current_a is not None:
            self.present_current_label.setText(
                f"Present current: {result.current_a:.6f} A (actual: {result.actual_current_a:.6f} A)"
            )

    def _on_error(self, message: str) -> None:
        self.warning_label.setText(message)
        QMessageBox.critical(self, "Measurement Error", message)

    def _on_finished(self, summary: MeasurementSummary) -> None:
        self._timer.stop()
        self.start_btn.setEnabled(True)
        self.refresh_static()
        QMessageBox.information(
            self, "Measurement Finished",
            f"{summary.message}\nPoints completed: {summary.points_completed}/{summary.total_points}",
        )

    def _update_elapsed(self) -> None:
        if self._start_time is None:
            return
        elapsed = int(time.monotonic() - self._start_time)
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        self.elapsed_label.setText(f"Elapsed: {h:02d}:{m:02d}:{s:02d}")

    def _manual_ramp_to_zero(self) -> None:
        if self.ctx.power_supply is None:
            return
        from src.measurement.ramping import CurrentRamper

        ramp_config = RampConfig(
            current_step_a=self.ramp_step_spin.value(), step_delay_s=self.ramp_delay_spin.value()
        )
        CurrentRamper(self.ctx.power_supply, ramp_config, logger=self.ctx.logger).ramp_to_zero(
            context="manual ramp to zero (live measurement tab)"
        )
        self.present_current_label.setText("Present current: 0.000000 A")

    def _emergency_stop(self) -> None:
        self.ctx.safety_manager.trigger_emergency_stop()
        if self.controller is not None:
            self.controller.request_emergency_stop()
        self.warning_label.setText("EMERGENCY STOP triggered.")
