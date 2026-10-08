# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Aedan Lawrence <aedan@mrinterbugs.uk>
# HA entity mixins and dynamic properties override cached_property descriptors.
# pyright: reportIncompatibleVariableOverride=false
from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import SunRiserCoordinator

PARALLEL_UPDATES = 0

# DS1820 device type id
_DS1820 = 1
# unit id for celsius
_UNIT_CELSIUS = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SunRiserCoordinator = entry.runtime_data

    # Static diagnostic sensors — always present.
    async_add_entities(
        [
            SunRiserUptimeSensor(coordinator),
            SunRiserFirmwareSensor(coordinator),
            SunRiserHostnameSensor(coordinator),
        ]
    )

    # Discover weather channels and DS1820 ROMs on every update, including
    # recovery after the optional initial weather request failed.
    _added_weather_channels: set[int] = set()
    _added_roms: set[str] = set()

    @callback
    def _check_sensors() -> None:
        if coordinator.data is None:
            return
        new_entities: list[SunRiserTemperatureSensor | SunRiserWeatherChannelSensor] = (
            []
        )
        for channel, weather in enumerate(coordinator.data.get("weather") or [], 1):
            if weather is not None and channel not in _added_weather_channels:
                _added_weather_channels.add(channel)
                new_entities.append(SunRiserWeatherChannelSensor(coordinator, channel))
        sensors: dict[str, Any] = coordinator.data.get("sensors") or {}
        for rom, reading in sensors.items():
            if rom in _added_roms or not coordinator.sensor_config_loaded(rom):
                continue
            device_type = reading[0]
            if device_type == _DS1820:
                _added_roms.add(rom)
                new_entities.append(SunRiserTemperatureSensor(coordinator, entry, rom))
        if new_entities:
            async_add_entities(new_entities)

    _check_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_check_sensors))


class SunRiserUptimeSensor(CoordinatorEntity[SunRiserCoordinator], SensorEntity):
    """Device uptime in seconds."""

    _attr_has_entity_name = True
    _attr_translation_key = "uptime"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "s"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # Changes every poll — creates many state changes; disabled by default.
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: SunRiserCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}_uptime"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("uptime")


class SunRiserFirmwareSensor(CoordinatorEntity[SunRiserCoordinator], SensorEntity):
    """Firmware version reported by the device."""

    _attr_has_entity_name = True
    _attr_translation_key = "firmware_version"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SunRiserCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}_firmware"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str | None:
        return self.coordinator.firmware_version


class SunRiserHostnameSensor(CoordinatorEntity[SunRiserCoordinator], SensorEntity):
    """Hostname configured on the device."""

    _attr_has_entity_name = True
    _attr_translation_key = "hostname"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SunRiserCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}_hostname"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str | None:
        return self.coordinator.config.get("hostname") or None


class SunRiserTemperatureSensor(CoordinatorEntity[SunRiserCoordinator], SensorEntity):
    """DS1820 temperature sensor reported in /state."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: SunRiserCoordinator,
        entry: ConfigEntry,
        rom: str,
    ) -> None:
        super().__init__(coordinator)
        self._rom = rom
        self._attr_unique_id = f"{entry.entry_id}_sensor_{rom}"
        self._attr_name = coordinator.sensor_name(rom)
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> float | None:
        return self.coordinator.sensor_value(self._rom)

    @property
    def device_class(self) -> SensorDeviceClass | None:
        if self.coordinator.sensor_unit(self._rom) == _UNIT_CELSIUS:
            return SensorDeviceClass.TEMPERATURE
        return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        # Sensors configured as raw (unit=0) have no meaningful HA unit.
        if self.coordinator.sensor_unit(self._rom) == _UNIT_CELSIUS:
            return UnitOfTemperature.CELSIUS
        return None


# ---------------------------------------------------------------------------
# Weather simulation sensors (GET /weather — API still under development)
# One entity per PWM channel that has a weather program assigned.
# ---------------------------------------------------------------------------


class SunRiserWeatherChannelSensor(
    CoordinatorEntity[SunRiserCoordinator], SensorEntity
):
    """Weather simulation state for a single PWM channel.

    State describes the active effect: thunder, rain, cloudy, moon, or clear.
    Extra attributes include the program name, activity flags, and event times.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "weather_channel"

    def __init__(self, coordinator: SunRiserCoordinator, channel: int) -> None:
        super().__init__(coordinator)
        self._channel = channel
        self._attr_unique_id = f"{coordinator.entry_id}_weather_{channel}"
        self._attr_translation_placeholders = {"channel": coordinator.pwm_name(channel)}
        self._attr_device_info = coordinator.device_info

    def _channel_data(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        weather: list[Any] = self.coordinator.data.get("weather") or []
        idx = self._channel - 1
        if idx >= len(weather):
            return None
        return cast(dict[str, Any] | None, weather[idx])

    @property
    def native_value(self) -> str | None:
        ch = self._channel_data()
        if ch is None:
            return None
        if bool(ch.get("thunder_state")):
            return "thunder"
        if (ch.get("rainmins") or 0) > 0:
            return "rain"
        if bool(ch.get("clouds_state")):
            return "cloudy"
        if bool(ch.get("moon_state")):
            return "moon"
        return "clear"

    # Maps raw tick field → (output attribute name, zero-value label)
    _TICK_FIELDS: dict[str, tuple[str, str]] = {
        "clouds_next_state_tick": ("clouds_next_change_at", "no clouds today"),
        "rain_next_tick": ("rain_next_at", "no rain today"),
        "thunder_next_state_tick": ("thunder_next_change_at", "no thunder today"),
        "moon_next_state_tick": ("moon_next_change_at", "no moon tonight"),
    }
    _RENAME_FIELDS: dict[str, str] = {
        "cloudticks": "cloud_ticks",
        "rainmins": "rain_duration_mins",
        "rainfront_start": "rainfront_start_tick",
        "rainfront_length": "rainfront_length_ticks",
        "stormfront_start": "stormfront_start_tick",
        "stormfront_length": "stormfront_length_ticks",
        "daycount": "day_count",
    }
    _EXCLUDE_FIELDS: frozenset[str] = frozenset(
        {"weather_program_id", "clouds_state", "thunder_state", "moon_state"}
    )
    # State fields whose presence indicates the subsystem is configured.
    _ACTIVE_STATE_FIELDS: dict[str, str] = {
        "clouds_state": "clouds_active",
        "thunder_state": "thunder_active",
        "moon_state": "moon_active",
    }

    def _tick_to_attr(self, tick_value: Any, uptime_ms: int, zero_label: str) -> str:
        if tick_value:
            seconds = round((tick_value - uptime_ms) / 1000)
            return (dt_util.utcnow() + timedelta(seconds=seconds)).isoformat()
        return zero_label

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ch = self._channel_data()
        if not ch:
            return {}

        uptime_ms = ((self.coordinator.data or {}).get("uptime") or 0) * 1000
        result: dict[str, Any] = {}

        for k, v in ch.items():
            if k in self._EXCLUDE_FIELDS:
                continue
            if k in self._TICK_FIELDS:
                attr_name, zero_label = self._TICK_FIELDS[k]
                result[attr_name] = self._tick_to_attr(v, uptime_ms, zero_label)
            else:
                result[self._RENAME_FIELDS.get(k, k)] = v

        program_id = ch.get("weather_program_id")
        result["weather_program_id"] = program_id
        result["weather_program_name"] = self.coordinator.weather_program_name(
            program_id
        )

        # Convenience booleans: only included when the firmware reports that
        # subsystem as configured (absent fields → not in this program).
        for state_key, attr_name in self._ACTIVE_STATE_FIELDS.items():
            if state_key in ch:
                result[attr_name] = bool(ch[state_key])
        # rain_active: rain is running when rainmins > 0 (device counts down
        # the remaining minutes of the current rain event).
        if "rainmins" in ch:
            result["rain_active"] = (ch.get("rainmins") or 0) > 0

        return result
