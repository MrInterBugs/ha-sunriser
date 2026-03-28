# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import EntityCategory
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANAGER_OPTIONS
from .coordinator import SunRiserCoordinator

PARALLEL_UPDATES = 1

_MANAGER_TO_INT: dict[str, int] = {v: k for k, v in MANAGER_OPTIONS.items()}


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
        new_entities: list[SunRiserPWMManagerSelect] = []
        for pwm_num in range(1, coordinator.pwm_count + 1):
            active = not coordinator.pwm_is_unused(pwm_num)
            if active and pwm_num not in _added:
                _added.add(pwm_num)
                new_entities.append(
                    SunRiserPWMManagerSelect(coordinator, entry, pwm_num)
                )
            elif not active and pwm_num in _added:
                _added.discard(pwm_num)
                uid = f"{entry.entry_id}_pwm_{pwm_num}_manager"
                eid = er.async_get_entity_id("select", DOMAIN, uid)
                if eid:
                    er.async_remove(eid)
        if new_entities:
            async_add_entities(new_entities)

    _check_entities()
    entry.async_on_unload(coordinator.async_add_listener(_check_entities))


class SunRiserPWMManagerSelect(CoordinatorEntity[SunRiserCoordinator], SelectEntity):
    """Select which planner controls a PWM channel (pwm#X#manager)."""

    _attr_has_entity_name = True
    _attr_translation_key = "pwm_manager"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(MANAGER_OPTIONS.values())
    # Advanced config — most users set once and never revisit; disabled by default.
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: SunRiserCoordinator,
        entry: ConfigEntry,
        pwm_num: int,
    ) -> None:
        super().__init__(coordinator)
        self._pwm_num = pwm_num
        self._attr_unique_id = f"{entry.entry_id}_pwm_{pwm_num}_manager"
        self._attr_translation_placeholders = {"channel": coordinator.pwm_name(pwm_num)}
        self._attr_device_info = coordinator.device_info

    @property
    def current_option(self) -> str:
        return MANAGER_OPTIONS.get(self.coordinator.pwm_manager(self._pwm_num), "none")

    async def async_select_option(self, option: str) -> None:
        value = _MANAGER_TO_INT.get(option, 0)
        await self.coordinator.async_set_config({f"pwm#{self._pwm_num}#manager": value})
        self.coordinator.config[f"pwm#{self._pwm_num}#manager"] = value
