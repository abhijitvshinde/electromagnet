"""Interactive, standalone power supply checker -- run this yourself from
a command prompt. Connects ONCE, then lets you type in as many currents
as you want to test, one at a time, showing setpoint/actual current/
actual voltage/output state/any instrument errors after each -- all
within the same GPIB session, so you can set the front panel (voltage
range and setpoint) right after connecting without the app or any other
script reconnecting and resetting it out from under you.

Usage (run in your own terminal, not through the app):
    python scripts/check_power_supply.py --max-current 0.5
    python scripts/check_power_supply.py --max-current 0.5 --address GPIB0::3::INSTR
    python scripts/check_power_supply.py --max-current 0.5 --simulate
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config.app_config import power_supply_profiles  # noqa: E402
from src.drivers.base_instrument import InstrumentCommunicationError, VisaTransport  # noqa: E402
from src.drivers.power_supply import PowerSupplyController  # noqa: E402
from src.drivers.simulation import SimulatedPowerSupplyTransport, SimulationEngine  # noqa: E402
from src.safety.safety_manager import SafetyManager, SafetyViolationError  # noqa: E402


def report(ps: PowerSupplyController, target: float) -> None:
    setpoint = ps.get_setpoint_current()
    actual_i = ps.get_actual_current()
    actual_v = ps.get_actual_voltage()
    output_state = ps.get_output_state()

    print(f"  Setpoint readback : {setpoint:.6f} A" if setpoint is not None else "  Setpoint readback : ?")
    print(f"  Actual current    : {actual_i:.6f} A" if actual_i is not None else "  Actual current    : (not supported)")
    print(f"  Actual voltage    : {actual_v:.6f} V" if actual_v is not None else "  Actual voltage    : (not supported)")
    print(f"  Output state      : {'ENABLED' if output_state else 'DISABLED' if output_state is False else '?'}")

    try:
        errors = ps.check_for_errors(context="this current")
        print("  Instrument errors : none")
    except InstrumentCommunicationError as exc:
        print(f"  Instrument errors : {exc}")

    if actual_i is not None and target != 0.0:
        tolerance = max(0.1 * abs(target), 0.002)
        if abs(actual_i - target) > tolerance:
            print(f"  -> MISMATCH: commanded {target:.6f} A but actual is {actual_i:.6f} A (not holding)")
        else:
            print("  -> OK: actual current matches commanded value")


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive power supply checker.")
    parser.add_argument("--address", default="GPIB0::3::INSTR")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--timeout", type=int, default=5000)
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--max-current", type=float, required=True, help="Mandatory safety limit, in amperes")
    args = parser.parse_args()

    if args.profile is None:
        args.profile = "GENERIC_PLACEHOLDER" if args.simulate else "AGILENT_E3634A"

    profile = power_supply_profiles()[args.profile]
    sm = SafetyManager()
    sm.set_max_current(args.max_current)

    if args.simulate:
        print("=== SIMULATION MODE ===")
        transport = SimulatedPowerSupplyTransport(SimulationEngine(comm_delay_s=0.0))
    else:
        transport = VisaTransport(args.address, args.timeout, profile.write_termination, profile.read_termination)

    ps = PowerSupplyController(profile, transport, sm)

    try:
        idn = ps.open_connection()
        print(f"Connected: {idn}")
        print(f"Mandatory safety limit: |I| <= {args.max_current} A\n")

        # Discard whatever's already in the error queue from before this
        # session -- so any error we report later is caused by something
        # WE do, not old backlog.
        try:
            ps.check_for_errors(context="pre-existing backlog, discarded")
        except InstrumentCommunicationError:
            pass

        ps.enable_output()
        print("Output enabled.\n")
        print(
            "IMPORTANT: this instrument resets its voltage setpoint (and possibly its\n"
            "voltage range) to ~0V every time a NEW session connects to it -- this is a\n"
            "confirmed, repeatable behavior of the instrument itself, not a bug in this\n"
            "script or the app. If you haven't already, go to the front panel NOW and set\n"
            "the correct voltage range and setpoint (e.g. 50V,4A range, ~10V) before\n"
            "testing currents below -- this script will NOT reconnect again until you quit,\n"
            "so whatever you set will stay in effect for every current you test here.\n"
        )
        input("Press Enter once the front panel is set up and you're ready to test currents...")
        print()

        while True:
            raw = input("Enter a current to test (A), or 'q' to quit and ramp to zero: ").strip()
            if raw.lower() in ("q", "quit", "exit"):
                break
            try:
                target = float(raw)
            except ValueError:
                print("  Not a number, try again.")
                continue

            try:
                ps.set_current(target, context="interactive check")
            except (SafetyViolationError, InstrumentCommunicationError) as exc:
                print(f"  FAILED to set current: {exc}")
                continue

            import time

            time.sleep(1.0)
            report(ps, target)
            print()

    except (InstrumentCommunicationError, SafetyViolationError) as exc:
        print(f"FAILED: {exc}")
        return 1
    finally:
        print("\nRamping to zero and disabling output...")
        try:
            if ps.transport.is_open:
                ps.set_current(0.0, context="cleanup")
                ps.disable_output()
        except (InstrumentCommunicationError, SafetyViolationError) as exc:
            print(f"WARNING: could not confirm safe cleanup: {exc}")
        try:
            ps.close_connection()
        except Exception:
            pass
        print("Connection closed.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
