# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Aedan Lawrence <aedan@mrinterbugs.uk>
# HA entity mixins and dynamic properties override cached_property descriptors.
# pyright: reportIncompatibleVariableOverride=false
from __future__ import annotations

from typing import Any, cast

from homeassistant.components.light import ATTR_BRIGHTNESS, LightEntity
from homeassistant.components.light.const import ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import PWM_MAX
from .coordinator import SunRiserCoordinator
from .discovery import pwm_entity_reconciler

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
    _check_entities = pwm_entity_reconciler(
        hass,
        entry,
        async_add_entities,
        "light",
        "",
        lambda channel: not coordinator.pwm_is_unused(channel)
        and not coordinator.pwm_is_onoff(channel),
        lambda channel: SunRiserLight(coordinator, entry, channel),
    )

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
