# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for diagnostics.py."""

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunriser.coordinator import SunRiserCoordinator
from custom_components.sunriser.diagnostics import async_get_config_entry_diagnostics
from tests.conftest import FAKE_CONFIG, FAKE_STATE, HOST


async def test_diagnostics_includes_coordinator_data(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Diagnostics must include coordinator config and state snapshots."""
    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert result["coordinator_config"] == FAKE_CONFIG
    assert result["coordinator_state"] == FAKE_STATE
    assert result["config_entry"][CONF_HOST] == HOST
    assert "last_update_success" in result
