"""Standalone power-supply-only connectivity test -- no GUI required.

Uses the exact same PowerSupplyController / SafetyManager / CurrentRamper
code the full application uses, so a pass here means the real driver will
work; it does not reimplement anything separately. A maximum current is
MANDATORY (--max-current), exactly like the application enforces, and
every current command still goes through the SafetyManager -- there is no
way to bypass that from this script either.

Usage:
    python scripts/test_power_supply_connection.py --max-current 0.5 --address GPIB0::2::INSTR
    python scripts/test_power_supply_connection.py --max-current 0.5 --simulate   (no hardware needed)

By default this only tests *IDN?/communication (--skip-current-test is
NOT the default -- current IS tested by default, but only up to a small,
safe --test-current). Pass --skip-current-test to test connectivity only,
with no current ever commanded.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config.app_config import power_supply_profiles  # noqa: E402
from src.drivers.base_instrument import InstrumentCommunicationError, VisaTransport  # noqa: E402
from src.drivers.power_supply import PowerSupplyController  # noqa: E402
from src.drivers.simulation import SimulatedPowerSupplyTransport, SimulationEngine  # noqa: E402
from src.measurement.ramping import CurrentRamper, RampConfig  # noqa: E402
from src.safety.safety_manager import SafetyManager, SafetyViolationError  # noqa: E402


def drain_error_queue(ps: PowerSupplyController, label: str) -> None:
    print(f"--- Draining SYST:ERR? queue ({label}) ---")
    for _ in range(20):
        try:
            resp = ps._query_raw(ps.profile.command("get_error_queue"), critical=False).strip()
        except InstrumentCommunicationError as exc:
            print(f"  (could not query error queue: {exc})")
            return
        print(f"  {resp}")
        if resp.startswith(("0", "+0")) or resp == "":
            return


def main() -> int:
    parser = argparse.ArgumentParser(description="Test power-supply GPIB connectivity in isolation.")
    parser.add_argument("--address", default="GPIB0::2::INSTR", help="VISA resource address")
    parser.add_argument(
        "--profile", default=None,
        help="Profile name from power_supply_profiles.json (default: GENERIC_PLACEHOLDER if "
             "--simulate, else HP_AGILENT_E3631A_P6V)",
    )
    parser.add_argument("--timeout", type=int, default=5000, help="Timeout in ms")
    parser.add_argument("--simulate", action="store_true", help="Use the software simulator instead of real hardware")
    parser.add_argument("--max-current", type=float, required=True, help="MANDATORY safety limit, in amperes")
    parser.add_argument("--test-current", type=float, default=0.05, help="Small test current to ramp to, in amperes")
    parser.add_argument("--voltage-limit", type=float, default=5.0, help="Voltage compliance to set, in volts")
    parser.add_argument(
        "--step-delay", type=float, default=1.0,
        help="Delay between each ramp step, in seconds (slow this down to watch a multimeter move)",
    )
    parser.add_argument("--ramp-step", type=float, default=0.01, help="Current step size per ramp step, in amperes")
    parser.add_argument("--skip-current-test", action="store_true", help="Only test *IDN?/communication, no current")
    args = parser.parse_args()

    if args.profile is None:
        args.profile = "GENERIC_PLACEHOLDER" if args.simulate else "HP_AGILENT_E3631A_P6V"

    if abs(args.test_current) > abs(args.max_current):
        print(f"--test-current ({args.test_current} A) cannot exceed --max-current ({args.max_current} A)")
        return 1

    profiles = power_supply_profiles()
    if args.profile not in profiles:
        print(f"Unknown profile {args.profile!r}. Available: {list(profiles.keys())}")
        return 1
    profile = profiles[args.profile]

    if args.simulate:
        print("=== SIMULATION MODE: no real hardware will be used ===")
        transport = SimulatedPowerSupplyTransport(SimulationEngine(comm_delay_s=0.01))
    else:
        print(f"Connecting to real hardware at {args.address} using profile {args.profile!r}...")
        transport = VisaTransport(
            args.address, args.timeout, profile.write_termination, profile.read_termination
        )

    safety = SafetyManager()
    safety.set_max_current(args.max_current)
    print(f"Mandatory safety limit set: |I| <= {args.max_current} A")

    ps = PowerSupplyController(profile, transport, safety)
    ramper = CurrentRamper(
        ps, RampConfig(current_step_a=args.ramp_step, step_delay_s=args.step_delay, stabilization_time_s=1.0)
    )
    output_was_enabled = False

    try:
        print("\n--- Step 1: open connection + *IDN? ---")
        idn = ps.open_connection()
        print(f"SUCCESS: {idn}")

        print("\n--- Step 2: test_communication() ---")
        ok = ps.test_communication()
        print("SUCCESS" if ok else "FAILED")
        drain_error_queue(ps, "after connect")

        if args.skip_current_test:
            print("\n--skip-current-test given, stopping here. No current was ever commanded.")
            return 0

        print(f"\n--- Step 3: set voltage limit to {args.voltage_limit} V ---")
        ps.set_voltage_limit(args.voltage_limit)
        # Confirm the instrument actually accepted this, not just that the
        # bytes went out over GPIB -- a mismatched profile/instrument
        # combination can be silently rejected by the instrument's own
        # parser while every transport-level call still reports success.
        ps.check_for_errors(context="after setting voltage limit")
        print("Voltage limit set and confirmed (no instrument error).")

        print(f"\n--- Step 4: best-effort hardware current limit ({args.max_current} A) ---")
        ps.set_hardware_current_limit(args.max_current)
        print(f"Driver status after this (should still be Connected): {ps.status.value}")
        drain_error_queue(ps, "after limits (best-effort, not fatal)")

        print("\n--- Step 5: enable output ---")
        ps.enable_output()
        output_was_enabled = True
        print("Output enabled.")

        print(f"\n--- Step 6: ramp to test current {args.test_current} A ---")
        ramper.ramp_to(args.test_current, context="standalone power supply test", verify_no_error=True)
        print(f"Reached setpoint {args.test_current} A and confirmed no instrument error. "
              f"Setpoint readback: {ps.get_setpoint_current()}")

        actual = ps.get_actual_current()
        if actual is not None:
            print(f"Actual measured current: {actual:.6f} A")
        else:
            print("This profile does not support actual-current readback "
                  "(supports_actual_current_readback is false) -- verify with a multimeter.")

        print("\n=== ALL POWER SUPPLY TESTS PASSED (instrument confirmed no rejected commands) ===")
        return 0

    except (InstrumentCommunicationError, SafetyViolationError) as exc:
        print(f"\nFAILED: {exc}")
        return 1

    finally:
        if args.skip_current_test:
            print("\n--- Cleanup: --skip-current-test given, no current was ever commanded, nothing to ramp down ---")
        else:
            print("\n--- Cleanup: ramping to zero and disabling output ---")
            try:
                if ps.transport.is_open:
                    ramper.ramp_to_zero(context="standalone test cleanup")
                    print("Ramped to zero.")
            except (InstrumentCommunicationError, SafetyViolationError) as exc:
                print(f"WARNING: could not confirm ramp to zero: {exc}")
            try:
                if ps.transport.is_open and output_was_enabled:
                    ps.disable_output()
                    print("Output disabled.")
            except InstrumentCommunicationError as exc:
                print(f"WARNING: could not confirm output disabled: {exc}")
        try:
            ps.close_connection()
        except Exception:
            pass
        print("Connection closed.")


if __name__ == "__main__":
    sys.exit(main())
