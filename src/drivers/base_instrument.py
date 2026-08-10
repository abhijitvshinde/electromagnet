"""Transport-agnostic instrument driver base.

A driver (``PowerSupplyController``, ``VNAController``) talks to a
:class:`Transport`, never directly to PyVISA. Swapping
:class:`VisaTransport` for :class:`SimulatedTransport` (see
``simulation.py``) lets the exact same driver and controller code run
against real GPIB hardware or a fully software simulation, which is what
Simulation Mode is built on.
"""
from __future__ import annotations

import abc
import time
from enum import Enum

from PySide6.QtCore import QObject, Signal

from src.config.app_config import InstrumentProfile


class InstrumentStatus(Enum):
    DISCONNECTED = "Disconnected"
    CONNECTING = "Connecting"
    CONNECTED = "Connected"
    BUSY = "Busy"
    ERROR = "Error"


class InstrumentCommunicationError(Exception):
    """Raised for any GPIB/VISA failure: timeout, disconnection, bad response."""


class Transport(abc.ABC):
    """Abstract communication channel used by an instrument driver."""

    @abc.abstractmethod
    def open(self) -> None: ...

    @abc.abstractmethod
    def close(self) -> None: ...

    @abc.abstractmethod
    def write(self, command: str) -> None: ...

    @abc.abstractmethod
    def query(self, command: str) -> str: ...

    @property
    @abc.abstractmethod
    def is_open(self) -> bool: ...


class VisaTransport(Transport):
    """Real GPIB transport built on PyVISA. No SCPI knowledge lives here."""

    def __init__(
        self,
        resource_address: str,
        timeout_ms: int,
        write_termination: str = "\n",
        read_termination: str = "\n",
    ) -> None:
        self.resource_address = resource_address
        self.timeout_ms = timeout_ms
        self.write_termination = write_termination
        self.read_termination = read_termination
        self._resource_manager = None
        self._resource = None

    @property
    def is_open(self) -> bool:
        return self._resource is not None

    def open(self) -> None:
        try:
            import pyvisa  # imported lazily so simulation mode needs no VISA backend installed

            if self._resource_manager is None:
                self._resource_manager = pyvisa.ResourceManager()
            self._resource = self._resource_manager.open_resource(self.resource_address)
            self._resource.timeout = self.timeout_ms
            self._resource.write_termination = self.write_termination
            self._resource.read_termination = self.read_termination
        except Exception as exc:  # pyvisa raises many different error types
            self._resource = None
            raise InstrumentCommunicationError(
                f"Failed to open {self.resource_address}: {exc}"
            ) from exc

    def close(self) -> None:
        if self._resource is not None:
            try:
                self._resource.close()
            except Exception:
                pass
        self._resource = None

    def write(self, command: str) -> None:
        if self._resource is None:
            raise InstrumentCommunicationError("Transport is not open")
        try:
            self._resource.write(command)
        except Exception as exc:
            raise InstrumentCommunicationError(f"Write failed ({command!r}): {exc}") from exc

    def query(self, command: str) -> str:
        if self._resource is None:
            raise InstrumentCommunicationError("Transport is not open")
        try:
            return self._resource.query(command)
        except Exception as exc:
            raise InstrumentCommunicationError(f"Query failed ({command!r}): {exc}") from exc


class BaseInstrumentDriver(QObject):
    """Shared connect/disconnect/status-tracking logic for all drivers."""

    status_changed = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, profile: InstrumentProfile, transport: Transport, logger=None) -> None:
        super().__init__()
        self.profile = profile
        self.transport = transport
        self._logger = logger
        self._status = InstrumentStatus.DISCONNECTED
        self._idn: str | None = None

    @property
    def status(self) -> InstrumentStatus:
        return self._status

    @property
    def is_connected(self) -> bool:
        return self._status in (InstrumentStatus.CONNECTED, InstrumentStatus.BUSY)

    @property
    def idn(self) -> str | None:
        return self._idn

    def _set_status(self, status: InstrumentStatus) -> None:
        self._status = status
        self.status_changed.emit(status.value)

    def _log(self, message: str, level: str = "info") -> None:
        if self._logger is not None:
            getattr(self._logger, level, self._logger.info)(message)

    # ------------------------------------------------------------------
    def open_connection(self) -> str:
        self._set_status(InstrumentStatus.CONNECTING)
        try:
            self.transport.open()
            self._idn = self.identify()
            self._set_status(InstrumentStatus.CONNECTED)
            self._log(f"Connected to {self.profile.name}: {self._idn}")
            return self._idn
        except InstrumentCommunicationError as exc:
            self._set_status(InstrumentStatus.ERROR)
            self._log(f"Connection failed: {exc}", level="error")
            self.error_occurred.emit(str(exc))
            raise

    def close_connection(self) -> None:
        try:
            self.transport.close()
        finally:
            self._idn = None
            self._set_status(InstrumentStatus.DISCONNECTED)
            self._log(f"Disconnected {self.profile.name}")

    def identify(self) -> str:
        return self._query_raw(self.profile.command("identify")).strip()

    def test_communication(self) -> bool:
        try:
            idn = self.identify()
            self._log(f"Test communication OK: {idn}")
            return True
        except InstrumentCommunicationError as exc:
            self._log(f"Test communication failed: {exc}", level="error")
            return False

    # ------------------------------------------------------------------
    def _write_raw(self, command: str) -> None:
        if not self.transport.is_open:
            raise InstrumentCommunicationError("Not connected")
        prev_status = self._status
        self._set_status(InstrumentStatus.BUSY)
        try:
            self.transport.write(command)
        except InstrumentCommunicationError as exc:
            self._set_status(InstrumentStatus.ERROR)
            self.error_occurred.emit(str(exc))
            raise
        finally:
            if self._status == InstrumentStatus.BUSY:
                self._set_status(prev_status)

    def _query_raw(self, command: str) -> str:
        if not self.transport.is_open:
            raise InstrumentCommunicationError("Not connected")
        prev_status = self._status
        self._set_status(InstrumentStatus.BUSY)
        try:
            return self.transport.query(command)
        except InstrumentCommunicationError as exc:
            self._set_status(InstrumentStatus.ERROR)
            self.error_occurred.emit(str(exc))
            raise
        finally:
            if self._status == InstrumentStatus.BUSY:
                self._set_status(prev_status)

    def _write_cmd(self, key: str, **kwargs) -> None:
        self._write_raw(self.profile.command(key, **kwargs))

    def _query_cmd(self, key: str, **kwargs) -> str:
        return self._query_raw(self.profile.command(key, **kwargs))

    def wait(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))
