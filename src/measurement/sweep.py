"""Magnetic-field sweep generation and pre-flight validation.

Produces the field points requested by the user, converts every one of
them to a current via the CalibrationManager (which itself enforces the
SafetyManager limit and calibration range), and returns a validation
table. The GUI uses this table to decide whether Start Measurement may be
enabled: it must not be, if any point fails.
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass

from src.calibration.calibration_manager import CalibrationManager, CalibrationRangeError
from src.safety.safety_manager import SafetyManager, SafetyViolationError

SWEEP_MODES = ("forward", "reverse", "forward_reverse", "custom")


@dataclass
class SweepPoint:
    index: int
    field_oe: float
    current_a: float | None
    direction: str
    within_calibration_range: bool
    within_current_limit: bool
    status: str
    extrapolated: bool = False

    @property
    def is_valid(self) -> bool:
        return (
            (self.within_calibration_range or self.extrapolated)
            and self.within_current_limit
            and self.current_a is not None
        )


def generate_field_values(
    start_oe: float,
    stop_oe: float,
    step_oe: float,
    mode: str = "forward",
    custom_values: list[float] | None = None,
    repeats: int = 1,
) -> list[tuple[float, str]]:
    """Return a list of (field_oe, direction) pairs for the requested mode."""
    if mode == "custom":
        if not custom_values:
            raise ValueError("Custom sweep mode requires a non-empty list of field values")
        base = [(v, "custom") for v in custom_values]
    else:
        if step_oe <= 0:
            raise ValueError("Field step must be positive")
        n = int(round(abs(stop_oe - start_oe) / step_oe)) + 1
        sign = 1.0 if stop_oe >= start_oe else -1.0
        forward_values = [start_oe + sign * step_oe * i for i in range(n)]
        forward_values[-1] = stop_oe

        if mode == "forward":
            base = [(v, "forward") for v in forward_values]
        elif mode == "reverse":
            base = [(v, "reverse") for v in reversed(forward_values)]
        elif mode == "forward_reverse":
            base = [(v, "forward") for v in forward_values] + [
                (v, "reverse") for v in reversed(forward_values)
            ]
        else:
            raise ValueError(f"Unknown sweep mode: {mode}")

    return base * max(1, repeats)


def build_validation_table(
    field_direction_pairs: list[tuple[float, str]],
    calibration_manager: CalibrationManager,
    safety_manager: SafetyManager,
    calibration_direction_mode: str = "auto",
    interpolation_method: str = "linear",
    allow_extrapolation: bool = False,
    extrapolation_margin_fraction: float = 0.2,
) -> list[SweepPoint]:
    """Convert every requested field to current and validate it.

    Never raises: invalid points are recorded in the table with a status
    string so the GUI can display them and keep Start Measurement disabled.

    By default, a field outside the calibrated range is rejected. Pass
    ``allow_extrapolation=True`` to instead compute it via a curve fit
    beyond the measured range (still capped at
    ``extrapolation_margin_fraction`` of the calibrated span, and still
    subject to the max-current safety limit) -- such points are flagged
    with :attr:`SweepPoint.extrapolated`.
    """
    rows: list[SweepPoint] = []
    for i, (field_oe, sweep_dir) in enumerate(field_direction_pairs):
        calib_dir = calibration_direction_mode
        if calibration_direction_mode == "auto":
            calib_dir = {"forward": "increasing", "reverse": "decreasing"}.get(sweep_dir, "all")

        ok, current, status = calibration_manager.validate_field_request(
            field_oe, direction=calib_dir, method=interpolation_method,
            allow_extrapolation=allow_extrapolation,
            extrapolation_margin_fraction=extrapolation_margin_fraction,
        )
        extrapolated = ok and "EXTRAPOLATED" in status
        within_range = "OUTSIDE CALIBRATION RANGE" not in status and not extrapolated
        within_limit = "EXCEEDS MAX CURRENT" not in status

        rows.append(
            SweepPoint(
                index=i,
                field_oe=field_oe,
                current_a=current if ok else None,
                direction=sweep_dir,
                within_calibration_range=within_range,
                within_current_limit=within_limit,
                status=status,
                extrapolated=extrapolated,
            )
        )
    return rows


@dataclass
class SequenceSummary:
    total_points: int
    max_positive_current_a: float
    max_negative_current_a: float
    max_abs_current_a: float
    all_valid: bool


def summarize_sequence(rows: list[SweepPoint]) -> SequenceSummary:
    currents = [r.current_a for r in rows if r.current_a is not None]
    pos = max([c for c in currents if c > 0], default=0.0)
    neg = min([c for c in currents if c < 0], default=0.0)
    abs_max = max([abs(c) for c in currents], default=0.0)
    return SequenceSummary(
        total_points=len(rows),
        max_positive_current_a=pos,
        max_negative_current_a=neg,
        max_abs_current_a=abs_max,
        all_valid=all(r.is_valid for r in rows) if rows else False,
    )
