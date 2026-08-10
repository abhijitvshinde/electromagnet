# Electromagnet & VNA Control Application

Windows desktop application for controlling an electromagnet power
supply and a Vector Network Analyzer over GPIB, running automated
magnetic-field sweeps, measuring S11/S21, plotting live, and saving all
measurement data. Built for electromagnet equipment **YP180829-188-2**.

A hard maximum-current safety limit is mandatory and enforced centrally
(`src/safety/safety_manager.py`) on every current command anywhere in the
application, with no override. See `docs/USER_MANUAL.md` for the full
per-tab walkthrough.

## Architecture

```
src/
  config/       JSON-driven configuration loading (no hard-coded SCPI)
  safety/        SafetyManager -- the single mandatory validation choke point
  drivers/       BaseInstrumentDriver, PowerSupplyController, VNAController,
                 VisaTransport (real GPIB), simulation.py (software-only)
  calibration/   CalibrationManager (storage/validation/interpolation),
                 CalibrationController (manual calibration sequence)
  measurement/   ramping (CurrentRamper), sweep (field->current sequence
                 generation/validation), MeasurementController (full
                 automated sequence, runs in a QThread)
  data/          DataManager -- experiment folders, per-point CSV/HDF5,
                 combined data, immediately on every point
  plotting/      PlotManager -- live pyqtgraph plots + matplotlib static/
                 color-map figure export
  logging_/      ExperimentLogger -- app + per-experiment log files, Qt
                 signal bridge to the Event Log tab
  gui/           AppContext (shared state) + MainWindow + 8 tabs
config/          power_supply_profiles.json, vna_profiles.json (SCPI
                 command PLACEHOLDERS -- see docs/SCPI_REPLACEMENT_GUIDE.md),
                 app_settings.json (GPIB addresses, ramp defaults, ...)
tests/           pytest unit tests (safety, ramping, calibration, sweep
                 validation, data saving, driver enforcement)
scripts/         generate_sample_data.py -- full simulated experiment,
                 also produces sample_data/
sample_data/     Output of a sample simulated experiment (CSV, HDF5,
                 JSON metadata, PNG/PDF plots and color maps)
docs/            User manual, GPIB address guide, SCPI replacement guide,
                 packaging guide
```

**No instrument-specific SCPI commands have been invented for the
generic template.** `GENERIC_PLACEHOLDER` in both
`config/power_supply_profiles.json` and `config/vna_profiles.json` is a
clearly marked template of `PLACEHOLDER_...` strings for whatever
instruments you have. Real, filled-in profiles are also included for
this setup's actual hardware -- **`AGILENT_E3634A`** and
**`KEYSIGHT_PNA_X_N5242B`** -- selectable from the Instrument Connection
tab's Command profile dropdown; read the caveats in
`docs/SCPI_REPLACEMENT_GUIDE.md` before an unattended run (the E3634A is
unipolar, and the PNA-X measurement-creation commands have a firmware-
dependent edge case). The application also runs fully in **Simulation
Mode** without any real hardware or real commands -- see below.

## Installation

Requires Python 3.10+ (developed and tested on 3.13).

```bash
python -m venv .venv
```

Windows (PowerShell):
```bash
.venv\Scripts\Activate.ps1
```
Windows (Git Bash / this environment):
```bash
source .venv/Scripts/activate
```

```bash
pip install -r requirements.txt
```

## Running

```bash
python -m src.main
```

The application opens in **Simulation Mode** by default (no physical
GPIB hardware required) -- a banner on the Instrument Connection tab
makes this obvious. Uncheck it and enter real GPIB addresses once your
instrument profiles have real SCPI commands (see
`docs/SCPI_REPLACEMENT_GUIDE.md`) and hardware is connected.

## Testing

```bash
pytest
```

43 unit tests cover: maximum-current enforcement (boundary values,
positive/negative, rejection, lock semantics, emergency stop), ramp-step
generation and abort behavior, calibration interpolation/range/validation
checks, field-sweep sequence generation and validation, the power-supply
driver's safety enforcement, and data saving (per-point CSV, combined
CSV, HDF5).

## Sample data

```bash
python scripts/generate_sample_data.py
```

Runs a complete simulated hysteresis-calibrated field sweep (forward and
reverse, -250 to +250 Oe) end-to-end through the real
`MeasurementController`/`DataManager` code path and writes a full
experiment folder into `sample_data/`, including per-point CSV files, a
combined CSV, an HDF5 file, JSON metadata/settings, example S11/S21 trace
plots, and S11/S21 color maps (PNG + PDF). This doubles as an end-to-end
smoke test of the whole pipeline.

## Further reading

- `docs/USER_MANUAL.md` -- what each of the 8 tabs does
- `docs/GPIB_ADDRESS_GUIDE.md` -- finding your instruments' VISA/GPIB addresses
- `docs/SCPI_REPLACEMENT_GUIDE.md` -- replacing the placeholder SCPI commands for your real instruments
- `docs/PACKAGING.md` -- building a standalone Windows executable with PyInstaller

## Safety summary

- A maximum allowable current must be entered and confirmed before any
  other tab is usable.
- Every current command (manual, calibration, sweep, ramp step, resume,
  error recovery) passes through `SafetyManager.validate_current`
  immediately before transmission; only `PowerSupplyController` is
  permitted to send a current-setting SCPI command, and it always
  validates first. There is no override.
- The limit cannot be changed while the output is enabled or a
  calibration/measurement is running.
- Data is saved to disk after every single field/calibration point, not
  only at the end.
- Emergency Stop and application-close both attempt a safe ramp-to-zero
  and output-disable, and clearly warn if the physical state could not
  be confirmed (e.g. communication lost) rather than assuming success.
