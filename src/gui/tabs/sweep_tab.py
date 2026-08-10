"""Tab 4: Magnetic-Field Sweep configuration and pre-flight validation.

Builds the complete field->current sequence and validates every point
against the calibration range and the maximum-current limit. The
Live Measurement tab's Start button stays disabled until
``ctx.sequence_valid`` is True.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from src.gui.app_context import AppContext
from src.measurement.sweep import build_validation_table, generate_field_values, summarize_sequence


class SweepTab(QWidget):
    sequence_ready = Signal(bool)

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.sequence = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        box = QGroupBox("Sweep Configuration")
        grid = QGridLayout(box)

        grid.addWidget(QLabel("Sweep mode:"), 0, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["forward", "reverse", "forward_reverse", "custom"])
        grid.addWidget(self.mode_combo, 0, 1)

        grid.addWidget(QLabel("Start field (Oe):"), 0, 2)
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(-1e7, 1e7)
        self.start_spin.setDecimals(3)
        grid.addWidget(self.start_spin, 0, 3)

        grid.addWidget(QLabel("Stop field (Oe):"), 0, 4)
        self.stop_spin = QDoubleSpinBox()
        self.stop_spin.setRange(-1e7, 1e7)
        self.stop_spin.setDecimals(3)
        self.stop_spin.setValue(100.0)
        grid.addWidget(self.stop_spin, 0, 5)

        grid.addWidget(QLabel("Step (Oe):"), 0, 6)
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.001, 1e7)
        self.step_spin.setValue(10.0)
        grid.addWidget(self.step_spin, 0, 7)

        grid.addWidget(QLabel("Custom list (comma-separated Oe):"), 1, 0, 1, 2)
        self.custom_list_edit = QLineEdit()
        grid.addWidget(self.custom_list_edit, 1, 2, 1, 6)

        grid.addWidget(QLabel("Repeated sweeps:"), 2, 0)
        self.repeats_spin = QSpinBox()
        self.repeats_spin.setRange(1, 1000)
        grid.addWidget(self.repeats_spin, 2, 1)

        grid.addWidget(QLabel("Measurements per field (averaged):"), 2, 2)
        self.avg_count_spin = QSpinBox()
        self.avg_count_spin.setRange(1, 100)
        grid.addWidget(self.avg_count_spin, 2, 3)

        grid.addWidget(QLabel("Calibration direction:"), 2, 4)
        self.calib_dir_combo = QComboBox()
        self.calib_dir_combo.addItems(["auto", "increasing", "decreasing", "average", "all"])
        grid.addWidget(self.calib_dir_combo, 2, 5)

        grid.addWidget(QLabel("Interpolation:"), 2, 6)
        self.interp_combo = QComboBox()
        self.interp_combo.addItems(["linear", "cubic"])
        grid.addWidget(self.interp_combo, 2, 7)

        layout.addWidget(box)

        build_btn = QPushButton("Build && Validate Sequence")
        build_btn.clicked.connect(self._build_sequence)
        layout.addWidget(build_btn)

        self.summary_label = QLabel("No sequence built yet.")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["#", "Field (Oe)", "Current (A)", "Direction", "In Calib. Range", "Status"]
        )
        layout.addWidget(self.table)

    def _build_sequence(self) -> None:
        if not self.ctx.safety_manager.is_configured:
            QMessageBox.warning(self, "Set Maximum Current", "Set the maximum allowable current first.")
            return
        if not self.ctx.calibration_manager.points:
            QMessageBox.warning(self, "No Calibration", "Load or create a calibration first.")
            return

        mode = self.mode_combo.currentText()
        try:
            if mode == "custom":
                custom_values = [float(x) for x in self.custom_list_edit.text().split(",") if x.strip()]
                pairs = generate_field_values(0, 0, 1, mode="custom", custom_values=custom_values,
                                               repeats=self.repeats_spin.value())
            else:
                pairs = generate_field_values(
                    self.start_spin.value(), self.stop_spin.value(), self.step_spin.value(),
                    mode=mode, repeats=self.repeats_spin.value(),
                )
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Sweep", str(exc))
            return

        rows = build_validation_table(
            pairs, self.ctx.calibration_manager, self.ctx.safety_manager,
            calibration_direction_mode=self.calib_dir_combo.currentText(),
            interpolation_method=self.interp_combo.currentText(),
        )
        self.sequence = rows
        self.ctx.sweep_sequence = rows
        summary = summarize_sequence(rows)

        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            values = [
                str(i + 1), f"{r.field_oe:.4f}",
                f"{r.current_a:.6f}" if r.current_a is not None else "-",
                r.direction, "Yes" if r.within_calibration_range else "No", r.status,
            ]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if not r.is_valid:
                    item.setBackground(Qt_red())
                self.table.setItem(i, col, item)

        self.summary_label.setText(
            f"Total points: {summary.total_points}  |  "
            f"Max +I: {summary.max_positive_current_a:.4f} A  |  "
            f"Max -I: {summary.max_negative_current_a:.4f} A  |  "
            f"Max |I|: {summary.max_abs_current_a:.4f} A  |  "
            f"{'ALL VALID' if summary.all_valid else 'INVALID -- fix before starting'}"
        )
        self.ctx.sequence_valid = summary.all_valid
        self.sequence_ready.emit(summary.all_valid)


def Qt_red():
    from PySide6.QtGui import QColor
    return QColor(255, 205, 205)
