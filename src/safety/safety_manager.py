"""Central, single-choke-point current safety validation.

Every current value that could ever reach the power supply -- typed by the
user, produced by calibration, produced by field->current conversion, or
part of a generated ramp/sweep sequence -- MUST pass through
``SafetyManager.validate_current`` immediately before transmission. No other
mechanism in this application is permitted to bypass it, and there is no
override switch: exceeding the configured maximum always raises
``SafetyViolationError``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable

from PySide6.QtCore import QObject, Signal


class SafetyViolationError(Exception):
    """Raised whenever a requested current fails safety validation."""


@dataclass
class ValidationRow:
    """One row of a pre-flight validation table (calibration or sweep)."""

    index: int
    requested_value: float
    requested_unit: str
    calculated_current_a: float | None
    within_current_limit: bool
    within_calibration_range: bool
    status: str


class SafetyManager(QObject):
    """Owns the mandatory maximum-current limit and validates every command.

    The limit cannot be changed while ``is_locked`` is True. Callers that
    enable the power-supply output, or start a calibration/measurement
    sequence, must call :meth:`acquire_lock` with a reason string, and
    release it with :meth:`release_lock` once the current has been ramped
    back to zero and the output disabled.
    """

    max_current_changed = Signal(float)
    lock_state_changed = Signal(bool)
    safety_violation = Signal(str)
    emergency_stop_changed = Signal(bool)

    def __init__(self, logger=None) -> None:
        super().__init__()
        self._max_current: float | None = None
        self._locked_reasons: set[str] = set()
        self._emergency_stop_active: bool = False
        self._logger = logger
        self._epsilon = 1e-9

    # ------------------------------------------------------------------
    # Max-current limit lifecycle
    # ------------------------------------------------------------------
    @property
    def max_current(self) -> float | None:
        return self._max_current

    @property
    def is_configured(self) -> bool:
        return self._max_current is not None

    @property
    def is_locked(self) -> bool:
        return len(self._locked_reasons) > 0

    @property
    def lock_reasons(self) -> tuple[str, ...]:
        return tuple(sorted(self._locked_reasons))

    def set_max_current(self, value: float) -> None:
        """Set (or change) the absolute maximum current limit, in amperes.

        Refuses to run while locked -- callers must stop any active
        process, ramp to zero, and disable the output first, per the
        mandatory safety workflow.
        """
        if self.is_locked:
            reasons = ", ".join(self.lock_reasons)
            raise SafetyViolationError(
                f"Cannot change maximum current while locked ({reasons}). "
                "Stop the active process, ramp to zero, and disable the "
                "output first."
            )
        if value is None or value <= 0:
            raise ValueError("Maximum current must be a positive number of amperes.")
        self._max_current = float(value)
        self._log(f"Maximum current limit set to {self._max_current:.6f} A")
        self.max_current_changed.emit(self._max_current)

    def acquire_lock(self, reason: str) -> None:
        self._locked_reasons.add(reason)
        self.lock_state_changed.emit(self.is_locked)

    def release_lock(self, reason: str) -> None:
        self._locked_reasons.discard(reason)
        self.lock_state_changed.emit(self.is_locked)

    # ------------------------------------------------------------------
    # Emergency stop
    # ------------------------------------------------------------------
    @property
    def emergency_stop_active(self) -> bool:
        return self._emergency_stop_active

    def trigger_emergency_stop(self) -> None:
        self._emergency_stop_active = True
        self._log("EMERGENCY STOP triggered - all current commands blocked", level="critical")
        self.emergency_stop_changed.emit(True)

    def clear_emergency_stop(self) -> None:
        self._emergency_stop_active = False
        self._log("Emergency stop cleared")
        self.emergency_stop_changed.emit(False)

    # ------------------------------------------------------------------
    # The single mandatory validation choke point
    # ------------------------------------------------------------------
    def validate_current(self, requested_current: float, context: str = "") -> float:
        """Validate ``requested_current`` (amperes) and return it unchanged.

        Raises :class:`SafetyViolationError` if the limit is not configured,
        emergency stop is active, or the absolute value exceeds the limit.
        This function must be the last thing called before any current
        command is transmitted to the power supply.
        """
        if self._emergency_stop_active:
            msg = f"Rejected current command ({context}): emergency stop is active"
            self._log(msg, level="error")
            self.safety_violation.emit(msg)
            raise SafetyViolationError(msg)

        if not self.is_configured:
            msg = f"Rejected current command ({context}): maximum current limit is not set"
            self._log(msg, level="error")
            self.safety_violation.emit(msg)
            raise SafetyViolationError(msg)

        if abs(requested_current) > self._max_current + self._epsilon:
            msg = (
                f"Rejected current command ({context}): requested "
                f"{requested_current:.6f} A exceeds maximum allowable "
                f"current {self._max_current:.6f} A"
            )
            self._log(msg, level="error")
            self.safety_violation.emit(msg)
            raise SafetyViolationError(msg)

        return requested_current

    def is_within_limit(self, requested_current: float) -> bool:
        """Non-raising check, useful for building validation tables."""
        if not self.is_configured:
            return False
        return abs(requested_current) <= self._max_current + self._epsilon

    def validate_sequence(
        self,
        values: Iterable[float],
        context: str = "sequence",
    ) -> list[ValidationRow]:
        """Validate a full list of currents without sending anything.

        Used to build the mandatory pre-measurement / pre-calibration
        validation table. Never transmits; only checks.
        """
        rows: list[ValidationRow] = []
        for i, val in enumerate(values):
            ok = self.is_within_limit(val)
            rows.append(
                ValidationRow(
                    index=i,
                    requested_value=val,
                    requested_unit="A",
                    calculated_current_a=val,
                    within_current_limit=ok,
                    within_calibration_range=True,
                    status="OK" if ok else "EXCEEDS MAX CURRENT",
                )
            )
            if not ok:
                self._log(
                    f"Sequence validation ({context}) point {i}: {val:.6f} A "
                    f"exceeds max {self._max_current} A",
                    level="warning",
                )
        return rows

    # ------------------------------------------------------------------
    def _log(self, message: str, level: str = "info") -> None:
        if self._logger is not None:
            getattr(self._logger, level, self._logger.info)(message)
