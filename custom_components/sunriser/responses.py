# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Aedan Lawrence <aedan@mrinterbugs.uk>
"""Validate consumed firmware fields before publishing a response.

Missing optional fields and unknown fields are retained. A bad known field rejects
its entire response so callers can keep the last valid snapshot.
"""

from __future__ import annotations

import math
from typing import Any, TypeGuard, cast

import msgpack


class InvalidResponse(ValueError):
    """The controller returned malformed MessagePack or an unusable field."""


def _decode(body: bytes, *, stream: bool = False) -> Any:
    try:
        return msgpack.unpackb(body, raw=False, strict_map_key=False)
    except msgpack.ExtraData as err:
        if stream:
            # /weather intentionally uses only the first object.
            return getattr(err, "unpacked")
        raise InvalidResponse("Unexpected trailing MessagePack data") from err
    except (ValueError, TypeError) as err:
        raise InvalidResponse("Malformed MessagePack response") from err


def _is_mapping(value: object) -> TypeGuard[dict[Any, Any]]:
    return isinstance(value, dict)


def _is_list(value: object) -> TypeGuard[list[Any]]:
    return isinstance(value, list)


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not _is_mapping(value) or any(not isinstance(k, str) for k in value):
        raise InvalidResponse(f"{field} must be a mapping with text keys")
    return cast(dict[str, Any], value)


def _number(value: Any, field: str, *, integer: bool = False) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or (integer and not isinstance(value, int))
    ):
        raise InvalidResponse(
            f"{field} must be a finite {'integer' if integer else 'number'}"
        )


def decode_state(body: bytes) -> dict[str, Any]:
    state = _mapping(_decode(body), "state")
    for field in ("uptime", "service_mode", "timewarp", "service_left"):
        if state.get(field) is not None:
            _number(state[field], field)
    if "blackout" in state and state["blackout"] is not None:
        if type(state["blackout"]) not in (bool, int) or state["blackout"] not in (
            0,
            1,
        ):
            raise InvalidResponse("blackout must be a boolean or 0/1")
    if "pwms" in state:
        pwms = state["pwms"]
        if not _is_mapping(pwms) or len(pwms) > 10:
            raise InvalidResponse("pwms must be a channel mapping")
        normalized: dict[str, Any] = {}
        for key, value in pwms.items():
            if type(key) not in (str, int) or str(key) not in {
                str(i) for i in range(1, 11)
            }:
                raise InvalidResponse("Invalid PWM channel identifier")
            if str(key) in normalized:
                raise InvalidResponse("Duplicate PWM channel identifier")
            _number(value, f"pwms.{key}")
            if not 0 <= value <= 1000:
                raise InvalidResponse("PWM value must be between 0 and 1000")
            normalized[str(key)] = value
        state["pwms"] = normalized
    if "sensors" in state:
        for rom, reading in _mapping(state["sensors"], "sensors").items():
            if reading is None:
                continue  # Disconnected probe.
            if not _is_list(reading) or len(reading) < 2:
                raise InvalidResponse(f"sensors.{rom} must contain type and reading")
            _number(reading[1], f"sensors.{rom}.reading")
    return state


def decode_config(body: bytes) -> dict[str, Any]:
    config = _mapping(_decode(body), "configuration")
    for key, value in config.items():
        if value is None:
            continue  # Unset configuration values are normal.
        if key == "pwm_count":
            _number(value, key, integer=True)
            if not 1 <= value <= 10:
                raise InvalidResponse("pwm_count must be between 1 and 10")
        elif key in (
            "name",
            "model",
            "hostname",
            "factory_version",
            "save_version",
        ) or (
            key.startswith(("pwm#", "sensors#sensor#", "weather#setup#"))
            and key.rsplit("#", 1)[-1] in ("name", "color")
        ):
            if not isinstance(value, str):
                raise InvalidResponse(f"{key} must be text")
        elif (
            key.startswith(("pwm#", "sensors#sensor#"))
            and key.rsplit("#", 1)[-1]
            in ("max", "manager", "fixed", "unit", "unitcomma", "service")
            or key in ("service_timeout", "service_value")
        ):
            _number(value, key, integer=True)
        elif key.startswith("pwm#") and key.rsplit("#", 1)[-1] in ("onoff", "nomaint"):
            if type(value) not in (bool, int) or value not in (0, 1):
                raise InvalidResponse(f"{key} must be a boolean or 0/1")
        elif key.startswith(("dayplanner#marker#", "weekplanner#programs#")):
            if not _is_list(value):
                raise InvalidResponse(f"{key} must be a list")
            for item in value:
                if item is not None:
                    _number(item, key, integer=True)
    return config


def decode_weather(body: bytes) -> list[dict[str, Any] | None]:
    weather = _decode(body, stream=True)
    if not _is_list(weather) or len(weather) > 10:
        raise InvalidResponse("weather must be a list of channels")
    for channel in weather:
        if channel is None:
            continue
        channel = _mapping(channel, "weather channel")
        for key in (
            "weather_program_id",
            "rainmins",
            "clouds_next_state_tick",
            "rain_next_tick",
            "thunder_next_state_tick",
            "moon_next_state_tick",
        ):
            if channel.get(key) is not None:
                _number(channel[key], key, integer=key == "weather_program_id")
    return cast(list[dict[str, Any] | None], weather)
