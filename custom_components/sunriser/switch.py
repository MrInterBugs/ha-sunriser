# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PWM_MAX
from .coordinator import SunRiserCoordinator

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SunRiserCoordinator = entry.runtime_data

    entities: list[SwitchEntity] = [
        SunRiserMaintenanceSwitch(coordinator, entry),
        SunRiserTimelapseSwitch(coordinator, entry),
        SunRiserDSTAutoSwitch(coordinator, entry),
    ]
    entities += [
        SunRiserSwitch(coordinator, entry, pwm_num)
        for pwm_num in range(1, coordinator.pwm_count + 1)
        if coordinator.pwm_is_onoff(pwm_num) and not coordinator.pwm_is_unused(pwm_num)
    ]
    async_add_entities(entities)


class SunRiserMaintenanceSwitch(CoordinatorEntity[SunRiserCoordinator], SwitchEntity):
    """Maintenance mode switch — freezes all PWM channels on the device."""

    _attr_has_entity_name = True
    _attr_translation_key = "maintenance_mode"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: SunRiserCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_maintenance"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return False
        # service_mode is 0 when off, or a Unix timestamp when on
        return bool(self.coordinator.data.get("service_mode"))

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_set_service_mode(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_set_service_mode(False)
        await self.coordinator.async_request_refresh()


class SunRiserSwitch(CoordinatorEntity[SunRiserCoordinator], SwitchEntity):
    """On/off PWM channel (pwm#X#onoff = true) on a SunRiser device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SunRiserCoordinator,
        entry: ConfigEntry,
        pwm_num: int,
    ) -> None:
        super().__init__(coordinator)
        self._pwm_num = pwm_num
        self._attr_unique_id = f"{entry.entry_id}_pwm_{pwm_num}"
        self._attr_name = coordinator.pwm_name(pwm_num)
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        return self.coordinator.pwm_value(self._pwm_num) > 0

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_set_pwms({str(self._pwm_num): PWM_MAX})
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_set_pwms({str(self._pwm_num): 0})
        await self.coordinator.async_request_refresh()


class SunRiserTimelapseSwitch(CoordinatorEntity[SunRiserCoordinator], SwitchEntity):
    """Time-lapse (timewarp) mode — runs the day/week planner at ~1800× speed."""

    _attr_has_entity_name = True
    _attr_translation_key = "timelapse"

    def __init__(self, coordinator: SunRiserCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_timelapse"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return False
        return bool(self.coordinator.data.get("timewarp"))

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_set_timewarp(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_set_timewarp(False)
        await self.coordinator.async_request_refresh()


class SunRiserDSTAutoSwitch(
    CoordinatorEntity[SunRiserCoordinator], SwitchEntity, RestoreEntity
):
    """Automatic DST tracking — keeps the device summertime config in sync with the HA timezone."""

    _attr_has_entity_name = True
    _attr_translation_key = "dst_auto_track"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SunRiserCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_dst_auto_track"
        self._attr_device_info = coordinator.device_info

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == STATE_ON:
            await self.coordinator.async_set_dst_auto_track(True)

    @property
    def is_on(self) -> bool:
        return self.coordinator._dst_auto_track

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_set_dst_auto_track(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_set_dst_auto_track(False)
        self.async_write_ha_state()
