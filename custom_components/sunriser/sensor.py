# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
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
    entities: list[SensorEntity] = [
        SunRiserUptimeSensor(coordinator),
        SunRiserFirmwareSensor(coordinator),
        SunRiserHostnameSensor(coordinator),
    ]

    # Add temperature sensors discovered in the initial state poll.
    if coordinator.data and coordinator.data.get("sensors"):
        for rom, reading in coordinator.data["sensors"].items():
            device_type = reading[0]
            if device_type == _DS1820:
                entities.append(SunRiserTemperatureSensor(coordinator, entry, rom))

    weather = coordinator.data.get("weather") or [] if coordinator.data else []
    for i, ch in enumerate(weather):
        if ch is not None:
            entities.append(SunRiserWeatherChannelSensor(coordinator, i + 1))

    async_add_entities(entities)


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
        self._attr_unique_id = f"{coordinator._entry_id}_uptime"
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
        self._attr_unique_id = f"{coordinator._entry_id}_firmware"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str | None:
        return self.coordinator.config.get("save_version") or None


class SunRiserHostnameSensor(CoordinatorEntity[SunRiserCoordinator], SensorEntity):
    """Hostname configured on the device."""

    _attr_has_entity_name = True
    _attr_translation_key = "hostname"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SunRiserCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator._entry_id}_hostname"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str | None:
        return self.coordinator.config.get("hostname") or None


class SunRiserTemperatureSensor(CoordinatorEntity[SunRiserCoordinator], SensorEntity):
    """DS1820 temperature sensor reported in /state."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

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
    def native_unit_of_measurement(self) -> str:
        # Sensors configured as raw (unit=0) have no meaningful HA unit.
        if self.coordinator.sensor_unit(self._rom) == _UNIT_CELSIUS:
            return UnitOfTemperature.CELSIUS
        return "raw"


# ---------------------------------------------------------------------------
# Weather simulation sensors (GET /weather — API still under development)
# One entity per PWM channel that has a weather program assigned.
# ---------------------------------------------------------------------------


class SunRiserWeatherChannelSensor(
    CoordinatorEntity[SunRiserCoordinator], SensorEntity
):
    """Weather simulation state for a single PWM channel.

    State = weather_program_id (which program is running on this channel).
    All other fields (clouds_state, rain ticks, moon state, etc.) are
    exposed as extra state attributes.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "weather_channel"

    def __init__(self, coordinator: SunRiserCoordinator, channel: int) -> None:
        super().__init__(coordinator)
        self._channel = channel
        self._attr_unique_id = f"{coordinator._entry_id}_weather_{channel}"
        self._attr_translation_placeholders = {"channel": coordinator.pwm_name(channel)}
        self._attr_device_info = coordinator.device_info

    def _channel_data(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        weather = self.coordinator.data.get("weather") or []
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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ch = self._channel_data()
        if not ch:
            return {}

        uptime_ms = ((self.coordinator.data or {}).get("uptime") or 0) * 1000

        # *_next_state_tick / *_next_tick fields are milliseconds from device
        # boot; convert to an ISO timestamp of the next state transition.
        _tick_to_seconds = {
            "clouds_next_state_tick": "clouds_next_change_at",
            "rain_next_tick": "rain_next_at",
            "thunder_next_state_tick": "thunder_next_change_at",
            "moon_next_state_tick": "moon_next_change_at",
        }
        _rename = {
            "cloudticks": "cloud_ticks",
            "rainmins": "rain_duration_mins",
            "rainfront_start": "rainfront_start_tick",
            "rainfront_length": "rainfront_length_ticks",
            "stormfront_start": "stormfront_start_tick",
            "stormfront_length": "stormfront_length_ticks",
            "daycount": "day_count",
        }
        exclude = {"weather_program_id", "clouds_state", "thunder_state", "moon_state"}

        now = dt_util.utcnow()
        result: dict[str, Any] = {}
        for k, v in ch.items():
            if k in exclude:
                continue
            if k in _tick_to_seconds:
                if v:
                    seconds = round((v - uptime_ms) / 1000)
                    result[_tick_to_seconds[k]] = (
                        now + timedelta(seconds=seconds)
                    ).isoformat()
                else:
                    result[_tick_to_seconds[k]] = None
            else:
                result[_rename.get(k, k)] = v

        # Human-readable program name (resolved from config).
        program_id = ch.get("weather_program_id")
        result["weather_program_id"] = program_id
        result["weather_program_name"] = self.coordinator.weather_program_name(
            program_id
        )

        # Convenience booleans derived from the state-machine integers.
        # A non-zero state means that subsystem is currently active.
        result["thunder_active"] = bool(ch.get("thunder_state"))
        result["moon_active"] = bool(ch.get("moon_state"))
        result["clouds_active"] = bool(ch.get("clouds_state"))
        # rain_active: rain is running when rainmins > 0 (device counts down
        # the remaining minutes of the current rain event).
        result["rain_active"] = (ch.get("rainmins") or 0) > 0

        return result
