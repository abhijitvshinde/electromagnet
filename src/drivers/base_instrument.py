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

    def clear(self) -> None:
        """Optional: clear the instrument's I/O buffers (Selective Device
        Clear). Default no-op -- override where the underlying transport
        actually supports it (e.g. real GPIB)."""
        return None


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

    def clear(self) -> None:
        """Selective Device Clear -- resets the instrument's I/O buffers
        (e.g. recovers from a stuck/unread response) without a full *RST."""
        if self._resource is None:
            raise InstrumentCommunicationError("Transport is not open")
        try:
            self._resource.clear()
        except Exception as exc:
            raise InstrumentCommunicationError(f"Device clear failed: {exc}") from exc


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

    def clear_io_buffers(self) -> None:
        """Best-effort Selective Device Clear -- recovers from a stuck/
        unread response in the instrument's output buffer (SCPI error
        -410 'Query INTERRUPTED') without a full *RST. No-op if the
        transport doesn't support it (e.g. simulation)."""
        try:
            self.transport.clear()
            self._log("Sent device clear (I/O buffer reset)")
        except InstrumentCommunicationError as exc:
            self._log(f"Device clear failed: {exc}", level="warning")

    def check_for_errors(self, context: str = "", max_entries: int = 20) -> list[str]:
        """Drain the instrument's SCPI error queue and raise if anything is
        actually queued.

        A write/query completing without a transport-level exception only
        means the bytes were exchanged -- it does NOT mean the instrument
        accepted the command. A malformed or unsupported command can be
        silently rejected by the instrument's own parser while every layer
        below us reports success. Call this after any command whose actual
        effect matters (e.g. a current setpoint) to catch that case instead
        of assuming the command took effect.

        If the very first response is -410 "Query INTERRUPTED" (the
        instrument still had an unread response from some earlier query
        sitting in its output buffer -- e.g. an overlapping background
        poll), this sends a device clear and retries once rather than
        surfacing that as if it were a real error about our own command.
        """
        if "get_error_queue" not in self.profile.commands:
            return []

        for attempt in range(2):
            errors: list[str] = []
            interrupted = False
            for i in range(max_entries):
                resp = self._query_raw(self.profile.command("get_error_queue"), critical=False).strip()
                if i == 0 and attempt == 0 and "-410" in resp:
                    # This response isn't a real queued error -- it means
                    # OUR query got interrupted by leftover unread data from
                    # something earlier. Stop draining immediately (further
                    # reads in this same attempt would be unreliable too)
                    # rather than treating it as consuming a real queue slot.
                    interrupted = True
                    break
                if not resp or resp.lstrip("+").startswith("0"):
                    break
                errors.append(resp)

            if interrupted:
                self._log(
                    "Got -410 'Query INTERRUPTED' while checking for errors -- clearing I/O and retrying",
                    level="warning",
                )
                self.clear_io_buffers()
                continue

            if errors:
                joined = "; ".join(errors)
                msg = f"Instrument reported error(s){' (' + context + ')' if context else ''}: {joined}"
                self._log(msg, level="error")
                raise InstrumentCommunicationError(msg)
            return errors
        return []

    # ------------------------------------------------------------------
    def _write_raw(self, command: str, critical: bool = True) -> None:
        """Send ``command``. If ``critical`` is False, a failure is still
        raised to the caller but does NOT leave the driver's status stuck
        on Error -- use this for optional/best-effort commands (e.g. an
        extra hardware safety limit) whose failure doesn't mean the
        instrument connection itself is broken."""
        if not self.transport.is_open:
            raise InstrumentCommunicationError("Not connected")
        prev_status = self._status
        self._set_status(InstrumentStatus.BUSY)
        try:
            self.transport.write(command)
        except InstrumentCommunicationError as exc:
            self._set_status(InstrumentStatus.ERROR if critical else prev_status)
            self.error_occurred.emit(str(exc))
            raise
        finally:
            if self._status == InstrumentStatus.BUSY:
                self._set_status(prev_status)

    def _query_raw(self, command: str, critical: bool = True) -> str:
        """See :meth:`_write_raw` for the meaning of ``critical``."""
        if not self.transport.is_open:
            raise InstrumentCommunicationError("Not connected")
        prev_status = self._status
        self._set_status(InstrumentStatus.BUSY)
        try:
            return self.transport.query(command)
        except InstrumentCommunicationError as exc:
            self._set_status(InstrumentStatus.ERROR if critical else prev_status)
            self.error_occurred.emit(str(exc))
            raise
        finally:
            if self._status == InstrumentStatus.BUSY:
                self._set_status(prev_status)

    def _write_cmd(self, key: str, critical: bool = True, **kwargs) -> None:
        self._write_raw(self.profile.command(key, **kwargs), critical=critical)

    def _query_cmd(self, key: str, critical: bool = True, **kwargs) -> str:
        return self._query_raw(self.profile.command(key, **kwargs), critical=critical)

    def wait(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))
