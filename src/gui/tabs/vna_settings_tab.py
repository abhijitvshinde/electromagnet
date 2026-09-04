"""Tab 5: VNA Settings."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QLabel,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from src.drivers.vna import VNASweepConfig
from src.gui.app_context import AppContext

_FREQ_UNITS = {"Hz": 1.0, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9, "THz": 1e12}


class _FreqInput:
    """A frequency value + unit dropdown (Hz/kHz/MHz/GHz/THz), so entering
    e.g. 10 GHz doesn't mean typing '10000000000' and risking a mistyped
    zero. Switching units re-converts the displayed value so the actual
    frequency it represents doesn't silently change underneath the user.
    """

    def __init__(self, default_hz: float, on_change=None) -> None:
        self.value_spin = QDoubleSpinBox()
        self.value_spin.setRange(0.000001, 1_000_000.0)
        self.value_spin.setDecimals(6)
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(list(_FREQ_UNITS.keys()))
        self.unit_combo.setCurrentText("GHz")
        self._last_unit = "GHz"
        self.value_spin.setValue(default_hz / _FREQ_UNITS[self._last_unit])
        self.unit_combo.currentTextChanged.connect(self._on_unit_changed)
        if on_change is not None:
            self.value_spin.valueChanged.connect(on_change)
            self.unit_combo.currentTextChanged.connect(on_change)

    def _on_unit_changed(self, new_unit: str) -> None:
        hz = self.value_spin.value() * _FREQ_UNITS[self._last_unit]
        self.value_spin.blockSignals(True)
        self.value_spin.setValue(hz / _FREQ_UNITS[new_unit])
        self.value_spin.blockSignals(False)
        self._last_unit = new_unit

    def hz(self) -> float:
        return self.value_spin.value() * _FREQ_UNITS[self.unit_combo.currentText()]


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

        grid.addWidget(QLabel("Start frequency:"), 0, 0)
        self.start_freq = _FreqInput(float(d.get("start_freq_hz", 1e9)), on_change=self._update_spacing)
        grid.addWidget(self.start_freq.value_spin, 0, 1)
        grid.addWidget(self.start_freq.unit_combo, 0, 2)

        grid.addWidget(QLabel("Stop frequency:"), 0, 3)
        self.stop_freq = _FreqInput(float(d.get("stop_freq_hz", 3e9)), on_change=self._update_spacing)
        grid.addWidget(self.stop_freq.value_spin, 0, 4)
        grid.addWidget(self.stop_freq.unit_combo, 0, 5)

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
        spacing = (self.stop_freq.hz() - self.start_freq.hz()) / max(1, n - 1)
        self.spacing_label.setText(f"Frequency spacing: {spacing / 1e3:.4f} kHz  |  IF bandwidth is a separate setting")

    def build_config(self) -> VNASweepConfig:
        return VNASweepConfig(
            start_freq_hz=self.start_freq.hz(),
            stop_freq_hz=self.stop_freq.hz(),
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
