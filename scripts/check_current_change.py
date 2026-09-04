"""Minimal script: connect once, set a series of currents, read back the
actual current after each, and print whether it actually held. Uses the
same real driver/safety code as the app -- no GUI involved -- to isolate
whether Set Current genuinely works when nothing else (reconnects, other
tabs, background timers) is in the picture.

Usage:
    python scripts/check_current_change.py --max-current 0.5
    python scripts/check_current_change.py --max-current 0.5 --currents 0.05 0.1 0.2 0.1 0
    python scripts/check_current_change.py --simulate --max-current 0.5
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
from src.safety.safety_manager import SafetyManager, SafetyViolationError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Set a series of currents and verify each one actually holds.")
    parser.add_argument("--address", default="GPIB0::3::INSTR")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--timeout", type=int, default=5000)
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--max-current", type=float, required=True, help="Mandatory safety limit, in amperes")
    parser.add_argument(
        "--currents", type=float, nargs="+", default=[0.05, 0.1, 0.2, 0.1, 0.0],
        help="Sequence of currents (A) to set, one after another",
    )
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds to wait before reading back each one")
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
        ps.enable_output()

        print(f"\n{'Target (A)':>12} | {'Setpoint RB (A)':>16} | {'Actual (A)':>12} | Result")
        print("-" * 62)
        all_ok = True
        for target in args.currents:
            ps.set_current(target, context="check script")
            time.sleep(args.delay)
            setpoint = ps.get_setpoint_current()
            actual = ps.get_actual_current()

            if actual is None:
                result = "NO READBACK SUPPORT"
            else:
                tolerance = max(0.1 * abs(target), 0.002)
                result = "OK" if abs(actual - target) <= tolerance else "MISMATCH <-- current not holding"
                if result != "OK":
                    all_ok = False

            setpoint_str = f"{setpoint:.6f}" if setpoint is not None else "?"
            actual_str = f"{actual:.6f}" if actual is not None else "?"
            print(f"{target:12.6f} | {setpoint_str:>16} | {actual_str:>12} | {result}")

        print()
        print("ALL POINTS HELD CORRECTLY" if all_ok else "AT LEAST ONE POINT DID NOT HOLD -- see MISMATCH rows above")
        return 0 if all_ok else 1

    except (InstrumentCommunicationError, SafetyViolationError) as exc:
        print(f"FAILED: {exc}")
        return 1
    finally:
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


if __name__ == "__main__":
    sys.exit(main())
