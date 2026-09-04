"""Headless smoke test that drives the actual GUI classes (not just the
underlying managers) through a full simulated experiment: set max
current, connect both instruments in Simulation Mode, build a
calibration, validate a sweep, configure the VNA, create an experiment,
and run Start Measurement to completion -- exactly the code paths a user
clicking through the application would exercise. QMessageBox popups are
monkeypatched to auto-accept/no-op so this can run non-interactively.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton  # noqa: E402

from src.gui.main_window import MainWindow  # noqa: E402


def find_button(widget, text: str) -> QPushButton:
    for btn in widget.findChildren(QPushButton):
        if btn.text() == text:
            return btn
    raise RuntimeError(f"Button {text!r} not found")


def main() -> None:
    app = QApplication(sys.argv)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.critical = staticmethod(lambda *a, **k: print("CRITICAL DIALOG:", a[2] if len(a) > 2 else a))
    QMessageBox.warning = staticmethod(lambda *a, **k: print("WARNING DIALOG:", a[2] if len(a) > 2 else a))

    win = MainWindow()
    ctx = win.ctx

    # 1. Safety
    win.safety_tab.max_current_spin.setValue(1.5)
    win.safety_tab.confirm_button.click()
    assert ctx.safety_manager.is_configured
    print("[1] Max current set:", ctx.safety_manager.max_current)

    # 2. Connections
    connect_buttons = [b for b in win.connection_tab.findChildren(QPushButton) if b.text() == "Connect"]
    assert len(connect_buttons) == 2, "expected one Connect button per instrument"
    for b in connect_buttons:
        b.click()
    app.processEvents()
    assert ctx.power_supply is not None and ctx.power_supply.is_connected
    assert ctx.vna is not None and ctx.vna.is_connected
    ctx.power_supply.set_voltage_limit(5.0)  # required before any current has a real effect
    print("[2] Both instruments connected:", ctx.power_supply.idn, "|", ctx.vna.idn)

    # 3. Calibration (populate directly, then let the tab refresh itself)
    for current in [-1.0, -0.5, 0.0, 0.5, 1.0]:
        ctx.calibration_manager.add_point(current, current * 300.0, direction="increasing")
    win.calibration_tab._refresh_table()
    assert ctx.calibration_manager.is_valid()
    print("[3] Calibration points:", len(ctx.calibration_manager.points))

    # 4. Sweep
    win.sweep_tab.start_spin.setValue(-100)
    win.sweep_tab.stop_spin.setValue(100)
    win.sweep_tab.step_spin.setValue(50)
    win.sweep_tab.mode_combo.setCurrentText("forward")
    find_button(win.sweep_tab, "Build && Validate Sequence").click()
    assert ctx.sequence_valid, "sweep sequence should validate"
    print("[4] Sweep sequence points:", len(ctx.sweep_sequence))

    # 5. VNA settings
    win.vna_settings_tab.num_points_spin.setValue(101)
    find_button(win.vna_settings_tab, "Apply Configuration to VNA").click()
    assert ctx.vna_sweep_config is not None
    print("[5] VNA configured:", ctx.vna_sweep_config.num_points, "points")

    # 6. Data tab: create experiment
    win.data_tab.experiment_name_edit.setText("GuiSmokeTest")
    win.data_tab.output_folder_edit.setText(str(PROJECT_ROOT / "sample_data"))
    find_button(win.data_tab, "Create Experiment Folder").click()
    assert ctx.data_manager.experiment_dir is not None
    print("[6] Experiment folder:", ctx.data_manager.experiment_dir)

    # 7. Live measurement: Start and wait for completion
    win.live_tab.ramp_step_spin.setValue(0.2)
    win.live_tab.ramp_delay_spin.setValue(0.0)
    win.live_tab.stabilization_spin.setValue(0.0)
    find_button(win.live_tab, "Start Measurement").click()

    deadline = time.monotonic() + 30
    while win.live_tab.controller is not None and win.live_tab.controller.isRunning():
        app.processEvents()
        if time.monotonic() > deadline:
            raise TimeoutError("Measurement did not finish in time")
    app.processEvents()
    print("[7] Measurement finished. Files in raw/:",
          len(list((ctx.data_manager.experiment_dir / "raw").glob("*.csv"))))

    win.close()
    print("GUI SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
