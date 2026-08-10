"""Tab 8: Event Log."""
from __future__ import annotations

from PySide6.QtWidgets import QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from src.gui.app_context import AppContext

_COLORS = {
    "DEBUG": "#888888", "INFO": "#222222", "WARNING": "#b8860b",
    "ERROR": "#c62828", "CRITICAL": "#8b0000",
}


class LogTab(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        layout = QVBoxLayout(self)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)
        clear_btn = QPushButton("Clear Display (log file is preserved)")
        clear_btn.clicked.connect(self.text_edit.clear)
        layout.addWidget(clear_btn)

        self.ctx.logger.bridge.message_logged.connect(self._append)

    def _append(self, level: str, message: str) -> None:
        self.text_edit.appendPlainText(message)
