# Identifying GPIB Addresses

A VISA resource string for GPIB normally looks like:

```
GPIB0::<primary address>::INSTR
```

for example `GPIB0::5::INSTR` (power supply at primary address 5) or
`GPIB0::16::INSTR` (VNA at primary address 16). `GPIB0` is the GPIB
board/controller index (almost always `0` for a single GPIB interface
card or USB-GPIB adapter).

## Option A: List resources from Python (works cross-platform)

With the project's virtual environment active:

```bash
python -c "import pyvisa; print(pyvisa.ResourceManager().list_resources())"
```

This prints every VISA resource the installed backend can currently see,
including all connected GPIB instruments. Match each string to an
instrument by connecting one device at a time, or by sending `*IDN?` to
each candidate address with the **Test Communication** button after
entering it on the Instrument Connection tab.

## Option B: NI MAX (National Instruments Measurement & Automation Explorer)

If you use the NI-VISA backend on Windows:

1. Install NI-VISA / NI-488.2 (from ni.com) if not already installed.
2. Open **NI MAX**.
3. Expand **Devices and Interfaces -> GPIB0 (or your GPIB board)**.
4. Each listed instrument shows its primary address and VISA resource
   string; select one and use **VISA Test Panel** to send `*IDN?`
   directly and confirm you've got the right device before entering
   the address into the application.

## Option C: The instrument's own front panel

Most GPIB instruments display or let you set their GPIB primary address
from a front-panel menu (often under "Interface", "Remote", or "I/O
Config"). Whatever address is configured there is the number that goes
between the `::` in the VISA resource string.

## Notes

- Every instrument on the same GPIB bus must have a **unique** primary
  address.
- If you have more than one GPIB controller/board in the PC, the board
  index (`GPIB0`, `GPIB1`, ...) matters too -- check NI MAX or your
  backend's resource list to confirm which board an instrument is on.
- USB-GPIB or Ethernet-GPIB adapters also resolve to a `GPIBn::...`
  resource string once their driver is installed; the process above
  still applies.
- Simulation Mode does not require any of this -- it needs no VISA
  backend or physical hardware at all.
