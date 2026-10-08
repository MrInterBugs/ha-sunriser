# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for SunRiser button platform (reboot)."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity import Entity
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunriser.button import SunRiserRebootButton, async_setup_entry
from custom_components.sunriser.coordinator import SunRiserCoordinator
from tests.conftest import ENTRY_ID
from tests.typing import as_async_mock, collect_entities


def test_reboot_button_unique_id(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    button = SunRiserRebootButton(coordinator, mock_config_entry)
    assert button.unique_id == f"{ENTRY_ID}_reboot"


def test_reboot_button_name(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    button = SunRiserRebootButton(coordinator, mock_config_entry)
    assert button._attr_translation_key == "reboot"


async def test_reboot_button_press_calls_coordinator(
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    coordinator.async_reboot = AsyncMock()
    button = SunRiserRebootButton(coordinator, mock_config_entry)
    await button.async_press()
    as_async_mock(coordinator.async_reboot).assert_called_once()


@pytest.mark.parametrize("old_beta", [False, True])
async def test_async_setup_entry_adds_reboot_button(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
    old_beta: bool,
) -> None:
    """Setup keeps reboot and removes the obsolete beta resume registry entry."""
    mock_config_entry.add_to_hass(hass)
    registry = entity_registry.async_get(hass)
    obsolete_id = f"{mock_config_entry.entry_id}_resume_normal_operation"
    if old_beta:
        registry.async_get_or_create(
            "button", "sunriser", obsolete_id, config_entry=mock_config_entry
        )
    mock_config_entry.runtime_data = coordinator
    added: list[Entity] = []
    await async_setup_entry(hass, mock_config_entry, collect_entities(added))
    assert len(added) == 1
    assert isinstance(added[0], SunRiserRebootButton)
    assert registry.async_get_entity_id("button", "sunriser", obsolete_id) is None
