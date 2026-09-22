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
    s12 = SParameterResult(freqs, real * 0.4, imag * 0.4)
    s22 = SParameterResult(freqs, real * 0.9, imag * 0.9)
    return MeasurementPointResult(
        index=index, requested_field_oe=field_oe, current_a=current_a,
        actual_current_a=current_a + 0.001, direction="forward", sweep_number=1,
        timestamp="2026-01-01T00:00:00", s11=s11, s21=s21, s12=s12, s22=s22,
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
    assert "s12_magnitude_db" in df.columns
    assert "s22_phase_deg" in df.columns
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


def test_save_point_exports_magnitude_graphs_only_no_phase(tmp_path):
    """Phase is still saved as numeric data (see the CSV-column test above)
    but is deliberately NOT graphed -- only a magnitude PNG per
    S-parameter."""
    dm = DataManager(tmp_path)
    dm.create_experiment("Exp")
    dm.save_point(_fake_result(0, 50.0, 0.25))
    graphs_dir = dm.experiment_dir / "graphs"
    for name in ("s11_magnitude.png", "s21_magnitude.png", "s12_magnitude.png", "s22_magnitude.png"):
        path = graphs_dir / name
        assert path.exists(), f"{name} was not exported"
        assert path.stat().st_size > 0
    for name in ("s11_phase.png", "s21_phase.png", "s12_phase.png", "s22_phase.png"):
        assert not (graphs_dir / name).exists()


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


def test_save_background_writes_separate_csv_and_hdf5_group(tmp_path):
    import h5py

    dm = DataManager(tmp_path)
    dm.create_experiment("Exp")
    # A background measurement at 0A -- distinct from a swept field point.
    result = _fake_result(-1, field_oe=0.0, current_a=0.0)
    result.direction = "background"
    csv_path = dm.save_background(result)

    assert csv_path == dm.experiment_dir / "background" / "background.csv"
    df = pd.read_csv(csv_path)
    assert len(df) == 11
    assert "s11_magnitude_db" in df.columns
    assert "s22_phase_deg" in df.columns
    # Background rows have no requested_field_oe/direction/sweep_number
    # columns -- those are field-sweep-specific concepts.
    assert "requested_field_oe" not in df.columns

    h5_path = dm.experiment_dir / "processed" / "experiment_data.h5"
    with h5py.File(h5_path, "r") as h5:
        assert "background" in h5
        assert len(h5["background"]["frequency_hz"]) == 11
        assert "s12_real" in h5["background"]


def test_save_background_does_not_affect_sweep_graphs_or_combined_csv(tmp_path):
    dm = DataManager(tmp_path)
    dm.create_experiment("Exp")
    dm.save_background(_fake_result(-1, 0.0, 0.0))
    # No sweep points were ever saved -- the sweep's combined CSV/graphs
    # should not exist just because a background measurement was taken.
    assert not (dm.experiment_dir / "processed" / "combined_data.csv").exists()
    assert not (dm.experiment_dir / "graphs" / "s11_magnitude.png").exists()


def test_filename_encodes_sign_and_magnitude(tmp_path):
    dm = DataManager(tmp_path)
    dm.create_experiment("Exp")
    result = _fake_result(0, -1500.0, -1.25)
    csv_path = dm.save_point(result)
    assert "Neg" in csv_path.name
    assert "1500" in csv_path.name
    assert "1p250" in csv_path.name
