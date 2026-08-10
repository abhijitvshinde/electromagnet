"""Runs a full simulated experiment end-to-end and writes sample output
data and plots into ``sample_data/``. This exercises the exact same code
path the GUI uses (SafetyManager -> CalibrationManager -> sweep
validation -> MeasurementController -> DataManager) and is used both as a
smoke test and to produce the sample deliverables requested in the spec.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.calibration.calibration_manager import CalibrationManager  # noqa: E402
from src.config.app_config import default_power_supply_profile, default_vna_profile  # noqa: E402
from src.data.data_manager import DataManager  # noqa: E402
from src.drivers.power_supply import PowerSupplyController  # noqa: E402
from src.drivers.simulation import SimulatedPowerSupplyTransport, SimulatedVNATransport, SimulationEngine  # noqa: E402
from src.drivers.vna import VNAController, VNASweepConfig  # noqa: E402
from src.logging_.experiment_logger import ExperimentLogger  # noqa: E402
from src.measurement.measurement_controller import MeasurementController  # noqa: E402
from src.measurement.ramping import RampConfig  # noqa: E402
from src.measurement.sweep import build_validation_table, generate_field_values, summarize_sequence  # noqa: E402
from src.plotting.plot_manager import PlotManager  # noqa: E402
from src.safety.safety_manager import SafetyManager  # noqa: E402


def main() -> None:
    app = QApplication(sys.argv)

    sample_root = PROJECT_ROOT / "sample_data"
    logger = ExperimentLogger(sample_root / "logs")

    safety = SafetyManager(logger=logger)
    safety.set_max_current(2.0)

    engine = SimulationEngine(comm_delay_s=0.0)
    ps_transport = SimulatedPowerSupplyTransport(engine)
    vna_transport = SimulatedVNATransport(engine)

    power_supply = PowerSupplyController(default_power_supply_profile(), ps_transport, safety, logger=logger)
    power_supply.open_connection()
    vna = VNAController(default_vna_profile(), vna_transport, logger=logger)
    vna.open_connection()

    calibration = CalibrationManager(safety, logger=logger)
    for current in [-1.0, -0.6, -0.2, 0.0, 0.2, 0.6, 1.0]:
        calibration.add_point(current, current * 300.0, direction="increasing")
    for current in [1.0, 0.6, 0.2, 0.0, -0.2, -0.6, -1.0]:
        calibration.add_point(current, current * 300.0 + 5.0, direction="decreasing")
    print("Calibration issues:", calibration.validate())

    vna_config = VNASweepConfig(
        start_freq_hz=1.0e9, stop_freq_hz=3.0e9, num_points=201,
        source_power_dbm=-10.0, if_bandwidth_hz=1000.0, sweep_time_s=None,
        averaging_enabled=False, averages=1, channel=1, trigger_mode="SINGLE",
    )
    vna.configure(vna_config)

    pairs = generate_field_values(-250, 250, 25, mode="forward_reverse")
    rows = build_validation_table(pairs, calibration, safety, calibration_direction_mode="auto")
    summary = summarize_sequence(rows)
    print(f"Sequence: {summary.total_points} points, all_valid={summary.all_valid}, "
          f"max|I|={summary.max_abs_current_a:.4f} A")
    if not summary.all_valid:
        raise SystemExit("Sequence validation failed -- aborting sample data generation")

    data_manager = DataManager(sample_root, logger=logger)
    experiment_dir = data_manager.create_experiment(
        experiment_name="FMR_Sample_Sweep",
        sample_name="YP180829-188-2_test_sample",
        sample_description="Simulated ferromagnetic-resonance style S11/S21 sweep for sample output.",
        operator_name="Simulation",
        notes="Generated automatically by scripts/generate_sample_data.py",
    )
    data_manager.save_max_current(safety.max_current)
    data_manager.save_instrument_info(power_supply.identify(), vna.identify())
    data_manager.save_vna_settings(vna_config.__dict__)
    data_manager.save_sweep_settings({"mode": "forward_reverse", "start_oe": -250, "stop_oe": 250, "step_oe": 25})
    calibration.save_csv(experiment_dir / "calibration" / "calibration.csv")

    ramp_config = RampConfig(current_step_a=0.05, step_delay_s=0.0, stabilization_time_s=0.0)
    controller = MeasurementController(
        power_supply, vna, safety, data_manager, ramp_config,
        measure_s11=True, measure_s21=True, logger=logger,
    )
    controller.configure(rows)

    plot_manager = PlotManager()
    plot_manager.set_overlay_mode(True)
    saved_static = {"S11": False, "S21": False}

    def on_point_completed(result):
        if result.s11 is not None:
            plot_manager.update_s11(result.s11.frequencies_hz, result.s11.magnitude_db,
                                     result.requested_field_oe, result.current_a)
            if not saved_static["S11"]:
                PlotManager.save_static_figure(
                    result.s11.frequencies_hz, result.s11.magnitude_db,
                    f"S11 at H={result.requested_field_oe:.1f} Oe", "S11 Magnitude (dB)",
                    png_path=experiment_dir / "plots" / "s11_example_trace.png",
                    pdf_path=experiment_dir / "plots" / "s11_example_trace.pdf",
                )
                saved_static["S11"] = True
        if result.s21 is not None:
            plot_manager.update_s21(result.s21.frequencies_hz, result.s21.magnitude_db,
                                     result.requested_field_oe, result.current_a)
            if not saved_static["S21"]:
                PlotManager.save_static_figure(
                    result.s21.frequencies_hz, result.s21.magnitude_db,
                    f"S21 at H={result.requested_field_oe:.1f} Oe", "S21 Magnitude (dB)",
                    png_path=experiment_dir / "plots" / "s21_example_trace.png",
                    pdf_path=experiment_dir / "plots" / "s21_example_trace.pdf",
                )
                saved_static["S21"] = True

    controller.point_completed.connect(on_point_completed)
    controller.error_occurred.connect(lambda m: print("ERROR:", m))
    controller.sequence_finished.connect(lambda s: print("Finished:", s.message, s.points_completed, "/", s.total_points))

    controller.run()  # run synchronously (direct call, not .start()) for a simple one-shot script

    for which in ("S11", "S21"):
        result = data_manager.build_colormap(which)
        if result is not None:
            fields, freqs, matrix = result
            PlotManager.render_colormap_figure(
                fields, freqs, matrix, f"{which} Magnitude vs. Frequency and Field",
                png_path=experiment_dir / "plots" / f"{which.lower()}_colormap.png",
                pdf_path=experiment_dir / "plots" / f"{which.lower()}_colormap.pdf",
            )

    power_supply.close_connection()
    vna.close_connection()
    print(f"Sample experiment written to: {experiment_dir}")


if __name__ == "__main__":
    main()
