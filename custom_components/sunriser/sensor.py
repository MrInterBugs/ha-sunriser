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
from homeassistant.core import HomeAssistant, callback
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

    # Static diagnostic sensors — always present.
    async_add_entities(
        [
            SunRiserUptimeSensor(coordinator),
            SunRiserFirmwareSensor(coordinator),
            SunRiserHostnameSensor(coordinator),
        ]
    )

    # Weather channel sensors are fixed at setup time (weather list length
    # is determined by pwm_count and doesn't change without a reload).
    weather = coordinator.data.get("weather") or [] if coordinator.data else []
    weather_entities: list[SunRiserWeatherChannelSensor] = [
        SunRiserWeatherChannelSensor(coordinator, i + 1)
        for i, ch in enumerate(weather)
        if ch is not None
    ]
    if weather_entities:
        async_add_entities(weather_entities)

    # DS1820 temperature sensors: add at setup and dynamically as new ROMs appear.
    _added_roms: set[str] = set()

    @callback
    def _check_ds1820_sensors() -> None:
        if coordinator.data is None:
            return
        new_entities: list[SunRiserTemperatureSensor] = []
        for rom, reading in (coordinator.data.get("sensors") or {}).items():
            if rom in _added_roms:
                continue
            device_type = reading[0]
            if device_type == _DS1820:
                _added_roms.add(rom)
                new_entities.append(SunRiserTemperatureSensor(coordinator, entry, rom))
        if new_entities:
            async_add_entities(new_entities)

    _check_ds1820_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_check_ds1820_sensors))


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

    def _tick_to_attr(
        self, tick_value: Any, uptime_ms: int, zero_label: str
    ) -> str:
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
