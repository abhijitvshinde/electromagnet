"""Current <-> magnetic-field calibration: storage, validation, interpolation.

Every current value this module hands back from :meth:`current_for_field`
is passed through the SafetyManager before being returned, so a caller can
never receive an out-of-limit current even if it forgets to check.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.safety.safety_manager import SafetyManager, SafetyViolationError

DIRECTIONS = ("increasing", "decreasing", "unspecified")


class CalibrationRangeError(Exception):
    """Raised when a requested field lies outside the calibrated range."""


@dataclass
class CalibrationPoint:
    index: int
    commanded_current_a: float
    field_oe: float
    actual_current_a: float | None = None
    polarity: str = field(init=False, default="")
    direction: str = "unspecified"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    notes: str = ""

    def __post_init__(self) -> None:
        if self.commanded_current_a > 0:
            self.polarity = "positive"
        elif self.commanded_current_a < 0:
            self.polarity = "negative"
        else:
            self.polarity = "zero"

    def to_dict(self) -> dict:
        return asdict(self)


class CalibrationManager:
    def __init__(self, safety_manager: SafetyManager, logger=None) -> None:
        self.safety_manager = safety_manager
        self._logger = logger
        self.points: list[CalibrationPoint] = []
        self._autosave_path: Path | None = None

    # ------------------------------------------------------------------
    def _log(self, msg: str, level: str = "info") -> None:
        if self._logger is not None:
            getattr(self._logger, level, self._logger.info)(msg)

    def set_autosave_path(self, path: Path | None) -> None:
        self._autosave_path = Path(path) if path else None

    # ------------------------------------------------------------------
    # Point management
    # ------------------------------------------------------------------
    def add_point(
        self,
        commanded_current_a: float,
        field_oe: float,
        actual_current_a: float | None = None,
        direction: str = "unspecified",
        notes: str = "",
    ) -> CalibrationPoint:
        point = CalibrationPoint(
            index=len(self.points),
            commanded_current_a=commanded_current_a,
            field_oe=field_oe,
            actual_current_a=actual_current_a,
            direction=direction,
            notes=notes,
        )
        self.points.append(point)
        self._log(
            f"Calibration point added: I={commanded_current_a:.6f} A -> "
            f"H={field_oe:.4f} Oe ({direction})"
        )
        if self._autosave_path is not None:
            self.save_csv(self._autosave_path)
        return point

    def edit_point(self, index: int, **kwargs) -> None:
        for p in self.points:
            if p.index == index:
                for k, v in kwargs.items():
                    setattr(p, k, v)
                if "commanded_current_a" in kwargs:
                    p.__post_init__()
                if self._autosave_path is not None:
                    self.save_csv(self._autosave_path)
                return
        raise IndexError(f"No calibration point with index {index}")

    def delete_point(self, index: int) -> None:
        self.points = [p for p in self.points if p.index != index]
        for i, p in enumerate(self.points):
            p.index = i
        if self._autosave_path is not None:
            self.save_csv(self._autosave_path)

    def clear(self) -> None:
        self.points = []

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------
    def load_csv(self, path: Path) -> list[str]:
        df = pd.read_csv(path)
        return self._load_dataframe(df)

    def load_json(self, path: Path) -> list[str]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        df = pd.DataFrame(data.get("points", data))
        return self._load_dataframe(df)

    def _load_dataframe(self, df: pd.DataFrame) -> list[str]:
        issues: list[str] = []
        col_map = {c.lower().strip(): c for c in df.columns}

        def find_col(*names: str) -> str | None:
            for n in names:
                if n in col_map:
                    return col_map[n]
            return None

        current_col = find_col("current_a", "current", "commanded_current_a", "i_a")
        field_col = find_col("field_oe", "field", "h_oe", "magnetic_field_oe")
        if current_col is None or field_col is None:
            raise ValueError(
                "Calibration file must contain a current column (e.g. 'current_a') "
                "and a field column (e.g. 'field_oe')"
            )

        actual_col = find_col("actual_current_a", "actual_current")
        direction_col = find_col("direction", "sweep_direction")
        notes_col = find_col("notes")

        currents_raw = pd.to_numeric(df[current_col], errors="coerce")
        fields_raw = pd.to_numeric(df[field_col], errors="coerce")

        missing_mask = currents_raw.isna() | fields_raw.isna()
        if missing_mask.any():
            issues.append(f"{int(missing_mask.sum())} row(s) with missing/invalid numeric values were dropped")

        new_points: list[CalibrationPoint] = []
        seen_currents: dict[tuple[float, str], int] = {}
        for i in range(len(df)):
            if missing_mask.iloc[i]:
                continue
            cur = float(currents_raw.iloc[i])
            fld = float(fields_raw.iloc[i])
            direction = str(df[direction_col].iloc[i]) if direction_col else "unspecified"
            key = (round(cur, 9), direction)
            if key in seen_currents:
                issues.append(f"Duplicate current {cur:.6f} A for direction '{direction}' (row {i})")
                continue
            seen_currents[key] = i

            if self.safety_manager.is_configured and not self.safety_manager.is_within_limit(cur):
                issues.append(
                    f"Row {i}: current {cur:.6f} A exceeds maximum allowable current "
                    f"{self.safety_manager.max_current:.6f} A -- point excluded"
                )
                continue

            actual = None
            if actual_col is not None and not pd.isna(df[actual_col].iloc[i]):
                try:
                    actual = float(df[actual_col].iloc[i])
                except (TypeError, ValueError):
                    actual = None
            notes = str(df[notes_col].iloc[i]) if notes_col and not pd.isna(df[notes_col].iloc[i]) else ""

            new_points.append(
                CalibrationPoint(
                    index=len(new_points),
                    commanded_current_a=cur,
                    field_oe=fld,
                    actual_current_a=actual,
                    direction=direction if direction in DIRECTIONS or direction else "unspecified",
                    notes=notes,
                )
            )

        self.points = new_points
        issues.extend(self.validate())
        self._log(f"Loaded calibration: {len(self.points)} point(s), {len(issues)} issue(s)")
        return issues

    def save_csv(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame([p.to_dict() for p in self.points])
        df.to_csv(path, index=False)

    def save_json(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"points": [p.to_dict() for p in self.points]}, f, indent=2)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate(self) -> list[str]:
        issues: list[str] = []
        if not self.points:
            return ["Calibration is empty"]

        currents = [p.commanded_current_a for p in self.points]
        fields = [p.field_oe for p in self.points]

        if any(np.isnan(currents)) or any(np.isnan(fields)):
            issues.append("Calibration contains invalid (NaN) numeric values")

        seen: dict[tuple[float, str], int] = {}
        for p in self.points:
            key = (round(p.commanded_current_a, 9), p.direction)
            if key in seen:
                issues.append(f"Duplicate current value {p.commanded_current_a:.6f} A ({p.direction})")
            seen[key] = p.index

        if self.safety_manager.is_configured:
            for p in self.points:
                if not self.safety_manager.is_within_limit(p.commanded_current_a):
                    issues.append(
                        f"Point {p.index}: current {p.commanded_current_a:.6f} A exceeds "
                        f"maximum allowable current {self.safety_manager.max_current:.6f} A"
                    )

        for direction in ("increasing", "decreasing"):
            subset = sorted(
                (p for p in self.points if p.direction == direction),
                key=lambda p: p.commanded_current_a,
            )
            if len(subset) >= 2 and not self._is_monotonic([p.field_oe for p in subset]):
                issues.append(f"Calibration curve '{direction}' is not monotonic in field vs. current")

        return issues

    @staticmethod
    def _is_monotonic(values: list[float]) -> bool:
        arr = np.array(values)
        diffs = np.diff(arr)
        return bool(np.all(diffs >= -1e-9) or np.all(diffs <= 1e-9))

    def is_valid(self) -> bool:
        blocking_keywords = ("exceeds maximum", "not monotonic", "empty", "invalid (NaN)")
        return not any(any(k in issue for k in blocking_keywords) for issue in self.validate())

    # ------------------------------------------------------------------
    # Ranges
    # ------------------------------------------------------------------
    def current_range(self) -> tuple[float, float] | None:
        if not self.points:
            return None
        currents = [p.commanded_current_a for p in self.points]
        return (min(currents), max(currents))

    def field_range(self, direction: str = "all") -> tuple[float, float] | None:
        subset = self._select(direction)
        if not subset:
            return None
        fields = [p.field_oe for p in subset]
        return (min(fields), max(fields))

    # ------------------------------------------------------------------
    # Interpolation: field (Oe) -> current (A)
    # ------------------------------------------------------------------
    def _select(self, direction: str) -> list[CalibrationPoint]:
        if direction == "all":
            return list(self.points)
        if direction == "average":
            return list(self.points)
        return [p for p in self.points if p.direction == direction] or list(self.points)

    def current_for_field(
        self,
        field_oe: float,
        direction: str = "all",
        method: str = "linear",
        context: str = "field-to-current conversion",
    ) -> float:
        """Convert a requested field (Oe) into a validated current (A).

        Never extrapolates: raises :class:`CalibrationRangeError` if
        ``field_oe`` falls outside the calibrated range. The resulting
        current is always passed through the SafetyManager before being
        returned, so callers get either a safe current or an exception.
        """
        subset = self._select(direction)
        if len(subset) < 2:
            raise CalibrationRangeError("Not enough calibration points to interpolate")

        if direction == "average" and {"increasing", "decreasing"} <= {p.direction for p in self.points}:
            inc = self.current_for_field(field_oe, direction="increasing", method=method, context=context)
            dec = self.current_for_field(field_oe, direction="decreasing", method=method, context=context)
            return self.safety_manager.validate_current((inc + dec) / 2.0, context=context)

        subset = sorted(subset, key=lambda p: p.field_oe)
        fields = np.array([p.field_oe for p in subset])
        currents = np.array([p.commanded_current_a for p in subset])

        lo, hi = float(fields.min()), float(fields.max())
        if field_oe < lo - 1e-9 or field_oe > hi + 1e-9:
            raise CalibrationRangeError(
                f"Requested field {field_oe:.4f} Oe is outside the calibrated range "
                f"[{lo:.4f}, {hi:.4f}] Oe -- extrapolation is not permitted"
            )

        if method == "cubic" and len(subset) >= 4:
            from scipy.interpolate import interp1d

            f = interp1d(fields, currents, kind="cubic")
            current = float(f(field_oe))
        else:
            current = float(np.interp(field_oe, fields, currents))

        return self.safety_manager.validate_current(current, context=context)

    def validate_field_request(
        self, field_oe: float, direction: str = "all", method: str = "linear"
    ) -> tuple[bool, float | None, str]:
        """Non-raising check used to build sweep validation tables."""
        try:
            current = self.current_for_field(field_oe, direction=direction, method=method)
            return True, current, "OK"
        except CalibrationRangeError as exc:
            return False, None, f"OUTSIDE CALIBRATION RANGE: {exc}"
        except SafetyViolationError as exc:
            return False, None, f"EXCEEDS MAX CURRENT: {exc}"
