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

        voltage_limit_spin = None
        voltage_limit_btn = None
        if is_power_supply:
            grid.addWidget(QLabel("Voltage limit / compliance (V):"), 4, 0)
            voltage_limit_spin = QDoubleSpinBox()
            voltage_limit_spin.setRange(0.0, 1000.0)
            voltage_limit_spin.setDecimals(3)
            grid.addWidget(voltage_limit_spin, 4, 1)
            voltage_limit_btn = QPushButton("Set Voltage Limit")
            voltage_limit_btn.setEnabled(False)
            voltage_limit_btn.setToolTip(
                "For a CV supply with a current setpoint (e.g. E3634A), the voltage "
                "limit must be set high enough that the current setpoint is actually "
                "reachable given the electromagnet coil's resistance (V >= I_max * R_coil)."
            )
            grid.addWidget(voltage_limit_btn, 4, 2, 1, 2)

            def do_set_voltage_limit() -> None:
                if self.ctx.power_supply is not None:
                    try:
                        self.ctx.power_supply.set_voltage_limit(voltage_limit_spin.value())
                    except InstrumentCommunicationError as exc:
                        QMessageBox.critical(self, "Voltage Limit Failed", str(exc))

            voltage_limit_btn.clicked.connect(do_set_voltage_limit)

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
                if is_power_supply:
                    voltage_limit_btn.setEnabled(True)
                    if self.ctx.safety_manager.is_configured:
                        # Best-effort: mirror the mandatory software limit onto the
                        # instrument's own hardware current limit, when supported.
                        driver.set_hardware_current_limit(self.ctx.safety_manager.max_current)
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
            if is_power_supply and voltage_limit_btn is not None:
                voltage_limit_btn.setEnabled(False)
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
