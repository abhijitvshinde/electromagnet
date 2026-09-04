"""Tab 1: Safety.

Entering a maximum allowable current is mandatory before any other tab is
usable. The limit cannot be changed while the SafetyManager reports a
lock (output enabled, or calibration/measurement running). This tab also
collects a voltage figure (coil resistance + margin -> max current x
resistance x (1 + margin)) that serves TWO purposes:

1. Software-only monitoring ceiling: the app polls the real output
   voltage while current is applied and emergency-stops (ramp to zero,
   then disable output) if it's ever exceeded -- see
   src/safety/voltage_monitor.py.
2. The instrument's actual compliance-voltage setpoint (plain VOLT, sent
   via PowerSupplyController.set_voltage_limit): a CV/CC power supply's
   CURR command has no physical effect unless VOLT is set high enough
   for it to regulate on current, so this same generously-margined value
   is also pushed to the instrument so it behaves as a genuine current
   source with the operating voltage floating (per V = I * R_coil) below
   that ceiling, rather than needing manual front-panel setup.

Note this is deliberately NOT the instrument's own OVP protection
circuit (VOLT:PROT) -- that is never configured automatically; #1 above
is this app's substitute for it.

HISTORY: auto-pushing this value was briefly reverted after a report
that it was "setting voltage at 42V" -- that turned out to be a
misreading of the front panel (which shows the compliance CEILING in
some display states, not the live output), confirmed harmless via an
independent multimeter check of the real output voltage. Re-enabled.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from src.drivers.base_instrument import InstrumentCommunicationError
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

        layout.addWidget(self._build_voltage_box())
        layout.addStretch(1)

    def _build_voltage_box(self) -> QGroupBox:
        box = QGroupBox("Voltage Safety Monitoring && Compliance")
        info = QLabel(
            "This value is used two ways: (1) the app polls the real output voltage "
            "while current is applied and automatically triggers an emergency stop "
            "(ramp to zero, then disable output) if it's ever exceeded, instead of "
            "relying on the instrument's own OVP circuit; and (2) it is sent to the "
            "power supply as its compliance-voltage setpoint (VOLT) so it can "
            "actually deliver your intended currents and behaves as a current "
            "source with voltage floating below that ceiling. This is NOT the "
            "instrument's OVP protection circuit (VOLT:PROT), which is never "
            "configured automatically. Coil resistance/Margin are remembered "
            "across app restarts; Max Current and this threshold are not -- "
            "recalculate and re-set each session."
        )
        info.setWordWrap(True)
        grid = QGridLayout(box)
        grid.addWidget(info, 0, 0, 1, 4)

        grid.addWidget(QLabel("Coil resistance (Ω):"), 1, 0)
        self.coil_resistance_spin = QDoubleSpinBox()
        self.coil_resistance_spin.setRange(0.0, 100000.0)
        self.coil_resistance_spin.setDecimals(3)
        self.coil_resistance_spin.setValue(self.ctx.coil_resistance_ohms)
        grid.addWidget(self.coil_resistance_spin, 1, 1)

        grid.addWidget(QLabel("Margin (%):"), 1, 2)
        self.margin_spin = QDoubleSpinBox()
        self.margin_spin.setRange(0.0, 500.0)
        self.margin_spin.setDecimals(1)
        self.margin_spin.setValue(self.ctx.voltage_margin_percent)
        grid.addWidget(self.margin_spin, 1, 3)

        grid.addWidget(QLabel("Voltage monitoring threshold (V):"), 2, 0)
        self.voltage_threshold_spin = QDoubleSpinBox()
        self.voltage_threshold_spin.setRange(0.0, 1000.0)
        self.voltage_threshold_spin.setDecimals(3)
        grid.addWidget(self.voltage_threshold_spin, 2, 1)

        calc_btn = QPushButton("Calculate from Max Current")
        calc_btn.setToolTip(
            "Fills the field above with (max current) x (coil resistance) x (1 + "
            "margin) -- generous enough to cover your full current range."
        )
        calc_btn.clicked.connect(self._on_calculate_voltage_threshold)
        grid.addWidget(calc_btn, 2, 2)

        set_btn = QPushButton("Set Monitoring Threshold && Compliance Voltage")
        set_btn.setToolTip(
            "Stores this value as the software monitoring threshold AND sends it to "
            "the connected power supply as its compliance-voltage setpoint (VOLT) -- "
            "not its OVP protection circuit."
        )
        set_btn.clicked.connect(self._on_set_voltage_threshold)
        grid.addWidget(set_btn, 2, 3)

        return box

    def _on_calculate_voltage_threshold(self) -> None:
        if not self.ctx.safety_manager.is_configured:
            QMessageBox.warning(self, "Set Maximum Current", "Set the maximum allowable current first.")
            return
        resistance = self.coil_resistance_spin.value()
        if resistance <= 0:
            QMessageBox.warning(self, "Enter Coil Resistance", "Enter the coil's resistance (in Ω) first.")
            return
        max_current = self.ctx.safety_manager.max_current
        margin = self.margin_spin.value() / 100.0
        computed = max_current * resistance * (1.0 + margin)
        self.voltage_threshold_spin.setValue(computed)
        self.ctx.coil_resistance_ohms = resistance
        self.ctx.voltage_margin_percent = self.margin_spin.value()
        self.ctx.save_user_state()
        self.ctx.logger.info(
            f"Calculated voltage threshold/compliance value: {max_current:.4f} A x {resistance:.3f} "
            f"ohm x {1 + margin:.2f} margin = {computed:.3f} V (not yet sent anywhere -- "
            "click 'Set Monitoring Threshold & Compliance Voltage' to apply it)"
        )

    def _on_set_voltage_threshold(self) -> None:
        value = self.voltage_threshold_spin.value()
        if value <= 0:
            QMessageBox.warning(
                self, "Invalid Voltage Value",
                "This value is 0 (or less) -- almost always because Coil resistance "
                "is 0 or Max Current isn't set yet. Fix those, click 'Calculate from "
                "Max Current' again, and retry. Pushing 0V to the power supply as its "
                "compliance-voltage setpoint would prevent any current from actually "
                "flowing, even though the app would report success.",
            )
            return
        self.ctx.voltage_monitoring_threshold = value
        applied_to_instrument = False
        if self.ctx.power_supply is not None and self.ctx.power_supply.is_connected:
            self.ctx.power_supply.set_voltage_monitoring_threshold(value)
            # Also push this as the instrument's actual compliance-voltage
            # setpoint (plain VOLT) -- generously covering the full max-current
            # range via the margin above -- so the supply behaves as a genuine
            # current source with voltage floating up to this ceiling, instead
            # of needing manual front-panel setup. This is NOT the OVP
            # protection circuit (VOLT:PROT); that is still never touched
            # automatically. Unlike the connect-time reapplication, this is a
            # deliberate user action, so a failure here should surface loudly
            # rather than being swallowed as best-effort.
            try:
                self.ctx.power_supply.set_voltage_limit(value)
                applied_to_instrument = True
            except InstrumentCommunicationError as exc:
                QMessageBox.critical(self, "Could Not Set Compliance Voltage", str(exc))
                return
        QMessageBox.information(
            self, "Threshold Set",
            f"Software voltage monitoring threshold set to {value:.3f} V."
            + (
                f"\n\nThe same value was also sent to the power supply as its "
                f"compliance-voltage setpoint (VOLT), so it can act as a current "
                f"source across your full current range. This is separate from "
                f"the instrument's own OVP protection circuit, which is never "
                f"configured automatically."
                if applied_to_instrument else
                "\n\nNo power supply is connected, so nothing was sent to an "
                "instrument yet -- reconnect (or click this again once connected) "
                "to also apply it as the compliance-voltage setpoint."
            ),
        )

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
