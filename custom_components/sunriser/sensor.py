from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SunRiserCoordinator

# DS1820 device type id
_DS1820 = 1
# unit id for celsius
_UNIT_CELSIUS = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SunRiserCoordinator = hass.data[DOMAIN][entry.entry_id]
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

    async_add_entities(entities)


class SunRiserUptimeSensor(CoordinatorEntity[SunRiserCoordinator], SensorEntity):
    """Device uptime in seconds."""

    _attr_has_entity_name = True
    _attr_name = "Uptime"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "s"
    _attr_icon = "mdi:timer-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

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
    _attr_name = "Firmware Version"
    _attr_icon = "mdi:chip"
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
    _attr_name = "Hostname"
    _attr_icon = "mdi:network"
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
