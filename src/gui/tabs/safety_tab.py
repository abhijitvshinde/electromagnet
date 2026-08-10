"""Tab 1: Safety and Maximum Current.

Entering a maximum allowable current is mandatory before any other tab is
usable. The limit cannot be changed while the SafetyManager reports a
lock (output enabled, or calibration/measurement running).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from src.gui.app_context import AppContext
from src.safety.safety_manager import SafetyViolationError


class SafetyTab(QWidget):
    max_current_confirmed = Signal(float)

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._build_ui()
        self.ctx.safety_manager.lock_state_changed.connect(self._refresh)
        self.ctx.safety_manager.max_current_changed.connect(self._refresh)
        self.ctx.safety_manager.emergency_stop_changed.connect(self._refresh)
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        warn = QLabel(
            "<b>Mandatory safety limit.</b> You must enter and confirm the maximum "
            "allowable electromagnet current before connecting instruments, "
            "calibrating, or running a measurement. The application enforces "
            "|commanded current| ≤ maximum current on every current command, "
            "with no override."
        )
        warn.setWordWrap(True)
        layout.addWidget(warn)

        box = QGroupBox("Maximum Allowable Current")
        form = QHBoxLayout(box)
        form.addWidget(QLabel("Maximum current (A):"))
        self.max_current_spin = QDoubleSpinBox()
        self.max_current_spin.setRange(0.001, 10000.0)
        self.max_current_spin.setDecimals(4)
        self.max_current_spin.setSingleStep(0.1)
        self.max_current_spin.setValue(1.0)
        form.addWidget(self.max_current_spin)

        self.confirm_button = QPushButton("Set / Confirm Maximum Current")
        self.confirm_button.clicked.connect(self._on_confirm)
        form.addWidget(self.confirm_button)
        layout.addWidget(box)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        note = QLabel(
            "To change this value later, stop any active process, ramp the "
            "current to zero, and disable the power-supply output first."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

    def _on_confirm(self) -> None:
        value = self.max_current_spin.value()
        try:
            self.ctx.safety_manager.set_max_current(value)
            if self.ctx.power_supply is not None and self.ctx.power_supply.is_connected:
                # Best-effort: mirror the mandatory software limit onto the
                # instrument's own hardware current limit, when supported.
                self.ctx.power_supply.set_hardware_current_limit(value)
            self.max_current_confirmed.emit(value)
            QMessageBox.information(
                self, "Maximum Current Set",
                f"Maximum allowable current set to ±{value:.4f} A.",
            )
        except SafetyViolationError as exc:
            QMessageBox.critical(self, "Cannot Change Maximum Current", str(exc))

    def _refresh(self, *_args) -> None:
        sm = self.ctx.safety_manager
        locked = sm.is_locked
        self.max_current_spin.setEnabled(not locked)
        self.confirm_button.setEnabled(not locked)

        lines = []
        if sm.is_configured:
            lines.append(f"<b>Current limit:</b> ±{sm.max_current:.4f} A")
        else:
            lines.append("<b>Current limit:</b> NOT SET (mandatory)")
        if locked:
            lines.append(f"<b>Locked</b> (cannot change limit): {', '.join(sm.lock_reasons)}")
        if sm.emergency_stop_active:
            lines.append("<b style='color:red'>EMERGENCY STOP ACTIVE</b>")
        self.status_label.setText("<br>".join(lines))
