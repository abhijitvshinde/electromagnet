# Replacing the Placeholder SCPI Commands

## Real profiles already included

Two real (non-placeholder) profiles are included and selectable from the
Instrument Connection tab's **Command profile** dropdown:

- **`AGILENT_E3634A`** (power supply) in `config/power_supply_profiles.json`
- **`KEYSIGHT_PNA_X_N5242B`** (VNA) in `config/vna_profiles.json`

Both use standard, well-documented SCPI command sets for these
instrument families, entered with high confidence -- but neither has
been tested against a physical unit by this application's author, so
read the `notes` / `current_polarity_convention` / `data_format.notes`
fields inside each profile in the JSON before an unattended run. Two
things in particular:

- **E3634A is a single-quadrant (unipolar) supply** -- it cannot source
  negative current by itself. A bipolar/reversible sweep needs external
  polarity-reversal hardware; see the profile's `current_polarity_convention`.
- **PNA-X measurement creation**: `select_measurement_s11`/`s21` call
  `CALC:PAR:DEF:EXT` every time, which may error on some firmware
  revisions if the measurement name already exists -- see the profile's
  `data_format.notes` for the fallback (`CALC:PAR:MOD:EXT`, or create
  the measurement once manually).

If you have a different instrument (or these two don't match your exact
firmware revision), use `GENERIC_PLACEHOLDER` as a starting template and
follow the rest of this guide.

## How the placeholder profiles work

This application ships with **no invented instrument-specific SCPI
commands** in its generic template. Every command the power supply and
VNA drivers send is read from a JSON profile at runtime:

- `config/power_supply_profiles.json`
- `config/vna_profiles.json`

Every command string in those files currently starts with
`PLACEHOLDER_...` (except the standard IEEE-488.2 common commands
`*IDN?`, `*RST`, `*CLS`, and `SYST:ERR?`, which are part of the SCPI
standard itself and not instrument-specific).

You must replace these placeholders with the exact commands documented
in your instruments' programming manuals before connecting to real
hardware. **Simulation Mode does not need any of this** -- it recognizes
the placeholder vocabulary directly, which is why it works out of the box.

## Step 1: Find your instrument's programming manual

Locate the SCPI/GPIB programming reference for:
1. Your electromagnet power supply
2. Your Vector Network Analyzer

These are usually available from the manufacturer's website (search for
"<model> programming guide" or "<model> SCPI command reference").

## Step 2: Edit `config/power_supply_profiles.json`

Under `profiles.GENERIC_PLACEHOLDER.commands`, replace each value:

| Key | Purpose | Example replacement (illustrative only) |
|---|---|---|
| `set_current` | Command the output current, in amperes | `"CURR {value:.6f}"` |
| `get_current_setpoint` | Query the programmed setpoint | `"CURR?"` |
| `get_current_actual` | Query the measured/actual current | `"MEAS:CURR?"` |
| `set_current_limit` | Set the instrument's own hardware current limit | `"CURR:LIM {value:.6f}"` |
| `set_voltage_limit` | Set a voltage compliance limit | `"VOLT:LIM {value:.6f}"` |
| `output_on` / `output_off` | Enable/disable the output | `"OUTP ON"` / `"OUTP OFF"` |
| `get_output_state` | Query whether the output is enabled | `"OUTP?"` |

Also set:
- `manufacturer`, `model`
- `termination` / `write_termination` / `read_termination` (often `"\n"`, sometimes `"\r\n"`)
- `supports_actual_current_readback` (`true` only if your supply can report a measured current)
- `current_polarity_convention` (document what positive/negative means physically for your magnet)

`{value:.6f}` etc. are Python format placeholders -- keep the `{value}`
(or `{points}`, `{channel}`, ...) placeholder names used by
`src/drivers/power_supply.py` / `src/drivers/vna.py` (see the `_write_cmd`
/ `_query_cmd` calls) so the formatting keeps working; only change the
literal command text around them.

## Step 3: Edit `config/vna_profiles.json`

Same idea, for the commands under `profiles.GENERIC_PLACEHOLDER.commands`:
`set_start_freq`, `set_stop_freq`, `set_num_points`, `set_source_power`,
`set_if_bandwidth`, `set_sweep_time`, `set_averaging_state`,
`set_averaging_count`, `clear_averaging`, `set_trigger_mode`,
`trigger_single_sweep`, `query_sweep_complete`, `select_measurement_s11`,
`select_measurement_s21`, `get_sdata_s11`, `get_sdata_s21`.

### Data format

`VNAController._parse_ascii_vector` (in `src/drivers/vna.py`) assumes the
common ASCII, comma-separated, interleaved real/imaginary format many
VNAs return for an SDATA-style query (`re0,im0,re1,im1,...`). If your
instrument instead returns an **IEEE-488.2 binary block**
(`#<n><len><bytes>`), you must:

1. Set `"supports_binary_transfer": true` and describe the byte order in
   `data_format.notes` inside `vna_profiles.json`.
2. Replace `_parse_ascii_vector` (or add a binary-aware branch) in
   `src/drivers/vna.py` to decode the block into a `numpy` array of
   interleaved real/imaginary `float64`/`float32` values, matching your
   instrument's documented format.

## Step 4: Set default GPIB addresses (optional convenience)

Edit `config/app_settings.json` -> `gpib.power_supply_address` /
`gpib.vna_address` to your instruments' actual VISA resource strings
(see `docs/GPIB_ADDRESS_GUIDE.md`), or just type them into the
Instrument Connection tab each time.

## Step 5: Test with `Test Communication`

With Simulation Mode **unchecked**, use each instrument's **Connect**
button, then **Test Communication**, which sends `*IDN?` and reports the
response. If it fails, check the address, termination characters, and
timeout before touching anything else.

## Do not skip validation

After replacing commands, re-run the unit tests (`pytest`) and the
`scripts/generate_sample_data.py` simulation to confirm nothing else in
the application broke, then validate manually against the real
instrument with the current limit set very low (e.g. 0.05 A) before
raising it.
