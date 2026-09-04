"""Shared application state, created once by MainWindow and handed to
every tab. Holds the safety/data/calibration/plot managers plus whichever
instrument drivers currently exist (they are recreated on every Connect).
"""
from __future__ import annotations

from pathlib import Path

from src.calibration.calibration_manager import CalibrationManager
from src.config.app_config import AppSettings, UserState
from src.data.data_manager import DataManager
from src.drivers.power_supply import PowerSupplyController
from src.drivers.simulation import SimulationEngine
from src.drivers.vna import VNAController
from src.logging_.experiment_logger import ExperimentLogger
from src.plotting.plot_manager import PlotManager
from src.safety.safety_manager import SafetyManager


class AppContext:
    def __init__(self) -> None:
        self.settings = AppSettings.load()
        self.logger = ExperimentLogger(Path("./logs"))
        self.safety_manager = SafetyManager(logger=self.logger)
        self.calibration_manager = CalibrationManager(self.safety_manager, logger=self.logger)
        self.data_manager = DataManager(Path(self.settings.data_output_root), logger=self.logger)
        self.plot_manager = PlotManager()
        self.simulation_engine = SimulationEngine()
        self.simulation_mode: bool = self.settings.simulation_mode_default

        self.power_supply: PowerSupplyController | None = None
        self.vna: VNAController | None = None

        self.sweep_sequence: list = []
        self.sequence_valid: bool = False
        self.vna_sweep_config = None

        # Voltage safety monitoring (set on the Safety tab). Persists across
        # connect/disconnect cycles within this process and is (re)applied
        # to whichever PowerSupplyController instance is currently
        # connected -- both as the software-only monitoring ceiling (see
        # VoltageMonitor) AND, deliberately, as the instrument's real
        # compliance-voltage setpoint (plain VOLT, never the OVP circuit)
        # so it can actually deliver the requested currents.
        self.voltage_monitoring_threshold: float | None = None

        # Coil resistance / margin are physical/preference values that
        # don't change between sessions, unlike the mandatory max-current
        # limit (deliberately re-confirmed every session) -- loaded from
        # state/user_state.json so an app restart doesn't silently wipe
        # them back to 0 and, in turn, cause a 0V compliance-voltage push.
        self._user_state = UserState.load()
        self.coil_resistance_ohms: float = self._user_state.coil_resistance_ohms
        self.voltage_margin_percent: float = self._user_state.voltage_margin_percent

        self.logger.info("Application context created")
        if self.simulation_mode:
            self.logger.warning("SIMULATION MODE is active by default (no real hardware required)")

    def save_user_state(self) -> None:
        UserState(
            coil_resistance_ohms=self.coil_resistance_ohms,
            voltage_margin_percent=self.voltage_margin_percent,
        ).save()
