# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Aedan Lawrence <aedan@mrinterbugs.uk>
"""Reconcile PWM entities against the current channel configuration."""

from collections.abc import Callable
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SunRiserCoordinator


def pwm_entity_reconciler(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    platform: str,
    suffix: str,
    eligible: Callable[[int], bool],
    create_entity: Callable[[int], Entity],
) -> Callable[[], None]:
    """Track additions and remove obsolete channels, including across reloads."""
    coordinator: SunRiserCoordinator = entry.runtime_data
    registry = entity_registry.async_get(hass)
    pattern = re.compile(
        rf"{re.escape(entry.entry_id)}_pwm_([1-9][0-9]*){re.escape(suffix)}"
    )
    known: set[int] = set()
    for entity in entity_registry.async_entries_for_config_entry(
        registry, entry.entry_id
    ):
        if entity.domain == platform and entity.platform == DOMAIN:
            match = pattern.fullmatch(entity.unique_id)
            if match:
                known.add(int(match[1]))
    added: set[int] = set()

    @callback
    def reconcile() -> None:
        if not coordinator.last_update_success:
            return
        current = {
            channel
            for channel in range(1, coordinator.pwm_count + 1)
            if eligible(channel)
        }
        for channel in known - current:
            entity_id = registry.async_get_entity_id(
                platform, DOMAIN, f"{entry.entry_id}_pwm_{channel}{suffix}"
            )
            if entity_id:
                registry.async_remove(entity_id)
        new_entities = [create_entity(channel) for channel in sorted(current - added)]
        known.clear()
        known.update(current)
        added.clear()
        added.update(current)
        if new_entities:
            async_add_entities(new_entities)

    return reconcile
