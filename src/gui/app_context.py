"""Shared application state, created once by MainWindow and handed to
every tab. Holds the safety/data/calibration/plot managers plus whichever
instrument drivers currently exist (they are recreated on every Connect).
"""
from __future__ import annotations

from pathlib import Path

from src.calibration.calibration_manager import CalibrationManager
from src.config.app_config import AppSettings
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

        self.logger.info("Application context created")
        if self.simulation_mode:
            self.logger.warning("SIMULATION MODE is active by default (no real hardware required)")
