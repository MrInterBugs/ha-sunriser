# SPDX-License-Identifier: GPL-3.0-or-later
"""Channel removal must also work beyond the device's new channel count."""

from collections.abc import Awaitable, Callable

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunriser.coordinator import SunRiserCoordinator
from custom_components.sunriser.light import async_setup_entry as light_setup
from custom_components.sunriser.number import async_setup_entry as number_setup
from custom_components.sunriser.select import async_setup_entry as select_setup
from custom_components.sunriser.switch import async_setup_entry as switch_setup
from tests.conftest import DOMAIN
from tests.test_dynamic_devices import _capture_listener
from tests.typing import collect_entities

type Setup = Callable[
    [HomeAssistant, ConfigEntry, AddEntitiesCallback], Awaitable[None]
]

PLATFORMS = [
    (light_setup, "light", "", False),
    (switch_setup, "switch", "", True),
    (number_setup, "number", "_fixed", False),
    (select_setup, "select", "_manager", False),
]


@pytest.mark.parametrize("setup,platform,suffix,onoff", PLATFORMS)
async def test_count_shrink_and_return(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
    setup: Setup,
    platform: str,
    suffix: str,
    onoff: bool,
) -> None:
    """Remove vanished channels and rediscover them once if they return."""
    entry = mock_config_entry
    entry.add_to_hass(hass)
    entry.runtime_data = coordinator
    coordinator.config["pwm#4#onoff"] = onoff
    captured = _capture_listener(coordinator)
    added: list[Entity] = []
    await setup(hass, entry, collect_entities(added))
    uid = f"{entry.entry_id}_pwm_4{suffix}"
    assert sum(e.unique_id == uid for e in added) == 1
    registry = entity_registry.async_get(hass)
    old = registry.async_get_or_create(platform, DOMAIN, uid, config_entry=entry)
    assert captured[0] is not None

    # A failed refresh must not remove entities, even if count is unavailable.
    coordinator.last_update_success = False
    coordinator.config["pwm_count"] = 2
    captured[0]()
    assert registry.async_get(old.entity_id) is not None

    coordinator.last_update_success = True
    captured[0]()
    assert registry.async_get(old.entity_id) is None
    coordinator.config["pwm_count"] = 4
    captured[0]()
    captured[0]()
    assert sum(e.unique_id == uid for e in added) == 2


@pytest.mark.parametrize("setup,platform,suffix,onoff", PLATFORMS)
async def test_reload_reconciles_only_owned_channels(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
    setup: Setup,
    platform: str,
    suffix: str,
    onoff: bool,
) -> None:
    """Clean old entries on startup without resetting retained entity settings."""
    entry = mock_config_entry
    entry.add_to_hass(hass)
    entry.runtime_data = coordinator
    coordinator.config["pwm_count"] = 2
    coordinator.config["factory_version"] = "1.006"
    coordinator.config["pwm#1#onoff"] = onoff
    registry = entity_registry.async_get(hass)
    retained = registry.async_get_or_create(
        platform, DOMAIN, f"{entry.entry_id}_pwm_1{suffix}", config_entry=entry
    )
    retained = registry.async_update_entity(
        retained.entity_id,
        name="My channel",
        disabled_by=entity_registry.RegistryEntryDisabler.USER,
    )
    obsolete = registry.async_get_or_create(
        platform, DOMAIN, f"{entry.entry_id}_pwm_4{suffix}", config_entry=entry
    )
    # Active maintenance controls and unrelated entity platforms are not owned.
    unrelated = [
        registry.async_get_or_create(
            platform,
            DOMAIN,
            f"{entry.entry_id}_pwm_1_maintenance_level",
            config_entry=entry,
        ),
        registry.async_get_or_create(
            "sensor", DOMAIN, f"{entry.entry_id}_pwm_4{suffix}", config_entry=entry
        ),
        registry.async_get_or_create(
            platform,
            "other_integration",
            f"{entry.entry_id}_pwm_4{suffix}",
            config_entry=entry,
        ),
    ]
    other = MockConfigEntry(domain=DOMAIN, entry_id="other_controller")
    other.add_to_hass(hass)
    unrelated.append(
        registry.async_get_or_create(
            platform, DOMAIN, f"{other.entry_id}_pwm_4{suffix}", config_entry=other
        )
    )
    captured = _capture_listener(coordinator)
    added: list[Entity] = []
    await setup(hass, entry, collect_entities(added))
    assert registry.async_get(obsolete.entity_id) is None
    assert registry.async_get(retained.entity_id) == retained
    assert all(registry.async_get(e.entity_id) == e for e in unrelated)
    assert sum(e.unique_id == retained.unique_id for e in added) == 1
    assert captured[0] is not None
    captured[0]()
    assert sum(e.unique_id == retained.unique_id for e in added) == 1


@pytest.mark.parametrize(
    "setup,platform,onoff",
    [(light_setup, "light", False), (switch_setup, "switch", True)],
)
async def test_channel_type_change_removes_previous_platform(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
    setup: Setup,
    platform: str,
    onoff: bool,
) -> None:
    """A light becoming a switch (or vice versa) retires its old entity."""
    entry = mock_config_entry
    entry.add_to_hass(hass)
    entry.runtime_data = coordinator
    coordinator.config["pwm#1#onoff"] = onoff
    captured = _capture_listener(coordinator)
    added: list[Entity] = []
    await setup(hass, entry, collect_entities(added))
    registry = entity_registry.async_get(hass)
    uid = f"{entry.entry_id}_pwm_1"
    old = registry.async_get_or_create(platform, DOMAIN, uid, config_entry=entry)
    coordinator.config["pwm#1#onoff"] = not onoff
    assert captured[0] is not None
    captured[0]()
    assert registry.async_get(old.entity_id) is None
