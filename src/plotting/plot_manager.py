"""Live S11/S21 plotting (pyqtgraph, fast incremental updates) plus static
figure rendering (matplotlib) for saved PNG/PDF outputs and 2D color maps.

Nothing in this module touches instrument or measurement state directly --
the MeasurementController pushes data to it via plain method calls, all
made from the GUI thread through queued Qt signal/slot connections so no
widget is ever touched from a worker thread.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

pg.setConfigOptions(antialias=True, background="w", foreground="k")

_PALETTE = [
    (31, 119, 180), (255, 127, 14), (44, 160, 44), (214, 39, 40),
    (148, 103, 189), (140, 86, 75), (227, 119, 194), (127, 127, 127),
    (188, 189, 34), (23, 190, 207),
]


class _LegendPanel(QWidget):
    """A small, fully Qt-native legend: one row per trace, a colored line
    swatch immediately beside its label.

    This exists instead of pyqtgraph's own ``LegendItem`` because that
    widget only lays out correctly when it floats as an overlay inside a
    ViewBox (the default ``addLegend()`` behavior) -- placed as a
    standalone item in a ``GraphicsLayout`` column instead (to get it
    genuinely outside the plotting area rather than overlapping the
    traces), each entry's color swatch rendered UNDER its label instead of
    beside it. A plain QVBoxLayout of QHBoxLayout rows has no such
    surprise: each row is guaranteed to keep its swatch and text aligned
    on the same line.
    """

    def __init__(self) -> None:
        super().__init__()
        self._rows: dict[int, QWidget] = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(2)
        self._layout.addStretch(1)

    def add_entry(self, trace_id: int, color: tuple[int, int, int], label: str) -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        swatch = QFrame()
        swatch.setFixedSize(18, 3)
        swatch.setStyleSheet(f"background-color: rgb{color}; border: none;")
        row_layout.addWidget(swatch, 0, Qt.AlignmentFlag.AlignVCenter)
        text = QLabel(label)
        row_layout.addWidget(text, 0, Qt.AlignmentFlag.AlignVCenter)
        row_layout.addStretch(1)
        self._rows[trace_id] = row
        self._layout.insertWidget(self._layout.count() - 1, row)  # before the trailing stretch

    def clear(self) -> None:
        for row in self._rows.values():
            self._layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()

    def set_visible(self, trace_id: int, visible: bool) -> None:
        row = self._rows.get(trace_id)
        if row is not None:
            row.setVisible(visible)


@dataclass
class _PlotSlot:
    """One live plot (S11/S21 magnitude or phase): the composite widget
    added to the GUI layout (plot + legend side by side), the pyqtgraph
    PlotWidget itself, and the legend panel."""

    widget: QWidget
    plot_widget: pg.PlotWidget
    legend: _LegendPanel
    curves: dict[int, pg.PlotDataItem] = field(default_factory=dict)


def _build_slot(title: str, ylabel: str, y_units: str) -> _PlotSlot:
    plot_widget = pg.PlotWidget()
    plot_widget.showGrid(x=True, y=True, alpha=0.3)
    plot_widget.setLabel("bottom", "Frequency", units="Hz")
    plot_widget.setLabel("left", ylabel, units=y_units)
    plot_widget.setTitle(title)
    plot_widget.setMouseEnabled(x=True, y=True)

    legend = _LegendPanel()
    scroll = QScrollArea()
    scroll.setWidget(legend)
    scroll.setWidgetResizable(True)
    scroll.setFixedWidth(150)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(plot_widget, 5)
    layout.addWidget(scroll, 1)

    return _PlotSlot(widget=container, plot_widget=plot_widget, legend=legend)


class PlotManager:
    def __init__(self) -> None:
        self._s11_mag = _build_slot("S11 Magnitude (dB)", "S11 Magnitude", "dB")
        self._s21_mag = _build_slot("S21 Magnitude (dB)", "S21 Magnitude", "dB")
        self._s11_phase = _build_slot("S11 Phase (deg)", "S11 Phase", "deg")
        self._s21_phase = _build_slot("S21 Phase (deg)", "S21 Phase", "deg")

        # Public names kept stable -- the GUI adds these QWidgets directly
        # to its layout (GraphicsLayoutWidget is itself a QWidget, so this
        # is a drop-in replacement for the plain PlotWidget used before).
        self.s11_plot_widget = self._s11_mag.widget
        self.s21_plot_widget = self._s21_mag.widget
        self.s11_phase_plot_widget = self._s11_phase.widget
        self.s21_phase_plot_widget = self._s21_phase.widget

        self.overlay_mode: bool = False
        self._trace_counter: int = 0

    # ------------------------------------------------------------------
    def clear(self) -> None:
        for slot in (self._s11_mag, self._s21_mag, self._s11_phase, self._s21_phase):
            slot.plot_widget.clear()
            slot.legend.clear()
            slot.curves.clear()
        self._trace_counter = 0

    def set_overlay_mode(self, enabled: bool) -> None:
        self.overlay_mode = enabled
        if not enabled:
            self.clear()

    def set_trace_visible(self, s_param: str, trace_id: int, visible: bool) -> None:
        slots = (self._s11_mag, self._s11_phase) if s_param == "S11" else (self._s21_mag, self._s21_phase)
        for slot in slots:
            curve = slot.curves.get(trace_id)
            if curve is not None:
                curve.setVisible(visible)
            slot.legend.set_visible(trace_id, visible)

    # ------------------------------------------------------------------
    def _plot_into(self, slot: _PlotSlot, trace_id: int, freqs, values, label: str, color) -> None:
        if not self.overlay_mode:
            slot.plot_widget.clear()
            slot.legend.clear()
            slot.curves.clear()
        curve = slot.plot_widget.plot(freqs, values, pen=pg.mkPen(color=color, width=2))
        slot.legend.add_entry(trace_id, color, label)
        slot.curves[trace_id] = curve

    def update_s11(self, freqs: np.ndarray, mag_db: np.ndarray, phase_deg: np.ndarray, field_oe: float, current_a: float) -> int:
        label = f"H={field_oe:.2f} Oe"
        trace_id = self._trace_counter
        self._trace_counter += 1
        color = _PALETTE[trace_id % len(_PALETTE)]
        self._plot_into(self._s11_mag, trace_id, freqs, mag_db, label, color)
        self._plot_into(self._s11_phase, trace_id, freqs, phase_deg, label, color)
        return trace_id

    def update_s21(self, freqs: np.ndarray, mag_db: np.ndarray, phase_deg: np.ndarray, field_oe: float, current_a: float) -> int:
        label = f"H={field_oe:.2f} Oe"
        trace_id = self._trace_counter
        self._trace_counter += 1
        color = _PALETTE[trace_id % len(_PALETTE)]
        self._plot_into(self._s21_mag, trace_id, freqs, mag_db, label, color)
        self._plot_into(self._s21_phase, trace_id, freqs, phase_deg, label, color)
        return trace_id

    def autoscale(self) -> None:
        for slot in (self._s11_mag, self._s21_mag, self._s11_phase, self._s21_phase):
            slot.plot_widget.autoRange()

    # ------------------------------------------------------------------
    @staticmethod
    def save_overlay_figure(
        series: list[tuple[str, np.ndarray, np.ndarray]],
        title: str,
        ylabel: str,
        png_path: Path | None = None,
        pdf_path: Path | None = None,
    ) -> None:
        """Render every ``(label, freqs_hz, values)`` trace in ``series``
        onto one static figure and save it.

        The legend is always placed outside the axes (to the right, via
        ``bbox_to_anchor``) rather than matplotlib's default in-plot
        placement, so it never overlaps the traces no matter how many
        points are overlaid.
        """
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 4.5))
        for label, freqs, values in series:
            ax.plot(np.asarray(freqs) / 1e9, values, label=label, linewidth=1.2)
        ax.set_xlabel("Frequency (GHz)")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize="small", borderaxespad=0.0)
        # Reserve the right ~18% of the figure for the legend so
        # tight_layout doesn't shrink it back under the axes.
        fig.tight_layout(rect=(0.0, 0.0, 0.82, 1.0))
        if png_path:
            png_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(png_path, dpi=150)
        if pdf_path:
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
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
