# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Aedan Lawrence <aedan@mrinterbugs.uk>
"""Validated planning snapshots for the editor; no output or mode commands."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, TypedDict, TypeGuard
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.exceptions import HomeAssistantError

from .responses import InvalidResponse


class Profile(TypedDict):
    id: int
    name: str


def _list(value: object) -> TypeGuard[list[Any]]:
    return isinstance(value, list)


def _dict(value: object) -> TypeGuard[dict[str, Any]]:
    return isinstance(value, dict)


def profiles(value: Any) -> list[Profile]:
    """The vendor stores its profile index as a JSON array (or decoded array)."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as err:
            raise InvalidResponse("Invalid profile index JSON") from err
    if not _list(value):
        raise InvalidResponse("Profile index must be a list")
    result: list[Profile] = []
    seen: set[int] = set()
    for item in value:
        if item is None:
            continue
        if (
            not _dict(item)
            or type(item.get("id")) is not int
            or item["id"] <= 0
            or item["id"] in seen
            or not isinstance(item.get("name"), str)
        ):
            raise InvalidResponse("Invalid or duplicate profile identity")
        seen.add(item["id"])
        result.append({"id": item["id"], "name": item["name"]})
    return result


def markers(value: Any) -> list[dict[str, Any]]:
    flat: Any = [] if value is None else value
    if not _list(flat) or len(flat) % 2:
        raise InvalidResponse("Schedule must contain time/percentage pairs")
    result: list[dict[str, Any]] = []
    seen: set[int] = set()
    for minute, percent in zip(flat[::2], flat[1::2], strict=True):
        if (
            type(minute) is not int
            or not 0 <= minute <= 1440
            or minute in seen
            or type(percent) is not int
            or not 0 <= percent <= 100
        ):
            raise InvalidResponse("Invalid or duplicate schedule marker")
        seen.add(minute)
        result.append(
            {"time": f"{minute // 60:02d}:{minute % 60:02d}", "percent": percent}
        )
    return sorted(result, key=lambda marker: marker["time"])


def flatten(value: list[dict[str, Any]]) -> list[int]:
    flat: list[int] = []
    try:
        for marker in value:
            hour, minute = map(int, marker["time"].split(":"))
            if not 0 <= minute < 60 or not 0 <= hour <= 24 or (hour == 24 and minute):
                raise ValueError
            flat.extend([hour * 60 + minute, marker["percent"]])
        if not flat:
            raise ValueError
        ordered = markers(flat)
    except (KeyError, TypeError, ValueError) as err:
        raise HomeAssistantError(
            "Use unique times from 00:00 to 24:00 and whole percentages from 0 to 100"
        ) from err
    return [
        part
        for marker in ordered
        for part in (
            int(marker["time"][:2]) * 60 + int(marker["time"][3:]),
            marker["percent"],
        )
    ]


def assignments(value: Any) -> list[int]:
    if value is None or value == []:
        return [0] * 8
    if (
        not _list(value)
        or len(value) != 8
        or any(v is not None and (type(v) is not int or v < 0) for v in value)
    ):
        raise InvalidResponse("Weekly assignments must contain eight program IDs")
    return [v or 0 for v in value]


def revision(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def weekday(config: dict[str, Any], now: datetime) -> int | None:
    """Resolve today using controller time settings, never the browser timezone."""
    tz = config.get("tz")
    try:
        if tz:
            local = now.astimezone(ZoneInfo(tz))
        elif type(config.get("gmtoff")) is int:
            offset = config["gmtoff"] + (60 if config.get("summertime") else 0)
            local = now.astimezone(timezone(timedelta(minutes=offset)))
        else:
            return None
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return None
    return (local.weekday() + 1) % 7
