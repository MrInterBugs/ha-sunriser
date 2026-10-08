# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Aedan Lawrence <aedan@mrinterbugs.uk>
# HA entity mixins and dynamic properties override cached_property descriptors.
# pyright: reportIncompatibleVariableOverride=false
from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SunRiserCoordinator

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SunRiserCoordinator = entry.runtime_data
    # Remove the redundant button registered by the first maintenance beta.
    registry = entity_registry.async_get(hass)
    obsolete = registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_resume_normal_operation"
    )
    if obsolete:
        registry.async_remove(obsolete)
    async_add_entities([SunRiserRebootButton(coordinator, entry)])


class SunRiserRebootButton(CoordinatorEntity[SunRiserCoordinator], ButtonEntity):
    """Button that reboots the SunRiser device."""

    _attr_has_entity_name = True
    _attr_translation_key = "reboot"
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SunRiserCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_reboot"
        self._attr_device_info = coordinator.device_info

    async def async_press(self) -> None:
        await self.coordinator.async_reboot()
