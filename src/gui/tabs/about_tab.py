"""Tab 9: About."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from src.gui.app_context import AppContext


class AboutTab(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addStretch(1)

        label = QLabel(
            "<div style='text-align:center;'>"
            "<h1>Electromagnet &amp; VNA Control</h1>"
            f"<p>Equipment: {self.ctx.settings.electromagnet_equipment_number}</p>"
            "<p>Automated magnetic-field sweeps with synchronized S-parameter "
            "(S11/S21/S12/S22) measurement, current-to-field calibration, live "
            "plotting, and full data logging.</p>"
            "<br>"
            "<p>Developed for the <b>WiSERL Lab</b> of <b>Dr. Binbin Yang</b></p>"
            "<p>by <b>Abhijit Shinde</b>, with help from <b>Shantu Ghose</b></p>"
            "<br>"
            "<p>Department of Electrical and Computer Engineering</p>"
            "<p>North Carolina A&amp;T State University</p>"
            "<p>Greensboro, NC, USA</p>"
            "</div>"
        )
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)

        layout.addStretch(2)
