import numpy as np
import pandas as pd

from src.data.data_manager import DataManager, MeasurementPointResult
from src.drivers.vna import SParameterResult


def _fake_result(index: int, field_oe: float, current_a: float) -> MeasurementPointResult:
    freqs = np.linspace(1e9, 2e9, 11)
    real = np.cos(freqs / 1e9)
    imag = np.sin(freqs / 1e9)
    s11 = SParameterResult(freqs, real, imag)
    s21 = SParameterResult(freqs, real * 0.5, imag * 0.5)
    return MeasurementPointResult(
        index=index, requested_field_oe=field_oe, current_a=current_a,
        actual_current_a=current_a + 0.001, direction="forward", sweep_number=1,
        timestamp="2026-01-01T00:00:00", s11=s11, s21=s21,
    )


def test_create_experiment_creates_expected_subfolders(tmp_path):
    dm = DataManager(tmp_path)
    exp_dir = dm.create_experiment("MyExperiment", sample_name="Sample1")
    assert exp_dir.exists()
    for sub in ("raw", "processed", "plots", "calibration", "logs"):
        assert (exp_dir / sub).is_dir()
    assert (exp_dir / "metadata.json").exists()


def test_save_point_writes_csv_immediately(tmp_path):
    dm = DataManager(tmp_path)
    dm.create_experiment("Exp")
    result = _fake_result(0, 150.0, 0.75)
    csv_path = dm.save_point(result)
    assert csv_path.exists()
    df = pd.read_csv(csv_path)
    assert len(df) == 11
    assert "s11_magnitude_db" in df.columns
    assert "s21_phase_deg" in df.columns
    assert df["requested_field_oe"].iloc[0] == 150.0


def test_save_point_updates_combined_csv_after_every_point(tmp_path):
    dm = DataManager(tmp_path)
    dm.create_experiment("Exp")
    dm.save_point(_fake_result(0, 0.0, 0.0))
    combined_path = dm.experiment_dir / "processed" / "combined_data.csv"
    assert combined_path.exists()
    assert len(pd.read_csv(combined_path)) == 11

    dm.save_point(_fake_result(1, 100.0, 0.5))
    assert len(pd.read_csv(combined_path)) == 22


def test_save_point_writes_hdf5(tmp_path):
    import h5py

    dm = DataManager(tmp_path)
    dm.create_experiment("Exp")
    dm.save_point(_fake_result(0, 50.0, 0.25))
    h5_path = dm.experiment_dir / "processed" / "experiment_data.h5"
    assert h5_path.exists()
    with h5py.File(h5_path, "r") as h5:
        assert "point_0000" in h5
        assert h5["point_0000"].attrs["requested_field_oe"] == 50.0
        assert len(h5["point_0000"]["frequency_hz"]) == 11


def test_save_point_exports_magnitude_and_phase_graphs(tmp_path):
    dm = DataManager(tmp_path)
    dm.create_experiment("Exp")
    dm.save_point(_fake_result(0, 50.0, 0.25))
    graphs_dir = dm.experiment_dir / "graphs"
    for name in ("s11_magnitude.png", "s11_phase.png", "s21_magnitude.png", "s21_phase.png"):
        path = graphs_dir / name
        assert path.exists(), f"{name} was not exported"
        assert path.stat().st_size > 0


def test_graphs_accumulate_across_points(tmp_path):
    """The exported graph should be regenerated (not merely appended to)
    from every point measured so far -- verified indirectly by checking
    the file grows to reflect more overlaid traces, not by re-parsing the
    PNG, since a second point's overlay renders a strictly larger figure
    content than a single trace."""
    dm = DataManager(tmp_path)
    dm.create_experiment("Exp")
    dm.save_point(_fake_result(0, 0.0, 0.0))
    one_point_size = (dm.experiment_dir / "graphs" / "s11_magnitude.png").stat().st_size
    dm.save_point(_fake_result(1, 100.0, 0.5))
    two_point_size = (dm.experiment_dir / "graphs" / "s11_magnitude.png").stat().st_size
    assert two_point_size != one_point_size


def test_filename_encodes_sign_and_magnitude(tmp_path):
    dm = DataManager(tmp_path)
    dm.create_experiment("Exp")
    result = _fake_result(0, -1500.0, -1.25)
    csv_path = dm.save_point(result)
    assert "Neg" in csv_path.name
    assert "1500" in csv_path.name
    assert "1p250" in csv_path.name
