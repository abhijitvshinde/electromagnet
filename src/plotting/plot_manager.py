"""Live S11/S21/S12/S22 MAGNITUDE plotting (pyqtgraph, fast incremental
updates) plus static figure rendering (matplotlib) for saved PNG/PDF
outputs and 2D color maps. Phase is deliberately not plotted live (it's
still saved as numeric data -- see src/data/data_manager.py).

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

_LEGEND_VISIBLE_ROWS = 10  # scroll area height reserved for this many rows


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

    def row_height_hint(self) -> int:
        """Height in px of one entry row, used to size the scroll area to
        ``_LEGEND_VISIBLE_ROWS`` regardless of the platform's font metrics."""
        probe = QLabel("Hg")
        return probe.sizeHint().height() + self._layout.spacing()


@dataclass
class _PlotSlot:
    """One live plot (S11/S21/S12/S22 magnitude): the composite widget
    added to the GUI layout (plot and legend side by side), the pyqtgraph
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
    # Sized to show _LEGEND_VISIBLE_ROWS entries before a vertical
    # scrollbar appears, instead of growing to match the plot's height
    # (which could show far more, or far fewer, than 10 depending on the
    # window size).
    scroll.setFixedHeight(legend.row_height_hint() * _LEGEND_VISIBLE_ROWS + 8)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(plot_widget, 5)
    layout.addWidget(scroll, 1)

    return _PlotSlot(widget=container, plot_widget=plot_widget, legend=legend)


class PlotManager:
    def __init__(self) -> None:
        self._slots: dict[str, _PlotSlot] = {
            "S11": _build_slot("S11 Magnitude (dB)", "S11 Magnitude", "dB"),
            "S21": _build_slot("S21 Magnitude (dB)", "S21 Magnitude", "dB"),
            "S12": _build_slot("S12 Magnitude (dB)", "S12 Magnitude", "dB"),
            "S22": _build_slot("S22 Magnitude (dB)", "S22 Magnitude", "dB"),
        }

        # Public names kept stable -- the GUI adds these QWidgets directly
        # to its layout (GraphicsLayoutWidget is itself a QWidget, so this
        # is a drop-in replacement for the plain PlotWidget used before).
        self.s11_plot_widget = self._slots["S11"].widget
        self.s21_plot_widget = self._slots["S21"].widget
        self.s12_plot_widget = self._slots["S12"].widget
        self.s22_plot_widget = self._slots["S22"].widget

        self.overlay_mode: bool = False
        self._trace_counter: int = 0

    # ------------------------------------------------------------------
    def clear(self) -> None:
        for slot in self._slots.values():
            slot.plot_widget.clear()
            slot.legend.clear()
            slot.curves.clear()
        self._trace_counter = 0

    def set_overlay_mode(self, enabled: bool) -> None:
        self.overlay_mode = enabled
        if not enabled:
            self.clear()

    def set_trace_visible(self, s_param: str, trace_id: int, visible: bool) -> None:
        slot = self._slots[s_param]
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

    def update(self, s_param: str, freqs: np.ndarray, mag_db: np.ndarray, field_oe: float, current_a: float) -> int:
        """Plot one trace of magnitude data for ``s_param`` ('S11', 'S21',
        'S12', or 'S22'). Returns a trace_id usable with set_trace_visible."""
        label = f"H={field_oe:.2f} Oe"
        trace_id = self._trace_counter
        self._trace_counter += 1
        color = _PALETTE[trace_id % len(_PALETTE)]
        self._plot_into(self._slots[s_param], trace_id, freqs, mag_db, label, color)
        return trace_id

    def autoscale(self) -> None:
        for slot in self._slots.values():
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
        points are overlaid. Every trace gets a listed entry -- the figure
        height grows with the trace count instead of capping the legend,
        so a saved graph never hides data.
        """
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        n_traces = len(series)
        fig_height = max(4.5, 1.5 + 0.25 * n_traces)

        fig, ax = plt.subplots(figsize=(8, fig_height))
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
    ) -> None:
        """Render a magnitude-vs-frequency-vs-field colormap and save it.

        Square figure/axes (``set_box_aspect(1)``) regardless of the data's
        physical units (GHz vs. Oe) -- this is purely a display choice, not
        a claim that one GHz should look like one Oe.
        """
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7, 7))
        mesh = ax.pcolormesh(fields, freqs / 1e9, matrix_db.T, shading="auto", cmap="viridis")
        ax.set_xlabel("Magnetic field (Oe)")
        ax.set_ylabel("Frequency (GHz)")
        ax.set_title(title)
        ax.set_box_aspect(1)
        fig.colorbar(mesh, ax=ax, label="Magnitude (dB)", fraction=0.046, pad=0.04)
        fig.tight_layout()
        if png_path:
            png_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(png_path, dpi=150)
        if pdf_path:
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(pdf_path)
        plt.close(fig)
