# User Manual

Electromagnet (equipment YP180829-188-2) + VNA control application.
Eight tabs, used roughly left to right for a full experiment.

## 1. Safety & Maximum Current

The application opens with every other tab disabled. Enter the maximum
allowable electromagnet current in amperes and click **Set / Confirm
Maximum Current**. This is mandatory: no current command anywhere in the
application (manual control, calibration, sweeps, ramping, resume, error
recovery) can ever exceed `±this value`, and there is no override.

You cannot change this value while a calibration or measurement is
running, or while the power-supply output is enabled -- stop the active
process, ramp to zero, and disable the output first (the Live
Measurement and Calibration tabs both have a **Ramp Current to Zero**
button for this).

## 2. Instrument Connection

Check **Simulation Mode** to work without physical hardware (it is
checked by default and clearly banners itself as active). Otherwise,
enter each instrument's GPIB VISA address (see
`docs/GPIB_ADDRESS_GUIDE.md`), timeout, and command profile, then
**Connect**. **Test Communication** sends `*IDN?` and reports the
response. Status indicators show Disconnected / Connecting / Connected /
Busy / Error for each instrument.

## 3. Calibration

**Option 1 -- Load Existing Calibration**: browse to a CSV or JSON file
with at least a current column and a field column, click **Load
Calibration**. The table, plot, and issue list populate immediately;
invalid points (duplicates, missing values, non-monotonic curve, currents
over the limit) are reported and excluded.

**Option 2 -- Create New Calibration Manually**: enter a start/stop/step
or a custom comma-separated current list, a direction label, stabilization
time, and ramp step/delay, then **Start Calibration**. For each current
point the software ramps to it, holds it, and prompts:

> Enter the measured magnetic field corresponding to the presently
> applied current.

Measure the field with your external instrument, type it into **Measured
field (Oe)**, and click **Confirm Field Value** -- only then does the
sequence advance. **Repeat Current Point** re-applies the same current
without saving a point; **Previous Point** goes back one point. **Pause /
Resume / Abort / Ramp Current to Zero / Emergency Stop** are always
available. Every confirmed point is saved to disk immediately.

## 4. Field Sweep

Configure start/stop/step (or a custom field list), sweep mode (forward,
reverse, forward+reverse), repeats, calibration-direction selection, and
interpolation method, then **Build & Validate Sequence**. The table shows
every point's calculated current and validation status. Live Measurement
will refuse to start unless every point is valid.

## 5. VNA Settings

Set start/stop frequency, number of points (frequency spacing is
computed and displayed automatically), source power, IF bandwidth,
sweep time, averaging, channel, trigger mode, and which S-parameters to
measure. **Apply Configuration to VNA** pushes it to the connected
instrument (or just stores it if not yet connected).

## 6. Live Measurement

The main screen: connection status, maximum current, present
current/field, progress, elapsed time, and the live S11/S21 plots
(zoom/pan/autoscale, overlay or latest-trace-only). **Start Measurement**
checks every precondition (limit set, both instruments connected, valid
calibration, valid sequence, VNA configured, experiment folder created)
and asks for confirmation before it enables the output and begins. Data
for every field point is saved to disk the instant it is measured.
**Pause / Resume / Abort / Ramp to Zero / EMERGENCY STOP** are always
available during a run.

## 7. Data & Experiment

Enter experiment/sample/operator metadata and an output folder, then
**Create Experiment Folder** -- do this before starting a measurement.
Generates S11/S21 color maps (magnitude vs. frequency and field) once
data exists.

## 8. Event Log

Live view of every logged event (connections, current commands, field
points, pauses/aborts/emergency stops, errors, file saves, shutdown). The
underlying log files persist in `logs/` (application-wide) and inside
each experiment folder (`event_log.log`), regardless of what's cleared
from this view.

## Closing the application

If a process is running or the output is enabled, closing the window
prompts for confirmation, then stops the process, ramps the current to
zero, disables the output, saves all collected data, and disconnects
both instruments -- it will not just quit and leave the magnet energized.
