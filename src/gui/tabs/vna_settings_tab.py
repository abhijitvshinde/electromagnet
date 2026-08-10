"""Tab 5: VNA Settings."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QLabel,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from src.drivers.vna import VNASweepConfig
from src.gui.app_context import AppContext


class VNASettingsTab(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        box = QGroupBox("VNA Sweep Configuration")
        grid = QGridLayout(box)
        d = self.ctx.settings.vna_defaults

        grid.addWidget(QLabel("Start frequency (Hz):"), 0, 0)
        self.start_freq_spin = QDoubleSpinBox()
        self.start_freq_spin.setRange(1, 1e12)
        self.start_freq_spin.setDecimals(1)
        self.start_freq_spin.setValue(float(d.get("start_freq_hz", 1e9)))
        grid.addWidget(self.start_freq_spin, 0, 1)

        grid.addWidget(QLabel("Stop frequency (Hz):"), 0, 2)
        self.stop_freq_spin = QDoubleSpinBox()
        self.stop_freq_spin.setRange(1, 1e12)
        self.stop_freq_spin.setDecimals(1)
        self.stop_freq_spin.setValue(float(d.get("stop_freq_hz", 3e9)))
        grid.addWidget(self.stop_freq_spin, 0, 3)

        grid.addWidget(QLabel("Number of points:"), 1, 0)
        self.num_points_spin = QSpinBox()
        self.num_points_spin.setRange(2, 100001)
        self.num_points_spin.setValue(int(d.get("num_points", 401)))
        self.num_points_spin.valueChanged.connect(self._update_spacing)
        grid.addWidget(self.num_points_spin, 1, 1)

        self.spacing_label = QLabel()
        grid.addWidget(self.spacing_label, 1, 2, 1, 2)

        grid.addWidget(QLabel("Source power (dBm):"), 2, 0)
        self.power_spin = QDoubleSpinBox()
        self.power_spin.setRange(-60, 30)
        self.power_spin.setValue(float(d.get("source_power_dbm", -10.0)))
        grid.addWidget(self.power_spin, 2, 1)

        grid.addWidget(QLabel("IF bandwidth (Hz):"), 2, 2)
        self.ifbw_spin = QDoubleSpinBox()
        self.ifbw_spin.setRange(1, 1e7)
        self.ifbw_spin.setValue(float(d.get("if_bandwidth_hz", 1000.0)))
        grid.addWidget(self.ifbw_spin, 2, 3)

        grid.addWidget(QLabel("Sweep time (s, 0=auto):"), 3, 0)
        self.sweep_time_spin = QDoubleSpinBox()
        self.sweep_time_spin.setRange(0, 3600)
        self.sweep_time_spin.setDecimals(4)
        grid.addWidget(self.sweep_time_spin, 3, 1)

        self.averaging_check = QCheckBox("Averaging enabled")
        self.averaging_check.setChecked(bool(d.get("averaging_enabled", False)))
        grid.addWidget(self.averaging_check, 3, 2)

        grid.addWidget(QLabel("Number of averages:"), 3, 3)
        self.averages_spin = QSpinBox()
        self.averages_spin.setRange(1, 10000)
        self.averages_spin.setValue(int(d.get("averages", 1)))
        grid.addWidget(self.averages_spin, 3, 4)

        grid.addWidget(QLabel("Channel:"), 4, 0)
        self.channel_spin = QSpinBox()
        self.channel_spin.setRange(1, 32)
        self.channel_spin.setValue(int(d.get("channel", 1)))
        grid.addWidget(self.channel_spin, 4, 1)

        grid.addWidget(QLabel("Trigger mode:"), 4, 2)
        self.trigger_combo = QComboBox()
        self.trigger_combo.addItems(["SINGLE", "CONTINUOUS", "EXTERNAL"])
        grid.addWidget(self.trigger_combo, 4, 3)

        self.s11_check = QCheckBox("Measure S11")
        self.s11_check.setChecked(True)
        self.s21_check = QCheckBox("Measure S21")
        self.s21_check.setChecked(True)
        grid.addWidget(self.s11_check, 5, 0)
        grid.addWidget(self.s21_check, 5, 1)

        layout.addWidget(box)

        apply_btn = QPushButton("Apply Configuration to VNA")
        apply_btn.clicked.connect(self._apply)
        layout.addWidget(apply_btn)
        layout.addStretch(1)
        self._update_spacing()

    def _update_spacing(self) -> None:
        n = self.num_points_spin.value()
        spacing = (self.stop_freq_spin.value() - self.start_freq_spin.value()) / max(1, n - 1)
        self.spacing_label.setText(f"Frequency spacing: {spacing / 1e3:.4f} kHz  |  IF bandwidth is a separate setting")

    def build_config(self) -> VNASweepConfig:
        return VNASweepConfig(
            start_freq_hz=self.start_freq_spin.value(),
            stop_freq_hz=self.stop_freq_spin.value(),
            num_points=self.num_points_spin.value(),
            source_power_dbm=self.power_spin.value(),
            if_bandwidth_hz=self.ifbw_spin.value(),
            sweep_time_s=self.sweep_time_spin.value() or None,
            averaging_enabled=self.averaging_check.isChecked(),
            averages=self.averages_spin.value(),
            channel=self.channel_spin.value(),
            trigger_mode=self.trigger_combo.currentText(),
            measure_s11=self.s11_check.isChecked(),
            measure_s21=self.s21_check.isChecked(),
        )

    def _apply(self) -> None:
        config = self.build_config()
        self.ctx.vna_sweep_config = config
        if self.ctx.vna is not None and self.ctx.vna.is_connected:
            try:
                self.ctx.vna.configure(config)
                QMessageBox.information(self, "VNA Configured", "Configuration applied to the VNA.")
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Configuration Failed", str(exc))
        else:
            QMessageBox.information(
                self, "Saved", "Configuration saved. Connect the VNA to apply it."
            )
