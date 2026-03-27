# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
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
    async_add_entities(
        SunRiserPWMFixedNumber(coordinator, entry, pwm_num)
        for pwm_num in range(1, coordinator.pwm_count + 1)
        if not coordinator.pwm_is_unused(pwm_num)
    )


class SunRiserPWMFixedNumber(CoordinatorEntity[SunRiserCoordinator], NumberEntity):
    """Number entity for pwm#X#fixed — the value used when manager is set to 'fixed'."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:numeric"
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0
    _attr_native_max_value = PWM_MAX
    _attr_native_step = 1

    def __init__(
        self,
        coordinator: SunRiserCoordinator,
        entry: ConfigEntry,
        pwm_num: int,
    ) -> None:
        super().__init__(coordinator)
        self._pwm_num = pwm_num
        self._attr_unique_id = f"{entry.entry_id}_pwm_{pwm_num}_fixed"
        self._attr_name = f"{coordinator.pwm_name(pwm_num)} Fixed Value"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> float:
        return float(self.coordinator.config.get(f"pwm#{self._pwm_num}#fixed") or 0)

    async def async_set_native_value(self, value: float) -> None:
        int_value = int(value)
        await self.coordinator.async_set_config(
            {f"pwm#{self._pwm_num}#fixed": int_value}
        )
        self.coordinator.config[f"pwm#{self._pwm_num}#fixed"] = int_value
