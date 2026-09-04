"""Gradual current ramping, shared by manual control and every automated
sequence (calibration, sweeps, resume, error recovery, emergency stop).

Using one ramp implementation everywhere is what makes the "manual control
must use the same ramping and safety-validation functions as automated
measurement" requirement mechanically true rather than merely intended.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

from src.drivers.power_supply import PowerSupplyController


class AbortRequested(Exception):
    """Raised internally to unwind a ramp/sequence cleanly on abort."""


@dataclass
class RampConfig:
    current_step_a: float = 0.05
    step_delay_s: float = 0.2
    stabilization_time_s: float = 1.0
    current_tolerance_a: float = 0.005


def generate_ramp_steps(start: float, end: float, step: float) -> list[float]:
    """Return the intermediate current values from ``start`` to ``end``.

    Always ends exactly on ``end``. Pure function (no I/O), which is what
    makes ramp generation unit-testable in isolation from any instrument.
    """
    if step <= 0:
        raise ValueError("Ramp step must be a positive number of amperes")
    if math.isclose(start, end, abs_tol=1e-12):
        return [end]

    direction = 1.0 if end > start else -1.0
    total_delta = abs(end - start)
    n_full_steps = int(total_delta // step)

    steps = [start + direction * step * i for i in range(1, n_full_steps + 1)]
    if not steps or not math.isclose(steps[-1], end, abs_tol=1e-9):
        steps.append(end)
    return steps


class CurrentRamper:
    """Ramps :class:`PowerSupplyController` current gradually and safely.

    Every intermediate step is sent through
    ``PowerSupplyController.set_current``, which itself validates through
    the SafetyManager -- so no ramp, manual or automated, can produce an
    out-of-limit command.
    """

    def __init__(self, power_supply: PowerSupplyController, config: RampConfig, logger=None) -> None:
        self.power_supply = power_supply
        self.config = config
        self._logger = logger

    def _log(self, msg: str, level: str = "info") -> None:
        if self._logger is not None:
            getattr(self._logger, level, self._logger.info)(msg)

    def ramp_to(
        self,
        target_current_a: float,
        context: str = "ramp",
        should_abort: Callable[[], bool] | None = None,
        wait_if_paused: Callable[[], None] | None = None,
        stabilize: bool = True,
        verify_no_error: bool = False,
    ) -> None:
        """Ramp to ``target_current_a``.

        ``verify_no_error``: when True, drains the instrument's SCPI error
        queue once after the final step and raises if it rejected the
        command -- a transport-level write succeeding does not guarantee
        the instrument's own parser accepted it (e.g. a malformed/
        unsupported command for that specific profile). Off by default to
        avoid doubling GPIB traffic on every intermediate step of a long
        automated sweep; turn it on for manual/diagnostic use where
        confirming the command actually took effect matters more than raw
        throughput.
        """
        present = self.power_supply.last_commanded_current_a
        steps = generate_ramp_steps(present, target_current_a, self.config.current_step_a)
        self._log(f"Ramping current {present:.6f} A -> {target_current_a:.6f} A ({context}), {len(steps)} step(s)")

        for step_value in steps:
            if wait_if_paused is not None:
                wait_if_paused()
            if should_abort is not None and should_abort():
                raise AbortRequested(f"Ramp to {target_current_a:.6f} A aborted at {step_value:.6f} A")
            self.power_supply.set_current(step_value, context=context)
            time.sleep(self.config.step_delay_s)

        if verify_no_error:
            self.power_supply.check_for_errors(context=f"{context} (target {target_current_a:.6f} A)")

        if stabilize and self.config.stabilization_time_s > 0:
            time.sleep(self.config.stabilization_time_s)

    def ramp_to_zero(self, context: str = "ramp to zero") -> None:
        self.ramp_to(0.0, context=context, stabilize=False)
