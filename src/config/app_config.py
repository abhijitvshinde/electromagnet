"""Configuration loading for the electromagnet/VNA control application.

All instrument-specific SCPI commands live in JSON profile files under
``config/``. This module only loads and validates that data; it never
hard-codes a command string itself, so swapping instrument models means
editing JSON, not Python.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@dataclass
class InstrumentProfile:
    """A named, swappable set of SCPI commands for one instrument."""

    name: str
    manufacturer: str
    model: str
    description: str
    commands: dict[str, str]
    termination: str = "\n"
    write_termination: str = "\n"
    read_termination: str = "\n"
    extra: dict[str, Any] = field(default_factory=dict)

    def command(self, key: str, **kwargs: Any) -> str:
        """Format and return the raw SCPI string for ``key``.

        Raises KeyError if the profile has no such command defined, so
        missing placeholders fail loudly instead of silently sending junk.
        """
        template = self.commands[key]
        return template.format(**kwargs) if kwargs else template


def load_profiles(json_path: Path) -> dict[str, InstrumentProfile]:
    data = _load_json(json_path)
    profiles: dict[str, InstrumentProfile] = {}
    for name, p in data.get("profiles", {}).items():
        profiles[name] = InstrumentProfile(
            name=name,
            manufacturer=p.get("manufacturer", "UNKNOWN"),
            model=p.get("model", "UNKNOWN"),
            description=p.get("description", ""),
            commands=p.get("commands", {}),
            termination=p.get("termination", "\n"),
            write_termination=p.get("write_termination", "\n"),
            read_termination=p.get("read_termination", "\n"),
            extra={k: v for k, v in p.items() if k not in (
                "manufacturer", "model", "description", "commands",
                "termination", "write_termination", "read_termination",
            )},
        )
    return profiles


def active_profile_name(json_path: Path) -> str:
    data = _load_json(json_path)
    return data.get("active_profile", next(iter(data.get("profiles", {}))))


@dataclass
class AppSettings:
    electromagnet_equipment_number: str
    simulation_mode_default: bool
    power_supply_gpib_address: str
    vna_gpib_address: str
    gpib_timeout_ms: int
    default_current_step_a: float
    default_step_delay_s: float
    default_stabilization_time_s: float
    default_current_tolerance_a: float
    vna_defaults: dict[str, Any]
    data_output_root: str

    @classmethod
    def load(cls, json_path: Path | None = None) -> "AppSettings":
        path = json_path or (CONFIG_DIR / "app_settings.json")
        data = _load_json(path)
        gpib = data.get("gpib", {})
        ramping = data.get("ramping", {})
        return cls(
            electromagnet_equipment_number=data.get("electromagnet_equipment_number", "UNKNOWN"),
            simulation_mode_default=bool(data.get("simulation_mode_default", True)),
            power_supply_gpib_address=gpib.get("power_supply_address", "GPIB0::5::INSTR"),
            vna_gpib_address=gpib.get("vna_address", "GPIB0::16::INSTR"),
            gpib_timeout_ms=int(gpib.get("timeout_ms", 5000)),
            default_current_step_a=float(ramping.get("default_current_step_a", 0.05)),
            default_step_delay_s=float(ramping.get("default_step_delay_s", 0.2)),
            default_stabilization_time_s=float(ramping.get("default_stabilization_time_s", 1.0)),
            default_current_tolerance_a=float(ramping.get("default_current_tolerance_a", 0.005)),
            vna_defaults=data.get("vna_defaults", {}),
            data_output_root=data.get("data_output_root", "./experiments"),
        )


def power_supply_profiles() -> dict[str, InstrumentProfile]:
    return load_profiles(CONFIG_DIR / "power_supply_profiles.json")


def vna_profiles() -> dict[str, InstrumentProfile]:
    return load_profiles(CONFIG_DIR / "vna_profiles.json")


def default_power_supply_profile() -> InstrumentProfile:
    name = active_profile_name(CONFIG_DIR / "power_supply_profiles.json")
    return power_supply_profiles()[name]


def default_vna_profile() -> InstrumentProfile:
    name = active_profile_name(CONFIG_DIR / "vna_profiles.json")
    return vna_profiles()[name]


STATE_DIR = PROJECT_ROOT / "state"
_USER_STATE_PATH = STATE_DIR / "user_state.json"


@dataclass
class UserState:
    """Small local preferences that are safe to remember across app
    restarts -- physical/setup values that don't change between sessions.

    Deliberately excludes anything safety-gated (the mandatory max-current
    limit, in particular): that is re-confirmed by the user every session
    on purpose, not silently restored, so it stays out of this file.
    """

    coil_resistance_ohms: float = 0.0
    voltage_margin_percent: float = 20.0

    @classmethod
    def load(cls) -> "UserState":
        try:
            data = _load_json(_USER_STATE_PATH)
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()
        return cls(
            coil_resistance_ohms=float(data.get("coil_resistance_ohms", 0.0)),
            voltage_margin_percent=float(data.get("voltage_margin_percent", 20.0)),
        )

    def save(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(_USER_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "coil_resistance_ohms": self.coil_resistance_ohms,
                    "voltage_margin_percent": self.voltage_margin_percent,
                },
                f, indent=2,
            )
