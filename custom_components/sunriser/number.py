# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import EntityCategory
from homeassistant.helpers import entity_registry
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
    _added: set[int] = set()
    er = entity_registry.async_get(hass)

    @callback
    def _check_entities() -> None:
        new_entities: list[SunRiserPWMFixedNumber] = []
        for pwm_num in range(1, coordinator.pwm_count + 1):
            active = not coordinator.pwm_is_unused(pwm_num)
            if active and pwm_num not in _added:
                _added.add(pwm_num)
                new_entities.append(SunRiserPWMFixedNumber(coordinator, entry, pwm_num))
            elif not active and pwm_num in _added:
                _added.discard(pwm_num)
                uid = f"{entry.entry_id}_pwm_{pwm_num}_fixed"
                eid = er.async_get_entity_id("number", DOMAIN, uid)
                if eid:
                    er.async_remove(eid)
        if new_entities:
            async_add_entities(new_entities)

    _check_entities()
    entry.async_on_unload(coordinator.async_add_listener(_check_entities))


class SunRiserPWMFixedNumber(CoordinatorEntity[SunRiserCoordinator], NumberEntity):
    """Number entity for pwm#X#fixed — the value used when manager is set to 'fixed'."""

    _attr_has_entity_name = True
    _attr_translation_key = "fixed_value"
    _attr_entity_category = EntityCategory.CONFIG
    # Only relevant when manager is set to "fixed"; disabled by default to reduce noise.
    _attr_entity_registry_enabled_default = False
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
        self._attr_translation_placeholders = {"channel": coordinator.pwm_name(pwm_num)}
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
