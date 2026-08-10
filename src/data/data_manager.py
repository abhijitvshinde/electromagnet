"""Experiment folder creation and immediate, point-by-point data saving.

Data for a field point is written to disk (CSV, combined CSV, and HDF5)
the instant that point is measured -- never buffered until the end of the
sequence -- so a crash, communication loss, or emergency stop loses at
most the point in flight.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd

from src.drivers.vna import SParameterResult


@dataclass
class MeasurementPointResult:
    index: int
    requested_field_oe: float
    current_a: float
    actual_current_a: float | None
    direction: str
    sweep_number: int
    timestamp: str
    s11: SParameterResult | None
    s21: SParameterResult | None


def _sanitize(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_\-]+", "_", name.strip())
    return name or "experiment"


def _field_current_filename(field_oe: float, current_a: float) -> str:
    field_sign = "Pos" if field_oe >= 0 else "Neg"
    field_part = f"{abs(field_oe):07.2f}".replace(".", "p")
    current_sign = "Pos" if current_a >= 0 else "Neg"
    current_part = f"{abs(current_a):.3f}".replace(".", "p")
    return f"Field_{field_sign}_{field_part}_Oe_Current_{current_sign}_{current_part}_A"


class DataManager:
    def __init__(self, output_root: Path, logger=None) -> None:
        self.output_root = Path(output_root)
        self._logger = logger
        self.experiment_dir: Path | None = None
        self._metadata: dict[str, Any] = {}
        self._combined_rows: list[dict[str, Any]] = []

    def _log(self, msg: str, level: str = "info") -> None:
        if self._logger is not None:
            getattr(self._logger, level, self._logger.info)(msg)

    # ------------------------------------------------------------------
    def create_experiment(
        self,
        experiment_name: str,
        sample_name: str = "",
        sample_description: str = "",
        operator_name: str = "",
        notes: str = "",
    ) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dir_name = f"{timestamp}_{_sanitize(experiment_name)}"
        self.experiment_dir = self.output_root / dir_name

        for sub in ("raw", "processed", "plots", "calibration", "logs"):
            (self.experiment_dir / sub).mkdir(parents=True, exist_ok=True)

        self._combined_rows = []
        self._metadata = {
            "experiment_name": experiment_name,
            "sample_name": sample_name,
            "sample_description": sample_description,
            "operator_name": operator_name,
            "notes": notes,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._write_metadata()
        self._log(f"Experiment folder created: {self.experiment_dir}")
        return self.experiment_dir

    def _write_metadata(self) -> None:
        if self.experiment_dir is None:
            return
        with open(self.experiment_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(self._metadata, f, indent=2, default=str)

    def update_metadata(self, **kwargs: Any) -> None:
        self._metadata.update(kwargs)
        self._write_metadata()

    def save_instrument_info(self, power_supply_idn: str | None, vna_idn: str | None) -> None:
        self.update_metadata(power_supply_idn=power_supply_idn, vna_idn=vna_idn)

    def save_max_current(self, value: float) -> None:
        self.update_metadata(max_current_a=value)

    def save_vna_settings(self, config: dict[str, Any]) -> None:
        if self.experiment_dir is None:
            return
        with open(self.experiment_dir / "vna_settings.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, default=str)

    def save_sweep_settings(self, config: dict[str, Any]) -> None:
        if self.experiment_dir is None:
            return
        with open(self.experiment_dir / "sweep_settings.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, default=str)

    def save_calibration_csv(self, source_points_df: pd.DataFrame) -> None:
        if self.experiment_dir is None:
            return
        source_points_df.to_csv(self.experiment_dir / "calibration" / "calibration.csv", index=False)

    # ------------------------------------------------------------------
    def save_point(self, point: MeasurementPointResult) -> Path:
        """Write this point's data to disk immediately: per-point CSV,
        rewritten combined CSV, and an appended HDF5 group."""
        if self.experiment_dir is None:
            raise RuntimeError("No experiment folder created yet")

        n = len(point.s11.frequencies_hz) if point.s11 is not None else len(point.s21.frequencies_hz)
        freqs = point.s11.frequencies_hz if point.s11 is not None else point.s21.frequencies_hz

        data: dict[str, Any] = {
            "frequency_hz": freqs,
            "requested_field_oe": np.full(n, point.requested_field_oe),
            "current_a": np.full(n, point.current_a),
            "actual_current_a": np.full(n, point.actual_current_a if point.actual_current_a is not None else np.nan),
            "direction": [point.direction] * n,
            "sweep_number": np.full(n, point.sweep_number),
            "timestamp": [point.timestamp] * n,
        }
        if point.s11 is not None:
            data.update(
                s11_real=point.s11.real,
                s11_imag=point.s11.imag,
                s11_magnitude=point.s11.magnitude_linear,
                s11_magnitude_db=point.s11.magnitude_db,
                s11_phase_deg=point.s11.phase_deg,
            )
        if point.s21 is not None:
            data.update(
                s21_real=point.s21.real,
                s21_imag=point.s21.imag,
                s21_magnitude=point.s21.magnitude_linear,
                s21_magnitude_db=point.s21.magnitude_db,
                s21_phase_deg=point.s21.phase_deg,
            )

        df = pd.DataFrame(data)
        filename = _field_current_filename(point.requested_field_oe, point.current_a) + ".csv"
        csv_path = self.experiment_dir / "raw" / filename
        df.to_csv(csv_path, index=False)

        self._combined_rows.append(df)
        combined_df = pd.concat(self._combined_rows, ignore_index=True)
        combined_df.to_csv(self.experiment_dir / "processed" / "combined_data.csv", index=False)

        self._append_hdf5(point, freqs)

        self._log(f"Saved point {point.index} ({point.requested_field_oe:.4f} Oe) -> {csv_path.name}")
        return csv_path

    def _append_hdf5(self, point: MeasurementPointResult, freqs: np.ndarray) -> None:
        if self.experiment_dir is None:
            return
        h5_path = self.experiment_dir / "processed" / "experiment_data.h5"
        with h5py.File(h5_path, "a") as h5:
            h5.attrs["experiment_name"] = self._metadata.get("experiment_name", "")
            h5.attrs["max_current_a"] = self._metadata.get("max_current_a", np.nan)
            group_name = f"point_{point.index:04d}"
            if group_name in h5:
                del h5[group_name]
            grp = h5.create_group(group_name)
            grp.attrs["requested_field_oe"] = point.requested_field_oe
            grp.attrs["current_a"] = point.current_a
            grp.attrs["actual_current_a"] = point.actual_current_a if point.actual_current_a is not None else np.nan
            grp.attrs["direction"] = point.direction
            grp.attrs["sweep_number"] = point.sweep_number
            grp.attrs["timestamp"] = point.timestamp
            grp.create_dataset("frequency_hz", data=freqs)
            if point.s11 is not None:
                grp.create_dataset("s11_real", data=point.s11.real)
                grp.create_dataset("s11_imag", data=point.s11.imag)
            if point.s21 is not None:
                grp.create_dataset("s21_real", data=point.s21.real)
                grp.create_dataset("s21_imag", data=point.s21.imag)

    # ------------------------------------------------------------------
    def build_colormap(self, which: str) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """Return (fields, frequencies, magnitude_db) for an S11/S21 colormap."""
        if not self._combined_rows:
            return None
        combined = pd.concat(self._combined_rows, ignore_index=True)
        mag_col = f"{which.lower()}_magnitude_db"
        if mag_col not in combined.columns:
            return None
        pivot = combined.pivot_table(index="requested_field_oe", columns="frequency_hz", values=mag_col)
        fields = pivot.index.to_numpy()
        freqs = pivot.columns.to_numpy()
        matrix = pivot.to_numpy()
        return fields, freqs, matrix

    def finalize(self) -> None:
        if self.experiment_dir is None:
            return
        self.update_metadata(
            finalized_at=datetime.now().isoformat(timespec="seconds"),
            total_points_saved=len(self._combined_rows),
        )
        self._log(f"Experiment finalized: {self.experiment_dir} ({len(self._combined_rows)} point(s))")
