# Electromagnet & VNA Control -- User Manual

Graphical user interface (GUI) guide for the electromagnet + Vector Network
Analyzer measurement station (electromagnet equipment **YP180829-188-2**).

Developed for the **WiSERL Lab** of **Dr. Binbin Yang** by **Abhijit Shinde**,
with help from **Shantu Ghose**. Department of Electrical and Computer
Engineering, North Carolina A&T State University, Greensboro, NC, USA.

> All screenshots in this manual were taken in **Simulation Mode** with
> made-up demo data (a synthetic calibration and a simulated sample), so you
> can follow every step without hardware. Your real numbers will differ.

---

## Contents

1. [What the application does](#1-what-the-application-does)
2. [Starting the application](#2-starting-the-application)
3. [Hardware connections](#3-hardware-connections)
   - [3.1 What connects to what](#31-what-connects-to-what)
   - [3.2 VNA rear panel](#32-vna-rear-panel-keysight-n5242b)
   - [3.3 Power supplies and GPIB adapter](#33-power-supplies-and-gpib-adapter)
   - [3.4 GPIB addresses and application settings](#34-gpib-addresses-and-application-settings)
   - [3.5 Connection checklist](#35-connection-checklist)
4. [Window layout and the tab order](#4-window-layout-and-the-tab-order)
5. [Quick start: a complete experiment in 10 steps](#5-quick-start-a-complete-experiment-in-10-steps)
6. [Tab reference](#6-tab-reference)
   - [Tab 1 -- Safety](#tab-1----safety)
   - [Tab 2 -- Instrument Connection](#tab-2----instrument-connection)
   - [Tab 3 -- Calibration](#tab-3----calibration)
   - [Tab 4 -- Field Sweep](#tab-4----field-sweep)
   - [Tab 5 -- VNA Settings](#tab-5----vna-settings)
   - [Tab 6 -- Data & Experiment](#tab-6----data--experiment)
   - [Tab 7 -- Live Measurement](#tab-7----live-measurement)
   - [Tab 8 -- Background Comparison](#tab-8----background-comparison)
   - [Tab 9 -- Event Log](#tab-9----event-log)
   - [Tab 10 -- About](#tab-10----about)
7. [Stopping, aborting and emergencies](#7-stopping-aborting-and-emergencies)
8. [Where your data goes](#8-where-your-data-goes)
9. [Troubleshooting](#9-troubleshooting)
10. [Known limitations](#10-known-limitations)
11. [Glossary](#11-glossary)

---

## 1. What the application does

The application drives the electromagnet's power supply and the VNA over
GPIB and automates the whole measurement:

1. It converts the **magnetic field** you ask for (in oersted, Oe) into the
   **coil current** (in amperes, A) needed to produce it, using a
   current-to-field **calibration** you load or create.
2. For every field point it ramps the current there safely, waits for it to
   settle, triggers a VNA sweep, and reads back **S11, S21, S12 and S22**
   (magnitude *and* phase).
3. It plots the results live, saves every point to disk the moment it is
   measured, and keeps color maps (magnitude vs. field and frequency) up to
   date automatically.
4. It can take a zero-field (0 A) **background** measurement and show or
   export your data with that background subtracted.

A **maximum-current limit** that you set first is enforced on every single
current command in the program. There is no override (see
[Tab 1](#tab-1----safety)).

---

## 2. Starting the application

From the project folder, with the project's virtual environment active:

```bash
python -m src.main
```

(If you were given a packaged `ElectromagnetVNAControl.exe`, just
double-click it. See `docs/PACKAGING.md` for how it is built.)

The application starts in **Simulation Mode**: instruments are simulated in
software, so nothing real is driven. This is the safe way to learn the
program or to check a sweep before running it on the magnet. To use the real
hardware, see [Hardware connections](#3-hardware-connections) and
[Tab 2](#tab-2----instrument-connection).

---

## 3. Hardware connections

Wire and power the instruments **before** you switch the application from
Simulation Mode to real hardware. This section shows the rear panels of the
instruments the application controls and how they connect to the PC.

### 3.1 What connects to what

The PC talks to both instruments over one **GPIB** bus, through a single
USB-GPIB adapter. Logically:

```
PC running this application
 |
 |  USB
 |
NI GPIB-USB-HS adapter
 |
 |  GPIB cables -- one shared bus, called GPIB0
 |
 +-- Agilent E3634A power supply      (address 3 by default in the app)
 |      '-- DC current leads --> electromagnet coil
 |
 +-- Keysight N5242B VNA              (address 16 by default in the app)
 |      '-- RF ports 1 and 2 (coax) --> device under test in the magnet gap
 |
 '-- Agilent E3631A power supply      (not used by the application)
```

This is drawn as a tree for clarity. Physically, GPIB cables are
**daisy-chained** from one instrument to the next, in any order -- the photos
below show how this rack is wired. The magnetic field itself is read with an
external gaussmeter during calibration; it is **not** connected to the PC (you
type the reading into the Calibration tab).

### 3.2 VNA rear panel (Keysight N5242B)

![Rear panel of the Keysight N5242B VNA with numbered callouts](images/hw_vna_rear.jpg)

| # | What it is | Notes |
|---|------------|-------|
| **1** (green) | **GPIB (1) TALKER/LISTENER**, with the GPIB cable (Agilent 10833B) plugged in | **This is the port the PC uses.** Keep both thumbscrews tight. |
| **2** (red) | **GPIB (0) CONTROLLER** -- empty | **Do not use.** This port lets the VNA control *other* instruments; it is not the port for controlling the VNA from a PC. |
| **3** (blue) | **LAN** port -- empty | No network cable is used; the application talks to the VNA over GPIB only. |
| **4** (amber) | **AC line power** | 100/120 V (50/60/400 Hz) or 220/240 V (50/60 Hz), 575 W maximum, per the rear-panel label. |

The VNA test ports (port 1 and port 2) are on its front panel; connect them
to the two ports of your device under test with coax, after doing a 2-port
calibration on the VNA. Leave the short jumper loops on the rear panel as
they are.

### 3.3 Power supplies and GPIB adapter

![Rear panels of the two Agilent power supplies and the NI GPIB-USB-HS adapter, with numbered callouts](images/hw_supplies_rear.jpg)

The left unit is the **Agilent E3631A** (not used by the application); the
right unit is the **Agilent E3634A**, the supply that drives the electromagnet.

| # | What it is | Notes |
|---|------------|-------|
| **1** (green) | **NI GPIB-USB-HS** adapter | Its attached black USB cable goes to the PC. Its GPIB connector plugs onto the E3631A's GPIB connector (callout 2). |
| **2** (blue) | **E3631A GPIB connector** | The adapter and the onward GPIB cable are stacked on this connector, so the bus passes through this instrument. It is on the bus even though the application does not use it, so its address must differ from the others'. |
| **3** (green) | **E3634A GPIB connector** | A GPIB cable is plugged in here. This is how the PC reaches the magnet supply. |
| **4** (red) | **E3634A rear OUTPUT terminal block** (+, -, sense) | Nothing is plugged into it in this photo, so the coil's current leads are presumably on the front-panel terminals -- check on the unit. |
| **5** (amber) | **AC line power** of the E3634A | Set the voltage selector to match your mains supply (100/115/230 V). |

> **Coil leads.** Never connect or disconnect the electromagnet's current leads
> while the output is enabled -- ramp the current to zero and make sure the
> output is off first (the coil is a large inductor). Positive current gives
> one field direction; the E3634A is single-quadrant, so reversing the field
> needs the leads or an external reversing switch (see
> [Known limitations](#10-known-limitations)).

### 3.4 GPIB addresses and application settings

| | Power supply | VNA |
|-|--------------|-----|
| Instrument | Agilent E3634A | Keysight N5242B |
| **Command profile** (Tab 2) | `AGILENT_E3634A` | `KEYSIGHT_PNA_X_N5242B` |
| **GPIB address** (Tab 2), default | `GPIB0::3::INSTR` | `GPIB0::16::INSTR` |
| Port used on the instrument | GPIB connector (rear) | GPIB (1) TALKER/LISTENER (rear) |
| Where the address is set | The instrument's own menu | The instrument's own menu |

The number between the `::` must equal the address configured **on the
instrument**, and every instrument on the bus (including the unused E3631A)
needs a **different** address. To see what the PC can detect, use NI MAX or the
command in `docs/GPIB_ADDRESS_GUIDE.md`.

### 3.5 Connection checklist

1. **Power everything off**, then connect the GPIB cables and tighten the
   thumbscrews. Plug the adapter's USB cable into the PC.
2. Make sure the VISA/GPIB driver for the adapter is installed on the PC
   (NI-VISA with NI-488.2 for the NI adapter). After step 3, NI MAX should list
   the instruments under `GPIB0`.
3. **Power on the instruments** and wait until the VNA has finished booting
   (it can take a few minutes).
4. Check each instrument's GPIB address (table above).
5. In the application, go to **Tab 2 -- Instrument Connection**: untick
   **Simulation Mode**, choose the two **Command profiles**, enter the
   addresses, and click **Connect** for each instrument.
6. Click **Test Communication** for each. The **IDN** line should name the
   right model (E3634A for the power supply, N5242B for the VNA). If the two
   look swapped, the addresses are swapped.
7. If **Connect** fails, see [Troubleshooting](#9-troubleshooting).

---

## 4. Window layout and the tab order

The window has ten tabs across the top. They are numbered in the order you
normally use them, left to right:

| # | Tab | Purpose |
|---|-----|---------|
| 1 | Safety | Set the mandatory maximum current; set voltage monitoring/compliance |
| 2 | Instrument Connection | Connect to the power supply and VNA (or simulation) |
| 3 | Calibration | Current -> field table (load, or build one point at a time) |
| 4 | Field Sweep | Define the fields to measure; check they are all reachable and safe |
| 5 | VNA Settings | Frequency range, power, bandwidth, which S-parameters |
| 6 | Data & Experiment | Name the experiment, create its folder, see the color maps |
| 7 | Live Measurement | Run the sweep; live plots; background measurement; stop buttons |
| 8 | Background Comparison | View the sweep raw, or with the 0 A background subtracted |
| 9 | Event Log | Running log of everything the program does |
| 10 | About | Credits |

**Tabs 2-8 are greyed out until you set the maximum current on tab 1.**
Safety, Event Log and About are always available.

![Safety tab before the limit is set: tabs 2-8 are locked](images/01a_safety_locked.png)

---

## 5. Quick start: a complete experiment in 10 steps

Use Simulation Mode first. Each step names the tab.

1. **Safety** -- enter the maximum allowable current (e.g. `2.0` A) and click
   **Set / Confirm Maximum Current**. The other tabs unlock.
2. **Instrument Connection** -- leave **Simulation Mode** checked (or
   uncheck it for real hardware, after wiring it as in
   [Hardware connections](#3-hardware-connections)) and click **Connect** for
   the Power Supply and for the VNA.
3. **Safety** (again) -- enter the **coil resistance**, click **Calculate
   from Max Current**, then **Set Monitoring Threshold & Compliance
   Voltage**.
4. **Calibration** -- load a calibration file (**Browse...** then **Load
   Calibration**) or build one ([details](#tab-3----calibration)).
5. **Field Sweep** -- choose mode, start, stop and step in oersted, then
   click **Build & Validate Sequence**. Every row must say `OK` and the
   summary must say **ALL VALID**.
6. **VNA Settings** -- set the frequency range and number of points, then
   click **Apply Configuration to VNA** (*after* the VNA is connected).
7. **Data & Experiment** -- type an experiment name, sample name and
   operator, then click **Create Experiment Folder**.
8. **Live Measurement** -- optionally click **Measure Background (0A)** to
   save a zero-field reference. (It is what the Background Comparison tab
   and the background-subtracted color maps use; you can take it before or
   after the sweep.)
9. **Live Measurement** -- click **Start Measurement** and confirm. Watch
   the four S-parameter plots fill in.
10. When the "Measurement Finished" box appears, your data is already in the
    experiment folder (path shown on the Data tab and in the Live status
    panel). The output is ramped to 0 A and disabled automatically. Open
    **Background Comparison** (tab 8) to view the sweep with and without the
    background subtracted.

---

## 6. Tab reference

### Tab 1 -- Safety

![Safety tab with a 2 A limit and the voltage threshold calculated](images/01b_safety.png)

**Purpose:** set the one number that protects the magnet and supply, and
configure voltage monitoring.

#### Maximum Allowable Current

| Control | What it does |
|---------|--------------|
| **Maximum current (A)** | The absolute ceiling. Every commanded current, in every tab, must not exceed this value in magnitude (positive or negative). |
| **Set / Confirm Maximum Current** | Stores the limit and unlocks tabs 2-8. If the power supply is already connected it also writes the same limit to the instrument's own current limit (best-effort). |

The status line shows `Current limit: ±2.0000 A`, or `NOT SET (mandatory)`
until you confirm one. A current command above the limit is *rejected*, not
clipped -- nothing is sent to the supply.

**You cannot change the limit while a process is active or the output is
enabled.** The fields grey out and the status line says why (e.g.
`Locked ... measurement_running`). To change it: stop the calibration or
measurement, click **Ramp Current to Zero**, and make sure the output is
disabled; then the limit can be edited again.

> The maximum current is **not remembered** between sessions on purpose --
> you re-enter it every time you start the program.

#### Voltage Safety Monitoring & Compliance

This box does two jobs with one number:

1. **Software monitoring ceiling.** While current is applied, the app reads
   the supply's real output voltage and triggers an *emergency stop* if it
   ever exceeds this value.
2. **The supply's compliance-voltage setpoint (`VOLT`).** A constant-
   voltage/constant-current supply can only deliver the current you
   command if its voltage setpoint is high enough to regulate on current.
   The same value is therefore sent to the instrument, so it behaves as a
   current source with the actual voltage floating below this ceiling.

It is **not** the instrument's own over-voltage protection (OVP); the app
never configures that.

| Control | What it does |
|---------|--------------|
| **Coil resistance (Ω)** | The electromagnet coil's DC resistance. Remembered between sessions. |
| **Margin (%)** | Head-room added on top of `I x R`. Remembered between sessions. |
| **Voltage monitoring threshold (V)** | The value that will be used. Filled by the button below, or type your own. |
| **Calculate from Max Current** | Computes `max current x coil resistance x (1 + margin/100)`. Example: 2 A x 5 Ω x 1.20 = **12 V**. Nothing is sent yet. |
| **Set Monitoring Threshold & Compliance Voltage** | Stores the threshold and, if the power supply is connected, sends it to the instrument as `VOLT`. A dialog confirms what happened. |

**Notes**

- A threshold of 0 V is refused: it would stop any current from flowing.
  This almost always means the coil resistance is still 0.
- Connecting a new GPIB session resets the supply's voltage setpoint. The
  app therefore **re-applies the threshold automatically every time the
  power supply connects**, as long as you have set a non-zero one.
- The threshold is not remembered across restarts. Recalculate and re-set it
  each session.

---

### Tab 2 -- Instrument Connection

![Instrument Connection tab with both simulated instruments connected](images/02_connection.png)

**Purpose:** connect the power supply and the VNA.

| Control | What it does |
|---------|--------------|
| **Simulation Mode** checkbox | Checked: connecting creates software-simulated instruments. A yellow banner is shown while it is on. Unchecked: connecting talks to real GPIB hardware. **Disconnect both instruments before changing this.** |
| **GPIB address** | The VISA resource string, e.g. `GPIB0::3::INSTR` (power supply) and `GPIB0::16::INSTR` (VNA). See `docs/GPIB_ADDRESS_GUIDE.md` to find yours. |
| **Timeout (ms)** | How long to wait for an instrument to reply (100-60000 ms). |
| **Command profile** | Which set of SCPI commands to use. |
| Status | Disconnected (grey), Connecting (amber), Connected (green), Busy (blue), Error (red). |
| **Connect / Disconnect** | Open or close the connection. |
| **Test Communication** | Sends an `*IDN?`-style query and reports OK/FAILED. Enabled only when connected. |
| **IDN** line | The instrument's identification string, shown after connecting. |
| **Clear Protection Trip** (power supply only) | Clears a latched over-voltage/over-current trip. Use it if the output stays off with no other explanation. |

**For real hardware**, pick the matching **Command profile**:

- Power supply: **`AGILENT_E3634A`**
- VNA: **`KEYSIGHT_PNA_X_N5242B`**

The default entry, `GENERIC_PLACEHOLDER`, is only a template for the
simulator and for people adding a new instrument -- it will not control real
hardware. (See `docs/SCPI_REPLACEMENT_GUIDE.md`.)

Once connected, the address, timeout and profile fields lock, because
changing them would not affect the already-open connection. **Disconnect and
reconnect** to apply a change.

On connecting the power supply, the app also sends your maximum current as the
instrument's hardware current limit and re-applies the compliance voltage
from tab 1 (see above).

For the physical cabling (which rear-panel connector to use, the GPIB adapter
and the addresses), see [Hardware connections](#3-hardware-connections).

---

### Tab 3 -- Calibration

![Calibration tab: a 9-point calibration loaded, with the I-vs-H plot](images/03_calibration.png)

**Purpose:** teach the program how much field a given current produces. The
Field Sweep tab uses this table to turn the fields you ask for into
currents.

The calibration is a table of (current, field) points. A good one:

- **covers the whole field range you plan to sweep** (a sweep point outside
  it is rejected unless you allow extrapolation);
- includes both an **increasing** and a **decreasing** current pass if your
  magnet shows hysteresis, so the sweep can use the right branch;
- has at least 2 points (4 or more if you want cubic interpolation).

You can fill the table in three ways.

#### Option 1: Load Existing Calibration

1. Click **Browse...** and choose a `.csv` or `.json` file.
2. Click **Load Calibration**.

The file needs a current column and a field column. Accepted column names
(case-insensitive): current -- `current_a`, `current`, `commanded_current_a`,
`i_a`; field -- `field_oe`, `field`, `h_oe`, `magnetic_field_oe`. Optional
columns: `actual_current_a` (or `actual_current`), `direction` (or
`sweep_direction`), and `notes`. A current that appears twice for the same
direction is reported as a duplicate and only the first is kept.

The table, the plot and the *issues* box fill in at once. Invalid points
(duplicates, missing values, a non-monotonic curve, currents above the
limit) are listed in the issues box and left out.

**Save Calibration** writes the current table to a CSV you choose. Do this
after building a calibration, so you can reload it next time.

#### Manually Enter Current/Field Point

For when you measure the field yourself with a gaussmeter or probe.

1. Type a **Current (A)** and click **Set Current**. The supply ramps to it
   (same safety checks as everything else) and the supply's real output
   voltage is shown in *Present voltage (actual)*.
2. Measure the field with your external instrument and type it into
   **Field (Oe)**.
3. Pick the **Direction** (`increasing`, `decreasing` or `unspecified`),
   optionally add **Notes**, and click **Add Point**.
4. Repeat. Select a table row and click **Delete Selected Point** to remove
   a bad one.

If the instrument's measured current is more than about 10% away from what
you commanded, a **Current Not Holding** warning appears -- see
[Troubleshooting](#9-troubleshooting).

> **The current stays applied after Add Point.** It is not ramped back to
> zero automatically. Click **Ramp Current to Zero** when you are done.

#### Option 2: Create New Calibration Manually (guided sequence)

The program steps through a list of currents and asks you for the field at
each one.

1. Choose **Mode**:
   - **Start/Stop/Step** -- fill **Start (A)**, **Stop (A)**, **Step (A)**.
   - **Custom List** -- type comma-separated currents in **Custom list**,
     e.g. `-1, -0.5, 0, 0.5, 1`.
2. Set **Direction label** (`increasing`/`decreasing`/`unspecified`) -- it
   is stored with every point.
3. Set **Stabilization time (s)** (settling wait after reaching each
   current), **Ramp step (A)** and **Ramp delay (s)** (how gently the
   current is stepped; see the note below).
4. Click **Start Calibration**. Every current is checked against the
   maximum first; if any exceeds it, nothing starts.
5. At each point the program ramps to the current, waits, and shows:
   *"Enter the measured magnetic field corresponding to the presently
   applied current."* Type the value in **Measured field (Oe)** and click
   **Confirm Field Value**. Only then does it advance.

| Button | Effect |
|--------|--------|
| **Confirm Field Value** | Records the field for this current and moves on. |
| **Repeat Current Point** | Re-applies the same current without saving a point (e.g. you mis-read). |
| **Previous Point** | Goes back one point. |
| **Pause / Resume** | Hold and continue the sequence. |
| **Abort** | Stop the sequence. |
| **Ramp Current to Zero** | Ramps the supply to 0 A using the ramp step/delay above. |
| **EMERGENCY STOP** | See [section 7](#7-stopping-aborting-and-emergencies). |

When the sequence ends, the program ramps back to 0 A and disables the
output.

> **Why ramp step / ramp delay matter.** The coil is an inductor. A sudden
> jump in current induces a voltage spike that can trip the supply's
> over-voltage protection and drop the output to zero. Small steps with a
> short delay avoid this. The defaults (0.01 A step, 0.2 s delay) come from
> `config/app_settings.json`.

#### Reading the lower half of the tab

- **Table** -- every point: commanded current, actual (measured) current,
  field, polarity, direction, timestamp.
- **Plot** -- field vs. current for all points.
- **Calibrated current/field range** -- the span the sweep can use without
  extrapolating.
- **Issues box** -- `No issues found.` or a list of problems.

> Save your calibration with **Save Calibration**. When you later click
> **Create Experiment Folder** the current table is also copied into that
> experiment's `calibration/` folder.

---

### Tab 4 -- Field Sweep

![Field Sweep tab: forward+reverse sweep, 22 points, all valid](images/04_sweep.png)

**Purpose:** decide which fields to measure and prove every one of them is
reachable and safe *before* anything is energised.

#### Sweep Configuration

| Control | Meaning |
|---------|---------|
| **Sweep mode** | `forward`: start -> stop. `reverse`: stop -> start. `forward_reverse`: up, then back down (the turn-around field is measured twice -- once in each direction). `custom`: exactly the list you type. |
| **Start field / Stop field / Step (Oe)** | The range and spacing. Ignored in `custom` mode. The stop value is always included. |
| **Custom list** | Comma-separated fields in Oe, used only in `custom` mode. |
| **Repeated sweeps** | Repeats the whole list this many times. |
| **Calibration direction** | Which calibration branch converts field to current. `auto`: forward sweep points use the *increasing* branch, reverse points the *decreasing* branch, custom points use all points. `increasing` / `decreasing`: force one branch. `average`: the mean of the two branches. `all`: use every point. |
| **Interpolation** | `linear`, or `cubic` (needs 4+ calibration points on the branch being used, otherwise linear is used). |
| **Allow extrapolation beyond calibrated range (curve fit)** | Off by default. When on, a field outside your calibrated range is converted with a quadratic curve fit instead of being rejected. |
| **Extrapolation margin (%)** | How far beyond the calibrated span extrapolation is allowed (default 20%). Further out is still rejected. |

> **Extrapolation warning.** Electromagnets saturate -- the field flattens at
> high current -- so a fitted point is less trustworthy the further it is
> from your measured data. Enabling it asks you to confirm. Extrapolated
> currents are still held to the maximum-current limit.

#### Build & Validate Sequence

Click it. The program converts every field to a current and fills the table:

| Column | Meaning |
|--------|---------|
| # | Position in the sequence |
| Field (Oe) | Requested field |
| Current (A) | Calculated current (`-` if it could not be computed) |
| Direction | `forward`, `reverse` or `custom` |
| In Calib. Range | Whether the field is inside the calibrated range |
| Extrapolated | `Yes` if it came from the curve fit (row shaded **yellow**) |
| Status | `OK`, or why the point is rejected (row shaded **red**) |

The summary line gives the **total points**, the largest positive and
negative current, the largest |I|, and either **ALL VALID** or **INVALID --
fix before starting**.

**Live Measurement will not start unless the sequence is ALL VALID.** To fix
a red row: change the field range, calibrate further, raise the limit on tab
1 (if it is safe to do so), or enable extrapolation -- then click **Build &
Validate Sequence** again.

> **The built sequence is a snapshot.** If you change the calibration or any
> sweep setting afterwards, click **Build & Validate Sequence** again.

---

### Tab 5 -- VNA Settings

![VNA Settings tab with the default 1-3 GHz, 401-point sweep](images/05_vna_settings.png)

**Purpose:** configure the VNA sweep.

| Control | Meaning |
|---------|---------|
| **Start frequency / Stop frequency** | Value plus a unit drop-down (Hz, kHz, MHz, GHz, THz). Changing the unit converts the number so the frequency does not change. |
| **Number of points** | 2 - 100001. The frequency spacing (kHz) is shown next to it. |
| **Source power (dBm)** | VNA output power, -60 to +30 dBm. Keep it low enough not to drive your sample nonlinear. |
| **IF bandwidth (Hz)** | Receiver bandwidth. Lower = less noise but a slower sweep. |
| **Sweep time (s, 0=auto)** | Fixed sweep time, or `0` to let the VNA choose. |
| **Averaging enabled / Number of averages** | VNA-side averaging for lower noise (slower). |
| **Channel** | VNA channel number (1-32). |
| **Trigger mode** | `SINGLE`, `CONTINUOUS` or `EXTERNAL`. Leave on `SINGLE` for normal use -- the app triggers one sweep per field point. |
| **Measure S11 / S21 / S12 / S22** | Which S-parameters to acquire (all on by default). Unchecked ones are not read, not plotted and not saved. |
| **Apply Configuration to VNA** | Stores the settings and, if the VNA is connected, pushes them to the instrument. |

> **Apply after connecting.** The settings only reach the instrument when you
> click **Apply Configuration to VNA** *while the VNA is connected*. If you
> click it before connecting you only get "Configuration saved. Connect the
> VNA to apply it." -- connect, then click it again. Click it again after any
> change (including toggling the S-parameter checkboxes) and after every
> reconnect. Without it, a measurement fails with "VNA has not been
> configured".

The app does **not** perform a VNA calibration. Do any calibration
(e.g. a full 2-port calibration, which you want for meaningful S12/S22) on
the instrument itself before the experiment.

---

### Tab 6 -- Data & Experiment

![Data & Experiment tab after a run: S11 and S21 color maps](images/06_data_after_run.png)

**Purpose:** name the experiment, create its folder, and see the field-vs-
frequency color maps build up.

#### Experiment Information

| Field | Meaning |
|-------|---------|
| **Experiment name** | Used in the folder name. |
| **Sample name** | Free text, saved to `metadata.json`. |
| **Operator name** | Free text, saved to `metadata.json`. |
| **Output folder** | Where experiment folders are created. Default is `experiments/` next to the program. **Browse...** to change. |
| **Sample description / Notes** | Free text, saved to `metadata.json`. |

Click **Create Experiment Folder**. This makes a new timestamped folder
(`YYYYMMDD_HHMMSS_<experiment name>`) with its sub-folders, writes
`metadata.json`, records the maximum current, and copies the current
calibration table into it. The full path is shown under the button.

**Do this before you start a measurement or a background measurement** --
they refuse to run without an experiment folder. Clicking the button again
starts a *new* folder (the old one is left untouched on disk) and resets
the color maps.

#### Color maps

Two square plots, **S11** and **S21**, show magnitude (dB) with *field on the
x-axis and frequency on the y-axis*. They **update by themselves** after each
field point is saved -- there is no button to press. Before any data exists
they read "no data yet".

Color maps for **all four** S-parameters (S11, S21, S12, S22) are saved to
the experiment's `plots/` folder as they update, even though only S11 and
S21 are shown on screen. The two maps shown here are always the raw
(uncorrected) ones.

Once a **background (0 A)** measurement exists for the experiment (see
[Tab 7](#tab-7----live-measurement)), the program also saves a
**background-subtracted** color map for each S-parameter, named
`<sparam>_colormap_background_subtracted.png`. Each row of the map has the
background magnitude subtracted from it, in dB. These files are rewritten
whenever a point is saved *and* whenever the background is saved, so it makes
no difference whether you measure the background before or after the sweep.
The background must have been measured with the same VNA sweep settings as
the sweep; if its frequency points do not line up, no subtracted map is
written.

---

### Tab 7 -- Live Measurement

![Live Measurement tab at the end of a 22-point forward+reverse sweep](images/07_live_measurement.png)

**Purpose:** run the experiment and watch it.

#### Live Status panel

| Item | Shows |
|------|-------|
| Power Supply / VNA | Connection state |
| Max current | The limit from tab 1 |
| Present current | Target current, and the measured one once a point completes |
| Present voltage (actual) | The supply's *real metered* output voltage (not the compliance setpoint, which a front panel may display instead) |
| Present field | Requested field of the current point |
| Direction | `forward`, `reverse` ... |
| VNA sweep status | The run state: `Running`, `Paused`, `Completed`, `Stopped` or `Error` |
| Output folder | The experiment folder (or a reminder to create one) |
| Elapsed | Time since Start Measurement |
| Progress bar | Points done / total |
| Red warning line | The last error message, if any |

#### The four plots

Top-left **S11**, top-right **S21**, bottom-left **S12**, bottom-right
**S22** -- all magnitude in dB versus frequency in GHz. Each point you
measure adds a trace, labelled `H=<field> Oe` in the legend beside the plot
(10 rows are visible; scroll the legend for more).

- Mouse: drag to pan, scroll wheel to zoom, right-click for the plot menu.
- **Overlay traces** -- checked: keep every trace so you can compare fields.
  Unchecked (default): show only the latest trace. Toggling it clears the
  plots.
- **Clear Plots** -- remove all traces from the screen (saved data is not
  affected).
- **Autoscale** -- reset the axes to fit.

Phase is **not** plotted, but it *is* saved for every S-parameter in the CSV
and HDF5 files.

#### Ramp & Stabilization

| Control | Meaning |
|---------|---------|
| **Ramp step (A)** | Size of each current step when moving between points. |
| **Ramp delay (s)** | Pause between steps. |
| **Stabilization (s)** | Extra wait after reaching each point's current, before the VNA sweep. |

Defaults come from `config/app_settings.json`. The coil's inductance means
smaller steps / longer delays are gentler; larger ones are faster but risk
tripping the supply (see tab 3).

#### Measure Background (0A)

Saves a reference measurement with **no applied field**, separate from the
sweep:

1. The program asks you to confirm.
2. It ramps the current to 0 A, enables the output, triggers one VNA sweep,
   and reads the enabled S-parameters.
3. It saves them to `background/background.csv` and as a `background` group
   in the HDF5 file.

It does **not** change the field-sweep data or the raw graphs and color maps.
It needs both instruments connected, an experiment folder, and a configured
VNA, and cannot be used while a sweep is running. The output is left enabled
at 0 A afterwards.

The background is what the **Background Comparison** tab (tab 8) and the
background-subtracted color maps are built from. Saving it refreshes both
immediately. Typical use: measure it once with the same VNA settings as the
sweep -- before or after the sweep, either order works.

#### Start Measurement

Click **Start Measurement**. The program first checks everything and, if any
condition fails, lists *all* the problems in one dialog:

- maximum current is set;
- power supply and VNA both connected;
- calibration present and valid;
- a field sweep has been built and is **ALL VALID**;
- an experiment folder has been created;
- the VNA has been configured;
- a compliance voltage has been sent to the power supply (needed whenever
  the sweep uses any non-zero current).

It then asks "N field point(s) will be measured ... Proceed?". After you
confirm, for each point in turn the program:

1. ramps the current to the point's value (in the ramp step/delay you set),
2. waits the stabilization time,
3. triggers one VNA sweep and reads S11/S21/S12/S22,
4. reads the actual current and voltage,
5. **writes the point to disk immediately** (per-point CSV, combined CSV,
   HDF5, cumulative graphs, color maps), and
6. adds the traces to the plots.

At the end it ramps to 0 A, disables the output, and shows
"Measurement Finished" with the number of points completed.

#### Run controls

| Button | Effect |
|--------|--------|
| **Pause** / **Resume** | Hold the sequence at the current point and continue later. The current stays applied while paused. |
| **Abort** | Stop the sequence now. The program ramps to zero, disables the output, and keeps all data measured so far. |
| **Ramp to Zero** | Ramp the supply to 0 A using the ramp step/delay above (e.g. after a pause). |
| **EMERGENCY STOP** | See [section 7](#7-stopping-aborting-and-emergencies). |

---

### Tab 8 -- Background Comparison

![Background Comparison tab with background subtraction switched on](images/08_background_comparison.png)

**Purpose:** compare your field sweep with and without the 0 A background
removed, without leaving the program.

The tab shows the same four plots as Live Measurement -- **S11, S21, S12 and
S22** magnitude (dB) versus frequency (GHz), one trace per field point, with a
legend beside each plot -- but built from the data already saved for the
current experiment. It only displays data: it never talks to the instruments
and never starts a measurement.

| Control | What it does |
|---------|--------------|
| **Subtract background (0A measurement)** | Unchecked: raw magnitudes, exactly as measured. Checked: the background trace is subtracted from every trace, frequency point by frequency point, in dB -- i.e. each trace is divided by the 0 A reference in linear terms. |
| Status line | Says what is being shown, or why you are seeing something else (see below). |

Status messages:

- *No field-sweep data measured yet for this experiment.* -- nothing to show.
- *Showing raw (uncorrected) data.* -- the box is unchecked.
- *Showing each trace minus the background (0A) measurement.* -- subtraction
  is active.
- *No background (0A) measurement saved for this experiment -- showing raw
  data instead ...* -- you ticked the box but no background exists yet. Go to
  Live Measurement, click **Measure Background (0A)**, then tick the box again.

Notes:

- The plots redraw automatically whenever a point or the background is saved,
  and whenever you tick or untick the box.
- Every trace is kept (overlay). There is no Clear button -- the tab always
  reflects the whole current experiment.
- A trace whose number of frequency points differs from the background's is
  shown uncorrected, even with the box ticked. Measure the background with the
  same VNA settings as the sweep.
- The tab uses the data held in memory for the experiment of the current
  session; it does not load earlier experiment folders from disk.
- These line plots are for viewing and are not exported. The
  background-subtracted *color maps* are -- see [Tab 6](#tab-6----data--experiment).

---

### Tab 9 -- Event Log

![Event Log tab during/after a run](images/09_event_log.png)

A read-only, live list of everything the program does: connections, every
current command, saved points, pauses/aborts/emergency stops, warnings and
errors, file saves, and shutdown.

**Clear Display** only empties this view. The complete log is always kept in
`logs/application.log` and, once you create an experiment, in that
experiment's `event_log.log`.

When something unexpected happens, this is the first place to look.

---

### Tab 10 -- About

![About tab](images/10_about.png)

Credits and a one-paragraph description of the tool. Always accessible, even
before the maximum current is set.

---

## 7. Stopping, aborting and emergencies

| Situation | Use | What happens |
|-----------|-----|--------------|
| You want to stop for a moment | **Pause** | Sequence holds; current stays applied. **Resume** continues. |
| You want to end the run but keep the data | **Abort** | The program ramps to zero, disables the output, and keeps all points saved so far. |
| You want the current off but stay in the program | **Ramp to Zero** / **Ramp Current to Zero** | Smooth ramp to 0 A. |
| Something is wrong *right now* | **EMERGENCY STOP** (red button, Calibration and Live tabs) | Blocks **all** further current commands, stops the running process, and attempts to disable the output. Confirm on the front panel and in the Event Log that the output is off. |
| Output voltage exceeds the monitoring threshold | (automatic) | The app triggers the same emergency stop on its own and tells you with a **VOLTAGE EMERGENCY STOP** dialog. |

**After an emergency stop, restart the application.** The Safety tab shows
`EMERGENCY STOP ACTIVE`, and the program rejects every current command until
it is restarted -- there is no on-screen button that clears it. Check the
Event Log and the instrument's front panel to confirm the output really is
off before you do anything else.

**Closing the window** while a process is running or the output is enabled
asks for confirmation, then stops the process, ramps to zero, disables the
output, saves all data and disconnects both instruments. It never just quits
with the magnet energised. If it could not *confirm* the shutdown (for
example GPIB communication was lost) it says so in the log -- then check the
instrument manually.

---

## 8. Where your data goes

Each experiment gets its own folder under the output folder:

```
experiments/20261015_144649_NiFe_film_FMR/
  metadata.json                  experiment/sample/operator info, max current,
                                 start and finish time, number of points
  event_log.log                  this experiment's log
  calibration/calibration.csv    copy of the calibration used
  raw/Field_Pos_0100p00_Oe_Current_Pos_0p357_A.csv
                                 one CSV per field point (name encodes the
                                 field and current), written immediately
  processed/combined_data.csv    every point so far, in one table
  processed/experiment_data.h5   HDF5: one group per point + "background"
  background/background.csv      the 0 A reference (if measured)
  graphs/s11_magnitude.png       cumulative overlay of all points, per
  graphs/s21_magnitude.png       S-parameter (magnitude only), refreshed
  graphs/s12_magnitude.png       after every point
  graphs/s22_magnitude.png
  plots/s11_colormap.png         field-vs-frequency color maps, all four
  plots/s21_colormap.png         S-parameters, refreshed after every point
  plots/s12_colormap.png
  plots/s22_colormap.png
  plots/s11_colormap_background_subtracted.png
  plots/s21_colormap_background_subtracted.png
  plots/s12_colormap_background_subtracted.png
  plots/s22_colormap_background_subtracted.png
                                 the same maps with the 0 A background
                                 subtracted (only once a background has
                                 been measured)
```

**CSV columns** (per-point, combined and background files). One row per
frequency point; a block of five columns for each S-parameter you enabled:

| Column | Meaning |
|--------|---------|
| `frequency_hz` | Frequency of the row |
| `requested_field_oe` | Field you asked for (not in the background file) |
| `current_a` | Commanded current |
| `actual_current_a`, `actual_voltage_v` | Measured current and voltage (blank if unavailable) |
| `direction`, `sweep_number` | `forward`/`reverse`/`custom`; repeat index (not in background) |
| `timestamp` | When the point was taken |
| `s11_real`, `s11_imag` | Complex S11 |
| `s11_magnitude` | Linear magnitude |
| `s11_magnitude_db` | Magnitude in dB |
| `s11_phase_deg` | Phase in degrees |
| `s21_*`, `s12_*`, `s22_*` | Same five columns for S21, S12, S22 |

**HDF5 layout:** each field point is a group `point_0000`, `point_0001`, ...
with the field, current, direction, etc. as attributes and datasets
`frequency_hz` and `<sparam>_real` / `<sparam>_imag`. The 0 A reference is a
group named `background`.

---

## 9. Troubleshooting

| Symptom / message | Likely cause and fix |
|-------------------|----------------------|
| Tabs 2-8 are greyed out | The maximum current has not been set. Go to tab 1 and click **Set / Confirm Maximum Current**. |
| **Cannot Change Maximum Current** / the limit field is greyed | A process is running or the output is enabled. Abort, **Ramp Current to Zero**, disable the output. |
| **Connection Failed** | Wrong GPIB address, instrument off (or the VNA still booting), cable/adapter problem, the VNA cable in **GPIB (0) CONTROLLER** instead of **GPIB (1) TALKER/LISTENER**, or the wrong **Command profile**. See [Hardware connections](#3-hardware-connections) and `docs/GPIB_ADDRESS_GUIDE.md`; try **Simulation Mode** to confirm the program itself works. |
| Connects, but nothing responds correctly on real hardware | The **Command profile** is still `GENERIC_PLACEHOLDER`. Choose `AGILENT_E3634A` / `KEYSIGHT_PNA_X_N5242B`, disconnect and reconnect. |
| **Invalid Voltage Value** (0 V) | Coil resistance is 0 or no maximum current is set. Fix, click **Calculate from Max Current**, then set again. |
| **Current Not Holding** | The commanded current is not appearing at the instrument. Usually a protection trip (OVP/OCP) or too-low compliance voltage. Click **Clear Protection Trip** on tab 2, and re-click **Set Monitoring Threshold & Compliance Voltage** on tab 1 with the supply connected. Use smaller ramp steps. |
| Output drops to ~0 V right after a large current step | The inductive spike tripped the supply's OVP. Reduce **Ramp step** / increase **Ramp delay**, then **Clear Protection Trip**. |
| **Cannot Start Measurement** | The dialog lists exactly what is missing (limit, connections, calibration, sweep, experiment folder, VNA configuration, compliance voltage). Fix each item. |
| Sweep table has red rows | A field is outside the calibrated range or needs more than the maximum current. See [Tab 4](#tab-4----field-sweep). |
| **VNA has not been configured** | Click **Apply Configuration to VNA** on tab 5 *while the VNA is connected* (see the note there). |
| **Timed out waiting for VNA sweep to complete** | The sweep takes longer than 30 s. Use fewer points, a higher IF bandwidth, or less averaging. |
| **No experiment folder created** | Tab 6 -> **Create Experiment Folder**. |
| Color maps say "no data yet" | No field point has been saved in this experiment folder yet. |
| Plots look empty after switching **Overlay** | Toggling overlay clears the plots; new points will appear as they are measured. |
| **EMERGENCY STOP ACTIVE** on tab 1 | Restart the application (see [section 7](#7-stopping-aborting-and-emergencies)). |
| Background Comparison says "No background (0A) measurement saved" | You ticked **Subtract background** but none exists for this experiment. On tab 7 click **Measure Background (0A)**, then tick the box again. |
| Background-subtracted color maps are missing from `plots/` | No background has been measured, or its frequency points differ from the sweep's. Measure it with the same VNA settings. |
| Something odd happened | Read tab 9 (Event Log) or `logs/application.log`. |

---

## 10. Known limitations

- **"Measurements per field (averaged)" on the Field Sweep tab is not yet
  used** by the measurement code -- changing it has no effect. Use the VNA's
  own **Averaging** on tab 5 instead.
- **The Agilent E3634A is a single-quadrant (unipolar) supply** -- it cannot
  source negative current by itself. A sweep through negative fields needs
  external polarity reversal (a relay or manual reversal of the coil
  leads). See `docs/SCPI_REPLACEMENT_GUIDE.md`.
- The calibration table is **not auto-saved** while you build it. Click
  **Save Calibration** (or create an experiment folder, which copies it).
- A measurement runs one VNA sweep per field point; the sweep must finish
  within 30 s.
- The maximum current and the voltage threshold are intentionally **not**
  remembered between sessions; coil resistance and margin are.
- **Background Comparison** (tab 8) shows the experiment of the current
  session from memory; it cannot open an earlier experiment folder. Its line
  plots are not exported -- only the background-subtracted color maps are.
  The background must be measured with the same VNA sweep settings as the
  sweep, otherwise traces are shown uncorrected.

---

## 11. Glossary

| Term | Meaning |
|------|---------|
| **Oe (oersted)** | Unit of magnetic field strength used throughout the app (1 Oe ≈ 79.58 A/m). |
| **A** | Ampere -- the coil current. |
| **S11, S22** | Reflection coefficients at VNA port 1 / port 2. |
| **S21, S12** | Transmission coefficients port 1 -> 2 / port 2 -> 1. |
| **dB** | Decibels; magnitude plots show 20·log10 of the linear magnitude of S. |
| **IFBW** | Intermediate-frequency bandwidth of the VNA receiver. |
| **Compliance voltage** | The voltage ceiling of a constant-current supply; the supply raises its voltage up to this limit to push the commanded current through the coil. |
| **OVP / OCP** | The instrument's over-voltage / over-current protection circuits. |
| **Background** | A measurement taken at 0 A (no applied field), used as a reference. |
| **Background subtraction** | Subtracting the background's magnitude (dB) from each field point's magnitude (dB) at every frequency, which removes whatever the setup does at zero field and leaves the field-dependent part. |
| **Hysteresis** | The field produced at a given current depends on whether the current is increasing or decreasing; hence separate increasing/decreasing calibration branches. |
| **Simulation Mode** | Software-simulated instruments; no hardware is driven. |
