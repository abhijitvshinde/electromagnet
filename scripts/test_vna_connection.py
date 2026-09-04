"""Standalone VNA-only connectivity test -- no GUI, no safety-limit setup.

Uses the exact same VNAController / profile / transport code the full
application uses, so a pass here means the real driver will work; it
does not reimplement anything separately.

Usage:
    python scripts/test_vna_connection.py --address GPIB0::3::INSTR
    python scripts/test_vna_connection.py --simulate   (no hardware needed)

Add --profile to pick a different profile name from vna_profiles.json
(default: KEYSIGHT_PNA_X_N5242B).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config.app_config import vna_profiles  # noqa: E402
from src.drivers.base_instrument import InstrumentCommunicationError, VisaTransport  # noqa: E402
from src.drivers.simulation import SimulatedVNATransport, SimulationEngine  # noqa: E402
from src.drivers.vna import VNAController, VNASweepConfig  # noqa: E402


def drain_error_queue(vna: VNAController, label: str) -> None:
    """Print every pending SCPI error the instrument has queued up."""
    print(f"--- Draining SYST:ERR? queue ({label}) ---")
    for _ in range(20):
        try:
            resp = vna._query_raw(vna.profile.command("get_error_queue"), critical=False).strip()
        except InstrumentCommunicationError as exc:
            print(f"  (could not query error queue: {exc})")
            return
        print(f"  {resp}")
        if resp.startswith("0") or resp == "":
            return


def main() -> int:
    parser = argparse.ArgumentParser(description="Test VNA GPIB connectivity in isolation.")
    parser.add_argument("--address", default="GPIB0::3::INSTR", help="VISA resource address")
    parser.add_argument(
        "--profile", default=None,
        help="Profile name from vna_profiles.json (default: GENERIC_PLACEHOLDER if --simulate, "
             "else KEYSIGHT_PNA_X_N5242B)",
    )
    parser.add_argument("--timeout", type=int, default=5000, help="Timeout in ms")
    parser.add_argument("--simulate", action="store_true", help="Use the software simulator instead of real hardware")
    parser.add_argument("--skip-sweep", action="store_true", help="Only test *IDN?, skip the real sweep/data test")
    parser.add_argument("--start-ghz", type=float, default=1.0, help="Sweep start frequency in GHz")
    parser.add_argument("--stop-ghz", type=float, default=2.0, help="Sweep stop frequency in GHz")
    parser.add_argument("--points", type=int, default=51, help="Number of sweep points")
    parser.add_argument("--poll-timeout", type=float, default=15.0, help="Seconds to poll *OPC? before giving up")
    args = parser.parse_args()

    if args.profile is None:
        args.profile = "GENERIC_PLACEHOLDER" if args.simulate else "KEYSIGHT_PNA_X_N5242B"

    profiles = vna_profiles()
    if args.profile not in profiles:
        print(f"Unknown profile {args.profile!r}. Available: {list(profiles.keys())}")
        return 1
    profile = profiles[args.profile]

    if args.simulate:
        print("=== SIMULATION MODE: no real hardware will be used ===")
        transport = SimulatedVNATransport(SimulationEngine(comm_delay_s=0.01))
    else:
        print(f"Connecting to real hardware at {args.address} using profile {args.profile!r}...")
        transport = VisaTransport(
            args.address, args.timeout, profile.write_termination, profile.read_termination
        )

    vna = VNAController(profile, transport)

    try:
        print("\n--- Step 1: open connection + *IDN? ---")
        idn = vna.open_connection()
        print(f"SUCCESS: {idn}")

        print("\n--- Step 2: test_communication() ---")
        ok = vna.test_communication()
        print("SUCCESS" if ok else "FAILED")

        if args.skip_sweep:
            print("\n--skip-sweep given, stopping here.")
            return 0

        print(
            f"\n--- Step 3: configure sweep ({args.start_ghz} GHz - {args.stop_ghz} GHz, "
            f"{args.points} points) ---"
        )
        config = VNASweepConfig(
            start_freq_hz=args.start_ghz * 1e9,
            stop_freq_hz=args.stop_ghz * 1e9,
            num_points=args.points,
            source_power_dbm=-10.0,
            if_bandwidth_hz=1000.0,
            sweep_time_s=None,
            averaging_enabled=False,
            averages=1,
            channel=1,
            trigger_mode="SINGLE",
        )
        vna.configure(config)
        print("Configured OK.")
        drain_error_queue(vna, "after configure")

        print("\n--- Step 4: trigger a sweep and wait for completion (verbose) ---")
        import time as _time

        ch = config.channel
        print(f"Sending trigger_single_sweep (channel={ch})...")
        vna._write_cmd("trigger_single_sweep", channel=ch)
        n_iterations = max(1, int(args.poll_timeout / 0.5))
        print(f"Trigger command sent. Now polling *OPC? every 0.5s for up to {args.poll_timeout:.0f}s, "
              f"printing every response:")
        start = _time.monotonic()
        completed = False
        for i in range(n_iterations):
            t0 = _time.monotonic()
            try:
                resp = vna._query_cmd("query_sweep_complete", channel=ch)
            except Exception as e:  # noqa: BLE001
                resp = f"<EXCEPTION: {type(e).__name__}: {e}>"
            elapsed_query = _time.monotonic() - t0
            elapsed_total = _time.monotonic() - start
            print(f"  [t={elapsed_total:5.2f}s] *OPC? -> {resp!r}  (query took {elapsed_query:.3f}s)")
            if resp.strip().lstrip("+").startswith("1"):
                completed = True
                break
            _time.sleep(0.5)
        print("Sweep completed." if completed else "Sweep did NOT complete within the diagnostic window.")
        drain_error_queue(vna, "after sweep trigger attempt")

        if not completed:
            print("\nSkipping Step 5 (data fetch) since the sweep never reported completion.")
            return 1

        print("\n--- Step 5: fetch S11 and S21 ---")
        s11 = vna.get_s_parameter("S11")
        s21 = vna.get_s_parameter("S21")
        print(f"S11: {len(s11.frequencies_hz)} points, "
              f"magnitude range {s11.magnitude_db.min():.2f} to {s11.magnitude_db.max():.2f} dB")
        print(f"S21: {len(s21.frequencies_hz)} points, "
              f"magnitude range {s21.magnitude_db.min():.2f} to {s21.magnitude_db.max():.2f} dB")

        print("\n=== ALL VNA TESTS PASSED ===")
        return 0

    except InstrumentCommunicationError as exc:
        print(f"\nFAILED: {exc}")
        return 1
    finally:
        try:
            vna.close_connection()
        except Exception:
            pass
        print("\nConnection closed.")


if __name__ == "__main__":
    sys.exit(main())
