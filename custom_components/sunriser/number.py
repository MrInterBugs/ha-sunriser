# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Aedan Lawrence <aedan@mrinterbugs.uk>
# HA entity mixins and dynamic properties override cached_property descriptors.
# pyright: reportIncompatibleVariableOverride=false
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import PWM_MAX
from .coordinator import SunRiserCoordinator
from .discovery import pwm_entity_reconciler
from .maintenance import setup_maintenance_entities

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SunRiserCoordinator = entry.runtime_data
    setup_maintenance_entities(hass, entry, async_add_entities, "number")
    _check_entities = pwm_entity_reconciler(
        hass,
        entry,
        async_add_entities,
        "number",
        "_fixed",
        lambda channel: not coordinator.pwm_is_unused(channel),
        lambda channel: SunRiserPWMFixedNumber(coordinator, entry, channel),
    )

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
