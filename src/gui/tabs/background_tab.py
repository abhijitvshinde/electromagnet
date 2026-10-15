"""Tab: Background Comparison -- S11/S21/S12/S22 magnitude, with and
without subtracting the experiment's 0A background/reference measurement
(see LiveMeasurementTab._measure_background).

Purely a data-display tab: it only reads whatever DataManager already has
in memory (point_summaries / background_summary) and re-plots it. It never
talks to the power supply or VNA, and never triggers a measurement itself.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from src.gui.app_context import AppContext
from src.plotting.plot_manager import PlotManager


class BackgroundComparisonTab(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        # A separate PlotManager instance from ctx.plot_manager (which the
        # Live Measurement tab owns) -- its 4 S11/S21/S12/S22 widgets just
        # need to live in this tab's own layout and be re-populated from
        # whatever data exists whenever refresh() runs, not track a
        # measurement in progress.
        self._plots = PlotManager()
        self._plots.set_overlay_mode(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        self.subtract_check = QCheckBox("Subtract background (0A measurement)")
        self.subtract_check.toggled.connect(self.refresh)
        controls.addWidget(self.subtract_check)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        plots_grid = QGridLayout()
        plots_grid.addWidget(self._plots.s11_plot_widget, 0, 0)
        plots_grid.addWidget(self._plots.s21_plot_widget, 0, 1)
        plots_grid.addWidget(self._plots.s12_plot_widget, 1, 0)
        plots_grid.addWidget(self._plots.s22_plot_widget, 1, 1)
        layout.addLayout(plots_grid, 1)

        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Re-render all 4 plots from whatever point_summaries /
        background_summary currently exist. Safe to call any time (tab
        switch, after a point is saved, or the checkbox being toggled) --
        it only reads already-saved in-memory data."""
        points = self.ctx.data_manager.point_summaries
        background = self.ctx.data_manager.background_summary
        subtract = self.subtract_check.isChecked()

        if not points:
            self.status_label.setText("No field-sweep data measured yet for this experiment.")
        elif subtract and background is None:
            self.status_label.setText(
                "No background (0A) measurement saved for this experiment -- showing raw "
                "data instead. Use the 'Measure Background' button on the Live Measurement "
                "tab to capture one, then re-check this box."
            )
        elif subtract:
            self.status_label.setText("Showing each trace minus the background (0A) measurement.")
        else:
            self.status_label.setText("Showing raw (uncorrected) data.")

        self._plots.clear()
        for s_param in ("S11", "S21", "S12", "S22"):
            key = f"{s_param.lower()}_magnitude_db"
            bg_db = background.get(key) if background is not None else None
            for point in points:
                mag_db = point.get(key)
                if mag_db is None:
                    continue
                freqs = point["freqs"]
                if subtract and bg_db is not None and len(bg_db) == len(mag_db):
                    values = np.asarray(mag_db) - np.asarray(bg_db)
                else:
                    values = mag_db
                # field_oe/current_a aren't in point_summaries (only the
                # label is) -- the label itself already encodes the field
                # value, and PlotManager.update only uses field_oe to build
                # its own label, so recovering it isn't needed here.
                self._plots.update(s_param, freqs, values, field_oe=_field_from_label(point["label"]), current_a=0.0)
        self._plots.autoscale()


def _field_from_label(label: str) -> float:
    """Recover the numeric H value from a point_summaries label like
    'H=1234.00 Oe', since PlotManager.update rebuilds its own label from
    field_oe rather than taking one directly."""
    try:
        return float(label.split("=", 1)[1].split()[0])
    except (IndexError, ValueError):
        return 0.0
