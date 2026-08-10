"""Live S11/S21 plotting (pyqtgraph, fast incremental updates) plus static
figure rendering (matplotlib) for saved PNG/PDF outputs and 2D color maps.

Nothing in this module touches instrument or measurement state directly --
the MeasurementController pushes data to it via plain method calls, all
made from the GUI thread through queued Qt signal/slot connections so no
widget is ever touched from a worker thread.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg

pg.setConfigOptions(antialias=True, background="w", foreground="k")

_PALETTE = [
    (31, 119, 180), (255, 127, 14), (44, 160, 44), (214, 39, 40),
    (148, 103, 189), (140, 86, 75), (227, 119, 194), (127, 127, 127),
    (188, 189, 34), (23, 190, 207),
]


class PlotManager:
    def __init__(self) -> None:
        self.s11_plot_widget = pg.PlotWidget()
        self.s21_plot_widget = pg.PlotWidget()
        for w, label in ((self.s11_plot_widget, "S11"), (self.s21_plot_widget, "S21")):
            w.showGrid(x=True, y=True, alpha=0.3)
            w.setLabel("bottom", "Frequency", units="Hz")
            w.setLabel("left", f"{label} Magnitude", units="dB")
            w.addLegend(offset=(10, 10))
            w.setMouseEnabled(x=True, y=True)

        self._s11_curves: dict[int, pg.PlotDataItem] = {}
        self._s21_curves: dict[int, pg.PlotDataItem] = {}
        self.overlay_mode: bool = False
        self._trace_counter: int = 0

    # ------------------------------------------------------------------
    def clear(self) -> None:
        self.s11_plot_widget.clear()
        self.s21_plot_widget.clear()
        self._s11_curves.clear()
        self._s21_curves.clear()
        self._trace_counter = 0

    def set_overlay_mode(self, enabled: bool) -> None:
        self.overlay_mode = enabled
        if not enabled:
            self.clear()

    def set_trace_visible(self, s_param: str, trace_id: int, visible: bool) -> None:
        curves = self._s11_curves if s_param == "S11" else self._s21_curves
        curve = curves.get(trace_id)
        if curve is not None:
            curve.setVisible(visible)

    # ------------------------------------------------------------------
    def _add_trace(self, widget: pg.PlotWidget, curves: dict, freqs, mag_db, label: str) -> int:
        if not self.overlay_mode:
            widget.clear()
            curves.clear()
        trace_id = self._trace_counter
        self._trace_counter += 1
        color = _PALETTE[trace_id % len(_PALETTE)]
        curve = widget.plot(freqs, mag_db, pen=pg.mkPen(color=color, width=2), name=label)
        curves[trace_id] = curve
        return trace_id

    def update_s11(self, freqs: np.ndarray, mag_db: np.ndarray, field_oe: float, current_a: float) -> int:
        label = f"H={field_oe:.2f} Oe"
        trace_id = self._add_trace(self.s11_plot_widget, self._s11_curves, freqs, mag_db, label)
        self.s11_plot_widget.setTitle(f"S11  |  H = {field_oe:.2f} Oe,  I = {current_a:.4f} A")
        return trace_id

    def update_s21(self, freqs: np.ndarray, mag_db: np.ndarray, field_oe: float, current_a: float) -> int:
        label = f"H={field_oe:.2f} Oe"
        trace_id = self._add_trace(self.s21_plot_widget, self._s21_curves, freqs, mag_db, label)
        self.s21_plot_widget.setTitle(f"S21  |  H = {field_oe:.2f} Oe,  I = {current_a:.4f} A")
        return trace_id

    def autoscale(self) -> None:
        self.s11_plot_widget.autoRange()
        self.s21_plot_widget.autoRange()

    # ------------------------------------------------------------------
    def save_png(self, which: str, path: Path) -> None:
        from pyqtgraph.exporters import ImageExporter

        widget = self.s11_plot_widget if which == "S11" else self.s21_plot_widget
        exporter = ImageExporter(widget.plotItem)
        exporter.export(str(path))

    @staticmethod
    def save_static_figure(
        freqs: np.ndarray,
        mag_db: np.ndarray,
        title: str,
        ylabel: str,
        png_path: Path | None = None,
        pdf_path: Path | None = None,
    ) -> None:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7, 4.5))
        ax.plot(np.asarray(freqs) / 1e9, mag_db)
        ax.set_xlabel("Frequency (GHz)")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        if png_path:
            fig.savefig(png_path, dpi=150)
        if pdf_path:
            fig.savefig(pdf_path)
        plt.close(fig)

    @staticmethod
    def render_colormap_figure(
        fields: np.ndarray,
        freqs: np.ndarray,
        matrix_db: np.ndarray,
        title: str,
        png_path: Path | None = None,
        pdf_path: Path | None = None,
    ):
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7.5, 5))
        mesh = ax.pcolormesh(freqs / 1e9, fields, matrix_db, shading="auto", cmap="viridis")
        ax.set_xlabel("Frequency (GHz)")
        ax.set_ylabel("Magnetic field (Oe)")
        ax.set_title(title)
        fig.colorbar(mesh, ax=ax, label="Magnitude (dB)")
        fig.tight_layout()
        if png_path:
            fig.savefig(png_path, dpi=150)
        if pdf_path:
            fig.savefig(pdf_path)
        return fig
