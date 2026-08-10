"""Application and experiment event logging.

Logs everything the spec requires (startup, connections, calibration,
every current command, every field point, VNA config, measurement
lifecycle, pauses/aborts/emergency stops, communication errors, file
saves, shutdown) to both a rotating application log file and, once an
experiment folder exists, a per-experiment log file. Also exposes a Qt
signal so the GUI's Event Log tab can display messages live without
polling.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, Signal


class _QtLogBridge(QObject):
    message_logged = Signal(str, str)  # (level, message)


class _QtSignalHandler(logging.Handler):
    def __init__(self, bridge: _QtLogBridge) -> None:
        super().__init__()
        self._bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._bridge.message_logged.emit(record.levelname, msg)
        except Exception:
            pass


class ExperimentLogger:
    """Wraps a standard :mod:`logging.Logger` plus a Qt signal bridge."""

    def __init__(self, app_log_dir: Path, name: str = "electromagnet_vna") -> None:
        app_log_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(name)
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False
        self.bridge = _QtLogBridge()

        if not self._logger.handlers:
            fmt = logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

            file_handler = RotatingFileHandler(
                app_log_dir / "application.log",
                maxBytes=5_000_000,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(fmt)
            self._logger.addHandler(file_handler)

            console_handler = logging.StreamHandler()
            console_handler.setFormatter(fmt)
            self._logger.addHandler(console_handler)

            qt_handler = _QtSignalHandler(self.bridge)
            qt_handler.setFormatter(fmt)
            self._logger.addHandler(qt_handler)

        self._experiment_handler: RotatingFileHandler | None = None

    # ------------------------------------------------------------------
    def attach_experiment_log(self, experiment_dir: Path) -> None:
        """Add a second log file scoped to one experiment folder."""
        self.detach_experiment_log()
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler = RotatingFileHandler(
            Path(experiment_dir) / "event_log.log",
            maxBytes=5_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(fmt)
        self._logger.addHandler(handler)
        self._experiment_handler = handler

    def detach_experiment_log(self) -> None:
        if self._experiment_handler is not None:
            self._logger.removeHandler(self._experiment_handler)
            self._experiment_handler.close()
            self._experiment_handler = None

    # ------------------------------------------------------------------
    def debug(self, msg: str) -> None:
        self._logger.debug(msg)

    def info(self, msg: str) -> None:
        self._logger.info(msg)

    def warning(self, msg: str) -> None:
        self._logger.warning(msg)

    def error(self, msg: str) -> None:
        self._logger.error(msg)

    def critical(self, msg: str) -> None:
        self._logger.critical(msg)

    @property
    def raw_logger(self) -> logging.Logger:
        return self._logger
