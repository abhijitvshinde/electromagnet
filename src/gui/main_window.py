"""Main application window: ties the eight tabs together and enforces the
mandatory safe-shutdown sequence when the application is closed while a
process is active or the power-supply output is enabled.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QMessageBox, QTabWidget

from src.gui.app_context import AppContext
from src.gui.tabs.calibration_tab import CalibrationTab
from src.gui.tabs.connection_tab import ConnectionTab
from src.gui.tabs.data_tab import DataTab
from src.gui.tabs.live_measurement_tab import LiveMeasurementTab
from src.gui.tabs.log_tab import LogTab
from src.gui.tabs.safety_tab import SafetyTab
from src.gui.tabs.sweep_tab import SweepTab
from src.gui.tabs.vna_settings_tab import VNASettingsTab
from src.measurement.ramping import CurrentRamper, RampConfig


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.ctx = AppContext()
        self.setWindowTitle(
            f"Electromagnet & VNA Control -- Equipment {self.ctx.settings.electromagnet_equipment_number}"
        )
        self.resize(1500, 950)

        self.tabs = QTabWidget()
        self.safety_tab = SafetyTab(self.ctx)
        self.connection_tab = ConnectionTab(self.ctx)
        self.calibration_tab = CalibrationTab(self.ctx)
        self.sweep_tab = SweepTab(self.ctx)
        self.vna_settings_tab = VNASettingsTab(self.ctx)
        self.live_tab = LiveMeasurementTab(self.ctx)
        self.data_tab = DataTab(self.ctx)
        self.log_tab = LogTab(self.ctx)

        self.tabs.addTab(self.safety_tab, "1. Safety && Max Current")
        self.tabs.addTab(self.connection_tab, "2. Instrument Connection")
        self.tabs.addTab(self.calibration_tab, "3. Calibration")
        self.tabs.addTab(self.sweep_tab, "4. Field Sweep")
        self.tabs.addTab(self.vna_settings_tab, "5. VNA Settings")
        self.tabs.addTab(self.live_tab, "6. Live Measurement")
        self.tabs.addTab(self.data_tab, "7. Data && Experiment")
        self.tabs.addTab(self.log_tab, "8. Event Log")
        self.setCentralWidget(self.tabs)

        # Every tab except Safety and the Event Log requires the mandatory
        # maximum-current limit to be configured first.
        for i in range(self.tabs.count()):
            if i not in (0, 7):
                self.tabs.setTabEnabled(i, False)
        self.ctx.safety_manager.max_current_changed.connect(self._on_max_current_set)

        self.connection_tab.connections_changed.connect(self.live_tab.refresh_static)

        self.ctx.logger.info("Main window initialized")

    def _on_max_current_set(self, value: float) -> None:
        for i in range(self.tabs.count()):
            self.tabs.setTabEnabled(i, True)
        self.live_tab.refresh_static()

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        ctx = self.ctx
        active = ctx.safety_manager.is_locked or (
            ctx.power_supply is not None and ctx.power_supply.output_enabled
        )
        if active:
            reply = QMessageBox.warning(
                self, "Active Process",
                "A calibration or measurement is running, or the power-supply "
                "output is enabled. Closing now will stop the process, ramp "
                "the current safely to zero, disable the output, and save all "
                "collected data. Continue?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return

        for tab in (self.calibration_tab, self.live_tab):
            controller = getattr(tab, "controller", None)
            if controller is not None and controller.isRunning():
                controller.request_abort()
                controller.wait(10000)

        ctx.data_manager.finalize()

        if ctx.power_supply is not None and ctx.power_supply.is_connected:
            try:
                CurrentRamper(ctx.power_supply, RampConfig(), logger=ctx.logger).ramp_to_zero(
                    context="application shutdown"
                )
                ctx.power_supply.disable_output()
            except Exception as exc:  # noqa: BLE001
                ctx.logger.critical(
                    f"Could not confirm safe shutdown state (current/output): {exc}. "
                    "Verify the physical instrument state manually."
                )
            ctx.power_supply.close_connection()

        if ctx.vna is not None and ctx.vna.is_connected:
            ctx.vna.close_connection()

        ctx.logger.info("Application closed: shutdown sequence completed")
        event.accept()
