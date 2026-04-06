# SPDX-License-Identifier: GPL-3.0-or-later
"""MkDocs macros hook — exposes integration data to doc templates."""

import importlib.util
import re
from pathlib import Path
import yaml

_ROOT = Path(__file__).parent


def _load_const() -> object:
    """Load custom_components/sunriser/const.py without triggering HA imports."""
    spec = importlib.util.spec_from_file_location(
        "sunriser_const",
        _ROOT / "custom_components" / "sunriser" / "const.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parse_int(name: str, text: str, default: int) -> int:
    """Extract a named integer constant from Python source via regex."""
    m = re.search(rf"^\s+{re.escape(name)}\s*=\s*(\d+)", text, re.MULTILINE)
    return int(m.group(1)) if m else default


def _format_duration(seconds: int) -> str:
    """Return a human-readable duration string, switching to minutes when < 1 hour."""
    if seconds < 3600:
        mins = seconds // 60
        return f"~{mins} minute{'s' if mins != 1 else ''}"
    total_hours = seconds / 3600
    if total_hours == int(total_hours):
        h = int(total_hours)
        return f"~{h} hour{'s' if h != 1 else ''}"
    return f"~{total_hours:.1f} hours"


def define_env(env):
    const = _load_const()

    coord_text = (
        _ROOT / "custom_components" / "sunriser" / "coordinator.py"
    ).read_text()

    pwm_config_interval = _parse_int("_PWM_CONFIG_INTERVAL", coord_text, 240)
    failure_grace = _parse_int("_FAILURE_GRACE", coord_text, 3)
    # init_steps: how many ticks before entities appear (_init_step >= N)
    m = re.search(r"return self\._init_step >= (\d+)", coord_text)
    init_steps = int(m.group(1)) if m else 4

    # Weather poll interval: length of _REFRESH_SEQUENCE tuple
    m = re.search(r"_REFRESH_SEQUENCE\s*=\s*\(([^)]+)\)", coord_text)
    weather_interval_ticks = len(m.group(1).split(",")) if m else 5

    scan_interval = const.DEFAULT_SCAN_INTERVAL
    init_minutes = round(init_steps * scan_interval / 60)
    weather_interval_mins = weather_interval_ticks * scan_interval / 60

    services_path = _ROOT / "custom_components" / "sunriser" / "services.yaml"
    with open(services_path) as f:
        env.variables["services"] = yaml.safe_load(f)

    env.variables["cfg"] = {
        "default_port": const.DEFAULT_PORT,
        "default_scan_interval": scan_interval,
        "default_reboot_time": const.DEFAULT_REBOOT_TIME,
        "scan_interval_min": 5,
        "scan_interval_max": 3600,
        "pwm_max": const.PWM_MAX,
        "init_steps": init_steps,
        "init_minutes": init_minutes,
        "pwm_config_interval": pwm_config_interval,
        "pwm_config_duration": _format_duration(pwm_config_interval * scan_interval),
        "failure_grace": failure_grace,
        "weather_interval_ticks": weather_interval_ticks,
        "weather_interval_mins": weather_interval_mins,
    }

    @env.macro
    def fields_table(fields: dict) -> str:
        """Render a service fields dict as a markdown table with no blank lines."""
        if not fields:
            return ""
        rows = [
            "| Field | Description | Required |",
            "|-------|-------------|----------|",
        ]
        for field_id, field in fields.items():
            desc = " ".join(field.get("description", "").split())
            required = "Yes" if field.get("required") else "No"
            rows.append(f"| `{field_id}` | {desc} | {required} |")
        return "\n".join(rows)
