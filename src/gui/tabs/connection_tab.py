"""Tab 2: Instrument Connection."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from src.config.app_config import power_supply_profiles, vna_profiles
from src.drivers.base_instrument import InstrumentCommunicationError, VisaTransport
from src.drivers.power_supply import PowerSupplyController
from src.drivers.simulation import SimulatedPowerSupplyTransport, SimulatedVNATransport
from src.drivers.vna import VNAController
from src.gui.app_context import AppContext

_STATUS_COLORS = {
    "Disconnected": "#888888",
    "Connecting": "#d2a300",
    "Connected": "#2e8b2e",
    "Busy": "#1e6fd9",
    "Error": "#c62828",
}


def _status_badge(text: str) -> str:
    color = _STATUS_COLORS.get(text, "#888888")
    return f"<span style='color:{color}; font-weight:bold;'>{text}</span>"


class ConnectionTab(QWidget):
    connections_changed = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._ps_profiles = power_supply_profiles()
        self._vna_profiles = vna_profiles()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.sim_checkbox = QCheckBox(
            "Simulation Mode (no physical GPIB hardware required)"
        )
        self.sim_checkbox.setChecked(self.ctx.simulation_mode)
        self.sim_checkbox.toggled.connect(self._on_sim_toggled)
        layout.addWidget(self.sim_checkbox)
        self._sim_banner = QLabel()
        self._sim_banner.setStyleSheet(
            "background-color:#fff3cd; color:#7a5b00; padding:6px; border:1px solid #e0c568;"
        )
        layout.addWidget(self._sim_banner)

        layout.addWidget(self._build_instrument_box(
            "Power Supply", is_power_supply=True,
            default_address=self.ctx.settings.power_supply_gpib_address,
        ))
        layout.addWidget(self._build_instrument_box(
            "Vector Network Analyzer", is_power_supply=False,
            default_address=self.ctx.settings.vna_gpib_address,
        ))
        layout.addStretch(1)
        self._update_sim_banner()

    def _build_instrument_box(self, title: str, is_power_supply: bool, default_address: str) -> QGroupBox:
        box = QGroupBox(title)
        grid = QGridLayout(box)

        grid.addWidget(QLabel("GPIB address:"), 0, 0)
        address_edit = QLineEdit(default_address)
        grid.addWidget(address_edit, 0, 1)

        grid.addWidget(QLabel("Timeout (ms):"), 0, 2)
        timeout_spin = QSpinBox()
        timeout_spin.setRange(100, 60000)
        timeout_spin.setValue(self.ctx.settings.gpib_timeout_ms)
        grid.addWidget(timeout_spin, 0, 3)

        grid.addWidget(QLabel("Command profile:"), 1, 0)
        profile_combo = QComboBox()
        profiles = self._ps_profiles if is_power_supply else self._vna_profiles
        profile_combo.addItems(list(profiles.keys()))
        grid.addWidget(profile_combo, 1, 1)

        status_label = QLabel(_status_badge("Disconnected"))
        grid.addWidget(status_label, 1, 2, 1, 2)

        connect_btn = QPushButton("Connect")
        disconnect_btn = QPushButton("Disconnect")
        test_btn = QPushButton("Test Communication")
        disconnect_btn.setEnabled(False)
        test_btn.setEnabled(False)
        btn_row = QHBoxLayout()
        btn_row.addWidget(connect_btn)
        btn_row.addWidget(disconnect_btn)
        btn_row.addWidget(test_btn)
        grid.addLayout(btn_row, 2, 0, 1, 4)

        idn_label = QLabel("IDN: -")
        idn_label.setWordWrap(True)
        grid.addWidget(idn_label, 3, 0, 1, 4)

        if is_power_supply:
            clear_protection_btn = QPushButton("Clear Protection Trip")
            clear_protection_btn.setEnabled(False)
            clear_protection_btn.setToolTip(
                "Some power supplies (e.g. the E3634A) latch the output off when an "
                "overvoltage/overcurrent protection circuit trips -- Output On alone will "
                "not restore it. Use this if the output stays off with no other explanation."
            )
            grid.addWidget(clear_protection_btn, 4, 0, 1, 4)

            def do_clear_protection() -> None:
                if self.ctx.power_supply is not None:
                    try:
                        self.ctx.power_supply.clear_protection_trips()
                        QMessageBox.information(
                            self, "Protection Cleared",
                            "Sent the clear command(s) for overvoltage/overcurrent protection "
                            "(if supported by this profile). Try enabling the output again.",
                        )
                    except InstrumentCommunicationError as exc:
                        QMessageBox.critical(self, "Clear Protection Failed", str(exc))

            clear_protection_btn.clicked.connect(do_clear_protection)
        else:
            clear_protection_btn = None

        def do_connect() -> None:
            profile = profiles[profile_combo.currentText()]
            try:
                if is_power_supply:
                    if self.ctx.simulation_mode:
                        transport = SimulatedPowerSupplyTransport(self.ctx.simulation_engine)
                    else:
                        transport = VisaTransport(
                            address_edit.text(), timeout_spin.value(),
                            profile.write_termination, profile.read_termination,
                        )
                    driver = PowerSupplyController(profile, transport, self.ctx.safety_manager, logger=self.ctx.logger)
                    idn = driver.open_connection()
                    self.ctx.power_supply = driver
                else:
                    if self.ctx.simulation_mode:
                        transport = SimulatedVNATransport(self.ctx.simulation_engine)
                    else:
                        transport = VisaTransport(
                            address_edit.text(), timeout_spin.value(),
                            profile.write_termination, profile.read_termination,
                        )
                    driver = VNAController(profile, transport, logger=self.ctx.logger)
                    idn = driver.open_connection()
                    self.ctx.vna = driver

                driver.status_changed.connect(lambda s: status_label.setText(_status_badge(s)))
                idn_label.setText(f"IDN: {idn}")
                status_label.setText(_status_badge("Connected"))
                connect_btn.setEnabled(False)
                disconnect_btn.setEnabled(True)
                test_btn.setEnabled(True)
                # Lock these: changing them while connected has NO effect on the
                # already-built driver (its profile/transport are fixed at connect
                # time), so leaving them editable invites exactly the confusing bug
                # where the dropdown shows one profile while a different one is
                # actually in use. Disconnect and reconnect to apply a change.
                address_edit.setEnabled(False)
                timeout_spin.setEnabled(False)
                profile_combo.setEnabled(False)
                if is_power_supply:
                    clear_protection_btn.setEnabled(True)
                    if self.ctx.safety_manager.is_configured:
                        # Best-effort: mirror the mandatory software limit onto the
                        # instrument's own hardware current limit, when supported.
                        driver.set_hardware_current_limit(self.ctx.safety_manager.max_current)
                    if self.ctx.voltage_monitoring_threshold is not None:
                        # Re-apply the Safety tab's software monitoring threshold to
                        # this newly-connected driver instance (never sent to the
                        # instrument -- see VoltageMonitor).
                        driver.set_voltage_monitoring_threshold(self.ctx.voltage_monitoring_threshold)
                        # Also (re)apply it as the instrument's actual
                        # compliance-voltage setpoint (plain VOLT) -- NOT the OVP
                        # protection circuit (VOLT:PROT), which this app still
                        # never touches automatically. This supply is CV/CC: a
                        # CURR command has no physical effect at all unless VOLT
                        # is set high enough for the supply to regulate on
                        # current -- so the power supply can act as a genuine
                        # current source (with the operating voltage floating
                        # below this ceiling per V = I*R_coil) instead of
                        # needing manual front-panel setup every time.
                        # CONFIRMED on real hardware: connecting a new GPIB
                        # session resets this instrument's VOLT setpoint to ~0V,
                        # so this must be reapplied on every connect, not just
                        # once. Skip (with a warning) rather than push a
                        # worthless 0V ceiling if the threshold hasn't actually
                        # been calculated yet (e.g. Coil resistance still 0).
                        # Best-effort otherwise: the connection itself should
                        # still succeed even if this particular write fails.
                        if self.ctx.voltage_monitoring_threshold > 0:
                            try:
                                driver.set_voltage_limit(self.ctx.voltage_monitoring_threshold)
                            except InstrumentCommunicationError as exc:
                                self.ctx.logger.warning(
                                    f"Could not apply compliance-voltage setpoint on connect: {exc}"
                                )
                        else:
                            self.ctx.logger.warning(
                                "Voltage monitoring threshold is 0 -- not pushing it as a "
                                "compliance-voltage setpoint. Check Coil resistance and Max "
                                "Current on the Safety tab, then use 'Set Monitoring "
                                "Threshold & Compliance Voltage' again."
                            )
                self.connections_changed.emit()
            except InstrumentCommunicationError as exc:
                QMessageBox.critical(self, "Connection Failed", str(exc))
                status_label.setText(_status_badge("Error"))

        def do_disconnect() -> None:
            driver = self.ctx.power_supply if is_power_supply else self.ctx.vna
            if driver is not None:
                driver.close_connection()
            if is_power_supply:
                self.ctx.power_supply = None
            else:
                self.ctx.vna = None
            status_label.setText(_status_badge("Disconnected"))
            idn_label.setText("IDN: -")
            connect_btn.setEnabled(True)
            disconnect_btn.setEnabled(False)
            test_btn.setEnabled(False)
            address_edit.setEnabled(True)
            timeout_spin.setEnabled(True)
            profile_combo.setEnabled(True)
            if is_power_supply:
                clear_protection_btn.setEnabled(False)
            self.connections_changed.emit()

        def do_test() -> None:
            driver = self.ctx.power_supply if is_power_supply else self.ctx.vna
            if driver is None:
                return
            ok = driver.test_communication()
            QMessageBox.information(
                self, "Test Communication",
                "Communication OK." if ok else "Communication FAILED. See event log.",
            )

        connect_btn.clicked.connect(do_connect)
        disconnect_btn.clicked.connect(do_disconnect)
        test_btn.clicked.connect(do_test)
        return box

    def _on_sim_toggled(self, checked: bool) -> None:
        self.ctx.simulation_mode = checked
        self._update_sim_banner()

    def _update_sim_banner(self) -> None:
        if self.ctx.simulation_mode:
            self._sim_banner.setText(
                "⚠ SIMULATION MODE ACTIVE — connecting to software-simulated "
                "instruments, not real hardware."
            )
            self._sim_banner.show()
        else:
            self._sim_banner.hide()
