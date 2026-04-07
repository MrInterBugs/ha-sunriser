# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Any, cast

from homeassistant.components.light import ATTR_BRIGHTNESS, LightEntity
from homeassistant.components.light.const import ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PWM_MAX
from .coordinator import SunRiserCoordinator

PARALLEL_UPDATES = 1


# Linear scale: device 0–1000 ↔ HA 0–255
# Endpoints are exact: only PWM 1000 maps to HA 255, and only HA 255 maps to PWM 1000.
def _to_ha_brightness(pwm_value: int) -> int:
    if pwm_value <= 0:
        return 0
    if pwm_value >= PWM_MAX:
        return 255
    return max(1, min(254, round(pwm_value * 255 / PWM_MAX)))


def _to_device_brightness(brightness: int) -> int:
    if brightness >= 255:
        return PWM_MAX
    return round(brightness * PWM_MAX / 255)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SunRiserCoordinator = entry.runtime_data
    _added: set[int] = set()
    er = entity_registry.async_get(hass)

    @callback
    def _check_entities() -> None:
        new_entities: list[SunRiserLight] = []
        for pwm_num in range(1, coordinator.pwm_count + 1):
            is_light = not coordinator.pwm_is_unused(
                pwm_num
            ) and not coordinator.pwm_is_onoff(pwm_num)
            if is_light and pwm_num not in _added:
                _added.add(pwm_num)
                new_entities.append(SunRiserLight(coordinator, entry, pwm_num))
            elif not is_light and pwm_num in _added:
                _added.discard(pwm_num)
                uid = f"{entry.entry_id}_pwm_{pwm_num}"
                eid = er.async_get_entity_id("light", DOMAIN, uid)
                if eid:
                    er.async_remove(eid)
        if new_entities:
            async_add_entities(new_entities)

    _check_entities()
    entry.async_on_unload(coordinator.async_add_listener(_check_entities))


class SunRiserLight(CoordinatorEntity[SunRiserCoordinator], LightEntity):
    """Dimmable PWM channel on a SunRiser device."""

    _attr_has_entity_name = True
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

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

    @property
    def brightness(self) -> int:
        return _to_ha_brightness(self.coordinator.pwm_value(self._pwm_num))

    async def async_turn_on(self, **kwargs: Any) -> None:
        brightness: int = cast(int, kwargs.get(ATTR_BRIGHTNESS, 255))
        device_value = _to_device_brightness(brightness)
        await self.coordinator.async_set_pwms({str(self._pwm_num): device_value})
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_pwms({str(self._pwm_num): 0})
        await self.coordinator.async_request_refresh()
