# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PWM_MAX
from .coordinator import SunRiserCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SunRiserCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SwitchEntity] = [SunRiserMaintenanceSwitch(coordinator, entry)]
    entities += [
        SunRiserSwitch(coordinator, entry, pwm_num)
        for pwm_num in range(1, coordinator.pwm_count + 1)
        if coordinator.pwm_is_onoff(pwm_num) and not coordinator.pwm_is_unused(pwm_num)
    ]
    async_add_entities(entities)


class SunRiserMaintenanceSwitch(CoordinatorEntity[SunRiserCoordinator], SwitchEntity):
    """Maintenance mode switch — freezes all PWM channels on the device."""

    _attr_has_entity_name = True
    _attr_name = "Maintenance Mode"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:wrench"

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
