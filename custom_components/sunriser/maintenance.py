# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Aedan Lawrence <aedan@mrinterbugs.uk>
# HA entity mixins override cached_property descriptors.
# pyright: reportIncompatibleVariableOverride=false
"""Firmware 1.006 maintenance controls shared by the entity platforms."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SunRiserCoordinator

MaintenancePlatform = Literal["switch", "number", "sensor", "button"]


class MaintenanceEntity(CoordinatorEntity[SunRiserCoordinator]):
    """Stable identity and firmware availability for additional controls."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SunRiserCoordinator, key: str, channel: int | None = None
    ) -> None:
        super().__init__(coordinator)
        self.channel = channel
        self._attr_translation_key = key
        suffix = f"pwm_{channel}_{key}" if channel is not None else key
        self._attr_unique_id = f"{coordinator.entry_id}_{suffix}"
        self._attr_device_info = coordinator.device_info
        if channel is not None:
            self._attr_translation_placeholders = {
                "channel": coordinator.pwm_name(channel)
            }

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.supports_maintenance_config


class SunRiserBlackoutSwitch(MaintenanceEntity, SwitchEntity):
    """The controller's timed blackout, including maintenance exclusions."""

    def __init__(self, coordinator: SunRiserCoordinator) -> None:
        super().__init__(coordinator, "blackout")

    @property
    def is_on(self) -> bool | None:
        mode = self.coordinator.operating_mode
        return None if mode is None else mode == "blackout"

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_set_blackout(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_set_blackout(False)


class SunRiserMaintenanceConfigSwitch(MaintenanceEntity, SwitchEntity):
    """Channel exclusion or the maintenance state of an on/off output."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: SunRiserCoordinator, channel: int, *, exclusion: bool
    ) -> None:
        super().__init__(
            coordinator,
            "maintenance_excluded" if exclusion else "maintenance_output",
            channel,
        )
        self._key = f"pwm#{channel}#{'nomaint' if exclusion else 'service'}"
        self._on_value: int | bool = True if exclusion else 100
        self._off_value: int | bool = False if exclusion else 0

    @property
    def is_on(self) -> bool:
        # The vendor UI defaults an unset on/off maintenance output to off.
        return bool(self.coordinator.config.get(self._key))

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_set_maintenance_config(self._key, self._on_value)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_set_maintenance_config(self._key, self._off_value)


class SunRiserMaintenanceNumber(MaintenanceEntity, NumberEntity):
    """Persistent timeout in minutes or dimmable channel level in percent."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_native_min_value = 0
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(
        self, coordinator: SunRiserCoordinator, channel: int | None = None
    ) -> None:
        super().__init__(
            coordinator,
            "maintenance_timeout" if channel is None else "maintenance_level",
            channel,
        )
        self._key = "service_timeout" if channel is None else f"pwm#{channel}#service"
        self._attr_native_max_value = 10080 if channel is None else 100
        self._attr_native_unit_of_measurement = (
            UnitOfTime.MINUTES if channel is None else "%"
        )

    @property
    def native_value(self) -> float:
        value = self.coordinator.config.get(self._key)
        if value is not None:
            return float(value)
        if self.channel is None:
            return 1440
        legacy = self.coordinator.config.get("service_value")
        return max(0, min(100, int(legacy) // 10)) if legacy is not None else 100

    async def async_set_native_value(self, value: float) -> None:
        if (
            not 0 <= value <= self._attr_native_max_value
            or not float(value).is_integer()
        ):
            raise ValueError(
                f"Expected a whole number from 0 to {self._attr_native_max_value}"
            )
        await self.coordinator.async_set_maintenance_config(self._key, int(value))


class SunRiserOperatingModeSensor(MaintenanceEntity, SensorEntity):
    """Current mode, without conflating enabled settings and active operation."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["normal", "maintenance", "blackout", "time_lapse"]

    def __init__(self, coordinator: SunRiserCoordinator) -> None:
        super().__init__(coordinator, "operating_mode")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.operating_mode


class SunRiserMaintenanceEndSensor(MaintenanceEntity, SensorEntity):
    """Estimated end of maintenance/blackout from the last reported countdown."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: SunRiserCoordinator) -> None:
        super().__init__(coordinator, "maintenance_ends_at")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.maintenance_ends_at


class SunRiserResumeButton(MaintenanceEntity, ButtonEntity):
    """End maintenance or blackout without changing stored plans or time-lapse."""

    def __init__(self, coordinator: SunRiserCoordinator) -> None:
        super().__init__(coordinator, "resume_normal_operation")

    async def async_press(self) -> None:
        await self.coordinator.async_resume_normal_operation()


def setup_maintenance_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    platform: MaintenancePlatform,
) -> None:
    """Discover on upgrade and reconcile channels/types after external changes."""
    coordinator: SunRiserCoordinator = entry.runtime_data
    added: set[str] = set()
    registry = entity_registry.async_get(hass)

    @callback
    def reconcile() -> None:
        candidates: list[MaintenanceEntity] = []
        if coordinator.supports_maintenance_config:
            if platform == "switch":
                candidates.append(SunRiserBlackoutSwitch(coordinator))
            elif platform == "number":
                candidates.append(SunRiserMaintenanceNumber(coordinator))
            elif platform == "sensor":
                candidates.extend(
                    [
                        SunRiserOperatingModeSensor(coordinator),
                        SunRiserMaintenanceEndSensor(coordinator),
                    ]
                )
            elif platform == "button":
                candidates.append(SunRiserResumeButton(coordinator))
            if platform in ("number", "switch"):
                for channel in range(1, coordinator.pwm_count + 1):
                    if coordinator.pwm_is_unused(channel):
                        continue
                    onoff = coordinator.pwm_is_onoff(channel)
                    if platform == "switch":
                        candidates.append(
                            SunRiserMaintenanceConfigSwitch(
                                coordinator, channel, exclusion=True
                            )
                        )
                        if onoff:
                            candidates.append(
                                SunRiserMaintenanceConfigSwitch(
                                    coordinator, channel, exclusion=False
                                )
                            )
                    elif not onoff:
                        candidates.append(
                            SunRiserMaintenanceNumber(coordinator, channel)
                        )
        current = {str(entity.unique_id) for entity in candidates}
        for uid in added - current:
            eid = registry.async_get_entity_id(platform, DOMAIN, uid)
            if eid:
                registry.async_remove(eid)
        new = [entity for entity in candidates if str(entity.unique_id) not in added]
        added.clear()
        added.update(current)
        if new:
            async_add_entities(new)

    reconcile()
    entry.async_on_unload(coordinator.async_add_listener(reconcile))
